"""Switch the owned IQ4 payload container without copying its 27 GiB rows."""
import ctypes,hashlib,json,os,sys
from pathlib import Path
root=Path('/ngram');raw=root/'r9v/per_layer_token_embd.iq4_nl.bin';wrapped=root/'strata/ple-iq4-nl.gguf';header=Path('/workspace/flashnext-competition/strata-ple-header.bin').read_bytes();assert len(header)==4096 and header[:4]==b'GGUF'
expected='dd55c28902f38cd88134b2a569c51282c5ffce30080487e1a645740115c56cc3';size=28800138240
mode=sys.argv[1];assert mode in ('raw','gguf')
fn=ctypes.CDLL(None,use_errno=True).fallocate;fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_longlong]
if mode=='gguf' and raw.exists():
 assert not wrapped.exists() and raw.stat().st_size==size
 with raw.open('r+b') as f:
  if fn(f.fileno(),0x20,0,4096):raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
  f.write(header);f.flush();os.fsync(f.fileno())
 wrapped.parent.mkdir(exist_ok=True);raw.rename(wrapped)
elif mode=='raw' and wrapped.exists():
 assert not raw.exists() and wrapped.stat().st_size==size+4096
 with wrapped.open('r+b') as f:
  assert f.read(4096)==header
  if fn(f.fileno(),0x08,0,4096):raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
  os.fsync(f.fileno())
 wrapped.rename(raw)
p=wrapped if mode=='gguf' else raw;assert p.stat().st_size==size+(4096 if mode=='gguf' else 0)
h=hashlib.sha256()
with p.open('rb') as f:
 if mode=='gguf':assert f.read(4096)==header
 while chunk:=f.read(8<<20):h.update(chunk)
assert h.hexdigest()==expected
print(json.dumps({'format':mode,'path':str(p),'payload_sha256':h.hexdigest(),'payload_bytes':size,'header_sha256':hashlib.sha256(header).hexdigest(),'method':'XFS fallocate insert/collapse 4096 bytes; payload readback verified'}))
