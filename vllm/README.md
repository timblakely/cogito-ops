# vLLM deployment images

This directory contains locally built images used by the LLM deployment.

Build or push an immutable image tag from a workstation authenticated to GHCR:

```sh
make -C vllm build-proxy TAG=<tag>
make -C vllm push-proxy TAG=<tag>
make -C vllm build-openai TAG=<tag>
make -C vllm push-openai TAG=<tag>
```

After pushing, pin the resulting tag in the relevant HelmRelease instead of using `latest`.

`vllm-openai` derives from the upstream `vllm/vllm-openai` image. Its patches must be version-pinned and documented under `vllm-openai/patches/`.
