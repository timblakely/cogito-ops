import ctypes,sys,json,shutil
shutil.copytree('/workspace/flashnext-competition/davetha-overlays/vllm','/app/vllm/vllm',dirs_exist_ok=True)
import torch
print('TORCH_CPU_ABI',torch.__version__,torch.version.hip,flush=True)
ctypes.CDLL('/app/fp8hip/libfp8hip_gemm.so');print('FP8HIP_CPU_LINK_OK',flush=True)
from vllm.model_executor.kernels import r4d_lib
print('R4D_CTYPES',r4d_lib.lib(),flush=True)
r=r4d_lib.import_r4d();assert r is not None;print('R4D_PYBIND_IMPORT_OK',flush=True)
from vllm import _custom_ops
import vllm._moe_C_stable_libtorch
print('VLLM_MOE_IMPORT_OK',flush=True)
