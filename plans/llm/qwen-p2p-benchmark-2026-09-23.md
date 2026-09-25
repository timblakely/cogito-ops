# Qwen TP=2 post-P2P benchmark — 2026-09-23 UTC

## Power limit: 250 W on both cards

The cap was **250 W per RTX 3090**, not 280 W, for this run. Live
`nvidia-smi` reported 250.00 W on GPU 0 (`GPU-787b…`) and GPU 1
(`GPU-a598…`) before and after the benchmark. The running
`nvidia-power-limit` DaemonSet reapplies `nvidia-smi -pl 250` every five
minutes. A two-second sampler recorded 169 samples per GPU during the run:
every sample reported a 250 W limit; peak draw was 249.95 W on GPU 0 and
250.15 W on GPU 1. Both reached 100% utilization. Raw samples:
[power-samples.csv](artifacts/2026-09-23-qwen-p2p/power-samples.csv).

The 250 W setting also predates the September pre-P2P benchmarks. Git commit
`ce5316e1` set 280 W on 2026-07-10; commit `ae757b02` reduced it to 250 W on
2026-07-13 with the message “lower power consumption to 250W until new PSU gets
here.” No later power-limit change appears in Git history. Historical
Prometheus `DCGM_FI_DEV_POWER_USAGE` peaks support a roughly 250 W cap:

| UTC window | GPU 0 peak | GPU 1 peak |
|---|---:|---:|
| 2026-09-14 (Glimmer study) | 254.621 W | 251.380 W |
| 2026-09-16 (Qwen retune) | 249.546 W | 250.538 W |

The query was `max by (gpu) (max_over_time(DCGM_FI_DEV_POWER_USAGE{Hostname="iggy"}[1d]))`, evaluated at 00:00 UTC on September 15 and 17 respectively. These are observed draw peaks, not archived readings of `power.limit`; the GitOps setting and the Glimmer report establish the pre-P2P cap. Brief draw readings slightly above 250 W do not mean the configured limit was 280 W. The July commit records the PSU reason for the reduction; check the PSU before restoring 280 W.

## Setup

- Target: live `InferenceService/qwen3-8-27b` on Iggy, vLLM 0.29.0,
  tensor parallel size 2, INT8 W8A16 target, native MTP n=3, FP8 KV.
- Container: `vllm/vllm-openai@sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1`;
  NVIDIA driver 595.71.05 on Talos v1.13.5/kernel 6.18.36.
- The running service logged `NCCL P2P enabled at PHB`; live
  `nvidia-smi topo -p2p r` returned `OK` in both directions.
- Direct backend via a local Kubernetes port-forward, bypassing LiteLLM.
  Pod Ready with zero restarts before and after; vLLM reported zero running
  and waiting requests after the run.
- Harness: [qwen_p2p_bench.py](../../scripts/llm/qwen_p2p_bench.py), using a
  shared synthetic technical context with SHA256
  `33dda80a6f1a40b0ebda1e0b6bd6a9db761e22b33b2c0771d1630b35cff000a3`.
  `/tokenize` counted 40,645 tokens; each chat request reported 40,700 prompt
  tokens. Temperature 0, seed 20260923, streaming, 512 output tokens per
  request. Every response ended at the output limit. Git HEAD at the run was
  `fee61d265f6ea7e395f7368448ecd1ade228d482`; the harness was a new
  uncommitted worktree file.

## Results

| Cell | Repetitions / requests | Success | TTFT p50 / p95 | Decode p50 / p95 per request | Total p50 / p95 |
|---|---:|---:|---:|---:|---:|
| One session, 40.7k prompt | 5 / 5 | 5/5 | 3.50 / 31.52 s | 65.77 / 65.97 tok/s | 11.29 / 39.28 s |
| Eight concurrent sessions, 40.7k each | 4 / 32 | 32/32 | 23.54 / 30.31 s | 21.53 / 28.80 tok/s | 47.75 / 48.28 s |

The first single-session request had a cold 31.52 s TTFT. Its four warm
repetitions had 3.49–3.52 s TTFT and reused 36,800 cached tokens each. The
eight-session requests also reported 36,800 cached prompt tokens each and
finished in four rounds of 47.67–48.69 s. Peak sampled VRAM was 23,420 MiB
and 23,428 MiB on GPUs 0 and 1.

Raw results: [single-40k.json](artifacts/2026-09-23-qwen-p2p/single-40k.json)
and [eight-40k.json](artifacts/2026-09-23-qwen-p2p/eight-40k.json).

## Comparison limit

The [2026-09-16 Qwen notes](bench-notes.md#qwen-38-concurrent-session-retune-2026-09-16)
recorded 85.34 tok/s for one session and 51.27 tok/s for eight sessions on
their prose corpus, before P2P. The original prompt corpus and harness are not
in this repository, and their output length, thinking-token mix, and metric
calculation cannot be reproduced here. This new synthetic prompt produced
roughly 290–325 reasoning tokens within each 512-token completion. **These
numbers do not establish a P2P speedup or regression.** They establish that
the patched driver and NCCL P2P ran a sustained TP=2 workload at the same
configured 250 W cap, with 37/37 requests succeeding and no pod restart.
