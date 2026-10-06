"""Record physical GPU use, cgroup RAM, and pageable n-gram mappings."""
import json,os,re
from pathlib import Path
out={'processes':[],'gpus':[]}
for p in Path('/proc').iterdir():
    if not p.name.isdigit() or int(p.name)==os.getpid():continue
    try:
        cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        if not any(s in cmd for s in ('llama-server','radiance --','vllm','VLLM::','strata --','multiprocessing.spawn')):continue
        if cmd.startswith('python3 -'):continue
        fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (p/'status').read_text().splitlines() if ':' in line}
        record={'pid':int(p.name),'name':fields.get('Name'),'memory_status':{k:fields.get(k) for k in ('VmRSS','VmLck','VmPin','VmSize')}}
        maps=[];current=None;libraries=set()
        for line in (p/'smaps').read_text().splitlines():
            if re.match(r'^[0-9a-f]+-[0-9a-f]+ ',line):
                if any(name in line for name in ('libamdhip64.so','libhsa-runtime64.so','librocblas.so','librccl.so','libomp.so')):
                    libraries.add(line.split()[-1])
                if current:maps.append(current)
                current={'mapping':line} if any(s in line for s in ('.gguf','.rad','ple-fp8.bin','iq4_nl.bin')) else None
            elif current and line.startswith(('Rss:','Locked:','Anonymous:','Swap:')):
                k,v=line.split(':',1);current[k]=v.strip()
        if current:maps.append(current)
        record['model_mappings']=maps;record['runtime_library_paths']=sorted(libraries);out['processes'].append(record)
    except (FileNotFoundError,PermissionError):continue
for d in Path('/sys/bus/pci/devices').iterdir():
    if not (d/'mem_info_vram_total').exists():continue
    gpu={'bdf':d.name,'device_path':str(d.resolve())}
    for n in ('mem_info_vram_total','mem_info_vram_used','mem_info_gtt_used','gpu_busy_percent','pp_dpm_sclk','pp_dpm_mclk'):
        try:gpu[n]=(d/n).read_text().strip()
        except OSError:pass
    out['gpus'].append(gpu)
cg=Path('/sys/fs/cgroup')
for n in ('memory.current','memory.peak','memory.events','memory.stat'):
    try:out[n]=(cg/n).read_text()
    except OSError:pass
out['host_mem_available']=next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
print(json.dumps(out,indent=2))
