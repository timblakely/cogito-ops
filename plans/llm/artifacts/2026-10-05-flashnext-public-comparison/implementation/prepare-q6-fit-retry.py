import json
from pathlib import Path
r=Path('/tmp/flashnext-competition');name='stew-q6-all-cache-layer-4k-headroom'
p=json.loads((r/'stew-q6-all-cache-layer-wide-loader.json').read_text());p['metadata']['name']='flashnext-'+name;c=p['spec']['containers'][0];c['args'][c['args'].index('--ubatch-size')+1]='4096'
next(e for e in c['env'] if e['name']=='MOE_EXPERT_CACHE_RESERVE_MIB')['value']='2048'
(r/(name+'.json')).write_text(json.dumps(p,indent=2)+'\n')
(r/'q6-all-cache-fit-retry-decision.json').write_text(json.dumps({'failed_profile':'stew-q6-all-cache-layer-wide-loader','observed_failure':'All three40K C1 requests fail GPU allocation; first GPU0 compute buffer growth7835.94->8054.54MiB','allocator_source':'ggml-alloc.c frees old buffer before replacement; CUDA backend buffer destructor calls cudaFree','cause':'Exact exhaustion/fragmentation breakdown not established. Extra transient scratch and cache headroom are plausible; no claim of simultaneous old/new compute allocations.','retry_profile':name,'changes':{'microbatch':'8192->4096','per_gpu_cache_reserve_mib':'1024->2048'},'unchanged':'same Q6 model, NVMe placement, layer split, nc48, two roughly64K slots, batch8192, cache-RAM0,114GiB Pod limit','qualification':'Require long C1, exact replay and independent C2 output reviews plus API probes before recommendation'},indent=2)+'\n')
f=r/'run-q6-layer-retry.py';s=f.read_text();old="print('LAYER_RETRY_SCREEN_FINISHED',p.returncode,flush=True);raise SystemExit(p.returncode)";assert old in s;s=s.replace(old,"print('LAYER_RETRY_SCREEN_FINISHED',p.returncode,flush=True)\nname='stew-q6-all-cache-layer-4k-headroom'\nwith (r/(name+'-runner.log')).open('w') as f:\n p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)\nprint('ALL_CACHE_FIT_RETRY_FINISHED',p.returncode,flush=True);raise SystemExit(p.returncode)")
f.write_text(s)
# Persist rejected screens independently of whether performance table has usable measurements.
f=r/'q6-qualification-decisions.json';d=json.loads(f.read_text())
for n,why in [('stew-q6-cache-layer-wide-loader','GPU1 cannot allocate7330MiB compute buffer before readiness; no timed trials'),('stew-q6-all-cache-layer-wide-loader','All3long C1 trials fail with GPU0 compute-buffer allocation OOM; short results and API probes alone do not qualify this profile')]:
 d['profiles'][n]={'screen_complete':True,'c1_qualified':False,'c2_qualified':False,'c2_failure_kind':'GPU OOM','reason':why,'cause':'Insufficient allocatable VRAM at requested compute allocation; exact fragmentation/scratch breakdown not established'}
f.write_text(json.dumps(d,indent=2)+'\n')
print('SERIAL_RETRY_MANIFEST_AND_REVIEW_SAVED')
