# LLM Operator Runbook

## M6 observation phase

The operator is the sole reconciler for `LLMModel`, `LLMModelOverlay`,
`LLMBackend`, and `ActiveModel`. The vLLM proxy is read-only and serves the
CR-backed catalog; it must not be used to transition models.

Healthy state: both manager Pods are ready, `ActiveModel/default` reports
`Stable`, the selected `LLMBackend` reports `Serving`, and the operator
ServiceMonitor is scraped.

Investigate a transition failure with `kubectl get activemodel,llmbackend -n
llm` and the `LLMOperatorTransitionFailed` alert/dashboard. Do not patch a
runtime Deployment to recover it: correct the CR desired state and let Flux
and the operator reconcile.

Rollback a bad catalog or operator promotion by reverting the Cogito Git
change, then wait for the Flux Kustomization and HelmRelease to become Ready.
Keep the image and chart OCI digests pinned in Git.
