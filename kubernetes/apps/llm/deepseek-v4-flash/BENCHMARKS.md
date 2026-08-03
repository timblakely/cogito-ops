# DeepSeek V4 Flash placement benchmark

Run: 2026-08-03. The model retains its working 143,360-token, one-slot Q8_0
KV cache. Measurements use the first request in the retained Pi capture
(`sha256:36f533004ae7055dd5ed20662ec755eec2f426862479493d1181bd51e2e8e859`),
through the production proxy, with a 128-token completion cap. llama.cpp
rendered 10,330 prompt tokens after its chat/tool template (the captured
surrogate is labelled 18,067 tokens). Server prompt/decode timing is the
reproducible comparison metric. The final retained-37 clean-client run returned
HTTP 200 with TTFT **265.097 s** and 125 completion tokens in 273.955 s
(14.112 client-observed completion tok/s).

| `n_cpu_moe` | Placement | PP tok/s | Decode tok/s | GPU0 used/free MiB | GPU1 used/free MiB | Host RSS GiB | Result |
| ---: | --- | ---: | ---: | --- | --- | ---: | --- |
| 39 | layer | 37.56 | 11.16 | 6,744 / 17,383 | 14,808 / 9,317 | 93.8 | exact control; Stable |
| 37 | layer | 39.39 | 11.12 | 6,734 / 17,393 | 19,598 / 4,527 | 89.2 | Stable; selected |
| 36 | layer | 40.31 | 11.07 | 6,730 / 17,397 | 21,976 / 2,149 | 86.8 | Stable, but only 101 MiB above the 2 GiB safety gate |
| 35 | layer | — | — | 3,582 / 20,545 | 23,378 / 747 | — | rejected: GPU1 safety/headroom failure |
| 35 | row | — | — | — | — | — | rejected: unsupported llama.cpp row split for this model |
| fitter (`--fit-target 1024,1024`) | layer | 80.66 | 13.73 | 22,432 / 1,695 | 22,676 / 1,449 | 72.8 | Stable; retained |

The automatic fitter is retained. It uses `--threads 12`, `--threads-batch 22`,
`--fit on`, `--fit-ctx 143360`, `--fit-target 1024,1024`, `--split-mode layer`,
`--batch-size 4096`, and `--ubatch-size 1024`; it deliberately has no
`--n-cpu-moe` override. The one-GiB-per-GPU safety floor passed (1,695 MiB and
1,449 MiB free). No context or KV-cache capacity was reduced.

The final clean-client run was performed after a controlled DeepSeek-only
restart, so its slot had zero cached prompt tokens. It returned HTTP 200 with
85 completion tokens in 134.345 s. True TTFT, measured to the first generated
content/reasoning/tool-call delta rather than llama.cpp's earlier progress SSE
event, was **128.154 s**. Client-observed decode was **13.73 tok/s**; llama.cpp
reported **80.66 prompt tok/s** and **13.73 decode tok/s**. The first SSE event
arrived at 30.081 s and must not be interpreted as TTFT. Against the retained
37-layer control, the fitter more than doubles server prompt throughput (80.66
vs 39.39 tok/s) and cuts the comparable clean-client TTFT from 265.097 s to
128.154 s.

At the retained 37-layer placement the unallocated GPU memory is approximately
21.4 GiB total (17.0 + 4.4 GiB). It is not safe to turn that into another full
143,360-token Q8 KV slot: one slot was previously estimated at at least about
6.3 GiB plus hybrid-attention/runtime overhead and capacity is unevenly split.
Keep one slot until a dedicated multi-slot fit/throughput test is run.
