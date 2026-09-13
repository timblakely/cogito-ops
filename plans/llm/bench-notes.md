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

## Muse concurrency and prefix reuse

| Check | Required evidence | Result | Artifact |
|---|---|---|---|
| Two simultaneous scouts | both slots active; no eviction or refusal | pending | pending |
| Host pressure | `iggy` memory requests and peak RSS below the plan thresholds | pending | pending |
| Turn latency | scout p50/p95 and whether p95 exceeds 600 s | pending | pending |
| Prefix reuse | identical recorded prefix hash plus backend cache-hit metric/log | pending | pending |

If Muse scout p95 exceeds 600 seconds, test `reasoningBudget: 8192` against the
same corpus before changing any other knob.

## Hermes direct-session evaluation

The existing Hermes PVC is expected to retain a LiteLLM provider. Verify the
provider URL, select the `coordinator` alias, and exercise a resumable encrypted
DM without granting Hermes gateway/merge/cluster authority. Record tool
fidelity, session resume behavior, Matrix media handling, and token accounting.
Only design the harness bridge if this evaluation fails a concrete use case.
