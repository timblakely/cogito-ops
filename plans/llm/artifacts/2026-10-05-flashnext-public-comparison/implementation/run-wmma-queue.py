import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition')
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-control-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
name='strata-public-dual-wmma'
with (r/(name+'-runner.log')).open('w') as f:p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--inside','--smoke','--protocols','decode,pp,common,c2'],stdout=f,stderr=subprocess.STDOUT)
print('WMMA_PROFILE_FINISHED',p.returncode,flush=True)
