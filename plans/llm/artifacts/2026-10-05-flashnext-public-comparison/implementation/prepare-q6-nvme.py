"""Recycle inactive campaign copies; keep originals, then verify Q6 on NVMe."""
import hashlib,json,os,time
from pathlib import Path
r=Path('/workspace/flashnext-competition');modeldir=Path('/models/q6/UD-Q6_K_XL');destdir=Path('/ngram/q6/UD-Q6_K_XL');archive=Path('/archive/llmkube/flashnext-iggy');manifest=json.loads((r/'q6-conventional-checksums.json').read_text());proof={'start_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'recycled':[],'files':[]}
# The controller must finish all public profiles and confirm idle GPUs first.
for d in Path('/sys/bus/pci/devices').iterdir():
 if (d/'mem_info_vram_used').exists():assert int((d/'mem_info_vram_used').read_text())<256*1024*1024
john=Path('/ngram/john-iq3/UD-IQ3_XXS/Qwen3.8-Flash-Next-UD-IQ3_XXS-00002-of-00003.gguf');johnorig=archive/'john-iq3/UD-IQ3_XXS'/john.name
# Downloader only promotes the upstream-hash-verified complete file.
assert johnorig.exists() and johnorig.stat().st_size==49567921344
for name in ('Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf','Qwen3.8-Flash-Next-UD-IQ4_XS-00002-of-00003.gguf','Qwen3.8-Flash-Next-UD-IQ4_XS-00003-of-00003.gguf'):assert (archive/'r9v-iq4/target'/name).is_file()
for i in range(1,26):assert (archive/'davetha-mxfp4'/f'model-{i:05d}-of-00025.safetensors').is_file()
# Leave the inactive IQ3 symlink pointing at its preserved original, not a dead path.
p=Path('/models/iq3/UD-IQ3_XXS')/john.name
assert p.is_symlink() and p.resolve() in (john,johnorig)
if p.resolve()==john:
 p.with_suffix('.new-link').symlink_to(johnorig);p.with_suffix('.new-link').replace(p)
for p,expected in [(john,49567921344),(Path('/ngram/davetha/ple-fp8.bin'),51200245760),(Path('/ngram/strata/ple-iq4-nl.gguf'),28800142336)]:
 if p.exists():
  assert p.is_file() and not p.is_symlink() and p.stat().st_size==expected
  proof['recycled'].append({'path':str(p),'bytes':expected,'originals_retained':True});p.unlink();print('RECYCLED',str(p),expected,flush=True)
# Save deletion evidence before the free-space guard; retries retain the prior ledger.
ledger=r/'results/q6-nvme-recycling-proof.json'
if ledger.exists():
 prior=json.loads(ledger.read_text());proof['recycled']=prior['recycled']+proof['recycled']
ledger.write_text(json.dumps({'recycled':proof['recycled'],'description':'Inactive campaign copies removed after original-source and GPU-idle checks'},indent=2)+'\n')
# 15% kubelet reserve plus an additional margin after all Q6 copies.
for item in manifest:
 partial=(destdir/Path(item['path']).name).with_suffix('.copy-partial')
 if partial.exists():partial.unlink()
reserve=80*1024**3;needed=sum(item['bytes'] for item in manifest if not (destdir/Path(item['path']).name).exists());free=os.statvfs(destdir).f_bavail*os.statvfs(destdir).f_frsize
os.sync()
for _ in range(60):
 free=os.statvfs(destdir).f_bavail*os.statvfs(destdir).f_frsize
 if free-needed>reserve:break
 print('WAIT_NVME_RECLAIM',free,needed,reserve,flush=True);time.sleep(2)
assert free-needed>reserve,(free,needed,reserve)
for item in manifest:
 source=archive/'q6'/item['path'];dest=destdir/source.name;expected=item['sha256'];assert source.stat().st_size==item['bytes']
 start=time.monotonic()
 if not dest.exists():
  tmp=dest.with_suffix('.copy-partial');h=hashlib.sha256()
  with source.open('rb') as src,tmp.open('wb') as out:
   while chunk:=src.read(16<<20):out.write(chunk);h.update(chunk)
   out.flush();os.fsync(out.fileno())
  assert h.hexdigest()==expected;tmp.replace(dest)
 with dest.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 assert actual==expected and dest.stat().st_size==item['bytes']
 p=modeldir/source.name;assert p.is_symlink();link=p.with_suffix('.new-link');link.symlink_to(dest);link.replace(p)
 rec={'path':str(dest),'bytes':item['bytes'],'sha256':actual,'matches_upstream':True,'source':str(source),'copy_and_readback_s':time.monotonic()-start};proof['files'].append(rec)
 (r/'results/q6-nvme-conventional-proof.json').write_text(json.dumps(proof,indent=2)+'\n');print('Q6_NVME_VERIFIED',json.dumps(rec),flush=True)
proof['free_bytes_after']=os.statvfs(destdir).f_bavail*os.statvfs(destdir).f_frsize;proof['finish_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());(r/'results/q6-nvme-conventional-proof.json').write_text(json.dumps(proof,indent=2)+'\n');print('Q6_NVME_PREPARE_COMPLETE',proof['free_bytes_after'],flush=True)
