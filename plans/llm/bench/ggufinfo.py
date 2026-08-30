import struct, sys, json

GT = {0:'u8',1:'i8',2:'u16',3:'i16',4:'u32',5:'i32',6:'f32',7:'bool',8:'str',9:'arr',10:'u64',11:'i64',12:'f64'}
FMT = {0:'<B',1:'<b',2:'<H',3:'<h',4:'<I',5:'<i',6:'<f',7:'<B',10:'<Q',11:'<q',12:'<d'}
SZ  = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}

TYPES={0:'F32',1:'F16',2:'Q4_0',3:'Q4_1',6:'Q5_0',7:'Q5_1',8:'Q8_0',9:'Q8_1',10:'Q2_K',11:'Q3_K',12:'Q4_K',13:'Q5_K',14:'Q6_K',15:'Q8_K',16:'IQ2_XXS',17:'IQ2_XS',18:'IQ3_XXS',19:'IQ1_S',20:'IQ4_NL',21:'IQ3_S',22:'IQ2_S',23:'IQ4_XS',24:'I8',25:'I16',26:'I32',27:'I64',28:'F64',29:'IQ1_M',30:'BF16',34:'TQ1_0',35:'TQ2_0',39:'MXFP4'}
BLK={'F32':(1,4),'F16':(1,2),'BF16':(1,2),'Q4_0':(32,18),'Q4_1':(32,20),'Q5_0':(32,22),'Q5_1':(32,24),'Q8_0':(32,34),'Q2_K':(256,84),'Q3_K':(256,110),'Q4_K':(256,144),'Q5_K':(256,176),'Q6_K':(256,210),'Q8_K':(256,292),'IQ4_NL':(32,18),'IQ4_XS':(256,136),'MXFP4':(32,17),'I32':(1,4),'I64':(1,8)}

class R:
    def __init__(s,f): s.f=f
    def u32(s): return struct.unpack('<I',s.f.read(4))[0]
    def u64(s): return struct.unpack('<Q',s.f.read(8))[0]
    def val(s,t):
        if t==8:
            n=s.u64(); return s.f.read(n).decode('utf-8','replace')
        if t==9:
            et=s.u32(); n=s.u64()
            return [s.val(et) for _ in range(n)]
        return struct.unpack(FMT[t], s.f.read(SZ[t]))[0]

def parse(path, dump_kv):
    f=open(path,'rb'); r=R(f)
    magic=f.read(4)
    assert magic==b'GGUF', magic
    ver=r.u32(); nten=r.u64(); nkv=r.u64()
    kv={}
    for _ in range(nkv):
        kl=r.u64(); k=f.read(kl).decode(); t=r.u32(); kv[k]=r.val(t)
    tensors=[]
    for _ in range(nten):
        nl=r.u64(); name=f.read(nl).decode()
        nd=r.u32(); dims=[r.u64() for _ in range(nd)]
        tt=r.u32(); off=r.u64()
        tn=TYPES.get(tt,f'T{tt}')
        ne=1
        for d in dims: ne*=d
        bs,bb = BLK.get(tn,(1,4))
        nbytes = ne//bs*bb
        tensors.append((name,dims,tn,off,ne,nbytes))
    if dump_kv:
        for k,v in kv.items():
            sv=str(v)
            if len(sv)>120: sv=sv[:120]+f'...(len {len(v) if hasattr(v,"__len__") else "?"})'
            print(f'  {k} = {sv}')
    return kv,tensors

if __name__=='__main__':
    kv,tens = parse(sys.argv[1], True)
    print(f'\n{len(tens)} tensors')
