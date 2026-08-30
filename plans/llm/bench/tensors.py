import sys, os
sys.path.insert(0,'/host/d4-qwen4exp/bench')
from ggufinfo import parse
import re
tot={}
allt=[]
for p in sys.argv[1:]:
    kv,tens = parse(p, False)
    fs=os.path.getsize(p)
    print(f'== {os.path.basename(p)}  size={fs/2**30:.2f} GiB  tensors={len(tens)}')
    s=0
    for t in tens: s+=t[5]
    print(f'   tensor bytes = {s/2**30:.2f} GiB')
    for t in tens: allt.append((os.path.basename(p),)+t)
# group by normalized name
g={}
for f,name,dims,tt,off,ne,nb in allt:
    key=re.sub(r'\.\d+\.', '.#.', name)
    d=g.setdefault((key,tt,tuple(dims)),[0,0,set()])
    d[0]+=1; d[1]+=nb; d[2].add(f[-12:-5])
print(f'\n{"tensor":<46}{"type":<8}{"dims":<24}{"n":>5}{"GiB":>9}  files')
for (key,tt,dims),(n,nb,fs) in sorted(g.items(), key=lambda x:-x[1][1]):
    print(f'{key:<46}{tt:<8}{str(list(dims)):<24}{n:>5}{nb/2**30:>9.2f}  {",".join(sorted(fs))}')
