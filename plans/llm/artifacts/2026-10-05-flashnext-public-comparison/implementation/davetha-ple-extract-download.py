"""Extract verified checkpoint FP8 rows into an exact pageable NVMe table.

Each original slice and its destination slice are SHA-256 checked independently.
Only whole-file-verified checkpoint shards (not .range-part files) are accepted.
"""
import hashlib,json,os,re,struct,time
from pathlib import Path
archive=Path('/archive/llmkube/flashnext-iggy/davetha-mxfp4')
index_path=archive/'model.safetensors.index.json'
while not index_path.exists():time.sleep(5)
weight_map=json.loads(index_path.read_text())['weight_map']
pattern=re.compile(r'.*\.ngram_embedding\.shard_(\d+)\.weight$')
rows=[]
for name,shard in weight_map.items():
 m=pattern.fullmatch(name)
 if m:rows.append((int(m[1]),name,shard))
rows.sort();assert [r[0] for r in rows]==list(range(128))
root=Path('/ngram/davetha');root.mkdir(exist_ok=True);dest=root/'ple-fp8.bin';partial=dest.with_suffix('.partial');proof=root/'ple-slices.json';records=[];width=160;per_shard=2500012;size=128*per_shard*width
if dest.exists() and dest.stat().st_size==size and proof.exists():
 print('Existing verified FP8 table retained',flush=True);raise SystemExit(0)
with partial.open('wb') as out:out.truncate(size)
headers={}
with partial.open('r+b') as out:
 for number,name,shard in rows:
  source=archive/shard
  while not source.exists():time.sleep(5)
  if shard not in headers:
   with source.open('rb') as f:n=struct.unpack('<Q',f.read(8))[0];headers[shard]=(8+n,json.loads(f.read(n)))
  base,header=headers[shard];meta=header[name]
  assert meta['dtype']=='F8_E4M3' and meta['shape']==[per_shard,width],(name,meta)
  first,end=meta['data_offsets'];assert end-first==per_shard*width
  offset=number*per_shard*width;out.seek(offset);h=hashlib.sha256();left=end-first
  with source.open('rb') as f:
   f.seek(base+first)
   while left:
    chunk=f.read(min(8<<20,left));assert chunk;out.write(chunk);h.update(chunk);left-=len(chunk)
  out.flush();out.seek(offset);actual=hashlib.sha256(out.read(end-first)).hexdigest();assert actual==h.hexdigest()
  records.append({'number':number,'tensor':name,'source_shard':shard,'source_offset':base+first,'destination_offset':offset,'bytes':end-first,'sha256':actual})
  if number%32==0:print('PLE verified slice',number,flush=True)
 out.flush();os.fsync(out.fileno())
proof.write_text(json.dumps({'checkpoint_revision':'c453824e441f768e250990e2154a97e27796972e','dtype':'FP8 E4M3','rows':128*per_shard,'width':width,'slices':records},indent=2)+'\n');partial.rename(dest)
print('DAVETHA_NVME_PLE_COMPLETE',size,flush=True)
