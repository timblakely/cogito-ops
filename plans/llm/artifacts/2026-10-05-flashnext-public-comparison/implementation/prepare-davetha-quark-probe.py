import json
from pathlib import Path
r=Path('/tmp/flashnext-competition')
j=json.loads((r/'davetha-public-compat-preserved-r4d.json').read_text())
bootstrap='if test -d /opt/vllm/lib/python3.12/site-packages/aiter; then mv /opt/vllm/lib/python3.12/site-packages/aiter /tmp/flashnext-disabled-base-aiter; fi\n'
c=j['spec']['containers'][0]
c['command'][2]=bootstrap+c['command'][2]
j['metadata']['name']='flashnext-davetha-public-compat-quark'
(r/'davetha-public-compat-quark.json').write_text(json.dumps(j,indent=2)+'\n')
j['metadata']['name']='flashnext-davetha-quark-probe'
c['command']=['/bin/bash','-ec',bootstrap+'exec python3 /workspace/flashnext-competition/davetha-quark-probe.py']
c.pop('args',None)
for key in ('readinessProbe','livenessProbe','startupProbe','ports'):c.pop(key,None)
c['resources']['requests']['memory']='8Gi'
c['resources']['limits']['memory']='16Gi'
(r/'davetha-quark-probe.json').write_text(json.dumps(j,indent=2)+'\n')
