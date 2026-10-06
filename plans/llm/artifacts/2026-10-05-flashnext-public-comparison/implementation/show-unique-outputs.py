import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('file',type=Path);a=p.parse_args();j=json.loads(a.file.read_text());ts=j.get('trials',[]) or j.get('initial_together',[])+[t for r in j.get('replays',[]) for mode in ('alone','together') for t in r[mode]];unique={}
for t in ts:
 text=t.get('reasoning_text','')+t.get('text','');digest=hashlib.sha256(text.encode()).hexdigest();u=unique.setdefault(digest,{'labels':[],'output':text,'counts':[]});u['labels'].append(t['label']);u['counts'].append(t.get('usage',{}).get('completion_tokens'))
for digest,u in unique.items():print('FULL_UNIQUE_OUTPUT',digest,u['labels'],u['counts'],'\n'+u['output']+'\nEND_FULL_OUTPUT')
print('ALL_OUTPUTS_REPRESENTED',len(ts),'UNIQUE',len(unique))
