---
name: gpu-llm-serving
description: "Deploy and validate GPU-hosted LLM services safely."
version: 0.1.0
author: Tim, Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [kubernetes, llm, gpu, llama-cpp, scheduling]
    related_skills: []
---

# GPU LLM Serving Skill

Use this for adding, replacing, or tuning a GPU-backed LLM service in Kubernetes when another workload competes for the same node or GPU. It covers repository configuration, model-format/runtime checks, scheduling policy, cold-tier staging, and safe rollout. It does not authorize deleting a live service, evicting a game session, or changing a deployment before the user confirms the sequence.

## When to Use

- Add or replace a llama.cpp, vLLM, or similar GPU inference lane.
- Make an inference workload yield to interactive GPU workloads.
- Validate model files, quantization, context/KV sizing, and cluster scheduling before rollout.
- Do not use for a purely CPU model or a generic application deployment with no GPU/resource contention.

## Prerequisites

- Read repository instructions and the jj workflow before editing or publishing.
- Identify the cluster context explicitly with `KUBECONFIG`; never assume the current context. On this workstation there is no `~/.kube/config` — export `KUBECONFIG=~/git/cogito-gitonly/kubeconfig` and run kubectl through mise (`mise exec kubectl@<pinned> -- kubectl ...`); a bare kubectl falls back to localhost:8080 and connection-refused.
- Have read-only access to the rendered manifests, CRDs, relevant pods, PVCs/PVs, node labels, and priority classes.
- Know whether the requested change permits stopping, evicting, archiving, or rescheduling an existing workload.

## Procedure

1. Establish a read-only baseline. Use `terminal` to inspect `jj status`, the relevant manifests, rendered configuration, existing pods, PVC/PV bindings, node selectors, priority classes, and the current interactive workload. Completion criterion: the target service, model source, node, GPU owner, and consumers are identified without changing cluster or repository state.

2. Discover existing GPU lanes before proposing changes. Pin `KUBECONFIG`, inspect node labels/capacity and device-plugin resources, then filter pods by `spec.nodeName` and print each container's image, arguments, GPU request, phase, and start time. Trace the owning service/InferenceService and catalogue alias. For embedding or reranking lanes, inspect runtime mode flags and test the native endpoint (`/v1/embeddings` or `/v1/rerank`) from inside the pod; record vector dimensions, response shape, and a minimal usage/latency signal. Completion criterion: the hardware identity, actual workload, exposed API, and current activity are verified from live objects rather than inferred from filenames or labels alone.

3. Separate model comparison from deployment validation. For a newly announced model, use the primary model card or vendor documentation for parameterization, modalities, dimensions, license, and published scores; use secondary reporting only to locate artifacts or identify claims to verify. Mark benchmark comparisons as directional when datasets, pooling, prompts, or evaluation versions differ. Match the consumer's modality and protocol before comparing quality: a text embedding endpoint cannot replace a paired image-text/CLIP model, and a model's multimodal weights do not prove that the target application supports an external embedding API. Do not claim a multimodal serving path is ready merely because a GGUF exists: verify each encoder, runtime mode, and API operation on the target backend. Completion criterion: the recommendation distinguishes observed local behavior, authoritative model facts, and unverified or non-comparable claims.

4. Trace the service end to end before editing. Locate the model catalogue alias, backend object, runtime arguments, model mount, router/fallback entries, credential scopes, and any consumer environment references. Inventory consumers from live workloads and repository configuration rather than assuming the most visible application uses the lane; distinguish direct consumers, same-repo CPU replicas, and unrelated model-serving pods. Run the repository catalogue validator before and after changes. Completion criterion: every name and service reference has a known definition and the planned alias has a documented fallback/priority policy.

5. Verify model/runtime compatibility from authoritative artifacts. Inspect the actual GGUF or model metadata for architecture, context length, layer pattern, KV-head structure, quantization type, and file size; inspect the pinned serving image or its release metadata for architecture support. Do not infer support from the model name. Completion criterion: the selected runtime, image digest, quantization, context, and required flags are justified by observed metadata.

6. Size GPU and host resources before rollout. Calculate weights plus KV cache for the intended context and KV type, accounting for sliding-window layers and replicas/parallel slots. Compare the estimate with allocatable GPU memory and node host-memory constraints. Start with a conservative context and benchmark upward only when the user requested tuning. Completion criterion: requests/limits and context settings fit the node with a stated safety margin or an explicit test plan.

7. Choose the model source deliberately. Prefer the established cold-tier/NFS archive mount pattern when weights are large or the existing shared cache is pinned to another node; use a local PVC only when its node affinity and lifecycle are intentional. Preserve an old YAML manifest when removing an active deployment, but do not confuse retaining YAML with retaining a live workload. Completion criterion: the source path resolves in the same way as a known-good service and its storage lifecycle is understood.

8. Encode scheduling policy explicitly. Give interactive game/session pods a higher `PriorityClass` with `PreemptLowerPriority`, and give inference pods a lower class. Inspect every game template, not just the operator deployment: an App template without `priorityClassName` will not preempt a lower-priority inference pod. Completion criterion: the scheduler policy is visible on the actual generated pods and the intended preemption direction is one-way.

9. Separate analysis from destructive execution. If an existing service is Pending because an interactive session owns the GPU, do not delete, scale down, evict, archive, or recycle it merely to make room. Report the live owner and wait for explicit sequencing approval. Completion criterion: all changes are either read-only or covered by the user's confirmed rollout order.

10. Edit the smallest set of manifests, then render and validate. Preserve unrelated user changes. Check catalogue consistency, YAML/Kustomize rendering, image digests, service names, mounts, probes, resource requests, and generated priority classes. Completion criterion: the diff contains only the requested service/scheduling/storage changes and all local validators pass.

11. Roll out in reversible stages. Apply the priority/template fix before relying on preemption; stage or verify weights before removing the old lane; deploy with startup/readiness probes that match the runtime; reconcile the Flux source and owning Kustomizations explicitly; then inspect pod events, GPU allocation, logs, `/health`, and the OpenAI-compatible endpoint. Completion criterion: the new backend is Ready, serves a minimal request, and the old backend is removed only if explicitly authorized. Do not report rollout success while the pod is merely Running or the InferenceService is still Creating.

12. Verify the user-facing path. Test the catalogue alias through LiteLLM, confirm fallback behavior and scoped credentials, and confirm that an interactive game pod can reclaim the GPU under the declared policy. Completion criterion: backend, router, fallback, and preemption checks all pass and the final `jj diff` accounts for every file.

13. Close out storage and validation asynchronously but explicitly. Keep any source PVC protected by a verifier pod while a large archive copy is checked; compare every expected file's size before cleanup. If the user explicitly accepts the residual corruption risk, document that checksum verification was waived and proceed; do not silently substitute a stronger gate than the user chose. Release the claim/PV before touching its node-local path, then use a privileged, exact-path-guarded cleanup pod and verify the target disappeared while sibling directories remain. Use bounded jobs and monitor them rather than assuming a copy command succeeded.

## Quick Reference

- Baseline: `terminal(command="KUBECONFIG=... kubectl ... get ...")`
- Render: `terminal(command="kubectl kustomize ...")`
- Validate: `terminal(command="python3 scripts/validate-llm-catalogue.py")`
- Inspect generated pod args/mounts: `terminal(command="kubectl ... get pod ... -o json")`
- Inspect model metadata: use a small `terminal` Python parser or a trusted model-tool command; record observed values, not guesses.
- Final repo check: `terminal(command="jj status && jj diff")`

## Pitfalls

- Never equate a Pending old pod with an active serving deployment; inspect pod phase, events, and current consumers before changing it.
- Never assume a game operator's high priority propagates into App-created session pods; inspect the generated pod spec because templates commonly override or omit it.
- Never place a model on a node-pinned shared cache without checking PV/PVC affinity; the model may be unreachable from the intended node even when the catalogue is correct.
- Never treat a configured `gpuMemory` field as a scheduler reservation unless the installed CRD/operator documents that behavior; inspect the CRD schema and generated pod resources.
- Never raise context solely because the model advertises a large maximum; KV growth, parallel slots, and quantization determine whether the GPU can actually sustain it.
- Never assume a quantized release is quantization-aware trained — names like "KQuant" are post-training k-quants, not QAT; a base repo publishing bf16 weights plus a card that measures degradation after compression is the PTQ signature. Before recommending a larger quant, read the model card's per-build degradation table: the delta between published builds is the entire quality headroom, and paying for it by dropping the speculative drafter (tens of percent throughput) is usually a losing trade.
- Never start destructive rollout steps while the user is actively gaming or has asked to hold; keep the read-only analysis and the execution phase separate. After approval, delete only an exact, previously released host-path directory through a guard-checked privileged pod, then list the hostpath root to prove sibling workloads were untouched.
- Never release a large source PVC after a copy reports success alone; interrupted in-cluster transfers can leave hidden temporary files or partial shards, so compare every expected file's size first. Honor an explicit user decision to waive full checksums, recording the residual risk and making the archive re-download path clear.
- Never call a rollout complete from pod phase alone; model loading can leave a pod Running while readiness and the service phase remain unresolved.
- Never infer GPU ownership from a node label alone; device-plugin capacity, pod resource requests, generated pod arguments, and the live API identify what is actually consuming the device.
- Never report a node's physical GPU count from allocatable `nvidia.com/gpu` — a time-sliced device plugin inflates it by `nvidia.com/gpu.replicas`. Read the GFD labels `nvidia.com/gpu.count`, `nvidia.com/gpu.replicas`, `nvidia.com/gpu.sharing-strategy`, and `nvidia.com/gpu.product`/`memory` before stating hardware, and note that a pod requesting N slices of a replicas-N GPU occupies the whole card alone.
- Never validate an embedding or reranking deployment only through a generic chat endpoint; call its native operation and inspect dimensions or scores because compatibility shims can hide a misconfigured mode.
- Never compare model benchmark numbers as if they were interchangeable; prompt format, pooling, dataset version, and modality coverage can change the ranking even when the metric name matches.
- Never describe an untested multimodal runtime as deployable; a weight artifact can omit optional encoders or lack an API path for them, so probe every required modality on the selected serving stack.
- Never assume a prominent application is the consumer of a shared embedding lane; trace its deployment environment, service URL, and model configuration, because applications such as photo managers may use an in-process CLIP/OpenVINO model and never call the cluster's text-embedding alias.
- Never substitute a text-only embedding model for a paired image-text search model; shared vector spaces require compatible image and query encoders, and replacing one side invalidates existing indexes even when both APIs return vectors.

## Verification

- Repository validator passes with no unresolved model, backend, fallback, scope, or context errors.
- Rendered manifests contain the intended image digest, model path, arguments, resources, probes, and priority class.
- The model file is readable from the mounted path and the runtime reports the expected architecture.
- The pod is Ready, GPU memory is within the estimate, and a minimal inference request succeeds.
- The LiteLLM alias resolves to the intended backend and its fallback remains within the same model/host policy.
- An interactive session has the higher priority and can reclaim the node according to the declared preemption policy.
