import hashlib,json,time
from pathlib import Path
block=''.join(f'Record {i:03d}: Describe compute scheduling, memory pressure, network latency, failure recovery, and evidence collection in a GPU service.\n' for i in range(50));suffix='\nWrite a detailed technical briefing in prose about operating a two-GPU inference service. Cover scheduling, memory, communication, and recovery in at least twelve paragraphs. Use the context above as background and continue until the output limit.\n';base=block+suffix
assert hashlib.sha256(base.encode()).hexdigest()=='5d66f3e0639883c8f5697ccb114193af00889a1923cdfa7464a15f88f0f0049f'
j=json.loads(Path('/tmp/flashnext-competition/stew-q6-cache-rccl-loader-c2.json').read_text());ts=j['trials'][:2];known=1791261003949928377
messages=lambda i,nonce:[{'role':'system','content':'Answer directly in prose. Do not call tools.'},{'role':'user','content':f'independent {i} 0 {nonce}\n'+base+f'\nSession {i}.'}]
assert hashlib.sha256(json.dumps(messages(1,known)).encode()).hexdigest()==ts[1]['prompt_sha256']
text=json.dumps(messages(0,'NONCEPLACEHOLDER')).encode();prefix,suffix=text.split(b'NONCEPLACEHOLDER');seed=hashlib.sha256(prefix);start=time.monotonic()
for delta in range(1,1000001):
 value=known-delta;h=seed.copy();h.update(str(value).encode());h.update(suffix)
 if h.hexdigest()==ts[0]['prompt_sha256']:
  proof={'method':'Recover original nonce by matching retained full-prompt SHA-256; base prompt and peer nonce independently verified','base_prompt_sha256':hashlib.sha256(base.encode()).hexdigest(),'original_nonces':[f'independent 0 0 {value}',f'independent 1 0 {known}'],'prompt_sha256':[t['prompt_sha256'] for t in ts],'search_ns_before_peer':delta,'search_s':time.monotonic()-start};Path('/tmp/flashnext-competition/q6-original-c2-nonces.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof));break
else:raise SystemExit('Nonce not recovered in the bounded 1ms window; no exact-original replay claimed')
