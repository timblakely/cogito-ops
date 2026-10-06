"""Render explicitly mapped comparison rows from complete, successful sweeps."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
profiles=[('Stew r15 plain, Atomic Q4','stew-q4-baseline','stew-q4-baseline-pp-pp',None),('Stew r15 MTP, Atomic Q4','stew-q4-mtp-control','stew-q4-mtp-control-pp',None),('Native 1.0.13, production layout','radiance-1013-c2',None,'radiance-1013-c2-c2'),('Native 1.0.13, publisher layout','radiance-1013-exact','radiance-1013-exact-pp',None),('R9V original IQ4_XS, CED off','r9v-public','r9v-public-pp',None),('Shali plain, Atomic Q4, one GPU','stew-q4-public-single-sdk10','stew-q4-public-single-sdk10-pp','stew-q4-public-single-sdk10-c2'),('Shali MTP, Atomic Q4, one GPU','stew-q4-public-mtp-sdk10','stew-q4-public-mtp-sdk10-pp','stew-q4-public-mtp-sdk10-c2'),('John plain, original IQ3','john-iq3-layer-plain','john-iq3-layer-plain-pp','john-iq3-layer-plain-c2'),('John balanced MTP, original IQ3','john-iq3-layer-mtp-balanced','john-iq3-layer-mtp-balanced-pp','john-iq3-layer-mtp-balanced-c2'),('Strata single, adapted IQ4_XS','strata-public-single-header-retry','strata-public-single-header-retry-pp','strata-public-single-header-retry-c2'),('Strata dual base, adapted IQ4_XS','strata-public-dual-header-retry','strata-public-dual-header-retry-pp','strata-public-dual-header-retry-c2'),('Strata dual WMMA, adapted IQ4_XS','strata-public-dual-wmma','strata-public-dual-wmma-pp','strata-public-dual-wmma-c2'),('Davet LRU, Heretic MXFP4/FP8','davetha-public-compat-norm2','davetha-public-compat-norm2-pp','davetha-public-compat-norm2-c2')]
profiles += [(title, name, ('stew-q6-classic-r15-full-qualification-pp' if name=='stew-q6-classic-r15' else name+'-pp'), name+'-c2') for title,name in [('Q6 tensor cache, hybrid','stew-q6-cache-hybrid-replay'),('Q6 tensor cache, pure RCCL','stew-q6-cache-pure-rccl-loader'),('Q6 layer cache, wide batch','stew-q6-cache-layer-wide-loader'),('Q6 all-expert cache, 65.6K slots','stew-q6-all-cache-layer-wide-loader'),('Q6 static split, Stew r15','stew-q6-classic-r15')]]
profiles += [('Q6 layer cache, 4K microbatch retry','stew-q6-cache-layer-4k-loader','stew-q6-cache-layer-4k-loader-pp','stew-q6-cache-layer-4k-loader-c2')]
profiles += [('Q6 all-expert cache, 4K / 2GiB reserve','stew-q6-all-cache-layer-4k-headroom','stew-q6-all-cache-layer-4k-headroom-pp','stew-q6-all-cache-layer-4k-headroom-c2')]
profiles += [('Q6 layer cache, 4K, fast card first','stew-q6-cache-layer-4k-fast-first','stew-q6-cache-layer-4k-fast-first-pp','stew-q6-cache-layer-4k-fast-first-c2')]
profiles += [('Q6 layer cache, 4K, eager host remap','stew-q6-cache-layer-4k-host-map','stew-q6-cache-layer-4k-host-map-pp','stew-q6-cache-layer-4k-host-map-c2')]
profiles += [('Q6 all-expert cache, single slot, 4GiB reserve','stew-q6-all-cache-c1-reserve4-full','stew-q6-all-cache-c1-reserve4-full-pp',None)]
profiles += [('Q6 layer cache, qualified single slot','stew-q6-cache-layer-c1-qualified-full','stew-q6-cache-layer-c1-qualified-full-pp',None)]
def read(name):
 f=a.root/(name+'.json');return json.loads(f.read_text()) if f.exists() else None
def valid(j,n):return j and len(j.get('trials',[]))==n and all(t.get('ok') for t in j['trials'])
def group(j,label):return [t for t in j['trials'] if t['label'].startswith(label+'-')]
def number(ts,key,mode=statistics.median):return f'{mode(t[key] for t in ts):,.2f}'
decision_file=a.root.parent/'provenance/q6-qualification-decisions.json'
decisions=json.loads(decision_file.read_text()).get('profiles',{}) if decision_file.exists() else {}
lines=['| Completed profile | Short TTFT, warmed | Short TG, warmed | 40K TTFT, median | 40K TG, median | 40K request wall, median | 32K PP, mean | 64K PP, mean | C2 40K pair wall |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for title,name,pp,c2 in profiles:
 if c2 and decisions.get(name,{}).get('c2_qualified') is False:title+=' (C2 rejected)'
 j=read(name+'-common')
 if not valid(j,6) or any(t['usage']['completion_tokens']!=256 for t in j['trials']):continue
 short=group(j,'common1500')[1:];long=group(j,'common40890');pj=read(pp) if pp else None;rates=[]
 for size in (32768,65536):
  ts=group(pj,f'pp{size}') if valid(pj,16) else []
  if name=='stew-q4-public-mtp-sdk10' and size==65536:
   repeat=read('stew-q4-public-mtp-sdk10-pp-recheck-pp-recheck');ts=ts[:1]+group(repeat,'pp65536') if valid(repeat,2) else []
  rates.append(number(ts,'pp_effective_tok_s',statistics.mean) if ts else '—')
 cj=read(c2) if c2 else None;cts=group(cj,'common40890') if valid(cj,4) else []
 pair=f'{max(t["wall_s"] for t in cts):,.2f} s' if cts and all(t['usage']['completion_tokens']==256 for t in cts) else '—'
 if name.startswith('strata') and cts:pair+=' (FIFO)'
 lines.append('| '+' | '.join([title,number(short,'ttft_s')+' s',number(short,'legacy_decode_tok_s'),number(long,'ttft_s')+' s',number(long,'legacy_decode_tok_s'),number(long,'wall_s')+' s',*rates,pair])+' |')
a.output.write_text('\n'.join(lines)+'\n');print('COMPARISON_ROWS',len(lines)-2)
