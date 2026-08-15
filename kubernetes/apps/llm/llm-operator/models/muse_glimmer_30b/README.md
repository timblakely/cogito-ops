# Muse Glimmer 30B

Model-card notes for agents working on the `LLMModel` CR in this directory.

## Base model

- **Publisher:** Meta
- **Parameters:** ~29.6B dense causal transformer (52 layers, GQA 32:2 query
  head ratio, SwiGLU FFN) + a dedicated ~1.8B ViT-G/14 perception encoder (50
  layers). Distilled from Meta's larger "Muse Spark" model, purpose-built for
  agentic tasks on consumer hardware.
- **License:** Apache 2.0 — no custom acceptable-use appendix, no
  monthly-active-user threshold. Note: upstream card also states usage is
  restricted to individuals 18+, which is a policy constraint independent of
  the license grant.

## Context length

131,072+ combined input/output tokens. Deployed here at 200,000, per the
sizing validated during this repo's initial local deployment testing (see
`../../resources/README.md`).

## Modalities

Text + interleaved image input (up to 4,096 visual tokens per image, via the
dedicated perception encoder). No video, no audio.

## Tool calling

Designed for reliable tool use with precise schema adherence across long
agentic workflows, including diagnosing and retrying failed tool calls
rather than halting. Served here via llama.cpp using the GGUF's own template
(`--jinja`) — no explicit parser flag is needed the way vLLM requires one.

## Thinking / reasoning

Supports adjustable reasoning effort (low/medium/high/xhigh) with chained
reasoning across long-horizon plans. This deployment passes
`--reasoning-preserve` to retain reasoning content across turns, matching
the model's chained-reasoning design.

## Deployed variant

**`meta_kquant_17gb.yaml`** — Meta's official 17 GB K-quant (Q4_K_M) with
its matching DFlash draft model (speculative decoding) and multimodal
projector, all materialized together and pinned to one Hugging Face
revision. Sized for a single RTX 3090 at 200k context with an f16 KV cache;
scaled to zero replicas by default. DFlash gives Meta-reported speedups of
3.1x on RTX 5090 and 1.5-1.8x on Apple silicon versus baseline generation —
actual speedup on this cluster's 3090 has not been independently confirmed.

## Known limitations

- Single-GPU sizing (200k context, f16 KV cache) was set from initial local
  testing only — validate on the model's actual first live acceptance run
  before trusting it under load (open TODO in
  `../../resources/README.md`).
- No video input support.
- Variable performance in less-represented languages per upstream card,
  despite training across 100+ languages.
- Usage restricted to 18+ per upstream policy.
