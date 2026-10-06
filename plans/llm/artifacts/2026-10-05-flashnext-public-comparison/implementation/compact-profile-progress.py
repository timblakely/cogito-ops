import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('profile');a=p.parse_args();r=Path('/tmp/flashnext-competition');f=r/(a.profile+'-campaign.log');trials=[]
if f.exists():
 for line in f.read_text().splitlines():
  try:j=json.loads(line)
  except json.JSONDecodeError:continue
  if 'label' in j:trials.append(j)
counts={}
for t in trials:
 protocol=t['label'].split('-')[0];protocol='common' if protocol.startswith('common') else 'pp' if protocol.startswith('pp') else 'decode';counts[protocol]=counts.get(protocol,0)+1
last=trials[-1] if trials else {};print(json.dumps({'profile':a.profile,'completed':counts,'last':{k:last.get(k) for k in ('label','ok','ttft_s','wall_s','pp_effective_tok_s','generation_e2e_tok_s')},'runner_tail':(r/(a.profile+'-runner.log')).read_text().splitlines()[-2:]}))
