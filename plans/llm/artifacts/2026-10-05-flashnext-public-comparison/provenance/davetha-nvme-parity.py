"""Check sampled checkpoint FP8 rows and scaled values against the NVMe view."""
import hashlib,json,os,struct
from pathlib import Path
import torch
root=Path('/archive/llmkube/flashnext-iggy/davetha-mxfp4')
proof=json.loads(Path('/ngram/davetha/ple-slices.json').read_text())
mapped=torch.from_file('/ngram/davetha/ple-fp8.bin',shared=False,size=proof['rows']*160,dtype=torch.uint8).view(torch.float8_e4m3fn).view(proof['rows'],160)
index=json.loads((root/'model.safetensors.index.json').read_text())['weight_map']; scale_name=next(n for n in index if n.endswith('ngram_embedding.weight_scale'))
with (root/index[scale_name]).open('rb') as f:
 n=struct.unpack('<Q',f.read(8))[0]; h=json.loads(f.read(n));m=h[scale_name];a,b=m['data_offsets'];f.seek(8+n+a);raw=f.read(b-a)
assert m['dtype'] in ('F32','BF16'); scale=torch.frombuffer(bytearray(raw),dtype={'F32':torch.float32,'BF16':torch.bfloat16}[m['dtype']]).clone();assert scale.numel()==1
checks=0
for rec in proof['slices']:
 with (root/rec['source_shard']).open('rb') as f:
  for row in (0,1,1250006,2500011):
   f.seek(rec['source_offset']+row*160);raw=f.read(160)
   source=torch.frombuffer(bytearray(raw),dtype=torch.uint8).view(torch.float8_e4m3fn)
   target=mapped[rec['destination_offset']//160+row]
   assert torch.equal(source.view(torch.uint8),target.view(torch.uint8))
   assert torch.equal(source.to(torch.bfloat16)*scale.to(torch.bfloat16),target.to(torch.bfloat16)*scale.to(torch.bfloat16))
   checks+=1
maps=[];active=None
for line in Path('/proc/self/smaps').read_text().splitlines():
 if 'ple-fp8.bin' in line:active={'mapping':line};maps.append(active)
 elif '-' in line.split()[0] and len(line.split())>=5:active=None
 elif active and line.startswith(('Rss:','Locked:','Anonymous:')):
  k,v=line.split(':',1);active[k]=v.strip()
assert maps and all(m['Locked']=='0 kB' for m in maps)
print(json.dumps({'status':'PASS','rows_checked':checks,'scale':scale.item(),'scale_tensor':scale_name,'nvme_mapping':maps,'torch':torch.__version__},indent=2))
