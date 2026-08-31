# D4 results v3 — Qwen3.8-Flash-Next on iggy: engine sweep (llama.cpp, MTP, vLLM)

2026-08-31 MDT. Extends `d4-qwen4exp-results-v2.md`, which stands: the D4X
requantization, the ~68 GiB anonymous RAM floor, the NVMe-backed PLE table and
the thread/placement tuning are all unchanged. This run answers three questions
v2 left open:

1. Has anything newer than the pinned `b10666` image moved the numbers?
2. Does the NextN/MTP draft head — v2 §12's largest remaining lever — work on
   CPU, and what is it worth?
3. Can vLLM serve this model on iggy at all?

## TL;DR

**Single-stream decode goes from 6.9 to 10.9 t/s** (code; 9.5 on prose) — a 56%
gain, entirely from the NextN/MTP draft head plus building the branch with the
oneAPI compiler instead of GCC. Prefill is unchanged at 41 t/s (`-t 8`) /
53 t/s (`-tb 12`).

| | v2 best (2026-08-29) | **v3 best** |
| --- | ---: | ---: |
| decode, single stream | 6.88 t/s | **10.90 t/s** |
| decode, aggregate | 11.75 t/s @ 4 streams¹ | 10.47 t/s @ **1** stream |
| prefill pp2048 | 53.14 t/s | 53.14 t/s |

¹ not directly comparable: v2's 11.75 is `llama-batched-bench` steady-state
decode, v3's aggregates are end-to-end server throughput including prefill and
queueing. The like-for-like v3 figure for four non-speculative streams is
10.52 t/s (S4).

Three findings, in order of how much they change the lane:

1. **MTP works on CPU and is worth +38–56%.** llama.cpp PRs #27836 + #28097
   (both still drafts) plus one 8-line patch of ours for the draft pack's tensor
   layout. Draft acceptance 0.86–0.89 at `--spec-draft-n-max 3
   --spec-draft-p-min 0.75`; the confidence gate matters far more than the depth.
2. **MTP and continuous batching compete for the same headroom.** One MTP stream
   (10.47 t/s aggregate) equals four non-speculative streams (10.52) at 4× the
   per-stream rate, and MTP at `-np 4` is *slower* than no speculation at
   `-np 4`. v2's "run with `-np 4`, it's free" is now conditional on actually
   having four concurrent agents.
3. **vLLM cannot run this model on iggy, on any path.** No CPU implementation
   exists — the model lives under `vllm/models/qwen4_exp/{nvidia,amd}/` and the
   package raises "CUDA and ROCm only" — and the smallest usable GPU checkpoint
   needs ~66 GB of VRAM against iggy's 48 GiB. Not a version or nightly problem.

Also settled: **nothing in mainline llama.cpp has moved this workload since
b10666.** The 13–15% prefill gap v2 saw between the image and a source build is
the *compiler* (icx vs gcc), not the version — so any branch can now be built at
full speed.

## Setup

Unchanged from v2. Model `D4X` =
`/var/mnt/local-hostpath/d4-work/d4s/Qwen3.8-Flash-Next-D4X-IQ4.gguf`
(93.13 GiB, 4.52 BPW — the locally-requantized `UD-Q4_K_XL`). Bench pod
`d5-bench` on iggy: hostPath `/var/mnt/local-hostpath`, requests 8 CPU / 72 Gi,
limit 80 Gi, `OMP_PROC_BIND=spread OMP_PLACES=cores`, `-t 8 -tb 12`. The
`qwen-3-8-fp8` GPU lane stayed up throughout and did not restart; no Talos OOM
events. All `llama-bench` numbers are `-p 2048 -n 64 -r 3`, warm page cache.

## 1. Newer llama.cpp buys nothing on this box

`b10666` remains the newest **published** `server-intel` image — verified
against the GHCR tag list today; `server-intel-b10679/-b10690/-b10700/-b10720`
all 404. The comparison is therefore image-vs-tarball as much as version-vs-version.

| build | toolchain | pp2048 t8 | tg64 t8 | pp2048 t12 | tg64 t12 |
| --- | --- | ---: | ---: | ---: | ---: |
| `server-intel-b10666` image (v2, 2026-08-29) | IntelLLVM + libiomp5 | 37.20 | 6.65 | 52.95 | 6.51 |
| **`server-intel-b10666` image (today)** | IntelLLVM + libiomp5 | **41.02** | **7.00** | **53.32** | 6.76 |
| `b10720` release tarball | GCC + libgomp | 35.74 | 6.93 | 47.60 | 6.82 |
| PR #27836+#28097 source build | GCC + libgomp | 36.01 | 6.90 | 47.65 | 6.86 |
| **same source, rebuilt with `icx`/`icpx`** | IntelLLVM + libiomp5 | **40.94** | 6.88 | **53.14** | 6.71 |

Three readings, and the third is the useful one:

- **Decode is pinned at 6.7–7.0 t/s across every build.** The only qwen4exp
  change merged between `b10666` and `b10720` is #27880 (graph splits), which
  v2 already measured as neutral. Mainline has not moved this workload.
- **The ~13–15% prefill gap is the compiler, not the version.** v2 §4 saw a
  GCC source build lose 11% of prefill to the image and attributed it to
  "IntelLLVM + libiomp5 vs GCC + ggml threadpool", leaving the two variables
  entangled. Rebuilding the *same* source tree with the oneAPI compiler already
  in the image (`-DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx`,
  `GGML_OPENMP=ON`) recovers all of it — 40.94/53.14 against the image's
  41.02/53.32. So v2's "stay on the b10666 image" is now "stay on the oneAPI
  toolchain", which is a much weaker constraint: any branch can be built at
  full speed inside that image.
- Today's session runs ~5% hotter than v2's (7.00 vs 6.65 decode on the same
  binary and model), inside this box's documented run-to-run spread (v2 §10) —
  cross-session comparisons must stay same-session.

## 2. MTP / NextN speculative decoding: it works on CPU, and it is worth +38–56%

v2 §12 called MTP the largest remaining lever and noted it was unimplemented.
It is implemented now, in two stacked draft PRs, and it works here:

- [#27836](https://github.com/ggml-org/llama.cpp/pull/27836) adds the NextN/MTP
  draft head and `--spec-type draft-mtp` (draft, base `master`).
- [#28097](https://github.com/ggml-org/llama.cpp/pull/28097) adds draft-head-only
  GGUF support and fixes a regression where `-md` loaded the *target* path again
  (i.e. a second 93 GiB model). Its branch contains #27836's commits, so it is
  the only one to build.

Draft head: `dzannotti/Qwen3.8-Flash-Next-MTP-Q4_K_M.gguf` (2.44 GiB, 34 tensors,
`n_layer_nextn = 1`, block 48). It pairs with the unmodified D4X target — no
requantization or re-export needed.

### One patch was required

`#28097`'s fallback chain did not cover this file's layout and the server aborted
at load:

```
src/models/qwen4exp.cpp:497: GGML_ASSERT(head_norm && head_down && head_up
  && "MTP block missing head mixer tensors") failed
```

The pack ships the head mixer under the **trunk** names `output_hc_{norm,down,up}`
(→ `model.hc_head_*`) rather than per-block `blk.48.nextn.hc_head_*` or
`nextn.shared_head_norm`. #28097's fallback only knows the latter two and then
drops to `layer.hc_ffn_{down,up}`, which are the MTP block's *internal* FFN
hyper-connection projections, not its output mixer. Adding `model.hc_head_*` to
the chain fixes it — 8 lines, kept in
`plans/llm/bench/qwen4exp-mtp-trunk-mixer-fallback.patch`. Worth sending upstream
to #28097; it is exactly the class of layout mismatch that PR exists to absorb.

`LLAMA_ATTN_ROT_DISABLE=1` is set per the draft pack's instructions.

### Numbers

Same binary, same target, `-t 8 -tb 12 -np 1`, two passes of a 256-token code
completion and a 256-token prose completion, `cache_prompt: false`:

| config | code t/s | prose t/s | draft acceptance | mean draft len |
| --- | ---: | ---: | ---: | ---: |
| no speculation | 6.82 / 6.88 | 6.84 / 6.90 | — | — |
| `n-max 2, p-min 0.75` | 9.29 / 9.59 | 9.29 / 8.67 | 0.88–0.94 | 2.44–2.62 |
| **`n-max 3, p-min 0.75`** | **9.54 / 9.59** | **9.24 / 9.28** | 0.86–0.88 | 2.90–2.95 |
| `n-max 4, p-min 0.75` | 9.68 / 9.40 | 9.23 / 9.16 | 0.78–0.85 | 2.96–3.28 |
| `n-max 3, p-min 0.00` | 8.32 / 8.34 | 9.25 / 9.27 | 0.60–0.69 | 2.79–3.07 |

- **`n-max 3, p-min 0.75` is the pick: +39% on code, +35% on prose.** Depth 2 and
  4 are within noise of it; the curve is flat between 2 and 4.
- **The confidence gate is the load-bearing knob, not the depth.** Dropping
  `p-min` to 0 collapses acceptance from 0.86 to 0.60 on code and costs 13%
  (9.54 → 8.33) — the drafts still get generated, they just get thrown away, and
  on a bandwidth-bound CPU every rejected token is a wasted verify slot. This
  reproduces the draft pack's own "p-min matters more than depth" note.
- Acceptance here (0.86–0.88 at depth 3) matches #27836's M3 Max measurement
  (85.7%), so the head generalises across quantizations and machines.

Why it works when v1 thought it would not: v2 §14 already retracted v1's "batching
buys nothing" finding. MTP is batching in disguise — the dense tensors, still
~55% of per-token traffic after D4X, are read once per *verify batch* rather than
once per token. The same amortisation that made `-np 4` worth +73% makes a
2.9-token draft worth +37%.

### MTP compounds with the oneAPI toolchain

Rebuilding the same patched branch with `icx` and re-running the winning config
gives the session's best numbers:

| build | code t/s | prose t/s | acceptance | mean draft len |
| --- | ---: | ---: | ---: | ---: |
| GCC, `n-max 3 p-min 0.75` | 9.54 / 9.59 | 9.24 / 9.28 | 0.86–0.88 | 2.90–2.95 |
| **oneAPI, `n-max 3 p-min 0.75`** | **10.64 / 10.75** | **9.45 / 9.48** | 0.891 | 2.82–3.20 |

The compiler is worth +12% on code with MTP but ~0% without it (6.88 vs 6.90 on
`llama-bench`). That is the expected shape: a verify step over a ~3-token draft is
a small prefill, and prefill is exactly where the oneAPI build wins. **Speculation
moves decode toward the compute-bound regime, so the toolchain choice starts to
matter for decode too.**

Against the same binary's non-speculative decode (6.88 t/s), the best config is
**+56% on code and +38% on prose**.

### Output equivalence: close, but not byte-identical on CPU

#27836 reports temp-0 byte-identical output with MTP on and off (M3 Max/Metal).
On this box it is not, and the reason looks benign. Two greedy smoke prompts
(`temperature 0`, `top_k 1`, fixed seed, same binary):

| prompt | common prefix | divergence |
| --- | ---: | --- |
| 17-sheep trap | 28 chars | `The classic riddle:` vs `The classic riddle.` |
| crontab semantics | 165 chars | `…(Monday through Friday).**` vs `…(Monday through Friday)**.` |

Both are single-token argmax flips at a near-tie, and both answers stay correct
(9 sheep; every 15 min, 09:00–17:59, Mon–Fri). Verifying a batch of 3 drafted
tokens runs different GEMM shapes than a batch of 1 — on ggml's CPU path that is
a different kernel (`gemv_*_8x8` vs the batched path) — so tiny FP differences
can flip a coin-flip token. Worth knowing before anyone tries to use MTP on/off
as a regression oracle; it is not evidence of a broken draft head (acceptance is
0.89).

## 3. vLLM: not runnable on iggy, and not for a fixable reason

vLLM's Qwen3.8-Flash-Next support merged today
([vllm-project/vllm#53896](https://github.com/vllm-project/vllm/pull/53896),
merged 2026-08-31T05:57Z). It is GPU-only by construction, and the model is too
large for iggy's GPUs even in int4. Both halves are hard blocks.

**There is no CPU implementation.** The entire model lives under
`vllm/models/qwen4_exp/{nvidia,amd}/` — there is no `cpu/` tree — and the
package dispatcher says so explicitly:

```python
# vllm/models/qwen4_exp/__init__.py
if current_platform.is_xpu() or current_platform.is_tpu():
    raise NotImplementedError("Qwen4Exp currently supports CUDA and ROCm only")
if current_platform.is_rocm():
    from .amd.model import ...
else:
    from .nvidia.model import ...
```

The CPU platform falls into the `else` branch and imports the CUDA path. The PR
also adds `csrc/libtorch_stable/gdn/fused_gdn_decode_kernel.cu` and wires the
model into `vllm/v1/worker/gpu/*` (`model_runner`, `model_states/mamba_hybrid`,
`warmup`). Gated DeltaNet and the QSA indexer have no CPU kernels. So the
requested setup — weights, activations and KV in host RAM, PLE on NVMe — is not
expressible in vLLM at any version, nightly included.

**The GPU fallback does not fit either.** Checkpoint sizes measured from the HF
API (safetensors bytes only):

| checkpoint | size |
| --- | ---: |
| `Qwen/Qwen3.8-Flash-Next-FP8` | 172.8 GiB |
| `aixiaoma/Qwen3.8-Flash-Next-W4A16` (int4, "ampere/rtx-3090") | 167.5 GiB |
| `Intel/Qwen3.8-Flash-Next-W4A16-AutoRound` | 168.8 GiB |
| `cyankiwi/Qwen3.8-Flash-Next-AWQ-INT4` | 175.4 GiB |

The int4 build is the interesting one — it exists specifically for pre-Blackwell
consumer cards — and its own model card puts **~66 GB of GPU-resident weights**
after `VLLM_PLE_CPU_OFFLOAD=1` moves the 51B n-gram table to host RAM (it asks
for ≥110 GB free host RAM to hold it). iggy has **48 GiB of VRAM** across two
RTX 3090s, both currently ~22.5/24 GiB occupied by the `qwen-3-8-fp8` lane. The
card's stated target is 4×–8× RTX 3090; vLLM's own recipe asks for GB300 TP2
minimum or 8×H200. Two 3090s are 18 GB short before any KV cache, and the host
RAM budget for the PLE table would collide with the ~68 GiB llama.cpp floor.

Recorded so it is not re-litigated: the vLLM arm on iggy is dead on both the CPU
path (no implementation) and the GPU path (66 GB weights vs 48 GiB VRAM). It
reopens only if someone ships a CPU backend for qwen4_exp, or if iggy gains
≥96 GB of VRAM.

## 4. MTP and batching do not compose — they compete

This is the result that changes how the lane should be run. Same oneAPI binary,
4 fixed prompts, 192 tokens each with `ignore_eos`, `-t 8 -tb 12`, aggregate
measured as total tokens / wall clock:

| slots | no speculation | MTP `n3 p0.75` |
| --- | ---: | ---: |
| `-np 1` | 6.70 (6.84/stream) | **10.47** (10.90/stream) |
| `-np 2` | 8.51 (4.37/stream) | 9.00 (4.63–5.50/stream) |
| `-np 4` | **10.52** (2.70/stream) | 9.21 (2.36–3.09/stream) |

Two things fall out:

- **A single MTP stream matches four non-speculative streams** — 10.47 vs 10.52
  aggregate — while running **4× faster per stream** (10.90 vs 2.70 t/s). For a
  coordinator that dispatches one job at a time and waits, that is a strictly
  better machine.
- **Stacking them makes things worse**: MTP at `-np 4` is 12% *slower* than no
  speculation at `-np 4`. Acceptance is not the problem (0.82–0.94 across the
  four slots, mean draft length 2.7–3.4) — the verify batches and the other
  slots are bidding for the same bandwidth, and v2 §14's amortisation has
  already been collected by the batch. Speculation and batching are two ways of
  spending the same headroom, not two independent gains.

The crossover sits between 2 and 4 slots: MTP is still slightly ahead at `-np 2`
(9.00 vs 8.51, and 4.6–5.5 t/s per stream vs 4.37) and behind at 4.

v2 §11 recommends `-np 4` as free throughput. That recommendation is now
conditional: `-np 4` without MTP if the lane really serves four concurrent
agents, `-np 1`–`2` with MTP if it serves one or two at a time. Given how this
lane is actually used — a coordinator dispatching a job and waiting on it —
`-np 1` with MTP is the right default, and it costs nothing in aggregate.

**Memory with the draft head.** Peak measured during the MTP `-np 2` run at
`-c 32768`: `RssAnon` 68.9 GiB, `RssFile` ~20 GiB, `VmHWM` 89.5 GiB. The
anonymous floor rises from v2's 66.3 GiB by ~2.6 GiB — the repacked draft head.
v2 §8's sizing therefore shifts up one notch: **76 Gi request / 84 Gi limit**
(the file-backed half is reclaimable; the anon half is not, and 62 GiB OOM-killed
the container in v2).

## 5. Recommended lane

Build inside the pinned image (it already carries oneAPI 2025.3), so the
toolchain that wins prefill and the branch that carries MTP come together:

```
# base: ghcr.io/ggml-org/llama.cpp:server-intel-b10666
#       @sha256:394b0fd7a15f527480c6c9e6ed0a75d5bc5861cfc89b4b8cc6628cd14fc52d3f
#       (still the newest published server-intel tag as of 2026-08-31)
# preamble: mv /app/libggml-sycl.so{,.disabled}
#
# branch: TheArchitectit/llama.cpp qwen4exp-draft-head-fix   (= PR #28097, contains #27836)
#       + plans/llm/bench/qwen4exp-mtp-trunk-mixer-fallback.patch
# cmake:  -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx
#         -DGGML_NATIVE=ON -DGGML_OPENMP=ON -DLLAMA_CURL=OFF
```

```yaml
env:
  - {name: OMP_PROC_BIND,          value: spread}
  - {name: OMP_PLACES,             value: cores}
  - {name: LLAMA_ATTN_ROT_DISABLE, value: "1"}   # required by the draft head
args: [-m,  /models/Qwen3.8-Flash-Next-D4X-IQ4.gguf,
       -md, /models/Qwen3.8-Flash-Next-MTP-Q4_K_M.gguf,
       --spec-type, draft-mtp,
       --spec-draft-n-max, "3",
       --spec-draft-p-min, "0.75",   # the load-bearing knob, not n-max
       -td, "8",
       -t,  "8",      # decode saturates at 6-8 cores
       -tb, "12",     # prefill peaks at 12
       -c,  "8192",
       -np, "1"]      # NOT 4 - see S4; MTP and batching compete
resources:
  requests: {cpu: "8", memory: 76Gi}
  limits:   {memory: 84Gi}          # never near node total - v2 S7
```

Expected: **10.5–10.9 t/s decode** on code, **9.5 t/s** on prose, **41 t/s**
prefill at `-tb 12` (53 t/s on a 2048-token prompt), cold start ~105 s.

Artifacts on iggy's second NVMe (`/dev/nvme1n1p1`, XFS, 282 GB free):

| path | what |
| --- | --- |
| `/var/mnt/local-hostpath/d4-work/d4s/Qwen3.8-Flash-Next-D4X-IQ4.gguf` | target, 93.13 GiB |
| `/var/mnt/local-hostpath/d5-work/mtp/Qwen3.8-Flash-Next-MTP-Q4_K_M.gguf` | draft head, 2.44 GiB |
| `/var/mnt/local-hostpath/d5-work/src/llama.cpp` | clone with the patched `mtpfix` branch |
| `/var/mnt/local-hostpath/d5-work/src/build-icx` | the oneAPI build used for every S4/S5 number |
| `/var/mnt/local-hostpath/d5-work/logs` | every raw bench log from this session |

## 6. What is left on the table

Updating v2 §12, which said "nothing large":

1. **MTP is no longer on this list — it landed and it is worth +38–56%.** What
   remains of it is upstream risk: #27836 and #28097 are both drafts, and the
   layout patch in `bench/` is ours. Re-check on every rebase.
2. **The remaining decode traffic is unchanged**: ~250 MB/token of F32 MoE router
   (`ffn_gate_inp`, which llama.cpp refuses to quantize) and ~226 MB/token of F32
   SSM state. v2 §12 items 2 and 3 stand.
3. **QSA in the draft head.** #27836's MTP block "attends densely" by design
   (`TODO: wire up QSA here for long-context draft fidelity`). Acceptance was
   measured at short context here; expect it to sag at long context until that
   lands. Re-measure acceptance at ~32k held tokens before trusting the +40% in
   a real coordinator workload.
4. **A GPU-hybrid arm was not run and is the largest untested lever.** The
   dense/attention tensors are still ~55% of per-token traffic and run on the
   generic CPU kernels; `--n-cpu-moe` would put them on a 3090 and leave the 512
   experts in RAM. It was out of scope here because both of iggy's 3090s are held
   by the `qwen-3-8-fp8` lane (~22.5/24 GiB each) and because the brief was an
   all-RAM configuration. It needs that lane stopped for the duration.
