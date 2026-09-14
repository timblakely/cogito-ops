# Agentic homelab benchmark notes

This file records the measurements required by
`async-agentic-homelab-v4.md`. Do not promote inherited serving knobs from
"profile" to "validated" without filling in the raw artifact links below.

## 2026-09-13 implementation baseline

- Cluster measurements: **blocked**. The first read-only Kubernetes API call
  could not resolve `k8s.internal` from the execution sandbox, so no live
  measurement was retried.
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

## Muse Glimmer 30B capacity, concurrency, and prefix reuse

The live 2026-09-14 baseline is `InferenceService/muse-glimmer-30b` generation
6 on iggy's PCIe x4 RTX 3090 (`GPU-787b...`): llama.cpp digest
`sha256:6ac92152...`, Q4_K_M target plus DFlash drafter, Q8 KV, a 262,144-token
arena divided into two fixed 131,072-token slots, and a 16 GiB container memory
limit. The service being Ready proves only that this operating point loads; it
does not establish usable context under simultaneous inference.

llama.cpp divides `contextSize` by `parallelSlots`, so record both total arena
and effective per-slot context. Run the following frontier in order. For each
slot count, stop increasing context after the first OOM, pod restart, request
refusal, or context-allocation failure; do not run the larger cells in that
column until the cause is understood.

| Cell | Parallel slots | Total `contextSize` | Context per slot | Concurrent requests | Result | Artifact |
|---|---:|---:|---:|---:|---|---|
| G1 | 1 | 65,536 | 65,536 | 1 | pending | pending |
| G2 | 1 | 131,072 | 131,072 | 1 | pending | pending |
| G3 | 1 | 262,144 | 262,144 | 1 | pending | pending |
| G4 | 2 | 65,536 | 32,768 | 2 | pending | pending |
| G5 | 2 | 131,072 | 65,536 | 2 | pending | pending |
| G6 (current config) | 2 | 262,144 | 131,072 | 2 | pending | pending |
| G7 | 3 | 98,304 | 32,768 | 3 | pending | pending |
| G8 | 3 | 196,608 | 65,536 | 3 | pending | pending |
| G9 | 3 | 294,912 | 98,304 | 3 | pending | pending |
| G10 | 4 | 131,072 | 32,768 | 4 | pending | pending |
| G11 | 4 | 262,144 | 65,536 | 4 | pending | pending |
| G12 | 4 | 393,216 | 98,304 | 4 | pending | pending |

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
| Stable slot/context frontier | highest passing cell for each slot count with no restart or refusal | pending | pending |
| Host pressure | container peak RSS and iggy memory pressure below limits | pending | pending |
| Turn latency | scout p50/p95 and whether p95 exceeds 600 s | pending | pending |
| Prefix reuse | identical recorded prefix hash plus cold/warm cache-hit metric or log | pending | pending |
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
