"""Retain the publisher's step-time and draft-acceptance calculation per raw trial."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('decode',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();j=json.loads(a.decode.read_text())
def totals(snapshot):
 out={}
 for line in snapshot.get('metrics',[]):
  if line.startswith('vllm:spec_decode_num_'):
   k,v=line.rsplit(' ',1);k=k.split('{')[0];out[k]=out.get(k,0)+float(v)
 return out
records=[]
for t in j['trials']:
 before,after=totals(t['before']),totals(t['after']);d={k:v-before.get(k,0) for k,v in after.items()};steps=d.get('vllm:spec_decode_num_drafts_total',0);offered=d.get('vllm:spec_decode_num_draft_tokens_total',0);accepted=d.get('vllm:spec_decode_num_accepted_tokens_total',0)
 records.append({'label':t['label'],'completion_tokens':t.get('usage',{}).get('completion_tokens'),'wall_s':t['wall_s'],'draft_counter_deltas':d,'publisher_ms_per_step':1000*t['wall_s']/steps if steps else None,'tokens_per_step':t.get('usage',{}).get('completion_tokens',0)/steps if steps else None,'acceptance':accepted/offered if offered else None})
a.output.write_text(json.dumps({'profile':j['profile'],'description':'Publisher ab3.py step counters calculated from the retained streamed raw trials; response transport differs from the publisher nonstreaming calls. Per-step timing helps distinguish kernel work from text-dependent draft acceptance.','trials':records},indent=2)+'\n');print('PUBLISHER_STEP_COUNTERS',records)
