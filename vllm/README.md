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

The Gemma 4 canonical chat template is mounted into the vLLM pod from the LLM app's ConfigMap; it does not require a derived vLLM image. Its source is `google/gemma-4-31B-it@b9ea41a2887d8607f594846523f94c6cc75ac8a4` (SHA256 `ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4`).
