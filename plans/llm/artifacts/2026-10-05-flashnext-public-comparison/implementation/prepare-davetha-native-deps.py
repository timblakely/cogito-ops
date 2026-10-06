"""Carry over only the original base libraries missing from the repaired runtime."""
import hashlib,json,re,shutil,subprocess
from pathlib import Path
r=Path('/workspace/flashnext-competition');dest=r/'davetha-native';dest.mkdir(exist_ok=True);needed=['libibverbs.so.1','libmlx5.so.1','libpci.so.3','libdrm.so.2','libdrm_amdgpu.so.1','libnl-3.so.200','libnl-route-3.so.200','librdmacm.so.1'];lookup={}
for line in subprocess.check_output(['ldconfig','-p'],text=True).splitlines():
 m=re.match(r'\s*(\S+)\s+.*=>\s+(\S+)',line)
 if m:lookup.setdefault(m.group(1),m.group(2))
proof={'source':'preserved published image ghcr.io/davetha/vllm-flashnext:DevQwenNextFlash@sha256:1465c4571b6b24a0ad91ede614f91bccb938158e10a86fff7cbd56b98543e713','reason':'missing base dependencies during MoRI model inspection; no replacement of HIP, Torch, RCCL, libc or libstdc++','files':[]}
for name in needed:
 src=Path(lookup[name]).resolve();dst=dest/name;assert src.is_file();shutil.copy2(src,dst);a=hashlib.file_digest(src.open('rb'),'sha256').hexdigest();b=hashlib.file_digest(dst.open('rb'),'sha256').hexdigest();assert a==b;proof['files'].append({'soname':name,'source':str(src),'sha256':a,'bytes':dst.stat().st_size})
assert sum(f['bytes'] for f in proof['files'])<20<<20
(r/'results/davetha-native-dependencies.json').write_text(json.dumps(proof,indent=2)+'\n');print('DAVETHA_NATIVE_DEPENDENCIES_PRESERVED',len(needed),flush=True)
