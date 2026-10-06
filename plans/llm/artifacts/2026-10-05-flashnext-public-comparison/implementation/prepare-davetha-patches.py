"""Reconstruct publisher overlays from the verified public image source."""
import hashlib,json,re,shutil,subprocess
from pathlib import Path
base=Path('/tmp/flashnext-competition');repo=base/'r9700-lru-expert-cache';original=base/'davetha-base-vllm/app/vllm/vllm';out=base/'davetha-overlays';out.mkdir(exist_ok=True)
script=(repo/'patches/apply_patches.sh').read_text();records=[]
for rel,dif in [x.split('|') for x in re.search('PATCHED="\n(.*?)\n"',script,re.S).group(1).splitlines() if x]:
    source=original/rel;dest=out/'vllm'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    patch=repo/'patches'/dif.replace('MOE_MODE','lru')
    subprocess.run(['patch','--batch','--forward','--fuzz=0','-p1','-i',str(patch)],cwd=out,check=True)
    records.append({'path':rel,'original_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'publisher_patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'result_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
for source,rel in [x.split('|') for x in re.search('NEWFILES="\n(.*?)\n"',script,re.S).group(1).splitlines() if x]:
    dest=out/'vllm'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/source,dest)
    records.append({'path':rel,'publisher_newfile_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
rel='models/qwen4_exp/amd/ple_layer.py';dest=out/'vllm'/rel;shutil.copy2(original/rel,dest)
subprocess.run(['patch','--batch','--forward','--fuzz=0','-p1','-i',str(base/'davetha-nvme-ple.patch')],cwd=out,check=True)
records.append({'path':rel,'original_sha256':hashlib.sha256((original/rel).read_bytes()).hexdigest(),'nvme_patch_sha256':hashlib.sha256((base/'davetha-nvme-ple.patch').read_bytes()).hexdigest(),'result_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
for row in records:compile((out/'vllm'/row['path']).read_text(),row['path'],'exec')
(out/'provenance.json').write_text(json.dumps(records,indent=2)+'\n')
print('All publisher overlays apply with fuzz=0; Python syntax valid')
