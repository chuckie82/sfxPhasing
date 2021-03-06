from __future__ import print_function
import sys
import shutil
import subprocess
import os
import argparse
import re
import numpy as np
import json
import ast
import itertools

if os.path.isfile("final_result.txt"):
    os.remove("final_result.txt")



original_path = os.getcwd()
parser= argparse.ArgumentParser()

parser.add_argument("-rfl","--reflection-mtz", help="input the mtz file of reflection", type = str)
#parser.add_argument("-resl","--resolution", default = "2.5", help="define the resolution", type = str)
parser.add_argument("-pdb","--pdb-file", nargs='+', help="input the pdb file",type = str)
parser.add_argument("-seq","--sequence-file", nargs='+', help="input the sequence file",type = str)
parser.add_argument("-q", "--queue", help = "input the computing queue you want to use", type = str)
parser.add_argument("-n", "--number-of-cores", help = "input the number of core you want to use", type = str)
parser.add_argument("-res","--resolution_range", nargs = '+', help='input the range of the resolution range (optional)',type = str)
parser.add_argument("-rmsd","--rmsd_range", nargs = '+', help='input the range of the rmsd range. Default: 0.5 2.0 (optional)',type = str)
parser.add_argument("-Host","--host", help = 'must enter a host name, either type lcls or cori ',type = str)


args = parser.parse_args()

if args.reflection_mtz:
    rfl_file = args.reflection_mtz
else:
    print('The reflection file is missing')
    sys.exit()

if args.pdb_file:
     pdb_list= args.pdb_file
else:
    print('The pdb file is missing')
    sys.exit()

if args.sequence_file:
    seq_list = args.sequence_file
else:
    print('The sequence file is missing')
    sys.exit()
    
if args.queue:
    computeQueue = args.queue
else:
    print ('Please input the computing queue you want to use')
    sys.exit()
    
if args.number_of_cores:
    coreNumber = args.number_of_cores
else:
    print ('Please address the core number you want to use')
    sys.exit()
    
if len(pdb_list) != len(seq_list):
    print("Number of pdb files is different from the sequence files. Recheck the entering files")
    sys.exit()
    
if args.rmsd_range:
    rmsd_low = str(round(float(args.rmsd_range[0]),1))
    rmsd_high = str(round(float(args.rmsd_range[1]),1))
else:
    rmsd_low = str(0.5)
    rmsd_high = str(2.0)
    
if args.host == 'lcls':
    job_submitter = 'bsub'
    python_run = 'python'
    core_selector = ' -n '
elif args.host == 'cori':
    job_submitter = 'srun -A m3506 -C haswell'
    python_run = 'python2.7'
    core_selector = ' --cores-per-socket '
else:
    print ('You have to enter the host: either lcls or cori')
    sys.exit()

##Creating the user-defined range if any
def get_range(x,y):
    if x == y:
        return np.array([x])
    else:
        return np.arange(x,y+0.1,0.1)



component_num = len(pdb_list)

input_file = {}
for i in range(1,component_num+1):
    input_file['component'+str(i)] = {}
    input_file['component'+str(i)]={"pdb":pdb_list[i-1],"rmsd":rmsd_low+":"+rmsd_high,"seq":seq_list[i-1]}
    input_file['component number'] = component_num


with open('FILE_SETUP.json', 'w') as outfile:
    json.dump(input_file, outfile)
    
    
# Get resolution by extracting the highest resolution bound, say res_h, from the input mtz file
# Create the grid of [res_h, res_h+1.5) with interval of 0.1

# Using phenix.mtz.dump to read the reflection file 
print('Creating resolution scanning range ..........')
process = subprocess.Popen('phenix.mtz.dump '+rfl_file, 
                          stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,shell=True)

out,err = process.communicate()

split_out=out.splitlines()

for line in split_out:
    if 'Resolution range' in line.decode("utf-8"):
        resolution = round(float(line.decode("utf-8").split(' ')[-1]),1)

# Create the grid of resolution
if args.resolution_range:
    resolution_range = get_range(round(float(args.resolution_range[0]),1),round(float(args.resolution_range[1]),1))
else:
    resolution_range = []
    for i in np.arange(resolution, resolution+1.5, 0.1):
        resolution_range.append(round(i,1))

print('Creating rmsd scanning range')
rmsd_dict = {}
rmsd_list = []
with open('FILE_SETUP.json') as json_file:
    parameter = json.load(json_file)
    for i in range(1,component_num+1):
        start = round(float(parameter['component'+str(i)]["rmsd"].split(':')[0]),1)
        end = round(float(parameter['component'+str(i)]["rmsd"].split(':')[1]),1)
        if start == end:
            rmsd_dict['rmsd'+str(i)]=np.around(np.array([start]),1)
        else:
            rmsd_dict['rmsd'+str(i)]=np.around(np.arange(start,end,0.1),1)


##################################### Get request copy number range ############################################
# Create the number of reasonable request copies by using phenix.xtriage to read the reflection file and sequence file
# If the read Matthew Coefficient = m, the requested copy is [m-1, m+1] with interaval of 1.
# Data label is also read here. The idea is to open one file and extract as much information as possible

print("Creating guessed copy grid ...........")
asu_copy_dict = {}
for i in range(len(pdb_list)):
    process = subprocess.Popen('phenix.xtriage '+rfl_file+' '+ seq_list[i], 
                              stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,shell=True)

    out,err = process.communicate()

    split_out=out.splitlines()
    my_list=[]
    for j in range(len(split_out)):
        my_list.append(split_out[j].decode("utf-8"))

    for line in my_list:
        if 'Best guess' in line:
            string = line
            stoichiometry = int(re.findall('\d+', string )[0])
            #print(str(i+1))
            asu_copy_dict['component'+str(i+1)] = stoichiometry
        if "Data labels" in line:
            data_labels = line.split(':')[1].replace(' ','')

uncertainty = 1

max_overall_asu_count = max(list(asu_copy_dict.values()))+uncertainty
if (min(list(asu_copy_dict.values()))-uncertainty) == 0:
    min_overall_asu_count = 1
else:
    min_overall_asu_count = min(list(asu_copy_dict.values()))-uncertainty

total_request_copy_list = range(min_overall_asu_count,max_overall_asu_count+1)


for directory in os.listdir(os.getcwd()):
    if 'Request_' in directory:
        shutil.rmtree(directory)
        
###################################################################################################
print ("copy list:"+str(total_request_copy_list))
print ("rmsd range:"+str(rmsd_dict['rmsd1']))
print ("Resolution range:"+str(resolution_range))
###################################################################################################
if component_num == 1:
    rmsd_range = rmsd_dict['rmsd1']
#create each grid as a directory
    for i in total_request_copy_list:
        for j in rmsd_range:
            for k in resolution_range:
                directory = 'Request_'+str(i)+'_copy/rmsd'+str(j)+'/resolution'+str(k)
                os.system('mkdir -p '+directory)
                os.system('cp MR_pip.py'+' '+rfl_file+' '+pdb_list[0]+' '+seq_list[0]+' '+'FILE_SETUP.json'+' '+directory)
                os.chdir("./"+directory)
                os.system(job_submitter+' -q '+computeQueue+core_selector+coreNumber+' -o %J.log '+python_run+' MR_pip.py -rfl '+rfl_file+' -pdbE1 '+pdb_list[0]+' -seq1 '+seq_list[0]+' -idenE1 '+str(j)+' -errtE1 rmsd -c '+str(i)+' -res '+str(k)+' -labin '+data_labels+' -P '+original_path+' -cpus '+coreNumber)
                os.chdir("../../..")

    

elif component_num > 1:
    rmsd_permutation = []
    for m in itertools.product(*rmsd_dict.values()):
        rmsd_permutation.append(m)
        
    folder_list = []

    for p in rmsd_permutation:
        folder = 'rmsd'
        for q in range(2):
            folder += str(p[q])+'_'
                
        folder_list.append(folder)
    
    
    for i in total_request_copy_list:
        print("creating file"+str(i))
        for j in range(len(rmsd_permutation)):
            for k in resolution_range:
                directory = 'Request_'+str(i)+'_copy/'+folder_list[j]+'/resolution'+str(k)
                
                os.system('mkdir -p '+directory)
                
                cl = ''
                for t in range(1,component_num+1):
                    os.system('cp MR_pip.py'+' '+rfl_file+' '+pdb_list[t-1]+' '+seq_list[t-1]+' '+'FILE_SETUP.json '+' '+directory)
                    
                    cl += '-pdbE'+str(t)+' '+pdb_list[t-1]+' '+'-seq'+str(t)+ \
                    ' '+seq_list[t-1]+' '+'-idenE'+str(t)+' '+str(rmsd_permutation[j][t-1])+ \
                    ' '+'-errtE'+str(t)+' rmsd '  
                os.chdir("./"+directory)
                f = open("output.txt", "a")

                #print(cl+' -c '+str(i)+' -res '+str(k)+' -labin '+data_labels)
                os.system(job_submitter+' -q '+computeQueue+core_selector+coreNumber+' -o %J.log '+python_run+' MR_pip.py -rfl '+rfl_file+' '+cl+' -c '+str(i)+' -res '+str(k)+' -labin '+data_labels+' -P '+original_path+' -cpus '+coreNumber)
                os.chdir("../../..")
