"""Show physical VRAM and cgroup memory classes, avoiding virtual-buffer totals."""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();profiles=[('Native 1.0.13 production','radiance-1013-c2'),('Stew plain Q4','stew-q4-baseline'),('Stew MTP Q4','stew-q4-mtp-control'),('R9V IQ4','r9v-public'),('Shali plain Q4','stew-q4-public-single-sdk10'),('Shali MTP Q4','stew-q4-public-mtp-sdk10'),('John plain IQ3','john-iq3-layer-plain'),('John MTP IQ3','john-iq3-layer-mtp-balanced'),('Strata single','strata-public-single-header-retry'),('Strata dual base','strata-public-dual-header-retry'),('Strata dual WMMA','strata-public-dual-wmma'),('Davet LRU','davetha-public-compat-norm2'),('Q6 initial tensor cache','stew-q6-cache-rccl-loader'),('Q6 tensor hybrid replay','stew-q6-cache-hybrid-replay'),('Q6 pure RCCL','stew-q6-cache-pure-rccl-loader'),('Q6 layer wide','stew-q6-cache-layer-wide-loader'),('Q6 larger cache','stew-q6-all-cache-layer-wide-loader'),('Q6 classic r15','stew-q6-classic-r15'),('Q6 layer 4K retry','stew-q6-cache-layer-4k-loader'),('Q6 all-expert 4K / 2GiB reserve','stew-q6-all-cache-layer-4k-headroom'),('Q6 layer 4K fast card first','stew-q6-cache-layer-4k-fast-first'),('Q6 layer 4K eager host remap','stew-q6-cache-layer-4k-host-map'),('Q6 all-expert single-slot / 4GiB reserve','stew-q6-all-cache-c1-reserve4-full')]
profiles += [('Q6 layer cache, single slot','stew-q6-cache-layer-c1-qualified-full'),('Q6 classic r15 full suite, after admin wait','stew-q6-classic-r15-full-qualification')]
lines=['| Measured profile | CPU-card VRAM | Chipset-card VRAM | Pod RAM | Anonymous + shmem | File pages excluding shmem |','|---|---:|---:|---:|---:|---:|']
for name,stem in profiles:
 if stem in ('stew-q6-all-cache-layer-wide-loader','stew-q6-all-cache-layer-4k-headroom','stew-q6-all-cache-c1-reserve4-full'):name+=' (after failed 40K)'
 f=a.root/(stem+'-memory.json')
 if f.exists() and f.stat().st_size:j=json.loads(f.read_text())
 else:
  fallback=a.root/(stem+'-memory-shell.txt')
  if not fallback.exists():continue
  text=fallback.read_text();sections=dict(re.findall(r'FILE:([^\n]+)\n(.*?)(?=\nFILE:|\nGPU:|\Z)',text,re.S));gpu=re.findall(r'GPU:/sys/bus/pci/devices/([^\n]+)\n(\d+)\n(\d+)\n(\d+)',text)
  j={'memory.current':sections['/sys/fs/cgroup/memory.current'],'memory.stat':sections['/sys/fs/cgroup/memory.stat'],'gpus':[{'bdf':bdf,'mem_info_vram_used':used} for bdf,total,used,gtt in gpu]}
 stats=dict((k,int(v)) for k,v in (x.split() for x in j['memory.stat'].splitlines()));g={x['bdf']:int(x['mem_info_vram_used']) for x in j['gpus']};values=[g.get('0000:2f:00.0',0),g.get('0000:25:00.0',0),int(j['memory.current']),stats['anon']+stats['shmem'],stats['file']-stats['shmem']]
 lines.append('| '+' | '.join([name,*[f'{v/2**30:.2f} GiB' for v in values]])+' |')
a.output.write_text('\n'.join(lines)+'\n');print('MEMORY_ROWS',len(lines)-2)
