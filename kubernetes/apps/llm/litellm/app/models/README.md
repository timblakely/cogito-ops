# LiteLLM model catalogue

One `LiteLLMModel` per client-facing alias, adopted by the `LiteLLMProxy` in
this app through `proxyRef`. These replace the inline `proxy_config.model_list`
that used to live in the HelmRelease.

## Why these are hand-written and not auto-registered

litellm-operator can mirror LLMKube `InferenceService` objects into
`LiteLLMModel` resources automatically (`llmkube.autoRegister`). It is off, and
must stay off: projected models are named after the InferenceService, so the
client-facing names become deployment names, and one projection per backend
cannot express this catalogue's shape — several aliases over one backend, each
with its own pinned effort, timeout and context budget. `modelName` here is an
arbitrary string, which is what lets the catalogue keep advertising the Hugging
Face-style identifier clients are already configured against.

## Current catalogue and key scopes

Read [kustomization.yaml](kustomization.yaml) for the models Flux
registers, the included model files for client-facing names, backends and
limits, and [virtualkeys/](../virtualkeys/) for declared key scopes. A YAML
file omitted from `kustomization.yaml` is not a served alias. For the actual
state, use `kubectl -n llm get litellmmodels` and
`kubectl -n llm get litellmvirtualkeys`; an existing key's scope in LiteLLM's
database can lag its edited resource (see the [Hermes README](../../../hermes/README.md)).

**Local routes.** Local entries point directly at their serving backend's
Service (there is no router in between; with one always-on backend there is
nothing to dispatch across), and the string after `openai/` is the served model
name. On the vLLM/radiance-served aliases that string must stay byte-identical
to the backend's served model name or the request 404s at the backend (the
radiance fleet's entry names, e.g. `qwen3.8-flash-next`, fill that role). The
llama.cpp lanes (embedder, reranker) launch without a served-model name at all
and ignore the model field, so theirs is a label rather than a key.

**ChatGPT subscription routes.** The eight public subscription models in
`kustomization.yaml` use LiteLLM's `chatgpt/` provider and the writable OAuth token at
`CHATGPT_TOKEN_DIR`. They do not use OpenAI API credits; `litellm-secrets` carries
no `OPENAI_API_KEY` at all. Model IDs and product reasoning tiers come from the
authenticated `https://chatgpt.com/backend-api/codex/models` catalogue using the
tested `client_version=0.169.0` query. The `model-caps` publisher reads the shared
token **read-only**, fetches metadata every 15 minutes, and joins it to the
proxy's registered `chatgpt/` routes. It never logs credentials or response bodies,
refreshes OAuth, registers routes, or rewrites GitOps resources.

The sanitized `../model-caps/openai-models.json` is a cold-start fallback; a failed
fetch retains last-known-good metadata. `/caps/v1/models` publishes freshness and
visible-but-unregistered IDs under `openai_catalogue`, so new releases do not stay
invisible while registration/key scope remains an explicit GitOps change. The
November live catalogue contains eight public models plus two hidden/internal IDs;
only the eight public models are registered.

Product tiers are not identical to wire tiers: `ultra` orchestrates multi-agent
work in OpenAI's client and resolves to another wire effort. It is preserved as
product metadata but never advertised as a sendable `reasoning.effort`. The
product picker also omits Off on models with a working off switch, so separately
verified `none` overrides are preserved: six public models accept Off; Astra and
6.1 Sol reject it. Local-runtime controls
remain curated/probed; an OpenAI catalogue does not describe those backends.

Subscription models ride the dedicated `hermes-subscription` virtual key and are
deliberately absent from the shared `hermes` key: LiteLLM
filters `/v1/models` by key scope, so leaving them on `hermes` made a
chat-completions client discover them *and* its Responses provider list them again.
Paseo's Hermes agent uses a separate Responses provider for these models because
Astra and Sol require the Responses API for tool calls. The per-model effort
lists are published by `model-caps.yaml`; do not create one LiteLLM alias per
effort. Subscription usage is reported as zero-dollar spend by LiteLLM, so a
virtual key's dollar budget does not limit subscription requests.

The proxy mounts `chatgpt-recovery/sitecustomize.py` through a ConfigMap. On
LiteLLM 1.105.5, a ChatGPT plan or security change can revoke an access token
before its stored expiry; LiteLLM otherwise keeps sending it until expiry. The
hook recognizes only the upstream `401 token_expired` response, locks the shared
token volume, refreshes once, and retries the request once. Other errors pass
through. If the refresh token is also rejected, an operator must complete the
ChatGPT device login again; `LiteLLMChatGPTAuthFailure` alerts on the unrecovered
401. Remove the hook when the pinned LiteLLM release handles early revocation.

Local models declare `input_cost_per_token: 0` / `output_cost_per_token: 0`.
Not cosmetic: LiteLLM raises "This model isn't mapped yet" inside spend
calculation for any `openai/<slug>` missing from its cost map, so the choice is
between an asserted zero and a per-request error with no ledger entry.

The former role-seat aliases were retired in October 2026. Their history is in
[the dated cleanup inventory](../../../../../../plans/docs-cleanup-2026-10-23.md).
The gateway code still has old planning defaults; follow its
[runbook](../../../../../../services/gateway/RUNBOOK.md) before using planning.
Give a component that needs narrower access its own `LiteLLMVirtualKey`.

## Where the escape hatches are

The CRD types the common `model_info` and `litellm_params` fields, and passes
anything else through verbatim:

| Setting | Lands in | Why it is not typed |
| --- | --- | --- |
| `allowed_openai_params` | `params.additional` | LiteLLM-specific, not a provider param |
| `chat_template_kwargs` | `params.additional` | passthrough request kwarg |
| `supports_reasoning` | `info.extra` | the CRD types vision/tools/caching, not reasoning |
| `thinking_levels` | `info.extra` | non-standard; read by the pi `llm-proxy-refresh` extension |
| `supportsVision` | `info` (typed) | modalities come from the proxy, not from each client's config |
| `input_cost_per_token` | `info.extra` | cost keys are not typed |

## What `thinking_levels` means

It is not "what the chat template accepts". It is **what a client may choose**,
and the two differ whenever an alias pins `reasoning_effort` in
`params.additional`.

Measured 2026-08-28: a server-side `reasoning_effort` overwrites whatever the
client puts in `chat_template_kwargs`. The clean proof is the template-invalid
value `high` — sent to `worker` it returns 200, because the pin replaced it
before the template ever saw it; sent to `Qwen/Qwen3.8-27B-INT8-W8A16`, which pins
nothing, it 400s out of the Jinja. `enable_thinking` is *not* overwritten (the
pin does not set it), so a client can still turn thinking off on a pinned alias.

So the rule is:

- **Pins no effort** → publish only the levels the template accepts.
- **Pins an effort** → publish only that level. Anything else would advertise a
  control that silently does nothing.
- **Publishes no `thinking_levels`** → clients should not offer an effort picker.

Check the included model files for current values; the August 2026 measurement
above explains the rule, not the current catalogue.

## Adding or changing a model

A new local model is a `Model` + `InferenceService` in `llmkube/resources/`
and a file here. The catalogue is still declared twice — once as serving config, once as proxy
config — and `maxInputTokens` in particular must mirror the backend's
`maxModelLen` (vLLM) or `contextSize` (llama.cpp). Auto-registration is the only
thing that would collapse that duplication, and it is unusable here, so the
mirroring is a standing maintenance cost rather than a bug to fix.

The mirror is not strict equality in one direction. An alias may advertise
**less** than its backend serves, and `scripts/validate-llm-catalogue.py`
treats an unexplained difference as the accident it usually is. It only
compares when it can read the backend value, so a lane that carries its
context in a raw engine argument — the raw `--max-model-len`/`--ctx-size` of a
generic-runtime lane is invisible to it (the radiance fleet entries are all
hand-mirrored this way). When changing an engine's raw context flag, inspect
every included alias that points to that backend and update its
`maxInputTokens` deliberately. An alias holding a smaller window than its
backend on purpose carries the annotation:

```yaml
metadata:
  annotations:
    cogito.dev/context-budget: deliberate
```

Advertising **more** than a backend whose context the validator can read is
always an error and has no annotation: the client is told it may send a prompt
vLLM will refuse.
