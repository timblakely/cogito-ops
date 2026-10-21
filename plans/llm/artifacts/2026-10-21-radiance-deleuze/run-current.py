import subprocess,sys,json
from pathlib import Path
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server=https://192.168.42.13:6443','--request-timeout=20s','-n','llm']
r=Path(__file__).resolve().parent
profile=sys.argv[1]
subprocess.run(k+['delete','pod','radiance-bench-current','--ignore-not-found=true','--wait=true'],check=True)
subprocess.run(k+['apply','-f',str(r/'profiles'/(profile+'.json'))],check=True)
subprocess.run(k+['wait','--for=condition=Ready','pod/radiance-bench-current','--timeout=8m'],check=True)
subprocess.run([sys.executable,str(r/'run-profile.py'),'--pod','radiance-bench-current','--profile',profile,*sys.argv[2:]],check=True)
