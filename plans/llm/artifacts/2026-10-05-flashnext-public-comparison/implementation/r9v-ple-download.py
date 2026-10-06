import time,subprocess,hashlib,json
from pathlib import Path
p=Path('/archive/llmkube/flashnext-iggy/r9v-iq4/target/Qwen3.8-Flash-Next-UD-IQ4_XS-00002-of-00003.gguf')
while not p.exists(): time.sleep(5)
o=Path('/ngram/r9v/per_layer_token_embd.iq4_nl.bin')
subprocess.run(['python3','/workspace/flashnext-competition/R9V/tools/prepare_ple.py',str(p),'--output',str(o)],check=True)
with o.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
assert digest=='dd55c28902f38cd88134b2a569c51282c5ffce30080487e1a645740115c56cc3',digest
print('PLE_FULL_READBACK_VERIFIED',digest,flush=True)
