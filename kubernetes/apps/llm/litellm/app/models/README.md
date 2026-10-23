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

## The catalogue today

Eight aliases, verified against `kubectl -n llm get litellmmodels` and
`kubectl -n llm get litellmvirtualkeys` on 2026-10-23. `kustomization.yaml` in
this directory is the only thing that registers them — note that
`qwen-3-8-fp8.yaml` still sits here unreferenced, so it is an orphan file, not
a served alias.

| `metadata.name` | `modelName` clients send | backend Service | `maxInputTokens` | notes |
| --- | --- | --- | --- | --- |
| `coder` | `coder` | `qwen3-8-awq-iggy:8000` | 65536 | |
| `qwen3-8-27b` | `Qwen/Qwen3.8-27B-INT8-W8A16` | `qwen3-8-awq-iggy:8000` | 65536 | `supportsVision: false` |
| `worker` | `worker` | `qwen3-8-awq-iggy:8000` | 65536 | pins `reasoning_effort: low` |
| `flashnext-deleuze` | `flashnext-deleuze` | `radiance:8080` | 262144 | served name `openai/qwen3.8-flash-next` |
| `muse-glimmer-30b` | `Muse-Glimmer-30B` | `muse-glimmer-30b:8080` | 131072 | `supportsVision: true` |
| `gemma-4-12b` | `google/gemma-4-12b-it` | `gemma-4-12b:8080` | 65536 | `supportsVision: true`; preemptible Amnesia lane |
| `embedder` | `embedder` | `bge-m3:8080` | — | |
| `reranker` | `reranker` | `bge-reranker-v2-m3:8080` | — | `infinity/` prefix, not `openai/` |

Key scopes as issued: `hermes` carries all eight; `open-webui` carries
`Qwen/Qwen3.8-27B-INT8-W8A16`, `flashnext-deleuze`, `Muse-Glimmer-30B`,
`google/gemma-4-12b-it`, `embedder`; `coder` and `worker` carry their own alias
only; `pi` is unrestricted (`spec.models` empty).

**Local only.** Every entry points directly at its InferenceService's Service
(there is no router in between; with one always-on backend there is nothing to
dispatch across), and the string after `openai/` is the served model name. On
the vLLM-served Qwen aliases that string must stay byte-identical to the
backend's `--served-model-name` or the request 404s at the backend. The
llama.cpp lanes (embedder, reranker) launch without a served-model
name at all and ignore the model field, so theirs is a label rather than a key.

Local models declare `input_cost_per_token: 0` / `output_cost_per_token: 0`.
Not cosmetic: LiteLLM raises "This model isn't mapped yet" inside spend
calculation for any `openai/<slug>` missing from its cost map, so the choice is
between an asserted zero and a per-request error with no ledger entry.

**There are no role seats and no metered frontier.** The October 2026 agent-tier
cleanup (`ab8324d`, `ced129f`, `49624bf`, `e54742a`) deleted `coordinator`,
`coordinator-heavy`, `planner`, `planner-local`, `planner-gpt`,
`planner-gpt-pro`, `reviewer`, `reviewer-qwen`, `scout`, `scout-qwen`,
`worker-escalated` and the CPU `vision` lane. The paid escape hatches went with
them: no live key reaches a paid API model. `services/gateway/coordinator/service.py:46,65`
still defaults to `planner` and `coordinator`, which is why the gateway
runbook opens with a retirement note — set `PLANNER_MODEL`/`COORDINATOR_MODEL`
before relying on gateway planning rather than re-adding an alias. Per-component
scoped keys went with the tiers too; a component that needs a narrower scope
gets its own `LiteLLMVirtualKey`.

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

- **Pins no effort** → publish the levels the template accepts. Only
  `Qwen/Qwen3.8-27B-INT8-W8A16` does this today, with
  `thinking_levels: [low, medium, xhigh]`.
- **Pins an effort** → publish that one level only, as `worker` does
  (`reasoning_effort: low` pinned in `params.additional`, `thinking_levels:
  [low]`). Anything else would advertise a control that silently does nothing,
  which is the exact failure this key exists to prevent.
- `coder`, `flashnext-deleuze`, `muse-glimmer-30b` and `gemma-4-12b` declare no
  `thinking_levels` at all, so no picker offers an effort choice on them.

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
context in a raw engine argument — `--max-model-len` on `qwen3-8-awq-iggy`,
`--ctx-size` on `muse-glimmer-30b` — is invisible to it. That is exactly where
three of the eight aliases live: `coder`, `worker` and
`Qwen/Qwen3.8-27B-INT8-W8A16` are all held at 65536 by hand against
`qwen3-8-awq-iggy`, and `qwen38-awq-iggy.yaml` says so explicitly — move
`--max-model-len` and every alias's `maxInputTokens` together.
`muse-glimmer-30b` carries the annotation for the same unreadable-context
reason:

```yaml
metadata:
  annotations:
    cogito.dev/context-budget: deliberate
```

Advertising **more** than a backend whose context the validator can read is
always an error and has no annotation: the client is told it may send a prompt
vLLM will refuse.
