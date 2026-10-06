"""Verify every Q6 shard resolves to the intended local NVMe volume."""
import json,os,time
from pathlib import Path
r=Path('/workspace/flashnext-competition');model=Path('/models/q6/UD-Q6_K_XL');files=[]
for p in sorted(model.glob('*.gguf')):
 target=p.resolve();assert str(target).startswith('/ngram/q6/UD-Q6_K_XL/'),str(target)
 files.append({'path':str(p),'target':str(target),'bytes':target.stat().st_size,'device_id':target.stat().st_dev,'is_symlink':p.is_symlink()})
assert len(files)==6
mounts=[x for x in Path('/proc/self/mountinfo').read_text().splitlines() if ' /ngram ' in x];assert len(mounts)==1 and '/dev/nvme1n1p4' in mounts[0]
proof={'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'description':'All six Q6 model shards resolve to the same verified local NVMe volume after conventional promotion; n-gram shard3 preserved','files':files,'mountinfo':mounts,'free_bytes':os.statvfs('/ngram').f_bavail*os.statvfs('/ngram').f_frsize}
(r/'results/q6-local-nvme-mapping-proof.json').write_text(json.dumps(proof,indent=2)+'\n');print('Q6_ALL_SIX_SHARDS_LOCAL_NVME',len(files),proof['free_bytes'])
