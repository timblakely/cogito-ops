"""Preserve the published image's vLLM, kernels and Python dependencies on the archive."""
import hashlib,json,shutil,time
from pathlib import Path
root=Path('/archive/llmkube/flashnext-iggy/davetha-compat');root.mkdir(exist_ok=True)
excluded=('torch','torchvision','torchaudio','triton','numpy','setuptools','_rocm_sdk','rocm_sdk')
src=Path('/usr/local/lib/python3.12/dist-packages');dst=root/'deps';dst.mkdir(exist_ok=True)
for p in src.iterdir():
 if any(p.name==name or p.name.startswith(name+'-') for name in excluded) or p.name=='__pycache__':continue
 q=dst/p.name
 if p.is_dir():shutil.copytree(p,q,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
 elif p.is_file():shutil.copy2(p,q)
for name in ('vllm','fp8hip','r4dhip'):
 p=Path('/app')/name;assert p.is_dir()
 shutil.copytree(p,root/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.git','*.log','build'))
# The preparation pod already has the exact pinned patches and opt-in NVMe/collective adapters merged.
checks={}
for parent in ('vllm/vllm','fp8hip','r4dhip'):
 for p in (root/parent).rglob('*'):
  if p.is_file() and p.suffix in ('.py','.so'):
   digest=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
   original=Path('/app')/p.relative_to(root)
   assert digest==hashlib.file_digest(original.open('rb'),'sha256').hexdigest(),str(original)
   checks[str(p.relative_to(root))]=digest
proof={'source_image':'ghcr.io/davetha/vllm-flashnext:DevQwenNextFlash@sha256:1465c4571b6b24a0ad91ede614f91bccb938158e10a86fff7cbd56b98543e713','base_image_adaptation':'newer glibc runtime; published vLLM tree, compiled kernels, dependencies and staged ROCm SDK retained','checksums':checks,'excluded_dependency_prefixes':list(excluded)}
(root/'provenance.json').write_text(json.dumps(proof,indent=2)+'\n');(root/'COMPLETE').write_text(str(time.time())+'\n');print('DAVETHA_COMPAT_PREPARED',len(checks),flush=True)
