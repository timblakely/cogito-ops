import urllib.request,json,hashlib,tarfile,pathlib,time
root=pathlib.Path('/tmp/flashnext-competition');m=json.loads((root/'davetha-image.json').read_text());layer=m['manifest']['layers'][9]
token=json.load(urllib.request.urlopen('https://ghcr.io/token?service=ghcr.io&scope=repository:davetha/vllm-flashnext:pull'))['token']
p=root/'davetha-vllm-source-layer.tar.gz';h=hashlib.sha256()
with urllib.request.urlopen(urllib.request.Request('https://ghcr.io/v2/davetha/vllm-flashnext/blobs/'+layer['digest'],headers={'Authorization':'Bearer '+token}),timeout=120) as response,p.open('wb') as f:
 while b:=response.read(2**20): f.write(b);h.update(b)
assert p.stat().st_size==layer['size'];assert 'sha256:'+h.hexdigest()==layer['digest'];print('LAYER_VERIFIED',p.stat().st_size,flush=True)
out=root/'davetha-base-vllm'
with tarfile.open(p) as t:
 for m in t:
  parts=pathlib.PurePosixPath(m.name).parts
  if m.isfile() and m.name.endswith('.py') and 'vllm' in parts and 'app' in parts:
   if '..' in parts:raise ValueError(m.name)
   dest=out.joinpath(*parts);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(t.extractfile(m).read())
print('EXTRACTED',sum(1 for x in out.rglob('*.py')),flush=True)
