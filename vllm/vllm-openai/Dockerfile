ARG VLLM_BASE_IMAGE=vllm/vllm-openai@sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1
FROM ${VLLM_BASE_IMAGE}

ARG GGUF_PLUGIN_COMMIT=d4c1f0d082fc7cd4350da56689109a01c1f29d6c

LABEL org.opencontainers.image.description="vLLM 0.29.0 with the out-of-tree GGUF CUDA plugin for Cogito"
LABEL org.opencontainers.image.source="https://github.com/timblakely/cogito"
LABEL inference.cogito.dev/vllm-version="0.29.0"
LABEL inference.cogito.dev/gguf-plugin-commit="${GGUF_PLUGIN_COMMIT}"

# Build only the Ampere kernel needed by iggy. The plugin must be compiled
# against the exact PyTorch/CUDA installation in the serving image, so this is
# intentionally an image build rather than a pod-startup pip install.
ENV TORCH_CUDA_ARCH_LIST=8.6 \
    MAX_JOBS=2 \
    VLLM_GGUF_PLUGIN_LOCAL_VERSION_SUFFIX=git.d4c1f0d

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && git clone https://github.com/vllm-project/vllm-gguf-plugin.git /tmp/vllm-gguf-plugin \
    && git -C /tmp/vllm-gguf-plugin checkout --detach "${GGUF_PLUGIN_COMMIT}" \
    && test "$(git -C /tmp/vllm-gguf-plugin rev-parse HEAD)" = "${GGUF_PLUGIN_COMMIT}" \
    && python3 -m pip install --no-cache-dir 'gguf==0.19.0' \
    && python3 -m pip install --no-cache-dir --no-build-isolation --no-deps /tmp/vllm-gguf-plugin \
    && python3 -c 'from importlib.metadata import version; assert version("vllm") == "0.29.0"; assert version("nvidia-nccl-cu13") == "2.30.7"; import vllm_gguf_plugin.ops' \
    && rm -rf /tmp/vllm-gguf-plugin /var/lib/apt/lists/*
