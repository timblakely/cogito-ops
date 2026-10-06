"""Replay identical short prompts alone and together; retain differences, not a quality score."""
import argparse,json,threading,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from flashnext_public_bench import trial
from qwen_p2p_bench import build_prompt
p=argparse.ArgumentParser();p.add_argument('--profile');p.add_argument('--protocol');p.add_argument('--thinking');p.add_argument('--llama-cache-off',action='store_true');p.add_argument('--endpoint',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--repetitions',type=int,default=3);a=p.parse_args()
base,count=build_prompt(a.endpoint,'qwen3.8-flash-next',1500);results=[]
proof=json.loads((Path(__file__).parent/'q6-original-c2-nonces.json').read_text())
common_path=a.output.parent/(a.profile+'-pp.json')
common_bytes=common_path.read_bytes();common=json.loads(common_bytes)
assert len(common['trials'])==16 and all(t.get('ok') for t in common['trials'])
assert common['trials'][-1]['label']=='pp65536-2'
import hashlib
preconditioning={'file':common_path.name,'sha256':hashlib.sha256(common_bytes).hexdigest(),'protocol':'pp','trials':16,'last_label':common['trials'][-1]['label'],'timestamp_utc':common['timestamp_utc']}
initial_together=None
for rep in range(a.repetitions):
 payloads=[]
 for i in range(2):
  nonce=proof['original_nonces'][i]
  payloads.append({'model':'qwen3.8-flash-next','temperature':0,'seed':7,'max_tokens':256,'cache_prompt':False,'messages':[{'role':'system','content':'Answer directly in prose. Do not call tools.'},{'role':'user','content':nonce+'\n'+base+f'\nSession {i}.'}]})
 for i,d in enumerate(payloads):
  import hashlib
  assert hashlib.sha256(json.dumps(d['messages']).encode()).hexdigest()==proof['prompt_sha256'][i]
 if initial_together is None:
  initial_together=[None,None];first_barrier=threading.Barrier(2)
  first_workers=[threading.Thread(target=lambda i=i: initial_together.__setitem__(i,trial(a.endpoint,payloads[i],f'initial-together-{i}',first_barrier))) for i in range(2)]
  for w in first_workers:w.start()
  for w in first_workers:w.join()
  for rec in initial_together:
   rec['repeated_records_phrase_count']=((rec.get('text') or '')+(rec.get('reasoning_text') or '')).lower().count('records are all identical')
  print('INITIAL_ORIGINAL_PAIR_AFTER_64K_PP',[(t['label'],t.get('usage',{}).get('completion_tokens'),t['repeated_records_phrase_count']) for t in initial_together],flush=True)
 alone=[trial(a.endpoint,d,f'alone-{rep}-{i}') for i,d in enumerate(payloads)]
 together=[None,None];barrier=threading.Barrier(2)
 workers=[threading.Thread(target=lambda i=i: together.__setitem__(i,trial(a.endpoint,payloads[i],f'together-{rep}-{i}',barrier))) for i in range(2)]
 for w in workers:w.start()
 for w in workers:w.join()
 for i in range(2):
  assert alone[i]['prompt_sha256']==together[i]['prompt_sha256']
  for rec in (alone[i],together[i]):
   rec['concurrency_nonce']=payloads[i]['messages'][-1]['content'].splitlines()[0]
   rec['repeated_records_phrase_count']=((rec.get('text') or '')+(rec.get('reasoning_text') or '')).lower().count('records are all identical')
 results.append({'repetition':rep,'alone':alone,'together':together,'same_output':[all(alone[i].get(k)==together[i].get(k) for k in ('text','reasoning_text','finish_reason')) for i in range(2)]})
 a.output.write_text(json.dumps({'profile':a.profile,'protocol':'replay','base_prompt_tokens':count,'qualification':'Exact original anomalous C2 pair after completed16trial8K/32K/64KPP sweep, SHA-256 verified, repeated unchanged C1 then C2; differences recorded for manualqualityreview','original_nonce_proof':proof,'preconditioning':preconditioning,'initial_together':initial_together,'replays':results},indent=2)+'\n')
 print('REPLAY',rep,'same_output',results[-1]['same_output'],'repeat_counts',[(t['label'],t['repeated_records_phrase_count']) for t in alone+together],flush=True)

if any(not t.get("ok") for t in initial_together):
 raise SystemExit("Initial original pair contains failed requests; artifacts retained")
if any(not trial.get("ok") for replay in results for mode in ("alone", "together") for trial in replay[mode]):
 raise SystemExit("Replay contains failed requests; artifacts retained")
