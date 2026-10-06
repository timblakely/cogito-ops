"""Qualify the isolated RCCL loader before running the preserved public LRU model."""
import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm'];name='flashnext-davetha-probe-compat-deepbind'
for _ in range(100):
 state=json.loads(subprocess.check_output(k+['get','pod',name,'-o','json']))
 if state['status']['phase'] in ('Succeeded','Failed'):break
 time.sleep(3)
log=subprocess.check_output(k+['logs',name],text=True);(r/'davetha-probe-compat-deepbind-runtime.log').write_text(log);(r/'davetha-probe-compat-deepbind-result.json').write_text(json.dumps(state,indent=2)+'\n');subprocess.run(k+['delete','pod',name,'--wait=true'],check=True)
assert state['status']['phase']=='Succeeded',log[-4000:]
for rank in (0,1):
 assert f'ALLGATHER_GRAPH_PASS {rank}' in log
 for dim in (0,1,-1):assert f'COMMUNICATOR_ALLGATHER_PASS {rank} {dim}' in log
assert 'RCCL_PROBE_COMPLETE' in log
print('DAVETHA_DEEPBIND_GPU_QUALIFICATION_COMPLETE',flush=True)
with (r/'davetha-public-compat-deepbind-runner.log').open('w') as f:ret=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/'davetha-public-compat-deepbind.json'),'--port','8000','--reset-prefix-cache','--smoke','--protocols','decode,pp,common,c2'],stdout=f,stderr=subprocess.STDOUT)
print('DAVETHA_DEEPBIND_FULL_MODEL_FINISHED',ret.returncode,flush=True)
raise SystemExit(ret.returncode)
