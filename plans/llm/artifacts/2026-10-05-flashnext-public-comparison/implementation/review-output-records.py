"""Display retained response excerpts and repetition clues for human review."""
import argparse,collections,hashlib,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('files',nargs='+',type=Path);p.add_argument('--excerpt',type=int,default=400);a=p.parse_args()
for f in a.files:
 j=json.loads(f.read_text());ts=j.get('trials',[])
 if 'replays' in j:ts=j.get('initial_together',[])+[t for rr in j['replays'] for mode in ('alone','together') for t in rr[mode]]
 print('\nFILE',f.name)
 for t in ts:
  text=(t.get('reasoning_text') or '')+(t.get('text') or '');words=re.findall(r'\w+',text.lower());grams=collections.Counter(tuple(words[i:i+8]) for i in range(max(0,len(words)-7)));top=grams.most_common(1)
  print(json.dumps({'label':t['label'],'ok':t.get('ok'),'tokens':t.get('usage',{}).get('completion_tokens'),'finish':t.get('finish_reason'),'wall_s':t.get('wall_s'),'ttft_s':t.get('ttft_s'),'legacy_tg':t.get('legacy_decode_tok_s'),'output_sha256':hashlib.sha256(text.encode()).hexdigest(),'most_repeated_8_words':top,'repeat_count':t.get('repeated_records_phrase_count'),'head':text[:a.excerpt],'tail':text[-a.excerpt:]},ensure_ascii=False))
