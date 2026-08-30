> **SUPERSEDED by `d4-qwen4exp-results-v2.md` (2026-08-29).** The measurements
> below are sound, but the bottleneck attribution is wrong: this document
> assumes 3.3 GB/token and concludes decode is limited by "per-core random-block
> DRAM streaming" with 1.5–2× of efficiency left on the table. Decode was
> actually moving **7.2 GB/token** (measured with the Zen2 DF counters) at 73%
> of the machine's real 46 GB/s ceiling — because `UD-Q4_K_XL` keeps every
> dense tensor at Q8_0. Requantizing those locally gives **+44% decode and
> +79% prefill**. §5's open question, §6's MTP retraction, §8's unattributed
> 27B restart and §9.4's storage claim are all revised in v2.

# D4 results — Qwen3.8-Flash-Next (qwen4exp) on kristeva and iggy

2026-08-28/29 MDT. Full bench of `Qwen/Qwen3.8-Flash-Next` via unsloth
GGUF on llama.cpp build 10666, CPU-only, on two cluster nodes.
Supersedes the short results stub in `d4-qwen4exp.md`; raw context in
`bench-notes.md`.

## TL;DR

| node | CPU | best warm decode | verdict (bar 5 / kill 2) |
| --- | --- | --- | --- |
| kristeva | 2× Xeon E5-2680 v2 (Ivy, AVX+F16C) | **4.6 t/s** (20 thr) | FAIL (close) |
| iggy | Ryzen 9 3900X (Zen2, AVX2+FMA) | **5.06 t/s** (8 thr) | **PASS, borderline** |

Decode is limited by **per-core random-block DRAM streaming** under the MoE
access pattern, not by ALU throughput and not by aggregate bandwidth. AVX2
doubled single-thread speed (t1: 0.78 → 2.25 t/s) but did not move the
multi-thread plateau (4.5 → 5.0), because each core's block-stream rate,
not the dot-product rate, sets the ceiling.

**Open question (raised by user, unresolved):** 16.5 GB/s effective on
iggy's 2ch DDR4-3200 (51 GB/s peak) is only ~32% efficiency for access
that is mostly contiguous 6 MB blocks. A conservative estimate for this
workload on 3900X is 8–12 t/s. Something is leaving ~1.5–2× on the table —
candidates in §7.

## Environment

- **Model:** qwen4exp arch — 125B total / 6B active MoE (512 experts,
  top-10 + 1 shared per layer, 48 layers, hidden 2560) + 20M×2560 n-gram
  lookup table (layer 2, pure `ggml_get_rows`, ~40 GiB at Q4) used by QSA
  sparse attention + 4B MTP head (**not used** — no MTP support in b10666).
- **Quant:** UD-Q4_K_XL, 103.7 GiB, 4 parts (exact-size verified vs HF API:
  10,946,624 + 49,859,583,136 + 49,376,141,504 + 12,087,983,520 B).
  Also tested: UD-Q3_K_XL, 83.8 GiB, 3 parts.
- **Runtime:** `ghcr.io/ggml-org/llama.cpp:server-intel-b10666`
  (digest `sha256:394b0fd7a15f527480c6c9e6ed0a75d5bc5861cfc89b4b8cc6628cd14fc52d3f`),
  IntelLLVM build, all CPU variants, SYCL lib renamed out
  (`mv /app/libggml-sycl.so{,.disabled}` — required, SYCL runtime crashes
  GPU-less hosts). Confirmed on iggy via `/proc/PID/maps`:
  `libggml-cpu-haswell.so` (AVX2 256-bit) loaded.
- **Fixed params:** `-c 8192`, f16 KV (default), `-tb 20`, mmap (page cache
  resident), 393-token fixed prompt + 128-token generation, 4 rounds/arm
  (rounds 2–4 reuse server prompt cache: 4 new prompt tokens; decode
  numbers unaffected). Bench harness:
  `<modeldir>/bench/run-arm.sh` (see §10).
- **kristeva:** dual E5-2680 v2, 128 GiB, 2 TB NVMe.
  **Single NUMA node** (`/sys/devices/system/node/possible` = `0`) despite
  two sockets — kernel sees one flat memory pool, firmware 64B interleave.
- **iggy:** Ryzen 9 3900X 12C/24T, 128 GiB, 474 GB NVMe root (219 GB free
  at bench time), 2nd NVMe (nvme1n1p1) holds the 27B lane's model cache,
  2× RTX 3090 running the `qwen-3-8-fp8` vLLM lane.

## 1. Kristeva round 1 (arms A/B/C/Q)

Caveat discovered later: llama.cpp's default `--numa` mode (distribute)
**overrode `taskset` affinity** (worker mask observed as `fffff` = all 40
CPUs). "Socket-pinned" arm A was actually 10 free-scheduled threads.

| arm | config | warm gen t/s (r2–r4) | r1 (cold) |
| --- | --- | --- | --- |
| A | 10 thr (believed socket-0) | 3.97 / 4.03 / 3.95 | 3.91 (cold load 47 s) |
| B | `--numa distribute`, 20 thr | 4.62 / 4.58 / 4.67 | 4.62 |
| C | 20 thr (believed both sockets) | 4.50 / 4.43 / 4.52 | 4.60 |
| Q | Q3_K_XL, C config | 4.47 / 4.25 / 4.42 | 4.22 |

Cold prompt eval: A 10.4, B 18.3, C 19.0, Q 13.0 t/s.
Memory: anon RSS ~42→74 GB, model pages in page cache (75–97 GB),
pgmajfault warm arms ≈ 0–480, no OOM at 110 Gi limit.
Q4 quality smoke (this run): crontab-parser prompt → correct semantics +
type hints; 17-sheep trap → correct (9).

## 2. Kristeva follow-up suite (after cross-check)

- **E1′** — drop_caches, fresh fault-in with 20 threads spanning both
  sockets: **4.35 / 4.38 / 4.51 / 4.56**. `numa_maps`: N0=16.6 GB, N1=0 —
  **node 1 does not exist** (single-node kernel). Placement/skew
  hypothesis dead; NUMA design chapter void on this machine.
- **E2** — true-pinned thread curve (`--numa numactl` + taskset):

  | threads | 1 | 4 | 8 | 10 | 20 | 40 (HT) |
  | --- | --- | --- | --- | --- | --- | --- |
  | warm t/s | 0.78 | 2.51 | 3.74 | 3.92 | 4.53 | **1.72** |

  Knee at ~8–10; HT is 2.6× worse. Per-thread efficiency decays
  monotonically (2.6 → 2.1 → 1.54 → 0.75 GB/s/token).
- **E3** — 4 concurrent streams (`-np 4`, cont-batching): **aggregate
  4.10 t/s** (2.4 per stream) ≈ single stream 4.53. Zero gain.
- **E4** — 7074-token prompt (vs 393): gen 4.07–4.13 t/s (−10%), prefill
  steady ~19 t/s. QSA/n-gram path is **not** a dominant hidden cost.

## 3. Iggy suite

| run | threads | warm gen t/s (r2–r4) | notes |
| --- | --- | --- | --- |
| G1 | 16 | 4.75 / 4.80 / 4.84 | 27B probe during run: **53.4 t/s** (baseline 67.4) — 20% contention cost |
| Ig (curve) | 1 | **2.25** | 2.8× kristeva t1 → AVX2 dispatch confirmed |
| Ig (curve) | 8 | 5.07 (r2) | knee |
| Ig (curve) | 12 | 4.92 | plateau |
| F8 | 8 | **5.06 / 5.03 / 5.04** | the bar run |
| F8b | 8 | 4.80 / 4.86 / 4.77 | run-to-run variance ~4% |

Prefill: 25.0 t/s (F8). Load 57–83 s warm-cache.
27B baseline (3× 256-tok completions): 67.9 / 66.8 / 67.4 t/s.

## 4. Bottleneck model

**Per-core random-block streaming wall.** Each decode token streams
~3.3 GB as 528 blocks of ~6.4 MB (48 layers × 11 experts), each block a
contiguous multi-MB read with a random start position in a 60+ GiB space
that does not fit L3. Observed: ~2 GB/s per core at the plateau on both
machines (16.5 GB/s aggregate / 8 cores on iggy; ~15 GB/s on kristeva).

Evidence this — and not ALU compute or aggregate bandwidth — is the wall:

1. **AVX2 doubled t1 (0.78→2.25) but not the plateau (4.5→5.0).**
   Compute per byte got 2× cheaper; tok/s didn't follow.
2. **Q3 (−25% bytes/token) was no faster** (4.4 vs 4.6): K-quants add
   ops/byte, roughly offsetting the byte savings — consistent with a
   streaming-rate wall, inconsistent with pure compute or pure bandwidth.
3. **E3: 4-way cont-batching → aggregate unchanged.** Extra batch width
   adds no per-core stream.
4. **E2 curves on both machines:** steep to 8 threads, plateau; monotonic
   per-thread efficiency decay (bandwidth walls are near-linear to the
   knee; this decays from t2).
5. **HT hurts** (kristeva t40: 1.72): shared cores halve per-core stream
   rate.
6. **E4: 18× context cost only 10%** — attention/ngram scaling is minor.

## 5. Efficiency math (the "should be faster" question)

iggy: 2ch DDR4-3200 = 51.2 GB/s peak. Measured 16.5 GB/s = **32%**.
Contiguous 6 MB blocks with ≥8 streams in flight should sustain 50–70%
of peak on Zen2 → expected **8–12 t/s**, i.e. ~1.5–2× headroom exists
somewhere. kristeva: 8×DDR3-1866 (119 GB/s peak, sysbench 70.9 GB/s @ 8
threads) yet delivered ~15 GB/s for this pattern (13%) — DDR3 per-channel
weakness + pattern. Both machines converge on the same ~15–17 GB/s, which
is why the "faster CPU" retarget bought only +7%.

Unresolved suspects (next experiments if this is chased):
- **Raw scattered-read benchmark on iggy was never completed** (pod
  fork+mmap PermissionError in worker processes). If 8 plain readers
  sustain 30+ GB/s on the model file, the llama.cpp MoE CPU path (kernel
  MLP, expert granularity) is the 2×; if ~16 GB/s, the memory system is
  the true wall.
- **Expert-to-thread packing:** 11 experts vs 8 threads at expert
  granularity = 3 threads run 2 experts → 69% packing efficiency; 12
  threads = 92%. The t8≈t12 result argues the kernel splits below
  expert granularity, but it's unverified.
- **Whether the "haswell" build's Q4_K dot actually emits 256-bit
  `vpmaddubwq`** on AMD (Intel-built image; a string scan found none but
  that is not a valid check — needs `objdump -d`). If the integer path
  is 128-bit, that is ~2× in the hot loop.
- Per-thread MLP of the gemv kernel (2.9 KB rows): a poorly unrolled
  loop caps each core at a few GB/s even with perfect DRAM.

## 6. MTP — retracted as a lever

Earlier prediction ("MTP lands → ~9–10 t/s here") is **retracted**: the
upstream ~2× for MTP applies to memory-bound GPU decode with idle FLOPs.
Speculative decoding is batch width in disguise, and E3 measured this
machine's response to extra batch width: zero. Expect <1.3× here.
(Curiously, the 27B vLLM lane's own logs show MTP working on GPU:
mean acceptance length 3.90.)

## 7. Verdict vs criteria

- **kristeva: FAIL** — best 4.67 t/s < 5 bar; ≫ 2 kill. Parked.
- **iggy: PASS at t8 — 5.03–5.06 t/s warm**, marginally. A permanent lane
  at t8 is viable subject to the 27B coexistence check (§8).
- Cluster ceiling: no node combines the RAM (≥104 GiB) with 4+ memory
  channels to beat this wall (nuc-1/2/3 have VNNI but 91 GiB — Q4
  doesn't fit; iggy is the best fit).

## 8. 27B lane impact (constraint: do not affect it)

- Baseline 66.8–67.9 t/s. **t16 bench: 53.4 t/s (−20%)** — t16 is banned
  for any co-located lane. t8 impact: unmeasured (probe script bug lost
  the DURING sample); one clean t8 run + mid-run probe still owed after a
  stability watch.
- **27B pod restarted once, ~00:34** (`SandboxChanged` → kubelet killed +
  re-created the sandbox). Previous container's log ended normally at
  00:34:31 (all /health 200) → external SIGKILL, not a crash. Coincides
  with both the flux ~30-min reconcile wave (00:03:50, 00:34:11; qwen
  survived the first) and my F8 run. openebs provisioner ruled out
  (no iggy activity). **Root cause unattributed.** Pod recovered
  (1/1, /health OK). Watch through the next wave before further runs.
- Its model cache is mounted from **nvme1n1p1** (XFS partition), not from
  the (nonexistent) openebs hostpath directory the PV metadata claims.

## 9. Incidents & cluster findings

1. **kristeva `/var/mnt` deleted** (~23:00, during/after bench round 1):
   `nvme0n1p1` (1.8 TB XFS, was mounted at `/var/mnt/local-hostpath`)
   unmounted and the entire `/var/mnt` tree removed. No XFS errors, no
   reboot (19 d uptime), no flux job, no provisioner activity, not in the
   Talos machine config. Superblock still alive (held by running pods'
   mounts — camofox et al. unaffected), **data intact** (incl. both model
   copies, 187 GiB). Cannot re-mount in host namespace while any pod holds
   a mount of the same superblock ("Device or resource busy"). Restore
   = restart kristeva's hostpath-lane pods (camofox, bge-m3,
   bge-reranker, vision-cpu, litellm-db, open-webui-db). **Actor unknown —
   could recur.**
2. **openebs-localpv-provisioner 4.3.3 stuck** cluster-wide: work queue
   saturated with stale PV deletions on dead nodes (nuglab-4 etc.); new
   hostpath PVCs are never provisioned (survived controller restart +
   annotation requeue). Worked around with raw hostPath pods for the
   bench. All stale PVs (incl. both iggy PVs whose paths don't exist)
   deserve a cleanup pass.
3. **iggy kubelet hostPath quirk:** `type: Directory` check failed
   ("is not a directory") on a verified-good directory for 25+ retries;
   `type: DirectoryOrCreate` worked. Unexplained.
4. **iggy is Ryzen 9 3900X** (12C/24T), not a Xeon — single socket, 2ch
   DDR4, single NUMA node. The stale 150 GiB `cuda-dev-workspace` + 450 GiB
   `llmkube-model-cache` openebs PVs point at a `/var/mnt/local-hostpath`
   that does not exist (node was evidently rebuilt at some point).

## 10. Reproduction

Artifacts: model files at
- kristeva: `/var/mnt/local-hostpath/d4-qwen4exp/` (Q4 103.7 GiB + Q3
  83.8 GiB) — only reachable after the §9.1 mount is restored.
- iggy: `/var/lib/d4-qwen4exp-bench/d4-qwen4exp/` (Q4 only).
- Harness + prompts: `<modeldir>/bench/{run-arm.sh,prompt.txt,prompt-long.txt}`
  on both nodes (iggy copy current; kristeva copy has the numa-audit
  variant). `run-arm.sh ARM CPUS THREADS [EXTRA ARGS]`, env
  `MODEL`/`PROMPT`/`NROUNDS`. Results appended to `<modeldir>/bench/results.txt`.
- Pod manifests used: `/tmp/d4-bench.yaml` (kristeva),
  `/tmp/d4-bench-iggy2.yaml` (iggy, DirectoryOrCreate),
  `/tmp/d4-iggy-dl.yaml` (download). All throwaway pods deleted.

Operational gotchas (cost time, keep for next time):
- SYCL rename preamble required on GPU-less nodes.
- `taskset` is overridden by llama.cpp's default `--numa` (distribute) —
  use `--numa numactl` for external affinity.
- Image RUNPATH is `/app/build/bin:` (empty = cwd): launch the server from
  cwd `/app` or set `LD_LIBRARY_PATH=/app`.
- `/completion` timings are nested under `timings.*` (b10666); majflt is
  `/proc/PID/stat` field **12**.
- `curl -s` exits 0 on 503 — readiness probes need `-f`.
- `pkill -f llama-server` self-matches the calling shell's cmdline.
- Unquoted heredocs through `kubectl exec sh -c` eat `$vars`; quote the
  delimiter.
- `kubectl apply` on a just-deleted pod races → use `create`.

## 11. Recommendations

1. **iggy t8** is the only bar-clearing config; make it the permanent-lane
   candidate, pending (a) one clean t8 run with a working mid-run 27B
   probe, and (b) the 27B pod surviving ≥1 more flux wave without restart.
2. **Do not co-locate >8 llama threads** with the 27B lane on iggy.
3. Park kristeva (4.5 t/s ceiling + the mount incident).
4. If the ~2× headroom in §5 is worth chasing, run the three §5
   experiments (raw scattered-read BW; disassemble the q4_k dot for
   256-bit ops; expert/thread packing check) before any kernel work.
5. Separately: clean up stale openebs PVs + the stuck provisioner, and
   investigate the kristeva `/var/mnt` deletion (possible recurrence risk
   for any node-local storage).
