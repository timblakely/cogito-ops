# Qwen3.8-27B

Model-card notes for agents working on `LLMModel` CRs in this directory. This
covers the upstream base model; see each YAML for the exact quantization,
backend, and launch flags actually deployed.

## Base model

- **Publisher:** Alibaba Qwen team
- **Parameters:** 27B, dense (not MoE)
- **Architecture:** hybrid Gated DeltaNet (linear attention) + Gated Attention
  layers, plus multi-token prediction (MTP) for faster decoding
- **License:** Apache 2.0

## Context length

262,144 tokens native; extensible to ~1M via YaRN/RoPE scaling. Both
deployments here run the full 262,144.

## Modalities

Text, image, and video understanding.

## Tool calling

Built-in tool-call support. Both configs in this directory use vLLM's
`qwen3_xml` tool-call parser (`toolCallParser: qwen3_xml`), not
`qwen3_coder` (which the Qwen 3.6 directory uses instead).

## Thinking / reasoning

Enabled **by default** upstream: `reasoning_effort` defaults to `xhigh`
(other options `medium`, `low`), and `preserve_thinking=True` retains
reasoning content across turns by default.

Both configs here now pass `--default-chat-template-kwargs
'{"enable_thinking": true}'` explicitly, matching the upstream default. This
was **not** the case before 2026-08-15: both files previously forced
`enable_thinking: false` at the server level, which silently suppressed
reasoning output for any client that didn't override the kwarg itself
(discovered via a client — "Pi" — reporting the models as non-reasoning).
Keep this flag in sync across both files if either is edited.

## Recommended sampling (upstream)

- Thinking mode: temperature 1.0, top_p 0.95, top_k 20, presence_penalty 0.0
- Non-thinking mode: temperature 0.7, top_p 0.80, top_k 20, presence_penalty 1.5

Both configs here instead pin `--override-generation-config` to temperature
0.6 / top_p 0.95 / top_k 20 / min_p 0.0 — more conservative than upstream's
suggested 1.0 for thinking mode. Worth re-validating against upstream
guidance if output quality is ever in question.

## Deployed variants

- **`vishva007_w4a16_autoround.yaml`** — Vishva007's W4A16 AutoRound quant
  (Intel Neural Compressor `inc` quantization), vLLM, tensor-parallel 2,
  backend `vllm-qwen38-server`. Includes `--mm-processor-kwargs` pixel bounds
  for image input and MTP speculative decoding.
- **`lued_w8a16_mtp.yaml`** — lued's INT8 W8A16 MTP compressed-tensors quant,
  vLLM, tensor-parallel 2, backend `vllm-server` — **shared** with the Qwen
  3.6 and Gemma 4 vLLM deployments; only one model on that backend can be
  active at a time.

Both are third-party (non-Alibaba) quantizations; neither has been
independently re-benchmarked against upstream's published numbers on this
cluster.

## Operational notes

- The `lued` variant was cold (not pre-cached) on this cluster as of
  2026-08-15: first activation triggered a ~31.6 GB direct-from-HuggingFace
  download via cache-manager that took ~4.5 minutes. The operator does **not**
  wait for that download — a transition requested while the cache is
  "external" fails fast with `OfflineSnapshotUnavailable` (surfaced to
  clients as a proxy 504), even though cache-manager keeps downloading in the
  background and a retried transition succeeds once the snapshot goes hot.
  If a transition to a rarely-used model 504s, check
  `kubectl logs -n llm deploy/cache-manager` before assuming it's stuck.
