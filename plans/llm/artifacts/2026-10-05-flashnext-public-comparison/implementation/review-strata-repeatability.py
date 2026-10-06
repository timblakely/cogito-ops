"""Retain repeatability evidence; differing greedy text is not a quality verdict."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();proof={'description':'Observed repeatability on identical raw prompts at temperature zero and seed7; differing text is not automatically classified as corruption. Frontend sampling_keys omits zero temperature and engine per-request default req_temperature=0.0.','profiles':{}}
for name in ['strata-public-single-header-retry','strata-public-dual-header-retry','strata-public-dual-wmma']:
 f=a.root/'results'/(name+'-decode.json')
 if not f.exists():continue
 data=f.read_bytes();j=json.loads(data);groups={}
 for case in ['prose','JSON','code']:
  ts=[t for t in j['trials'] if t['label'].startswith(case+'-')]
  if not ts:continue
  assert len(set(t['prompt_sha256'] for t in ts))==1
  assert all(t['payload_settings']['temperature']==0 and t['payload_settings']['seed']==7 for t in ts)
  groups[case]={'prompt_sha256':[t['prompt_sha256'] for t in ts],'output_tokens':[t.get('usage',{}).get('completion_tokens') for t in ts],'text_sha256':[hashlib.sha256(t.get('text','').encode()).hexdigest() for t in ts],'draft_accepted_offered':[[t.get('after',{}).get('stats',{}).get('last',{}).get(k) for k in ['drafts_accepted','drafts_offered']] for t in ts]}
 proof['profiles'][name]={'source_file':f.name,'source_sha256':hashlib.sha256(data).hexdigest(),'groups':groups}
(a.root/'provenance/strata-output-repeatability.json').write_text(json.dumps(proof,indent=2)+'\n')
print('STRATA_REPEATABILITY_PROFILES',len(proof['profiles']))
