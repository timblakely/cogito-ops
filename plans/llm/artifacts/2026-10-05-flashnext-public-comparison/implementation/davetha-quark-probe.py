import importlib.util,json,time
from pathlib import Path
import torch
assert importlib.util.find_spec('aiter') is None
import r4d,quark
assert '/app/r4dhip/' in r4d.__file__,r4d.__file__
assert 'davetha-compat-local/deps/quark/' in quark.__file__,quark.__file__
from quark.torch.kernel import mx
from vllm.model_executor.layers.quantization.utils.mxfp4_utils import dequant_mxfp4
print('PRESERVED_PACKAGES',quark.__file__,r4d.__file__,mx.dq_mxfp4.__module__,flush=True)
results=[]
lut=torch.tensor([0,.5,1,1.5,2,3,4,6,0,-.5,-1,-1.5,-2,-3,-4,-6])
for device in range(torch.cuda.device_count()):
 torch.cuda.set_device(device)
 # Cover every signed E2M1 nibble and two power-of-two block scales.
 packed=torch.arange(256,dtype=torch.int32).to(torch.uint8).repeat(8).reshape(32,64)
 scale=torch.full((32,4),127,dtype=torch.uint8);scale[:,2:]=128
 ref=torch.stack((lut[(packed & 15).long()],lut[(packed >> 4).long()]),dim=-1).reshape(32,128)
 ref*=torch.pow(2.,scale.float()-127).repeat_interleave(32,dim=-1)
 for dtype in (torch.float16,torch.bfloat16):
  actual=dequant_mxfp4(packed.to(f'cuda:{device}'),scale.to(f'cuda:{device}'),dtype)
  torch.cuda.synchronize()
  assert torch.isfinite(actual).all()
  torch.testing.assert_close(actual.cpu().float(),ref,rtol=0,atol=0)
  result={'device':device,'dtype':str(dtype),'shape':list(actual.shape),'max_abs_error':0,'pass':True}
  results.append(result);print('MXFP4_CUSTOM_OP_PASS',result,flush=True)
proof={'time_unix':time.time(),'aiter_available':False,'quark_path':quark.__file__,'r4d_path':r4d.__file__,'dequant_impl':mx.dq_mxfp4.__module__,'tests':results}
Path('/workspace/flashnext-competition/results/davetha-quark-gpu-probe.json').write_text(json.dumps(proof,indent=2)+'\n')
print('ALL_MXFP4_CUSTOM_OP_TESTS_PASS',flush=True)
