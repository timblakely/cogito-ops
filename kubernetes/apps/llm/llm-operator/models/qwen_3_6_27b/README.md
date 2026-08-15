# Qwen3.6-27B

Model-card notes for agents working on `LLMModel` CRs in this directory. This
covers the upstream base model; see each YAML for the exact quantization,
backend, and launch flags actually deployed.

## Base model

- **Publisher:** Alibaba Qwen team (released ~April 2026)
- **Parameters:** 27B, dense (not MoE)
- **Architecture:** hybrid design alternating Gated DeltaNet (linear
  attention) blocks with Gated Attention blocks
- **License:** Apache 2.0

## Context length

262,144 tokens native; extensible to ~1,010,000 via YaRN. Upstream
specifically recommends keeping context at or above 128K when YaRN is
enabled.

## Modalities

Text, image, and video (vision-encoder equipped).

## Tool calling

Supported via Qwen-Agent / MCP integration upstream. The vLLM deployment
here (`lorbus_autoround.yaml`) uses the `qwen3_coder` tool-call parser (not
`qwen3_xml`, which the Qwen 3.8 directory uses) plus a vendored,
digest-pinned chat template (`qwen-fixed-chat-template` ConfigMap, validated
against a captured agentic tool-call request — see
`../../resources/README.md` and `../../plans/template_management.md` in the
`llm-operator` source repo). Do not use a request-level template override;
GitOps owns the template bytes.

## Thinking / reasoning

Unlike Qwen 3.8, this model does **not** have thinking-mode controls —
there is no `enable_thinking` switch to flip. `lorbus_autoround.yaml` sets
`--default-chat-template-kwargs '{"enable_thinking": false}'` and
`--reasoning-parser qwen3`; that's consistent with a non-thinking model and
is not the same class of bug that was found and fixed on the Qwen 3.8
configs (see `../qwen_3p8_27b/README.md`) — do not "fix" it to match that
pattern.

## Recommended sampling (upstream)

- General tasks: temperature 1.0, top_p 0.95, top_k 20
- Precise coding: temperature 0.6, top_p 0.95, top_k 20

## Deployed variants

- **`lorbus_autoround.yaml`** — Lorbus's INT4 AutoRound quant, vLLM,
  tensor-parallel 2, backend `vllm-server` (shared with the Qwen 3.8 `lued`
  config and Gemma 4 vLLM configs — mutually exclusive, only one active at a
  time). MTP speculative decoding enabled.
- **`davidau_fable_fusion_711_q4_k_m.yaml`** — "Fable Fusion 711", a
  community merge/decensored ("Uncensored-Heretic") fine-tune with MTP,
  GGUF Q4_K_M, served via llama.cpp using the GGUF's own baked-in template
  (no explicit tool/reasoning parser flags — llama.cpp doesn't expose the
  portable parser fields the way vLLM does).

## Known limitations

- The Fable Fusion variant is an unofficial, decensored community merge —
  expect behavioral divergence from Alibaba's tuned instruct model and no
  upstream support for it.
- AutoRound INT4 is a lossy quant; upstream's headline claim (beating a
  397B MoE model on agentic coding benchmarks) is for the full-precision
  release, not this quantization.
