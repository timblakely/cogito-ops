"""Retry demonstrated public-profile failures serially before Q6 storage promotion."""
import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm'];t=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-recheck-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
for name,inside in [('john-iq3-layer-mtp-balanced',False),('strata-public-single-header-retry',True),('strata-public-dual-header-retry',True)]:
 args=['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--smoke','--protocols','decode,pp,common,c2']+(['--inside'] if inside else ['--llama'])
 with (r/(name+'-runner.log')).open('w') as f:ret=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT)
 print('PUBLIC_RETRY_FINISHED',name,ret.returncode,flush=True)
for _ in range(40):
 used=[int(subprocess.check_output(t+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
 if max(used)<256*1024*1024:break
 time.sleep(3)
else:raise SystemExit('VRAM not clear')
name='flashnext-davetha-probe-compat-retry';subprocess.run(k+['apply','-f',str(r/'davetha-probe-compat-retry.json')],check=True)
for _ in range(100):
 state=json.loads(subprocess.check_output(k+['get','pod',name,'-o','json']))
 if state['status']['phase'] in ('Succeeded','Failed'):break
 time.sleep(5)
with (r/'davetha-probe-compat-retry-runtime.log').open('wb') as f:subprocess.run(k+['logs',name],stdout=f,stderr=subprocess.STDOUT)
(r/'davetha-probe-compat-retry-result.json').write_text(json.dumps(state,indent=2)+'\n');subprocess.run(k+['delete','pod',name,'--wait=true'],check=True)
if state['status']['phase']=='Succeeded':
 with (r/'davetha-public-compat-retry-runner.log').open('w') as f:ret=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/'davetha-public-compat-retry.json'),'--port','8000','--reset-prefix-cache','--smoke','--protocols','decode,pp,common,c2'],stdout=f,stderr=subprocess.STDOUT)
 print('DAVETHA_COMPAT_FULL_MODEL_FINISHED',ret.returncode,flush=True)
else:print('DAVETHA_COMPAT_GPU_PROBE_FAILED',flush=True)
print('PUBLIC_RETRIES_COMPLETE',flush=True)
