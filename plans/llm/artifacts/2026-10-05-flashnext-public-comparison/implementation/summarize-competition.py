"""Summarize completed records without promoting early EOS or partial sweeps."""
import argparse,collections,json,statistics,re,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();rows=[]
for f in sorted(a.results.glob('*.json')):
 try:j=json.loads(f.read_text())
 except (ValueError,OSError):continue
 if not isinstance(j,dict) or j.get('protocol') not in ('common','c2','decode','pp'):continue
 trials=j.get('trials',[]);groups=collections.defaultdict(list)
 for t in trials:
  label=t.get('label','');key=label.rsplit('-',2)[0] if label.startswith('common') else label.rsplit('-',1)[0]
  groups[key].append(t)
 standard_counts={'decode':9,'pp':16,'common':6,'c2':4}
 data={'file':f.name,'file_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'profile':j['profile'],'protocol':j['protocol'],'recorded_trials':len(trials),'standard_sweep_trials':standard_counts[j['protocol']],'matches_standard_sweep_trial_count':len(trials)==standard_counts[j['protocol']],'groups':{}}
 for key,ts in groups.items():
  g={'trials':len(ts),'ok':sum(t.get('ok',False) for t in ts),'output_tokens':[t.get('usage',{}).get('completion_tokens') for t in ts], 'input_tokens':[t.get('usage',{}).get('prompt_tokens') for t in ts], 'early_eos':[t.get('finish_reason')=='stop' for t in ts]}
  g['cached_prompt_tokens']=[t.get('usage',{}).get('prompt_tokens_details',{}).get('cached_tokens') for t in ts]
  if j['protocol'] in ('common','c2'):g['all_reach_256']=all(n==256 for n in g['output_tokens'])
  for metric in ('ttft_s','wall_s','pp_effective_tok_s','legacy_decode_tok_s','decode_tok_s','generation_e2e_tok_s'):
   nums=[t[metric] for t in ts if t.get('ok') and t.get(metric) is not None]
   if nums:g[metric]={'mean':statistics.mean(nums),'median':statistics.median(nums),'min':min(nums),'max':max(nums),'all':nums}
  if j['protocol']=='c2' and len(ts)==2 and all(t.get('ok') for t in ts):g['pair_output_tok_s']=sum(g['output_tokens'])/max(t['wall_s'] for t in ts);g['both_reach_256']=all(n==256 for n in g['output_tokens'])
  if j['protocol']=='decode' and any(n is not None and n<=1 for n in g['output_tokens']):g['usable_generation_measurement']=False
  data['groups'][key]=g
 rows.append(data)
a.output.write_text(json.dumps(rows,indent=2)+'\n');print('SUMMARIZED',len(rows),'files',flush=True)
