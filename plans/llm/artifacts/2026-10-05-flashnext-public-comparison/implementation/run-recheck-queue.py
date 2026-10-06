import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition')
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-wmma-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
name='stew-q4-public-mtp-sdk10-pp-recheck'
with (r/(name+'-runner.log')).open('w') as f:p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--protocols','pp-recheck'],stdout=f,stderr=subprocess.STDOUT)
print('PP_RECHECK_FINISHED',p.returncode,flush=True)
