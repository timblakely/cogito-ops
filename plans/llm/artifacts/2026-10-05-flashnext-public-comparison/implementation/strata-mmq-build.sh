set -euo pipefail
cd /workspace/flashnext-competition/strata
export LD_LIBRARY_PATH=/opt/rocm/core-7.14/lib:/opt/rocm/lib
mkdir -p /archive/llmkube/flashnext-iggy/build-provenance/strata-mmq
cmake -S src -B build -DSTRATA_BUILD_TESTS=ON -DSTRATA_PREFILL_MMQ=ON -DSTRATA_PORTABLE=ON -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AMX=OFF > /archive/llmkube/flashnext-iggy/build-provenance/strata-mmq/configure.log 2>&1
cmake --build build --target strata hip_prefill_mmq_parity hip_prompt_attn_wmma hip_router_fast -j 4 > /archive/llmkube/flashnext-iggy/build-provenance/strata-mmq/build.log 2>&1
python3 - <<'PY'
import hashlib,json,tarfile
from pathlib import Path
root=Path('/workspace/flashnext-competition/strata');files=[p for p in (root/'build').rglob('*') if p.is_file() and ('.so' in p.name or p.name in ('strata','hip_prefill_mmq_parity','hip_prompt_attn_wmma','hip_router_fast','CMakeCache.txt'))]
out=Path('/archive/llmkube/flashnext-iggy');sha={str(p.relative_to(root)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in files};(out/'build-provenance/strata-mmq/checksums.json').write_text(json.dumps(sha,indent=2)+'\n')
with tarfile.open(out/'strata-mmq-runtime.tar.gz','w:gz') as t:
 for p in files:t.add(p,arcname=str(p.relative_to(root)),recursive=False)
print('STRATA_MMQ_RUNTIME_PACKED',len(files),flush=True)
PY
