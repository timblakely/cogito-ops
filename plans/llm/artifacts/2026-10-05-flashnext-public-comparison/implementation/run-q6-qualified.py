"""Serial final coverage; retain Pods until explicit output review and removal."""
import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition')
while subprocess.run(['pgrep','-f',r'^/usr/bin/python3 -u /tmp/flashnext-competition/run-q6-host-map\.py$'],capture_output=True).returncode==0:time.sleep(15)
for name,protocols in [('stew-q6-all-cache-c1-reserve4-full','common,decode,pp'),('stew-q6-classic-r15-full-qualification','decode,pp,postpp-replay')]:
 print('FINAL_QUALIFICATION_START',name,flush=True)
 with (r/(name+'-runner.log')).open('w') as f:
  p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--retain','--protocols',protocols],stdout=f,stderr=subprocess.STDOUT)
 print('FINAL_QUALIFICATION_FINISHED',name,p.returncode,flush=True)
 marker=r/(name+'-reviewed-and-removed.json')
 while not marker.exists():time.sleep(15)
 proof=json.loads(marker.read_text());assert proof['pod_removed'] is True and proof['profile']==name
 print('FINAL_QUALIFICATION_REVIEW_ACKNOWLEDGED',name,proof.get('qualified'),flush=True)
print('Q6_FINAL_QUALIFICATION_CONTROLLER_COMPLETE',flush=True)
