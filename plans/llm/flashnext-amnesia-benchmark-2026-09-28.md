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

Raw streamed-request artifacts are in [artifacts/2026-09-28-flashnext-amnesia](artifacts/2026-09-28-flashnext-amnesia). The harness is [qwen_p2p_bench.py](../../scripts/llm/qwen_p2p_bench.py), with llama.cpp `/tokenize` compatibility added for this run.
