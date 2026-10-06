import urllib.request,json,hashlib,tarfile,pathlib,io
root=pathlib.Path('/tmp/flashnext-competition');m=json.loads((root/'davetha-image.json').read_text());tok=json.load(urllib.request.urlopen('https://ghcr.io/token?service=ghcr.io&scope=repository:davetha/vllm-flashnext:pull'))['token'];out=root/'davetha-base-vllm'
for i,l in enumerate(m['manifest']['layers'][10:],10):
 if l['size']>20*2**20:continue
 b=urllib.request.urlopen(urllib.request.Request('https://ghcr.io/v2/davetha/vllm-flashnext/blobs/'+l['digest'],headers={'Authorization':'Bearer '+tok}),timeout=120).read();assert len(b)==l['size'];assert 'sha256:'+hashlib.sha256(b).hexdigest()==l['digest']
 count=0
 with tarfile.open(fileobj=io.BytesIO(b)) as t:
  for a in t:
   parts=pathlib.PurePosixPath(a.name).parts
   if a.isfile() and a.name.endswith(('.py','.sh')) and 'app' in parts:
    assert '..' not in parts
    d=out.joinpath(*parts);d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes(t.extractfile(a).read());count+=1
 if count:print(i,count,flush=True)
