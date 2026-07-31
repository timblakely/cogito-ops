# Reviewed LLM resources

This directory contains the reviewed Cogito resources. Flux reconciles it
through a Kustomization that depends on the `llm-operator` app, so the bundled
CRDs are available first.

The passive rollout completed successfully on 2026-07-29. M5 subsequently
completed a stable operator-owned Gemma activation, and M6 retired the legacy
ConfigMap catalog. The active CR set is reconciled through Flux.

The inventory supports two backends (`llm-vllm` and `laguna`), four valid
models, the Gemma overlay, and `LLMActiveModel/default`. M7 completed the
operator-owned transition to `poolside/Laguna-S-2.1`: Laguna served through
the read-only proxy and cache-manager reported the GGUF artifacts hot. M8 then
validated proxy-requested Qwen and Gemma transitions; Gemma/vLLM is currently
Serving and Laguna is scaled to zero.

The Fable Fusion model and its three overlays are intentionally absent from the
CR catalog. Their legacy ConfigMaps were retired in M6; reintroduce them only
after defining a supported backend and valid model arguments as reviewed CRs.

TODO: add runtime/container integration coverage for both successful and
failed transitions, including cache-manager ensure behavior and rollback.
