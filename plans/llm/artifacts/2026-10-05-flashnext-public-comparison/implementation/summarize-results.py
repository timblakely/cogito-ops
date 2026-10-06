"""Summarize retained trials without treating partial runs or EOS as full-cap rates."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
for path in sorted(a.directory.glob('*.json')):
 j=json.loads(path.read_text())
 if not isinstance(j,dict) or not j.get('trials'):continue
 groups={}
 for t in j['trials']:
  label=t['label'];label=label.rsplit('-',1)[0]
  if label.startswith('common'):label=label.split('-')[0]
  groups.setdefault(label,[]).append(t)
 for label,ts in groups.items():
  valid=[t for t in ts if t.get('ok')]
  summary={'artifact':path.name,'label':label,'n':len(ts),'ok':len(valid),'full_cap':sum(t.get('output_cap_reached',False) for t in valid),'input_tokens':[t.get('usage',{}).get('prompt_tokens') for t in valid],'output_tokens':[t.get('usage',{}).get('completion_tokens') for t in valid]}
  for key in ('ttft_s','pp_effective_tok_s','generation_e2e_tok_s','decode_tok_s','legacy_decode_tok_s'):
   vals=[t[key] for t in valid if t.get(key) is not None]
   if vals:summary[key]={'first':vals[0],'median':statistics.median(vals),'best':min(vals) if key=='ttft_s' else max(vals)}
  summary['degenerate_slashes']=sum('////' in ((t.get('text') or '')+(t.get('reasoning_text') or '')) for t in valid)
  print(json.dumps(summary))
