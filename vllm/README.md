# vLLM deployment images

This directory contains locally built images used by the LLM deployment.

Build or push an immutable image tag from a workstation authenticated to GHCR:

```sh
make -C vllm build-openai TAG=<tag>
make -C vllm push-openai TAG=<tag>
```

After pushing, pin the resulting tag in the relevant manifest instead of using
`latest`.

Nothing in the cluster currently references these images: serving runs the
upstream `vllm/vllm-openai` and `ghcr.io/ggml-org/llama.cpp` images. The
`build-muse`/`push-muse` targets in the Makefile are kept for Wave 4's Muse
roster (plans/llm/plan.md G7); the proxy and cache-manager targets moved to
`timblakely/llm-operator` before that stack was retired.
