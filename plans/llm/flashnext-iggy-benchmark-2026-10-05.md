# Flash Next on Iggy benchmark October 5 2026

Flash Next now serves through `flashnext-iggy` across Iggy's two Radeon AI PRO R9700s, using standalone Radiance with exact TP2 and NVMe-backed n-grams. It is the fastest tested option. The exact Amnesia Atomic quant remains available for a matching comparison, and the higher-precision Unsloth Q6 profile completes one and two active requests. Q6 fills both cards but needs CPU expert processing, which makes long-prefill latency substantially higher.

## Hardware and matching baseline

Iggy has a Ryzen 9 3900X, 128 GiB installed RAM, two 32 GB R9700s, and retained local NVMe model storage. It runs Talos 1.13.5 with kernel 6.18.36. PCIe inspection through the complete bridge paths finds one card behind PCIe 4.0 x16 and the other behind PCIe 4.0 x4. The cards' own downstream links report PCIe 5.0 x16; those do not describe the upstream bottleneck.

The baseline is `AtomicChat/Qwen3.8-Flash-Next-GGUF` revision `c30e114991c14ee0e5ed484ccfe0ded939ea5e81`, `AD-4.27bpw-Q4_K_M-M64`. All 33 shards copied from Amnesia match the pinned upstream SHA-256 checksums, retained in [the checksum artifact](artifacts/2026-10-05-flashnext-iggy/atomic-q4-checksums.json). The n-gram table remains mmap-backed on CPU; conventional weights use both GPUs. The previous non-downloadable D4X quant remains on its retained volume.

Both baselines use llama.cpp build b10991, 262,144 context, one slot, q8_0 K/V, batch 1024, microbatch 768, 12 decode and 12 prefill threads, 3 GiB host prompt cache, no context checkpoints, and no speculative decoding. Iggy uses the digest-pinned ROCm image; Amnesia uses the existing digest-pinned CUDA image. Amnesia keeps 45 expert layers on CPU to fit its 16 GB RTX 5070 Ti; Iggy fully offloads conventional weights with a 1:1 layer split. These are matching weights and request inputs with placement appropriate to each machine.

Iggy's service is `flashnext-iggy.llm.svc.cluster.local:8080`. `qwen3-8-27b` is suspended while Flash Next owns both physical GPUs. Amnesia's existing `flashnext` configuration is preserved. At final verification it is queued because the active Steam session holds both advertised time-sliced GPU allocations; its earlier matching benchmarks completed while the GPU was available. LiteLLM exposes `flashnext` for Amnesia and `flashnext-iggy` for Iggy; Hermes and Open WebUI key scopes include both, verified through `/v1/models`.

## Completed throughput measurements

The [existing harness](../../scripts/llm/qwen_p2p_bench.py) sends a greedy streamed request with 256 output tokens. Prompt hashes and token counts match across machines. The C1 short and 40k requests report zero cached prompt tokens. TTFT is client-observed; decode rate divides output tokens by elapsed time after the first token. These are single samples on repetitive technical prose, rather than latency percentiles or a quality evaluation. The model transfers were paused for Iggy's short and 40k comparison cells.

| Runtime and placement | Input tokens | TTFT seconds | Decode tokens per second |
| --- | ---: | ---: | ---: |
| Amnesia CUDA with 45 CPU expert layers | 1,512 | 7.12 | 32.69 |
| Iggy stock ROCm across both R9700s | 1,512 | 3.15 | 29.05 |
| Amnesia CUDA with 45 CPU expert layers | 40,712 | 134.80 | 27.21 |
| Iggy stock ROCm across both R9700s | 40,712 | 46.28 | 21.49 |
| Iggy gfx1201 fork, no draft | 1,512 | 4.48 | 37.58 |
| Iggy gfx1201 fork, no draft | 40,712 | 57.32 | 28.40 |
| Iggy gfx1201 fork, MTP, final four CPU expert layers | 1,512 | 6.31 | 41.42 |
| Iggy gfx1201 fork, MTP, final four CPU expert layers | 40,712 | 93.21 | 38.21 |
| Iggy Q6, one active request in the two-slot profile | 1,512 | 15.64 | 16.76 |
| Iggy Q6, one active request in the two-slot profile | 40,712 | 435.17 | 14.61 |
| Iggy standalone Radiance, exact TP2, IQ4R with protected BF16 experts | 1,512 | 1.00 | 78.89 |
| Iggy standalone Radiance, exact TP2, IQ4R with protected BF16 experts | 40,712 | 20.49 | 88.42 |

Raw artifacts are in [the run directory](artifacts/2026-10-05-flashnext-iggy). The earlier [Amnesia report](flashnext-amnesia-benchmark-2026-09-28.md) measured 34.8 short-prompt and 28.4 40k-prompt tokens/s after tuning. The fresh observations above are retained alongside those historical observations. A workstation short probe taken during the weight transfer is explicitly excluded from comparison in its artifact.

Both machines completed replacement near-window requests with 257,712 input and 64 output tokens without truncation or a pod restart. Iggy decoded at 8.25 tokens/s and Amnesia at 12.51 tokens/s. The preceding interrupted requests left cached prefixes (234,496 tokens on Iggy and 140,288 on Amnesia), so their replacement TTFT values are excluded from cold-prefill comparison. These runs establish context capacity while model staging continued in the background.

## llama.cpp optimizations

The [R9700 llama.cpp fork](https://github.com/JohnTDI-cpu/llama.cpp-flash-next-rdna4) was built from revision `185252d1edb27fde6b332908eb7c89a20cadc4bb` against the existing Radiance 0.9.3 image's ROCm 7.14 userspace and Clang 23, targeting gfx1201. HIP graphs and flash attention are compiled in. The measured profiles enable hyper-connection fusions, a MoE MMQ tile cap of 32, active OpenMP waiting, HIP graphs, and flash attention. MTP is measured separately. The exact Q4 model loads across both R9700s. Normal reasoning computes the arithmetic probe correctly, and tool calling succeeds. A no-thinking arithmetic error is reproduced by stock Amnesia. The fork initially ignored empty-schema JSON-object mode; a minimal Qwen-parser repair restores valid JSON and is included in the reproducible build. Explicit JSON schema works before and after that repair. The [build script](../../services/flashnext-iggy-llama/build.sh) verifies the pinned source archive, and [build provenance](artifacts/2026-10-05-flashnext-iggy/optimized-build.json) records binary checksums. MTP uses the checksum-verified shared Q8_0 head from the pinned Unsloth revision. It needs headroom on GPU 1, which holds the target output tensor: offloading final expert layers 44–47 provides it. Restricting the draft to GPU 0 fails because its shared output tensor remains on GPU 1. Measured draft acceptance is 52.4% on the short prompt and 60.1% at 40k. No upstream speedup is presented as an Iggy result.

Two active Q4 slots at 131,072 tokens each complete the short cell at 32.16 tokens/s per request. The recorded two-slot 40k cell overlapped a compatibility request near its end and is excluded from throughput comparisons. This tests two actual slots rather than two queued clients against a one-slot server.

## Higher precision and Radiance

The higher-precision quant is Unsloth `UD-Q6_K_XL`, pinned at revision `38bb39ee97821de2c9009abb7e93950eec396e66`. Its six shards total approximately 157.5 GiB, so CPU expert placement is necessary with 64 GB aggregate VRAM. All six shards pass whole-file upstream SHA-256 verification following resumable HTTPS range downloads to the model archive. Shard 3 contains the 50.66 GiB Q8_0 n-gram table. The verified local copy is on `/dev/nvme1n1p4`, through the persistent kubelet bind mount `/var/lib/kubelet/flashnext-iggy-ngram`; the retained local PV uses that directory. The model directory links this shard to `/ngram/q6` and the conventional shards to the archive. A read-back checksum of the local table also matches upstream. The first conventional-weight load is limited by the archive link; the CPU working set is warmed before throughput measurements. The Q6 profile uses `--load-mode none` for conventional tensors: the fork independently maps its lazy n-gram context, so this keeps the 53.2 GiB CPU expert buffer resident without eagerly prefaulting all archived shards. Startup reports a separate 51,880 MiB `CPU_Mapped` n-gram buffer, and [the placement artifact](artifacts/2026-10-05-flashnext-iggy/iggy-q6-nvme-placement.json) confirms the NVMe mapping has zero locked pages. The CPU/GPU weights and cache are budgeted within a 100 GiB host-memory limit.

The two-slot profile allocates 131,072 tokens per slot. Its placement starts with 26 CPU expert layers and overrides selected matrices in layers 24 and 25 onto GPU 0 and GPU 1. This keeps the original 768-token microbatch while balancing both cards. The pinned engine's metadata-only [memory probe](../../services/flashnext-iggy-llama/memory-probe.cpp) budgets context and compute reservations. Actual use after the complete test suite is 31.62 GiB on GPU 0 and 31.57 GiB on GPU 1, versus 25.70 and 29.80 GiB with the initial conservative placement. Conventional GPU weights increase from 46.7 to 53.7 GiB, and CPU conventional weights decrease from 60.1 to 53.2 GiB. The [memory plans](artifacts/2026-10-05-flashnext-iggy/q6-memory-partial-plan.json) record the tested overrides.

One active request in this profile decodes at 16.76 tokens/s on the short input and 14.61 tokens/s at 40k. Two active short requests decode at 8.13 and 11.74 tokens/s and finish in 56.32 and 56.38 seconds. All report zero cached tokens and match the baseline prompt hashes. CPU expert processing limits prefill: the single 40k request takes 435.17 seconds to its first token. Two uncached 40k requests also complete: TTFT is 442.13 and 879.71 seconds, with total latency 902.89 and 905.68 seconds. Prefilling the second request holds up the first stream, whose observed decode rate falls to 0.56 tokens/s; the second decodes at 9.86 tokens/s. Both return all 256 output tokens without truncation or restart. Reasoning, JSON-object mode and automatic tool calling pass; both arithmetic probes return 410. Higher nominal weight precision is not itself a measured quality score.

The [standalone Radiance engine](https://codeberg.org/StillDeadcode/radiance), version 1.0.12, serves the publisher's [Flash Next container](https://huggingface.co/StillDeadcode/qwen3.8-next-flash-fp8-iq4r-moe), model revision `8267a67384583f6be309981baf878b09ff900a9a`. The digest-pinned runtime uses exact TP2 communication, three speculative tokens, FP8 KV, a 12 GiB pinned expert pool per GPU, and disk n-grams. Its routed expert quant is IQ4R with ten protected BF16 experts, an int8 trunk and FP8 n-grams. This differs from the matching Atomic quant, so its throughput is a runtime and quant comparison; these probes do not establish relative model quality. No lossy TP wire was used. The full 113.59 GiB model container matches upstream SHA-256 on local NVMe, with a retained archive copy.

Both GPUs report direct peer access. Each holds approximately 31.3 GiB at startup; the expert host pool totals 24 GiB, and the 47.68 GiB n-gram table remains disk backed. Native startup and health pass on the existing Talos driver. Talos and its extensions required no upgrade.

Radiance completed two active short requests at 87.56 and 104.30 tokens/s. With two uncached 40,712-token requests, first-token latencies were 19.73 and 40.77 seconds and total latencies were 43.59 and 44.00 seconds. The first stream's 10.73 tokens/s includes a pause while the second prompt prefills; the second stream decoded at 79.38 tokens/s. Reporting their average decode rate would obscure this scheduling effect. The two-sequence profile has a 262,144-token request bound; two full-window requests have not been demonstrated.

Reasoning, JSON-object output, strict JSON-schema output, and automatic tool calling pass. JSON modes and automatic tools also pass through the production LiteLLM alias using the Hermes key. Radiance explicitly rejects `tool_choice: required` with HTTP 400; its supported modes are `auto` and `none`. This limitation matters to clients that require a forced call. The recorded benchmarks disable prefix caching and verbose live metrics are retained only in the private benchmark configuration. The production profile enables prefix reuse and removes live console rendering.

## Selecting a profile

The [selector](../../scripts/llm/select_flashnext_iggy.py) updates the active repository configuration and LiteLLM context bound. It supports `q4-stock`, `q4`, `q4-c2`, `q4-mtp`, `q6`, `q6-c2`, and `radiance`. These presets use the same Iggy endpoint and both GPUs, with one runtime active at a time. For example:

```sh
python scripts/llm/select_flashnext_iggy.py q6-c2
```

Validate and publish through the repository's [jj workflow](../../.claude/skills/jj-workflow/SKILL.md), then reconcile `llmkube-resources` and `litellm` in namespace `llm`. The matching Q4 C1 presets expose 262,144 context; C2 exposes 131,072 per slot. Q6 measurements use the two-slot preset with either one or two active requests. Its one-slot 262,144 preset is provided separately; a full-window Q6 request has not been measured. Radiance exposes a 262,144 request bound with two active sequences sharing its KV pool.

## Deployment validation

The pinned flux-local 8.4.0 check passes all 175 selected checks, with the two repository-configured deselections. The managed Radiance service is Ready with both R9700s, and production alias checks pass for structured JSON and automatic tools. Its 80 GiB memory limit passes startup and these API checks. Q6 completes all six measured requests and three compatibility probes with no truncation, restart, OOM or memory-limit event. Its n-gram mapping has zero locked pages and approximately 73 MiB resident after the suite. Both models and the original D4X artifact remain on retained storage.

GitOps ownership remains with `llmkube-resources` and `litellm`; source and applied revisions are checked against the published main revision during reconciliation. Amnesia's existing `flashnext` deployment is queued behind the active Steam session and will resume when its GPU allocations are released; the gaming workload was left in place.

## Runtime upgrade to Radiance 1.2.3 (October 7 2026)

The production runtime moved to `radiance:1.2.3` pinned at digest `sha256:7318df30fc95aab1fe73aa1eb0b04fa1d65aff9a1e717d51c7457be685b08398`, and the profile dropped `--expert-vs-cache-ratio`: version 1.1.0 removed that flag and current startup rejects unknown options, so the split is now elastic — the experts keep what the pinned host pool cannot hold and the KV cache takes the rest, lending idle blocks under demand. Linear-state snapshots moved to pinned host memory (8 slots of 112.73 MiB at TP2, nothing on the card). The published 1.1.0 kernel work covers Flash Next decode and prefill paths, and 1.2.x additions (MXFP4 kernels, DFlash2 rescoring, static YaRN, adaptive draft windows) concern other artifacts or default-off environment knobs; the served IQ4R container at revision `8267a67384583f6be309981baf878b09ff900a9a` is unchanged.

The `tool_choice: required` limitation recorded above no longer applies: since 1.2.1 a reply call grammar serves forced and named-function calls, verified through the production alias after this upgrade (HTTP 200 with a valid `get_weather` call). Post-upgrade startup reports an elastic split of 26.54 GiB, a 3.59 GiB KV carve per card that lends approximately 3.36 GiB to the experts at idle, and both cards at approximately 31.4 of 31.9 GiB with the 512 MiB headroom reservation intact. Warm single-stream decode above 130 tokens/s was observed through the alias but is not a controlled measurement; the tables above remain the recorded baseline. Flux-local 8.4.0 passed 20/20 namespace-scoped checks for this change and `llmkube-resources` applied the published revision.
