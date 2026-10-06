import hashlib,os,time
from pathlib import Path
source=Path('/archive/llmkube/flashnext-iggy/john-iq3/UD-IQ3_XXS/Qwen3.8-Flash-Next-UD-IQ3_XXS-00002-of-00003.gguf')
while not source.exists():time.sleep(5)
dest=Path('/ngram/john-iq3/UD-IQ3_XXS')/source.name;dest.parent.mkdir(parents=True,exist_ok=True)
expected='cfe600b236b88c7fad1613a5ca5e83b9f2beb63cbd44c32b2be50a44747c695f'
if dest.exists():
 with dest.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
else:
 temp=dest.with_suffix('.partial');h=hashlib.sha256()
 with source.open('rb') as inp,temp.open('wb') as out:
  while chunk:=inp.read(16<<20):out.write(chunk);h.update(chunk)
  out.flush();os.fsync(out.fileno())
 assert h.hexdigest()==expected
 with temp.open('rb') as inp:assert hashlib.file_digest(inp,'sha256').hexdigest()==expected
 temp.rename(dest)
print('IQ3_NVME_NGRAM_SHARD_VERIFIED',expected,flush=True)
