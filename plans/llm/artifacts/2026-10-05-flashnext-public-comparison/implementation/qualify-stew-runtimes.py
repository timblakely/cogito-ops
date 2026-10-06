"""Verify retained runtimes and publish checksum manifests outside timed trials."""
import hashlib,json
from pathlib import Path
r=Path('/workspace/flashnext-competition');out={}
for name in ('stew','stew-loader'):
 root=r/name;files=[root/'build/bin/llama-server']+sorted((root/'build/bin').glob('lib*.so*'));assert all(p.is_file() for p in files)
 checks={str(p.relative_to(root)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in files}
 assert checks['build/bin/libggml-hip.so']=='5d46edb0e67e38cb3f01c4129954e94ee8593db91b906c4cfa097509f89ba5bb'
 text=''.join(f'{digest}  {path}\n' for path,digest in checks.items());p=root/'build.sha256'
 if p.exists():assert p.read_text()==text,'existing manifest differs'
 else:p.write_text(text)
 out[name]={'manifest_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'checksums':checks}
(r/'results/stew-qualified-runtime-manifests.json').write_text(json.dumps(out,indent=2)+'\n');print('STEW_RUNTIME_MANIFESTS_VERIFIED',len(out),flush=True)
