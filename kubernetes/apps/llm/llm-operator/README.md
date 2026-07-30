# llm-operator

Flux installs the operator from the pinned OCI chart in `app/repo.yaml`. It
started in observation mode and now owns the completed M5 non-production
Gemma activation:

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
The configured but absent `llm-llama-cpp` backend still causes non-blocking
proxy refresh warnings and is tracked separately.

## Remaining observation work

1. Maintain a sustained observation window and periodically record the
   `LLMBackend`, `LLMModel`, and overlay conditions alongside the live workload
   replicas, arguments, annotations, proxy health, and manager logs.
2. Treat any change to backend/proxy replicas, arguments, cache-manager state,
   or activation annotations as a failed passive-observation invariant until
   explained.
3. Resolve the pre-existing Fable proxy/catalog drift documented in
   `resources/README.md` separately; do not add it to the CR set as a shortcut.
4. TODO: add runtime/container integration coverage for successful and failed
   transitions, including cache-manager interaction, backend rollout/health,
   and handoff rollback.
