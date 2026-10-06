"""Check completed prefill sweeps against tokenizer and uncached input accounting."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();rows=[]
for f in sorted((a.root/'results').glob('*.json')):
 j=json.loads(f.read_text())
 if not isinstance(j,dict) or j.get('protocol')!='pp' or len(j.get('trials',[]))!=16:continue
 records=[]
 for t in j['trials']:
  expected=int(t['label'].split('-')[0][2:]);actual=t['usage']['prompt_tokens'];tokenized=t['tokens_by_tokenize'];cached=t['usage'].get('prompt_tokens_details',{}).get('cached_tokens')
  assert t['ok'] and actual==tokenized and abs(tokenized-expected)<=1 and cached in (None,0),(f.name,t['label'])
  records.append({'label':t['label'],'expected':expected,'tokenized':tokenized,'usage_input':actual,'cached_tokens':cached})
 rows.append({'file':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'records':records})
(a.root/'provenance/pp-input-accounting-review.json').write_text(json.dumps({'description':'Completed 16-trial PP sweeps agree with their runtime tokenizer within one target token and report no cached inputs where available. Server cache controls are retained separately; input qualification does not override documented timing exclusions.','sweeps':rows},indent=2)+'\n');print('PP_INPUT_ACCOUNTING_PASS',len(rows))
