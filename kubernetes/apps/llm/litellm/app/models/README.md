# LiteLLM model catalogue

One `LiteLLMModel` per client-facing alias, adopted by the `LiteLLMProxy` in
this app through `proxyRef`. These replace the inline `proxy_config.model_list`
that used to live in the HelmRelease.

## Why these are hand-written and not auto-registered

litellm-operator can mirror LLMKube `InferenceService` objects into
`LiteLLMModel` resources automatically (`llmkube.autoRegister`). It is off, and
must stay off, for two independent reasons:

1. **The pool.** Projection creates a model when an InferenceService reaches
   `Ready` and deletes it on a terminal phase, which includes `Stopped`. Ten of
   the eleven services here are `Stopped` at any moment, because `ModelPool`
   owns residency and scales non-resident members to zero. Auto-registration
   would rewrite the catalogue on every swap and advertise only the resident
   model.
2. **The addresses.** Projection points `apiBase` at each InferenceService's own
   Service, bypassing `ModelRouter` — handing clients a backend the pool can
   scale away mid-request.

There is a third cost, which is what upstream hit: projected models are named
after the InferenceService, so the client-facing names become deployment names.
`modelName` here is an arbitrary string, which is what lets the catalogue keep
advertising the Hugging Face-style identifiers Hermes, Open WebUI and pi are
already configured against.

## The two tiers

**Local** — every entry points at `cogito-llm-router-router-proxy`, and the
string after `openai/` is the `RouterBackend` name, which `BackendNameMatch`
dispatches on. It must stay byte-identical to the backend; a mismatch fails as
an unmatched route rather than an error. Backend names are constrained to
`^[a-z0-9][a-z0-9-]{0,62}$`, which is why they are slugs and the client-facing
`modelName` is not.

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

A new local model is a `Model` + `InferenceService` in `llmkube/resources/`, a
`RouterBackend` on the `ModelRouter`, a `ModelPool` member, and a file here.
The catalogue is still declared twice — once as serving config, once as proxy
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
