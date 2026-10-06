#!/bin/bash
set -euo pipefail
cd /workspace/flashnext-competition/stew
python3 -m pip install cmake==4.4.4 > cmake-install.log 2>&1
export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH
export LD_LIBRARY_PATH=/opt/rocm/core-7.14/lib:/opt/rocm/lib
cmake -S src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DGPU_TARGETS=gfx1201 -DGGML_HIP_RCCL=ON -DGGML_HIP_GRAPHS=ON -DGGML_CUDA_FA=ON -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF -DGGML_NATIVE=OFF -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ > configure.log 2>&1
cmake --build build --target llama-server llama-bench -j 8 > build.log 2>&1
build/bin/llama-server --version > version.txt 2>&1
sha256sum build/bin/llama-server build/bin/lib*.so* > build.sha256
printf 'BUILD_COMPLETE\n'
