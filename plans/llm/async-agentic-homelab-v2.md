# Async Agentic Homelab: Matrix-driven planning and execution on a Talos Kubernetes cluster

**Status:** design proposal, v2 (2026-09-13). Superseded by `async-agentic-homelab-v3.md` the same day; retained for the trail.
**Audience:** a reviewer with no prior context. Everything needed is in this document; unverified items are `[VERIFY]`, contestable choices are `[DECISION]`, and things observed on the live cluster on 2026-09-13 are `[OBSERVED]`.

---

## Changelog v1 → v2

v1 was written without reading `foreman_migration_pathway.md`, `matrix_development_coordination.md`, or the deployed manifests. A repo and live-cluster audit on 2026-09-13 found that most of v1's "new" system already exists in a different shape, and that the cluster had faults that would stop any plan from executing. v2 is a delta from what is deployed, not a green-field build.

| Area | v1 | v2 |
|---|---|---|
| The "one new component" | `planner-gateway`: new appservice + `PlanningSession` CRD | **Adapt `services/matrix-coordinator`** (exists, 3.2k lines incl. tests, SQLite state, durable outbox). Analysis in §5. |
| Foreman | Owner-written scheduler | **Upstream `defilantech/llmkube` Foreman v0.9.25**; kept, with llmkube. It already owns execution (coder → gate → two-reviewer quorum → PR). |
| Execution coordinator | Luna (cloud) runs a step DAG over an integration branch | **No Luna in the execution path.** Foreman `Workload` per deliverable, sequenced deterministically by the coordinator; escalation table (§8.4) implemented in code. Luna reserved for direct sessions (§9). |
| Muse Glimmer serving | vLLM 0.29 + custom int8 embed/head requant; llama.cpp as fallback | **llama.cpp, two slots** (`parallelSlots: 2`, 2 × 131k). Comparison in §3.2. |
| Qwen 3.8 serving | syv-ai stack in `SPEC=mtp` with 3 seats | **syv-ai stack, made to work as deployed** (`SERVED_MODEL_NAME` fix); `SPEC=dflash2` now, MTP is a measured switch. |
| flashnext (CPU Qwen3.8-Flash-Next lane) | Not mentioned | **Removed for now.** Frees 76 Gi of iggy RAM and un-sticks Flux. |
| 5070 Ti node | In the hardware table | **Ignored.** Not in the cluster. |
| LiteLLM | Illustrative aliases with cloud fallbacks | Real catalogue; **no fallbacks by design**; Foreman bypasses LiteLLM; fixes listed in §3.3. |
| E2EE in agent rooms | Off | **On** (already works; Synapse already runs encrypted appservices). |
| Session state | CRD | **SQLite** (already restart-safe; survived 147 involuntary restarts). |
| Plan storage | `agent-plans` git repo | **SQLite versions + hashed GitHub plan issue** (already the audit trail). |
| Notifications | To build | **Done** (ntfy 2.27 as UnifiedPush distributor and Matrix push gateway). Add mention gating. |
| Build order | 0–7, greenfield | **R0 cluster repair first**, then deltas (§13). |

---

## 0. Executive summary

The owner runs a Talos/Flux Kubernetes cluster with two RTX 3090s on one node, a Synapse homeserver used from Android via Commet, upstream llmkube + Foreman for agent scheduling, a LiteLLM catalogue fronting local and ChatGPT-subscription models, and an existing Matrix coordinator service that already drives an Astra planning loop with local Muse scouts and hands approved deliverables to Foreman. The owner has a newborn and operates from a phone in short bursts.

Goal, unchanged from v1: an asynchronous, notification-driven agentic system where Astra plans with local scouts and asks questions in Matrix; the owner approves from the phone; Foreman executes; the owner is pinged only on state transitions; and a direct coding session can be opened from Matrix without SSH.

What v2 asserts:

1. **Repair before building.** Two live faults block execution today (§1.5): both agent Deployments restart every 30 minutes, and Foreman's coder/reviewer cannot reach Qwen because of a model-id mismatch. Both are one-line GitOps fixes.
2. **Adapt the coordinator, do not rewrite it.** The gap between the deployed coordinator and v1's gateway is roughly 1.2k lines of UI and control-flow work on top of 3.2k lines of tested plumbing that a rewrite would have to reproduce first (§5).
3. **Serving is settled on this hardware.** Qwen 3.8-27B on the syv-ai vLLM 0.28 image is the only single-card path with acceptable speed; Muse Glimmer 30B on llama.cpp gets two full-context slots, speculative decoding, and vision in host RAM, none of which vLLM can give on a 24 GB Ampere card (§3).
4. **Foreman is the execution owner.** The plan's deliverables become Foreman Workloads; the coordinator sequences them and applies the escalation table. Adding a paid coordinator model above Foreman has no named job today.

---

## 1. Context for the reviewer

### 1.1 The owner and the operating constraint

Unchanged from v1: Android phone, short attention windows, resume after days away, one thumb. Simplify the interaction surface, not the infrastructure.

### 1.2 Existing infrastructure (corrected inventory)

All rows exist today. Versions are what is deployed at repo commit `5c850664`.

| Component | What it is | Facts relevant to this design |
|---|---|---|
| **Talos cluster** | 5 nodes (`iggy`, `kristeva`, `nuc-1/2/3`), all control-plane, Kubernetes 1.34.2, Flux-managed from `timblakely/cogito-ops` (this repo). | iggy runs Talos v1.13.5, the rest v1.12.5 (deliberate after the DRA rollback; converge later). |
| **llmkube 0.9.25** | Operator for inference servers: `Model` and `InferenceService` CRDs, runtimes `llamacpp`, `vllm`, `generic`. | Runs the syv-ai image as `runtime: generic` and Muse as `runtime: llamacpp`. Has `rolloutPolicy.waitForIdle` (llama.cpp `/slots` aware), `parallelSlots`, `speculativeDecoding`, `reasoningBudget`. GPUs are UUID-bound via `NVIDIA_VISIBLE_DEVICES`, not the device plugin. |
| **Foreman 0.9.25** (upstream, `defilantech/llmkube`) | Agent scheduler. CRDs `Agent`, `AgenticTask`, `Workload`, `FleetNode`, `ModelProfile`, `AgentRelease`. Roles coder / verifier / reviewer / planner / worker. `Workload` runs a fixed pipeline per issue: coder → gate Job → reviewer(s) → PR. `AgenticTask kind: freeform` for read-only scouts. | Agents call InferenceServices **directly** (`provider: local`, `allowCloudProviders: false`); LiteLLM never sees worker traffic. Per-Agent `maxConcurrentTasks` is the seat control. Result contract is `submit_result` → `verdict GO/NO-GO + summary`, plus a transcript ConfigMap. Foreman does not plan across issues; that is the coordinator's job. |
| **LiteLLM 1.97.0** | Proxy with a GitOps catalogue (`kubernetes/apps/llm/litellm/app/models/`, `virtualkeys/`), validated by `scripts/validate-llm-catalogue.py`. | **No fallbacks anywhere, by decision** (the validator refuses one on `coordinator`). Cloud models are ChatGPT-subscription OAuth (`chatgpt/`) plus metered OpenAI and Moonshot. Currently on nuc-3. |
| **matrix-coordinator** (`services/matrix-coordinator`) | The existing planning gateway: maubot transport container + stdlib-Python coordinator container, SQLite schema v10 on a volsync-backed PVC. | Astra via Responses API with one `delegate_research` tool (≤4 scouts × ≤2 rounds), `!cogito plan/draft/revise/approve/status`, GitHub plan issue + sub-issues with native dependencies, one Foreman `Workload` per deliverable, two-reviewer quorum, SHA-pinned async squash merge. 45 unit tests. |
| **Synapse 1.160.0** | Homeserver on CNPG. | One appservice registered (Hookshot). MSC3202/MSC2409 already enabled, so encrypted appservices work. Push goes to ntfy. |
| **Rooms** (Terraform-managed) | Space `Agents`: `#agent-control`, `#agent-alerts`, `#agent-plans`, `#agent-runs`, `#project-cogito`. Space `Personal`. | All E2EE, invite-only. Members `@tim`, `@coordinator`, `@hermes`, `@agent-gitops`, `@hookshot`. Hookshot's GitHub connection for `cogito-ops` lives in `#agent-runs`. |
| **Commet** | Owner's Matrix client. | `[VERIFY]` `m.poll` rendering. |
| **ntfy 2.27** | Deployed in `observability`. | UnifiedPush distributor **and** Matrix push gateway; Synapse whitelists it. Working. |
| **Hookshot 7.4.4** | GitHub App 4906005 + generic webhooks. | PR/issue events to `#agent-runs`. |
| **Hermes** (`nousresearch/hermes-agent`) | Matrix agent bot `@hermes`, E2EE required, allowed user `@tim`. | Its LiteLLM provider config lived on the PVC and was orphaned when llm-proxy was removed; its virtual key has never been used. Candidate for §9. |
| **Reloader** | Cluster-wide, `autoReloadAll: true`. | Root cause of the restart loop (§1.5). |

### 1.3 Cluster hardware (as it is)

| Node | Hardware | Role |
|---|---|---|
| **iggy** | Ryzen 9, 128 GB DDR4, 2 × RTX 3090 24 GB (one on PCIe x16 `GPU-a598…`, one on x4 `GPU-787b…`), power-limited to 250 W by a DaemonSet. | Qwen on the x16 card, Muse on the x4 card. Foreman agent, gate cache, model cache (450 Gi hostpath). After flashnext removal: ~40 Gi RAM requests instead of ~124 Gi. |
| **kristeva** | Dual Xeon, 128 GB DDR3, Intel Arc A380. | `bge-m3` embedder, `bge-reranker-v2-m3`, `vision-cpu` (Qwen3.5-9B VLM). Always on. |
| **nuc-1/2/3** | Meteor Lake NUCs, Thunderbolt ring. | Ceph, Qdrant, LiteLLM, Matrix, coordinator, Hookshot, immich. No LLM serving. |

There is no 5070 Ti node. The gaming node is a parked Wave 4 item and is out of scope for this document.

### 1.4 Decisions already made (read these before objecting)

From `foreman_migration_pathway.md` and `matrix_development_coordination.md`, both "complete":

- Matrix thread = plan-review object; GitHub issue = accepted-work object; PRs carry code only. (v1 §7 rediscovered this.)
- Foreman replaced the custom Argo execution path outright; no parallel path, Git is the rollback.
- Quorum auto-merge: two distinct reviewer Agents must return GO against the final coder SHA; merge is SHA-pinned and async.
- Astra (`planner` alias) delegates to local scouts; no paid fallback; failures block visibly.
- Room-level notification policy: mute `#agent-runs`, keep the project room loud.

From `plans/llm/plan.md` (locked): coordinator pattern, no autorouting; no cross-model proxy fallbacks (LiteLLM does not re-check key scope on fallback); GLM 5.3 skipped; Kimi K3 is `reviewer-escalated` only.

From this revision:

- `[DECISION]` flashnext is removed from serving for now. Weights stay on the `flashnext-weights` PVC (93 GiB + 2.4 GiB draft head) until the D4 lane is formally retired.
- `[DECISION]` The 5070 Ti node is ignored.
- `[DECISION]` llmkube + Foreman stay. No new scheduler, no broker MCP server as a separate process.
- `[DECISION]` The syv-ai Qwen image is the Qwen lane. It is the only measured single-card path at acceptable speed (126 tok/s C1 DFlash2, 118 MTP, per the syv-ai README; the repo's own GGUF single-card result was 35 tok/s).
- `[DECISION]` Muse gets two slots on llama.cpp (§3.2).
- `[DECISION]` E2EE stays on. SQLite stays. `matrix-coordinator` is adapted, not rewritten (§5).

### 1.5 Cluster repair list `[OBSERVED 2026-09-13]`

These are prerequisites, not milestones. Each is a GitOps change; none needs new code.

| # | Fault | Evidence | Fix |
|---|---|---|---|
| **R1** | `foreman-agent` and `matrix-coordinator` Deployments roll every 30 min. Each roll drains the FleetNode, expires in-flight scout claims (tasks terminal-fail after 3 expiries), and re-creates Jobs for every AgenticTask in the namespace, including ones that succeeded a day earlier. | `foreman-agent` at revision 76 and `matrix-coordinator` at 147; new ReplicaSets at :25 and :55 every hour, matching `refreshInterval: 30m` on the `GithubAccessToken`-generated secrets. Reloader `autoReloadAll: true`. | Annotate both Deployments `reloader.stakater.com/auto: "false"`. matrix-coordinator: `controllers.coordinator.annotations` in its HelmRelease (it already re-reads the token from the mounted file per request, `github.py:64-72`). foreman-agent: the Foreman chart exposes only `podAnnotations`, so add a kustomize patch on `Deployment/foreman-agent`. `[VERIFY]` after one hour that the long-lived foreman-agent process does not itself use the now-stale `GITHUB_TOKEN` env (coder Jobs get a fresh copy at Job creation, so they are unaffected). If it does, mount the token as a file via `coderGitSecret` or switch to a fine-grained PAT with a constant value. |
| **R2** | Foreman coder and reviewer 404 on every turn: they request model `qwen3-8-27b`, the syv-ai server serves `qwen3.8-27b`. PR 43 fixed LiteLLM and missed Foreman. | `GET /v1/models` on the InferenceService → `["qwen3.8-27b"]`; Job logs: `The model qwen3-8-27b does not exist`. | Set `SERVED_MODEL_NAME=qwen3-8-27b` in the Qwen InferenceService env (documented syv-ai knob, default `qwen3.8-27b`). Revert the three LiteLLM backends (`Qwen/Qwen3.8-27B-W4A16`, `worker`, `planner-local`) from `openai/qwen3.8-27b` to `openai/qwen3-8-27b`. Result: InferenceService name, Foreman `spec.model`, `installedModels`, served id, and LiteLLM backend are one string. |
| **R3** | Flux `llm` Kustomization unhealthy since 2026-09-08 (`Job/flashnext-stage-v1` Failed); flashnext Deployment stuck 6 h on a RollingUpdate that cannot surge a 76 Gi pod on a 97 %-requested node. | `flux get ks -A`; `kubectl describe pod flashnext-…` → `Insufficient memory`. | Remove `flashnext.yaml` and `flashnext-stage.yaml` from `llmkube/resources/kustomization.yaml`; delete the Job, ConfigMap, `Model/flashnext`, `Model/flashnext-mtp`, `InferenceService/flashnext`; remove `litellm/app/models/flashnext.yaml` from the catalogue. Keep the PVC. |
| **R4** | Muse Agents override sampling: `cogito-planning-scout` `temperature: 0.2`, `cogito-reviewer-falsifier` `0.1`. Muse's model card requires 1.0 / 0.95 / 64. Two scouts ran 78 turns (1256 s and 1547 s) cycling `git remote -v`, `git worktree list`, `git branch --list`, `git status` 11–13 times each; `repeatedToolThreshold: 5` does not catch a four-command cycle. | Transcript ConfigMaps `foreman-transcript-plan-8dfd3c17…-research-r1-{1,2}`. | Delete the `temperature` field from both Muse Agents so the server's `--temp 1.0 --top-p 0.95 --top-k 64` apply. Raise scout `requestTurnTimeoutSeconds` from 300 to 900: a full `--reasoning-budget 16384` turn at ~40 tok/s is ~7 min. |
| **R5** | Every read-only scout is recorded `verdict: NO-GO, "model emitted GO but produced no diff"`: Foreman applies the coder no-diff gate to `freeform` tasks. | All 17 scout AgenticTasks. Coordinator already reads `result.extra.modelSummary` instead. | File upstream against llmkube. No local change; do not key any new logic on scout `verdict`. |
| **R6** | PR 22 (issue 21) can never merge: its Workload predates the falsifier Agent, so only one reviewer identity exists and the two-identity quorum is unreachable. Issue 21 and plan issue 23 stay open. | `gh pr list`, Workload `foreman-acceptance-21-v5`. | Merge or close by hand; delete the Workload. |
| **R7** | GPU lanes use `RollingUpdate`; a Muse spec change at 22:24 and 23:30 caused four scout `JOB-ERROR connection refused`. | AgenticTask log tails. | `rolloutPolicy: {waitForIdle: true, idleTimeoutSeconds: 900}` on both GPU InferenceServices. |

---

## 2. Roles and the conceptual hierarchy

```
You             set intent, answer questions, approve plans, approve code PRs.
Astra           decides WHAT. `planner` alias (gpt-6-astra via ChatGPT subscription, Responses API). No world tools.
Coordinator     deterministic code (matrix-coordinator): routes Matrix ↔ Astra ↔ Foreman ↔ GitHub, holds state, applies the escalation table.
Foreman         executes approved deliverables: coder → gate → two reviewers → PR, per issue. Deterministic pipeline.
Local workers   Qwen 3.8-27B (coder, reviewer) and Muse Glimmer 30B (planning scout, falsifier reviewer, vision).
Luna            reserved: direct coding sessions (§9) and, optionally, a "replan with failure context" turn. Not in the execution path.
```

Planning: `You ⇄ Matrix ⇄ coordinator ⇄ Astra`, with Astra's single `delegate_research` tool fanning out to Muse scouts through Foreman `AgenticTask`s. Astra has, conceptually, four tools: delegate research, read a scout summary (delivered back in the next turn), ask the owner (the `clarify`/`pushback` statuses), publish a plan (`ready` + `plan_markdown`). It never has shell, git or kubectl.

Implementation: `Approved plan → GitHub plan issue + ordered sub-issues → Foreman Workload per deliverable (serial) → PR → quorum → merge → next`. Astra is re-entered only on `REPLANNING` (§8.4).

---

## 3. Models and serving

### 3.1 Card 1 (PCIe x16): Qwen 3.8-27B on the syv-ai stack `[DECISION: this must work]`

Deployed as `InferenceService/qwen3-8-27b`, `runtime: generic`, image `ghcr.io/syv-ai/qwen38-27b-rtx3090@sha256:8382b699…` (vLLM 0.28.0 + patches), port 18020, env `SPEC=dflash2 PREFIX_CACHE=1 CTX=long MAX_SEQS=5 VISION=0`, 24 Gi host RAM, `[OBSERVED]` 22.9 GB VRAM in use.

Facts from the syv-ai README (fetched 2026-09-13) that matter here:

- Knobs are environment variables, one per boot: `SPEC=mtp|dflash2` (default `mtp`), `CTX=fast|long|huge` (64k bf16 KV / 150k int8 KV via FlashInfer / 240k+ KVarN), `MAX_SEQS` (admission, default 8), `PREFIX_CACHE=0|1`, `DFLASH_TOKENS` (7; 15 halves request slots), `VISION`, `TOOLS`, **`SERVED_MODEL_NAME`** (default `qwen3.8-27b`), `MODEL`, `EXTRA_ARGS`, `KV_MEM`, `INT8_ACT`.
- Single-user C1 decode at 250 W: MTP 118 tok/s, DFlash2 126, DFlash2 + `DFLASH_TOKENS=15` 133.
- Residency under concurrency, `SPEC=dflash2 CTX=fast`, distinct 4k prompts: C1 137 / C2 97 / C4 46 / C8 33 tok/s per stream, ~5 resident at C8 with preemption. MTP sustains 8 residents at 23 tok/s. Long prompts cost residency: at 16k prompts DFlash2 holds ~2, MTP ~4 (v1 §3.1 figures).
- `--mamba-cache-mode align` is required for DFlash2 recurrent-state persistence; prefix caching restores KV and mamba state losslessly.
- Batch mode: ~1,035 tok/s aggregate at 64 concurrent, no speculation.

**Mode `[DECISION]`:** keep `SPEC=dflash2 CTX=long MAX_SEQS=5 PREFIX_CACHE=1` as deployed. Today's Qwen demand from Foreman is coder (1) + reviewer (1) plus the occasional `planner-local` or `worker` key call; two residents at 16k covers it, and DFlash2 is the faster single stream. Switch to `SPEC=mtp` (an env change and a restart) when measured Qwen concurrency exceeds three long-context requests, which happens if scouts are ever moved to Qwen. Do not pre-empt that with v1's "3 seats" figure; it was not measured here.

**Foreman seats:** `cogito-coder` 1, `cogito-reviewer` 1 (unchanged). LiteLLM `worker` and `reviewer` virtual keys still say `maxParallelRequests: 8 # matches the backend's eight seats`; that comment dates from the retired FP8 TP2 lane. Set `worker` to 4 and fix the comment (§3.3).

### 3.2 Card 2 (PCIe x4): Muse Glimmer 30B, two slots `[DECISION]`

Deployed as `InferenceService/muse-glimmer-30b`, `runtime: llamacpp`, image `ghcr.io/ggml-org/llama.cpp:server-cuda` build **b10920** (latest release b10936, 2026-09-13), `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf`, DFlash drafter `dflash-Muse-Glimmer-30B-Q4_K_M.gguf` (`nDraftMax 15, pMin 0.75`), `mmproj` kept in host RAM (`--no-mmproj-offload`), `contextSize 131072`, KV `q8_0/q8_0`, `parallelSlots 1`, `--kv-unified`, `--reasoning-budget 16384`, sampling 1.0/0.95/64. `[OBSERVED]` 17.1 GB of 24.6 GB VRAM in use with one 131k slot; `/props` confirms `total_slots: 1`, `n_ctx: 131072`. Tool calls in ATEM format are parsed into OpenAI `tool_calls` by `--jinja` today: every scout transcript shows `bash`/`read_file`/`submit_result` calls round-tripping, which resolves v1's `[VERIFY]` #3.

**The two-slot question, at current stable releases:**

| | llama.cpp b10936 (server-cuda) | vLLM v0.29.0 (2026-09-09) |
|---|---|---|
| Weights that fit a 24 GB Ampere card | Q4_K_M GGUF, 17 GB on disk, **running today** | RedHatAI/aisquared/Vishva007 W4A16 keep embeddings, lm_head and the 1.8B vision tower in BF16: ~22 GB before KV. Requires the custom int8 embed/head requant v1 proposed (new checkpoint, llm-compressor run, cache-prime Job) to reach ~19 GB. Official NVFP4 is Blackwell-only. |
| Two slots at full context | `parallelSlots: 2` with `contextSize: 262144` and `--kv-unified` removed → 2 × 131,072 fixed. KV cost ≈ +1.1 GB at q8_0 (Muse KV ≈ 17 KB/token BF16, ~8.5 KB q8_0). Est. ~18.5 GB. Alternative: keep `--kv-unified` and `contextSize: 131072` with 2 slots → shared 131k pool, no extra VRAM, but one long scout can starve the other. | `--max-num-seqs 2 --max-model-len 65536` at best with the requant (2 × 64k); 2 × 128k needs vision dropped. |
| Speculative decoding | DFlash k-quant drafter, **on** today | DFlash head is 5.11 GB BF16; the vLLM recipe needs a second card even on a 32 GB 5090. None on this card. ~45 tok/s plain. |
| Vision | mmproj in host RAM, GPU memory untouched | Vision tower on-card in BF16 (3.6 GB) or dropped. |
| Reasoning control | `--reasoning-budget` + budget message, `--reasoning-preserve` | Prompt-line `Reasoning strength:` only; no hard budget. Empty-content truncation trap (v1 §3.2). |
| Tool/reasoning parsing | `--jinja` ATEM parsing, verified live | `--tool-call-parser muse_glimmer --reasoning-parser muse_glimmer`, fully typed `reasoning_content`; `tool_choice=required` unsupported. |
| Ampere history in this repo | Working | vLLM 0.25.1 crashed in the compressed-tensors quantised `lm_head` path on SM8.6 (`modes/split-b-vllm-nvfp4.yaml`). 0.29 unverified here. |
| Rollout / idle awareness | llmkube `rolloutPolicy.waitForIdle` reads `/slots` natively | Prometheus scrape of `vllm:num_requests_running` |
| What vLLM would win | | Continuous batching beyond 2 seats; per-request spec-decode metrics; typed reasoning field. None needed at two slots. |

**Decision:** llama.cpp, `parallelSlots: 2`, `contextSize: 262144`, drop `--kv-unified`, keep everything else. Bump the image to a b1093x release for parity with upstream fixes. `[VERIFY]` after rollout: `/props` → `total_slots: 2`, each slot `n_ctx: 131072`; `nvidia-smi` under 20 GB; a 2-scout plan runs both scouts concurrently (`/slots` shows two `is_processing`).

Consumers of the two slots: `cogito-planning-scout` `maxConcurrentTasks: 2` (unchanged), `cogito-reviewer-falsifier` 1, LiteLLM `reviewer` key `maxParallelRequests: 2` (was 8), `Muse-Glimmer-30B` alias unchanged at 131072. A third concurrent request queues inside llama.cpp; that is acceptable.

llama.cpp `--cache-prompt` is per slot, so prefix reuse (§6.2) only lands when a follow-up hits the same slot. Expect ~50 % hit rate on Muse with two slots; the prefix protocol's large payoff is on the Qwen lane.

### 3.3 LiteLLM: the real catalogue and the fixes

The catalogue is GitOps (`kubernetes/apps/llm/litellm/app/models/*.yaml`, `virtualkeys/*.yaml`), validated in CI. Current aliases:

| Alias | Backend | Role in this design |
|---|---|---|
| `planner` | `chatgpt/gpt-6-astra`, Responses API, `reasoning_effort: medium`, 1,050k in / 128k out | Astra. The only alias the coordinator calls. |
| `planner-local` | `openai/qwen3-8-27b` (after R2), effort `xhigh` | Local planner for experiments; not used by the coordinator. |
| `coordinator` | `chatgpt/gpt-5.6-luna`, Responses, effort `max` | Luna. Reserved for §9. Must never gain a fallback (validator rule). |
| `coordinator-heavy` | `chatgpt/gpt-5.6-terra` | Temporary compat alias; 10× burn; not used. |
| `worker` | `openai/qwen3-8-27b`, effort `low`, timeout 300 | Ad-hoc local worker calls via LiteLLM (pi, Hermes). Foreman does not use it. |
| `reviewer` | `openai/muse-glimmer-30b`, vision | Ad-hoc Muse calls via LiteLLM. Foreman does not use it. |
| `worker-escalated` | `chatgpt/gpt-5.6-luna` | Escalation key only. GLM 5.3 skipped by decision. |
| `reviewer-escalated` | `openai/kimi-k3` (Moonshot, metered) | Escalation key only. |
| `Qwen/Qwen3.8-27B-W4A16`, `Muse-Glimmer-30B`, `vision`, `embedder`, `reranker` | local | Open WebUI, RAG, pi. |
| `flashnext` | `openai/flashnext` | **Remove** (R3). |

Virtual keys: `planner` ($10/30d, 10 rpm, 2 parallel), `coordinator` (30 rpm, 4 parallel), `worker` and `reviewer` ($1 tripwire, 8 parallel), `escalation` ($15/30d), `open-webui`, `pi` (unscoped), `hermes` (unscoped, unused).

Fixes `[DECISION]`:

1. **R2 revert**: three backends back to `openai/qwen3-8-27b` once `SERVED_MODEL_NAME` is set.
2. **Remove `flashnext.yaml`** and its kustomization entry (R3).
3. **Parallel caps to match real seats**: `reviewer` key 8 → 2; `worker` key 8 → 4; fix both "matches the backend's eight seats" comments. Backends are 5 and 2.
4. **Budgets are not dollars for Astra.** `planner` and `coordinator` run on the ChatGPT subscription (`chatgpt/`, cost 0 in the catalogue). v1's per-session USD caps do not apply; the real limits are the subscription's rate/quota and the key's `rpm`/`maxParallelRequests`. The session card shows *turns and scout tasks*, not USD, for local and subscription models; USD only for `reviewer-escalated`.
5. **No fallbacks.** v1 §3.3's `coordinator → GLM 5.3 / K3` and `escalation` alias are dropped. Escalation is a coordinator decision using the `escalation` key's aliases, never a proxy fallback.
6. **Foreman bypasses LiteLLM** (`provider: local`). This stays: it removes a hop and a failure domain from the hot path, and local tokens are free. Consequences: LiteLLM's dashboard does not see Foreman traffic (use llama.cpp `/metrics` and vLLM metrics via the existing ServiceMonitors instead), and "escalate a worker to cloud after N failures" is a coordinator action (re-run the deliverable with a cloud reviewer via the `escalation` key), not an alias switch.
7. v1 milestone 0 (Responses↔chat translation) is **moot** for the deployed shape: Astra is called natively over Responses on `chatgpt/`; Foreman calls local models over chat completions. It only matters if Codex is chosen as the §9 harness, and then only for the `coordinator` alias, which is Responses-native.
8. Known break to retest on the next LiteLLM bump: non-streaming on `chatgpt/` at 1.97.0 (`plan.md`).

### 3.4 Version notes

- **vLLM** is pinned to 0.28.0 inside the syv-ai image and is not independently bumped. vLLM 0.29.0's MRV2 default, `prefix_cache_retention_interval` change and `--per-request-spec-decode-metrics` are irrelevant until syv-ai rebases; re-verify `SPEC=mtp` and prefix-cache hit rate after such a rebase.
- **llama.cpp**: running b10920, latest b10936. llmkube pins by digest; bump deliberately. `--kv-unified` defaults on when `--parallel` is auto, so always set `parallelSlots` explicitly.
- **cuda-dev** comments still describe vLLM 0.27/0.28 targets; update or leave dormant.

---

## 4. Architecture overview (as it will be after §13)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ PHONE (Commet)                                                           │
│  Space "Agents"                                                          │
│   #project-cogito   thread = session; mentions only                      │
│   #agent-runs       scout threads, Workload phases, Hookshot; muted      │
│   #agent-alerts     alertmanager; mentions only                          │
│   DM @coordinator   direct sessions (§9)                                 │
│  push: Synapse → ntfy (Matrix push gateway) → UnifiedPush → Commet       │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ /sync (maubot, E2EE via mautrix)   HMAC HTTP over localhost
┌───────────────▼──────────────────────────────────────────────────────────┐
│ matrix-coordinator (EXISTING, adapted)                                   │
│  bot container: cogito_bot.py  — decrypt, gate, forward; send/edit/     │
│                                   react/upload from the outbox           │
│  main container: coordinator   — SQLite (schema v11), reconciler,        │
│    state machine (§5.3), session card + progress edits, reactions,       │
│    Astra turns (Responses), scout fan-out, plan issue + deliverables,    │
│    Workload sequencing, quorum merge, escalation table, §9 sessions      │
└───┬──────────────────────┬────────────────────────────┬──────────────────┘
    │ Responses API        │ k8s API (AgenticTask,       │ GitHub REST (App)
    ▼                      │  Workload, ConfigMap)       ▼
┌──────────┐          ┌────▼──────────────────────┐  ┌──────────────────┐
│ LiteLLM  │          │ Foreman 0.9.25 (upstream) │  │ GitHub           │
│ planner  │          │ Agent/AgenticTask/Workload│  │ plan issue +     │
│ coord.   │          │ seats, tool whitelists,   │  │ sub-issues, PRs  │
│ no fbk   │          │ gate Jobs, quorum         │  └──────────────────┘
└────┬─────┘          └────┬──────────────────────┘
     │ chatgpt/ OAuth       │ Jobs (provider: local, direct to InferenceService)
     ▼                 ┌────▼─────────────────────────────────────────────┐
  ChatGPT sub.         │ iggy  x16: Qwen 3.8-27B  syv-ai vLLM 0.28        │
  (Astra, Luna)        │            SPEC=dflash2 CTX=long MAX_SEQS=5      │
                       │       x4:  Muse Glimmer 30B llama.cpp, 2 slots   │
                       │            Q4_K_M + DFlash + mmproj in host RAM  │
                       └──────────────────────────────────────────────────┘
```

---

## 5. The gateway: adapt `matrix-coordinator` or rewrite it?

### 5.1 What exists (measured)

`services/matrix-coordinator`: 9 stdlib-Python modules, 1,656 lines of source, 45 tests in 8 files (≈ 900 lines), plus the 152-line maubot plugin `kubernetes/apps/home-infra/matrix-coordinator/app/cogito_bot.py`. Written between 2026-09-10 and 2026-09-13 in 51 commits. Deployed as one pod, two containers: maubot (transport, E2EE, `/sync`) and the coordinator (HTTP API + 15 s reconciler), joined by HMAC-signed JSON over localhost.

Already there and tested:

- **Durability**: SQLite schema v10, WAL, `BEGIN IMMEDIATE`; `inbound_events` idempotency; `matrix_event_results` replay (a redelivered command returns the cached response and re-enqueues its actions); `matrix_outbox` with deterministic `notification_id` reused as the Matrix `txn_id`, marked sent only on the bot's ACK; parent-before-child ordering for thread replies; append-only `audit_events`; `external_actions` two-phase idempotency for GitHub writes.
- **Planner**: Astra over the Responses API, SSE reassembly, forced-draft mode, `delegate_research` (≤4 tasks/round, ≤2 rounds), `clarify`/`pushback`/`ready` statuses.
- **Scouts**: deterministic `AgenticTask` names, 409 tolerance, modelSummary extraction, JOB-ERROR classification, Agent Runs threads with redacted transcripts.
- **GitHub**: plan issue with hash markers, sub-issues with `parent_issue_id` and `blocked_by` chains, deliverable body contract, token re-read per request, SHA-pinned `merge-async` with polling.
- **Execution**: one Workload per deliverable, serial dispatch, two-distinct-reviewer quorum against the final coder SHA, Blocked/quorum-failed/merge-failed messages.
- **Ops**: Prometheus metrics, five alert rules, Grafana dashboard, RUNBOOK.

### 5.2 Gap table against v1's gateway

| v1 capability | Status today | Adapt cost (est. lines) | Notes |
|---|---|---|---|
| Astra planning loop with scout delegation | Exists | 0 | |
| Ask the owner a question | Exists (`clarify`/`pushback` → thread reply routed as intake answer) | ~40 | Add an explicit `NEEDS_INPUT` flag so the state machine and mention gating can key on it. |
| Session `notes.md` working memory | Missing | ~100 | `plan_notes` table; Astra writes it via a second tool or a `notes` field in the `ready`/`clarify` object; re-injected on resume instead of full transcript. |
| Result packets with schema | Partial (`verdict + ≤4000-char summary + modelSummary`) | ~80 | Require the §6.3 YAML shape inside the summary; validate in `state.update_research`; one retry on schema failure. Foreman's NO-GO quirk (R5) is upstream. |
| Prefix protocol + hash logging | Missing | ~50 | Prompt assembly is already in one place (`foreman.py:156-192`). Order it, hash the prefix, log it. |
| `inspect` / `cancel` / `followup` | `status` exists; cancel and follow-up missing | ~120 + RBAC `agentictasks: delete` | Follow-up = new task carrying the parent's summary in the `[task]` segment. |
| Durable, restart-safe state | Exists (SQLite + outbox) | 0 | Schema bump to v11 for the new tables/columns. |
| v1 state machine | Partial (see §5.3) | ~150 | Add `NEEDS_INPUT`, `BLOCKED`, `REPLANNING`, `PAUSED`, `CANCELLED` as explicit states; map the rest. |
| Session card + progress message edited in place | Missing | ~150 | New outbox action kind `edit` (`m.replace`) with the target's `sent_event_id`; bot handler; renderer. |
| Reactions as controls | Missing | ~90 | Bot forwards `m.reaction` on card events; coordinator maps ✅ ✏️ ⏹ ⏸ 🔄 🔍. |
| @mention on transitions only | Missing (room-level policy) | ~30 | Formatted body with the owner's mention pill + `m.mentions`; only on the five transition states. |
| Routing by state, no prefix | Partial (thread replies routed; `!cogito` needed at top level) | ~40 | Top-level owner message in a project room starts a session; bare `status` / `stop` / `approve` anywhere in a thread. Keep `!cogito` as an alias. |
| Per-room project config | Missing (repo hardcoded to `cogito-ops`) | ~50 + Terraform | Room-id → {repo, base branch, allowed Agents} map in the coordinator config; one Terraform room per project. |
| Plan as section messages + attached file | Missing | ~90 | Split `plan_markdown` on `## §` headings; bot uploads the file (`m.file`), new outbox action kind. |
| Semantic changelog on revision | Missing | ~40 | Ask Astra for a `changelog` field on `ready`; post it; re-post only changed sections (diff by section hash). |
| Multi-persona senders | Missing (one bot account) | 0 now; ~350 later | Personas are cosmetic. Prefix glyphs (`◆ Astra`, `▣ Fleet`) cost 10 lines. A later appservice transport rewrite of the 152-line bot keeps E2EE (Synapse already runs Hookshot encrypted). Defer. |
| Escalation table (§8.4) | Partial (Blocked, quorum-failed, merge-failed) | ~120 | Retry via 🔄; `REPLANNING` re-enters Astra with the failure packet; guardrail check on deliverable text before Workload creation. |
| Direct coordinator sessions (§9) | Missing | ~400 + pod launcher RBAC + PVC | The largest genuinely new piece. |
| Images from the phone | Missing | ~80 | Bot downloads `m.image`; coordinator passes it to `Muse-Glimmer-30B` for description or to the §9 session. |

Adapt total: roughly **1,200–1,500 new or changed lines** across `cogito_bot.py`, `matrix.py`, `state.py`, `foreman.py`, `planner.py`, one new `sessions.py`, plus tests, on top of 3.2k existing lines that stay.

### 5.3 State mapping

| v1 phase | Existing state | Change |
|---|---|---|
| `NEW` | `intake` | none |
| `DISCOVERING` | `researching` → `synthesizing` | none |
| `NEEDS_INPUT` | `intake` after `clarify`/`pushback`; `research_failed` | make explicit; mention |
| `PLAN_READY` | `review` | mention |
| `REVISING` | `review` + comments + `!cogito revise` | ✏️ reaction collects comments; auto-revise on second ✏️ or on `revise` |
| `APPROVED` | `accepted` → `decomposed` | ✅ reaction = `approve` |
| `EXECUTING` | `running` | none |
| `BLOCKED` | deliverable `failed` (plan stays `running`) | explicit state; mention; 🔄 retry re-creates the Workload with a new hash suffix |
| `REPLANNING` | none | new: Astra turn with the failure packet → new plan version → `review` |
| `DONE` | `completed` | mention |
| `PAUSED` / `CANCELLED` | none | new: `suspend` the Workload / stop dispatch; ⏹ cancels remaining deliverables and closes issues |

### 5.4 What a rewrite would buy, and cost

**Buy:** an appservice-first transport with real personas; a state model named after the phases above from day one; one async process instead of two containers over HTTP; a typed Foreman client. None of these are visible from the phone.

**Cost:** re-implementing roughly 2,000 lines of plumbing that is already correct and tested (outbox ordering, replay, GitHub issue graph and async merge, quorum rule, transcript redaction, JOB-ERROR bounding, migrations, metrics, alerts) before reaching parity, then the same ~1,300 lines of new features. The corner cases are the expensive part and they are recorded in the tests and the RUNBOOK: delayed-approval rejection, NO-GO scouts, parent-ack ordering, 409 on re-created tasks, stale-SHA reviews. A rewrite re-discovers each one in production. It also discards the pathway document's evidence ledger, which is the only record that the merge path has been exercised.

**Decision `[DECISION]`:** adapt. Rewrite only the transport file if and when personas are wanted; that is a bounded 150 → ~350 line change and Synapse already supports what it needs.

### 5.5 Idempotency and restart

Unchanged mechanisms: event replay by `event_id`, outbox with `txn_id`, `synthesizing` reset to `researching` on boot. New: edits and reactions go through the same outbox (`kind: edit | react | upload`), so a crash between send and ACK cannot double-post. After R1, restarts are voluntary again.

---

## 6. The Foreman client (v1's "broker")

### 6.1 Interface

No separate MCP process `[DECISION]`. The broker is `coordinator/foreman.py` plus the research tables in `state.py`, exposed to Astra as tools in the Responses request and to the owner as thread verbs:

```
delegate_research(tasks[≤4])            exists   → AgenticTask kind: freeform, agentRef: cogito-planning-scout
status(plan|workload)                   exists   → !cogito status / bare "status"
followup(task, question)                new      → child task whose [task] segment carries the parent summary
cancel(task)                            new      → delete AgenticTask (RBAC)
results(task)                           exists   → status.result + transcript ConfigMap
```

Seats are Foreman `Agent.maxConcurrentTasks` (scout 2, coder 1, reviewer 1, falsifier 1); extra tasks queue in Foreman. Model choice is by Agent, not by the planner.

### 6.2 Prefix protocol

Kept from v1, applied in `foreman.py`'s prompt wrapper:

```
[system prompt for role]      Agent CR systemPrompt (stable, versioned by GitOps)
[repo preamble]               "Repository: … Base branch: …" + repo map (regenerated on base SHA change)
[plan excerpt, if executing]  stable per plan version
[task]                        varies
```

No timestamps or task ids above `[task]`. Log `sha256(prefix)` in the AgenticTask annotations so hit rate can be read from llama.cpp `/metrics` (`prompt_tokens_cached`) and the syv-ai server's prefix-cache counters. Expect the payoff on Qwen; on two-slot Muse it is per-slot.

### 6.3 Result packet

Kept from v1 as the required shape of the scout's `submit_result` summary (YAML, ≤4000 chars). Foreman wraps it in `verdict/summary`; the coordinator parses `modelSummary` (R5) and validates the packet. `artifacts` point at the transcript ConfigMap and, for coder tasks, the branch and commit; there is no object-storage bucket for agents today and none is added `[DECISION]` (transcript ConfigMaps are bounded and already redacted; revisit if they exceed ~1 MB).

### 6.4 Worker pods

As deployed: one Job per task, clone at base branch, tool whitelist per Agent, SA `foreman-coder`. Two changes: `[VERIFY]` that the scout Job pod carries no push-capable token (the chart's `coderGitSecret` is mounted for all coder-image Jobs; a read-only scout with `bash` must not be able to `git push`); and image-side, keep the scout derivative image (`gh`, `jq`, `unzip`) digest-pinned as now.

---

## 7. Plans: format, storage, review

### 7.1 Format

v1 §7.1's front-matter `steps` block with `depends_on`, `mode`, `acceptance`, and `guardrails.never_touch` is adopted, with one mapping: each top-level step becomes one GitHub sub-issue and one Foreman Workload; `acceptance` becomes the issue's acceptance checklist, which the gate Job and reviewers already read from the issue body. `depends_on` becomes GitHub `blocked_by` (already emitted for the serial case).

### 7.2 Storage `[DECISION]`

No `agent-plans` repo. Plan versions live in `plan_versions` (unique `content_hash`, unique Matrix event id) and the accepted version's hash is embedded in the plan issue body. That is already "this exact plan was approved; this exact plan was executed". The session card links the plan issue and the version's Matrix event.

### 7.3 Review in Matrix

As v1 §7.3, implemented per the gap table: section messages, reply-to-section comments (already recorded as review comments), ✅ / ✏️ on the card, semantic changelog, attached `plan.md`. Bare `approve` is already safe: the coordinator rejects an approval whose timestamp predates the current version, so the `sha256:` argument becomes optional rather than required.

---

## 8. Execution

### 8.1 Coordinator

Deterministic. On `APPROVED`: create the plan issue and sub-issues (exists), then one Workload per deliverable, serially (exists). Each Workload runs Foreman's pipeline: `cogito-coder` (Qwen) → `cogito-gate` (deterministic checks) → `cogito-reviewer` (Qwen) and `cogito-reviewer-falsifier` (Muse) → PR → quorum → async squash merge → next deliverable. Model diversity in review is already enforced (two distinct Agents, two model families).

### 8.2 Git model

Foreman's: one branch per Workload (`foreman/<workload>/issue-<n>`), one PR per deliverable to `main`, merged in order. v1's integration branch is dropped `[DECISION]`; serial PRs are what the quorum and merge code already handle, and they are what GitHub Mobile reviews well.

### 8.3 Concurrency

Foreman seats as in §6.1. Two slots on Muse serve two scouts, or one scout and one falsifier review. Qwen holds coder and reviewer. If a plan's research round wants four scouts, two queue; that is fine.

### 8.4 Escalation boundary (coordinator code, not a model)

| Discovery during execution | Action |
|---|---|
| Gate fails, reviewer NO-GO, coder needs another try | Foreman retries within `maxRetries`; Workload `maxReviewIterations` |
| Merge conflict on a later deliverable | Coordinator re-creates the Workload against the new `main` (🔄) |
| Deliverable fails after Foreman's retries | `BLOCKED` → @mention; 🔄 retries, ⏹ cancels, a thread reply with new guidance re-creates the Workload with the reply appended to the issue body |
| Deliverable text intersects `guardrails.never_touch` (k8s manifests, Talos, secrets, RBAC) | `NEEDS_INPUT` → owner, before any Workload is created |
| Owner says "this approach won't work" or two consecutive deliverables block | `REPLANNING` → Astra with the failure packets → new plan version → `PLAN_READY` |
| Local reviewers disagree repeatedly | Coordinator re-runs the review with `reviewer-escalated` via the `escalation` key (explicit, logged; never a proxy fallback) |

### 8.5 Code review in GitHub

As deployed: Hookshot posts PR events to `#agent-runs`; quorum merge is automatic; GitHub branch protection still applies. Optional owner-gate: require the owner's GitHub approval before the coordinator calls merge (a config flag; today it merges on quorum alone).

### 8.6 Observability

Transcripts: ConfigMaps + Agent Runs threads (exists). Prefix hash annotations (new). Dashboards: existing coordinator Grafana board plus llama.cpp `/metrics` and vLLM metrics via the existing ServiceMonitors. Spend: turns and task counts on the card; USD only for metered keys.

---

## 9. Direct coordinator sessions

Unchanged goal. Two changes to the approach:

1. **Evaluate Hermes first `[DECISION]`.** It is already a Matrix agent in the Agents space with E2EE and tool use; it broke when its provider config was orphaned. Reconnecting it to LiteLLM (`coordinator` alias for Luna, `worker` for Qwen, `Muse-Glimmer-30B` for images) is a config task. If it gives a usable "talk to a coding agent from the couch" experience, milestone 4 shrinks to a PVC-backed workspace and a scoped git token.
2. If Hermes is not enough, the harness bridge as v1 §9: a Foreman-managed pod running Codex or pi, PVC session dir, bridged to a DM thread by the coordinator with an edited-in-place progress message. Codex needs the Responses API, which the `coordinator` alias already speaks natively; Qwen and Muse are chat-completions backends and would need LiteLLM's translation `[VERIFY]` only for Codex.

Images from the phone route through `Muse-Glimmer-30B` (vision, host-RAM projector) as in v1.

---

## 10. Matrix conventions

### 10.1 Rooms (existing, mapped)

| v1 | Existing room | Notification rule |
|---|---|---|
| `#proj-<repo>` | `#project-cogito` (one per project; add rooms via Terraform) | Mentions only (v2 adds mentions on transitions) |
| `#fleet` | `#agent-runs` (scout threads, Workload phases, Hookshot) | Muted |
| `#alerts` | `#agent-alerts` | Mentions only |
| DM `@lab-luna` | DM `@coordinator` | Normal |

`#agent-control` and `#agent-plans` exist and are currently unused by the coordinator; `#agent-plans` becomes the home for plan file attachments if the project-room thread gets too long, or is retired.

### 10.2 Thread anatomy and verbs

As v1 §10.2–10.3, with one persona for now (glyph-prefixed: `◆ Astra`, `▣ Fleet`, `▶ Foreman`). `!cogito` stays as an alias; `status`, `stop`, `approve` work bare; reactions on the card are the controls.

---

## 11. Notifications

Done: Synapse → ntfy push gateway → UnifiedPush → Commet. Add: @mention only on `NEEDS_INPUT`, `PLAN_READY`, `BLOCKED`, `DONE`, `CANCELLED`; everything else is a card/progress edit. Keep the existing out-of-band ntfy topic for "coordinator down" and "Synapse down" (Prometheus rules `MatrixCoordinatorAbsent/Down` already exist; route them to ntfy).

---

## 12. Security and budgets

- Astra: no world tools (exists). Coordinator SA: `workloads` create/get/list/watch, `agentictasks` create/get/list (+ delete for cancel), `configmaps` get. No cluster-wide rights.
- Worker pods: as deployed; verify the scout token scope (§6.4).
- `guardrails.never_touch`: checked by the coordinator before Workload creation; anything touching `kubernetes/`, `talos/`, secrets or RBAC goes to the owner.
- Budgets: subscription models are rate-capped by key; metered keys (`escalation`) keep USD caps; per-session caps are counts (scout tasks, deliverables, Astra turns).
- Prompt injection: scout summaries are data (exists: transcripts redacted, packets never executed). GitHub issue bodies written by the coordinator are the only text Foreman executes from.

---

## 13. Build order

| # | Milestone | Done when |
|---|---|---|
| **R0** | **Cluster repair** (§1.5 R1–R7) | No Deployment roll for 2 h without a spec change; a Foreman coder task completes a turn against Qwen; `flux get ks -A` all Ready; iggy memory requests < 50 %; Muse `/props` shows 2 slots; PR 22 resolved. |
| 1 | **Real plan end to end** (pathway F4.3/F4.4, G6, H6, I6) | One Commet-originated plan with two deliverables researches, gets approved, runs two Workloads, merges both via quorum, and posts `Completed`. Turn counts per scout < 40. |
| 2 | **Session card, reactions, mentions, state machine** (§5.2 rows 2, 7–11) | Card edited in place on every transition; ✅ ✏️ ⏹ ⏸ 🔄 🔍 work; phone pings only on the five transition states; restart mid-plan loses nothing. |
| 3 | **Plan review surface** (§7) | Sections as messages, reply-to-section comments, semantic changelog, attached file, bare `approve`. |
| 4 | **Escalation table + notes** (§8.4, notes.md) | Forced `BLOCKED` and `REPLANNING` exercised; guardrail intercept exercised; a three-day-old session resumes from notes. |
| 5 | **Per-room projects + prefix protocol + packets** | Second project room; prefix hash logged and hit rate read from metrics; packet schema validated. |
| 6 | **Direct sessions** (§9) | Hermes evaluated; if adopted, DM → coding turn round-trips with a PVC workspace and image input; else harness bridge. |
| 7 | **Personas + polish** | Optional appservice transport; dashboards; retire `!cogito` prefix requirement. |

---

## 14. Open items to verify

1. `[VERIFY]` R1: does the long-lived foreman-agent process need a fresh GitHub token after the Reloader opt-out? Watch its logs for 401s after 60 minutes.
2. `[VERIFY]` R2: Foreman accepts the change without an Agent re-validation issue; coder turn succeeds.
3. `[VERIFY]` Muse two-slot VRAM and concurrency (§3.2), and whether unified vs per-slot KV changes scout latency.
4. `[VERIFY]` Scout Job pods carry no push-capable token (§6.4).
5. `[VERIFY]` Commet renders `m.poll`; otherwise numbered options.
6. `[VERIFY]` Hermes reconnected to LiteLLM is a usable direct session (§9).
7. `[VERIFY]` LiteLLM Responses↔chat translation for Qwen/Muse, only if Codex is the §9 harness.
8. `[VERIFY]` Prefix-cache hit rate on the syv-ai server under `CTX=long` with the ordered prompt.
9. Upstream: Foreman's no-diff gate on `freeform` tasks (R5); Foreman re-creating Jobs for terminal tasks on agent restart (observed under R1, should not happen even then).

---

## 15. Glossary

- **Astra** — `planner` alias (`chatgpt/gpt-6-astra`). **Luna** — `coordinator` alias (`chatgpt/gpt-5.6-luna`), reserved for direct sessions. **Terra** — `coordinator-heavy`, unused. **K3** — `reviewer-escalated` (Moonshot).
- **Foreman** — upstream llmkube agent scheduler (`Agent`, `AgenticTask`, `Workload`, `FleetNode`); executes deliverables as coder → gate → reviewers → PR.
- **matrix-coordinator** — the existing planning gateway (maubot transport + Python coordinator + SQLite), adapted in this design.
- **Scout** — `cogito-planning-scout` Agent: read-only Muse task created by Astra's `delegate_research`.
- **Falsifier** — `cogito-reviewer-falsifier`: the Muse reviewer that gives the quorum its second model family.
- **Session card / progress message** — two thread messages edited in place (new in v2).
- **syv-ai stack** — `ghcr.io/syv-ai/qwen38-27b-rtx3090`, vLLM 0.28.0 + patches, env-configured.
- **flashnext** — the CPU Qwen3.8-Flash-Next lane, removed for now; weights retained.

## 16. Sources consulted (2026-09-13)

- Repo `timblakely/cogito-ops` @ `5c850664`: `services/matrix-coordinator/`, `kubernetes/apps/llm/{llmkube,foreman,litellm}/`, `kubernetes/apps/home-infra/{matrix,matrix-coordinator,matrix-hookshot}/`, `foreman_migration_pathway.md`, `matrix_development_coordination.md`, `plans/llm/*`.
- Live cluster via `kubeconfig`: pods, Deployments/ReplicaSets, CRDs, AgenticTask statuses and transcripts, `nvidia-smi` in the serving pods, llama.cpp `/props` and `/slots`, InferenceService `/v1/models`.
- syv-ai/qwen38-27b-rtx3090 README — https://github.com/syv-ai/qwen38-27b-rtx3090
- llama.cpp server README and releases (b10936) — https://github.com/ggml-org/llama.cpp
- vLLM releases (v0.29.0, 2026-09-09) — https://github.com/vllm-project/vllm/releases
- vLLM Muse Glimmer recipe — https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B
- RedHatAI/Muse-Glimmer-30B-W4A16 model card — https://huggingface.co/RedHatAI/Muse-Glimmer-30B-W4A16
- Hardware Corner, Muse Glimmer 30B on RTX 3090 (llama.cpp) — https://www.hardware-corner.net/hardware-for-muse-glimmer-30b-llm/
- defilantech/llmkube (Foreman) — https://github.com/defilantech/llmkube
- Review page for the v1 audit — https://claude.ai/code/artifact/8342d002-3e65-4ae8-a140-9bf27ddafea8
