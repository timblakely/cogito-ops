#!/usr/bin/env bash
set -eu
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 -m pip install 'cmake==4.4.4' > /tmp/cmake-install.log 2>&1
mkdir -p /workspace/flashnext-iggy/src
cd /workspace/flashnext-iggy
curl -fL --retry 3 https://api.github.com/repos/JohnTDI-cpu/llama.cpp-flash-next-rdna4/tarball/185252d1edb27fde6b332908eb7c89a20cadc4bb -o source.tar.gz
echo 'eb8d1fba5ec06127c96c000b7bc5edd83a149c9f8f3cf524a76a428ddf247319  source.tar.gz' | sha256sum -c -
sha256sum source.tar.gz > source.tar.gz.sha256
tar -xf source.tar.gz -C src --strip-components=1
python3 "$script_dir/fix_json_object.py" src
export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH
cmake -S src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DGGML_CUDA_FA=ON -DGGML_CUDA_GRAPHS=ON -DGGML_CUDA_COMPRESSION_MODE=size -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF -DGGML_NATIVE=OFF -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++
cmake --build build --target llama-server llama-bench -j 4
export LD_LIBRARY_PATH=/opt/rocm/core-7.14/lib:/opt/rocm/lib
build/bin/llama-server --version
sha256sum build/bin/llama-server build/bin/lib*.so* > build.sha256
# The planner loads metadata and reserves a graph with no_alloc; it does not
# load model weights or run a second inference server.
/opt/rocm/llvm/bin/clang++ -std=c++17 "$script_dir/memory-probe.cpp" \
  -I src/common -I src/include -I src/ggml/include -L build/bin \
  -Wl,-rpath,/workspace/flashnext-iggy/build/bin \
  -lllama-common -lllama -lggml -lggml-base -o memory-probe
