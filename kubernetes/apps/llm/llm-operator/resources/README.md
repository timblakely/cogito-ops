# Reviewed LLM resources

This directory contains the reviewed Cogito resources. Flux reconciles it
through a Kustomization that depends on the `llm-operator` app, so the bundled
CRDs are available first.

The passive rollout completed successfully on 2026-07-29. M5 subsequently
completed a stable operator-owned Gemma activation, and M6 retired the legacy
ConfigMap catalog. The active CR set is reconciled through Flux.

The inventory supports three operator-owned backends (`vllm-server`,
`laguna-server`, and the shared `llama-cpp-server`), five valid models, the Gemma overlay, and
`LLMActiveModel/default`. M7 completed the
operator-owned transition to `poolside/Laguna-S-2.1`: Laguna served through
the read-only proxy and cache-manager reported the GGUF artifacts hot. M8 then
validated proxy-requested Qwen and Gemma transitions; Gemma/vLLM is currently
Serving and Laguna is scaled to zero.

The Fable Fusion base model is present in the CR catalog and uses the shared
`llama-cpp-server` backend. Its legacy ConfigMaps and overlays were retired in
M6.

DeepSeek V4 Flash 0731 UD-IQ3_S is a 117 GiB, four-shard GGUF pinned to the
Unsloth commit recorded in its model CR. It uses the shared CUDA 13 llama.cpp
backend with the other GGUF models.
Its hybrid fitter keeps a minimum 140k-token context (`143360` tokens) and
maximizes offload across both GPUs, while 39 MoE layers remain in RAM. The
runtime requests 118 GiB RAM (with a 120 GiB cap) on `iggy`; do not activate
it until the node has enough allocatable memory for the model and the 140k KV
cache. It uses its own 140 GiB hostpath PVC because the pre-existing Laguna
PVC is only 100 GiB and its StorageClass does not allow expansion.

TODO: add runtime/container integration coverage for both successful and
failed transitions, including cache-manager ensure behavior and rollback.

## Managed templates (M9)

`kustomization.yaml` generates `qwen-fixed-chat-template` without a name
suffix because `LLMModel.spec.serving.chatTemplate` references its stable name.
The ConfigMap annotation and Qwen CR both pin the SHA-256 of the rendered file.
Update the vendored file, annotation, and CR digest together in one reviewed
change; do not use a request-level template override or allow the runtime to
fetch upstream content. Qwen keeps the `qwen3_coder` parser. The M9 rollout
validated this template against the captured Pi request: it returned a
structured `bash` tool call and completed the supplied tool-result turn.
