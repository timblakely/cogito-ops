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

`37` is retained: it gains 4.9% prefill throughput over the control while
preserving 4.4 GiB on the constrained GPU. `36` is 2.3% faster in prefill but
its 2.1 GiB free headroom leaves only 101 MiB above the hard gate and its decode
rate is slightly lower. No context or KV-cache capacity was reduced.

At the retained 37-layer placement the unallocated GPU memory is approximately
21.4 GiB total (17.0 + 4.4 GiB). It is not safe to turn that into another full
143,360-token Q8 KV slot: one slot was previously estimated at at least about
6.3 GiB plus hybrid-attention/runtime overhead and capacity is unevenly split.
Keep one slot until a dedicated multi-slot fit/throughput test is run.
