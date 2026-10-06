import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm'];t=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-peer-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
def clear():
 for _ in range(40):
  used=[int(subprocess.check_output(t+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
  if max(used)<256*1024*1024:return
  time.sleep(3)
 raise RuntimeError('VRAM not clear')
clear();subprocess.run(k+['apply','-f',str(r/'davetha-probe.json')],check=True)
state={}
for _ in range(100):
 state=json.loads(subprocess.check_output(k+['get','pod','flashnext-davetha-probe','-o','json']))
 if state['status']['phase'] in ('Succeeded','Failed'):break
 time.sleep(5)
else:
 (r/'davetha-probe-timeout.json').write_text(json.dumps(state,indent=2)+'\n')
with (r/'davetha-probe-runtime.log').open('wb') as f:subprocess.run(k+['logs','flashnext-davetha-probe'],stdout=f,check=True)
(r/'davetha-probe-result.json').write_text(json.dumps(state,indent=2)+'\n')
subprocess.run(k+['delete','pod','flashnext-davetha-probe','--wait=true'],check=True)
if state.get('status',{}).get('phase')=='Succeeded':
 with (r/'davetha-public-runner.log').open('w') as f:ret=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/'davetha-public.json'),'--port','8000','--reset-prefix-cache','--smoke','--protocols','decode,pp,common,c2'],stdout=f,stderr=subprocess.STDOUT)
 print('DAVETHA_PUBLIC_FINISHED',ret.returncode,flush=True)
else:print('DAVETHA_GPU_PROBE_FAILED',flush=True)
for name,protocols,llama in [('stew-q4-cache-rccl','common',True),('stew-q4-cache-layer-none','common',True),('radiance-1013-c2','common,c2',False)]:
 args=['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--smoke','--protocols',protocols]
 if llama:args+=['--llama']
 with (r/(name+'-runner.log')).open('w') as f:ret=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT)
 print('FINAL_PUBLIC_PROFILE_FINISHED',name,ret.returncode,flush=True)
print('FINAL_PUBLIC_QUEUE_COMPLETE',flush=True)
