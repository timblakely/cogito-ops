import json,time
from pathlib import Path
import torch
from vllm import ir
from vllm.config import VllmConfig,set_current_vllm_config
from vllm.model_executor.layers.layernorm import GemmaRMSNorm,GEMMA_NORM_FUSED,_fused_norm_impl
assert GEMMA_NORM_FUSED==2
results=[]
with set_current_vllm_config(VllmConfig()):
 for device in range(torch.cuda.device_count()):
  torch.cuda.set_device(device);torch.manual_seed(7)
  for rows,width in ((1,128),(4,512),(16,4096),(4096,256)):
   with torch.inference_mode():
    norm=GemmaRMSNorm(width).to(device=f'cuda:{device}',dtype=torch.bfloat16);norm.weight.copy_(torch.randn_like(norm.weight)*.05)
    x=torch.randn(rows,width,device=f'cuda:{device}',dtype=torch.bfloat16)
    actual=norm._try_fused(x,None);assert actual is not None,'mode2 did not select a fused implementation'
    reference=ir.ops.rms_norm.impls['native'].func_impl_fn(x,norm.weight.float()+1.,norm.variance_epsilon)
    torch.cuda.synchronize();assert torch.isfinite(actual).all()
    changed=int((actual!=reference).sum());fraction=changed/actual.numel()
    torch.testing.assert_close(actual,reference,rtol=.008,atol=0)
    assert fraction<=.001,(rows,width,changed,fraction)
    impl=_fused_norm_impl(ir.ops.rms_norm)
    rec={'device':device,'rows':rows,'width':width,'implementation':next(name for name,value in ir.ops.rms_norm.impls.items() if value is impl),'changed_elements':changed,'elements':actual.numel(),'changed_fraction':fraction,'max_abs_error':float((actual.float()-reference.float()).abs().max()),'pass':True}
    results.append(rec);print('FUSED_NORM2_GPU_PASS',rec,flush=True)
proof={'mode':2,'time_unix':time.time(),'qualification':'Published Gemma norm mode2 must use a real fused implementation, remain finite, stay within one BF16 relative ULP, and differ from the native decomposition in at most 0.1% of sampled elements. This is a bounded numerical probe, not a bit-exact model-output claim.','tests':results}
Path('/workspace/flashnext-competition/results/davetha-norm2-gpu-probe.json').write_text(json.dumps(proof,indent=2)+'\n');print('ALL_FUSED_NORM2_TESTS_PASS',flush=True)
