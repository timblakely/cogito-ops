# vLLM Proxy Runbook

## M6 CR-only catalog

The proxy reads only `LLMModel` and `LLMModelOverlay` resources. Legacy model
and overlay ConfigMaps have been retired and must not be recreated. Runtime
observations belong in the proxy-owned `llm-model-status` ConfigMap, keyed by
the immutable CR source. Because ConfigMap data keys cannot contain `/`, a
source such as `crd/<LLMModel resource name>` is encoded as
`crd__<LLMModel resource name>` in the key; desired model data remains
Flux-owned.

M6 used the one-shot `llm-legacy-catalog-prune-v3` Job to delete only the nine
audited ConfigMaps orphaned by the historical non-pruning parent
Kustomization. It completed successfully. Keep its narrowly scoped RBAC and
manifest in Git as an audit record; it is idempotent and does not touch
`llm-model-status`.

Confirm the active serving path with `kubectl get activemodel,llmbackend -n
llm`, then check the `llm-vllm` Deployment and proxy `/v1/models` catalog. An
unknown model or overlay means the corresponding CR is missing or invalid;
fix the CR and allow the operator to reconcile rather than editing the
Deployment or status ConfigMap.

The proxy runs with deployment mutations disabled during observation. Its
remaining Deployment access is read-only so it can report the serving backend.
