"""Wait for the verified local runtime, then qualify the full public LRU setup."""
import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm']
for _ in range(100):
 ready=subprocess.run(k+['exec','flashnext-davetha-compat-stage','--','test','-f','/workspace/flashnext-competition/davetha-compat-local/COMPLETE'],capture_output=True)
 if ready.returncode==0:break
 time.sleep(15)
else:raise SystemExit('Local runtime verification did not complete; no model started')
print('DAVETHA_LOCAL_RUNTIME_QUALIFIED',flush=True)
with (r/'davetha-public-compat-native-local-runner.log').open('w') as f:ret=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/'davetha-public-compat-native-local.json'),'--port','8000','--reset-prefix-cache','--smoke','--protocols','decode,pp,common,c2'],stdout=f,stderr=subprocess.STDOUT)
print('DAVETHA_LOCAL_FULL_MODEL_FINISHED',ret.returncode,flush=True)
raise SystemExit(ret.returncode)
