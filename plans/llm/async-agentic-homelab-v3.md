# Async Agentic Homelab: Matrix-driven planning and execution on a Talos Kubernetes cluster

**Status:** design proposal, v3 (2026-09-13). Superseded by `async-agentic-homelab-v4.md` the same day; retained for the trail.
**Audience:** a reviewer with no prior context. Unverified items are `[VERIFY]`, contestable choices are `[DECISION]`, live-cluster observations are `[OBSERVED]`, and things that were inherited from an upstream default or a colleague's profile rather than chosen here are `[INHERITED]`.

---

## Changelog v2 → v3

v2 corrected v1 against the repo, but it still carried seven settings forward as "as deployed" that nobody had actually chosen. v3 names each one, decides it, and changes the plan where the decision matters. Nothing from v2's v1 → v2 changelog is reversed.

| Setting | v2 said | What it actually is | v3 |
|---|---|---|---|
| Foreman → model routing | Foreman calls InferenceServices directly; "this stays" | Foreman's v0.1 `provider: local` default. Foreman supports `provider: cloud-proxy` for an OpenAI-compatible gateway, "typically LiteLLM". | **Foreman routes through LiteLLM** (§3.3, §6.1). One alias and one key per Agent role. The local/cloud boundary moves from Foreman's gates to LiteLLM key scope. |
| Task concurrency | "Two Muse slots serve two scouts" | Chart value `agent.maxSupervisedTasks: 1`, uncommented, makes the FleetNode run **one task at a time cluster-wide** `[OBSERVED]`. The scout's `maxConcurrentTasks: 2` has never applied; Muse's one-slot config was derived from this. | `maxSupervisedTasks: 4` (§3.2, R8). Muse two slots is only useful with this. |
| Verify gate and merge safety | "GitHub's own rules still apply" | Gate command is `git diff --check` only; `main` on cogito-ops has **no branch protection**; `merge-async` does not wait for the flux-local CI run. | Gate runs flux-local for `kubernetes/` changes; ruleset on `main` requires the `flux-local-status` check; the coordinator waits for checks before merge (§8.5, R9). |
| Qwen serving profile | Kept as a decision | `[INHERITED]` from Jory's Syv AI profile, per the manifest comment. Unmeasured on our prompts. | Keep to make the lane work; A/B `SPEC` and `CTX` on scout-shaped prompts before calling it settled (§3.1). |
| Astra reasoning effort | Not discussed | `planner` alias pins `reasoning_effort: medium`; the comment justifies the model, not the level. | `[DECISION]` `high` for the planner alias (§3.3). |
| Muse reasoning budget | Treated as fixed; raised the turn timeout around it | `reasoningBudget: 16384`, no rationale. | Keep 16384, turn timeout 900, measure scout turn p95; cut the budget to 8192 if p95 > 600 s (§3.2). |
| Coder / reviewer image | Not discussed | Upstream coder image without `gh`; only the scout got the derived image. | All coder-image Agents use the derived image (§6.4). |

Also carried into v3 from the conversation after v2: the local/cloud kill switches in Foreman (`allowCloudProviders`, `allowCloudReviewers`) flip to true deliberately, with the boundary re-established in key scope (§12).

---

## 0. Executive summary

The owner runs a Talos/Flux Kubernetes cluster with two RTX 3090s on one node, a Synapse homeserver used from Android via Commet, upstream llmkube + Foreman for agent scheduling, a LiteLLM catalogue fronting local and ChatGPT-subscription models, and an existing Matrix coordinator service that already drives an Astra planning loop with local Muse scouts and hands approved deliverables to Foreman. The owner has a newborn and operates from a phone in short bursts.

Goal, unchanged: an asynchronous, notification-driven agentic system where Astra plans with local scouts and asks questions in Matrix; the owner approves from the phone; Foreman executes; the owner is pinged only on state transitions; and a direct coding session can be opened from Matrix without SSH.

What v3 asserts:

1. **Repair before building.** Nine repair items (§1.5). Two block execution today: both agent Deployments restart every 30 minutes, and Foreman's coder and reviewer cannot reach Qwen. Two more make the deployed system unsafe for real changes: one-task-at-a-time supervision and a gate that checks nothing before auto-merge.
2. **LiteLLM is the single routing authority.** Every model call, including Foreman's workers, goes through the catalogue. Capabilities, sampling pins, timeouts, parallel caps and spend live in one place.
3. **Adapt the coordinator, do not rewrite it.** Roughly 1.2k–1.5k lines of phone-facing work on top of 3.2k lines of tested plumbing (§5).
4. **Serving is settled on this hardware.** Qwen 3.8-27B on the syv-ai vLLM 0.28 image is the only single-card path at acceptable speed; Muse Glimmer 30B on llama.cpp gets two full-context slots, speculative decoding and vision in host RAM, none of which vLLM offers on a 24 GB Ampere card (§3).
5. **Foreman is the execution owner.** Deliverables become Foreman Workloads; the coordinator sequences them and applies the escalation table. No paid coordinator model in the execution path.

---

## 1. Context for the reviewer

### 1.1 The owner and the operating constraint

Android phone, short attention windows, resume after days away, one thumb. Simplify the interaction surface, not the infrastructure.

### 1.2 Existing infrastructure (corrected inventory)

All rows exist today. Versions are what is deployed at repo commit `5c850664`.

| Component | What it is | Facts relevant to this design |
|---|---|---|
| **Talos cluster** | 5 nodes (`iggy`, `kristeva`, `nuc-1/2/3`), all control-plane, Kubernetes 1.34.2, Flux-managed from `timblakely/cogito-ops` (this repo). | iggy runs Talos v1.13.5, the rest v1.12.5 (deliberate after the DRA rollback; converge later). |
| **llmkube 0.9.25** | Operator for inference servers: `Model`, `InferenceService`; runtimes `llamacpp`, `vllm`, `generic`. | Runs the syv-ai image as `runtime: generic` and Muse as `runtime: llamacpp`. Has `rolloutPolicy.waitForIdle`, `parallelSlots`, `speculativeDecoding`, `reasoningBudget`. GPUs are UUID-bound via `NVIDIA_VISIBLE_DEVICES`, not the device plugin. |
| **Foreman 0.9.25** (upstream, `defilantech/llmkube`) | Agent scheduler. CRDs `Agent`, `AgenticTask`, `Workload`, `FleetNode`, `ModelProfile`, `AgentRelease`. Roles coder / verifier / reviewer / planner / worker. `Workload` runs a fixed pipeline per issue: coder → gate Job → reviewer(s) → PR, with `maxReviewIterations` repair rounds. `AgenticTask kind: freeform` for read-only scouts. | `Agent.spec.provider` is `local` (resolve `inferenceServiceRef`) or **`cloud-proxy`** (`providerConfig.baseURL`, `.model`, `.apiKeySecretRef`; "typically a LiteLLM gateway"). Cloud-proxy is gated by the operator's `allowCloudProviders` and per-Workload `allowCloudReviewers`. One `foreman-agent` FleetNode on iggy; its `maxSupervisedTasks` bounds cluster-wide concurrency. Result contract: `submit_result` → `verdict GO/NO-GO + summary` plus a transcript ConfigMap. Foreman does not plan across issues. |
| **LiteLLM 1.97.0** | Proxy with a GitOps catalogue (`kubernetes/apps/llm/litellm/app/models/`, `virtualkeys/`), validated by `scripts/validate-llm-catalogue.py`. | **No fallbacks anywhere, by decision.** `LiteLLMVirtualKey` CRs materialise `litellm-key-<name>` Secrets in the `llm` namespace; PushSecrets copy them to 1Password for other namespaces. Cloud models are ChatGPT-subscription OAuth (`chatgpt/`) plus metered OpenAI and Moonshot. One replica, currently on nuc-3. |
| **matrix-coordinator** (`services/matrix-coordinator`) | The existing planning gateway: maubot transport container + stdlib-Python coordinator container, SQLite schema v10 on a volsync-backed PVC. | Astra via Responses API with one `delegate_research` tool (≤4 scouts × ≤2 rounds), `!cogito plan/draft/revise/approve/status`, GitHub plan issue + sub-issues with native dependencies, one Foreman `Workload` per deliverable, two-reviewer quorum, SHA-pinned async squash merge. 45 unit tests. |
| **Synapse 1.160.0** | Homeserver on CNPG. | One appservice registered (Hookshot). MSC3202/MSC2409 enabled, so encrypted appservices work. Push goes to ntfy. |
| **Rooms** (Terraform-managed) | Space `Agents`: `#agent-control`, `#agent-alerts`, `#agent-plans`, `#agent-runs`, `#project-cogito`. Space `Personal`. | All E2EE, invite-only. Hookshot's GitHub connection for `cogito-ops` lives in `#agent-runs`. |
| **Commet** | Owner's Matrix client. | `[VERIFY]` `m.poll` rendering. |
| **ntfy 2.27** | Deployed in `observability`. | UnifiedPush distributor **and** Matrix push gateway. Working. |
| **Hookshot 7.4.4** | GitHub App 4906005 + generic webhooks. | PR/issue events to `#agent-runs`. |
| **CI on cogito-ops** | `.github/workflows/flux-local.yaml` (flux-local v7.11.0 `test` + `diff`, summary job `flux-local-status`) on `pull_request` to `main`. | **`main` is unprotected**; nothing requires the check. |
| **Hermes** | Matrix agent bot `@hermes`, E2EE required, allowed user `@tim`. | Provider config orphaned; virtual key never used. Candidate for §9. |
| **Reloader** | Cluster-wide, `autoReloadAll: true`. | Root cause of the restart loop (R1). |

### 1.3 Cluster hardware (as it is)

| Node | Hardware | Role |
|---|---|---|
| **iggy** | Ryzen 9, 128 GB DDR4, 2 × RTX 3090 24 GB (x16 `GPU-a598…`, x4 `GPU-787b…`), 250 W power limit via DaemonSet. | Qwen on the x16 card, Muse on the x4 card. Foreman agent, gate cache, 450 Gi model cache. After flashnext removal: ~40 Gi RAM requests instead of ~124 Gi. |
| **kristeva** | Dual Xeon, 128 GB DDR3, Intel Arc A380. | `bge-m3`, `bge-reranker-v2-m3`, `vision-cpu`. Always on. |
| **nuc-1/2/3** | Meteor Lake NUCs, Thunderbolt ring. | Ceph, Qdrant, LiteLLM, Matrix, coordinator, Hookshot, immich. No LLM serving. |

No 5070 Ti node exists; the gaming node is out of scope.

### 1.4 Decisions already made

From `foreman_migration_pathway.md` and `matrix_development_coordination.md`: Matrix thread = plan-review object; GitHub issue = accepted-work object; PRs carry code only. Foreman replaced the custom Argo path outright. Quorum auto-merge requires two distinct reviewer Agents against the final coder SHA. Astra delegates to local scouts; no paid fallback. Room-level notification policy: mute `#agent-runs`.

From `plans/llm/plan.md` (locked): coordinator pattern, no autorouting; no cross-model proxy fallbacks; GLM 5.3 skipped; Kimi K3 is `reviewer-escalated` only.

From v2: flashnext removed (weights PVC kept); 5070 Ti ignored; llmkube + Foreman stay; syv-ai Qwen is the Qwen lane; Muse two slots on llama.cpp; E2EE on; SQLite stays; coordinator adapted, not rewritten.

From v3 `[DECISION]`:

- **Foreman routes through LiteLLM** (`provider: cloud-proxy`). The proxy is the single routing and capability authority for every consumer, server-side agents included.
- **Foreman's local/cloud kill switches flip to true** and the boundary is re-established as LiteLLM key scope, which the catalogue validator already enforces per key.
- **`maxSupervisedTasks: 4`.** Matches two Muse slots plus a Qwen coder and reviewer.
- **The gate runs flux-local for `kubernetes/` changes and `main` gets a ruleset** requiring `flux-local-status`; the coordinator waits for required checks before merging.
- **Astra at `reasoning_effort: high`.** Planning turns are few and subscription-metered; quality is the constraint.
- **Inherited serving knobs are labelled as such** and get a measurement before they are called settled.

### 1.5 Cluster repair list `[OBSERVED 2026-09-13]`

Prerequisites, not milestones. Each is a GitOps change.

| # | Fault | Evidence | Fix |
|---|---|---|---|
| **R1** | `foreman-agent` and `matrix-coordinator` roll every 30 min. Each roll drains the FleetNode, expires in-flight scout claims (terminal failure after 3), and re-creates Jobs for every AgenticTask in the namespace, including day-old successes. | `foreman-agent` revision 76, `matrix-coordinator` revision 147; new ReplicaSets at :25 and :55 hourly, matching `refreshInterval: 30m` on the `GithubAccessToken`-generated secrets; Reloader `autoReloadAll: true`. | `reloader.stakater.com/auto: "false"` on both Deployments (app-template `controllers.coordinator.annotations`; a kustomize patch on `Deployment/foreman-agent`, since the Foreman chart exposes only `podAnnotations`). `[VERIFY]` after one hour that the long-lived foreman-agent process does not itself use the stale `GITHUB_TOKEN` env. |
| **R2** | Foreman coder and reviewer 404: they request `qwen3-8-27b`, the syv-ai server serves `qwen3.8-27b`. | `/v1/models` on the InferenceService; Job logs. | Two parts. (a) `SERVED_MODEL_NAME=qwen3-8-27b` in the Qwen InferenceService env and revert the three LiteLLM backends to `openai/qwen3-8-27b`, so the InferenceService name and the LiteLLM backend agree. (b) Move all four LLM-backed Agents to `provider: cloud-proxy` with `providerConfig.baseURL: http://litellm.llm.svc.cluster.local:4000/v1`, `providerConfig.model: <alias>`, `providerConfig.apiKeySecretRef: litellm-key-<role>` (§3.3). After (b) Foreman never names a served id again. |
| **R3** | Flux `llm` Kustomization unhealthy since 2026-09-08 (`Job/flashnext-stage-v1` Failed); flashnext RollingUpdate stuck 6 h (76 Gi surge pod, node at 97 % requests). | `flux get ks -A`; pod events. | Remove `flashnext.yaml` and `flashnext-stage.yaml` from `llmkube/resources/kustomization.yaml`; delete the Job, ConfigMap, `Model/flashnext`, `Model/flashnext-mtp`, `InferenceService/flashnext`; remove `litellm/app/models/flashnext.yaml`. Keep the PVC. |
| **R4** | Muse Agents override sampling: scout `temperature: 0.2`, falsifier `0.1`; model card requires 1.0 / 0.95 / 64. Two scouts ran 78 turns (1256 s, 1547 s) cycling four git commands 11–13 times each. | Transcript ConfigMaps `foreman-transcript-plan-8dfd3c17…-research-r1-{1,2}`. | Delete `temperature` from both Muse Agents **and** pin sampling at the alias level (drop `temperature`, `top_p`, `top_k` from the request in the Muse aliases) so no client can undo it. Scout `requestTurnTimeoutSeconds` 300 → 900. |
| **R5** | Every read-only scout is recorded `NO-GO, "model emitted GO but produced no diff"` (coder no-diff gate applied to `freeform`). | All 17 scout tasks. Coordinator reads `extra.modelSummary`. | File upstream. Never key new logic on scout `verdict`. |
| **R6** | PR 22 (issue 21) can never reach the two-identity quorum (its Workload predates the falsifier Agent). | `gh pr list`; Workload `foreman-acceptance-21-v5`. | Merge or close by hand; delete the Workload. |
| **R7** | GPU lanes use `RollingUpdate`; Muse spec changes caused four scout `connection refused` JOB-ERRORs. | AgenticTask log tails. | `rolloutPolicy: {waitForIdle: true, idleTimeoutSeconds: 900}` on both GPU InferenceServices. |
| **R8** | Cluster-wide serial execution. `agent.maxSupervisedTasks: 1` → FleetNode `supervisionCapacity.maximum: 1`. Scouts in one round are claimed back-to-back (r1-2 claimed 4 s after r1-1 finished). | `kubectl get fn -o json`; AgenticTask `claimedAt`/`finishedAt`. | `maxSupervisedTasks: 4`. Re-check the Muse 16 Gi host-memory limit under two concurrent scouts (it was raised after an OOM under sequential ones). |
| **R9** | Auto-merge with no checks. Gate is `git diff --check`; `main` has no branch protection; `merge-async` does not wait for CI. GEMINI.md requires flux-local before k8s changes land. | `gh api …/branches/main/protection` → 404; `foreman.py` gateProfile. | Ruleset on `main` requiring `flux-local-status`; gate `test` command runs `flux-local test` when the diff touches `kubernetes/` (§8.5); coordinator polls the PR's check rollup before `merge-async`. |

---

## 2. Roles and the conceptual hierarchy

```
You             set intent, answer questions, approve plans, approve code PRs.
Astra           decides WHAT. `planner` alias (gpt-6-astra, subscription, Responses API, effort high). No world tools.
Coordinator     deterministic code (matrix-coordinator): Matrix ↔ Astra ↔ Foreman ↔ GitHub, state, escalation table.
LiteLLM         the only path to any model: aliases, keys, sampling pins, timeouts, parallel caps, spend.
Foreman         executes approved deliverables: coder → gate → two reviewers → PR, per issue.
Local workers   Qwen 3.8-27B (coder, one reviewer) and Muse Glimmer 30B (scouts, falsifier reviewer, vision).
Luna            reserved: direct coding sessions (§9). Not in the execution path.
```

Planning: `You ⇄ Matrix ⇄ coordinator ⇄ Astra`, with `delegate_research` fanning out to Muse scouts through Foreman `AgenticTask`s. Implementation: `Approved plan → GitHub plan issue + ordered sub-issues → Foreman Workload per deliverable (serial) → PR → checks + quorum → merge → next`. Astra is re-entered only on `REPLANNING` (§8.4).

---

## 3. Models and serving

### 3.1 Card 1 (PCIe x16): Qwen 3.8-27B on the syv-ai stack `[DECISION: this must work]`

Deployed as `InferenceService/qwen3-8-27b`, `runtime: generic`, image `ghcr.io/syv-ai/qwen38-27b-rtx3090@sha256:8382b699…` (vLLM 0.28.0 + patches), port 18020, env `SPEC=dflash2 PREFIX_CACHE=1 CTX=long MAX_SEQS=5 VISION=0`, 24 Gi host RAM. `[OBSERVED]` 22.9 GB VRAM in use.

`[INHERITED]` The env profile "follows Jory's Syv AI profile" (manifest comment). The syv-ai defaults are `SPEC=mtp CTX=fast MAX_SEQS=8`; Jory chose DFlash2, `CTX=long` (FlashInfer, int8 KV, 150k) and five admitted requests for his workload. None of it has been measured on our scout- or coder-shaped prompts, and int8 KV is a quality trade nobody here evaluated.

Facts from the syv-ai README that matter here: knobs are boot-time env (`SPEC`, `CTX=fast|long|huge`, `MAX_SEQS`, `PREFIX_CACHE`, `DFLASH_TOKENS`, `VISION`, `TOOLS`, **`SERVED_MODEL_NAME`** default `qwen3.8-27b`, `MODEL`, `EXTRA_ARGS`). C1 decode at 250 W: MTP 118 tok/s, DFlash2 126. Residency (`dflash2`, `CTX=fast`, 4k prompts): C1 137 / C2 97 / C4 46 / C8 33 tok/s per stream, ~5 resident at C8; MTP sustains 8 at 23 tok/s. At 16k prompts DFlash2 holds ~2, MTP ~4. Prefix caching restores KV and mamba state losslessly.

**Plan:** (1) R2 makes the lane reachable. (2) Keep Jory's profile to get moving; today's Qwen demand is coder + reviewer. (3) Before calling the profile settled, A/B on real prompts (a scout transcript replayed, a coder task) across `SPEC=dflash2|mtp` and `CTX=fast|long`, measuring per-stream tok/s at C1–C4, TTFT on a 16k prompt, and the prefix-cache hit rate; record the result in `bench-notes.md` per the "bench parameters are not serving defaults" rule. Switch to `SPEC=mtp` if measured concurrency needs exceed DFlash2's residency.

**Foreman seats:** `cogito-coder` 1, `cogito-reviewer` 1. `[INHERITED]` Their `temperature: 0.2` / `0.3` are unmeasured too; not visibly harmful, and now pinnable at the alias.

### 3.2 Card 2 (PCIe x4): Muse Glimmer 30B, two slots `[DECISION]`

Deployed as `InferenceService/muse-glimmer-30b`, `runtime: llamacpp`, `server-cuda` build **b10920** (latest b10936), `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf`, DFlash drafter (`nDraftMax 15, pMin 0.75`), `mmproj` in host RAM, `contextSize 131072`, KV `q8_0`, `parallelSlots 1`, `--kv-unified`, `--reasoning-budget 16384`, sampling 1.0/0.95/64. `[OBSERVED]` 17.1 GB of 24.6 GB VRAM with one 131k slot; `/props` → `total_slots: 1`. ATEM tool calls parse into OpenAI `tool_calls` via `--jinja` today (every scout transcript shows tool round-trips), which closes v1's `[VERIFY]` #3.

**Two slots at current stable releases:**

| | llama.cpp b10936 | vLLM v0.29.0 (2026-09-09) |
|---|---|---|
| Weights on a 24 GB Ampere card | Q4_K_M GGUF, 17 GB, running today | W4A16 checkpoints keep embeddings, lm_head and vision in BF16: ~22 GB before KV; needs a custom int8 embed/head requant to reach ~19 GB. NVFP4 is Blackwell-only. |
| Two slots at full context | `parallelSlots: 2`, `contextSize: 262144`, `--kv-unified` removed → 2 × 131,072 fixed; ≈ +1.1 GB at q8_0; est. ~18.5 GB. | `--max-num-seqs 2 --max-model-len 65536` at best with the requant. |
| Speculative decoding | DFlash drafter, on | None on this card (5.11 GB BF16 head; recipe needs a second card even on a 5090). ~45 tok/s. |
| Vision | mmproj in host RAM | Tower on-card in BF16 or dropped. |
| Reasoning control | `--reasoning-budget` + message, `--reasoning-preserve` | Prompt line only; empty-content truncation trap. |
| Ampere history here | Working | vLLM 0.25.1 crashed in the compressed-tensors quantised `lm_head` path on SM8.6. |
| Rollout awareness | llmkube `waitForIdle` reads `/slots` natively | Prometheus scrape |
| What vLLM would win | | Continuous batching beyond 2; typed `reasoning_content`; per-request spec metrics. Not needed at two slots. |

**Decision:** llama.cpp, `parallelSlots: 2`, `contextSize: 262144`, drop `--kv-unified`, keep the rest, bump to a b1093x digest. **This only pays with R8**; with `maxSupervisedTasks: 1` the second slot never sees a request. `[VERIFY]` after rollout: `/props` shows 2 slots at 131,072 each; VRAM under 20 GB; a 2-scout round shows two `is_processing` slots; host RSS under the 16 Gi limit during a concurrent round.

`[INHERITED]` `reasoningBudget: 16384` has no recorded rationale. A full-budget turn at the measured ~35–45 tok/s (drafter helps, exact figure unmeasured) is 6–8 minutes, longer than the Agent's 300 s turn timeout. **Decision:** keep 16384, raise the scout and falsifier `requestTurnTimeoutSeconds` to 900, record scout turn durations from the transcripts, and cut the budget to 8192 if p95 turn time exceeds 600 s.

Consumers: `cogito-planning-scout` `maxConcurrentTasks: 2`, `cogito-reviewer-falsifier` 1, both via the `scout` / `reviewer` aliases; LiteLLM key `maxParallelRequests` set to the slot count. A third concurrent request queues inside llama.cpp.

llama.cpp `--cache-prompt` is per slot, so prefix reuse (§6.2) lands only on the same slot; expect ~50 % on Muse. The large payoff is on Qwen.

### 3.3 LiteLLM: the single routing authority

Every consumer, Foreman included, calls LiteLLM. Aliases carry the model, the sampling pins, the effort level, timeouts and context declarations; keys carry scope, rate and parallel caps.

**Foreman aliases and keys (new)** `[DECISION]`:

| Alias | Backend | Pins | Key (`litellm-key-<name>`, scope) |
|---|---|---|---|
| `coder` | `openai/qwen3-8-27b` | `timeout: 3600`, context 131072, effort as measured for coding (start `medium`), drop client `temperature` and pin 0.2 until measured | `coder` → `[coder]`, `maxParallelRequests: 1` |
| `reviewer-qwen` | `openai/qwen3-8-27b` | `timeout: 1800`, context 131072 | `reviewer` → `[reviewer, reviewer-qwen]`, `maxParallelRequests: 2` |
| `reviewer` (exists) | `openai/muse-glimmer-30b`, vision | **drop `temperature`/`top_p`/`top_k`**, `timeout: 900` | same key |
| `scout` | `openai/muse-glimmer-30b` | drop sampling params; `timeout: 900`; context 131072 | `scout` → `[scout]`, `maxParallelRequests: 2` |

Each Agent becomes:

```yaml
provider: cloud-proxy
providerConfig:
  baseURL: http://litellm.llm.svc.cluster.local:4000/v1
  model: coder            # the alias, not a served id
  apiKeySecretRef: { name: litellm-key-coder, key: api-key }
```

`inferenceServiceRef` and `model` are left as-is for the FleetNode capability match `[VERIFY]` whether cloud-proxy Agents still require `installedModels` to contain `spec.model`; if not, drop both.

**Existing aliases, unchanged in role:** `planner` (Astra; effort **`high`** `[DECISION]`, `thinking_levels` updated to match per the "publish the achievable set" rule), `planner-local`, `coordinator` (Luna, reserved), `coordinator-heavy` (unused), `worker` (ad-hoc Qwen via pi/Hermes; cap 4), `worker-escalated`, `reviewer-escalated` (K3), `Qwen/Qwen3.8-27B-W4A16`, `Muse-Glimmer-30B`, `vision`, `embedder`, `reranker`. `flashnext` removed.

**Rules that stay:** no fallbacks (validator); escalation is a coordinator action using the `escalation` key; budgets for subscription models are rate and parallel caps, not USD; the session card shows turns and task counts, USD only for metered keys.

**What routing Foreman through LiteLLM costs, and how it is handled:**

- LiteLLM (one replica) is now on the worker hot path. Acceptable for a single operator; the existing ServiceMonitor and PrometheusRule cover it; add an alert for `litellm` pod absence mirroring `MatrixCoordinatorAbsent`.
- Foreman's `allowCloudProviders: false` and the coordinator manifest's `allowCloudReviewers: False` must both become true. Foreman can then no longer tell "Qwen via the proxy" from "Kimi via the proxy"; that guarantee is now the `coder`, `scout` and `reviewer` keys' scopes, which the catalogue validator enforces. Document the flip in the chart values next to the setting.
- Timeouts stack: LiteLLM alias `timeout` ≥ Foreman `requestTurnTimeoutSeconds`; LiteLLM router `timeout: 600` is overridden per alias.
- Seats are two layers: Foreman `maxConcurrentTasks` and key `maxParallelRequests`. Keep them equal.
- v1 milestone 0 (Responses↔chat translation) is moot: Astra is Responses-native on `chatgpt/`; Foreman speaks chat completions to local aliases.

### 3.4 Version notes

vLLM is pinned inside the syv-ai image (0.28.0) and not bumped independently. llama.cpp is pinned by digest; `--kv-unified` defaults on when `--parallel` is auto, so always set `parallelSlots` explicitly. Known LiteLLM break to retest on the next bump: non-streaming on `chatgpt/` at 1.97.0.

---

## 4. Architecture overview (after §13)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ PHONE (Commet)                                                           │
│  #project-cogito  thread = session; mentions only                        │
│  #agent-runs      scout threads, Workload phases, Hookshot; muted        │
│  #agent-alerts    alertmanager; mentions only                            │
│  DM @coordinator  direct sessions (§9)                                   │
│  push: Synapse → ntfy (push gateway) → UnifiedPush → Commet              │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ /sync (maubot, E2EE)      HMAC HTTP over localhost
┌───────────────▼──────────────────────────────────────────────────────────┐
│ matrix-coordinator (EXISTING, adapted)                                   │
│  SQLite v11, outbox (send/edit/react/upload), state machine, card +      │
│  progress edits, Astra turns, scout fan-out, plan issue + deliverables,  │
│  Workload sequencing, checks + quorum merge, escalation table, §9        │
└───┬────────────────────────────┬─────────────────────────┬───────────────┘
    │ Responses API              │ k8s API                 │ GitHub REST
    ▼                            ▼                         ▼
┌────────────────────┐   ┌──────────────────────┐   ┌──────────────────┐
│ LiteLLM (nuc)      │   │ Foreman 0.9.25       │   │ GitHub           │
│ planner (Astra)    │◄──│ Agents: cloud-proxy  │   │ plan issue,      │
│ coder, scout,      │   │ maxSupervisedTasks 4 │   │ sub-issues, PRs, │
│ reviewer(-qwen),   │   │ Workload pipeline    │   │ ruleset on main  │
│ coordinator (Luna) │   │ gate: flux-local     │   └──────────────────┘
│ keys = boundary    │   └──────────────────────┘
└────┬───────────────┘
     │ chat completions (local) · Responses (chatgpt/)
     ▼
┌─────────────────────────────────────────────────────────────┐
│ iggy  x16: Qwen 3.8-27B  syv-ai vLLM 0.28 (Jory profile,    │
│            SERVED_MODEL_NAME=qwen3-8-27b, A/B pending)       │
│       x4:  Muse Glimmer 30B llama.cpp, 2 × 131k slots,      │
│            Q4_K_M + DFlash + mmproj in host RAM             │
│ cloud via chatgpt/ OAuth: Astra, Luna                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. The gateway: adapt `matrix-coordinator` or rewrite it?

### 5.1 What exists (measured)

9 stdlib-Python modules, 1,656 lines of source, 45 tests (≈ 900 lines), a 152-line maubot plugin. Written 2026-09-10 to 09-13 in 51 commits. One pod, two containers, HMAC-signed JSON over localhost.

Already there and tested: SQLite v10 with replay idempotency and a durable, ordered outbox whose `notification_id` doubles as the Matrix `txn_id`; append-only audit; two-phase idempotency for GitHub writes; Astra over Responses with SSE reassembly and forced-draft mode; deterministic scout task names with 409 tolerance and `modelSummary` extraction; Agent Runs threads with redacted transcripts; plan issue with hash markers, sub-issues with `parent_issue_id` and `blocked_by`; SHA-pinned `merge-async` with polling; one Workload per deliverable, serial, two-distinct-reviewer quorum; metrics, five alerts, dashboard, RUNBOOK.

### 5.2 Gap table against the design

| Capability | Status | Adapt cost (est. lines) | Notes |
|---|---|---|---|
| Astra planning loop with scout delegation | Exists | 0 | |
| Ask the owner a question | Exists (`clarify`/`pushback`) | ~40 | Explicit `NEEDS_INPUT` flag for the state machine and mention gating. |
| Session `notes.md` working memory | Missing | ~100 | `plan_notes` table; re-injected on resume. |
| Result packets with schema | Partial | ~80 | Require §6.3's shape in the summary; validate; one retry. |
| Prefix protocol + hash logging | Missing | ~50 | Prompt assembly is in one place (`foreman.py:156-192`). |
| `inspect` / `cancel` / `followup` | `status` exists | ~120 + RBAC `agentictasks: delete` | |
| Durable, restart-safe state | Exists | 0 (schema v11) | |
| Explicit state machine | Partial (§5.3) | ~150 | |
| Session card + progress edited in place | Missing | ~150 | Outbox action `edit`; bot handler; renderer. |
| Reactions as controls | Missing | ~90 | |
| @mention on transitions only | Missing | ~30 | |
| Routing by state, no prefix | Partial | ~40 | |
| Per-room project config | Missing (repo hardcoded) | ~50 + Terraform | |
| Plan as section messages + file | Missing | ~90 | |
| Semantic changelog on revision | Missing | ~40 | |
| Multi-persona senders | Missing | 0 now; ~350 later | Glyph prefixes now; appservice transport later, E2EE kept. |
| Escalation table (§8.4) | Partial | ~120 | |
| **Wait for required checks before merge** (new in v3) | Missing | ~40 | Poll the PR's check-runs rollup; refuse `merge-async` until `flux-local-status` succeeds. |
| **`allowCloudReviewers: True` in the Workload manifest** (new in v3) | One line | 1 | With a comment naming key scope as the boundary. |
| Direct coordinator sessions (§9) | Missing | ~400 + RBAC + PVC | Largest new piece. |
| Images from the phone | Missing | ~80 | |

Adapt total: roughly **1,300–1,600 lines** on top of 3.2k that stay.

### 5.3 State mapping

| Design phase | Existing state | Change |
|---|---|---|
| `NEW` | `intake` | none |
| `DISCOVERING` | `researching` → `synthesizing` | none |
| `NEEDS_INPUT` | `intake` after `clarify`/`pushback`; `research_failed` | explicit; mention |
| `PLAN_READY` | `review` | mention |
| `REVISING` | `review` + comments + `revise` | ✏️ collects comments |
| `APPROVED` | `accepted` → `decomposed` | ✅ = `approve` |
| `EXECUTING` | `running` | none |
| `BLOCKED` | deliverable `failed` | explicit; mention; 🔄 re-creates the Workload |
| `REPLANNING` | none | Astra turn with the failure packet → new version → `review` |
| `DONE` | `completed` | mention |
| `PAUSED` / `CANCELLED` | none | suspend / stop dispatch; ⏹ closes issues |

### 5.4 Rewrite: what it would buy and cost

Buy: appservice-first transport with personas; phase-named state model; one async process; typed Foreman client. None visible from the phone. Cost: reproducing ~2,000 lines of tested plumbing before parity, then the same new features, and re-discovering the corner cases that are only recorded in tests and the RUNBOOK. **Decision:** adapt. Rewrite the 152-line transport only if personas are wanted.

### 5.5 Idempotency and restart

Unchanged mechanisms. Edits, reactions and uploads go through the same outbox. After R1, restarts are voluntary again.

---

## 6. The Foreman client

### 6.1 Interface

No separate MCP process. `coordinator/foreman.py` plus the research tables:

```
delegate_research(tasks[≤4])   exists → AgenticTask kind: freeform, agentRef: cogito-planning-scout
status(plan|workload)          exists
followup(task, question)       new → child task carrying the parent summary in [task]
cancel(task)                   new → delete AgenticTask
results(task)                  exists → status.result + transcript ConfigMap
```

Concurrency: FleetNode `maxSupervisedTasks: 4` (R8) is the cluster ceiling; Agent `maxConcurrentTasks` (scout 2, coder 1, reviewer 1, falsifier 1) and key `maxParallelRequests` are the per-role seats. Model choice is by alias, set on the Agent's `providerConfig.model`.

### 6.2 Prefix protocol

```
[system prompt for role]      Agent CR systemPrompt (stable, versioned by GitOps)
[repo preamble]               repository + base branch + repo map (regenerated on base SHA change)
[plan excerpt, if executing]  stable per plan version
[task]                        varies
```

No timestamps or task ids above `[task]`. Log `sha256(prefix)` as an AgenticTask annotation. LiteLLM passes prompts through unchanged, so the protocol survives the proxy; verify hit rate from llama.cpp `/metrics` and the syv-ai server's counters.

### 6.3 Result packet

v1's YAML shape as the required content of the scout's `submit_result` summary (≤4000 chars); Foreman wraps it; the coordinator parses `modelSummary` (R5) and validates. No object-storage bucket is added; transcript ConfigMaps are bounded and redacted.

### 6.4 Worker pods

One Job per task, clone at base branch, tool whitelist per Agent, SA `foreman-coder`. Changes: all four LLM-backed Agents use the derived image `ghcr.io/timblakely/cogito-foreman-planning-scout` (upstream coder image + `gh`, `jq`, `unzip`), renamed to `cogito-foreman-agent` since it is no longer scout-specific `[DECISION]`; `[VERIFY]` that scout Job pods carry no push-capable token.

---

## 7. Plans: format, storage, review

### 7.1 Format

v1's front-matter `steps` with `depends_on`, `mode`, `acceptance`, `guardrails.never_touch`. Each top-level step → one sub-issue → one Workload; `acceptance` → the issue's acceptance checklist; `depends_on` → `blocked_by`.

### 7.2 Storage

No `agent-plans` repo. `plan_versions` (unique content hash, unique Matrix event id) plus the accepted hash in the plan issue body is the audit trail.

### 7.3 Review in Matrix

Section messages, reply-to-section comments, ✅ / ✏️ on the card, semantic changelog, attached `plan.md`. Bare `approve` is already safe (approvals older than the current version are rejected).

---

## 8. Execution

### 8.1 Coordinator

Deterministic. On `APPROVED`: plan issue and sub-issues, then one Workload per deliverable, serially. Each Workload runs Foreman's pipeline: `cogito-coder` (Qwen via `coder`) → `cogito-gate` → `cogito-reviewer` (Qwen via `reviewer-qwen`) and `cogito-reviewer-falsifier` (Muse via `reviewer`) → PR → **required checks** → quorum → async squash merge → next. One repair round (`maxReviewIterations: 1`, a deliberate coordinator choice).

### 8.2 Git model

Foreman's: one branch per Workload, one PR per deliverable to `main`, merged in order. No integration branch.

### 8.3 Concurrency

With R8, a round of two scouts runs concurrently on Muse's two slots while a coder runs on Qwen. Four scouts: two run, two queue in Foreman. Muse host RSS under a concurrent round is the number to watch.

### 8.4 Escalation boundary (coordinator code)

| Discovery during execution | Action |
|---|---|
| Gate fails, reviewer NO-GO, coder needs another try | Foreman repair round; then Workload fails |
| Merge conflict on a later deliverable | Coordinator re-creates the Workload against new `main` (🔄) |
| Deliverable fails after Foreman's rounds | `BLOCKED` → @mention; 🔄 retries, ⏹ cancels, a reply with guidance re-creates the Workload with the reply appended to the issue |
| Deliverable text intersects `guardrails.never_touch` | `NEEDS_INPUT` → owner, before any Workload is created |
| Required check fails on the PR | `BLOCKED` with the check summary; never merged |
| Owner says the approach won't work, or two consecutive deliverables block | `REPLANNING` → Astra with failure packets → new version → `PLAN_READY` |
| Local reviewers disagree repeatedly | Re-run review with `reviewer-escalated` via the `escalation` key (explicit, logged) |

### 8.5 Code review and merge safety `[DECISION]`

Three layers, none of which existed in v2:

1. **Gate.** `gateProfile.commands.test` runs `flux-local test` (the same `ghcr.io/allenporter/flux-local:v7.11.0` invocation as `.github/workflows/flux-local.yaml`) when `git diff --name-only HEAD^ HEAD` touches `kubernetes/`, and the repository's own checks otherwise (`python -m unittest discover -s tests` for `services/matrix-coordinator/`). `git diff --check` stays as `lint`. The gate image must carry `flux-local`; use its image as the gate image for kubernetes changes, or a derived gate image with both toolchains `[VERIFY]` which is simpler under Foreman's single `gateProfile.image`.
2. **Ruleset on `main`** requiring the `flux-local-status` check for all pushes, including the GitHub App's. No bypass actors.
3. **Coordinator waits.** Before `merge-async`, poll the PR head's check-runs rollup; merge only when required checks succeed; `BLOCKED` on failure.

Hookshot posts PR events to `#agent-runs`. Optional owner-gate before merge stays a config flag.

### 8.6 Observability

Transcripts as ConfigMaps + Agent Runs threads. Prefix hash annotations. LiteLLM now sees every worker call, so per-key spend, latency and error rate for `coder`, `scout`, `reviewer` come from the existing LiteLLM dashboard; llama.cpp and vLLM metrics via the existing ServiceMonitors for cache hits and slot occupancy.

---

## 9. Direct coordinator sessions

Evaluate Hermes first: reconnect it to LiteLLM (`coordinator` for Luna, `worker` for Qwen, `Muse-Glimmer-30B` for images) and judge the couch experience. If insufficient, the harness bridge as v1 §9 (Codex or pi in a Foreman-managed pod, PVC session dir, bridged to a DM thread). Codex needs Responses; the `coordinator` alias is Responses-native; Qwen and Muse would need LiteLLM's translation `[VERIFY]` only in that case.

---

## 10. Matrix conventions

Rooms as deployed: `#project-cogito` (session threads; mentions only, plus v3 mention gating), `#agent-runs` (muted), `#agent-alerts`, DM `@coordinator`. One persona for now with glyph prefixes. `!cogito` stays as an alias; `status`, `stop`, `approve` work bare; card reactions are the controls.

---

## 11. Notifications

Done: Synapse → ntfy → UnifiedPush → Commet. Add @mention only on `NEEDS_INPUT`, `PLAN_READY`, `BLOCKED`, `DONE`, `CANCELLED`. Route `MatrixCoordinatorAbsent/Down` and a new LiteLLM-absent rule to the out-of-band ntfy topic.

---

## 12. Security and budgets

- Astra: no world tools. Coordinator SA: `workloads` create/get/list/watch, `agentictasks` create/get/list/delete, `configmaps` get.
- **The local/cloud boundary is key scope.** `coder` → `[coder]`, `scout` → `[scout]`, `reviewer` → `[reviewer, reviewer-qwen]`. No worker key can reach a metered or subscription alias. Foreman's `allowCloudProviders` and `allowCloudReviewers` are true and documented as such.
- Worker pods: as deployed; verify token scope (§6.4).
- `guardrails.never_touch`: checked before Workload creation; `kubernetes/`, `talos/`, secrets and RBAC route to the owner. Independently, R9 means nothing under `kubernetes/` merges without flux-local.
- Budgets: rate and parallel caps on subscription models; USD caps on `escalation`; per-session counts (scout tasks, deliverables, Astra turns).
- Prompt injection: scout summaries are data; GitHub issue bodies written by the coordinator are the only text Foreman executes from.

---

## 13. Build order

| # | Milestone | Done when |
|---|---|---|
| **R0** | **Cluster repair** (R1–R9) | No involuntary Deployment roll for 2 h; a coder turn completes via LiteLLM (`coder` key shows the call); `flux get ks -A` all Ready; iggy memory requests < 50 %; Muse `/props` shows 2 slots and FleetNode capacity 4; a ruleset on `main`; PR 22 resolved. |
| 1 | **Real plan end to end** | One Commet-originated plan with two deliverables researches with two concurrent scouts, is approved, runs two Workloads, passes required checks, merges via quorum, posts `Completed`. Scout turn counts < 40. |
| 2 | **Session card, reactions, mentions, state machine** | Card edited on every transition; reactions work; pings only on the five states; restart mid-plan loses nothing. |
| 3 | **Plan review surface** | Sections as messages, reply-to-section comments, changelog, attached file, bare `approve`. |
| 4 | **Escalation table + notes** | Forced `BLOCKED`, `REPLANNING`, guardrail intercept and a failed required check exercised; a three-day-old session resumes from notes. |
| 5 | **Per-room projects + prefix protocol + packets + Qwen A/B** | Second project room; prefix hit rate measured; packet schema validated; `SPEC`/`CTX` A/B recorded in `bench-notes.md`. |
| 6 | **Direct sessions** | Hermes evaluated; DM → coding turn with a PVC workspace and image input, or the harness bridge. |
| 7 | **Personas + polish** | Optional appservice transport; dashboards; retire the `!cogito` prefix requirement. |

---

## 14. Open items to verify

1. `[VERIFY]` R1: does the foreman-agent process need a fresh GitHub token after the Reloader opt-out?
2. `[VERIFY]` R2(b): cloud-proxy Agents and the FleetNode `installedModels` / `requiredCapability` match; whether `inferenceServiceRef` can be dropped.
3. `[VERIFY]` Muse two-slot VRAM, concurrency, and host RSS under a concurrent round (R8).
4. `[VERIFY]` Gate image for flux-local under Foreman's single `gateProfile.image`.
5. `[VERIFY]` Scout Job pods carry no push-capable token.
6. `[VERIFY]` Commet renders `m.poll`.
7. `[VERIFY]` Hermes reconnected to LiteLLM is a usable direct session.
8. `[VERIFY]` LiteLLM Responses↔chat translation, only if Codex is the §9 harness.
9. `[VERIFY]` Prefix-cache hit rate on the syv-ai server through LiteLLM.
10. Measure: Qwen `SPEC`/`CTX` A/B; Muse scout turn p95 against the reasoning budget; coder effort level.
11. Upstream: Foreman's no-diff gate on `freeform` tasks (R5); Foreman re-creating Jobs for terminal tasks on agent restart.

---

## 15. Glossary

- **Astra** — `planner` alias (`chatgpt/gpt-6-astra`, effort high). **Luna** — `coordinator` alias, reserved for direct sessions. **K3** — `reviewer-escalated`.
- **Foreman** — upstream llmkube agent scheduler; executes deliverables as coder → gate → reviewers → PR. **FleetNode** — the single foreman-agent on iggy; `maxSupervisedTasks` is its concurrency.
- **cloud-proxy** — Foreman's provider mode for an OpenAI-compatible gateway; here, LiteLLM for every Agent.
- **matrix-coordinator** — the existing planning gateway, adapted.
- **Scout** — `cogito-planning-scout` Agent (Muse via `scout`). **Falsifier** — `cogito-reviewer-falsifier` (Muse via `reviewer`), the quorum's second model family.
- **Session card / progress message** — two thread messages edited in place.
- **syv-ai stack** — `ghcr.io/syv-ai/qwen38-27b-rtx3090`, vLLM 0.28.0 + patches, env-configured; profile inherited from Jory.
- **flux-local-status** — the CI summary check that the `main` ruleset requires.

## 16. Sources consulted (2026-09-13)

- Repo `timblakely/cogito-ops` @ `5c850664`: `services/matrix-coordinator/`, `kubernetes/apps/llm/{llmkube,foreman,litellm}/`, `kubernetes/apps/home-infra/{matrix,matrix-coordinator,matrix-hookshot}/`, `.github/workflows/flux-local.yaml`, `foreman_migration_pathway.md`, `matrix_development_coordination.md`, `plans/llm/*`, `GEMINI.md`.
- Live cluster: pods, Deployments/ReplicaSets, Foreman CRDs (`Agent.spec.provider`/`providerConfig`, `Workload.spec.maxReviewIterations`/`allowCloudReviewers`, FleetNode `supervisionCapacity`), AgenticTask statuses and transcripts, `nvidia-smi` in the serving pods, llama.cpp `/props` and `/slots`, InferenceService `/v1/models`; `gh api` branch protection on `cogito-ops`.
- Foreman chart values (`oci://ghcr.io/defilantech/charts/foreman` 0.9.25): `maxSupervisedTasks` comment.
- syv-ai/qwen38-27b-rtx3090 README — https://github.com/syv-ai/qwen38-27b-rtx3090
- llama.cpp server README and releases (b10936) — https://github.com/ggml-org/llama.cpp
- vLLM releases (v0.29.0) and Muse Glimmer recipe — https://github.com/vllm-project/vllm/releases, https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B
- RedHatAI/Muse-Glimmer-30B-W4A16 — https://huggingface.co/RedHatAI/Muse-Glimmer-30B-W4A16
- Hardware Corner, Muse Glimmer 30B on RTX 3090 — https://www.hardware-corner.net/hardware-for-muse-glimmer-30b-llm/
- defilantech/llmkube — https://github.com/defilantech/llmkube
- v1 audit page — https://claude.ai/code/artifact/8342d002-3e65-4ae8-a140-9bf27ddafea8
