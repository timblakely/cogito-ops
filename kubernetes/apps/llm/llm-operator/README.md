# llm-operator

Flux installs the operator from the pinned OCI chart in `app/repo.yaml`. It
started in observation mode and now owns the completed M5–M7
non-production control plane:

- the controller image is digest-only;
- leader election is enabled across two replicas;
- `transitions.enabled` is enabled for the reviewed handoff;
- cache-manager uses `http://cache-manager:8090`; and
- Helm creates or replaces the bundled CRDs on install and upgrade.

## Historical passive-observation status

The initial passive-observation rollout was verified live on 2026-07-29:

- chart `0.1.2` is pinned to OCI digest
  `sha256:02893675f50e7c41a6ec0254c1e47fc699f2981d7371bdf8485e542405a985d4`;
- the manager image is pinned to
  `sha256:56863a45d3c63d11eadb5d08330deb3ea7dc4e74b8ca399a38d0f9e858e6a596`;
- both the `llm-operator` and `llm-operator-resources` Flux Kustomizations are
  Ready and Healthy, with the latter depending on the former;
- the OCIRepository and HelmRelease are Ready, and the two manager pods are
  Running and Ready; and
- the live Deployment still contains `--enable-transitions=false`.

The observation resource set is reconciled successfully: two `LLMBackend`
objects report their zero-replica backends as `Stopped`, four `LLMModel` objects
report `ModelConfigured=True` and phase `Ready`, and the Gemma overlay reports
`OverlayValid=True`. There was deliberately no `LLMActiveModel` during this
historical passive phase.

The initial passive rollout did not alter the vLLM or Laguna replicas, container
arguments, or active-model annotations, and did not alter the proxy workload.
The manager Deployment rolled only to install the reviewed image.

M5 completed the operator handoff in non-production: `LLMActiveModel/default`
owns canonical Gemma, the proxy is read-only, the standalone cache-manager
returns a hot ensure, and `llm-vllm` is stable at one Ready replica with
`LLMBackend/vllm` phase `Serving`. Laguna remains unchanged at zero replicas.
M6 completed the CR-only catalog: legacy model/overlay ConfigMaps were deleted,
the proxy has read-only Deployment access, and runtime/model-card observations
are retained only in `llm-model-status` using ConfigMap-safe CR-source keys.

M7 validated the registered Laguna llama.cpp backend: its GGUF artifacts were
already hot, the operator transitioned from vLLM Gemma in about 40 seconds,
the proxy served a completion, and `LLMBackend/laguna` converged to `Serving`.
M8 then validated proxy-to-operator model selection with Qwen and Gemma: the
proxy requests `LLMActiveModel/default`, waits for the operator transition,
and serves the original request. Gemma/vLLM is currently active; Laguna is
scaled to zero.

## Remaining follow-up

1. TODO: add runtime/container integration coverage for successful and failed
   transitions, including cache-manager interaction, backend rollout/health,
   and handoff rollback.
2. TODO: exercise and document a repeatable rollback path before any
   production cutover.
3. Potential TODO: wire the opt-in admission webhook to certificate-managed
   TLS and validate rejection end-to-end before production use.
4. Potential TODO: add additional backend instances, such as SGLang, through
   the same CRD and GitOps workflow.
