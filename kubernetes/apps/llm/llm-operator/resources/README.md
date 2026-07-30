# Reviewed LLM resources

This directory contains the reviewed, observation-only Cogito resources. Flux
reconciles it through a Kustomization that depends on the `llm-operator` app,
so the bundled CRDs are available first.

The passive rollout completed successfully on 2026-07-29 with chart `0.1.2`.
The two `LLMBackend` resources observe the intentionally stopped (zero-replica)
backends, all four `LLMModel` resources are `Ready` with
`ModelConfigured=True`, and the Gemma overlay is valid. These resources only
publish status; they have not changed backend or proxy workloads.

The inventory supports two backends (`llm-vllm` and `laguna`), four valid
models, and the Gemma overlay. Each model has an explicit backend reference;
there is no `LLMActiveModel` resource in this set.

The Fable Fusion model and its three overlays are intentionally excluded. Its
existing ConfigMap declares the unsupported `llama-cpp-vanilla` backend and
contains a controller-injected `--model` argument. The current proxy rejects
that entry and also looks for the non-existent `llm-llama-cpp` Deployment. The
live `llm-vllm` annotation also says Gemma while its arguments load Fable.
These are pre-existing proxy/catalog drift issues, not observation-mode
findings to be masked by CR migration.

Observation mode permits status reconciliation but must not mutate backend
Deployments. `transitions.enabled` remains false; do not add an
`LLMActiveModel` until a sustained observation window and the separate
transition-safety gate are approved. During that window, compare CR conditions
with the live backend/proxy state and investigate any change to replicas,
arguments, cache-manager state, or active-model annotations.
