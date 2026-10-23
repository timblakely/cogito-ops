# Vision lanes: auditing and retiring one

## Status (2026-10-23): the CPU vision path is gone

Retired in `e117d353` + `e54742a5`. Catalogue afterwards: **8 modelNames (coder,
embedder, flashnext-deleuze, gemma-4-12b, muse-glimmer-30b, qwen3-8-27b, reranker,
worker), 5 keys (coder, hermes, open-webui, pi, worker)**, no `image`/`vision` alias.
`muse-glimmer-30b` stays Hermes' `auxiliary.vision` model; `gemma-4-12b` is the other
GPU vision path. Verified by NotFound on `litellmmodels/image`,
`litellmvirtualkeys/image`, `secret/litellm-key-image` + its PushSecret,
`litellmmodels/vision`, `inferenceservices/vision-cpu`.

`vision-cpu` itself was a 9B Qwen-derived GGUF llama.cpp on plain CPU at `--ngl 0`,
16Gi request / 24Gi limit, on **kristeva** (`kubectl get pod -o wide` — not nuc-3; the
`model-caps.yaml` "Nuc-3" prose is stale). A 1080p screenshot cost ~136 s and the
container had no GPU runtime, so the Arc A380 sat unused. Its `cache-prime-vision-v1`
Job went with it. The `llm-model-archive` PVC survived (owned by `model-archive.yaml`,
mounted by seven other workloads) — deleting a lane never GC'd weights, so the archive
still carries the CPU lane's GGUF.

## Auditing a lane before deleting it

`spec.models[].modelInfo.id` is what LiteLLM writes into `"LiteLLM_SpendLogs"."model"`,
so usage history survives the alias:

```bash
kubectl -n llm exec litellm-db-1 -c postgres -- psql -U postgres -d app -At -F'|' -c \
  "SELECT s.model, 'K: '||v.key_name, count(*) FROM \"LiteLLM_SpendLogs\" s \
   LEFT JOIN \"LiteLLM_VerificationToken\" v ON v.token = s.\"api_key\" \
   GROUP BY 1,2 ORDER BY 3 DESC;"
```

The database is `app`, not `litellm` (`\l` to list). `vision-cpu` had 12 calls in two
months; the dedicated `role-image` key had **zero**. Prefix opaque strings with a
literal (`'K: '||v.key_name`) so terminal redaction can't make a row ambiguous.

## Live contracts hide behind zero spend

Deleting the alias would have crash-looped `home-infra/gateway`: `service.py` resolved
`os.environ["LITELLM_IMAGE_API_KEY"]` at construction, so a missing key is a start-up
KeyError in CrashLoopBackOff, not a degraded feature. The maubot plugin sent an `image`
dict only when a Matrix event carried an `m.image` attachment — live but never used.
**Grep the consumers before deleting a model or alias; spend logs alone call a route
dead when it is only idle.**

## Ordering a removal has to follow

1. Land the code removal (service + plugin) and its tests.
2. Bump the image pin to the build of that commit — see skill `cogito-gateway-image-pin`.
3. Only then drop the alias / key / ExternalSecret entry.

The gateway read its key at import time, so pruning the `ExternalSecret` entry first
would crash-loop the *running* container on its next restart. PushSecret
`deletionPolicy: None` left the 1Password field untouched; `creationPolicy: Owner`
pruned it from the cluster Secret within one sync.

Retiring a model or key is a coordinated five-edit change: delete `models/*.yaml` and
`virtualkeys/*.yaml`, drop both `kustomization.yaml` entries, and remove the modelName
from **every** key scope — otherwise the catalogue validator fails the whole proxy.
Mark historical acceptance records (`kubernetes/acceptance/async-agentic-v4.md`)
superseded rather than rewriting the evidence they captured.

## Immich is not a LiteLLM consumer

Immich runs in `home-infra` and its only model reference is `ViT-B-32__openai`, Immich
ML's own CLIP, with no vision-language model configured — nothing there called `vision`
or `image`. (An earlier claim that Immich was absent from the cluster was wrong; it was
only absent from the `llm` namespace.)
