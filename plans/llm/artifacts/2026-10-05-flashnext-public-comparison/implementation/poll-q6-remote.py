import json,subprocess
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','--request-timeout=10s','-n','llm']
code='''from pathlib import Path
r=Path('/workspace/flashnext-competition/results')
for name in ('q6-detached-final-controller-state.json','stew-q6-classic-r15-full-qualification-detached-protocol.log','q6-detached-final-controller.log'):
 p=r/name
 print('REMOTE_FILE',name)
 if p.exists():print(p.read_text() if p.suffix=='.json' else '\\n'.join(p.read_text().splitlines()[-6:]))
'''
print(subprocess.check_output(k+['exec','flashnext-iggy-stage','--','python3','-c',code],timeout=20,text=True))
