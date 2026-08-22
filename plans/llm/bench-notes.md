# LLM bench notes

Running log of measurements and verification evidence. Manifest comments hold
the numbers next to their tunables; this file holds the raw context.

## 2026-08-21 · T0.1 GPU allocation check (pre-change)

`qwen-3-8-fp8-7ddd577cf8-5g7l8` on iggy, device plugin still time-slicing ×4:

```
GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14)
GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-a5982685-6ed7-6fce-8096-52d29e241396)
CUDA_VISIBLE_DEVICES=(unset)
0: 23114 MiB / 24576 MiB used
1: 23220 MiB / 24576 MiB used
```

Two distinct physical UUIDs → the TP=2 allocation does span both cards today.
The `replicas: 1` change makes that true by construction rather than by luck.

## 2026-08-21 · T0.1 outcome

- Gotcha: the device plugin **rejects `timeSlicing.replicas: 1`** ("number of
  replicas must be >= 2"). Removing the sharing block entirely is how
  advertised = physical. First attempt crash-looped the plugin for ~2 min;
  running workloads were unaffected.
- After fix: `iggy` capacity `nvidia.com/gpu: 2`, plugin 2/2 Running, qwen pod
  untouched (41h uptime preserved), backend smoke completion OK.

## 2026-08-21 · T1.1 retune results

New config: maxModelLen 131072, max-num-seqs 6, --language-model-only added.
vLLM startup (recorded per the manifest-comment convention):

- **GPU KV cache size: 277,007 tokens** → "Maximum concurrency for 131,072
  tokens per request: 2.11x". At the old 262,144 ceiling the same pool held
  ~1.05 full sequences — the ceiling halving doubled full-length seats, and
  typical worker turns (≤16k) pack ~17 deep in the same pool.
- Text-only mode confirmed: "All limits of multimodal modalities supported by
  the model are set to 0" — the vision tower is no longer resident.
- Engine init 119s (43.7s compilation) — the cost of a config rollout.
- vLLM hint: with CUDA-graph profiling, effective gpu-memory-utilization is
  0.8912; raising to 0.9088 would restore the pre-0.21 effective pool.
  Candidate micro-tune for the A1 sweep session.

## 2026-08-21 · T1.2/T1.3 verification

- worker/reviewer aliases live; worker-key smoke returned "OK" with short
  low-effort reasoning. Scope enforcement verified: worker key → reviewer and
  planner-gpt both 403.
- ModelPool + ModelRouter deleted; qwen pod uptime unbroken through the prune;
  InferenceService Ready with explicit replicas: 1.
- Validator: 8 modelNames, 1 backend, 0 warnings (mirror assertion now active).

## 2026-08-21 · A3 kristeva identity + bandwidth

- CPU: **dual Intel Xeon E5-2680 v2** (Ivy Bridge-EP, 2×10C/40T, DDR3-1866
  quad-channel per socket).
- sysbench memory (1M blocks): **70.9 GB/s @ 8 threads, 52.7 GB/s @ 32
  threads** (NUMA contention past one socket).
- **AVX only — no AVX2, no FMA** (Ivy Bridge). Consequences:
  - D2 MoE lane: ~6-8GB expert reads/token at ~50-70GB/s → 3-6 tok/s ceiling
    BEFORE the AVX-only compute penalty. The ≥5 tok/s bar is unlikely to
    clear; run the trial anyway when convenient, expect to delete it.
  - D1 CPU VLM: vision encode on AVX-only will run slower than the "seconds
    per image" estimate; still fine for rare screenshots, but benchmark
    before promising latency.
  - The A380 floor (Track B) is unaffected - the GPU does that work.

## 2026-08-22 · Wave 1 verification battery

- **Six parallel worker calls: 11.5s wall** for six ~11s completions — the
  seats are real (serial would be ~66s). Reviewer seat OK. Scope enforcement
  OK (worker key 403s on anything but `worker`).
- **litellm-operator gap:** LiteLLMVirtualKey scope changes are NOT pushed to
  existing keys — the DB kept the old 12-model allowlist through a spec
  change, an annotation nudge, and an operator restart (create-only
  reconciliation). Fixed via admin `/key/update`. Consequence: any future
  scope edit needs the same manual push (or an operator fix upstream); the
  validator keeps git honest but git-to-DB is not automatic for scopes.
- **coordinator / worker-escalated / reviewer-escalated: wired correctly but
  OpenAI returns "exceeded your current quota"** — the OPENAI_API_KEY account
  is out of credit, which also means planner-gpt/-pro are currently dead.
  User action required (T1.4): fund the account or land the real seats
  (Luna OAuth, GLM 5.3, K3).

## 2026-08-22 · Track B / B1-B2 probe

- **A380 confirmed by PCI id**: `0x8086:0x56a5` (DG2/Arc A380) — the NFD
  label was honest.
- **SYCL path proven before deploy**: `sycl-ls` inside the official
  `ghcr.io/ggml-org/llama.cpp:server-intel` image, unprivileged, with only
  `gpu.intel.com/i915: 1`, enumerates "Intel(R) Arc(TM) A380 Graphics" via
  Level Zero. /dev/dri injected by the plugin (card0 + renderD128).
- **No Resizable BAR** (Ivy Bridge platform cannot): notorious for Arc gaming
  performance, mild for compute; A4's throughput bench is the arbiter.
