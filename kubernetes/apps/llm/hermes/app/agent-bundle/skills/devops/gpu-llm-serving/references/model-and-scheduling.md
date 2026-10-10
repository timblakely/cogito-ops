# Model and Scheduling Checks

## Model metadata checklist

Record these values from the actual artifact or runtime metadata:

- architecture and tokenizer/chat-template support
- file type and exact weight size
- context length
- layer count and sliding-window pattern
- attention head and KV-head counts, key/value dimensions
- quantization type for weights and KV cache
- image/projector files when multimodal
- serving image tag and immutable digest

For a rough KV estimate, calculate full-attention layers and sliding-window layers separately. Multiply tokens by the per-token K+V bytes for each tier, cap sliding-window storage at the window size, then multiply for replicas or parallel sequences. Treat the result as a sizing estimate, not proof of fit; verify with the real runtime. On sliding-window-heavy architectures, dropping a parallel slot frees very little KV — the slot-reduction lever is much weaker than intuition suggests, so budget the upgrade from weights + compute buffers, not freed KV.

When parsing GGUF headers for these numbers, read at least an 8 MB head window: the KV-metadata section contains a giant tokenizer/tokens array that truncates smaller reads (a 2 MB window dies mid-section). Prefer reading the live pod's mounted file or the NFS archive over re-downloading.

## Quant upgrade evaluation

Before spending VRAM on a larger quant:

1. Price the upside first: the model card's per-build degradation table (full precision vs each quantized build) is the maximum the upgrade can buy. If the delta is well under a benchmark point, say so and stop.
2. Determine PTQ vs QAT: bf16 weights in the base repo + "no bf16 GGUF published" + after-the-fact degradation claims means post-training quantization, so quality rises monotonically and mildly with quant size — no trained-in Q4 sweet spot that would make larger quants unusually rewarding or pointless.
3. Enumerate the live VRAM breakdown (weights, drafter, mmproj, KV, compute buffers) from pod metrics plus header math, then check whether the bigger build fits only by dropping a companion — a speculative-decoding drafter is usually worth more than a sub-1% quant gain.
4. Check the upstream repo's file listing, not just the local archive: higher-quality builds are often published but never synced to the cold tier. Find the archive mount via another pod's `volumeMounts` (e.g. an NFS `/model-source`) rather than guessing paths.

## Scheduling checklist

Inspect both declared and generated objects:

1. `PriorityClass` values and `PreemptionPolicy`.
2. Inference pod `priorityClassName`, node selector, GPU request, memory request, and host-memory/offload settings.
3. Game App template `priorityClassName`, node selector, and generated session pod.
4. Pod events for `Insufficient nvidia.com/gpu`, affinity mismatch, memory pressure, or preemption.
5. Current GPU owner and session age before any rollout action.

Use a higher numeric priority for latency-sensitive interactive workloads and a lower one for opportunistic inference. Confirm the lower-priority inference pod is actually schedulable for preemption; a priority class defined only in an operator deployment or unused template has no effect.

## Safe sequencing

- Read-only baseline and render first.
- Fix generated game-pod priority before testing preemption.
- Stage/verify model storage before removing the old service.
- Deploy and health-check the replacement; wait for the controller's Ready condition, not just a Running pod.
- Remove or archive the old active deployment only after explicit authorization and after checking whether a live user session owns the GPU.

## Large archive verification

For a large model PVC that must be released, run the archive transfer as a bounded in-cluster Job with a memory limit appropriate to the copy tool. Prefer a simple streaming copy when rsync's memory use is not bounded; a killed rsync can leave dot-prefixed temporary shards that inflate the destination. Before deleting the source:

1. Keep a verifier pod mounted on both source and destination so PVC protection prevents premature cleanup.
2. Compare the expected file count, names, and byte sizes one-for-one; inspect for hidden transfer temporary files.
3. Hash every expected shard against its destination counterpart and require an explicit all-files pass.
4. Remove only known temporary files after verification, then release the PVC/PV and source host path in a separate, authorized step.

Do not treat matching directory totals or a successful Job exit as sufficient: directory accounting and interrupted transfers can conceal incomplete model shards.
