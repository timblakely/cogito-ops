# Glimmer RTX 3090 capacity benchmark — 2026-09-14

## Outcome

The PCIe x4 RTX 3090 on `iggy` sustained all tested Glimmer configurations:

- 2 concurrent slots at 131,072 tokens per slot;
- 4 concurrent slots at 131,072 tokens per slot;
- 8 concurrent slots at 65,536 tokens per slot; and
- 16 concurrent slots at 32,768 tokens per slot.

No request failed, timed out, or caused an in-test pod restart. The production
baseline remains 2x131k because it matches the two-Muse-scout round and has the
best deep-request latency. For Foreman's four-task ceiling, 4x98k (G12) is the
best measured balance; 4x131k (G13) fits, but its warm long-context tail is
less predictable. Sixteen slots are useful proof of capacity, not the proposed
agent setting.

## Fixed configuration and method

- Hardware: NVIDIA RTX 3090, 24 GiB, PCIe x4, UUID `GPU-787b...`, node `iggy`.
- Target: Muse Glimmer 30B Q4_K_M with DFlash draft model, Q8 K/V cache, and
  projector in host RAM.
- Runtime: `ghcr.io/ggml-org/llama.cpp:server-cuda` digest
  `sha256:6ac921528d613deb0fd142c654735e594a446a1c37a069eeab08d8fd974d4bec`,
  llama.cpp build `b10920-eafe15a5e`.
- Limits held fixed: 2 CPU and 16 GiB RAM. The RAM limit was not raised because
  every cell completed and peak RSS stayed below it; `iggy` ended with
  `MemoryPressure=False`.
- Serving knobs held fixed: DFlash `nDraftMax=15`, `pMin=0.75`, batch 4096,
  micro-batch 1024, flash attention, Jinja chat template, and reasoning budget
  16,384.
- Driver: `scripts/llm/glimmer_bench.py`. Each cell used temperature 0, a
  pinned seed, 64 output tokens, five synchronized repetitions, and one request
  per slot. The first repetition populated the cache; repetitions 2–5 reused
  the same long prompt with only the request-id suffix changing.
- InferenceService generations were G6=6, G11=7, G12=8, G13=9, G14=10, and
  G15=11. Runtime `/props` confirmed that the effective slot contexts matched
  the requested arena divisions for every cell.
- The long prompt was approximately 80% of effective per-slot context. Summary
  p95 values below intentionally include the cold first repetition. “Warm
  range” reports minimum-to-maximum request completion time across repetitions
  2–5 and makes the cache effect visible.

## Results

All success counts are successful requests divided by attempted requests.
Decode is the median per-request rate while all configured slots were active.

| Cell | Slots x context | Long prompt | Success | Long TTFT p50/p95 (s) | Long total p50/p95 (s) | Warm total range (s) | Decode p50 (tok/s/request) | Peak VRAM | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| G6 | 2x131,072 | 104,865 | 10/10 | 1.20 / 143.75 | 4.48 / 146.78 | 3.99–4.54 | 19.50 | 18,088 MiB | 14.52 GiB |
| G11 | 4x65,536 | 52,439 | 20/20 | 0.95 / 150.85 | 5.29 / 180.61 | 5.00–5.78 | 14.75 | 18,084 MiB | 6.28 GiB |
| G12 | 4x98,304 | 78,652 | 20/20 | 1.21 / 227.72 | 6.11 / 284.03 | 5.79–6.78 | 13.06 | 19,160 MiB | 6.14 GiB |
| G13 | 4x131,072 | 104,865 | 20/20 | 4.69 / 313.68 | 11.58 / 401.41 | 5.69–20.43 | 11.07 | 20,236 MiB | 10.10 GiB |
| G14 | 8x65,536 | 52,439 | 40/40 | 7.54 / 288.15 | 14.82 / 323.04 | 9.16–19.03 | 8.62 | 20,356 MiB | 9.47 GiB |
| G15 | 16x32,768 | 26,226 | 80/80 | 3.50 / 273.07 | 9.90 / 343.56 | 7.85–17.26 | 10.00 | 20,790 MiB | 13.06 GiB |

The original G6 configuration also passed 10/10 synchronized requests with an
actual 32,782-token prompt: TTFT p50/p95 0.50/52.85 seconds, total p50/p95
2.84/55.11 seconds, and median decode 27.37 tokens/s/request.

Short-prompt throughput confirms that increased batching remains productive:

| Cell | Success | TTFT p50/p95 (s) | Total p50/p95 (s) | Decode p50 (tok/s/request) | Approx. aggregate decode |
|---|---:|---:|---:|---:|---:|
| G6, 2 slots | 10/10 | 0.20 / 0.26 | 2.03 / 2.07 | 35.28 | 70.6 tok/s |
| G11, 4 slots | 20/20 | 0.24 / 0.56 | 2.83 / 3.16 | 24.66 | 98.6 tok/s |
| G12, 4 slots | 20/20 | 0.24 / 0.55 | 2.82 / 3.10 | 24.86 | 99.5 tok/s |
| G13, 4 slots | 20/20 | 0.24 / 0.43 | 2.82 / 3.00 | 24.81 | 99.2 tok/s |
| G14, 8 slots | 40/40 | 0.37 / 0.76 | 4.46 / 4.78 | 15.67 | 125.3 tok/s |
| G15, 16 slots | 80/80 | 0.40 / 1.02 | 3.23 / 3.83 | 22.63 | 362.1 tok/s |

Peak GPU utilization was 100% in every cell and peak board power ranged from
251.19 to 254.02 W. The highest VRAM observation left about 3.2 GiB free.

## Interpretation

The answer is a measured hardware capacity, not merely a proposed test matrix:
Glimmer can serve at least 16 simultaneous 32k lanes on this card, or four
lanes at the model's full trained 131k context. Context allocation is therefore
not the immediate constraint for v4's maximum of four supervised tasks.

Prefix reuse is operationally important. At G6's 80%-context cell, the cold
round took 146.12–146.78 seconds while warm rounds took 3.99–4.54 seconds.
The other cells show the same order-of-magnitude warmup effect. llama.cpp also
logged prompt-cache evictions under the 16-slot load, so a production cache-hit
ratio should be exported before relying on this synthetic best case.

Two caveats remain. This benchmark proves allocation, concurrency, and timing
with a deterministic synthetic text corpus; it does not prove scout answer
quality. It also did not run the paired DFlash-disabled boundary or overlapping
vision/text cell. Those stay open in `bench-notes.md`.

## Operational findings

- The 16 GiB pod RAM limit is sufficient for these clean-pod runs. The highest
  observed RSS was 14.52 GiB on the older G6 process, so there is limited
  headroom but no evidence that a higher limit improves throughput.
- At benchmark time the generated llama.cpp Deployment used `RollingUpdate`.
  A configuration change attempted to place old and new GPU replicas together
  on one card, which cannot succeed, so each benchmark rollout required
  pausing the Deployment and scaling the exact old ReplicaSet to zero.
  Follow-up PR #110 installed a narrowly scoped native admission policy that
  now forces `Recreate` for both UUID-bound GPU lanes.
- Four stale Foreman Jobs were consuming Glimmer after their AgenticTasks were
  already terminal. Their Jobs were deleted while retaining CRs/results. This
  reproduced the terminal-task Job re-creation issue listed in the v4 plan and
  could otherwise invalidate capacity measurements. Follow-up PR #108 upgraded
  Foreman to 0.9.27, whose drain and orphaned FleetNode fixes are now live.

The GitOps configuration was returned to G6 (2 slots, total context 262,144)
after recording these results.
