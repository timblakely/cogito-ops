"""Index retained results without assigning model-quality equivalence."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();records=[]
for f in sorted(a.root.rglob('*.json')):
 if f.name=='index.json':continue
 data=f.read_bytes();j=json.loads(data)
 rec={'path':f.relative_to(a.root).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
 if isinstance(j,dict) and 'trials' in j:
  ts=j['trials'];rec.update(profile=j.get('profile'),protocol=j.get('protocol'),trials=len(ts),successful_trials=sum(t.get('ok',False) for t in ts),output_tokens=[t.get('usage',{}).get('completion_tokens') for t in ts])
  if j.get('protocol') in ('common','c2'):rec['all_reach_256']=bool(ts) and all(t.get('ok') and t.get('usage',{}).get('completion_tokens')==256 for t in ts)
 if isinstance(j,dict) and 'replays' in j:
  ts=j.get('initial_together',[])+[t for replay in j['replays'] for mode in ('alone','together') for t in replay[mode]]
  rec.update(profile=j.get('profile'),protocol='replay',trials=len(ts),successful_trials=sum(t.get('ok',False) for t in ts),output_tokens=[t.get('usage',{}).get('completion_tokens') for t in ts],phrase_repeat_counts=[t.get('repeated_records_phrase_count') for t in ts])
 if f.name.endswith('-smoke.json') and isinstance(j,list):rec['api_checks']={c.get('case',c.get('test')):c.get('passed',False) for c in j}
 records.append(rec)
(a.root/'index.json').write_text(json.dumps({'description':'Retained evidence, including failed starts and deliberately interrupted screens. Trial success is transport completion; qualification requires review of output, protocol coverage, placement and adaptation.','records':records},indent=2)+'\n')
print('INDEXED',len(records))
