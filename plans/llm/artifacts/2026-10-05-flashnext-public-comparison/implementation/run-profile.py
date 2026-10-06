"""Run one prepared private profile and retain all trials before cleanup."""
import argparse,json,subprocess,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--protocols',default='common,decode,pp,c2');p.add_argument('--repetitions',type=int,default=3);p.add_argument('--llama',action='store_true');p.add_argument('--inside',action='store_true');p.add_argument('--retain',action='store_true');p.add_argument('--existing',action='store_true');p.add_argument('--smoke',action='store_true');p.add_argument('--reset-prefix-cache',action='store_true');p.add_argument('--port',type=int,default=8080)
a=p.parse_args();j=json.loads(a.manifest.read_text());name=j['metadata']['name'];assert name.startswith('flashnext-');profile=name.removeprefix('flashnext-')
base=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm'];root=Path('/tmp/flashnext-competition');remote='/workspace/flashnext-competition';logs=root/(profile+'-campaign.log')
def call(args,**kwargs):
 return subprocess.run(base+args,check=True,**kwargs)
def capture(args):return subprocess.check_output(base+args)
def pause(mode):
 for pod in ('flashnext-iggy-stage','flashnext-r9v-stage','flashnext-davetha-stage','flashnext-public-download'):
  r=subprocess.run(base+['exec','-i',pod,'--','python3','-',mode],input=(root/'pause-staging.py').read_bytes(),capture_output=True)
  print(pod,mode,r.returncode,r.stdout.decode(),r.stderr.decode(),flush=True)
if not a.existing:
 assert j['spec']['nodeSelector']['kubernetes.io/hostname']=='iggy'
 talos=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13','-e','192.168.42.13']
 for _ in range(40):
  used=[int(subprocess.check_output(talos+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
  if max(used)<256*1024*1024:break
  print('WAIT_VRAM_RELEASE',profile,used,flush=True);time.sleep(3)
 else:raise SystemExit('Previous GPU allocations did not clear; refusing overlapping runtime')
 if profile in ('stew-q6-all-cache-layer-4k-headroom','stew-q6-all-cache-c1-reserve4-full'):
  mem=subprocess.check_output(talos+['read','/proc/meminfo'],text=True)
  available=int(next(line.split()[1] for line in mem.splitlines() if line.startswith('MemAvailable:')))*1024
  if available < 112*2**30:
   (root/(profile+'-memory-screen-decision.json')).write_text(json.dumps({'decision':'skip larger host backing: insufficient node MemAvailable for unchanged112GiB guard','available_bytes':available,'meminfo':mem},indent=2)+'\n')
   raise SystemExit('Insufficient available node RAM for larger Q6 backing; no Pod or measurement started')
 if profile.startswith('strata-'):
  call(['exec','flashnext-iggy-stage','--','python3',remote+'/install-strata-mmq.py'])
 call(['apply','-f',str(a.manifest)])
ready=False
for _ in range(160):
 state=json.loads(capture(['get','pod',name,'-o','json']))
 phase=state['status']['phase']
 if phase in ('Failed','Succeeded') or any(c.get('state',{}).get('terminated') for c in state['status'].get('containerStatuses',[])) or any(c.get('state',{}).get('terminated',{}).get('exitCode',0) for c in state['status'].get('initContainerStatuses',[])):break
 if a.inside:
  probe=subprocess.run(base+['exec',name,'--','python3','-c',f'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:{a.port}/health",timeout=2).status)'],capture_output=True)
  ready=probe.returncode==0
 else:ready=any(c.get('ready') for c in state['status'].get('containerStatuses',[]))
 if ready:break
 print('WAIT',profile,phase,flush=True);time.sleep(15)
if not ready:
 with (root/(profile+'-startup.log')).open('wb') as f:
  for container in state['spec'].get('initContainers',[])+state['spec']['containers']:
   f.write(('CONTAINER '+container['name']+'\n').encode());f.flush()
   subprocess.run(base+['logs',name,'-c',container['name']],stdout=f,stderr=subprocess.STDOUT)
 (root/(profile+'-failed-pod.json')).write_text(json.dumps(state,indent=2)+'\n')
 if not a.retain:call(['delete','pod',name,'--wait=true'])
 raise SystemExit('Profile did not become ready; startup log retained')
(root/(profile+'-ready-pod.json')).write_text(json.dumps(state,indent=2)+'\n')
for init in state['spec'].get('initContainers',[]):
 with (root/(profile+'-'+init['name']+'.log')).open('wb') as f:call(['logs',name,'-c',init['name']],stdout=f)
ip=state['status']['podIP'];endpoint=f'http://127.0.0.1:{a.port}' if a.inside else f'http://{ip}:{a.port}'
runner=name if a.inside else 'flashnext-iggy-stage';pause('pause');failure=0
try:
 with logs.open('w') as f:
  for protocol in a.protocols.split(','):
   args=['exec',runner,'--','python3',remote+'/flashnext_public_bench.py','--endpoint',endpoint,'--profile',profile,'--protocol',protocol,'--output',f'{remote}/results/{profile}-{protocol}.json','--thinking','default','--repetitions',str(1 if protocol=='c2' else a.repetitions)]
   if protocol=='lru-publisher-pp':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-lru-publisher-pp.py'
   if protocol=='pp-recheck':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-pp-recheck.py'
   if protocol=='replay':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-c2-replay.py'
   if protocol=='postpp-replay':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-c2-replay-postpp.py'
   if a.llama:args+=['--llama-cache-off']
   if a.reset_prefix_cache and protocol in ('common','c2'):args+=['--reset-prefix-cache']
   if protocol=='pp':args+=['--corpus',remote+'/aider-chat-history.md']
   r=subprocess.run(base+args,stdout=f,stderr=subprocess.STDOUT);f.flush()
   print('PROTOCOL',profile,protocol,'exit',r.returncode,flush=True)
   if r.returncode:failure=r.returncode;break
 if a.smoke:
  call(['exec',runner,'--','python3',remote+'/profile-smoke.py','--endpoint',endpoint,'--output',f'{remote}/results/{profile}-smoke.json'])
finally:
 pause('resume')
 with (root/(profile+'-runtime.log')).open('wb') as f:call(['logs',name],stdout=f)
 with (root/(profile+'-memory.json')).open('wb') as f:
  r=subprocess.run(base+['exec','-i',name,'--','python3','-'],input=(root/'runtime-memory.py').read_bytes(),stdout=f,stderr=subprocess.PIPE)
  if r.returncode:
   print('PYTHON_MEMORY_CAPTURE_UNAVAILABLE',r.stderr.decode(),flush=True)
   shell='for x in /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.stat /proc/1/status; do echo FILE:$x; cat "$x"; done; for d in /sys/bus/pci/devices/*; do if test -f "$d/mem_info_vram_total"; then echo GPU:$d; cat "$d/mem_info_vram_total" "$d/mem_info_vram_used" "$d/mem_info_gtt_used"; fi; done'
   with (root/(profile+'-memory-shell.txt')).open('wb') as fallback:
    subprocess.run(base+['exec',name,'--','/bin/sh','-c',shell],stdout=fallback,stderr=subprocess.STDOUT)

 if not a.retain:
  if a.llama:
   subprocess.run(base+['exec',name,'--','python3','-c','import os,signal; os.kill(1,signal.SIGTERM)'],capture_output=True)
   for _ in range(20):
    final=json.loads(capture(['get','pod',name,'-o','json']))
    if any(c.get('state',{}).get('terminated') for c in final['status'].get('containerStatuses',[])):break
    time.sleep(1)
   with (root/(profile+'-shutdown.log')).open('wb') as f:call(['logs',name],stdout=f)
  call(['delete','pod',name,'--wait=true'])
print('PROFILE_COMPLETE',profile,'benchmark_exit',failure,flush=True)
raise SystemExit(failure)
