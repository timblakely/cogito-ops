"""Localize the checksum-qualified published runtime; preserve archive originals."""
import hashlib,json,os,shutil,time
from pathlib import Path
r=Path('/workspace/flashnext-competition');src=Path('/archive/llmkube/flashnext-iggy/davetha-compat');dst=r/'davetha-compat-local';dst.mkdir(exist_ok=True)
free=os.statvfs(dst).f_bavail*os.statvfs(dst).f_frsize;assert free>6*2**30
proof={'start_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'source':str(src),'destination':str(dst),'originals_retained':True,'checksums':{}}
for part in ('deps','vllm','fp8hip','r4dhip'):
 shutil.copytree(src/part,dst/part,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
 print('LOCAL_RUNTIME_COPIED',part,flush=True)
old=json.loads((src/'provenance.json').read_text())
for path,digest in old['checksums'].items():
 p=dst/path;actual=hashlib.file_digest(p.open('rb'),'sha256').hexdigest();assert actual==digest,path;proof['checksums'][path]=actual
# All dependencies, beyond the already qualified engine/kernel subset.
proof['dependency_file_checksums']={}
for p in sorted((dst/'deps').rglob('*')):
 if p.is_file():
  rel=p.relative_to(dst);original=src/rel;actual=hashlib.file_digest(p.open('rb'),'sha256').hexdigest();assert actual==hashlib.file_digest(original.open('rb'),'sha256').hexdigest(),str(rel);proof['dependency_file_checksums'][str(rel)]=actual
proof['free_bytes_after']=os.statvfs(dst).f_bavail*os.statvfs(dst).f_frsize;assert proof['free_bytes_after']>5*2**30;proof['finish_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());(r/'results/davetha-local-runtime-proof.json').write_text(json.dumps(proof,indent=2)+'\n');(dst/'COMPLETE').write_text(proof['finish_utc']+'\n');print('DAVETHA_LOCAL_RUNTIME_VERIFIED',len(proof['checksums']),len(proof['dependency_file_checksums']),flush=True)
