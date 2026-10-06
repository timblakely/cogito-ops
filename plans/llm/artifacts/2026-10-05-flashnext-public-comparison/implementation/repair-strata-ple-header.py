"""Mark the existing extracted n-gram container; write only its 4 KiB header."""
import hashlib,json,os,struct
from pathlib import Path
r=Path('/workspace/flashnext-competition');p=Path('/ngram/strata/ple-iq4-nl.gguf');old=(r/'strata-ple-header.bin').read_bytes();assert len(old)==4096
assert p.stat().st_size==28800138240+4096
with p.open('rb') as f:assert f.read(4096)==old

def string(s):b=s.encode();return struct.pack('<Q',len(b))+b
h=struct.pack('<IIQQ',0x46554747,3,1,2)
h+=string('general.alignment')+struct.pack('<II',4,4096)
h+=string('general.architecture')+struct.pack('<I',8)+string('strata-ple')
h+=string('per_layer_token_embd.weight')+struct.pack('<IQQIQ',2,160,320001536,20,0)
h+=b'\0'*((-len(h))%4096);assert len(h)==4096
with p.open('r+b') as f:
 f.write(h);f.flush();os.fsync(f.fileno());f.seek(0);assert f.read(4096)==h
(r/'strata-ple-header-before-marker.bin').write_bytes(old);(r/'strata-ple-header.bin').write_bytes(h)
proof={'path':str(p),'payload_bytes':28800138240,'payload_sha256_previously_readback_verified':'dd55c28902f38cd88134b2a569c51282c5ffce30080487e1a645740115c56cc3','payload_modified':False,'bytes_written':4096,'old_header_sha256':hashlib.sha256(old).hexdigest(),'new_header_sha256':hashlib.sha256(h).hexdigest(),'general.architecture':'strata-ple','qualification':'Upstream generate.cpp excludes a strata-ple container from the native dense shard list; tensor rows and payload offset remain unchanged'}
(r/'results/strata-ple-header-repair.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof),flush=True)
