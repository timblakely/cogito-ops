# Laguna S 2.1

Model-card notes for agents working on the `LLMModel` CR in this directory.

## Base model

- **Publisher:** poolside (released 2026-07-21)
- **Parameters:** 118B total, ~8B activated per token (MoE)
- **Architecture:** 256 routed experts (top-10) + 1 shared expert, 48 layers
  (12 global attention + 36 sliding-window at 512 tokens), grouped-query
  attention (8 KV heads), per-head softplus output gating
- **License:** OpenMDW-1.1 (permissive, commercial and non-commercial use)
- **Tier:** sits between poolside's Laguna XS 2.1 (33B-A3B) and Laguna M.1
  (225B-A23B) in capability

## Context length

1,048,576 tokens native. Deployed here at 102,400.

## Modalities

Text-to-text only — no vision.

## Tool calling

Native `poolside_v1` tool-call parser upstream, with support for
interleaved thinking between tool calls. This llama.cpp deployment relies on
the GGUF's own Jinja template (`--jinja`) rather than an explicit parser
flag — llama.cpp doesn't expose the portable `toolCallParser` field the way
the vLLM backend does, so tool-call framing here comes entirely from the
template.

## Thinking / reasoning

Supports interleaved thinking between tool calls with a per-request
`enable_thinking` control upstream; preserved thinking blocks are
recommended for agentic workflows. Not explicitly pinned in this
deployment's launch args — it's using whatever the GGUF template defaults
to. If an agentic tool loop against this model looks like it's missing
reasoning content, check this the same way the Qwen 3.8/3.6
`enable_thinking` default was checked (see `../qwen_3p8_27b/README.md`).

## Deployed variant

**`poolside_q4_k_m.yaml`** — Q4_K_M GGUF with a paired DFlash BF16 draft
model for speculative decoding, served via llama.cpp on the dedicated
`laguna-server` backend. MoE expert offload is manually split across two
GPUs and CPU via `--override-tensor`: experts in layers 26-36 pinned to
CUDA0, layers 37-47 to CUDA1, everything else to CPU.

## Known limitations

- Explicitly designed and marketed for software-engineering/agentic-coding
  use cases — not a general-purpose chat model target.
- Q4_K_M is a meaningfully lossy quant; upstream full-precision benchmark
  numbers (70.2% Terminal-Bench 2.1, 59.4% SWE-Bench Pro, 40.4% DeepSWE)
  should not be assumed to hold at this quantization.
- Full BF16 checkpoint needs ~236 GB across multiple GPUs — this cluster
  only ever runs the quantized GGUF variant.
