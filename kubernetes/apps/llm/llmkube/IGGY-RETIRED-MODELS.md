# Iggy model lanes on ice

The Iggy Qwen 27B (FP8 and AWQ), Muse Glimmer llama.cpp, and Maya-M lanes
are retired from the deployed resource graph. Their serving recipes remain in
`resources/` for reference, but are not registered in its `kustomization.yaml`.
Do not re-register them as routine cleanup.

The Deleuze Radiance fleet is independent and remains deployed. In particular,
`glimmer-deleuze` is not the retired Iggy `Muse-Glimmer-30B` route.

## Cold storage

The shared, Retain-policy `llm-model-archive` PV/PVC points to
`nuglab-storage.internal:/volume1/nuglab/Models`. Paths relative to that export:

| Artifact | NAS directory |
| --- | --- |
| Qwen 27B FP8 checkpoint | `llmkube/qwen-3-8-fp8` |
| Qwen 27B AWQ INT4 checkpoint | `llmkube/qwen-3-8-awq-int4` |
| Muse abliterated text, projector, DFlash | `llmkube/muse-glimmer-30b-abliterated` |
| Maya source GGUFs, generated pack, tokenizer, projector | `llmkube/glm-5.3-flash-maya-m/Maya-M` |
| Maya retained configuration, calibration, benchmark evidence | `llmkube/glm-5.3-flash-maya-m/maya-work` |

The retirement verification writes
`llmkube/iggy-retirement-20261120-verified.json` only after checksum verification
finishes. It records every verified file's path, size, SHA256, copied paths, and
completion time. Maya source shards and AWQ shards are checked against the
pinned upstream hashes; FP8 and Muse archive files are compared against the
retained local copies. Newly archived Maya assets are verified after copying.

## Data retention and deployment scope

No local storage is deleted as part of retirement. `muse-iggy`, `maya-m-iggy`,
`muse-kristeva`, `qwen38-awq-stage`, and the shared `llmkube-model-cache` claims
remain registered. Keeping a claim does not deploy an inference workload.
`qwen38-awq-stage-storage.yaml` preserves the existing scratch claim while the
old combined staging Job manifest is unregistered.

The pruned objects are the four InferenceServices, four Models, Maya's generated
start ConfigMap, Maya's routes/OIDC/network policies, and the completed Qwen AWQ
staging Job. No PV or PVC belongs in the prune set.

The explicit retired LiteLLM aliases and their key scopes are removed. `coder`
and `worker` remain role aliases but use the deployed FlashNext Radiance backend;
Hermes vision uses the deployed `heretic-deleuze` route. Restoration requires a
new, deliberate deployment and matching catalogue/key-scope updates; restoring
only a manifest or only an alias is insufficient.
