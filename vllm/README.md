# vLLM deployment images

This directory contains locally built images used by the LLM deployment. The
OpenAI image is based on the digest-pinned vLLM 0.29.0 image and compiles the
out-of-tree vLLM GGUF plugin at its pinned commit for SM86. That supplies the
CUDA Q6_K target path used by the dual-3090 Qwen deployment.

Build or push an immutable image tag from a workstation authenticated to GHCR:

```sh
make -C vllm build-openai TAG=<tag>
make -C vllm push-openai TAG=<tag>
```

After pushing, pin the resulting digest in the relevant manifest instead of
using a mutable tag.

The `build-muse`/`push-muse` targets in the Makefile are retained as rollback
tooling; the active Qwen lane uses `vllm-openai`. The proxy and cache-manager
targets moved to `timblakely/llm-operator` before that stack was retired.
