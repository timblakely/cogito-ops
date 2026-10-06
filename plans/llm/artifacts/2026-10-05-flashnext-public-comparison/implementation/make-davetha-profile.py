import json
from pathlib import Path

b=Path('/tmp/flashnext-competition');j=json.loads((b/'davetha-stage.json').read_text());j['metadata']['name']='flashnext-davetha-public';c=j['spec']['containers'][0]
root='/workspace/flashnext-competition';sdk='/ngram/davetha-sdk/_rocm_sdk_core'
env={
 'PYTHONPATH':f'/ngram/davetha-sdk:{sdk}/share/amd_smi',
 'ROCM_PATH':sdk,'ROCM_HOME':sdk,'HIP_PATH':sdk,
 'LD_LIBRARY_PATH':f'{root}:{sdk}/lib:{sdk}/lib/rocm_sysdeps/lib:{sdk}/lib/host-math/lib:/ngram/davetha-sdk/_rocm_sdk_libraries/lib:/usr/local/lib',
 'ROCR_VISIBLE_DEVICES':'0,1','HIP_VISIBLE_DEVICES':'0,1','HIP_FORCE_DEV_KERNARG':'1',
 'VLLM_NCCL_SO_PATH':f'{root}/librccl-nohostcall-2.27.7-multiarch.so',
 'VLLM_ROCM_USE_AITER':'0','VLLM_PLE_CPU_OFFLOAD':'1',
 'VLLM_R4D_HOT_PROFILE':f'{root}/davetha-profile/hot_profile.json','VLLM_R4D_HOT_GB':'15.0',
 'VLLM_R4D_LRU':'1','VLLM_R4D_LRU_FUSE':'1','R4D_LRU_LIB':f'{root}/davetha-kernels/librlu.so',
 'VLLM_R4D_SHARE_A8':'0','VLLM_GDN_STRIDED_QKV':'1','VLLM_FUSED_SHARED_GATE':'1',
 'VLLM_FUSED_SILU_QUANT':'1','VLLM_QSA_ROPE_GATHER':'1','VLLM_UVA_OFFLOAD_EMBED':'1',
 'VLLM_UVA_OFFLOAD_VISUAL':'1','VLLM_DRAFT_W4_LMHEAD':'1',
 'VLLM_R4D_MOE_CFG1':'1,2,4','VLLM_R4D_MOE_CFG2':'1,1,1','VLLM_TARGET_FP8_LMHEAD':'1',
 'VLLM_R4D_LRU_SKIP_EMPTY_COLD':'1','VLLM_GEMMA_NORM_FUSED':'0',
 'FLASHNEXT_PLE_NVME_PATH':'/ngram/davetha/ple-fp8.bin',
 'TRITON_CACHE_DIR':'/ngram/davetha-cache/triton','VLLM_CACHE_ROOT':'/ngram/davetha-cache/vllm',
}
c['env']=[{'name':k,'value':v} for k,v in env.items()]
c['resources']={'requests':{'cpu':'8','memory':'80Gi','amd.com/gpu':2},'limits':{'memory':'114Gi','amd.com/gpu':2}}
c['command']=['/bin/bash','-ec',f'cp -a {root}/davetha-overlays/vllm/. /app/vllm/vllm/; exec vllm serve "$@"','flashnext']
c['args']=['/archive/llmkube/flashnext-iggy/davetha-mxfp4','--served-model-name','qwen3.8-flash-next',
 '--tensor-parallel-size','2','--kv-cache-dtype','fp8','--cpu-offload-gb','40','--cpu-offload-params','experts',
 '--gpu-memory-utilization','.97','--max-model-len','262144','--max-num-seqs','4','--max-num-batched-tokens','4096',
 '--enable-prefix-caching','--enable-chunked-prefill','--reasoning-parser','qwen3','--enable-auto-tool-choice',
 '--tool-call-parser','qwen3_coder','--limit-mm-per-prompt.image','8','--limit-mm-per-prompt.video','1',
 '--mm-processor-cache-gb','.5','--speculative-config',json.dumps({'method':'mtp','num_speculative_tokens':4}),
 '--chat-template',f'{root}/davetha-templates/qwen_fixed_chat_template.jinja','--host','0.0.0.0','--port','8000']
c['readinessProbe']={'httpGet':{'path':'/health','port':8000},'periodSeconds':10}
(b/'davetha-public.json').write_text(json.dumps(j,indent=2)+'\n')
