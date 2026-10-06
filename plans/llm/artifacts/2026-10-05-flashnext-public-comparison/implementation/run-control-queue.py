import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition')
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-final-public-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
for name,protocols in [('stew-q4-baseline-pp','pp'),('stew-q4-mtp-control','decode,pp,common')]:
 with (r/(name+'-runner.log')).open('w') as f:p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols',protocols],stdout=f,stderr=subprocess.STDOUT)
 print('CONTROL_PROFILE_FINISHED',name,p.returncode,flush=True)
print('CONTROL_QUEUE_COMPLETE',flush=True)
