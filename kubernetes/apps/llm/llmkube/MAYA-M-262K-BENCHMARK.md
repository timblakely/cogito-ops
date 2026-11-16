# Maya-M 262144-token context pilot

Run `maya-262k-20261116T083345Z`; measured 2026-11-16 on Iggy. Raw [summary](resources/manual/maya-m/bench/results/maya-262k-20261116T083345Z/summary.json), [metadata](resources/manual/maya-m/bench/results/maya-262k-20261116T083345Z/metadata.json) and [progress/resource events](resources/manual/maya-m/bench/results/maya-262k-20261116T083345Z/events.jsonl) are retained.

## Result

The native runtime completed the full-window pilot with zero prefix reuse, no OOM kills, and exact retrieval of all three planted records plus the absent-key control. Native and LiteLLM context settings are aligned to 262144 after the pilot; normal prefix caching is restored.

| Actual prompt tokens | Cold prefill tokens/s | First content (s) | Decode tokens/s |
| ---: | ---: | ---: | ---: |
| 32,504 | 980.2 | 33.2 | 23.9 |
| 65,272 | 1,074.3 | 60.8 | 23.2 |
| 130,807 | 1,095.8 | 119.4 | 23.5 |
| 261,879 | 1,066.6 | 245.6 | 23.0 |

The near-full request took 256.8 seconds total, including exactly 256 generated tokens. First content at 4.09 minutes is the practical cold-prompt latency; decode staying near 23 tokens/s does not make a fresh 262K prompt instantaneous.

Peak container cgroup memory was **80.32 GiB** against a 112Gi limit. Both 3090s peaked near 22.8GiB used according to sampled NVML data. OOM-kill counters remained zero. The cgroup peak includes startup and the preflight fixture; sampled case memory and lifetime peaks are distinguished in the artifacts.

## Retrieval

A separate natural-EOS request contained 261,880 templated prompt tokens. It returned strict JSON with **4/4** expected values: three random archive records and `NOT_FOUND` for a fourth, absent key. Its first content arrived after 245.3 seconds. Record positions are native-token-counted within the document, not character percentages:

| Record | Document token offset | Document-relative depth |
| --- | ---: | ---: |
| 1 | 26,167 / 261,758 | 10.00% |
| 2 | 130,865 / 261,758 | 49.99% |
| 3 | 235,563 / 261,758 | 89.99% |

## Gateway And Normal-Cache Check

After restoring normal prefix caching, the same 261880-token retrieval request
was replayed through LiteLLM as `Maya-M` using the actual Hermes virtual key.
It again returned all three exact values and `NOT_FOUND`, with zero reused
prompt tokens: first content at 269.1 seconds, total 273.6 seconds. This is a
replay of the same archive, not another independent quality sample. The
post-check container lifetime memory peak was 80.70 GiB, with zero OOM kills.
See the [gateway artifact](resources/manual/maya-m/bench/results/maya-262k-20261116T083345Z/gateway-result.json).

The model-caps publisher reports `max_input_tokens=262144` and
`max_output_tokens=8192`. Paseo's persisted and live catalogues retain the
`Maya-M` provider ID and its four thinking choices. The native model is loaded
at 262144 with the benchmark-only cache bypass removed.

## Method And Scope

- Same 262144-token runtime capacity for every rung. The 32K row is a prompt-length comparison, not a paired test of different configured capacities.
- Maya 1.1.64, source `d93d1499021b98a39bede20d33368907f1ea4ad8`, pinned Zot image `sha256:5e82c10d8b7e042f40eac275fcf9ced54f583faacbc63c0ed352b764ab06763c`; retained upstream Maya-M mixed-quant pack and MTP drafting.
- Both Iggy RTX 3090s, low-priority exclusive allocation, 20-CPU request, 112Gi container memory, retained 90Gi RAM-tier configuration. Other lanes were not retargeted or resumed.
- `MAYA_GLM_NO_REUSE=1` disables native snapshots, slots and checkpoint reuse. Both usage and engine timing cache counters were zero for every measured request.
- Full chat-template token counting used native `/api/tokens`; actual usage had to match. Largest prompt plus 256 generated tokens plus the native 8-token admission margin stayed within 262144.
- Throughput uses thinking off, temperature zero, `ignore_eos:true`, loop guard off, exactly 256 output tokens and `finish_reason=length`. The separate quality request uses natural EOS; forced continuations are not scored for quality.
- TTFT starts at HTTP submission and stops at the first nonempty content delta, not the initial assistant-role chunk. Prefill/decode rates use the native engine clocks.
- Synthetic varied archive prose, one pilot per rung, one three-depth retrieval trial. This establishes this run's capacity/latency and exact-match behavior, not general long-context accuracy, a representative coding-workload rate, statistical reliability, sustained concurrency or 1M-token performance.
- Harness and reproducibility procedure: [benchmark README](resources/manual/maya-m/bench/README.md). Full request payloads and their SHA256 fingerprints remain on the retained Maya PVC under `/model/maya-work/benchmarks/maya-262k-20261116T083345Z`.
