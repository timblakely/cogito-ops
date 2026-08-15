# Gemma 4 31B

Model-card notes for agents working on `LLMModel` CRs in this directory. This
covers the upstream base model; see each YAML for the exact quantization,
backend, and launch flags actually deployed.

## Base model

- **Publisher:** Google
- **Parameters:** 30.7B, dense (not MoE)
- **Architecture:** 60 transformer layers, hybrid local sliding-window
  (1024-token window) + global attention
- **License:** Google Gemma Terms of Use (custom license, not a standard OSI
  license) — verify current terms against the upstream model card before
  making any redistribution or commercial-use decisions; do not assume
  Apache-2.0-equivalent freedoms.

## Context length

256K tokens native. The two vLLM configs here run at 229,376; the llama.cpp
GGUF config runs at 131,072.

## Modalities

Text input/output plus image understanding (variable-resolution image
tokens: 70/140/280/560/1120 depending on input size). No audio.

## Tool calling

Native structured tool-use support. The two vLLM configs here set
`--tool-call-parser gemma4` and `--reasoning-parser gemma4`.
`cyankiwi_qat_awq_int4.yaml` additionally mounts a vendored
`tool_chat_template_gemma4.jinja` chat template instead of using the model's
built-in template; `google_qat_w4a16_ct.yaml` uses the model's own template.

Known caveat from local testing (`../../../GEMMA4_LOCAL_RESEARCH_REPORT.md`
at the repo root): Gemma 4 can emit the tool-call protocol correctly but
locally-served models — Gemma included — often stop after a single search
tool call rather than completing a multi-step fetch/verify loop, especially
in Open WebUI's native agentic search flow. This is a model/harness
interaction, not evidence that tool calling itself is broken.

## Thinking / reasoning

Gated by an `enable_thinking`/`<|think|>` mechanism; **default is off**
at the base-model level. None of the three `LLMModel` configs in this
directory set `--default-chat-template-kwargs` to force it on. The
`gemma4-agentic` `LLMModelOverlay` (`../../resources/overlays.yaml`)
forces `enable_thinking: true` and `preserve_thinking: true` as
per-request defaults for that virtual model only — the base `LLMModel`
entries here remain non-thinking by default.

## Recommended sampling (upstream)

Temperature 1.0, top_p 0.95, top_k 64 — all three configs here already pin
this via `--override-generation-config`.

## Deployed variants

- **`google_qat_w4a16_ct.yaml`** — Google's own QAT W4A16 compressed-tensors
  checkpoint, vLLM, tensor-parallel 2, backend `vllm-server`.
- **`cyankiwi_qat_awq_int4.yaml`** — community AWQ INT4 requant of the QAT
  checkpoint, vLLM, tensor-parallel 2, backend `vllm-server` (shared/mutually
  exclusive with the config above and with the Qwen 3.6/3.8 vLLM configs).
- **`mradermacher_heretic_q4_k_m.yaml`** — "Heretic", a decensored community
  fine-tune, GGUF Q4_K_M, served via llama.cpp on the dedicated
  `llama-cpp-server` backend (no explicit tool/reasoning parser — relies on
  the GGUF's own template).

## Known limitations

- Training data cutoff January 2025 per upstream card; factual answers
  should be treated with the same skepticism as any model of that vintage.
- May struggle with sarcasm/nuance per upstream notes.
- The "Heretic" variant is a decensored community fine-tune — expect
  divergence from Google's safety-tuned instruct behavior.
- Confirm current Gemma license terms before any use that involves
  redistribution, since it is not a standard permissive license.
