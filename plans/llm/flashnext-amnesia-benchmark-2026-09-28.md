# Flash Next on Amnesia — 2026-09-28

## Deployment

- Node: `amnesia`, Ryzen 9 9900X, 64 GB installed RAM, RTX 5070 Ti (16,303 MiB visible VRAM), local NVMe.
- Target: `AtomicChat/Qwen3.8-Flash-Next-GGUF` at revision `c30e114991c14ee0e5ed484ccfe0ded939ea5e81`, variant `AD-4.27bpw-Q4_K_M-M64`, 33 GGUF shards. The 38.4 GB PLE/ngram table is shard 2 on Amnesia's retained local PVC. The complete download Job succeeded.
- Server: `ghcr.io/ggml-org/llama.cpp:server-cuda-b10991@sha256:d4bdfe78ad26a1ef3ccc834fc4e4a106d882e0f2163dd9a06e067c580c742101`, LLMKube `InferenceService/flashnext`, one replica and one serving slot. LiteLLM alias: `flashnext`.
- Settings: 131,072 context, q8_0 K/V, mmap, 42 MoE layers on CPU, remaining eligible weights on GPU, 1024 batch / 512 microbatch, 8 decode / 16 prefill threads, and a bounded 3 GiB host prompt cache. Both time-sliced scheduler units are reserved from the single physical GPU so another pod cannot overcommit its VRAM. No draft model or speculative decoding.

The quant publisher [reports](https://huggingface.co/AtomicChat/Qwen3.8-Flash-Next-GGUF/blob/main/README.md) 54.5 GB of conventional weights plus the 38.4 GB SSD-pageable table. This deployment keeps mmap enabled and does not pin the table in host RAM. The kernel may cache hot pages in otherwise available RAM.

## Throughput

One streamed chat request per cell, 256 output tokens except where noted. The harness constructs a repeated technical-prose prompt; it is useful for comparing settings and validating context size, but can overstate prefill throughput on varied real work. These are single samples, not p95 latency estimates. Timings below are llama.cpp's prompt and decode timings where available; client time to first token includes prompt processing and network overhead. The 100k cell preceded the bounded prompt cache and full-card scheduler reservation; the model, context, KV format, and compute placement were the same.

| Placement / endpoint | Prompt tokens | Prompt tok/s | Output tok/s | Time to first token | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 45 CPU MoE layers / temporary server | 1,512 | 221.6 | 31.1 | 6.84 s | 256 output tokens |
| 45 CPU MoE layers / temporary server | 40,712 | 299.9 | 25.5 | 135.8 s | 256 output tokens |
| 43 CPU MoE layers / temporary server | 1,512 | — | 32.3 | 5.33 s | 256 output tokens |
| 42 CPU MoE layers / temporary server | 1,512 | — | 32.8 | 4.69 s | 256 output tokens |
| 42 CPU MoE layers / temporary server | 40,712 | 320.9 | 26.7 | 127.0 s | 256 output tokens |
| 42 CPU MoE layers / LLMKube | 1,512 | — | 32.9 | 4.81 s | 256 output tokens |
| 42 CPU MoE layers / LLMKube | 99,512 | 295.8 | 20.7 | 336.6 s | 128 output tokens; no restart |
| Final LLMKube, both GPU shares | 1,512 | 325.3 | 32.9 | 4.67 s | 256 output tokens |

At 42 CPU MoE layers the GPU used 14,858 MiB idle after load and about 15,222 MiB during a long prefill, out of 16,303 MiB visible. The 41-layer placement with a 1024 microbatch failed its 2,073 MiB CUDA prompt-buffer allocation; 42 layers with a 512 microbatch stayed Ready with zero restarts through the long-context probes. Linux reported roughly 55 GB of reclaimable file cache on Amnesia during the 100k probe. The ngram table remains an SSD-backed file and is not pinned into process anonymous memory.

The LiteLLM alias returned the requested sentinel through the master key and the existing Hermes key. Both Hermes and Open WebUI key scopes were updated through `/key/update`, then `/v1/models` showed `flashnext` for each key.

## Native 262k context follow-up

Qwen documents a native 262,144-token context for Flash Next. The initial 131,072-token deployment was a conservative GPU fit choice, not a model limit. The production slot and LiteLLM advertised input limit were raised to 262,144; 45 instead of 42 MoE layers now run on CPU to free VRAM for the larger cache. Output tokens share this context budget with input tokens, so a request that fills the entire window cannot also generate an 8,192-token answer.

After GitOps reconciliation, one streamed request with 257,712 input tokens and 64 output tokens completed without truncation, CUDA error, or pod restart. The 258k synthetic prompt is repetitive technical prose, so this throughput is not a prediction for varied documents. One short-prompt run measured the cost of moving three more expert layers to CPU.

| 262k slot, 45 CPU MoE layers | Input tokens | Prompt tok/s | Output tok/s | Time to first token | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Long context | 257,712 | 235.5 | 12.3 | 1,094.7 s | 64 output tokens, no truncation |
| Short context | 1,512 | — | 30.2 | 4.70 s | 256 output tokens |

GPU memory was approximately 14,414 MiB during most of the long prefill, out of 16,303 MiB visible. Short-context output speed declined from the initial deployment's 32.9 to 30.2 tokens/s. These are single samples. An earlier long request was interrupted when Flux reconciled the unmerged config; its empty stream was excluded. The benchmark harness now rejects an empty stream as a failed request.

Raw streamed-request artifacts are in [artifacts/2026-09-28-flashnext-amnesia](artifacts/2026-09-28-flashnext-amnesia). The harness is [qwen_p2p_bench.py](../../scripts/llm/qwen_p2p_bench.py), with llama.cpp `/tokenize` compatibility added for this run.

## Throughput tuning follow-up

With the same quant, one slot, 262,144-token context, q8_0 KV, SSD mmap, and 45 CPU MoE layers, we compared CPU thread counts and physical microbatch sizes. Amnesia has 12 physical CPU cores. Each cell below is one streamed request using the same synthetic prompt and 256 output tokens. TTFT is client-observed; decode rate is output tokens divided by elapsed time after the first token. The 40k baseline was remeasured at the 262k context setting.

| Decode / prefill threads | Microbatch | 1,512-token TTFT | 1,512-token decode tok/s | 40,712-token TTFT | 40,712-token decode tok/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 / 16 (baseline) | 512 | 4.70 s | 30.2 | 136.82 s | 26.1 |
| 12 / 12 | 512 | 5.31 s | 34.2 | 135.76 s | 28.7 |
| **12 / 12 (selected)** | **768** | **5.00 s** | **34.8** | **132.61 s** | **28.4** |
| 16 / 16 | 768 | 4.92 s | 31.5 | 131.84 s | 26.2 |

llama.cpp's server timings on the 40,712-token prompt increased from 297.8 to 307.2 prompt tokens/s between baseline and selected settings, a 3.1% gain. Short-prompt generation increased from 30.2 to 34.8 tokens/s, a 15.4% gain. The 16-thread setting gave only a small prefill difference while reducing generation speed. We kept the 1,024 logical batch size; the physical microbatch controls the GPU allocation relevant to this single-GPU deployment.

The selected settings also completed a fresh near-window request with 257,712 input tokens and 64 output tokens, no truncation or pod restart. Server timing was 240.0 prompt and 13.0 output tokens/s, versus 235.5 and 12.3 before tuning; client TTFT improved from 1,094.7 to 1,074.3 seconds. GPU memory held around 15,170 MiB of 16,303 MiB visible during the long prefill, leaving roughly 1.1 GiB of headroom. All measurements are single samples on repetitive synthetic text, so small changes may be run-to-run noise. The ngram shard remains mmap pageable from SSD.
