"""Run after public qualification; source originals are retained by NVMe preparation."""
import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm']
# Start this controller only once public LRU qualification has been reviewed.
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-public-retries.py$'],capture_output=True).returncode==0:time.sleep(15)
talos=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
for _ in range(40):
 used=[int(subprocess.check_output(talos+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
 if max(used)<256*1024*1024:break
 time.sleep(3)
else:raise SystemExit('VRAM not clear before Q6 storage promotion')
subprocess.run(k+['exec','-i','flashnext-davetha-stage','--','python3','-'],input=(r/'qualify-stew-runtimes.py').read_bytes(),check=True)
with (r/'q6-nvme-preparation.log').open('w') as f:subprocess.run(k+['exec','flashnext-davetha-stage','--','python3','/workspace/flashnext-competition/prepare-q6-nvme.py'],stdout=f,stderr=subprocess.STDOUT,check=True)
for name,protocols in [('stew-q6-cache-hybrid-replay','common,replay,c2'),('stew-q6-cache-pure-rccl-loader','common,replay,c2'),('stew-q6-cache-layer-wide-loader','common,replay,c2'),('stew-q6-all-cache-layer-wide-loader','common,replay,c2'),('stew-q6-classic-r15','common,replay,c2')]:
 if name=='stew-q6-all-cache-layer-wide-loader':
  talos=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
  mem=subprocess.check_output(talos+['read','/proc/meminfo'],text=True)
  available=int(next(line.split()[1] for line in mem.splitlines() if line.startswith('MemAvailable:')))*1024
  if available < 112*2**30:
   (r/(name+'-memory-screen-decision.json')).write_text(json.dumps({'decision':'skip larger host backing: insufficient node MemAvailable for 112 GiB guard','available_bytes':available,'meminfo':mem},indent=2)+'\n');print('Q6_ALL_CACHE_MEMORY_GUARD',available,flush=True);continue
 with (r/(name+'-runner.log')).open('w') as f:p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols',protocols],stdout=f,stderr=subprocess.STDOUT)
 print('Q6_FINAL_PROFILE_FINISHED',name,p.returncode,flush=True)
print('Q6_FINAL_SCREEN_COMPLETE',flush=True)
