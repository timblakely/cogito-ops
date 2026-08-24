# Serving modes

Alternate specs for the objects in `../resources/` and `../../cuda-dev/`, used
when one or both of iggy's 3090s is handed to the CUDA development pod.

**These files are not part of any Kustomization and Flux never applies them.**
Flux's generated root scan adds a directory as a resource and stops descending
as soon as it finds a kustomization file, so `llmkube/` is pulled in through
its own `kustomization.yaml` and this directory is never read. Git is always
NORMAL; the modes exist only as something an operator applies on purpose.

| Mode | GPU 0 | GPU 1 | Local serving |
| --- | --- | --- | --- |
| NORMAL | Qwen 3.8 FP8, TP=2 | ← same | full, 8 seats, MTP, 131k |
| SPLIT | single-card 4-bit Qwen | dev pod | degraded, 1-2 seats |
| DARK | dev pod | dev pod | none |

```
just kube llm-mode          # what is running now
just kube llm-split a       # or `b` - the two degraded candidates below
just kube llm-dark          # dev pod takes both cards, no local serving
just kube llm-normal        # rollback from anywhere; never reads dev state
```

## How the switch works, and why it reverts cleanly

Each target suspends the affected Flux Kustomizations, then server-side applies
a **complete replacement** object *using Flux's own field manager*
(`kustomize-controller`). Because the manager is the same, apply semantics do
the bookkeeping: fields the manager owned and no longer sets are removed, so
`llm-normal` - which is nothing but `flux resume` plus a reconcile - restores
git exactly, including dropping the fields only a mode file sets.

Three rules follow from that and must not be broken:

- **Every mode file pins `metadata.namespace: llm`, and every apply passes
  `-n llm`.** Flux injects the namespace from its Kustomization, so manifests
  it renders never need one; these are applied by hand and inherit whatever
  the operator's kubectl context points at. When that context is `default` the
  apply *succeeds*, the objects land in the wrong namespace, and every check
  downstream passes against the untouched originals - so the switch reports
  success and changes nothing. This happened once; both belts stay on.

- **Never switch modes with `kubectl patch`/`edit`/`scale`.** Those record
  ownership under a different manager, and Flux's re-apply then cannot remove
  what they set: the cluster stays stuck in the mode after `llm-normal` claims
  to have left it.
- **Mode files must be complete objects**, not fragments. A partial apply under
  the shared manager strips every field it omits.

The mode targets assert the resulting spec before waiting on any rollout, for
the same reason: `kubectl rollout status` against an object the apply never
touched returns success immediately, turning a silent no-op into a green
result.

DARK sets `replicas: 0` on the serving object rather than deleting or
suspending it. That keeps the revert a plain field change, and it is why the
DARK spec may omit the runtime detail the NORMAL spec carries - with no pod,
there is nothing for the omitted fields to configure, and Flux restores them.

## The degraded serving candidates

Both keep `metadata.name: qwen-3-8-fp8` and `endpoint.port: 8000`, so the
Service keeps its name, the LiteLLM catalogue is not edited, and the catalogue
validator stays green. Only the thing behind the address changes.

- **`split-a-llamacpp.yaml`** - Unsloth Dynamic V3 GGUF on llama.cpp. ~17.6GB
  of weights leaves real KV headroom; llama.cpp's MMQ kernels use the card's
  integer tensor cores. No MTP, `--parallel 2`, no vision.
- **`split-b-vllm-nvfp4.yaml`** - the 4-bit mixed-precision safetensors build
  on vLLM's pre-Blackwell weight-only path. Keeps continuous batching and the
  8-bit-activation quality ceiling, but ~22.6GB on a 24GB card is marginal:
  context is cut to 16k with 8-bit KV, and whether it fits at all is the
  question the A/B answers.

Selection rule: keep whichever clears **20 tok/s single-stream decode with at
least 16k usable context**; ties break toward B, which additionally keeps a
4-bit-storage GEMM path warm on the serving card.

## Known consequence of leaving the catalogue alone

LiteLLM keeps advertising `maxInputTokens: 131072` in every mode, because the
catalogue is not touched. In SPLIT the backend serves 48k (A) or 16k (B), so a
prompt longer than that fails at the backend instead of being refused by the
proxy. That is accepted: the alternative is editing the catalogue on every
switch, which is exactly the drift this design exists to avoid. `worker` and
`reviewer` carry no fallback by standing decision, so in DARK they simply fail
and the coordinator escalates after reading the failure.
