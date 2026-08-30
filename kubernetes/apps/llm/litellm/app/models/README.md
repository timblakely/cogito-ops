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

## The two tiers

**Local** — every entry points directly at its InferenceService's Service
(there is no router in between; with one always-on backend there is nothing to
dispatch across), and the string after `openai/` is the served model name. On
the vLLM-served Qwen aliases that string must stay byte-identical to the
backend's `--served-model-name` or the request 404s at the backend. The
llama.cpp lanes (embedder, reranker, vision) launch without a served-model
name at all and ignore the model field, so theirs is a label rather than a key.

Local models declare `input_cost_per_token: 0` / `output_cost_per_token: 0`.
Not cosmetic: LiteLLM raises "This model isn't mapped yet" inside spend
calculation for any `openai/<slug>` missing from its cost map, so the choice is
between an asserted zero and a per-request error with no ledger entry.

**Frontier** — `planner-gpt` and `planner-gpt-pro`, deliberately under names no
local model shares. A shared `modelName` would make LiteLLM's router
load-balance between free local compute and paid API calls. They declare no
cost or capability metadata because LiteLLM already ships accurate values for
both `gpt-5.5` models.

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
before the template ever saw it; sent to `Qwen/Qwen3.8-27B-FP8`, which pins
nothing, it 400s out of the Jinja. `enable_thinking` is *not* overwritten (the
pin does not set it), so a client can still turn thinking off on a pinned alias.

So the rule is:

- **Pins no effort** (the passthrough alias) → publish every level the template
  accepts: `[low, medium, xhigh]`.
- **Pins an effort** (`worker` low, `reviewer` medium) → publish that one level
  only. Anything else would advertise a control that silently does nothing,
  which is the exact failure this key exists to prevent.

## Adding or changing a model

A new local model is a `Model` + `InferenceService` in `llmkube/resources/`
and a file here. The catalogue is still declared twice — once as serving config, once as proxy
config — and `maxInputTokens` in particular must mirror the backend's
`maxModelLen` (vLLM) or `contextSize` (llama.cpp). Auto-registration is the only
thing that would collapse that duplication, and it is unusable here, so the
mirroring is a standing maintenance cost rather than a bug to fix.

The mirror is not strict equality in one direction. An alias may advertise
**less** than its backend serves, which is how several aliases can share one
backend at different context budgets: `Qwen/Qwen3.8-27B-FP8` publishes the full
262144 ceiling for interactive use, while `worker` and `reviewer` publish 131072
so coordinated fan-out plans against a window the ~275k-token KV pool can
actually hold several of. That gap has to be declared with

```yaml
metadata:
  annotations:
    cogito.dev/context-budget: deliberate
```

or the validator treats it as the accident it usually is. Advertising **more**
than the backend serves is always an error and has no annotation: the client is
told it may send a prompt vLLM will refuse.
