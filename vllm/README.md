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

## Proxy model catalog migration

The vLLM proxy reads `LLMModel` and `LLMModelOverlay` resources first, then
uses the existing labeled model and overlay ConfigMaps as a compatibility
fallback. A CR with the same logical model or overlay name is authoritative;
the legacy ConfigMap is skipped rather than changing the catalog entry.

The proxy has read-only RBAC (`get`, `list`, and `watch`) for the two operator
CRDs. It never writes CR status or spec. The catalog exposes each entry's
`metadata.config_source`, and migration diagnostics are available at
`GET /vllm-proxy/catalog-diagnostics` and as
`vllm_proxy_catalog_diagnostics`. Invalid legacy ConfigMaps are isolated and
reported there instead of blocking valid CR-backed catalog entries.

Before retiring a ConfigMap, compare the proxy `/v1/models` catalog and
diagnostics with the matching CR resource, including model identity, backend,
context limit, arguments, artifact metadata, and overlays. The original
comparison ran with transitions disabled; CR reads alone do not authorize
backend or proxy workload changes.

## Accepted Gemma activation

The M4 catalog rollout intentionally activated the canonical Gemma backend.
`llm-vllm` is accepted at one Ready replica serving
`google/gemma-4-31B-it-qat-w4a16-ct` revision
`52f3f65bc7a02d555763bc923bd1d9094898219d`. The proxy's CR-first catalog and
the hot cache artifact were verified during activation; Laguna remains scaled
to zero and unchanged.

This describes the accepted M4 state; it was superseded by the M5 operator
handoff below.

## Accepted non-production comparison

The M4 comparison accepts CR-first operation for the following equivalent
legacy/CR pairs: canonical Gemma, AWQ Gemma, AutoRound Qwen, and Laguna, plus
the `gemma4-agentic` overlay. For each supported entry, model identity, source,
revision, backend, display name, context limit, ordered serving arguments, and
Laguna artifact metadata match. The overlay retains its Gemma base and request
defaults.

The live catalog exposes these entries with `config_source=crd/...`. The
diagnostics endpoint records the corresponding legacy ConfigMaps as skipped by
CR precedence, which is expected during migration. Keep those ConfigMaps in
place as a rollback path; this comparison does not authorize their retirement.

Fable Fusion and its three overlays remain deferred pending a separately
supported backend/catalog path.

## M5 non-production transition handoff

The M5 handoff is complete in the non-production cluster. The standalone
`cache-manager` Deployment and Service are now in use; the proxy is configured
with `CACHE_MANAGER_URL=http://cache-manager:8090` and no longer carries a
cache-manager sidecar. The Hugging Face and Laguna hot caches remain hostpath
`ReadWriteOnce` claims, so cache-manager and vLLM stay pinned to `iggy`.

`ENABLE_DEPLOYMENT_MUTATIONS=false` leaves the proxy serving the CR-first
catalog and overlays without patching backend Deployments. The operator owns
the `LLMActiveModel/default` activation of canonical Gemma. The accepted result
is a stable one-replica `llm-vllm`, a hot cache ensure, and
`LLMBackend/vllm` phase `Serving`; Laguna remains at zero replicas.

TODO: add runtime/container integration coverage for both successful and
failed transitions, including cache-manager interaction, rollout readiness,
and the handoff/rollback behavior.
