"""Compare full raw suites; one-token EOS has no generation-throughput score."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
profiles=[('Stew plain, Atomic Q4','stew-q4-baseline'),('Stew MTP, Atomic Q4','stew-q4-mtp-control'),('Native 1.0.13 publisher, exact','radiance-1013-exact'),('R9V original IQ4_XS','r9v-public'),('Shali plain, one GPU','stew-q4-public-single-sdk10'),('Shali MTP, one GPU','stew-q4-public-mtp-sdk10'),('John plain, original IQ3','john-iq3-layer-plain'),('John balanced MTP, original IQ3','john-iq3-layer-mtp-balanced'),('Strata single base','strata-public-single-header-retry'),('Strata dual base','strata-public-dual-header-retry'),('Strata dual WMMA','strata-public-dual-wmma'),('Davet LRU, published fused norm 2','davetha-public-compat-norm2'),('Davet LRU, norm 0 control','davetha-public-compat-quark'),('Q6 initial tensor-cache screen','stew-q6-cache-rccl-loader')]
profiles += [('Q6 all-expert single-slot, 4GiB reserve','stew-q6-all-cache-c1-reserve4-full')]
profiles += [('Q6 conservative two-slot, full qualification','stew-q6-classic-r15-full-qualification')]
profiles += [('Q6 layer cache, qualified single slot','stew-q6-cache-layer-c1-qualified-full')]
lines=['| Raw profile | Prose, 256 cap | JSON, 800 cap | Code, 600 cap |','|---|---:|---:|---:|']
for title,name in profiles:
 f=a.root/(name+'-decode.json')
 if not f.exists():continue
 j=json.loads(f.read_text());ts=j.get('trials',[])
 if len(ts)!=9 or not all(t.get('ok') for t in ts):continue
 cells=[]
 for label,cap in [('prose',256),('JSON',800),('code',600)]:
  group=[t for t in ts if t['label'].startswith(label+'-')];assert len(group)==3
  ns=[t['usage']['completion_tokens'] for t in group]
  cells.append(f'{max(t["generation_e2e_tok_s"] for t in group):.2f}' if ns==[cap]*3 else 'EOS; '+','.join(map(str,ns))+' tokens')
 lines.append('| '+' | '.join([title,*cells])+' |')
a.output.write_text('\n'.join(lines)+'\n');print('RAW_DECODE_ROWS',len(lines)-2)
