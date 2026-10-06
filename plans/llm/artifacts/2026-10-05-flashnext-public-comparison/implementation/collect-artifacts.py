"""Snapshot the private campaign's JSON records and local qualification evidence."""
import argparse,json,shutil,subprocess,tarfile,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
r=Path('/tmp/flashnext-competition');dst=a.destination;dst.mkdir(parents=True,exist_ok=True)
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm']
export='''import sys,tarfile
from pathlib import Path
r=Path('/workspace/flashnext-competition/results')
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as t:
 for pattern in ('*.json','*-engine.log','*detached*.log'):
  for f in sorted(r.glob(pattern)):t.add(f,arcname=f.name,recursive=False)
'''
with tempfile.TemporaryFile() as f:
 subprocess.run(k+['exec','flashnext-iggy-stage','--','python3','-c',export],stdout=f,check=True);f.seek(0)
 with tarfile.open(fileobj=f,mode='r:gz') as t:
  for m in t:
   assert m.isfile() and Path(m.name).name==m.name and (m.name.endswith('.json') or m.name.endswith('-engine.log') or (m.name.endswith('.log') and 'detached' in m.name)),m.name
   data=t.extractfile(m).read()
   if m.name.endswith('.json'):json.loads(data)
   target=dst/('results' if m.name.endswith('.json') else 'provenance')/m.name;target.parent.mkdir(exist_ok=True);target.write_bytes(data)
for f in r.glob('*'):
 if f.is_file() and f.suffix in ('.py','.sh','.patch','.c','.cpp','.hip','.jinja') and f.name != 'stew-loader-llama-model.cpp':
  target=dst/'implementation'/f.name;target.parent.mkdir(exist_ok=True);shutil.copy2(f,target)
 if f.is_file() and any(f.name.endswith(x) for x in ('-runner.log','-startup.log','-runtime.log','-shutdown.log','-memory.json','-memory-shell.txt','-numerical-qualification.log','-failed-pod.json','-ready-pod.json')):
  target=dst/'provenance'/f.name;target.parent.mkdir(exist_ok=True)
  if f.suffix=='.json' and not f.stat().st_size:
   if target.exists():target.unlink()
   continue
  shutil.copy2(f,target)
print('ARTIFACT_SNAPSHOT',len(list((dst/'results').glob('*.json'))),flush=True)
