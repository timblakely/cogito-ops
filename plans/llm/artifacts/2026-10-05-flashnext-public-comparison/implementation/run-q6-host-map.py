"""Serial documented eager-host cache control after observed C2 failures."""
import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');print('HOST_MAP_WAITING_FOR_RETRY_CONTROLLER',flush=True)
while subprocess.run(['pgrep','-f',r'^/usr/bin/python3 -u /tmp/flashnext-competition/run-q6-layer-retry\.py$'],capture_output=True).returncode==0:time.sleep(15)
name='stew-q6-cache-layer-4k-host-map';print('HOST_MAP_STARTING_SERIAL_SCREEN',flush=True)
with (r/(name+'-runner.log')).open('w') as f:
 p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)
print('HOST_MAP_SCREEN_FINISHED',p.returncode,flush=True);raise SystemExit(p.returncode)
