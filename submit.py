#!/usr/bin/env python
from __future__ import absolute_import, division, print_function

import os
import sys
import time
import platform
import subprocess
import logging
import tempfile

class Submit(object):
    """
    Base class for the submit classes
    Mostly to provide future expansion for common functions
    """
    def __init__(self, config):
        self.config = config

    def submit(self):
        pass
    
    def write_line(self, file, line):
        file.write(line+"\n")


class SubmitPBS(Submit):
    def __init__(self, config):
        """
        Initialize
        
        Args:
            config: cluster config dict for cluster
        """
        self.config = config
        
    def write_general_header(self, file, mem = 3000, wall_time_hours = 14, 
                             num_nodes = 1, num_cpus = 2, num_gpus = 0):
        """
        Writing the header for a PBS submission script.
        Most of the pieces needed to tell PBS what resources
        are being requested.
        
        Args:
            file: python file object
            mem: requested memory
            wall_time_hours: requested wall time
            num_nodes: requested number of nodes
            num_cpus: requested number of cpus
            num_gpus: requested number of gpus
        """
        self.write_line(file, "#!/bin/bash")
        # Add the necessary gpu request tag if we need gpus.
        if num_gpus == 0:
            self.write_line(file, "#PBS -l nodes=%d:ppn=%d" %\
                            (num_nodes, num_cpus))
        else:
            self.write_line(file, "#PBS -l nodes=%d:ppn=%d:gpus=%d" %\
                            (num_nodes, num_cpus, num_gpus))
        # Definition of requested memory changes depending on gpu and cpu job
        # It is easier to request more cpus rather than more memory on PBS
        if num_gpus == 0:
            self.write_line(file, "#PBS -l mem=%dmb,pmem=%dmb" %\
                            (mem / num_cpus, mem / num_cpus))
        else:
            # Need to accomodate the PBS base 10 vs. HTCondor base 2 requests. 
            # Increase memory by 10% for gpu jobs to make simprod happy.
            self.write_line(file, "#PBS -l mem=%dmb,pmem=%dmb" %\
                            ((mem / num_cpus)*1.1, (mem / num_cpus)*1.1))
        self.write_line(file, "#PBS -l walltime=%d:00:00" % wall_time_hours)
        self.write_line(file, "#PBS -o $HOME/glidein/out/${PBS_JOBID}.out")
        self.write_line(file, "#PBS -e $HOME/glidein/out/${PBS_JOBID}.err")
    
    def write_cluster_specific(self, file, cluster_specific):
        """
        Writing the cluster specific pieces provided by 
        config file.
        
        Args:
            file: python file object
            cluster_specific: string of cluster specific things
        """
        self.write_line(file, cluster_specific + "\n")
    
    def write_glidein_variables(self, file, mem, num_cpus, has_cvmfs, num_gpus = 0):
        """
        Writing the header for a PBS submission script.
        Most of the pieces needed to tell PBS what resources
        are being requested.
        
        Args:
            file: python file object
            mem: memory provided for glidein
            has_cvmfs: whether cvmfs is present
            num_cpus: number of cpus provided 
            num_gpus: number of cpus provided
        """
        # Accomodating some extra ram requests
        if num_gpus != 0:
            self.write_line(file, "export MEMORY=%d" % int(mem*1.1))
        else:
            self.write_line(file, "export MEMORY=%d" % mem)
        self.write_line(file, "export CPUS=%d" % num_cpus)
        # Hack around parsing the $CUDA_VISIBLE_DEVICES on PBS clusters
        # Without the extra "CUDA" part on 'export GPUS`, the variable is not
        # parsed properly by HTCondor
        # 99.9% of times number of gpus == 1. 
        if num_gpus != 0:
            self.write_line(file, "export GPUS=$CUDA_VISIBLE_DEVICES")
            self.write_line(file, "export GPUS=\"CUDA$GPUS\"")
        self.write_line(file, "export CVMFS=%s\n" % has_cvmfs)
        
    def write_glidin_part(self, file, local_dir = None, glidein_tarball = None, glidein_script = None, glidein_loc = None):
        """
        Writing the pieces needed to execute the glidein 
        
        Args:
            file: python file object
            local_dir: what is the local directory
            glidein_loc: directory of the glidein pieces 
            glidein_tarball: file name of tarball
            glidein_script: file name of glidein start script
        """
        self.write_line(file, "cd %s\n" % local_dir)
        if glidein_tarball:
            self.write_line(file, "ln -s %s %s" % (os.path.join(glidein_loc, glidein_tarball), glidein_tarball))
        self.write_line(file, 'ln -s %s %s' % (os.path.join(glidein_loc, glidein_script), glidein_script))
        self.write_line(file, './%s' % glidein_script)

    def write_submit_file(self, filename, state):
        """
        Writing the PBS submit file
        
        Args:
            filename: name of PBS script to create
            state: what resource requirements a given glidein has
        """
        with open(filename,'w') as f:
            num_cpus = state["cpus"]
            # It is easier to request more cpus rather than more memory on PBS
            # Makes scheduling easier
            if state["gpus"] == 0:
                while state["memory"] > (self.config["Cluster"]["mem_per_core"]*num_cpus):
                    num_cpus += 1
            # Correcting memory whether not we have gpus
            if state["gpus"] > 0:
                mem = state["memory"]
            elif num_cpus*self.config["Cluster"]["mem_per_core"] >= state["memory"]:
                mem = num_cpus*self.config["Cluster"]["mem_per_core"]
                
            self.write_general_header(f, mem = mem, 
                                      wall_time_hours = self.config["Cluster"]["walltime_hrs"],
                                      num_cpus = num_cpus, num_gpus = state["gpus"])
            if "custom_header" in self.config["SubmitFile"]:
                self.write_cluster_specific(f, self.config["SubmitFile"]["custom_header"])
            if "custom_middle" in self.config["SubmitFile"]:
                self.write_cluster_specific(f, self.config["SubmitFile"]["custom_middle"])
            
            self.write_glidein_variables(f, mem = mem,
                                         num_cpus = state["cpus"], has_cvmfs = state["cvmfs"], 
                                         num_gpus = state["gpus"])
            if "tarball" in self.config["Glidein"]:
                self.write_glidin_part(f, local_dir = self.config["SubmitFile"]["local_dir"], 
                                       glidein_loc = self.config["Glidein"]["loc"], 
                                       glidein_tarball = self.config["Glidein"]["tarball"], 
                                       glidein_script = self.config["Glidein"]["executable"])
            else:
                self.write_glidin_part(f, local_dir = self.config["SubmitFile"]["local_dir"], 
                                       glidein_loc = self.config["Glidein"]["loc"], 
                                       glidein_script = self.config["Glidein"]["executable"])
            if "custom_end" in self.config["SubmitFile"]:
                self.write_cluster_specific(f, self.config["SubmitFile"]["custom_end"])
            
    def submit(self, state):
        """
        Submitting the PBS script
        
        Args:
            state: what resource requirements a given glidein has
        """
        logging.basicConfig(level=logging.INFO)
        # (options,args) = glidein_parser()

        filename = self.config["SubmitFile"]["filename"]
        
        self.write_submit_file(filename, state)

        cmd = self.config["Cluster"]["submit_command"] + " " + filename
        print(cmd)
        if subprocess.call(cmd,shell=True):
            raise Exception('failed to launch glidein')

class SubmitCondor(Submit):
    def __init__(self, config):
        """
        Initialize
        
        Args:
            config: cluster config dict for cluster
        """
        self.config = config
        
    def make_env_wrapper(self, env_wrapper):
        """
        Creating wrapper execute script for 
        HTCondor submit file
        
        Args:
            env_wrapper: name of wrapper script
        """
        with open(env_wrapper,'w') as f:
            self.write_line(f, '#!/bin/sh')
            self.write_line(f, 'CPUS=$(grep -e "^Cpus" $_CONDOR_MACHINE_AD|awk -F "= " "{print \\$2}")')
            self.write_line(f, 'MEMORY=$(grep -e "^Memory" $_CONDOR_MACHINE_AD|awk -F "= " "{print \\$2}")')
            self.write_line(f, 'DISK=$(grep -e "^Disk" $_CONDOR_MACHINE_AD|awk -F "= " "{print \\$2}")')
            self.write_line(f, 'GPUS=$(grep -e "^AssignedGPUs" $_CONDOR_MACHINE_AD|awk -F "= " "{print \\$2}"|sed "s/\\"//g")')
            self.write_line(f, 'if ( [ -z $GPUS ] && [ ! -z $CUDA_VISIBLE_DEVICES ] ); then')
            self.write_line(f, '  GPUS=$CUDA_VISIBLE_DEVICES')
            self.write_line(f, 'fi')
            self.write_line(f, 'GPUS_NO_DIGITS=$(echo $GPUS | sed \'s/[0-9]*//g\')')
            self.write_line(f, 'if [ "${GPUS_NO_DIGITS}" = "${GPUS}" ]; then')
            self.write_line(f, '    GPUS=""')
            self.write_line(f, 'elif [ -z $GPUS_NO_DIGITS ]; then')
            self.write_line(f, '    GPUS="CUDA${GPUS}"')
            self.write_line(f, 'fi')
            self.write_line(f, 'if ( [ -z $GPUS ] || [ "$GPUS" = "10000" ] || [ "$GPUS" = "CUDA10000" ] ); then')
            self.write_line(f, '  GPUS=0')
            self.write_line(f, 'fi')
            f.write('env -i CPUS=$CPUS GPUS=$GPUS MEMORY=$MEMORY DISK=$DISK ')
            if "CustomEnv" in self.config:
                for k,v in self.config["CustomEnv"].items():
                    f.write(k + '=' + v + ' ')
            f.write('%s' % self.config["Glidein"]["executable"])
        
            mode = os.fstat(f.fileno()).st_mode
            mode |= 0o111
            os.fchmod(f.fileno(), mode & 0o7777)

    # def make_submit_file_custom(self, file):
    #     pass
    
    def make_submit_file(self, filename, env_wrapper, state):
        """
        Creating HTCondor submit file
        
        Args:
            filename: name of HTCondor submit file
            env_wrapper: name of wrapper script
            state: what resource requirements a given glidein has
        """
        with open(filename,'w') as f:
            if "custom_header" in self.config["SubmitFile"]:
                f.write(self.config["SubmitFile"]["custom_header"])
            self.write_line(f, "output = /dev/null")
            self.write_line(f, "error = /dev/null")
            self.write_line(f, "log = log")
            self.write_line(f, "notification = never")
            self.write_line(f, "should_transfer_files = YES")
            self.write_line(f, "when_to_transfer_output = ON_EXIT")
            self.write_line(f, "")
            self.write_line(f, "executable = %s" % env_wrapper)
            self.write_line(f, "+TransferOutput=\"\"")
            if os.path.isfile(self.config["Glidein"]["executable"]):
                f.write("transfer_input_files = %s" % self.config["Glidein"]["executable"]) 
            else:
                raise Exception("no executable provided")
            if "tarball" in self.config["Glidein"]:
                if os.path.isfile(self.config["Glidein"]["tarball"]):
                    f.write(','+path)
                else:
                    raise Exception("provided tarball does not exist")
            f.write('\n')
            if "custom_body" in self.config["SubmitFile"]:
                f.write(self.config["SubmitFile"]["custom_body"])
            f.write('\n')
        
            if state["cpus"] != 0:
                self.write_line(f, 'request_cpus=%d' % state["cpus"])
            if state["memory"] != 0:
                self.write_line(f, 'request_memory=%d' % int(state["memory"]*1.1))
            if state["disk"] != 0:
                self.write_line(f, 'request_disk=%d' % int(state["disk"]*1024*1.1))
            if state["gpus"] != 0:
                self.write_line(f, 'request_gpus=%d' % int(state["gpus"]))
            # self.make_submit_file_custom(f)
            if "custom_footer" in self.config["SubmitFile"]:
                f.write(self.config["SubmitFile"]["custom_footer"])
            f.write('queue')
    
    def submit(self, state):
        logging.basicConfig(level=logging.INFO)
        # (options,args) = glidein_parser()
        
        self.make_env_wrapper(self.config["SubmitFile"]["env_wrapper_name"])
        self.make_submit_file(self.config["SubmitFile"]["filename"],
                              self.config["SubmitFile"]["env_wrapper_name"],
                              state)
                              
        cmd = self.config["Cluster"]["submit_command"] + " " + self.config["SubmitFile"]["filename"]
        print(cmd)
        if subprocess.call(cmd,shell=True):
            raise Exception('failed to launch glidein')