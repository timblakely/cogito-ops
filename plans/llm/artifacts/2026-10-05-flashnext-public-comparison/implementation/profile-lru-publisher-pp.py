"""Repeat the publisher's 12,500-word nonstreaming prefill probe; retain the input."""
import argparse,hashlib,json,random,time
from pathlib import Path
from flashnext_public_bench import post,counters
p=argparse.ArgumentParser();p.add_argument('--endpoint',required=True);p.add_argument('--profile',required=True);p.add_argument('--output',required=True,type=Path)
for flag in ('protocol','thinking','repetitions'):p.add_argument('--'+flag)
a=p.parse_args()
words=('the quick brown fox jumps over the lazy dog while engineers tune kernels for decode throughput ').split();rng=random.Random(7)
nonce=str(time.time_ns());prompt=nonce+' '+' '.join(rng.choice(words) for _ in range(12500))
for _ in range(5):
 with post(a.endpoint,'/reset_prefix_cache',{}) as r:cleared=json.load(r).get('success') is True
 if cleared:break
 time.sleep(.1)
assert cleared,'publisher PP prefix reset did not succeed'
before=counters(a.endpoint);start=time.perf_counter()
with post(a.endpoint,'/v1/completions',{'model':'qwen3.8-flash-next','prompt':prompt,'max_tokens':1,'temperature':0},timeout=900) as r:response=json.load(r)
wall=time.perf_counter()-start;n=response['usage']['prompt_tokens']
record={'profile':a.profile,'protocol':'lru-publisher-pp','description':'Publisher ab3.py 12,500 random-word raw prompt, one output token, prompt tokens divided by whole nonstreaming request wall time. Seeded word selection (7) and time nonce are explicit reproducibility adaptations; original exact random prompt was not retained by the publisher.','prompt':prompt,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'publisher_commit':'3743f1330f9c4174015440d5863e73a918a34809','publisher_ab3_sha256':'281ea2655b01b45d5eb65e8622836f184908c6ba781ae7433ae541e7ea7858c0','word_seed':7,'word_count':12500,'prefix_reset_verified':True,'prompt_tokens':n,'wall_s':wall,'publisher_pp_tok_s':n/wall,'response':response,'before':before,'after':counters(a.endpoint)}
a.output.write_text(json.dumps(record,indent=2)+'\n');print('LRU_PUBLISHER_PREFILL',n,wall,n/wall,flush=True)
