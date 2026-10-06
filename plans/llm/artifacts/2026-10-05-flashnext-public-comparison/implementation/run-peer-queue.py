import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm']
# Shali's controller holds the devices until both profiles finish.
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-shali-queue.py$'],capture_output=True).returncode==0:time.sleep(15)
for name,inside in [('john-iq3-layer-plain',False),('john-iq3-layer-mtp',False),('strata-public-single',True),('strata-public-dual',True)]:
 args=['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--smoke','--protocols','decode,pp,common,c2']
 if inside:args+=['--inside']
 else:args+=['--llama']
 with (r/(name+'-runner.log')).open('w') as f:p=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT)
 print('PEER_PROFILE_FINISHED',name,p.returncode,flush=True)
 # Preserve each independent failure and keep testing the other engines.
print('PEER_QUEUE_COMPLETE',flush=True)
