# Agentic homelab benchmark notes

This file records the measurements required by
`async-agentic-homelab-v4.md`. Do not promote inherited serving knobs from
"profile" to "validated" without filling in the raw artifact links below.

## 2026-09-13 implementation baseline

- Cluster measurements resumed on 2026-09-14 with authorized cluster access.
  Glimmer results are recorded below; the Qwen and Hermes cells remain open.
- Qwen profile under test: `SPEC=dflash2`, `CTX=long`, `PREFIX_CACHE=1`,
  `MAX_SEQS=5`, served as `qwen3-8-27b`.
- Muse profile under test: two fixed 131,072-token slots in a 262,144-token
  arena, without `--kv-unified`.
- Foreman capacity under test: two execution slots plus two credential-isolated
  scout slots.

## Qwen SPEC/CTX A/B

Run the same pinned prompt corpus and seed through the `coder` and
`scout-qwen` aliases. Change one independent variable at a time and allow the
InferenceService to become Ready and idle between cells.

| Cell | SPEC | CTX | Prompt class | TTFT p50/p95 | Decode tok/s p50/p95 | Peak VRAM/RSS | Task result | Artifact |
|---|---|---|---|---|---|---|---|---|
| A | `dflash2` | `long` | coder | pending | pending | pending | pending | pending |
| B | disabled | `long` | coder | pending | pending | pending | pending | pending |
| C | `dflash2` | short/default | coder | pending | pending | pending | pending | pending |
| D | `dflash2` | `long` | scout | pending | pending | pending | pending | pending |
| E | disabled | `long` | scout | pending | pending | pending | pending | pending |
| F | `dflash2` | short/default | scout | pending | pending | pending | pending | pending |

Record the exact InferenceService generation, image digest, prompt corpus
commit, sampling parameters, and at least five warm repetitions per cell.

## Qwen 3.8 concurrent-session retune, 2026-09-16

This supersedes the `MAX_SEQS=5` profile named in the 2026-09-13 baseline above
and fills the capacity question the SPEC/CTX table does not ask. The SPEC/CTX
A/B below remains open and is a separate study.

Backend: `InferenceService/qwen3-8-27b` on iggy's two RTX 3090s (SM86, no
NVLink/P2P), vLLM 0.29.0, TP=2, FP8 E4M3 KV, digest-pinned SM86 FA2+fp8-KV
plugin `731d1942...`, four anchor-checked overlays (pr48375, gdn-async-order,
51581, and the newly vendored vllm#50021).

### Capacity

| profile | target | drafter | seqs | GPU KV cache size |
|---|---|---|---:|---:|
| previous | Qwen FP8 | W4A16 DFlash2 n=7 | 1 | 267,493 |
| **current** | **INT8 W8A16 (MTP build)** | **native MTP n=3** | **8** | **392,483** |
| rejected | INT8 W8A16 (MTP build) | DFlash2-W8 n=7 | 8 | would not start |

Per card at the current profile: 14.68 GiB weights + non-torch, 0.73 GiB peak
activation, 0.23 GiB CUDA graphs, 6.97 GiB KV, 0.54 GiB spare of 23.56 GiB.
19,067 B/token/card, against 23,940 with an external DFlash2 drafter.

Two non-obvious constraints, both measured, both worth not rediscovering:

- **`max_model_len` is a floor on the pool.** vLLM refuses to start unless the
  pool holds one max-length sequence, so the 262144 ceiling REQUIRES a
  >= 262,144-token pool. The old "Maximum concurrency 1.02x" was that floor.
- **The drafter sets the KV padding tax.** `get_kv_cache_groups` makes every
  group hold the same number of layers, with `group_size = min(bucket sizes)`.
  A 5-layer DFlash2 drafter bucket alongside 16 attention + 48 GDN layers gives
  group_size 5, padding attention 16 -> 20: a 25% tax on the pool's dominant
  consumer. The 1-layer MTP head merges into the attention bucket instead
  (group_size 17), leaving only 6.25% mamba padding.

### Throughput and acceptance

Harness: barrier-started sessions, `/metrics` bracketed per run. The `counting`
task (list 1..400) is speculation-ideal and overstates decode roughly 2.5x;
`prose` is the number to compare.

| cell | profile | conc | prompt tok | TTFT p50 | decode tok/s p50 | acceptance | accept len | prefix hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 | previous (FP8/DFlash2, 1 seq) | 1 | 40,890 | 6.20 s warm | 86.70 | 27.3% | 2.91 | 88.7% |
| Q2 | current (INT8/MTP, 8 seqs) | 1 | 40,886 | 38.79 s cold | 85.34 | 52.2% | 2.57 | 41.1% |
| Q3 | current | 8 x 4 rounds | 40,891 | 66.94 s | 51.27 | 56.4% | 2.69 | 82.7% |
| Q4 | current | 3 x 2 rounds | 102,562 | 266.40 s | 68.63 | 56.7% | 2.70 | 63.1% |
| Q5 | current, fully distinct prompts | 3 | 114,249 | 410.94 s | 79.05 | 57.1% | 2.71 | 0.0% |

Q3 is the vllm#50021 verification: 32 requests, 0 failures, 0 pod restarts,
`num_requests_waiting` 0 throughout. The issue reports an Xid 13/31 fault
inside 7-10 concurrent requests. No negative control was run: provoking the
fault can wedge the GPU and force the full cordon/drain/reboot cycle.

Q5 is the sizing proof: three ~114K sessions with NOTHING deduplicating in the
prefix cache (0.0% hit), 342,747 tokens of genuinely distinct resident KV,
peak `kv_cache_usage_perc` 0.891, scheduler never deferring for capacity.

Cold prefill runs ~1,200 tok/s aggregate, so a 110K prompt is ~95 s alone and
three concurrent cold ones are ~7 minutes. Prefix caching is therefore
load-bearing for multi-turn sessions, not an optimisation.

### Untried levers

Enumerated rather than tested, because the >= 340K goal was already met:

- `--prefix-match-unit 16` - both upstream model cards set it; this deployment
  does not. Attention block size is forced to 1648 tokens by mamba page
  alignment, so prefix reuse may currently be matching at a much coarser
  granularity than an agent turn's growth.
- `--kv-cache-memory 7896748032` (vLLM's "fully utilize" suggestion) in place
  of `--gpu-memory-utilization 0.95`, worth roughly +21,000 tokens, at the cost
  of the 0.54 GiB/card margin and of a reservation that cannot adapt.
- Restoring the vision tower costs ~24,000 tokens of pool; see
  `litellm/app/models/image.yaml` for what was traded away.
- The `lued/...-INT8-W8A16-DFlash2` build's packed embedding would return
  ~1.12 GiB if vLLM could load it; see `llmkube/resources/models.yaml`.

## Muse Glimmer 30B capacity, concurrency, and prefix reuse

The study started from `InferenceService/muse-glimmer-30b` generation 6 on
iggy's PCIe x4 RTX 3090 (`GPU-787b...`): llama.cpp digest
`sha256:6ac92152...`, Q4_K_M target plus DFlash drafter, Q8 KV, a 262,144-token
arena divided into two fixed 131,072-token slots, and a 16 GiB container memory
limit. Temporary generations through 11 measured the capacity frontier; the
GitOps baseline was restored after the run.

llama.cpp divides `contextSize` by `parallelSlots`, so record both total arena
and effective per-slot context. Run the following frontier in order. For each
slot count, stop increasing context after the first OOM, pod restart, request
refusal, or context-allocation failure; do not run the larger cells in that
column until the cause is understood.

| Cell | Parallel slots | Total `contextSize` | Context per slot | Concurrent requests | Result | Artifact |
|---|---:|---:|---:|---:|---|---|
| G1 | 1 | 65,536 | 65,536 | 1 | not run; bounded by stronger passing cells | [report](glimmer-benchmark-2026-09-14.md) |
| G2 | 1 | 131,072 | 131,072 | 1 | not run; bounded by G6 | [report](glimmer-benchmark-2026-09-14.md) |
| G3 | 1 | 262,144 | 262,144 | 1 | not run; beyond the model's trained 131k context | [report](glimmer-benchmark-2026-09-14.md) |
| G4 | 2 | 65,536 | 32,768 | 2 | not run; bounded by G6 | [report](glimmer-benchmark-2026-09-14.md) |
| G5 | 2 | 131,072 | 65,536 | 2 | not run; bounded by G6 | [report](glimmer-benchmark-2026-09-14.md) |
| G6 (restored config) | 2 | 262,144 | 131,072 | 2 | pass: 10/10 at 104,865 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |
| G7 | 3 | 98,304 | 32,768 | 3 | not run; bounded by G11 | [report](glimmer-benchmark-2026-09-14.md) |
| G8 | 3 | 196,608 | 65,536 | 3 | not run; bounded by G11 | [report](glimmer-benchmark-2026-09-14.md) |
| G9 | 3 | 294,912 | 98,304 | 3 | not run; bounded by G12 | [report](glimmer-benchmark-2026-09-14.md) |
| G10 | 4 | 131,072 | 32,768 | 4 | not run; bounded by G11 | [report](glimmer-benchmark-2026-09-14.md) |
| G11 | 4 | 262,144 | 65,536 | 4 | pass: 20/20 at 52,439 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |
| G12 | 4 | 393,216 | 98,304 | 4 | pass: 20/20 at 78,652 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |
| G13 | 4 | 524,288 | 131,072 | 4 | pass: 20/20 at 104,865 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |
| G14 | 8 | 524,288 | 65,536 | 8 | pass: 40/40 at 52,439 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |
| G15 | 16 | 524,288 | 32,768 | 16 | pass: 80/80 at 26,226 prompt tokens | [report](glimmer-benchmark-2026-09-14.md) |

Use one pinned text/reasoning corpus for every cell. Include a short request, a
32k prompt, and a prompt at 80% of effective per-slot context where the corpus
permits. Start all requests behind a barrier so their decode phases overlap;
run at least five warm repetitions. Record:

- successful concurrent requests, refusals, timeouts, and exact usable context;
- TTFT and end-to-end latency p50/p95, per-request and aggregate decode tok/s;
- GPU VRAM, utilization, and power plus container RSS and node memory pressure;
- pod restart count, exit reason, llama.cpp allocation errors, and health state;
- task-result quality, because a configuration that fits but truncates or
  degrades the scout/reviewer result is not a viable slot;
- the exact InferenceService generation, image digest, prompt corpus commit,
  sampling values, reasoning budget, and whether DFlash and mmproj were loaded.

Keep DFlash, mmproj placement, KV type, batch sizes, and sampling fixed for the
frontier. At the first capacity boundary, repeat only that boundary cell with
DFlash disabled to quantify the drafter's memory/latency tradeoff. Benchmark a
single image request and simultaneous image-plus-text traffic separately; do
not mix vision tokens into the text capacity comparison.

| Check | Required evidence | Result | Artifact |
|---|---|---|---|
| Stable slot/context frontier | highest passing cell for each slot count with no restart or refusal | pass: 2x131k, 4x131k, 8x65k, and 16x32k | [report](glimmer-benchmark-2026-09-14.md) |
| Host pressure | container peak RSS and iggy memory pressure below limits | pass: 14.52 GiB maximum RSS; no in-test OOM/restart; `MemoryPressure=False` | [report](glimmer-benchmark-2026-09-14.md) |
| Turn latency | scout p50/p95 and whether p95 exceeds 600 s | synthetic capacity pass: worst cold-inclusive p95 401.41 s; real scout turns still pending | [report](glimmer-benchmark-2026-09-14.md) |
| Prefix reuse | identical recorded prefix hash plus cold/warm cache-hit metric or log | partial: repeated-prefix warmup is large and cache eviction is logged; hit ratio was not exported | [report](glimmer-benchmark-2026-09-14.md) |
| DFlash boundary tradeoff | paired boundary result with drafter enabled and disabled | pending | pending |
| Mixed vision/text | one image request overlaps text traffic without starvation or failure | pending | pending |

If Glimmer scout p95 exceeds 600 seconds, test `reasoningBudget: 8192` against
the same corpus before changing any other knob. Select the production setting
from the Pareto frontier of usable per-slot context, successful concurrency,
tail latency, and task quality—not from maximum allocation alone.

## Hermes direct-session evaluation

The existing Hermes PVC is expected to retain a LiteLLM provider. Verify the
provider URL, select the `coordinator` alias, and exercise a resumable encrypted
DM without granting Hermes gateway/merge/cluster authority. Record tool
fidelity, session resume behavior, Matrix media handling, and token accounting.
Only design the harness bridge if this evaluation fails a concrete use case.
