# Idle hardware for more local models — options and throughput estimates (2026-09-24)

Brainstorm only; nothing here is deployed. Constraint: both RTX 3090s stay on
the Qwen 3.8 27B lane. The question is what the rest of the hardware can serve,
and how fast.

**Method.** Theoretical decode (TG) = memory bandwidth ÷ bytes read per token.
Theoretical prefill (PP) = compute peak ÷ (2 × active params); attention is
ignored. Each theoretical figure is then derated using our own D4 measurements
where they exist and external benchmarks where they don't. All numbers are
single-stream with no MTP unless marked. The external sources are listed at the
end. The arithmetic is in the session scratchpad (`est.py`), and each input is
listed below.

## 1. Hardware inventory (verified live, 2026-09-24)

| Box | CPU | RAM | Accelerator | Net | Theoretical BW | Measured BW | Currently |
|---|---|---|---|---|---|---|---|
| iggy | Ryzen 9 3900X (Zen 2, 12C, AVX2) | 128 GB DDR4-3200, 2ch | 2× 3090 (off-limits) | 1 GbE | 51.2 GB/s | 45–46 GB/s random-block (`bench/membw.c`, D4 v2) | 27B lane; ~111 GB RAM free |
| kristeva | 2× Xeon E5-2680 v2 (Ivy Bridge, 20C, **AVX only**, no AVX2/FMA) | 128 GB DDR3-1600, 4ch × 2 sockets | Arc A380 6 GB (186 GB/s, no ReBAR) | 1 GbE | 102.4 GB/s total | ~43 GB/s per socket (STREAM, external) | ~60 infra pods, bge-m3, reranker, vision-cpu; ~42 GB used |
| workstation (not in cluster) | Ryzen 9 9900X (Zen 5, 12C, full 512-bit AVX-512, VNNI, BF16) | 64 GB DDR5-6000, 2ch | RTX 5070 Ti 16 GB (896 GB/s, PCIe 5.0 x16) | 2.5 GbE | 96 GB/s | ~78 GB/s (Chips and Cheese, 9950X DDR5-6000) | desktop/gaming; ~36 GB in use. `lscpu` shows **frequency boost disabled** |
| nuc-1/2/3 | Core Ultra 5 125H (4P+8E, AVX2) | 96 GB DDR5-5600 each | Xe-LPG iGPU, 7 Xe-cores, no XMX | 2.5 GbE | 89.6 GB/s | 72.7 GB/s (AIDA64, external) | Ceph core + etcd |

Compute peaks used for PP (INT8 SIMD, which is what llama.cpp's quantized
kernels run on):
- 3900X: ~2.9 TOPS.
- E5-2680 v2 pair: ~2.0 TOPS (128-bit integer SIMD only).
- 9900X: ~12 TOPS (VNNI at ~4 GHz).
- 5070 Ti tensor cores: 351.5 INT8 TOPS dense, 175.8 FP16 (FP16 accumulate), 87.9 BF16 (FP32 accumulate, half rate on GeForce), 703 NVFP4.
- A380: 66 INT8 TOPS (XMX).

## 2. Models (from model cards and configs)

| Model | Total | Active/token | Notes that change the maths |
|---|---|---|---|
| Qwen3.8-Flash-Next | 125B core + 51B n-gram table + 4B MTP | ~6.6B (4.2B dense + 2.36B routed: 10 of 512, 48 layers, 2560×640 experts) | The n-gram table is a single lookup table at layer 2. It streams from NVMe at ~63 KB/token (D4 v2), so it never needs to be resident. The routed experts total 120.8B params. Hybrid GDN/QSA attention. The D4X requant (93 GiB) is **still on iggy's PVC `flashnext-weights`**. |
| DeepSeek V4.1 Flash (2026-09-10) | 552B backbone + 196B Engram + ViT (510 GB on disk) | 16B decode / 8B prefill | Smallest GGUFs are 264–340 GB. **Not in upstream llama.cpp**; runs on ik_llama.cpp (#2455), vLLM, SGLang. |
| DeepSeek V4 Flash-0731 | 284B | 13B (6 of 256 routed + 1 shared, 43 layers) | Experts are native FP4. unsloth UD-IQ2_XXS 90.9 GB, UD-Q2_K_XL 96.8 GB, UD-IQ3_XXS 104.2 GB. MTP + DSpark merged in llama.cpp. |
| Gemma 4 12B "Unified" | 11.95B dense | 11.95B | 256K context, tool calling, image+audio without encoders. |
| Gemma 4 26B-A4B | 25.2B | 3.8B | 128 experts, 8 active + 1 shared. |
| Gemma 4 E4B | 8B with embeddings | ~4.5B effective | Per-layer embeddings can live on the CPU. |
| Qwen3.6-35B-A3B | 35B | 3B | Alternative small MoE with a proven `qwen3_coder` tool parser. |

"Qwen3.8 Flash" without the "Next" is API-only (Qwen Cloud). There is no small
Qwen 3.8 MoE.

## 3. Derating factors (achieved ÷ theoretical)

| Regime | Factor | Basis |
|---|---|---|
| iggy CPU decode, MoE, requantized D4X | **0.54** | Ours: 7.0 t/s against a 13.0 ceiling. The stock UD quant reached 0.66 but read ~2× the bytes. |
| iggy CPU prefill, mainline llama.cpp | **0.24** | Ours: 53 t/s against ~220. |
| Zen 4/5 desktop CPU decode, MoE | 0.55–0.75 | ik_llama.cpp #710, #1456; hybrid-attention MoEs sit at 0.35–0.45 |
| CPU prefill: mainline vs ik_llama.cpp | 0.08–0.12 vs 0.20–0.35 of INT8 peak | ik_llama.cpp is 1.4–3.6× faster on MoE (#357, #531, #666) |
| Hybrid GPU+CPU, CPU-side expert decode | 0.40–0.60 of DRAM BW | moe-autopilot, carteakey, ubergarm |
| Hybrid prefill at ubatch ≥ 2048, PCIe gen5 x16 | 0.15–0.60 of PCIe ceiling (GPU compute binds) | FreeToken paper; ik_llama.cpp #698 and #1699 |
| Old dual Xeon CPU decode | 0.15–0.25 default, 0.30–0.50 tuned | llama.cpp #16000; ik_llama.cpp #201. Ours: kristeva MoE ~15 GB/s effective, while a 9B dense model reaches ~44 GB/s. |
| 5070 Ti llama.cpp decode, dense Q4 | 0.70–0.80 | llama.cpp #15013; Hardware Corner |
| 5070 Ti decode, small MoE | 0.50–0.60 | llama.cpp #15396 |
| 5070 Ti llama.cpp prefill | 0.25–0.32 of INT8 peak | llama.cpp #15013 |
| A380 decode (SYCL/OpenVINO, xe driver) | 0.35–0.50 | llama.cpp #23313 |
| llama.cpp RPC over 1–10 GbE TCP | 0.5–0.75× single-node | Geerling; kjaiswal; llama.cpp #9136 |

## 4. Scenarios

| # | Where | Model / quant | Resident footprint | TG theoretical | **TG realistic** | PP theoretical | **PP realistic** |
|---|---|---|---|---|---|---|---|
| S1 | iggy CPU | Flash-Next D4X (4.5 bpw, on disk already) | ~76 Gi | 13.0 | **6.7–7.0 measured**. MTP: 10.7 short context, 7–9 at agentic depth | ~220 | **42–53 measured**. ik_llama.cpp might reach ~75–150 (untested) |
| S2 | workstation hybrid: 5070 Ti holds dense + ~17% of experts, 9900X RAM holds the rest | Flash-Next with ~IQ3 experts (e.g. UD-IQ3_XXS, 82 GB) | ~40–45 GB RAM + 16 GB VRAM; n-gram table on NVMe | 93 | **25–40** (external: 22–26 t/s on 2× old Xeon + 3090 with the same model) | ~5,300 (PCIe gen5 bound at ub 4096) | **~1,000–2,000** at large prompts |
| S3 | iggy + one 3090 on x4 (breaks the constraint; listed for completeness) | Flash-Next D4X | 76 Gi RAM + 24 GB VRAM | 37 | **15–22** | ~480 (gen4 x4 bound) | **~300–450** |
| S4 | iggy CPU, instead of S1 | DeepSeek V4 Flash-0731 UD-IQ2_XXS | ~91 GB (tight beside the 27B lane) | 8.7 | **4–5**, maybe 5–7 with MTP | ~110 | **~20–28** |
| S5 | iggy + kristeva via RPC over 1 GbE | DeepSeek V4.1 Flash Q2 (~150 GiB backbone; Engram on NVMe) | Needs both boxes' RAM | ~11 | **~1–3** | kristeva-bound | **~10–20** |
| S6a | 5070 Ti alone | Gemma 4 12B, 4-bit | ~7 GB + KV | 133 | **~90–105** (external: 89 measured) | ~14,700 | **~3,500–4,500** |
| S6b | 5070 Ti alone | Gemma 4 26B-A4B, IQ3/IQ4_XS so it fits beside KV | ~11–13 GB | 419 | **~150–200** (external: gpt-oss-20b 156–190) | ~46,000 | **~4,000–6,000** |
| S6 aggregate | 5070 Ti, vLLM NVFP4, c=32 | an 8–12B model | — | — | **~1,000–2,000 t/s total** (external: Qwen3-8B NVFP4 ~2,000 at c=32) | — | — |
| S7 | kristeva CPU | Gemma 4 26B-A4B, Q4 | ~15 GB | 48 | **~7–14** | ~260 | **~30–35** |
| S8 | kristeva A380, beside the embedder and reranker | Gemma 4 E4B, Q4 | ~3–4 GB VRAM | 73 | **~25–35** | ~7,300 | **~500–900** |
| S9 | one NUC CPU | Flash-Next | ~76 Gi on a 96 GB Ceph node | 22.7 | ~4–6 (compute-bound on 4P+8E) | — | ~30 |

### Reading the table

- **Prefill is the real constraint for agentic work, not decode.** Tim's first
  real flashnext turn was a ~9k-token prompt. At S1's 42–53 t/s that is about
  3 minutes before the first token; at S2's ~1,500 t/s it is about 6 seconds.
  S2 is the single largest improvement available on hardware already owned.
  Its cost is that it needs ~45 GB of the workstation's 64 GB, so it only runs
  when the workstation is in "server mode", not beside a desktop session.
- **DeepSeek V4.1 Flash is out of reach.** Its backbone alone is larger than
  the RAM in any one box. Splitting it over 1 GbE between iggy and the AVX-only
  Xeons gives about 1–3 t/s, and upstream llama.cpp does not support it yet.
  The reachable DeepSeek is **V4 Flash-0731 at 2-bit on iggy (S4)**: about
  4–5 t/s with ~25 t/s prefill, so batch or review only. It also displaces
  Flash-Next from iggy, since iggy's RAM holds one large model.
- **kristeva is a batch-only box.** Without AVX2, MoE decode is compute-bound
  (~15 GB/s effective), and prefill is 20–35 t/s. Short-prompt background work
  suits it; interactive agent turns do not. D2 (0.6 t/s) and D4 (4.6 t/s) both
  measured this.
- **The NUCs are not worth it.** They have more bandwidth than iggy, but the
  CPU is weak, and an ~76 Gi resident model on a Ceph and etcd node puts the
  storage layer at risk from the OOM controller. Leave them alone.
- **Small models belong on the 5070 Ti.** Gemma 4 12B or 26B-A4B gives ~100–200
  t/s single-stream and 1–2k t/s aggregate under concurrency. That is roughly
  10–20× what any CPU lane in the house can do for scout, research and review
  work.

## 5. Two layouts

**Layout A: robust, mostly already built.**
- iggy CPU runs Flash-Next again (S1).
- The 5070 Ti runs the small-model lane (S6) when not gaming.
- kristeva runs Gemma 4 26B-A4B (S7) as the always-on slow fallback for that
  alias. The A380 optionally runs E4B (S8).
- When the workstation preempts, only the small lane degrades, to the kristeva
  fallback. The big model is unaffected.

**Layout B: maximum capability.**
- The workstation runs Flash-Next hybrid (S2).
- iggy CPU runs DeepSeek V4 Flash-0731 IQ2 (S4).
- kristeva runs the small-model fallback (S7).
- Gaming takes the fast Flash-Next away entirely, and nothing can stand in
  for it, because iggy's RAM is then holding DeepSeek.

**Suggested order:**
1. Restore S1 using the retained PVC and the manifests from `9e29c102`. The
   lane was retired for a stuck 76 Gi surge rollout (v4 R3), not for its
   throughput. Give it a `Recreate` rollout this time.
2. Try ik_llama.cpp's CPU prefill on it; that is the cheapest untested lever.
3. Before building any preemption machinery, benchmark S2 as a plain local
   `llama-server` on the workstation. That one measurement decides between A
   and B. Turn frequency boost back on first.
4. Stand up the 5070 Ti small lane.

Any lane still spans all three deployment layers: GitOps manifests, the
LiteLLM catalogue, and the pi.dev configuration.

## 6. Preemptible workstation: what exists

- **Wolf (Games on Whales)** shares one GPU without partitioning. Its k8s
  orchestrator, **Fenrir**, describes itself as "NOT IN A USEABLE STATE".
- No project cordons or taints a node from a game-launch hook, so that part
  has to be built. The closest prior art is `ollama-yield`: it polls `/proc`
  for Steam, Proton or Wine every 3 s, then stops the server.
- A clean yield means killing the process. Sleep-style unloads (llama.cpp
  sleep, vLLM sleep mode) keep 0.3–0.6 GB of VRAM and the CUDA context.
- Expected time from game launch to free VRAM is about 3–10 s; a graceful
  drain is 30 s or more.
- Cold reload of a 10–20 GB GGUF from local NVMe takes about 3–7 s with direct
  I/O or `--no-mmap`, and 15–40 s with cold mmap.
- S2 is much heavier to preempt than S6, because it holds ~45 GB of host RAM
  as well as the GPU.

## Sources

Our own measurements:
- `bench-notes.md` @ `faccf736`: D2, D4 v1–v3, and the flashnext deployment entries.
- `qwen-p2p-benchmark-2026-09-23.md`.

External:
- llama.cpp discussions #15013, #15396, #23313, #9136; PRs #16000, #18012, #24162, #25784, #27742.
- ik_llama.cpp PRs #520, #531, #534, #698, #710, #1456, #2396, #2455; discussions #201, #357, #666, #758; issue #1699.
- FreeToken (arXiv 2608.16157); arXiv 2601.09527 (vLLM on Blackwell GeForce).
- Hardware Corner 5070 Ti / 3090 tables; github.com/JigSawPT/moe-autopilot; carteakey.dev gpt-oss-120b post; ubergarm HF cards.
- Jeff Geerling (Framework cluster, Mac RDMA); kjaiswal/llama-cpp-distributed-benchmarks.
- NVIDIA RTX Blackwell whitepaper v1.1 and GA102 whitepaper; Chips and Cheese (Zen 5 memory, AVX-512); Intel ARK.
- Model cards: `deepseek-ai/DeepSeek-V4.1-Flash`, `deepseek-ai/DeepSeek-V4-Flash-0731`, `Qwen/Qwen3.8-Flash-Next`, `google/gemma-4-12B-it`, `unsloth/*-GGUF` file trees.
- github.com/games-on-whales/{wolf,fenrir}; github.com/preston-bernstein/ollama-yield.
