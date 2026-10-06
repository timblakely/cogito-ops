import concurrent.futures,hashlib,json,os,threading,time,urllib.request
from pathlib import Path
REPO='Dyluhn/Qwen3.8-Flash-Next-R9V-IQ4_XS'; REV='bf836f0c20b6c92fcad4226ad3115eb8a19f7582'
ROOT=Path('/archive/llmkube/flashnext-iggy/r9v-iq4'); CHUNK=512*2**20
METADATA=json.loads(Path('/workspace/flashnext-competition/r9v-model-files.json').read_text())
models=[]; jobs=[]; lock=threading.Lock()
for m in METADATA:
 target=ROOT/m['path']; target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists() and target.stat().st_size==m['size']:
  with target.open('rb') as f: existing=hashlib.file_digest(f,'sha256').hexdigest()
  if existing==m['lfs']['oid']: print('VERIFIED existing',m['path'],flush=True); continue
 part=target.with_suffix('.range-part'); statefile=target.with_suffix('.range-state.json')
 state=json.loads(statefile.read_text()) if statefile.exists() else {'sha256':m['lfs']['oid'],'completed':[]}
 assert state['sha256']==m['lfs']['oid']
 if not part.exists(): state['completed']=[]
 with part.open('ab') as f: f.truncate(m['size'])
 req=urllib.request.Request('https://huggingface.co/'+REPO+'/resolve/'+REV+'/'+m['path']+'?download=true&cb='+str(time.time_ns()),headers={'Range':'bytes=0-0','Cache-Control':'no-cache'})
 with urllib.request.urlopen(req,timeout=120) as response: url=response.url; response.read(1)
 item={'meta':m,'target':target,'part':part,'statefile':statefile,'state':state,'url':url}; models.append(item)
 for first in range(0,m['size'],CHUNK):
  if first not in state['completed']: jobs.append((item,first,min(first+CHUNK,m['size'])-1))
def download(job):
 item,first,last=job; m=item['meta']; started=time.monotonic()
 for attempt in range(5):
  try:
   req=urllib.request.Request(item['url'],headers={'Range':f'bytes={first}-{last}'})
   with urllib.request.urlopen(req,timeout=120) as response,item['part'].open('r+b') as out:
    wanted=f"bytes {first}-{last}/{m['size']}"
    assert (first==0 and last==m['size']-1 and response.status==200) or (response.status==206 and response.headers.get('Content-Range')==wanted),('unexpected range',response.status,response.headers.get('Content-Range'),wanted)
    out.seek(first); count=0
    while data:=response.read(2**20): out.write(data); count+=len(data)
    assert count==last-first+1
    out.flush(); os.fsync(out.fileno())
   with lock:
    item['state']['completed'].append(first); temp=item['statefile'].with_suffix('.tmp'); temp.write_text(json.dumps(item['state'])); temp.replace(item['statefile'])
   print('CHUNK',m['path'],first,last,round(time.monotonic()-started,1),flush=True); return
  except Exception as error:
   if attempt==4: raise
   print('RETRY',m['path'],first,repr(error),flush=True); time.sleep(2**attempt)
   refresh=urllib.request.Request('https://huggingface.co/'+REPO+'/resolve/'+REV+'/'+m['path']+'?download=true&cb='+str(time.time_ns()),headers={'Range':'bytes=0-0','Cache-Control':'no-cache'})
   with urllib.request.urlopen(refresh,timeout=120) as response: item['url']=response.url; response.read(1)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(download,jobs))
for item in models:
 with item['part'].open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
 assert actual==item['meta']['lfs']['oid'],('checksum mismatch',item['meta']['path'])
 item['part'].replace(item['target']); print('VERIFIED',item['meta']['path'],actual,flush=True)
print('All Q6 shards verified',flush=True)
