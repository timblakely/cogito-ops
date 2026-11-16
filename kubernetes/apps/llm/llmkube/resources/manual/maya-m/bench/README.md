# Native Maya 262144-token context pilot

Run this harness inside `llm/maya-m` on Iggy, not on the workstation. It calls
only the Pod-local native API. Enable `MAYA_GLM_NO_REUSE=1` on the **engine**
before running; `cache_prompt:false` does not disable native Maya prefix reuse.
Remove the benchmark-only environment setting after finishing.

The default ladder uses full templated prompt targets 32504, 65272, 130808,
261880. Each reserves 256 output tokens plus the server's 8-token admission
margin. The exact counter may land up to 16 tokens below target; every request
is recounted and checked against native usage. No prompt is silently truncated.

Each performance request forces exactly 256 generated tokens with
`ignore_eos:true`, `loop_guard:false`, thinking off and temperature zero.
Final usage and native timings must both show zero reused tokens. Initial
assistant-role chunks do not count as first-token latency.

A separate natural-EOS request at the largest target measures retrieval of
three random records near 10/50/90 percent document-token depth and an absent-key
control. Throughput rows' forced continuations are not scored as quality tests.
The corpus is synthetic varied archive prose, not a representative coding
workload. One pilot per rung is a feasibility measurement, not a statistical
quality estimate or sustained-concurrency benchmark.

Example after copying the script into the existing Pod:

```sh
kubectl -n llm exec deploy/maya-m -- python3 /model/maya-work/benchmark-262k.py \
  --out /model/maya-work/benchmarks/UNIQUE_RUN_ID --revision EXACT_JJ_COMMIT
```

Use `--targets 1024` first as an end-to-end fixture. The output directory must
not already exist. Requests, SHA256 fingerprints, native responses, timestamps,
CPU/RSS/thread observations, cgroup memory/OOM counters and both GPU UUIDs are
retained under that directory. `latest.json` is an atomic progress snapshot;
`summary.json` is written only after every requested case completes.

The pilot is sequential, with bounded per-request timeouts and a four-hour
inference wall budget. Stop on invalid token accounting, cache reuse, incomplete
fixed-length decode, OOM or native API failure. A retrieval miss is a measured
quality result, not a reason to erase successful performance measurements.
Copy result artifacts back and check their run ID before publishing a verdict.
