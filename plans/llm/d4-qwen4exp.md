# D4: Qwen3.8-Flash-Next (qwen4exp) on kristeva

Goal: clear the **5 tok/s** decode bar on kristeva with a model whose core
weights stay resident in RAM and whose n-gram table is backed by the local
NVMe (page cache). D4 is the first candidate where the math plausibly works:
6B active params at 4-bit ≈ 3–3.6 GB streamed per token.

Status: **run — PASS on iggy** (2026-08-31, **10.9 t/s** decode with the MTP
draft head, up from 6.65 after the v2 requantization; kristeva FAIL at 4.6 t/s).
This document is the pre-run plan of record; see the Results section at the
bottom, then `d4-qwen4exp-results-v3.md` (current) and
`d4-qwen4exp-results-v2.md` for what was measured.

## The model (verified facts)

- `Qwen/Qwen3.8-Flash-Next`, released 2026-08-24. Experimental `qwen4exp`
  arch: core LM 125B total / **6B active** (512 experts, top-10 + 1 shared,
  48 layers, hidden 2560, 262K ctx), plus a **51B-parameter n-gram table**
  (20M entries × 2560, bigrams/trigrams, layer 2, pure lookup) plus a 4B MTP
  head.
- The n-gram table is a **plain model tensor** (`per_layer_token_embd`,
  ~97.7 GiB full-precision): row indices computed on host, rows pulled with
  `ggml_get_rows`. No special disk mode — on a CPU box it is RAM/page-cache
  backed. Per-token cost of the table is 1–3 rows ≈ 2.5–7.5 KB, so even a
  fully cold NVMe-backed table adds a few ms per token.
- llama.cpp support: PR ggml-org/llama.cpp#27742, merged 2026-08-27; in
  release **b10666** (commit `4e97ac86e`, built 2026-08-28). No MTP support
  in the PR (watch item — iggy's A2 showed MTP=3 ≈ 2× decode).
- Quant: `unsloth/Qwen3.8-Flash-Next-GGUF` — **UD-Q4_K_XL = 103.7 GiB**
  total (core ≈ 63.6 GiB + table ≈ 40 GiB + MTP, mixed precision), plus a
  full ladder; **UD-Q3_K_XL = 83.8 GiB** (core ≈ 50 GiB) is the Q-arm
  candidate (~25% fewer bytes/token, quality smoke required).

## Runtime (verified)

- Image: `ghcr.io/ggml-org/llama.cpp:server-intel-b10666`, pin amd64 digest
  `sha256:394b0fd7a15f527480c6c9e6ed0a75d5bc5861cfc89b4b8cc6628cd14fc52d3f`.
- Ships the full CPU ISA variant ladder; **`libggml-cpu-ivybridge.so`** is
  the exact match for kristeva (SSE4.2 + AVX + F16C; live cpuinfo shows
  `avx`+`f16c` only — no AVX2/FMA/AVX-512). Runtime dispatch picks it.
- **Gotcha (reproduced on kristeva, 2026-08-28):** the image auto-loads
  `libggml-sycl.so`; its oneAPI runtime throws
  `can not find preferred GPU platform` on GPU-less hosts, crashing even
  `--version`. Fix verified: command preamble
  `mv /app/libggml-sycl.so{,.disabled}` (CPU lane only).
- No custom build needed; the official image beats a hand-rolled
  `-DGGML_AVX=ON -DGGML_F16C=ON` binary (same ISA path, proven deploy route).

## Storage (verified)

- kristeva has a 2 TB NVMe (`nvme0n1p1` → `/var/mnt/local-hostpath`, XFS,
  `openebs-hostpath` SC, ~1.8 TB free). Plan: new **~120 GiB hostpath PVC
  pinned to kristeva**; copy the GGUF from HF (or the NFS
  `llm-model-archive` PVC if it lands there first).
- D2's failure mode (active weights re-faulting over NFS) does not apply:
  only ~5 KB/token of n-gram rows can miss, and they miss against NVMe.

## RAM / storage split — core resident, n-gram table streams from NVMe

**Why the table's location barely matters (decides the whole design):** per
token, decode streams **~3–3.6 GB of core weights** (6 B active @ Q4) but
only **~2.5–15 KB of n-gram table** (2–3 rows × 2560 dims). The table is
**~2×10⁵–1.4×10⁶× smaller per token**, so tok/s is set by core-weight RAM
bandwidth (the A3 ceiling), *not* by where the table lives. A dedicated
"hot n-gram cache in RAM" buys **<1% on decode — we do not reserve RAM for
one.** (Prefill is the one phase where a cached table helps a little — a
long prompt reads one row-set per prompt token, ~1–2 s cold vs ~ms warm on a
20–80 s CPU prefill — but the page cache provides that for free, below.)

**Mechanism:** core + table ship as **one** 103.6 GiB GGUF on the NVMe
hostpath, `mmap`'d. Stock llama.cpp has **no per-tensor "pin in RAM / stream
from disk" flag and no tunable hot-cache size** — the kernel page cache (one
global LRU) is the only layer, and core + table pages compete in it. It
converges to the right split automatically because the access frequencies
differ ~300×:

- **Core (≈63.6 GiB): resident.** Touched across every sequence → LRU keeps it.
  This *is* the "core in RAM" requirement, achieved without a special flag.
- **n-gram table (≈40 GiB at UD-Q4_K_XL; 97.7 GiB full-precision): streams
  from NVMe.** A few scattered rows/token; a cold row is a random 4 KB NVMe
  read at **~100–200 µs** (not 1 ms) ≈ **<0.5 ms/token**, serialized on the
  autoregressive critical path (can't prefetch token *t+1*'s trigram before
  sampling *t+1*) but **<1% of a 200 ms token**. Negligible.

**RAM budget (128 GiB) — we pin what decode needs, not the whole file:**

| consumer | GiB |
| --- | --- |
| floor pods (camofox + D1 + A380) | ~13 |
| core weights resident | ~63.6 |
| KV cache (f16, 8–16k) | ~1–2 |
| runtime / overhead | ~1–2 |
| **total needed** | **~81** |
| **headroom** | **~47** |

The ~47 GiB headroom (a) keeps the **core** safe from LRU eviction, (b)
absorbs floor-pod spikes, and (c) lets the page cache opportunistically warm
table rows for free — so the table may end up mostly-cached anyway (bonus,
helps prefill) or fully streamed (fine). **Decode is fast in both cases.**
This is more robust than "fit the whole 103.6 GiB file in RAM." If the floor
pods grow, table pages evict first and stream — no action needed.

Pod: request ~85 Gi / limit ~110 Gi (sized to ~81 GiB needed + margin,
**not** to the 103.7 GiB file). File page cache IS charged against the pod's
cgroup limit (v2) but is reclaimable — a 110 Gi limit lets ~25–29 GiB of
table warm into cache; machine total ≈ 13 + 110 = 123 GiB, ~5 GiB spare.
Instrument: tok/s, effective GB/s (= bytes/token × tok/s),
`pgmajfault`/token (≤ 10 = healthy), RSS + page-cache.
Optional prefill speedup: one-shot `POSIX_FADV_WILLNEED` warm pass over the
table byte range (~40 GiB, ~30 s from NVMe; fits the headroom) — bench
variant, not the default.

## NUMA / threading — bench arms (revised 2026-08-28 after Claude cross-check)

There is **no CPU TP / layer-parallelism** in llama.cpp: one global thread
pool, every thread reads every tensor. `--numa distribute` is round-robin
thread affinity only (confirmed in source; no `set_mempolicy`/`mbind`
symbols in the b10666 binaries) → each thread reads ~50% of its bytes over
QPI. True per-node sharding exists only as stalled PR #14232
(`GGML_NUMA_MIGRATE`, open since Apr 2026); `--numa mirror` (#16000, draft)
needs 2× RAM. Measured prior: sysbench 70.9 GB/s @ 8 threads (one socket)
vs 52.7 @ 32 (cross-socket).

**Verified confound (b10666 `src/llama-mmap.cpp:472,507`):** enabling any
`--numa` mode also flips the model mmap policy — it zeroes the WILLNEED
prefetch and marks the **whole** 103.7 GiB mapping `POSIX_MADV_RANDOM`.
So `--numa on/off` is not a clean thread-placement comparison. Arms A and C
run WITHOUT the flag (identical mmap policy); B is "distribute as shipped".

**Open question the bench must settle — bandwidth- vs compute-bound:**
Ivy Bridge has no AVX2; Q4_K dot products run 128/256-bit SSE/AVX1/F16C
paths at a few GB/s per core. If decode is compute-bound (~20 GB/s at 10
cores < ~60 GB/s local DRAM), then 20 physical cores across both sockets
WIN despite QPI — the single-socket prior flips and more threads = more
tok/s. Decision rule: effective GB/s = bytes/token (~3.3) × tok/s;
**< ~30 GB/s ⇒ compute-bound ⇒ favor arms C/Q over A.**

Arms (100–150 tok × 3, warm; record tok/s, effective GB/s, cold load, RSS,
pgmajfault/token):

| arm | config |
| --- | --- |
| A | `numactl --cpunodebind=0 --membind=0,1`, `-t 10` (socket-0 physical cores), no `--numa` |
| B | `--numa distribute`, `-t 20` (10 physical per socket; MADV_RANDOM mmap, as shipped) |
| C | `numactl --membind=0,1`, `-t 20` (both sockets, same mmap policy as A) |
| Q | arm A or C config with **UD-Q3_K_XL** (83.8 GiB): ~25% fewer bytes/token, core ≈ 50 GiB fits one 64 GiB node; quality smoke required |

Fixed across arms: **f16 KV** (default; q8_0 saves only ~1 GiB, not worth
its unproven AVX1 cost), `-tb 20` (prefill is compute-bound — use both
sockets there regardless), ctx 8k–16k (QSA sparse attention handles long
ctx; decode is the bar).

**Do NOT use strict `--membind=0`:** node 0 is 64 GiB and the mmap'd file is
103.7 GiB — under a strict bind policy, page-cache faults beyond the node's
capacity fail. `--membind=0,1` (or `--preferred=0`) keeps the preference
without the cliff.

## Not applicable (so we don't re-litigate)

- AMX / AVX-512 / VNNI / AVX2 — post-Ivy-Bridge, absent.
- GPU offload of the core — 6 GB A380, no ReBAR.
- MTP speculative decoding — not in the PR (future upside).
- Both-socket 2× bandwidth — impossible without #14232 (see NUMA section).

## Steps

1. Hostpath PVC ~120 GiB, `node=kristeva`, `openebs-hostpath`.
2. Copy UD-Q4_K_XL (103.7 GiB, 3 parts) into it from HF (not on the NAS —
   verified 2026-08-28). Q3_K_XL (83.8 GiB) only if the Q arm is scheduled.
3. Lane manifest: pinned digest, SYCL rename preamble, arm-A args.
4. Verify load: `qwen4exp` arch accepted, model ready, RSS sane.
5. Bench arms A, B, C (× 3 each); Q arm if scheduled. Apply the
   bandwidth/compute decision rule (effective GB/s) between arms.
6. Record in `bench-notes.md` as `D4` with the bar verdict.

## Success / kill criteria

- **Pass:** warm decode ≥ 5 tok/s on any arm.
- **Watch:** table-page eviction under floor-pod pressure (if decode drops
  after long runs, re-warm or bump the limit).
- **Kill:** < 2 tok/s warm on arms A and C (and Q if run) → the AVX ceiling
  holds even at 6B active; record, delete lane, same-hour cleanup per D2
  precedent.

## Results — current: `d4-qwen4exp-results-v3.md` (2026-08-31): 10.9 t/s with MTP

**Current status: PASS on iggy, and the bar is now cleared by 2.2x.** v3 adds
the NextN/MTP draft head (llama.cpp PRs #27836 + #28097 plus one local patch)
and rebuilds the branch with oneAPI's `icx`: single-stream decode goes from
6.88 to **10.90 t/s** on code / 9.48 on prose, prefill unchanged at 53 t/s.
v3 also rules vLLM out on this box permanently (no CPU implementation for
`qwen4_exp`; the smallest GPU checkpoint needs ~66 GB against iggy's 48 GiB)
and finds that MTP and `-np 4` batching compete rather than compose, so the
lane's default slot count drops to 1. The v2 section below stands as written.

### v2 (2026-08-29): PASS, 6.65–6.88 t/s

**PASS on iggy.** Requantizing the stock `UD-Q4_K_XL`'s dense
Q8_0 tensors down to Q4_K/IQ4_NL (locally, no download) cuts per-token DRAM
traffic from 7.2 GB to ~4.3 GB and yields **6.65 t/s decode / 52.95 t/s
prefill** at `-t 8 -tb 12`, versus 4.61 / 29.51 for the stock file measured
back-to-back. Artifact:
`/var/mnt/local-hostpath/d4-work/Qwen3.8-Flash-Next-D4X-IQ4.gguf` on iggy
(93.13 GiB). The RAM design in this plan is confirmed but by a different
mechanism than assumed — llama.cpp repacks 65.5 GiB of matmul weights into
*anonymous* memory (hard floor ~68 GiB), while the n-gram table stays
file-backed and streams from NVMe for ~63 KB/token. A dedicated hot-n-gram RAM
cache is unnecessary: the page cache already does it (a repeated prompt goes
from 11,761 major faults to zero) and buys nothing on fresh text.

### Original 2026-08-28 verdict (superseded) — FAIL, close: best warm 4.67 t/s

**Full writeup: `d4-qwen4exp-results.md`** (both machines, all 10+
experiment arms, bottleneck model, incidents). Bottom line: kristeva
4.5 t/s = FAIL (parked); **iggy (Ryzen 9 3900X) 5.03–5.06 t/s at 8
threads = PASS, borderline** — with an unresolved ~1.5–2× efficiency
question on iggy (16.5 of 51 GB/s) and one 27B-lane restart incident to
watch. MTP-as-lever retracted.

Full data: `bench-notes.md` "D4 results" entry. A=4.0, B=4.6, C=4.5, Q=4.4
t/s warm. Decode is compute-bound in the AVX1/F16C dot paths (Q3 no-faster
is the tell); NUMA config bought ≤15%. MTP (absent from the PR, ≈2× per A2)
is the rerun trigger — expect ~9–10 t/s on this hardware. Weights kept on
kristeva NVMe at `/var/mnt/local-hostpath/d4-qwen4exp/`; all d4 pods
deleted.

Deviations from plan (all forced by environment, none by design):
- PVC → direct `hostPath` pod: openebs-localpv-provisioner 4.3.3 was stuck
  (work queue saturated with stale deletions on dead nodes; new PVC never
  queued even after controller restart + annotation requeue).
- `numactl` absent from image → `taskset` on physical-core sets
  (socket0 = cpu 0-9 + HT 20-29; socket1 = cpu 10-19 + HT 30-39 —
  interleaved numbering, verified via /sys).
- Q4_K_XL is 4 parts (103.7 GiB), not 3; bench pod mem req 80 Gi
  (kubelet admission: in-use + req ≤ capacity, page cache counts as in-use).
- Image RUNPATH is `/app/build/bin:` (empty = cwd): server must be launched
  from cwd `/app` or with LD_LIBRARY_PATH=/app.
