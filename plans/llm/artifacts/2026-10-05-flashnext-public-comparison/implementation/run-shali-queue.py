import json,subprocess,time
from pathlib import Path
root=Path('/tmp/flashnext-competition')
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm']
t=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
while subprocess.run(k+['get','pod','flashnext-stew-q6-cache-rccl-loader'],capture_output=True).returncode == 0:
 time.sleep(15)
def clear():
 for _ in range(40):
  values=[int(subprocess.check_output(t+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
  if max(values)<256*1024*1024:return
  print('WAIT_VRAM_RELEASE',values,flush=True);time.sleep(3)
 raise RuntimeError('GPU allocation remained after previous pod deletion')
for profile in ('stew-q4-public-single-sdk10','stew-q4-public-mtp-sdk10'):
 clear()
 args=['/usr/bin/python3','-u',str(root/'run-profile.py'),str(root/(profile+'.json')),'--llama','--smoke','--protocols','decode,pp,common,c2']
 with (root/(profile+'-runner.log')).open('w') as f:
  result=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT)
 print('QUEUE_PROFILE_FINISHED',profile,result.returncode,flush=True)
 if result.returncode:break
