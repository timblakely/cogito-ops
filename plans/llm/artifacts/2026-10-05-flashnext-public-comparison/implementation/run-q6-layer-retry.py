"""Run the measured-fit layer retry only after the existing serial Q6 screens."""
import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');print('LAYER_RETRY_WAITING_FOR_EXISTING_Q6_CONTROLLER',flush=True)
while subprocess.run(['pgrep','-f',r'^/usr/bin/python3 -u /tmp/flashnext-competition/run-q6-final\.py$'],capture_output=True).returncode==0:time.sleep(15)
print('LAYER_RETRY_STARTING_SERIAL_SCREEN',flush=True)
with (r/'stew-q6-cache-layer-4k-loader-runner.log').open('w') as f:
 p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/'stew-q6-cache-layer-4k-loader.json'),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)
print('LAYER_RETRY_SCREEN_FINISHED',p.returncode,flush=True)
if p.returncode==0:
 name='stew-q6-cache-layer-4k-fast-first'
 with (r/(name+'-runner.log')).open('w') as f:
  p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)
 print('FAST_FIRST_LAYER_RETRY_FINISHED',p.returncode,flush=True)
else:print('FAST_FIRST_LAYER_RETRY_SKIPPED_AFTER_DEFAULT_FIT_FAILURE',flush=True)
name='stew-q6-all-cache-layer-4k-headroom'
with (r/(name+'-runner.log')).open('w') as f:
 p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)
print('ALL_CACHE_FIT_RETRY_FINISHED',p.returncode,flush=True);raise SystemExit(p.returncode)
