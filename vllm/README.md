# vLLM deployment images

This directory contains locally built images used by the LLM deployment.

Build or push an immutable image tag from a workstation authenticated to GHCR:

```sh
make -C vllm build-openai TAG=<tag>
make -C vllm push-openai TAG=<tag>
```

After pushing, pin the resulting tag in the relevant manifest instead of using
`latest`.

Nothing in the cluster currently references these images: serving pulls the
upstream `vllm/vllm-openai` and `ghcr.io/ggml-org/llama.cpp` images plus the
third-party `docker.io/stilldeadcode/radiance` engine. The
`build-muse`/`push-muse` and `build-laguna`/`push-laguna` Makefile targets are
kept for the Wave 4 Muse/Laguna roster that never shipped — that roster was
defined as item G7 of `plans/llm/plan.md`, and the plan file is no longer in the
repo, so the targets have no live consumer. The proxy and cache-manager targets
moved to `timblakely/llm-operator` before that stack was retired.
