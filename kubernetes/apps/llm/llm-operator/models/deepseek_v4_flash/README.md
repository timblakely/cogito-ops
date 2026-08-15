# DeepSeek V4 Flash

Model-card notes for agents working on the `LLMModel` CR in this directory.

## Base model

- **Publisher:** DeepSeek
- **Parameters:** 284B total, ~13B activated per token (MoE)
- **Architecture:** Mixture-of-Experts with hybrid attention — Compressed
  Sparse Attention (CSA) and Heavily Compressed Attention (HCA) — plus
  Manifold-Constrained Hyper-Connections (mHC) for signal propagation across
  layers. 256 routed experts (top-6) + 1 shared expert.
- **License:** MIT
- **Training data:** reported >32T tokens

## Context length

1,000,000 tokens native (base model). The deployed GGUF here runs at
143,360 tokens, set by hybrid CPU/GPU offload capacity rather than a model
limitation — see Operational notes.

## Modalities

Text only — no image/audio input or output.

## Tool calling

Not documented in the upstream card as a first-class feature the way it is
for the Qwen/Gemma/Laguna families. This deployment does not set a
`toolCallParser`; treat tool-call reliability as unverified until tested.

## Thinking / reasoning

Three upstream reasoning modes: **Non-Think** (fast), **Think High**
(logical analysis), and **Think Max** (maximum reasoning effort — requires
≥384K context window to select). This deployment does not set a
`--reasoning-parser` or a thinking-related chat-template default, so
whichever mode the GGUF's baked-in template defaults to is what's live;
this has not been explicitly verified.

## Recommended sampling (upstream)

Temperature 1.0, top_p 1.0.

## Deployed variant

**`unsloth_ud_iq3_s.yaml`** — Unsloth's `UD-IQ3_S` GGUF quant (a ~3-bit
dynamic quant), 4 shards, ~117 GiB total, served via llama.cpp on the shared
`llama-cpp-server` backend with hybrid CPU/GPU MoE offload (`--fit on`): 39
MoE layers remain in RAM while attention and the rest offload across both
GPUs on node `iggy`.

## Known limitations / operational notes

- A ~3-bit quant of a 284B-parameter model trades meaningful quality for
  footprint — expect results below whatever upstream benchmarks quote for
  full FP4/FP8 precision.
- Requires ~118 GiB RAM (120 GiB cap) on `iggy` for the KV cache and offloaded
  MoE layers at 143,360 context; do not activate until the node has that much
  allocatable memory free.
- Uses its own dedicated 140 GiB hostpath PVC — it does not share the Laguna
  PVC, whose StorageClass doesn't support expansion to fit this model.
- Text-only despite the MIT license being otherwise permissive; don't expect
  multimodal input to work.
