# Flash Next public-runtime comparison on Iggy

For the exact workstation Atomic Q4, uncached Stew r15 gives the best measured common-request latency: warmed short generation is 48.67 tokens/s and median 40K generation is 42.51, about 49% and 56% above the earlier workstation baseline. Native 1.0.13 has the highest measured raw generation (160–227 tokens/s) and fast matching chat requests. Strata dual WMMA leads long prefill (2,963 tokens/s at 32K; 3,542 at 64K) and the complete 40K-plus-256 request (18.41 seconds), with FIFO handling of concurrent requests.

Q6 now has qualified C1 and C2 options. The C1 cache preset gives about 22 tokens/s on the short matching prompt and finishes 40K plus 256 output tokens in 100.38 seconds. The conservative C2 split passes the original concurrent pairs and the replay after 64K prefill, but its 40K pair takes 841.65 seconds. Faster cache variants are rejected for concurrent output failures or long-prefill OOM.

All active n-gram tables stay on local NVMe. The same Atomic table is retained for the workstation control; alternative quants have different table precision and conventional weights. This report measures performance and bounded correctness/API checks, not equivalent quality against BF16. The original [Iggy/workstation report](flashnext-iggy-benchmark-2026-10-05.md) remains the historical baseline. [Retained evidence](artifacts/2026-10-05-flashnext-public-comparison/index.json) includes completed trials, failed starts and prepared alternatives; [coverage](artifacts/2026-10-05-flashnext-public-comparison/campaign-coverage.json) distinguishes them.

## Completed comparison at a glance

Rates are tokens/s. Short columns average repetitions two and three; 40K columns use medians of three independent requests. TG uses the earlier workstation definition for direct comparison. PP is the complete corpus sweep. Every matching request in this table reaches 256 output tokens. Native production and publisher layouts are separate. A dash means that layout has no completed measurement for that column. C2 is the time until both 256-token requests finish; FIFO is explicitly queued execution. Q6 rows with failed output qualification are labelled C2 rejected; their timing cells remain measurements rather than recommendations.

<!-- completed-comparison:start -->
| Completed profile | Short TTFT, warmed | Short TG, warmed | 40K TTFT, median | 40K TG, median | 40K request wall, median | 32K PP, mean | 64K PP, mean | C2 40K pair wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Stew r15 plain, Atomic Q4 | 0.81 s | 48.67 | 28.23 s | 42.51 | 34.24 s | 1,351.53 | 1,258.35 | — |
| Stew r15 MTP, Atomic Q4 | 2.36 s | 55.18 | 63.35 s | 46.23 | 68.87 s | 561.58 | 568.96 | — |
| Native 1.0.13, production layout | 0.95 s | 130.01 | 18.30 s | 113.13 | 20.45 s | — | — | 40.44 s |
| Native 1.0.13, publisher layout | 0.91 s | 104.44 | 18.48 s | 104.85 | 20.67 s | 2,193.68 | 2,171.99 | — |
| R9V original IQ4_XS, CED off | 1.22 s | 62.52 | 26.18 s | 66.94 | 30.16 s | 1,437.52 | 1,416.16 | — |
| Shali plain, Atomic Q4, one GPU | 3.67 s | 30.71 | 105.08 s | 27.75 | 114.30 s | 346.06 | 326.88 | 227.40 s |
| Shali MTP, Atomic Q4, one GPU | 4.31 s | 29.75 | 121.85 s | 26.88 | 131.38 s | 298.37 | 286.23 | 266.86 s |
| John plain, original IQ3 | 1.68 s | 42.29 | 66.78 s | 31.71 | 74.86 s | 547.88 | 469.91 | 194.17 s |
| John balanced MTP, original IQ3 | 1.76 s | 62.61 | 70.01 s | 47.29 | 75.42 s | 531.10 | 447.68 | 203.18 s |
| Strata single, adapted IQ4_XS | 1.69 s | 70.27 | 24.20 s | 68.08 | 27.93 s | 1,691.64 | 1,643.16 | 55.99 s (FIFO) |
| Strata dual base, adapted IQ4_XS | 1.48 s | 45.32 | 17.31 s | 43.36 | 23.19 s | 2,188.77 | 2,556.28 | 45.11 s (FIFO) |
| Strata dual WMMA, adapted IQ4_XS | 1.43 s | 47.84 | 12.62 s | 44.31 | 18.41 s | 2,962.69 | 3,542.43 | 35.77 s (FIFO) |
| Davet LRU, Heretic MXFP4/FP8 | 1.94 s | 86.15 | 29.66 s | 71.98 | 33.32 s | 1,034.25 | 1,064.35 | 170.77 s |
| Q6 tensor cache, hybrid (C2 rejected) | 8.79 s | 20.86 | 172.51 s | 22.66 | 183.69 s | — | — | 378.59 s |
| Q6 tensor cache, pure RCCL (C2 rejected) | 8.73 s | 20.50 | 171.82 s | 22.27 | 183.30 s | — | — | 376.70 s |
| Q6 static split, Stew r15 | 15.09 s | 18.66 | 401.05 s | 17.64 | 415.60 s | 74.21 | 71.90 | 841.65 s |
| Q6 layer cache, 4K microbatch retry (C2 rejected) | 7.92 s | 23.05 | 88.24 s | 21.95 | 99.89 s | — | — | 206.87 s |
| Q6 layer cache, 4K, fast card first (C2 rejected) | 5.87 s | 12.30 | 73.52 s | 11.83 | 95.18 s | — | — | 191.37 s |
| Q6 layer cache, 4K, eager host remap (C2 rejected) | 7.91 s | 21.97 | 88.23 s | 20.90 | 100.48 s | — | — | 207.15 s |
| Q6 layer cache, qualified single slot | 7.91 s | 22.00 | 88.15 s | 20.93 | 100.38 s | 364.63 | 354.50 | — |
<!-- completed-comparison:end -->

## Public raw-generation comparison

These are end-to-end output tokens/s, best of three identical greedy raw prompts, including prefill. Every scored group reaches its requested cap in all three trials. A one-token EOS is shown with its counts. The Native row uses the publisher layout; the LRU rows separate the final published norm-2 setting from its completed norm-0 control. Final qualification is stated in each runtime section.

<!-- raw-decode:start -->
| Raw profile | Prose, 256 cap | JSON, 800 cap | Code, 600 cap |
|---|---:|---:|---:|
| Stew plain, Atomic Q4 | EOS; 1,1,1 tokens | 48.58 | 48.48 |
| Stew MTP, Atomic Q4 | EOS; 1,1,1 tokens | 68.14 | 62.60 |
| Native 1.0.13 publisher, exact | 159.66 | 227.16 | 203.73 |
| R9V original IQ4_XS | 55.61 | 59.36 | 72.54 |
| Shali plain, one GPU | EOS; 1,1,1 tokens | 31.53 | 30.43 |
| Shali MTP, one GPU | EOS; 1,1,1 tokens | 38.42 | 33.49 |
| John plain, original IQ3 | EOS; 1,1,1 tokens | 42.91 | 43.04 |
| John balanced MTP, original IQ3 | EOS; 1,1,1 tokens | 82.26 | 71.71 |
| Strata single base | 38.32 | 84.47 | 77.56 |
| Strata dual base | 46.77 | 63.65 | 55.16 |
| Strata dual WMMA | 46.73 | 63.60 | 55.18 |
| Davet LRU, published fused norm 2 | 83.43 | 101.15 | 89.86 |
| Davet LRU, norm 0 control | 81.49 | 101.22 | 84.92 |
| Q6 initial tensor-cache screen | 20.39 | 17.82 | 17.20 |
| Q6 conservative two-slot, full qualification | 18.47 | 18.55 | 18.53 |
| Q6 layer cache, qualified single slot | 19.30 | 17.43 | 17.64 |
<!-- raw-decode:end -->

## Comparable measurements

The [benchmark harness](../../scripts/llm/flashnext_public_bench.py) uses the public LRU project's three greedy raw-completion prompts, with output limits of 256, 800 and 600 tokens. Its published decode rate includes prefill; the artifacts also retain streamed time to first token, decode throughput excluding the first token, and the earlier workstation throughput definition. Early EOS is recorded. A one-token completion is not a usable generation-throughput measurement.

Prefill follows R9V's pinned Aider corpus: one 1K warmup, ten 8K requests with one output token, three 32K requests with sixteen output tokens, and two 64K requests with sixteen output tokens. Prompt size is verified through each runtime's tokenizer. Leading nonces prevent prefix reuse; actual cache usage is retained. PP here means prompt tokens divided by time to first token, including scheduling and the first decode step.

The workstation comparison retains the original prompt texts, verified by SHA-256, with 1,512 and 40,712 input tokens under the original reasoning template and a 256-token output limit. Other templates can produce different token counts; the artifacts retain each runtime's actual counts. Three repetitions expose cold and warmed behavior. C2 sends two independent requests together; its aggregate rate includes the complete duration of both requests. A request stalled behind the other request's prefill is identified separately from device decode speed. Completion counts include reasoning tokens; the 256-token matching cap often ends during reasoning, before a final answer. These are bounded throughput and coherence checks. The separate arithmetic, JSON and tool probes disable thinking and check completed answers.

## Quant and n-gram differences

| Profile | Model representation | NVMe n-gram representation | Table size |
|---|---|---|---:|
| Matching workstation Atomic | Q4_K_M mixture, advertised 4.27 bpw | Q5_1, confirmed from the GGUF tensor header | 35.76 GiB |
| Higher fidelity Unsloth Q6 | UD-Q6_K_XL mixture | Q8_0 | 50.66 GiB |
| John original IQ3 | UD-IQ3_XXS mixture | IQ4_NL | 26.82 GiB |
| R9V original IQ4 | UD-IQ4_XS | IQ4_NL | 26.82 GiB |
| Strata reproduction | R9V IQ4_XS expert bytes, converted dense pack | IQ4_NL | 26.82 GiB |
| Native Radiance | IQ4R routed weights with protected BF16 experts, int8 trunk | FP8 | 47.68 GiB |
| Public LRU | Heretic-decensored MXFP4/FP8 checkpoint | FP8, exact source bytes and BF16 scale | 47.68 GiB |

The Atomic control retains the identical n-gram file used by the workstation. Across different quants, the table representation also changes; all active tables retain the requested NVMe placement. The n-gram tables are accessed selectively rather than copied and pinned in full. A pageable resident row cache is permitted and its measured size is recorded. These are precision and storage differences, not a measured ranking of output quality. Native's protected experts and its custom MTP head are further differences from the GGUF configurations.

Native uses a different calibrated quantization recipe: 4-bit non-uniform expert codes after a 128-point Walsh–Hadamard rotation, with an FP8 scale per 64 weights. Ten individually named experts across layers 34, 44, 46 and 47 remain BF16; this is ten total, not ten per layer. The main linears use int8 W8A8, hyper-connection mixing uses FP8, and the custom draft head uses two-bit codes. Its FP8 n-grams use a fixed BF16 scale. These details come from the [publisher's conversion recipe](https://huggingface.co/StillDeadcode/qwen3.8-next-flash-fp8-iq4r-moe).

The 113.59 GiB container includes the n-gram table, vision tower and draft head. Its size and protected-expert strategy do not establish higher fidelity than Unsloth Q6. This campaign measures speed and bounded correctness/API probes, not a matched quality evaluation against BF16.

## Exact Atomic Q4 against the workstation

| Matching Atomic Q4, Iggy runtime | Short TTFT, see notes | Short generation, see notes | 40K TTFT | 40K generation |
|---|---:|---:|---:|---:|
| Workstation, earlier stock baseline | 7.12 s (first trial) | 32.69 tokens/s | 134.80 s | 27.21 tokens/s |
| Earlier John fork | 4.48 s | 37.58 tokens/s | 57.32 s | 28.40 tokens/s |
| Stew r15, cache disabled | 0.81 s | 48.67 tokens/s | 28.23 s | 42.51 tokens/s |
| Stew r15, tensor cache and copy-engine collective, short screen | 3.74 s | 43.22 tokens/s | Not measured | Not measured |
| Stew r15, tensor cache, exact F32 RCCL | 3.74 s | 43.04 tokens/s (all-trial median) | 75.09 s | 39.94 tokens/s |
| Stew r15, layer cache | 3.81 s | 46.93 tokens/s (warmed mean) | 76.20 s | 41.38 tokens/s |

The Stew control uses the exact 33-shard Atomic quant previously benchmarked on Amnesia, with the original Iggy placement. Model and prompt bytes match the workstation control; hardware and inference builds differ. The first short request has a 4.01-second TTFT; its generation rate is 47.95 tokens/s. Compared with the earlier John fork, warmed generation improves approximately 29% at short context and 50% at 40K. Compared with the workstation stock baseline on the same quant and prompt text, it improves approximately 49% and 56%. The workstation short TTFT is a first-trial value; Stew's first trial is 4.01 seconds, while 0.81 seconds describes its warmed trials. Comparing first short trials gives 47.95 versus 32.69 tokens/s, a 46.7% generation improvement; the 49% figure compares warmed Stew generation with that historical workstation point. Both physical GPUs use over 30 GiB after the suite. The NVMe n-gram mapping has no locked pages.

The cached copy-engine configuration is slower than that control and is not the selected configuration. Its GPU cache has capacity for 93.1% of the host expert bytes in that placement, but capacity is not a measured cache-hit rate. Actual VRAM use is 31.42 and 31.35 GiB. The repaired exact-F32 RCCL tensor cache completes all six matching requests at their 256-token caps, but remains slower than the uncached control at both contexts. The layer-cache control also completes every cap, with median 40K TTFT 76.20 seconds and generation 41.38 tokens/s. Both cache placements introduce substantial prefill latency on this Q4 model, whose conventional weights already fit across both cards.

## Native Radiance gap

The same checksum-verified `.rad` container is used throughout. The publisher's larger concurrency layout reproduces its raw-generation headline range with exact communication: warmed best-of-three rates are approximately 160 tokens/s for prose, 228 for JSON and 204 for code. The original common chat prompt generates at a different rate. Changing prompts and reporting conventions explains the apparent generation gap; those raw rates do not describe the original workstation prompt.

| Native Radiance, publisher layout, NVMe n-grams | 32K PP, mean | 64K PP, mean |
|---|---:|---:|
| 1.0.12, exact TP2 | 1,962.8 tokens/s | 1,946.3 tokens/s |
| 1.0.12, WHT6 TP2 | 2,247.0 tokens/s | 2,207.2 tokens/s |
| 1.0.13, exact TP2 | 2,193.7 tokens/s | 2,172.0 tokens/s |

WHT6 improves the paired 32K PP result by approximately 14.5%, with nearly unchanged raw decode. It changes large-message communication precision and is recorded as a separate approximation. Version 1.0.13 improves exact 32K PP by approximately 11.8% over 1.0.12's publisher layout. Neither closes the published prefill gap. Using the publisher's own corpus also stays around 2.2K tokens/s.

The publisher command leaves n-gram placement on `auto`. [Radiance's placement guide](https://codeberg.org/StillDeadcode/radiance/src/commit/d0f639bd0620e7ba2cb3672af07b252ebca2005f/docs/GUIDE.md) says auto can choose a full RAM copy when it fits. These runs force disk placement, as requested. The resolved publisher placement is not available, so RAM placement is a possible contributor, not an established explanation of the entire gap. Iggy's CPU and PCIe topology also differ. Its measured GPU clocks and temperatures do not indicate a simple thermal limit.

Native's `link.ssd_reads` counter belongs to expert movement, not n-gram reads. A zero value does not establish that its n-gram table stayed out of disk I/O. The disk gather uses bounded row caching and direct I/O rather than pinning the complete table.

One initial publisher-layout run was preempted when parent reconciliation restored the managed GPU service. That failed long request is retained and excluded. Reconciliation holds were corrected, and the exact profile was rerun in full.

The 1.0.13 production-like TP2 layout also completes all six matching requests and both concurrent pairs at their 256-token caps. Its first short result is 78.84 tokens/s, effectively matching the earlier 1.0.12 first-trial result of 79.00. Repeated independent short trials reach 118.23/141.80 tokens/s with zero prefix-cache hits; this warming is not assigned to the version upgrade. The three 40K TTFTs are 20.00/18.30/17.44 seconds, with generation 113.13/118.83/105.88 tokens/s. The short C2 pair finishes within 4.60 seconds; the long pair within 40.44 seconds, with one stream pausing during its peer's prefill. Arithmetic, JSON-object and automatic-tool probes pass.

## R9V, original IQ4_XS and CED off

The asymmetric WMMA profile completes all nine raw trials, the sixteen public PP requests and six matching workstation requests. Median matching-prompt generation is 62.49 tokens/s at short context and 66.94 at 40K, using the original throughput definition. Warmed short TTFT is about 1.22 seconds; median 40K TTFT is 26.18 seconds. The 32K PP mean is 1,437.5 tokens/s and the 64K mean is 1,416.2. The leading nonces prevent prefix reuse.

A separate 131,000-token input completes in 96.37 seconds to first token, about 1,359 prompt tokens/s. It stops after EOS at one output token, so this qualifies full-input processing but does not measure sustained generation at maximum context.

The conservative placement uses 70/427 hot experts, a 160-slot cache on the CPU-connected GPU, and a three-GiB planner reserve per card. Actual VRAM use after the suite is about 28.12/28.02 GiB. Pod memory is about 75.04 GiB; no OOM events occur. The n-gram worker maps the NVMe IQ4_NL table with 83.48 MiB resident, zero anonymous pages and zero locked pages.

## Stew correctness qualification

A [new upstream diagnosis](https://github.com/stew675/llama-cpp-rdna-boosts/blob/493808b9bff4bb41b379f9a073f771902f20b39c/wip/moe-cache-autosize/TENSOR-CORRUPTION.md) identifies silent output corruption when r15 activates its host-to-GPU staging ring. The cache profiles set `GGML_SCHED_STAGE_MIN_TOKENS=999999`, the documented workaround, before measuring wider prefill. Faster corrupted output is excluded. Shali's r30 configuration receives its exact older build, whose source tree matches `0fe48395051775079fb18041142e3f22dbf82a72`; it is recorded separately from the newer r15 chain.

## Higher fidelity Q6 qualification

The Q6 target contains **106.87 GiB of conventional weights** plus its **50.66 GiB Q8_0 n-gram shard**. Both 32 GB cards cannot hold all conventional weights alongside KV, activations and runtime buffers. The earlier static split already placed about 53.71 GiB of weights on GPU and 53.16 GiB on CPU; physical VRAM was near 31.6 GiB per card. The follow-up static and cache screens likewise fill both cards. Low static-buffer log values exclude dynamically allocated expert arenas and are not evidence of idle VRAM.

An expert cache computes hot host-backed experts on GPU while retaining backing copies for misses. Hit rate measures routed accesses, not the fraction of model bytes stored on GPU. The physical-memory table separates anonymous/shared backing from reclaimable file pages. Active n-grams remain pageable NVMe mappings with no full-table pinning.

All six Q6 shards now resolve to whole-file-checksummed local NVMe copies on /dev/nvme1n1p4. The five conventional shards total 114,765,121,376 bytes and pass upstream whole-file checksums plus destination readback. The original n-gram shard remains unchanged: SHA-256 34efd79a80a1ce540a517a5d56171924b66ce1c38b04c904f17ad6d8ef17cf20. [Mapping proof](artifacts/2026-10-05-flashnext-public-comparison/results/q6-local-nvme-mapping-proof.json) and [checksum proof](artifacts/2026-10-05-flashnext-public-comparison/results/q6-nvme-conventional-proof.json) retain resolved paths and whole-file validation.

The tensor-cache screens retain exact F32 collective transport and the [upstream staging workaround](https://github.com/stew675/llama-cpp-rdna-boosts/blob/493808b9bff4bb41b379f9a073f771902f20b39c/wip/moe-cache-autosize/TENSOR-CORRUPTION.md), GGML_SCHED_STAGE_MIN_TOKENS=999999. Hybrid and pure-RCCL C1 outputs match byte for byte, and the matching C1 outputs also match the earlier archive-backed conventional screen after promotion to NVMe. Their replay results still reject C2: a paragraph loop in the hybrid run and premature EOS after 17 reasoning tokens in pure RCCL. Ordinary independent pairs and small API probes passing do not override those failures.

Reducing the layer profile's microbatch from 8192 to 4096 solves its startup OOM: the static-heavy GPU's compute buffer drops from 7330 to 3894 MiB. The resulting 24,234 MiB expert arena retains 29.4% of its 82,562.5 MiB host-backed expert bytes. Warm short generation is 23.05 tokens/s; median 40K TTFT is 88.24 seconds and complete request latency 99.89 seconds. However, all four exact concurrent replay pairs reproduce a loop in one stream. The independent short pair also contains an off-task numeric continuation. Both long independent outputs remain coherent, and the long pair takes 206.87 seconds. This is a measured, rejected C2 configuration.

A device-order control changes only ROCR_VISIBLE_DEVICES=1,0 and HIP_VISIBLE_DEVICES=0,1; a runtime probe confirms the CPU-connected card becomes runtime GPU 0. All six C1 output bytes remain identical to the reviewed default-order outputs. TTFT improves, but warm short generation falls from 23.05 to 12.30 tokens/s and short request latency rises from about 19 to 26.7 seconds. Median 40K request latency improves modestly to 95.18 seconds. The large arena moves to the fast card while the small arena moves to the slow link; greater miss traffic on the small-arena side is a plausible explanation, not measured per-device PCIe traffic. All four exact concurrent pairs produce a malformed record/zero continuation in one stream, and an independent short stream degenerates into blank lines. C2 remains rejected.

The documented eager-host control sets only MOE_EXPERT_CACHE_DEVMAP=0, also gating off device admission policy and in-kernel slot lookup. All six C1 outputs again match the default-order bytes. Warm short generation is 21.97 tokens/s and median 40K wall time is 100.48 seconds. The original concurrent loop persists in three of four exact pairs; the independent short pair contains a different hidden-message loop. Both long outputs and API probes pass. These controls rule out pure RCCL, layer splitting, GPU ordering and eager host remapping as sufficient standalone fixes. The root cause is not established, and differing floating-point text alone is not classified as corruption. [Explicit output decisions](artifacts/2026-10-05-flashnext-public-comparison/provenance/q6-qualification-decisions.json) retain the failing labels, hashes and reviewed coverage.

The all-expert wide profile reaches about 27 tokens/s on warm short requests but fails all three 40K requests while resizing compute buffers. Its 4K-microbatch/2 GiB-reserve retry reaches 31.62 tokens/s on a warm short request but again fails all three long requests, now after the first 8192 input tokens while growing the second GPU's compute buffer by only 88 MiB. The allocator frees the old compute buffer before requesting its replacement. Separate kernel scratch buffers are pooled; their retention is a plausible headroom issue, but the precise allocation/fragmentation breakdown is unmeasured. A final one-slot / 4 GiB-reserve retry also fails all three 40K inputs at the same GPU1 compute resize, despite reaching 27.92 and 28.72 tokens/s on its warmed short requests. All three short outputs are coherent and API probes pass, but none of these all-expert configurations qualifies a long-context preset.

The all-expert failure prompted a separately tested **one-slot partial-layer-cache preset**, changing only parallel=2 to parallel=1 from the memory-fit default-order layer 4K screen. This preserves the Q6 weights, local NVMe placement, nc38, layer 1,1 split, 8192 batch, 4096 microbatch and 1024 MiB cache reserve. Its total configured context remains 262144, now belonging to one slot; testing reaches 64K input, not that configured maximum.

All six matching C1 requests reach their 256-token caps and are byte-identical to the previously reviewed coherent default-order C1 outputs. Warmed short generation averages 21.997 tokens/s with 7.914-second TTFT. Median 40K TTFT is 88.147 seconds, generation 20.929 tokens/s and complete request latency 100.379 seconds. The raw prose/JSON/code suites reach all 256/800/600 caps, with best end-to-end rates 19.30/17.43/17.64 tokens/s. Each raw prompt repeats identical output across three trials. The continuations are bounded rather than completed JSON/code-correctness tests; separate thinking-disabled arithmetic, JSON and automatic-tool probes all pass after the largest prefill.

The full public16-request PP sweep passes with zero prefix-cache hits and tokenizer/usage equality. Mean 8K/32K/64K prefill is 358.96/364.63/354.50 tokens/s. Physical VRAM is 31.84 GiB on the CPU-connected card and 31.80 GiB on the chipset-connected card. Pod RAM is 104.40 GiB, including 84.51 GiB anonymous/shared backing and 19.31 GiB other file pages; cgroup maximum/OOM counters are zero. The 50.66 GiB NVMe n-gram mapping has 3.60 GiB resident, zero anonymous pages and zero locked pages. This is a qualified C1-only option; a one-slot queue is not qualified parallel C2. [Preset](../../kubernetes/apps/llm/llmkube/resources/manual/flashnext-iggy-q6-cache-c1.yaml), [full manifest](artifacts/2026-10-05-flashnext-public-comparison/profiles/stew-q6-cache-layer-c1-qualified-full.json) and [matching-output proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/q6-c1-layer-output-comparison.json) retain the configuration and review.

The conservative uncached Stew r15 split passes all six matching C1 outputs, all fourteen original-nonce replay outputs, all four independent C2 outputs and arithmetic/JSON/automatic-tool probes. All matching/replay caps are reached and manually reviewed continuations remain coherent. Warm short generation is 18.66 tokens/s; median 40K TTFT is 401.05 seconds, generation 17.64 tokens/s and complete request wall time 415.60 seconds. This is about 21% faster generation and 8% lower long TTFT than the historical John Q6 screen, with changes in runtime and conventional storage placement rather than an isolated kernel experiment.

Its two independent 40K requests complete in 841.65 seconds, with TTFTs of 412.78 and 820.71 seconds. The earlier stream stalls during peer prefill, so C2 fits and passes bounded output checks but has substantial prefill interference. The six alone replay outputs repeat identically by session; the third long C1 continuation differs coherently from the first two, so no overall bit-exact determinism is claimed. Physical VRAM is 31.39/31.16 GiB, and pod RAM is 110.00 GiB including 57.37 GiB anonymous/shared pages and 52.44 GiB other file pages. The n-gram mapping is 85.29 MiB resident with zero anonymous and locked pages. Memory-limit reclaim counters do not represent an OOM; OOM counts are zero.

The identical-specification full run completes all nine raw trials at their 256/800/600-token caps. Best end-to-end prose/JSON/code rates are 18.47/18.55/18.53 tokens/s. Each prompt produces byte-identical output across its three repetitions; all full continuations are reviewed coherent without explicit loops or premature EOS. These capped raw continuations do not establish completed JSON/code correctness.

Its full public prefill sweep passes all sixteen requests with zero cached input and exact tokenizer/usage agreement. Mean 8K/32K/64K prefill is 76.08/74.21/71.90 tokens/s. Both 64K inputs complete in about 15.2 minutes each. The C1 cache option is about 4.9 times faster at 32K and 64K prefill, while the uncached option is slightly faster on the raw JSON/code prompts. The recommendation therefore follows workload and concurrency requirements.

Two host VPN interruptions break local administrative streams. The same Ready runtime Pod has zero restarts, and the remote client continues, saving each completed trial atomically. All nine raw trials and all sixteen prefill trials are recovered without rerunning them. The remaining replay/API chain is moved to a detached controller in the staging Pod with a single-instance lock. The replay precondition guard is corrected to require the actual final label pp65536-2, with unchanged nonce and request payloads and a fresh deployed-source checksum. The first interruption introduces an idle gap between raw and prefill; the resumed sweep retains the original warmup and prefix controls. [Recovery proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/q6-classic-transport-recovery.json) and [controller proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/q6-detached-controller-deployment-proof.json) retain this adaptation.

All fourteen original-nonce replay outputs after the completed 64K sweep reach 256 tokens and are manually reviewed coherent. Six alone outputs repeat identically by session; concurrent continuations differ coherently. No explicit loop, off-task numeric/blank continuation or premature EOS appears. Arithmetic, JSON-object and automatic-tool probes then pass. The final physical-memory capture is delayed by the host approval wait after protocol completion and is not a peak measurement: 30.87/30.36 GiB VRAM,107.39 GiB pod RAM,57.91 GiB anonymous/shared backing and49.25 GiB other file pages, with cgroup maximum/OOM counters zero. The earlier screen retains its separate immediate capture. The benchmark Pod stays Ready with zero restarts until removal. [Qualified C2 preset](../../kubernetes/apps/llm/llmkube/resources/manual/flashnext-iggy-q6-stew-c2.yaml) and [final capture proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/q6-detached-final-capture-proof.json) retain the deployable option and timing of the capture.

The configured context limits are capacity settings, not fully tested maxima. The timed sweeps validate up to 64K input at C1 and two 40K inputs at C2. These throughput checks include reasoning tokens and can end before the final answer; separate thinking-disabled API probes check completed answers. Q6 is a higher-precision representation, not a demonstrated quality improvement against BF16.

## Public LRU qualification

The closest [published profile](https://github.com/davetha/r9700-lru-expert-cache/tree/3743f1330f9c4174015440d5863e73a918a34809) completes all nine raw-generation caps, the full 16-request Aider prefill sweep, six matching C1 requests, four matching C2 requests and arithmetic, JSON and automatic tool-call probes. Its raw end-to-end rates are 83.43 tokens/s for prose, 101.15 for JSON and 89.86 for code, versus the publisher's 93.1, 138.8 and 128.5. A residual generation gap remains after matching the documented optimizations.

The publisher's separate PP protocol constructs 12,500 random words and measures a non-streamed, one-output request's whole wall time. The reproduced prompt contains 12,519 tokens and finishes in 8.47 seconds: 1,477.19 tokens/s, versus the published 3,551. This uses the same construction and wall-time contract, with a fixed word seed for reproduction; it is not the Aider PP column. The Aider sweep averages 1,037.80, 1,034.25 and 1,064.35 tokens/s at 8K, 32K and 64K respectively. Successful prefix-cache resets are recorded for the matching comparison.

On the workstation's matching prompt texts, warmed short generation is 86.15 tokens/s with 1.94-second TTFT. Median 40K TTFT is 29.66 seconds, generation is 71.98 tokens/s, and complete request wall time is 33.32 seconds. Actual input counts are 1,474 and 40,674 because the published tokenizer/template differs from the historical GGUF template. Both C2 requests reach 256 tokens, but the 40K pair takes 170.77 seconds. One generation stream pauses during the peer's prefill; this is substantial interference in the tested workload, not a FIFO-only interface.

Both physical GPUs are filled: 31.81 GiB on the CPU-connected card and 31.66 GiB on the chipset-connected card. Pod RAM reaches 113.99 GiB, including 90.78 GiB anonymous/shared memory and 22.42 GiB other file pages. There are no OOM events. The 47.68 GiB NVMe n-gram mapping has 10.66 GiB resident after the suite, with zero anonymous or locked pages. This keeps the full table off pinned RAM while allowing selected rows to remain pageable.

The fused-norm setting recovered from the publisher's README does not explain a large speed gain: the completed mode-0 raw control scores 81.49/101.22/84.92 tokens/s, versus mode 2's 83.43/101.15/89.86. Best measured steps are 31.63/38.21/39.98 ms, with draft acceptance 0.407/0.716/0.647. Text and acceptance vary, so these differences are not attributed solely to the norm switch. Manual review of matching C1/C2 outputs finds coherent continuations without the earlier Q6 repetition pattern; bounded 256-token answers can end mid-paragraph. Greedy long outputs vary between repetitions, so this qualification does not claim bit-for-bit deterministic generation or parity against BF16.

The profile is retained as a reproducible benchmark configuration rather than selected for production: Native is faster on these common requests and uses much less host RAM. Its temporary NVMe n-gram copy has been recycled for Q6 only after qualification; the original checkpoint remains on NAS and the parity records are retained.

## Shali r30 on one GPU

The plain reproduction uses only Iggy's CPU-connected card with the exact Atomic Q4 quant, 41 CPU-expert layers, a 4 GiB expert cache, two 128K slots, lazy NVMe n-grams and the staged ROCm 10 SDK. All three raw JSON and code requests reach their 800/600-token caps, with warmed best end-to-end rates of 31.53/30.43 tokens/s. The raw prose request reaches EOS at one token in all three repetitions and has no usable generation rate. The full PP sweep has mean rates of 343.39/346.06/326.88 tokens/s at 8K/32K/64K. Matching short requests generate at about 30.71 tokens/s after a warmed 3.67-second TTFT. All three 40K requests complete 256 tokens, with median TTFT 105.08 seconds and generation 27.75 tokens/s. Two short concurrent requests both reach the 256-token cap in about 21.3 seconds. Two 40K requests finish in about 227 seconds; one stream pauses behind the other prefill. These figures use the original matching-prompt rate definition. Arithmetic, JSON-object and automatic-tool probes pass. The active card uses 26.12 GiB and the second card is idle. Pod memory is 82.50 GiB, including reclaimable model-file cache. The NVMe n-gram mapping has 3.50 GiB resident after the sweep, with zero anonymous or locked pages. The MTP profile uses 47 CPU-expert layers and a shared Q8 draft head, depth 3. Its completed raw JSON/code sweep reaches every cap, with warmed best rates of 38.42/33.49 tokens/s. Prose again reaches EOS at one token. Its ten 8K and three 32K prefill samples average 302.49/298.37 tokens/s. The first 64K sample is 285.06 tokens/s; a brief owned source-archive transfer overlaps the second, which is retained but excluded. An uncontended repeat of that corpus rotation measures 287.41 tokens/s, giving a corrected paired mean of 286.23. The separate repeat receives its own 1K warmup and a new leading nonce, both retained. Matching short requests generate at about 29.75 tokens/s after a warmed 4.31-second TTFT. The three matching 40K requests have median TTFT 121.85 seconds and generation 26.88 tokens/s, each completing 256 output tokens. Thus MTP improves the raw JSON/code prompts but slows both prefill and generation on the original common reasoning prompts. Both short concurrent requests complete 256 tokens in about 25.9 seconds; both long concurrent requests reach 256 output tokens and finish in about 267 seconds, versus 227 for plain. Arithmetic, JSON-object and automatic-tool probes pass.

## John IQ3 plain

The original Unsloth IQ3_XXS model completes the public raw decode and prefill sweeps. JSON and code each reach every output cap, with warmed best end-to-end rates of 42.91 and 43.04 tokens/s. Prose stops after one token in all three trials and has no usable generation rate. Mean PP is 693.87/547.88/469.91 tokens/s at 8K/32K/64K. The 32K samples range from 440.82 to 607.80; the final two long samples retain sixteen output tokens, while other segments reach early EOS. PP still uses the verified input count and first-token latency. No prompt-cache hits are recorded.

The matching short chat prompt reaches all 256 output tokens at about 42.29 tokens/s after a warmed 1.63–1.73-second TTFT. All three 40K matching requests reach 256 tokens, with median TTFT 66.78 seconds and generation 31.71 tokens/s. The two short concurrent requests reach 256 tokens each in 11.49 seconds; the two 40K requests do so in 194.17 seconds. The earlier long stream pauses during the other request's prefill, so its 2.09 tokens/s stream average does not measure continuous device decode. Arithmetic, JSON-object and automatic-tool probes pass. Physical VRAM is 29.91/26.92 GiB after the suite, pod memory 53.13 GiB, and process RSS 8.15 GiB. The NVMe n-gram mapping has 3.43 GiB resident with zero anonymous or locked pages; no OOM events occur. This result is a different quant and an older runtime than the matching Atomic Q4 Stew control; its smaller files do not establish a runtime speedup or equivalent model quality.

## John IQ3 MTP, balanced retry

Changing the failed draft placement from 1:1.2 to 1:1 leaves sufficient VRAM for the shared Q8 head and completes the entire raw, PP, matching and C2 suite. Prose again stops at one token. JSON and code reach every cap, with best end-to-end rates 82.26/71.71 tokens/s. PP means are 675.51/531.10/447.68 tokens/s at 8K/32K/64K, slightly below plain at each depth. All matching requests reach 256 output tokens. Warmed short TTFT averages 1.76 seconds and generation 62.61 tokens/s, versus plain's 1.68 seconds and 42.29. Median 40K TTFT is 70.01 seconds and generation 47.29 tokens/s, versus 66.78 seconds and 31.71. Complete 40K request latency is approximately unchanged: 75.42 versus 74.86 seconds.

Both short C2 requests reach 256 tokens in 11.35 seconds; both long requests do so in 203.18 seconds, versus plain's 11.49/194.17. The early long stream pauses during its peer's prefill. Reviewed outputs remain coherent; arithmetic, JSON-object and automatic-tool probes pass. Physical VRAM is 31.54/29.67 GiB, pod RAM 50.30 GiB. The local NVMe n-gram mapping has about 3.47 GiB resident, with zero anonymous or locked pages. The original failed asymmetric start remains in the evidence.

## Dual-card Stew r15 MTP control

This control retains the original Atomic Q4 and earlier four-layer CPU expert placement needed for the shared Q8 MTP head, with the same single 262K slot. Raw JSON and code reach every output cap, with warmed best end-to-end generation of 68.14/62.60 tokens/s. Prose again stops at one token. Its three 32K prefill samples average 561.58 tokens/s, versus 1,351.53 for the uncached plain control. The full two-sample 64K mean is 568.96 tokens/s. The shared short chat requests all reach 256 output tokens. Warmed generation is 54.94–55.43 tokens/s, above plain's 48.67, but warmed TTFT rises to 2.35–2.36 seconds from 0.81. Their complete request latency is about 7.0 seconds versus plain's 6.1, so the higher generation rate does not win this short request. All three shared 40K requests reach 256 tokens. Median TTFT is 63.35 seconds and generation is 46.23 tokens/s, versus plain's 28.23 seconds and 42.51 tokens/s. Arithmetic, JSON-object and automatic-tool probes pass. This placement has no demonstrated advantage for the prompt-heavy shared workload. The CPU placement and draft are part of this comparison; it does not isolate speculative decoding alone on an otherwise identical placement.

## Strata single-card base, completed

The portable attention path on the CPU-connected card completes all raw, PP, matching and queued-pair requests. Raw best end-to-end prose/JSON/code rates are 38.32/84.47/77.56 tokens/s. PP means are 1,722.65/1,691.64/1,643.16 at 8K/32K/64K. Matching short generation averages 70.27 tokens/s after a warmed 1.69-second TTFT; the median 40K request has TTFT 24.20 seconds, generation 68.08 tokens/s and total latency 27.93 seconds. Every matching and paired request reaches 256 output tokens. The short pair finishes within 10.54 seconds and the 40K pair within 55.99 seconds through the same serial frontend queue. Arithmetic, JSON and automatic-tool probes pass.

This single-card layout generates faster than the completed dual WMMA layout, while dual WMMA finishes the long request sooner because its prefill is faster. This comparison changes GPU count and attention path. The completed dual base run narrows that comparison; PCIe topology alone is not established as the cause of the generation difference.

## Strata dual-card base, completed

The same two-card automatic split with portable attention completes all nine raw, sixteen PP, six matching and four queued requests. PP means are 1,416.46/2,188.77/2,556.28 tokens/s at 8K/32K/64K. Matching short generation averages 45.32 tokens/s after a warmed 1.48-second TTFT. Median 40K TTFT is 17.31 seconds, generation 43.36 tokens/s and complete request latency 23.19 seconds. The queued long pair finishes within 45.11 seconds. Every matching and paired request reaches 256 output tokens; reviewed reasoning remains coherent, and arithmetic, JSON and automatic-tool probes pass.

Compared with this dual base, dual WMMA improves 32K/64K PP by approximately 35%/39% and lowers matching 40K request latency by approximately 21%. Single-card base remains faster in generation than either dual layout. Outputs differ across greedy repetitions even within a layout; the retained hashes and draft counters do not establish a bit-exact attention comparison.

## Strata dual-card WMMA, completed

The corrected MMQ build with `STRATA_HIP_WMMA=1` completes all nine raw trials, the full sixteen-request PP sweep, six matching requests and both paired requests. Every raw request reaches its output cap. Best end-to-end generation is 46.73/63.60/55.18 tokens/s for prose/JSON/code. Mean PP is 1,886.00/2,962.69/3,542.43 tokens/s at 8K/32K/64K. Some PP segments reach early EOS; their first-token measurements retain verified input counts and zero prefix hits.

Matching short requests have median TTFT 1.426 seconds and generation 46.56 tokens/s. The three 40K requests reach all 256 output tokens, with median TTFT 12.62 seconds and generation 44.31 tokens/s. Native Radiance remains faster in generation, while this Strata profile leads completed long-input prefill. Its C2 requests each reach 256 tokens, with pair completion times 13.22 seconds short and 35.77 seconds long. The upstream frontend serves one active request and queues the other; these are queue-throughput measurements rather than qualification of parallel model execution. Arithmetic, JSON-object and automatic-tool checks pass.

Physical VRAM after the suite is 31.55/31.66 GiB, pod memory 95.16 GiB and process RSS 58.77 GiB. No cgroup OOM or memory-limit events occur. Its direct-read n-gram path uses the exact local NVMe IQ4_NL payload. WMMA attention is a documented numerical adaptation; this comparison also changes dense conversion and draft packing from the original R9V quant, so it does not establish equal model quality or isolate attention alone.

## Hardware, memory and compatibility

Iggy retains Talos 1.13.5 and kernel 6.18.36, with a Ryzen 9 3900X, 128 GB system RAM and two 32 GB R9700s. Runtime images and staged SDKs supply the required user-space changes. The table records physical VRAM and cgroup RAM after each suite; the failed all-expert profiles are explicitly captured after their long-request allocation failures, so a released compute buffer can reduce the final usage on one card.

| Measured profile | CPU-card VRAM | Chipset-card VRAM | Pod RAM | Anonymous + shmem | File pages excluding shmem |
|---|---:|---:|---:|---:|---:|
| Native 1.0.13 production | 31.34 GiB | 31.33 GiB | 25.68 GiB | 25.54 GiB | 0.02 GiB |
| Stew plain Q4 | 30.52 GiB | 31.13 GiB | 55.16 GiB | 2.64 GiB | 52.44 GiB |
| Stew MTP Q4 | 30.58 GiB | 30.66 GiB | 12.49 GiB | 9.67 GiB | 2.72 GiB |
| R9V IQ4 | 28.12 GiB | 28.02 GiB | 75.04 GiB | 45.52 GiB | 29.15 GiB |
| Shali plain Q4 | 26.12 GiB | 0.06 GiB | 82.50 GiB | 43.75 GiB | 38.40 GiB |
| Shali MTP Q4 | 25.18 GiB | 0.06 GiB | 73.05 GiB | 51.17 GiB | 21.59 GiB |
| John plain IQ3 | 29.91 GiB | 26.92 GiB | 53.13 GiB | 4.46 GiB | 48.52 GiB |
| John MTP IQ3 | 31.54 GiB | 29.67 GiB | 50.30 GiB | 5.51 GiB | 44.64 GiB |
| Strata single | 31.53 GiB | 0.06 GiB | 93.57 GiB | 57.43 GiB | 36.01 GiB |
| Strata dual base | 31.53 GiB | 31.64 GiB | 104.64 GiB | 58.93 GiB | 45.57 GiB |
| Strata dual WMMA | 31.55 GiB | 31.66 GiB | 95.16 GiB | 58.94 GiB | 36.08 GiB |
| Davet LRU | 31.81 GiB | 31.66 GiB | 113.99 GiB | 90.78 GiB | 22.42 GiB |
| Q6 initial tensor cache | 31.27 GiB | 31.71 GiB | 109.26 GiB | 87.80 GiB | 20.93 GiB |
| Q6 tensor hybrid replay | 31.25 GiB | 31.69 GiB | 110.00 GiB | 86.30 GiB | 23.24 GiB |
| Q6 pure RCCL | 31.04 GiB | 31.67 GiB | 110.00 GiB | 86.22 GiB | 23.32 GiB |
| Q6 larger cache (after failed 40K) | 31.78 GiB | 26.64 GiB | 112.20 GiB | 103.80 GiB | 7.91 GiB |
| Q6 classic r15 | 31.39 GiB | 31.16 GiB | 110.00 GiB | 57.37 GiB | 52.44 GiB |
| Q6 layer 4K retry | 31.55 GiB | 31.51 GiB | 94.82 GiB | 84.46 GiB | 9.93 GiB |
| Q6 all-expert 4K / 2GiB reserve (after failed 40K) | 29.15 GiB | 30.53 GiB | 113.36 GiB | 103.47 GiB | 9.40 GiB |
| Q6 layer 4K fast card first | 31.52 GiB | 31.54 GiB | 93.83 GiB | 84.48 GiB | 8.93 GiB |
| Q6 layer 4K eager host remap | 31.56 GiB | 31.52 GiB | 99.95 GiB | 84.43 GiB | 15.09 GiB |
| Q6 all-expert single-slot / 4GiB reserve (after failed 40K) | 27.18 GiB | 28.51 GiB | 110.93 GiB | 103.47 GiB | 6.97 GiB |
| Q6 layer cache, single slot | 31.84 GiB | 31.80 GiB | 104.40 GiB | 84.51 GiB | 19.31 GiB |
| Q6 classic r15 full suite, after admin wait | 30.87 GiB | 30.36 GiB | 107.39 GiB | 57.91 GiB | 49.25 GiB |

## Collective compatibility on Iggy

Iggy's physical GPU at `0000:2f:00.0` has a CPU-connected Gen4 x16 path. The card at `0000:25:00.0` shares a chipset Gen4 x4 upstream path. Endpoint link advertisements alone conceal that difference. Strata's startup host-to-device probe later measures 28.4 GB/s on the CPU-connected card and 6.5 GB/s on the chipset-connected card; these are the runtime's copy-probe results, separate from its inference timings. R9V orders the faster card first and retains the published asymmetric 416/224 expert channels.

RCCL 2.30.4 fails its first collective on the chipset-connected card. The [published hostcall probe and diagnosis](https://github.com/cadamcat/dual-radeon-vllm#the-rccl-bug) reproduce the cause directly: a plain kernel works on both cards; the hostcall kernel works on the CPU-connected card and is refused on the chipset-connected card. This is consistent with [the upstream RCCL report](https://github.com/ROCm/legacy-rocm-build/issues/6520).

The checksum-verified hostcall-free RCCL 2.27.7 multi-architecture library contains a gfx1201 image without hostcall metadata. Its published diagnostic and ROCm-SMI shims are built separately. Both ranks pass FP32, BF16 and integer all-reduce/all-gather checks, from one through one million elements, plus all-gather graph capture. R9V's existing PyNccl communicator also passes integer tensor-layout checks across dimensions 0, 1 and -1.

Selecting that library through PyNccl alone fixes initial all-reduce but leaves a later ROCm all-gather shortcut on PyTorch's original RCCL. A minimal opt-in patch selects the existing PyNccl all-gather path instead. It preserves the original tensor transformations and collective values. R9V retains its pinned image, native decode kernels and original model; the compatibility library and Python routing adaptation are explicitly recorded. Neither failed startup is a throughput result.

The closest published LRU configuration uses a newer-glibc root filesystem while preserving the original engine, Torch, SDK, Quark and GPU kernels. Whole-file hashes match for 2,384 engine/kernel files and 38,884 dependency files. Eight native base libraries are also preserved from the pinned published image. The verified runtime tree is placed on local NVMe. The replacement root filesystem supplies libc; it is not the measured Native Radiance engine.

The original root filesystem cannot load the hostcall-free RCCL library because it requires GLIBC 2.38. The newer root filesystem exposes a second issue: global symbol interposition mixes the selected RCCL with another already loaded build, producing a corrupted communicator. A narrowly scoped, opt-in `RTLD_DEEPBIND` overlay keeps the selected PyNccl library's symbols ahead of global definitions, following the [dynamic loader contract](https://man7.org/linux/man-pages/man3/dlopen.3.html). Both ranks then pass FP32, BF16 and integer all-reduce/all-gather from one through one million elements, graph capture, and tensor-layout checks. The overlay leaves the published library bytes and default behavior unchanged when unset.

Python module precedence also needs to match the published image. Prepending `/app/r4dhip` selects the preserved `r4d.so`, whose path, sparse-attention interfaces and QSA availability gate are checked explicitly. The replacement base's extra AITER package is hidden in the ephemeral container to restore its absence in the published image; the launch already disables AITER. The exact vLLM MXFP4 custom operation then loads the preserved Quark HIP library and matches every signed E2M1 code and two power-of-two scales exactly in FP16 and BF16 on both GPUs. The R4D sparse-kernel interface check is not a numerical parity test of that kernel. All failed full-model attempts and diagnostic probes remain in the evidence directory.

The published 47.68 GiB FP8 n-gram payload is copied to local NVMe with its original BF16 scale. The retained parity proof checks sampled rows in all 128 tensors against the source, with byte-range hashes. Runtime memory records distinguish the pageable file mapping from pinned conventional expert backing. This storage adaptation preserves n-gram values; it changes their placement from the published default.

The published vLLM version exposes `/reset_prefix_cache` through its developer API routes. The private benchmark enables `VLLM_SERVER_DEV_MODE=1` and verifies a successful reset before each matching C1/C2 repetition. A CPU probe registers the original router and tests its HTTP success response with a mocked engine; benchmark records verify the real engine reset separately. The earlier raw suite completes all nine caps and passes all three API checks before a helper encounters the absent route. Those measurements and the interrupted sweep remain retained.

The pinned launcher contains a stale comment advising `VLLM_GEMMA_NORM_FUSED=0`. The same pinned README corrects it using captured `rms_norm` kernel traces: mode 2 was active from `combo1` onward. The initial completed raw suite therefore provides a mode-0 baseline, while the closest published configuration enables mode 2. The preserved fused path is tested on both GPUs against the native decomposition. Decode-sized samples are identical; the large sample differs in 3 of 1,048,576 BF16 elements by one rounding step, matching the source’s stated reduction-order effect. The actual selected implementation is recorded in the probe. This switch changes numerical reduction order; full-output coherence and API qualification follow separately.

## Public sources and reproduction boundaries

| Source | Published workload | Closest Iggy reproduction and adaptations |
|---|---|---|
| [John](https://github.com/JohnTDI-cpu/llama.cpp-flash-next-rdna4) | Original IQ3, private prose/code; PP2048; EPYC and ROCm 7.2.4 | Same quant and kernel switches; 12 CPU threads, ROCm 7.14, shared KV pool enlarged for common 64K/C2 inputs; balanced MTP retry after asymmetric draft OOM |
| [R9V](https://github.com/Dyluhn/R9V/tree/aeee44ff9e37e973bf435bcd8bb0688e9ef1cc29) | IQ4_XS WMMA, pinned Aider corpus: 1,684.6/1,640.6/1,605.1 PP at 8K/32K/64K | Same corpus, warmup, counts and asymmetric channels; original model/CED off/NVMe; hostcall-free RCCL and opt-in PyNccl gather adaptation |
| [Shali](https://github.com/Shali12/r9700-flash-next-notes) | Atomic Q4, one R9700, Ryzen 7600X/DDR5, medium effort and sampled prompts | Same r30 tree, Atomic files, 4 GiB cache, 41/47 CPU-expert placements and SDK; fast physical card, six threads, standard template and cold-prefix policy |
| [Davet LRU](https://github.com/davetha/r9700-lru-expert-cache/tree/3743f1330f9c4174015440d5863e73a918a34809) | MXFP4/FP8 Heretic, public raw prompts, FP8 target head and MTP4 | Same checkpoint, patches and flags; exact FP8 n-gram rows moved to NVMe, newer glibc rootfs and hostcall-free collectives |
| [Strata AMD guide](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/AMD_HIP.md) | Portable attention and optional gfx1201 WMMA path | Exact v0.1.39 engine; IQ4_XS expert bytes with converted dense pack and official packed draft; single/dual base and dual WMMA separate |

Public headline rates retain their source's workload and precision contract. John PP2048 and private prompts cannot be ranked directly against the longer common sweeps. Shali's DDR5 CPU and sampled medium-effort prompts also differ. [Apex's Q6 results](https://github.com/VectorAnvil/apex-r9700) concern the 27B Heretic architecture, not Flash Next's 125B MoE; those results are excluded from this competition.

Strata's raw prose, JSON and code output hashes differ across the three identical-prompt, temperature-zero repetitions, including the single-card portable attention profile. The upstream frontend and engine protocol confirm greedy selection. The [repeatability record](artifacts/2026-10-05-flashnext-public-comparison/provenance/strata-output-repeatability.json) retains input/output hashes and draft counters. This is not a bit-exact output claim. Reviewed outputs remain coherent and all raw caps are reached; differing text alone is not classified as corruption.


## Reproduction and production outcome

The retained profile manifests, pinned source revisions, build manifests, SDK compatibility proofs and benchmark implementation snapshots describe the executable configurations. Suspended presets provide the exact Atomic Q4 control and qualified Q6 configurations; the selector renders a reviewable preview before changing the active resource. Stew presets verify both the build-manifest digest and every listed artifact at startup. They depend on the retained workspace build and model volumes.

Use the selector with --output for a preview, for example: python3 scripts/llm/select_flashnext_iggy.py q4-stew --output /tmp/flashnext-q4.yaml. The qualified Q6 keys are q6-cache-c1 and q6-stew-c2. Selecting a profile without --output changes repository files for validation and publication through jj; it does not directly contact the cluster. Native Radiance remains the active production choice.

The matched workload uses identical base prompt bytes, deterministic temperature zero and seed 7, with three single-request repetitions and bounded 256-token completions including reasoning. Public raw suites preserve their separate prompt and output contracts. PP uses the pinned Aider corpus and tokenizer-accounted sizes up to 64K. Model templates can produce different total input token counts, and quants have different weights and n-gram precision; matching prompt bytes does not establish equal model quality. All current-run measurements retain source JSONs, output text, adaptation proofs and failed attempts.

Active n-gram tables remain on local NVMe without whole-table pinning. To promote all Q6 conventional shards while preserving the 80 GiB free-space reserve, three inactive private benchmark copies were recycled: John IQ3's n-gram-containing shard, Strata's extracted n-gram table and Davet LRU's extracted table. Their archive originals and converted packs remain available. Those three public profiles require local NVMe restaging before another run; their historical measurements remain retained. Atomic Q4, Native RAD, Q6 and the original D4X file remain in place.

Native Radiance 1.0.13 is restored with exact TP2, two configured 262144-token slots and disk n-gram placement. Flux fetches and applies the first published revision, both scoped reconciliation holds are removed, and the Ready Iggy Pod requests both GPUs with zero restarts. The live /models mount resolves to /dev/nvme0n1p1, and the original 121,969,901,568-byte RAD file is checked in the running container. The minimal image ships BusyBox utilities, so the storage probe invokes its cat/stat applets explicitly. [Deployment proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/production-deployment-verification.json) records that first deployment; the final amended revision is verified after repushing.

The LiteLLM flashnext-iggy alias passes arithmetic, JSON-object, strict-schema and automatic-tool tests with the existing Hermes credential kept in memory. Forced tool_choice=required returns HTTP 400, matching the previously observed Native limitation. [Alias responses](artifacts/2026-10-05-flashnext-public-comparison/provenance/production-alias-smoke.json) retain the actual outcomes without credentials. Both Q6 presets remain suspended catalogue options.

The original Iggy NFS read-ahead setting is restored from 15360 KiB to 128 KiB, and all nine explicitly owned staging Pods are removed after the final evidence snapshot. [Cleanup proof](artifacts/2026-10-05-flashnext-public-comparison/provenance/private-campaign-cleanup-proof.json) records completed deletion and the restored setting. Steam, original model files, archive originals and retained converted packs are preserved.

The separate Amnesia model is currently Pending because the scheduler reports insufficient NVIDIA GPU and memory availability; the Amnesia node itself is Ready. Its configuration is unchanged by this campaign. [Workstation status](artifacts/2026-10-05-flashnext-public-comparison/provenance/amnesia-post-campaign-status.json) records that separate condition without changing its allocations or Steam.

