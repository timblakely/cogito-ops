"""Prepare Strata's native pack and pinned official MTP assets off the timed path."""
import hashlib,json,os,struct,subprocess,time
from pathlib import Path
base=Path('/workspace/flashnext-competition');src=base/'strata/src'
os.environ['STRATA_GGUF_PY']=str(base/'strata/ggml-source/gguf-py')
r9v=Path('/archive/llmkube/flashnext-iggy/r9v-iq4/target')
while not (r9v/'Qwen3.8-Flash-Next-UD-IQ4_XS-00003-of-00003.gguf').exists():time.sleep(5)
archive=Path('/archive/llmkube/flashnext-iggy/strata');archive.mkdir(exist_ok=True)
subprocess.run(['python3',str(src/'tools/iq_pack.py'),'--gguf',str(r9v/'Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf'),'--out',str(archive/'iq4-xs-pack'),'--compat-bf16'],check=True)
# Only the original payload is copied. Its expected SHA is the R9V package's.
raw=Path('/ngram/r9v/per_layer_token_embd.iq4_nl.bin')
while not raw.exists() or raw.stat().st_size!=28800138240:time.sleep(5)
p=Path('/ngram/strata/ple-iq4-nl.gguf');p.parent.mkdir(exist_ok=True)
def string(s):b=s.encode();return struct.pack('<Q',len(b))+b
header=struct.pack('<IIQQ',0x46554747,3,1,1)+string('general.alignment')+struct.pack('<II',4,4096)
header+=string('per_layer_token_embd.weight')+struct.pack('<IQQIQ',2,160,320001536,20,0)
header+=b'\0'*((-len(header))%4096)
if not p.exists():
    tmp=p.with_suffix('.partial');h=hashlib.sha256()
    with tmp.open('wb') as out,raw.open('rb') as inp:
        out.write(header)
        while chunk:=inp.read(16<<20):out.write(chunk);h.update(chunk)
        out.flush();os.fsync(out.fileno())
    assert h.hexdigest()=='dd55c28902f38cd88134b2a569c51282c5ffce30080487e1a645740115c56cc3'
    with tmp.open('rb') as inp:
        inp.seek(len(header));assert hashlib.file_digest(inp,'sha256').hexdigest()==h.hexdigest()
    tmp.rename(p)
    print('STRATA_PLE_READBACK_VERIFIED',h.hexdigest(),flush=True)
subprocess.run(['python3',str(src/'tools/mtp_fetch.py'),'fetch','--out',str(archive/'mtp-bf16')],check=True)
subprocess.run(['python3',str(src/'tools/mtp_fetch.py'),'verify','--out',str(archive/'mtp-bf16')],check=True)
env={**os.environ,'STRATA_GGUF_PY':str(base/'strata/ggml-source/gguf-py')}
subprocess.run(['python3',str(src/'tools/mtp_pack.py'),'--src',str(archive/'mtp-bf16'),'--experts','q2_0','--out',str(archive/'MTP.gguf')],env=env,check=True)
subprocess.run(['python3',str(src/'tools/mtp_rt.py'),'--gguf',str(archive/'MTP.gguf'),'--out',str(archive/'mtp-rt')],check=True)
import shutil
shutil.copy2(src/'data/draft_vocab.bin',archive/'mtp-rt/draft_vocab.bin')
print('STRATA_ASSETS_COMPLETE',flush=True)
