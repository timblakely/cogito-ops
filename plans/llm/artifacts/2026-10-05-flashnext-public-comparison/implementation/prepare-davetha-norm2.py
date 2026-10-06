import json
from pathlib import Path
r=Path('/tmp/flashnext-competition');j=json.loads((r/'davetha-public-compat-cache-control.json').read_text());j['metadata']['name']='flashnext-davetha-public-compat-norm2'
c=j['spec']['containers'][0];next(e for e in c['env'] if e['name']=='VLLM_GEMMA_NORM_FUSED')['value']='2'
(r/'davetha-public-compat-norm2.json').write_text(json.dumps(j,indent=2)+'\n')
j['metadata']['name']='flashnext-davetha-norm2-probe';c['command']=['/bin/bash','-ec',c['command'][2].split('exec python3')[0]+'exec python3 /workspace/flashnext-competition/davetha-norm2-probe.py'];c.pop('args',None)
for key in ('readinessProbe','livenessProbe','startupProbe','ports'):c.pop(key,None)
c['resources']['requests']['memory']='8Gi';c['resources']['limits']['memory']='16Gi'
(r/'davetha-norm2-probe.json').write_text(json.dumps(j,indent=2)+'\n')
