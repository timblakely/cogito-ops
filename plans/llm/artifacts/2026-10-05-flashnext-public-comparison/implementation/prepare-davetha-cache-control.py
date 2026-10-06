import json
from pathlib import Path
r=Path('/tmp/flashnext-competition');j=json.loads((r/'davetha-public-compat-quark.json').read_text());j['metadata']['name']='flashnext-davetha-public-compat-cache-control';c=j['spec']['containers'][0];c['env'].append({'name':'VLLM_SERVER_DEV_MODE','value':'1'});(r/'davetha-public-compat-cache-control.json').write_text(json.dumps(j,indent=2)+'\n')
j['metadata']['name']='flashnext-davetha-cache-route-probe';c['command']=['/bin/bash','-ec',c['command'][2].split('exec python3')[0]+'exec python3 /workspace/flashnext-competition/davetha-cache-route-probe.py'];c.pop('args',None)
for key in ('readinessProbe','livenessProbe','startupProbe','ports'):c.pop(key,None)
c['resources']={'requests':{'cpu':'1','memory':'2Gi'},'limits':{'memory':'8Gi'}}
(r/'davetha-cache-route-probe.json').write_text(json.dumps(j,indent=2)+'\n')
