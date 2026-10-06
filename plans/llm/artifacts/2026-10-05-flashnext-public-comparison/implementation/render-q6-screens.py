"""Render Q6 measurements together with explicit human qualification decisions."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--decisions',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();decisions=json.loads(a.decisions.read_text())['profiles'];profiles=[('Tensor hybrid','stew-q6-cache-hybrid-replay'),('Tensor pure RCCL','stew-q6-cache-pure-rccl-loader'),('Layer wide','stew-q6-cache-layer-wide-loader'),('All-expert layer wide','stew-q6-all-cache-layer-wide-loader'),('Static split r15','stew-q6-classic-r15'),('Layer 4K microbatch retry','stew-q6-cache-layer-4k-loader'),('All-expert 4K / 2GiB reserve','stew-q6-all-cache-layer-4k-headroom'),('Layer 4K fast card first','stew-q6-cache-layer-4k-fast-first'),('Layer 4K eager host remap','stew-q6-cache-layer-4k-host-map')]
def read(n):
 f=a.root/'results'/(n+'.json');return json.loads(f.read_text()) if f.exists() else None
lines=['| Q6 screen | Warm short TG | 40K TTFT, median | 40K TG, median | 40K wall, median | Independent C2 long pair | Exact replay caps | C2 output qualification |','|---|---:|---:|---:|---:|---:|---|---|']
for title,name in profiles:
 j=read(name+'-common')
 if not j or len(j.get('trials',[]))!=6 or not all(t.get('ok') for t in j['trials']):continue
 short=[t for t in j['trials'] if t['label'].startswith('common1500')][1:];long=[t for t in j['trials'] if t['label'].startswith('common40890')]
 value=lambda ts,key:f'{statistics.median(t[key] for t in ts):.2f}'
 c2=read(name+'-c2');pair='—'
 if c2 and len(c2.get('trials',[]))==4:
  ls=[t for t in c2['trials'] if t['label'].startswith('common40890')]
  if all(t.get('ok') for t in ls):pair=f'{max(t["wall_s"] for t in ls):.2f} s; '+','.join(str(t['usage']['completion_tokens']) for t in ls)+' tokens'
 replay=read(name+'-replay');caps='—'
 if replay and len(replay.get('replays',[]))==3:
  ts=replay.get('initial_together',[])+[t for rr in replay['replays'] for mode in ('alone','together') for t in rr[mode]];caps=f'{sum(t.get("ok") and t["usage"]["completion_tokens"]==256 for t in ts)}/{len(ts)} reach 256'
 d=decisions.get(name,{});q='Reviewed pass' if d.get('c2_qualified') is True else 'Rejected: '+d.get('c2_failure_kind','output failure') if d.get('c2_qualified') is False else 'Review pending'
 lines.append('| '+' | '.join([title,value(short,'legacy_decode_tok_s'),value(long,'ttft_s')+' s',value(long,'legacy_decode_tok_s'),value(long,'wall_s')+' s',pair,caps,q])+' |')
a.output.write_text('\n'.join(lines)+'\n');print('Q6_SCREEN_ROWS',len(lines)-2)
