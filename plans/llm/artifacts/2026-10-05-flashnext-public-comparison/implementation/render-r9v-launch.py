import os,json,subprocess
from pathlib import Path
base=Path('/workspace/flashnext-competition');env=json.loads((base/'r9v-placement/env.json').read_text());stub=base/'r9v-render-bin';stub.mkdir(exist_ok=True)
(stub/'docker').write_text('''#!/usr/bin/env python3
import sys,json
from pathlib import Path
args=sys.argv[1:]
if args[:2]==['container','inspect']:sys.exit(1)
if args[:2]==['image','inspect']:print('sha256:2dac17a215fb5b0e3461e4c3e36a2981eec8ac3d6021e73183d247e819740c03')
elif args[0]=='info':print('[]')
elif args[0]=='run':Path('/workspace/flashnext-competition/r9v-placement/launch-args.json').write_text(json.dumps(args,indent=2));print('rendered-only')
else:sys.exit('unexpected Docker operation '+str(args))
''');(stub/'docker').chmod(0o755)
env.update(PATH=str(stub)+':'+os.environ['PATH'],R9V_PROFILE=str(base/'R9V/profiles/qwen38-flash-next/dual-r9700-mtp4/profile.env'),R9V_CACHE_NAMESPACE='iggy-wmma-r2')
subprocess.run(['bash',str(base/'R9V/scripts/launch.sh')],env={**os.environ,**env},check=True)
