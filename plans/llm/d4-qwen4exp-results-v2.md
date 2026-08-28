# D4 results v2 — Qwen3.8-Flash-Next (qwen4exp) on iggy, CPU-only

2026-08-29 MDT. Supersedes `d4-qwen4exp-results.md` (v1). v1's measurements
were correct; its **bottleneck attribution was wrong**, and the corrected
model produced a real speedup. Raw context in `bench-notes.md`.

## TL;DR

| | v1 best (iggy) | v2 best (iggy) | change |
| --- | --- | --- | --- |
| decode, warm | 5.06 t/s (t8) | **6.88 t/s (t8)** | **+36%** |
| prefill (pp2048, t12) | 33.9 t/s | **53.1 t/s** | **+57%** |
| bytes/token | assumed 3.3 GB | **measured 7.2 GB → 4.3 GB** | −40% |
| model on disk | 103.7 GiB | 93.1 GiB | −10% |

**What v1 got wrong.** v1 assumed 3.3 GB/token (6 B active × 4 bits) and
therefore computed 16.5 GB/s effective = "32% of a 51 GB/s bus", concluding
~1.5–2× of efficiency was being left on the table and that decode was
"per-core random-block streaming limited". Both halves are wrong:

1. **The machine does 46 GB/s on exactly this access pattern**, not 16.5.
   A purpose-written microbenchmark (random 6.4 MB blocks, the MoE pattern)
   sustains 45–46 GB/s at 4+ threads and **26.8 GB/s from a single thread**.
   Transparent huge pages change nothing. There is no per-core streaming wall.
2. **Decode was actually moving 7.2 GB/token, not 3.3.** Measured directly
   with the Zen2 Data Fabric DRAM counters. That is **34.0 GB/s = 73% of the
   machine's practical ceiling** — llama.cpp was already near the bandwidth
   wall, so there was never 2× of "efficiency" to recover.

**The real lever was bytes/token, and it was hiding in the quant mix.**
`UD-Q4_K_XL` keeps every *dense* tensor at **Q8_0**. Those tensors are small
on disk (8.6 GiB of 103.7) but are read **in full on every token**, while the
512-expert FFN tensors that dominate the file are only read 10/512 at a time.
Result: **72% of each token's DRAM traffic was Q8_0 weights in a file labelled
Q4_K.** Requantizing them locally is worth ~1.4×.

This also explains v1's "Q3 was no faster" tell (§4.2), which v1 read as
evidence of a compute bound: UD-Q3_K_XL shrinks only the routed experts —
about a quarter of per-token traffic — and leaves the Q8_0 dense weights
untouched.

## 1. Machine ground truth

iggy: Ryzen 9 3900X (12C/24T, Zen2, 4 CCX × 16 MiB L3), 125.7 GiB RAM,
2-channel DDR4, single NUMA node, Talos v1.13.5 / kernel 6.18.36.

`bench/membw.c` — threads read randomly-chosen ~6.4 MB contiguous blocks out
of a 16 GiB buffer (the per-expert access shape), sum them, report GB/s:

| threads | 1 | 4 | 8 | 12 | 24 |
| --- | --- | --- | --- | --- | --- |
| random 6.4 MB blocks, 4 KiB pages | 26.84 | 43.69 | **45.96** | 45.10 | 43.94 |
| same, `MADV_HUGEPAGE` | 29.26 | 43.40 | **46.25** | 45.02 | 43.89 |
| sequential, 4 KiB pages | — | — | — | 45.03 | — |

Conclusions: the practical ceiling is **~46 GB/s** (90% of DDR4-3200 dual
channel peak); four threads already reach 95% of it; **huge pages are
irrelevant** (so the TLB/prefetcher-across-page-boundary hypothesis is dead,
and no tmpfs/hugetlbfs weight staging is worth building).

**DRAM counter calibration.** `amd_df/dram_channel_data_controller_{0,1}/`
count 64 B each; channels 2/3 count something else and must be ignored.
Validated against the microbenchmark: 0.732e9 counts/s × 64 B = 46.9 GB/s
vs. 45.27 GB/s measured by the program itself.

## 2. Where the bytes actually go

Tensor map of `UD-Q4_K_XL` (`bench/tensors.py`), and per-token active bytes.
The model is 125 B core / ~6.6 B active, plus a 51 B-parameter PLE ("n-gram")
table; llama.cpp's own `A3B` label is an undercount (it sees only the routed
expert FFN) and its `176.94 B` total is core + PLE table.

| tensor class | stored type | on disk | **bytes/token** |
| --- | --- | --- | --- |
| `per_layer_token_embd` (PLE table, 320 M × 160) | IQ4_NL | 26.82 GiB | ~0 (16 rows) |
| `ffn_{gate,up}_exps` (512 experts, top-10) | Q4_K | 41.30 GiB | 884 MB |
| `ffn_down_exps` | Q5_1 (43 lyr) / Q8_0 (5) | 29.35 GiB | 615 MB |
| `attn_qkv` (36 SSM layers, 2560→10240) | **Q8_0** | 0.93 GiB | **1003 MB** |
| `attn_gate`, `ssm_out` (36 lyr each) | **Q8_0** | 1.12 GiB | **1202 MB** |
| `attn_q/o/k/v` (12 full-attn layers) | **Q8_0** | 0.58 GiB | **635 MB** |
| `hc_*` hyper-connection projections (4 × 48) | **Q8_0** | 0.64 GiB | **668 MB** |
| `output.weight` (LM head) | **Q8_0** | 0.63 GiB | **676 MB** |
| shared expert (48 lyr) | **Q8_0** | 0.24 GiB | **251 MB** |
| `ffn_gate_inp` (MoE router) | F32 (forced) | 0.23 GiB | 252 MB |
| misc F32/BF16 (ssm_alpha/beta, conv1d, indexer) | F32/BF16 | small | 80 MB |
| | | | **≈6.27 GB** |

Plus ~0.9 GB/token of non-weight traffic (36 SSM states of 6144 × 128 F32 =
113 MB read + 113 MB written per token, KV, activations, PLE rows) — the
measured 7.2 GB/token.

Architecture notes worth recording: 48 layers, hidden 2560, 512 experts /
top-10 + 1 shared, expert FFN 640. Only **12 of 48 layers are full attention**
(`full_attention_interval: 4`) with a DeepSeek-style sparse indexer
(`indexer.top_k: 2048`); the other **36 are SSM/gated-delta-net** layers
(`ssm.inner_size 6144`, `state_size 128`). Hyper-connections
(`hyper_connection.count: 4`) add four projections per layer. The PLE table
is 16 heads × ~20 M rows × 160 dims, ~16 row lookups per token.

## 3. Profile of the stock model (t12, `perf record`)

```
48.46%  ggml_vec_dot_q8_0_q8_0        <- the dense Q8_0 weights, generic path
17.01%  kmp_flag_64::wait             <- Intel OpenMP barrier spin
 9.73%  ggml_gemv_q4_K_8x8_q8_K       <- routed experts, REPACKED path
 8.70%  __intel_avx_rep_memcpy
 5.65%  ggml_vec_dot_q5_1_q8_1        <- ffn_down_exps, generic path
 3.17%  ggml_vec_dot_f32              <- F32 MoE router
```

Two things fall out. Half the cycles are the Q8_0 dense weights. And type
choice selects the *kernel*, not just the size: Q4_K and IQ4_NL get ggml's
repacked `gemv_*_8x8` kernels, while Q5_1, Q6_K and Q8_0 fall back to the
generic `vec_dot`. So moving a tensor to Q4_K/IQ4_NL is a double win.

## 4. What was tried and did not work

Recorded so it is not re-litigated:

- **Transparent huge pages** — no effect on raw bandwidth at any thread count
  (§1). Not TLB-bound; do not build tmpfs/hugetlbfs weight staging.
- **Thread affinity / OpenMP tuning** — every variant was worse than the
  default. t12 baseline 4.93 t/s; `OMP_PROC_BIND=close OMP_PLACES=cores`
  4.11; adding `KMP_BLOCKTIME=0` 2.81. The barrier time is threads waiting on
  memory, not schedulable overhead.
- **SMT** — pp2048 t24 46.6 vs t12 53.1; tg64 t24 4.04 vs t8 6.88. Confirms
  v1.
- **`-ub`/`--ubatch-size`** — the default 512 is optimal (52.7 t/s vs 52.1 at
  256/1024 and 49.5 at 2048).
- **A newer llama.cpp + ggml's native threadpool.** b10666 is the newest
  published `server-intel` image (b10667–b10679 have none), so b10679 —
  which contains `qwen4exp: reduce number of graph splits` (#27880) and
  `disable non-fused GDN and LID ops` (#27877) — was built from source with
  `-DGGML_NATIVE=ON -DGGML_OPENMP=OFF`. On D4X: decode **6.85 t/s @ t8**
  (image: 6.88) and prefill **47.4 t/s @ t12** (image: 53.14). The graph-split
  change is not a decode lever here, and a GCC native build with ggml's own
  threadpool is ~11% *worse* at prefill than the IntelLLVM + libiomp5 image.
  Stay on the b10666 image.

## 5. The fix: requantize the dense tensors locally

No download needed. `llama-quantize --allow-requantize` reads the existing
`UD-Q4_K_XL` and rewrites it; tensors already at the target type are **copied,
not re-encoded**, so the 512-expert bulk is untouched and only the ~9 GiB of
Q8_0 dense tensors actually get quantized. Q8_0 is near-lossless, so
requantizing *from* it is close to quantizing from BF16.

Two variants were built (`/work/d4s` on iggy = `/var/mnt/local-hostpath/d4-work`,
nvme1n1p1):

**D4S** — dense → Q4_K, `ffn_down_exps` kept Q5_1, LM head Q6_K.
100.31 GiB, 4.87 BPW, **2.3 min** to build.

**D4X** — as D4S plus `ffn_down_exps` → IQ4_NL and LM head → Q4_K, i.e. every
hot tensor moved onto a *repacked* kernel. 93.13 GiB, 4.52 BPW, **16.8 min**
(IQ4_NL's search is the slow part).

```
llama quantize --allow-requantize --pure \
  --tensor-type per_layer_token_embd=iq4_nl \
  --tensor-type ffn_down_exps=iq4_nl --tensor-type ffn_down_shexp=iq4_nl \
  --tensor-type hc_attn_up=iq4_nl --tensor-type hc_ffn_up=iq4_nl \
  --tensor-type output_hc_up=iq4_nl \
  --tensor-type hc_attn_inject=f32 --tensor-type hc_ffn_inject=f32 \
  --tensor-type ssm_alpha=f32 --tensor-type ssm_beta=f32 \
  --output-tensor-type q4_K --token-embedding-type q6_K \
  <stock 00001-of-00004.gguf> Qwen3.8-Flash-Next-D4X-IQ4.gguf Q4_K 12
```

Recipe notes learned the hard way:

- `--pure` is required, otherwise the k-quant mixture re-inflates tensors.
- **Row length decides what is legal.** k-quants need `ne[0] % 256 == 0`.
  `ffn_down_exps` and `ffn_down_shexp` are `[640, …]` and `hc_*_up` are
  `[320, …]`, so they can only take block-32 types — which is exactly why
  unsloth used Q5_1 there. IQ4_NL is the fast, small, legal choice; without an
  explicit override they silently fall back to Q5_0.
- **`ffn_gate_inp` cannot be quantized** — llama.cpp forces the MoE router to
  F32. Its 252 MB/token is a floor.
- Keep `ssm_alpha`/`ssm_beta`/`hc_*_inject` at F32 explicitly; `--pure` would
  otherwise quantize these tiny, sensitive gating tensors for ~30 MB/token.
- `ple_conv1d` `[4, 10240]` is the one unavoidable fallback (→ F16).

## 6. Results

All numbers `llama-bench`, image `server-intel-b10666`, warm page cache,
`-r 3` for tg / `-r 2` for pp.

| model | on disk | BPW | tg64 t6 | **tg64 t8** | tg64 t12 | pp2048 t12 |
| --- | --- | --- | --- | --- | --- | --- |
| UD-Q4_K_XL (stock) | 103.68 GiB | 5.03 | 4.38 | 4.86 | 4.93 | 33.86 |
| D4S | 100.31 GiB | 4.87 | — | 6.41 | 6.32 | 44.49 |
| **D4X** | **93.13 GiB** | **4.52** | 6.78 | **6.88** | 6.78 | **53.14** |

Prefill thread curve on D4X (pp2048): t8 41.36, **t12 53.14**, t16 48.14,
t24 46.57. Decode is flat from 6 to 12 threads (6.78–6.88) — it saturates at
**6 cores**, which matters for co-tenancy with the 27B GPU lane (v1 §8 banned
t16 because it cost that lane 20%).

DRAM traffic, measured with the calibrated DF counters during decode:

| model | GB/s | t/s | **bytes/token** | % of 46 GB/s ceiling |
| --- | --- | --- | --- | --- |
| stock | 34.0 | 4.7 | 7.2 GB | 73% |
| D4S | 27.8 | 6.0 | 4.6 GB | 60% |

Profile after the change (D4S, t8) — the Q8_0 hot spot is gone and the
repacked Q4_K gemv leads:

```
35.89%  ggml_gemv_q4_K_8x8_q8_K
21.97%  kmp_flag_64::wait
 9.06%  ggml_vec_dot_q5_1_q8_1   <- removed in D4X (ffn_down_exps -> IQ4_NL)
 8.94%  __intel_avx_rep_memcpy
 6.94%  ggml_vec_dot_q6_K_q8_K   <- removed in D4X (LM head -> Q4_K)
 4.12%  ggml_vec_dot_f32         <- the F32 router, irreducible
 3.06%  ggml_gemv_iq4_nl_8x8_q8_0
```

**Quality.** D4S and D4X both answer the v1 smoke prompts correctly
(17-sheep trap → 9; crontab parser with correct semantics). The model emits
`<think>` blocks, so smoke prompts need `n_predict` ≥ 300 to reach the answer.

## 7. Cluster findings (corrections to v1 §8/§9)

**The 27B lane's mystery restart is attributed: Talos's userspace OOM
controller.** v1 §8 recorded a `SandboxChanged` kill of `qwen-3-8-fp8` with
"root cause unattributed". `dmesg` on iggy shows Talos v1.13's
`runtime.OOMController` firing repeatedly under the bench's page-cache
pressure and sending SIGKILL to whole cgroups:

```
[talos] OOM controller triggered {"controller": "runtime.OOMController"}
[talos] Sending SIGKILL to cgroup {"cgroup": ".../besteffort/pode37f8fd9-..."}
```

The four victim cgroup UIDs map to `llm/qwen-3-8-fp8`,
`cluster-infra/dcgm-exporter`, `home-infra/immich-db-3` and
`llm/open-webui-db-2` — **every one of them BestEffort**. The controller picks
BestEffort cgroups first, and `qwen-3-8-fp8` has no resource requests at all,
so the cluster's most important GPU workload is also its first OOM victim.
Two fixes, independent of D4: give `qwen-3-8-fp8` requests/limits so it is at
least Burstable, and keep any bench pod's memory limit below
`node total − other pods` (a 110 Gi limit on a 125.7 GiB node cannot be
satisfied and guarantees pressure).

**In-place pod resize works and is the right tool here.** k8s 1.34's
`kubectl patch pod … --subresource resize` changed the bench pod's memory
limit from 110 Gi to 86 Gi with no restart (`memory.max` = 92341796864
confirmed in the cgroup). That is how to walk the page-cache budget between
arms without reloading a 90+ GiB model.

**v1 §9.4 is wrong about iggy's storage.** `/var/mnt/local-hostpath` does
exist and *is* mounted — `/dev/nvme1n1p1`, XFS, 931 GB with **475 GB free**.
The openebs PVs pointing at it are live, not stale; `llmkube-model-cache`
holds 364 GB. This is where the requantized models were written, and it is the
right place for D4 artifacts — nvme0n1p4 (the Talos EPHEMERAL partition, where
v1 put them) had only 116 GB free, and writing a ~95 GiB model there would
have crossed kubelet's `nodefs.available<10%` eviction threshold.

**Operational gotchas (in addition to v1 §10).**

- Do **not** set `LD_LIBRARY_PATH=/app` — that clobbers the image's oneAPI
  paths and `llama-server` then fails with `libsvml.so: cannot open shared
  object file`. Prepend instead: `LD_LIBRARY_PATH=/app:$LD_LIBRARY_PATH`.
- `perf` works in a privileged pod: `apt-get install linux-tools-generic`
  (Ubuntu's 6.8 build samples the 6.18 Talos kernel fine) plus
  `echo -1 > /proc/sys/kernel/perf_event_paranoid`.
- A readiness loop must break on `kill -0 $SRV` failing, or a server that dies
  at startup costs a full 900 s timeout before you see the error.

## 8. RAM: what is actually resident, and where the n-gram table lives

The plan doc's design — "core weights resident, n-gram table streams from
NVMe, page cache holds the hot rows" — is what happens, but **not by page-cache
LRU**. llama.cpp's CPU **repack** buffer type is doing it. From the load log
(D4X, `-lv 4`):

```
CPU : ... AVX2 = 1 | F16C = 1 | FMA = 1 | LLAMAFILE = 1 | REPACK = 1
load_tensors:   CPU_Mapped model buffer size = 95017.43 MiB
load_tensors:   CPU_REPACK model buffer size = 67060.55 MiB
llama_kv_cache: CPU KV buffer size = 192.00 + 72.00 MiB
llama_memory_recurrent: CPU RS buffer size = 450.28 MiB   <- 36 SSM layers' state
sched_reserve:  CPU compute buffer size = 205.22 MiB
```

and from the process itself:

```
RssAnon:   69566088 kB  (66.3 GiB)   <- repacked matmul weights: PINNED
RssFile:   20253524 kB  (19.3 GiB)   <- page cache for the mmap'd file
```

**Every tensor that feeds a `mul_mat` gets copied out of the mmap and repacked
into anonymous memory** so the `gemv_*_8x8` kernels can use it. That memory is
not reclaimable. The **PLE / n-gram table is not repacked** — it is only ever
touched by `ggml_get_rows`, so it stays file-backed and streams from NVMe, with
the page cache holding whatever hot subset fits.

So the split the plan wanted is automatic, but the numbers are different from
the plan's estimate:

| | plan (v1) | measured |
| --- | --- | --- |
| core weights | ~63.6 GiB, page-cache resident | **65.5 GiB, anonymous, pinned** |
| n-gram table | ~40 GiB, streams | **26.8 GiB, streams (file-backed)** |
| KV + recurrent state + compute | ~1–2 GiB | 0.9 GiB (0.26 KV + 0.45 RS + 0.2 compute) |
| **hard RAM floor** | — | **~68 GiB** |

**Consequences.**

1. **Do not size the pod by page cache.** ~68 GiB is a hard floor, not a soft
   one: dropping the cgroup limit to 62 GiB **OOM-killed the container**
   (exit 137) even though the file was mmap'd, because two thirds of it is
   anon. 72 Gi request / 80 Gi limit is the right shape; anything above that
   is n-gram cache, which §9 shows buys nothing.
2. **A 110 Gi limit on a 125.7 GiB node is what caused v1's collateral
   damage** (§7). Since capping the bench pod at 86 Gi, iggy has logged **zero**
   further Talos OOM events in 2.2 h and the 27B lane has not restarted.
3. **Cold start is repack-bound, not IO-bound**: ~60–70 s to load, most of it
   spent repacking 65.5 GiB, not reading it.
