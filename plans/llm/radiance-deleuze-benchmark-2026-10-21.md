# Radiance on Deleuze, October 21 2026

This campaign repeats the original Iggy Radiance test on Deleuze's two R9700s, then measures and tunes the latest published runtime. The original runtime improves substantially on the new host; the tuned 1.10.0 profile reduces 40K request latency further while retaining exact TP communication. Full results, rejected candidates and source/runtime provenance are retained.

## Hardware and reproducibility

Deleuze has a Ryzen 5 5600 (6 cores / 12 threads), 128 GiB installed DDR4-3200, and two 32 GB Radeon AI PRO R9700s. Both CPU root ports support PCIe 4.0 ×8. The internal card bridges report PCIe 5.0 ×16; the complete upstream paths identify the host bottleneck. Both root ports report 16 GT/s ×8 while the benchmark is active; idle link speed downshifts are recorded separately from link capability. Talos is v1.14.4, kernel 6.18.57, and AMD compute wave save/restore is enabled. See [hardware](artifacts/2026-10-21-radiance-deleuze/hardware.json) and [node provenance](artifacts/2026-10-21-radiance-deleuze/node.json).

Iggy's original setup used a Ryzen 9 3900X, PCIe 4.0 ×16/×4 host links, Talos v1.13.5 and kernel 6.18.36. Differences from those historical results include CPU, memory subsystem, operating system and runtime warming; this is not an isolated measurement of PCIe lane allocation.

Both parts use the original `StillDeadcode/qwen3.8-next-flash-fp8-iq4r-moe` container at model revision `8267a67384583f6be309981baf878b09ff900a9a`: 121,969,901,568 bytes, SHA-256 `0af5e96244e80c21ac8edca1719dae49b8a201b94a2f3994c3e24026ceaa4d20`. It is copied from the retained archive to Deleuze's local NVMe and verified before serving. The `radiance-deleuze` 256 GiB claim uses `openebs-hostpath-retain` and is excluded from Flux pruning. The original Iggy artifacts remain retained.

## Protocol

The existing [original harness](../../scripts/llm/qwen_p2p_bench.py) repeats the October 5 short/40K tests, generating 256 tokens at temperature zero, seed 20260923, one repetition, with C1 and C2. The original single-stream prompt hashes and token counts are checked against the [Iggy artifacts](artifacts/2026-10-05-flashnext-iggy). Its throughput definition is generated tokens divided by elapsed time after the first streamed token.

The existing [public-comparison harness](../../scripts/llm/flashnext_public_bench.py) adds three independent short and 40K chat trials (seed 7), three trials each of raw prose/JSON/code at 256/800/600 output tokens, the pinned 16-request Aider prefill sweep, and one independent C2 pair per context. It retains outputs, timing, usage, prompt hashes and counters. Warm short throughput averages trials two and three; long-context figures use medians of three. Raw decode rates include prefill, while the chat comparison uses the original throughput definition. C2 pair wall time is the later request's completion, and each stream's timing is retained separately.

New measurements reach the pod through a workstation `kubectl port-forward`; client TTFT includes that transport. The two Deleuze versions share this path. Every benchmark process disables prefix caching at the server with `--no-prefix-cache`. A retained initial HTTP 400 establishes that Radiance 1.0.12 rejects the llama.cpp-specific per-request `cache_prompt` field; the actual benchmark requests omit it, as in the historical Radiance runs. Zero cached-token counts are checked. Model transfers finish before requests begin. These are bounded performance and API checks, not a model quality evaluation or latency percentiles under sustained production load.

## Part 1: historical runtime

Radiance 1.0.12 is the version used for the original recorded test, pinned to the amd64 image digest `sha256:9ec9a73048f3c11770c0e70806d88ce88ee4cfaf2a24c8ab84d28df76b0e224e`. This is earlier than the last Iggy production version, 1.3.0. The historical flags retain exact TP2, two sequences, 262,144 context, a 12 GiB host expert pool per rank, disk n-grams, FP8 KV, speculative depth 3, a 2,048-token batch, 512 MiB GPU headroom and the then-supported `--expert-vs-cache-ratio 0.82`.

The direct original C1 short request has 1,512 input tokens, 0.520 s TTFT and 102.07 tokens/s decode; the 40K request has 40,712 input tokens, 10.066 s TTFT and 109.48 tokens/s. Both prompt hashes match the Iggy records and all requests report zero cached tokens. Iggy's corresponding 1.0.12 observations were 1.001 s / 78.89 tokens/s and 20.490 s / 88.42 tokens/s. The Deleuze short request therefore generates 29.4% faster, while long TTFT falls 50.9% and long generation rises 23.8%; these are single samples, with the hardware/OS caveats above.

The original concurrent short pair finishes in 3.34 s, and the 40K pair in 23.16 s. The long streams' TTFTs are 9.69 and 20.53 s; their observed decode rates are 19.56 and 97.47 tokens/s. The earlier stream pauses while its peer prefills, so averaging those two rates is not a device decode measurement.

The broader repeated suite warms short generation to 169.66 tokens/s. Its three long requests have median TTFT 9.667 s, median generation 130.89 tokens/s and median complete latency 11.607 s. The 8K/32K/64K corpus sweeps average 3,986.93 / 3,842.61 / 3,715.57 prompt tokens/s, with exact tokenizer/usage agreement. Raw prose/JSON/code best end-to-end rates are 166.28 / 235.97 / 209.46 tokens/s, and all nine raw trials reach their caps.

Arithmetic JSON, strict JSON schema and automatic tools pass after the largest prefill. The pod completes without restarts, OOMs or memory-limit events. Its final container memory is 25.76 GiB; the GPUs hold about 31.3 GiB each. Retained [full results](artifacts/2026-10-21-radiance-deleuze/old-1.0.12) distinguish the original single samples from the repeated campaign.

## Part 2: Radiance 1.10.0 and tuning

[Version 1.10.0](https://codeberg.org/StillDeadcode/radiance/src/tag/v1.10.0) is the latest published tag checked for this run, at upstream revision `4246a1dd04e7e1bb8c1e9b6da847ea17c27a0f36`. Its amd64 image is pinned to `sha256:bb65a0a95534e4d35e21fa7c6ebd674365d271476169a67ffa9954af06a017ba`. [Source, image and harness provenance](artifacts/2026-10-21-radiance-deleuze/upstream-provenance.json) and the image's [actual CLI help](artifacts/2026-10-21-radiance-deleuze/latest-help.txt) are retained.

The new runtime sizes the expert/KV split elastically; `--expert-vs-cache-ratio` is removed. Its newer default token embedding placement is RAM, so the initial version-control measurement explicitly selects `--embedding-placement vram`, matching the historical placement. Its linear-state checkpoint store is in pinned host memory and now defaults to an automatically sized store. The new dashboard is served on the same HTTP port as the inference API.

The tuning screens consider RAM n-grams and token embeddings, GPU headroom, the expert host pool, CPU governor, prefill spans (`--max-num-batched-tokens 4096 --prefill-span 2`), and adaptive speculative depth (`--num-speculative-tokens 6 --draft-window adaptive`). WHT6 is measured separately because it changes communication precision. Every candidate's exact flags and runtime diagnostics are retained; a prepared profile alone is not evidence of a completed measurement.

The RAM n-gram candidate uses 74.55 GiB of host memory and reports 169 seconds of startup, versus 20 seconds for the disk profiles. Its three 40K requests have median 11.08 s TTFT and 120.07 tokens/s, compared with 8.57 s and 169.20 on the new-runtime control. It is rejected for this deployment. The subsequent span and adaptive screens therefore keep n-grams on local NVMe.

The strict tokenizer now rejects simultaneous `prompt` and `content`. The harness sends one input field, falling back to llama.cpp's `content` form for runtimes that require it; prompt text, corpus digest, fitting algorithm and timing are unchanged. The initial rejected tokenizer attempt is retained, and the successful 1.10.0 prefill sweep checks exact tokenizer/usage agreement at all sixteen cells.

Rates are tokens/s, latency columns are seconds. A dash means that protocol was not run for the candidate. All completed chat/raw cells reach their caps; all recorded cache counters are zero. The short span/adaptive screens start with three chat trials directly after startup; the control, compact and final runs first repeat the original four cells. That startup history is retained and matters most to the short trials.

| Profile | Short warm TG | 40K TTFT | 40K TG | 40K wall | 32K PP | 64K PP | C2 40K wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| new-adaptive | 168.23 | 7.54 | 169.47 | 9.05 | — | — | 18.55 |
| new-compact | 184.86 | 7.38 | 168.06 | 8.90 | 5265.42 | 5336.59 | 18.77 |
| new-final | 185.09 | 7.37 | 167.80 | 8.90 | 5235.30 | 5281.88 | 18.75 |
| new-matched | 185.84 | 8.57 | 169.20 | 10.09 | 4547.15 | 4459.73 | 21.17 |
| new-performance | 185.69 | 7.37 | 168.77 | 8.89 | — | — | 18.20 |
| new-powersave-repeat | 185.95 | 7.41 | 169.70 | 8.92 | — | — | — |
| new-ram | 155.11 | 11.08 | 120.07 | 13.21 | — | — | 25.37 |
| new-span | 182.29 | 7.37 | 164.96 | 8.92 | — | — | 18.31 |
| new-wht6 | 185.15 | 5.99 | 175.34 | 7.45 | 6442.22 | 6502.15 | 15.86 |
| old-1.0.12 | 169.66 | 9.67 | 130.89 | 11.61 | 3842.61 | 3715.57 | 26.54 |

The selected exact profile uses `--embedding-placement ram`, `--ngram-placement disk`, `--host-pool-mib 8192`, `--gpu-headroom-mib 160`, `--max-num-batched-tokens 4096 --prefill-span 2`, and fixed speculative depth 3. TP2, FP8 KV, two sequences and the 262,144-token request bound are retained. The final 48 GiB container limit passes the entire suite. Its measured 64K prefill is 5281.88 tokens/s; the planner reports 524,316 attention-pool tokens, sufficient for two configured full-window sessions before prefix retention. Current tests reach 64K input; two simultaneous full-window requests are not demonstrated.

Reducing the host expert pool from 12 to 8 GiB per rank preserves throughput while saving approximately 8 GiB of aggregate pinned host budget. The 4K budget/span-2 configuration improves 40K complete latency from 10.09 to 8.90 seconds versus the new-version control. Changing these settings together is a measured configuration comparison, not an isolated attribution to one flag.

Adaptive depth 6 raises raw JSON/code best rates to 256.70/234.36 tokens/s, but lowers short-prose throughput and does not beat fixed depth 3 on complete 40K latency. It is not selected. The CPU performance governor also shows no material gain: 185.69 short tokens/s and 7.37 s long TTFT, versus 184.86 and 7.38 before it, and 185.95 and 7.41 after restoring powersave/balance_performance. Both original CPU policy values are verified on all twelve logical CPUs and the temporary Talos document is removed. Two preliminary wire/final runs affected by the cleanup's EPP reset are retained with explicit exclusion records; the scored final runs verify the restored policy in live diagnostics.

WHT6 is the faster alternative: 40K median TTFT 5.99 s, complete latency 7.45 s and 64K prefill 6502.15 tokens/s. `--tp-wire-min-kb 128` keeps the tested C1/C2 decode messages exact and compresses prefill. It passes bounded JSON/schema/tool checks, but introduces a lossy 6-bit inter-GPU payload and is not established as quality-equivalent. Exact TP remains the hosted default.

The original single-sample test under the final exact settings records short TTFT 0.496 s / 135.63 tokens/s and 40K TTFT 7.387 s / 146.25 tokens/s. These are separate from the warmed repeated figures above. All scored profiles pass arithmetic JSON, strict schema and automatic tools, and complete without pod restarts or OOM. The matching chat cap frequently finishes inside reasoning; the raw capped JSON/code continuations are not completed-format correctness tests. [Qualification checks](artifacts/2026-10-21-radiance-deleuze/qualification.json), [summaries](artifacts/2026-10-21-radiance-deleuze/summary.json) and each profile's full outputs retain these distinctions.

## Serving and validation

The final InferenceService is `radiance` in namespace `llm`, pinned to Deleuze and requesting both AMD GPUs. Its dashboard is routed through `envoy-internal` at `https://radiance.${DOMAIN_NAME}` using the repository's existing Pocket ID gateway authentication convention for user `tim`. The concrete hostname is `radiance.timblakely.com`.

The initial full pinned flux-local 8.4.0 check passes 175 tests with the two repository-configured deselections. Kubernetes server dry-run accepts the new PVC, Model, InferenceService, HTTPRoute, Pocket ID group/client and SecurityPolicy. The final namespace-scoped pinned check passes 20/20 tests, and server dry-run accepts the selected 48 GiB configuration. Production restores prefix reuse and adds an 8 GiB host prefix tier (`--prefix-cache-mib 8192`). The published configuration revision is fetched by `flux-system` and applied by `llmkube-resources`; both report Ready. The managed pod is Ready on Deleuze with the pinned 1.10.0 digest, both AMD GPUs and no restarts or OOMs. Its model mount resolves to local NVMe, and its CPU governor/EPP remain powersave/balance_performance.

The HTTPS dashboard route is accepted and resolves its backend; the OIDC policy is accepted and unauthenticated HTTPS requests redirect to `pid.timblakely.com`. The direct dashboard and health endpoint return HTTP 200, the API identifies `radiance-1.10.0`, and arithmetic JSON, strict schema and automatic tools pass. A repeated 7,692-token prompt reuses 7,680 tokens (the first request reports zero cached tokens), confirming that production prefix reuse is active. [Deployment verification](artifacts/2026-10-21-radiance-deleuze/production/verification.json) records the configuration revision and each check. The final report/evidence update is reconciled afterward with the same running pod.
