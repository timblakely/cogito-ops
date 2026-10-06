"""Describe retained run coverage without equating request success with quality."""
import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();records={}
for f in sorted((a.root/'profiles').glob('*.json')):
 j=json.loads(f.read_text())
 if j.get('kind')!='Pod':continue
 name=j['metadata']['name'].removeprefix('flashnext-')
 records.setdefault(name,{'profile':name,'manifests':[],'protocols':{}})['manifests'].append(f.relative_to(a.root).as_posix())
for f in sorted((a.root/'results').glob('*.json')):
 j=json.loads(f.read_text())
 if not isinstance(j,dict) or not j.get('profile') or not j.get('protocol'):continue
 name=j['profile'];rec=records.setdefault(name,{'profile':name,'manifests':[],'protocols':{}})
 ts=j.get('trials',[])
 if j['protocol']=='replay':ts=j.get('initial_together',[])+[t for replay in j.get('replays',[]) for mode in ('alone','together') for t in replay[mode]]
 rec['protocols'][f.name]={'protocol':j['protocol'],'trials':len(ts),'successful_requests':sum(t.get('ok',False) for t in ts),'output_tokens':[t.get('usage',{}).get('completion_tokens') for t in ts],'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
for rec in records.values():
 name=rec['profile'];fail=a.root/'provenance'/(name+'-failed-pod.json');smoke=a.root/'results'/(name+'-smoke.json')
 rec['coverage']='measured' if rec['protocols'] else 'startup-failed' if fail.exists() else 'prepared; no retained performance trials'
 if smoke.exists():rec['api_probes']={c['case']:c.get('passed',False) for c in json.loads(smoke.read_text())}
 if fail.exists():rec['failed_start_record']=fail.relative_to(a.root).as_posix()
 canceled=a.root/'provenance'/(name+'-canceled-pod.json')
 if canceled.exists() and not rec['protocols']:
  rec['coverage']='cancelled during loading before measurement';rec['cancelled_load_record']=canceled.relative_to(a.root).as_posix()
(a.root/'campaign-coverage.json').write_text(json.dumps({'description':'Coverage only. Successful HTTP requests and output counts do not establish correctness, quality equivalence, or suitability for production. The report and explicit output reviews qualify recommendations. Prepared alternatives are included for reproducibility, not represented as measured results.','profiles':sorted(records.values(),key=lambda r:r['profile'])},indent=2)+'\n')
print('COVERAGE_PROFILES',len(records))
