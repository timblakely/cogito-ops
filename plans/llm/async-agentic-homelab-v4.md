# Async Agentic Homelab: Matrix-driven planning and execution on a Talos Kubernetes cluster

**Status:** core implementation deployed; a two-deliverable acceptance run completed on 2026-09-14. Hermes direct sessions (§9) are implemented pending the owner-device DM check. Phone image ingestion is deployed and passed an in-cluster Muse vision probe; the owner-device encrypted-media check remains. Prefix-free project-room intake is deployed and accepted. No required implementation work remains; optional appservice personas and owner-device checks are deferred. Supersedes v3 (2026-09-13), v2 (same day), and v1 (2026-09-12).
**Audience:** a reviewer with no prior context. Markers: `[VERIFY]` unverified, `[DECISION]` contestable choice, `[OBSERVED]` seen on the live cluster on 2026-09-13, `[INHERITED]` an upstream or colleague's default rather than a choice made here.

---

## Changelog v3 → v4

v3 corrected inherited defaults and moved Foreman behind LiteLLM. v4 fixes a role error that ran through v2 and v3 and adopts the owner's GitHub-centred plan flow.

| Area | v3 | v4 |
|---|---|---|
| The coordinator role | Deterministic code; "no Luna in the execution path" | **Luna is the coordinator**, an LLM agent (`coordinator` alias, `chatgpt/gpt-5.6-luna`, `reasoning_effort: max`) that supervises execution at the **Workload level** and triages every GitHub and Matrix event after a plan is drafted. The deterministic process is the **gateway**. |
| Service name | `services/matrix-coordinator` | **`services/gateway`**, deployment `gateway`, Matrix account unchanged. The `coordinator` alias, key and role belong to Luna. |
| Plan object | Matrix thread until approval; GitHub issue created at approval as a frozen record | **GitHub issue from first draft.** Astra writes the plan as the issue body; revisions are body edits (GitHub keeps edit history); the owner reviews with issue comments; approval is the `workflow/approved` label. The Matrix thread carries status, questions, and links, not the plan text. |
| Approval | ✅ reaction or `approve` in Matrix | `workflow/approved` label applied by the owner, **or** a `/approve` issue comment that the gateway turns into the label. Body hash frozen at that moment. |
| GitHub → system | Not consumed (dead route) | **Repository webhook straight to the gateway**, unfiltered by source `[DECISION]`, coalesced by time, every batch a Luna turn. Hookshot mirrors everything into a muted `#github` room as a debugging stream. |
| Sub-issues | Created at approval | Same, made explicit: the draft is one issue with a deliverables checklist (nested for sub-deliverables); sub-issues are created and linked after approval. |
| Implementation surface | `#agent-runs` phase messages + completion in the plan thread | **Implementation room**, one thread per approved plan, opened by Luna, linking the plan thread and the issues; Luna posts there; owner instructions there go to Luna. |
| Scouts | Muse only | **Muse and Qwen scout Agents**; Astra names the model per task or the gateway alternates. |
| Inline code review | Not possible | Reviewer packets carry file/line evidence; the gateway posts them as **PR review comments**; owner PR comments come back through the webhook to Luna. |
| Token accounting | USD only for metered keys | **Luna turns and tokens per plan** on the card and in Prometheus; per-plan turn cap enforced by the gateway. |
| Task-level Luna | v1 §8 model, dropped | Retained as a future option (§8.7); not built. |

Everything else from v3 stands: the nine repairs (R1–R9), Foreman behind LiteLLM, two-slot Muse on llama.cpp, syv-ai Qwen, E2EE on, SQLite, adapt-not-rewrite, single bot account with glyph prefixes.

---

## 0. Executive summary

The owner runs a Talos/Flux Kubernetes cluster with two RTX 3090s on one node, a Synapse homeserver used from Android via Commet, upstream llmkube + Foreman for agent scheduling, a LiteLLM catalogue fronting local and ChatGPT-subscription models, and an existing Matrix gateway service that already drives an Astra planning loop with local scouts and hands deliverables to Foreman. The owner has a newborn and operates from a phone in short bursts.

The system has three tiers, and every design choice below is checked against them:

- **Astra is the brains.** Intelligent, sparse, low tokens. Plans, revises, answers plan-content questions. Never reads a transcript, log or diff.
- **Luna is the coordinator.** Cheap (subscription), reactive, moderate tokens. Triages events, supervises execution one Workload at a time, decides retries and escalation, delegates any reading to local scouts.
- **Local models are the workhorses.** Free tokens. Research, implementing, tool calling, testing, searching, describing images, log spelunking, review, and anything else that burns significant tokens.

The **gateway** is the only deterministic process: Matrix transport, GitHub webhook and API, Foreman client, SQLite state, the outbox, and the hard limits Luna cannot talk around (budgets, guardrails, quorum, required checks, per-plan Luna turn cap).

---

## 1. Context for the reviewer

### 1.1 The owner and the operating constraint

Android phone, short attention windows, resume after days away, one thumb. Simplify the interaction surface, not the infrastructure.

### 1.2 Existing infrastructure (corrected inventory)

All rows exist today at repo commit `5c850664`.

| Component | What it is | Facts relevant to this design |
|---|---|---|
| **Talos cluster** | 5 nodes (`iggy`, `kristeva`, `nuc-1/2/3`), all control-plane, Kubernetes 1.34.2, Flux-managed from `timblakely/cogito-ops` (this repo). | iggy on Talos v1.13.5, the rest v1.12.5 (deliberate; converge later). |
| **llmkube 0.9.27** | Operator for inference servers: `Model`, `InferenceService`; runtimes `llamacpp`, `vllm`, `generic`. | syv-ai image as `runtime: generic`, Muse as `runtime: llamacpp`. `rolloutPolicy.waitForIdle`, `parallelSlots`, `speculativeDecoding`, `reasoningBudget`. GPUs UUID-bound via `NVIDIA_VISIBLE_DEVICES`. |
| **Foreman 0.9.27** (upstream, `defilantech/llmkube`) | Agent scheduler. CRDs `Agent`, `AgenticTask`, `Workload`, `FleetNode`, `ModelProfile`, `AgentRelease`. `Workload` runs a fixed pipeline per issue: coder → gate Job → reviewer(s) → PR, with `maxReviewIterations` repair rounds. `AgenticTask kind: freeform` for read-only scouts. | `Agent.spec.provider` is `local` or **`cloud-proxy`** (`providerConfig.baseURL/model/apiKeySecretRef`; "typically a LiteLLM gateway"), gated by `allowCloudProviders` and per-Workload `allowCloudReviewers`. One FleetNode on iggy; `maxSupervisedTasks` bounds cluster-wide concurrency. Result contract: `submit_result` → `verdict GO/NO-GO + summary` plus a transcript ConfigMap. Foreman does not plan across issues. |
| **LiteLLM 1.97.0** | Proxy with a GitOps catalogue, validated by `scripts/validate-llm-catalogue.py`. | **No fallbacks, by decision.** `LiteLLMVirtualKey` CRs materialise `litellm-key-<name>` Secrets in `llm`. `chatgpt/` OAuth for Astra and Luna (cost 0, quota-limited); metered OpenAI and Moonshot. One replica. |
| **services/matrix-coordinator** → **gateway** | maubot transport container + stdlib-Python process, SQLite schema v10 on a volsync-backed PVC. | Astra via Responses API with `delegate_research` (≤4 scouts × ≤2 rounds), `!cogito plan/draft/revise/approve/status`, plan issue + sub-issues with native dependencies, one Workload per deliverable, two-reviewer quorum, SHA-pinned async squash merge. 45 unit tests. Renamed in v4. |
| **Synapse 1.160.0** | Homeserver on CNPG. | One appservice registered (Hookshot); MSC3202/MSC2409 enabled. Push to ntfy. |
| **Rooms** (Terraform) | Space `Agents`: `#agent-control`, `#agent-alerts`, `#agent-plans`, `#agent-runs`, `#project-cogito`. | All E2EE, invite-only. v4 adds `#implementation` and `#github`. |
| **Commet** | Owner's Matrix client. | `[VERIFY]` `m.poll`. |
| **ntfy 2.27** | UnifiedPush distributor and Matrix push gateway. | Working. |
| **Hookshot 7.4.4** | GitHub App 4906005 + generic webhooks. | The App's single webhook URL points at Hookshot. Events currently land in `#agent-runs`. |
| **GitHub App 4906005** | Shared by Hookshot, the gateway and Foreman (installation tokens via the External Secrets generator). | One App has one webhook URL, so the gateway's webhook is a **repository webhook**, not the App's (§6.5). |
| **CI on cogito-ops** | `.github/workflows/flux-local.yaml` on `pull_request` to `main`, summary job `flux-local-status`. | `main` is unprotected. |
| **Hermes** | Matrix agent bot `@hermes`. | v4 direct sessions: E2EE, owner-only, backed-up session state; `coordinator` via LiteLLM Responses by default, local Qwen/Muse aliases via chat completions. |
| **Reloader** | Cluster-wide `autoReloadAll: true`. | Root cause of R1. |

### 1.3 Cluster hardware (as it is)

| Node | Hardware | Role |
|---|---|---|
| **iggy** | Ryzen 9, 128 GB DDR4, 2 × RTX 3090 24 GB (x16 `GPU-a598…`, x4 `GPU-787b…`), 250 W limit. | Qwen on x16, Muse on x4. Foreman agent, gate cache, 450 Gi model cache. After R3: ~40 Gi RAM requests. |
| **kristeva** | Dual Xeon, 128 GB DDR3, Arc A380. | `bge-m3`, `bge-reranker-v2-m3`, `vision-cpu`. |
| **nuc-1/2/3** | Meteor Lake NUCs, Thunderbolt ring. | Ceph, Qdrant, LiteLLM, Matrix, gateway, Hookshot. No LLM serving. |

No 5070 Ti node; out of scope.

### 1.4 Decisions already made

From the pathway documents: Foreman replaced the Argo path outright; quorum auto-merge with two distinct reviewer Agents; Astra delegates to local scouts, no paid fallback. **Superseded by v4:** "a Matrix thread is the plan-review object; a GitHub issue is the accepted-work object". In v4 the issue is the plan object for its whole life and the thread is the status and conversation surface. Update `matrix_development_coordination.md` and `foreman_migration_pathway.md` when v4 lands.

From `plans/llm/plan.md` (locked): coordinator pattern, no autorouting; no cross-model proxy fallbacks; GLM 5.3 skipped; K3 is `reviewer-escalated` only.

From v2/v3: flashnext removed (weights PVC kept); 5070 Ti ignored; llmkube + Foreman stay; syv-ai Qwen is the Qwen lane; Muse two slots on llama.cpp; E2EE on; SQLite; adapt not rewrite; Foreman behind LiteLLM; `maxSupervisedTasks: 4`; gate runs flux-local and `main` gets a ruleset; Astra at `high`; inherited knobs labelled and measured.

From v4 `[DECISION]`:

- **Luna is the coordinator**, at `reasoning_effort: max` (the alias's current pin), supervising at the Workload level for the initial implementation (§8.1). Task-level supervision is documented for later (§8.7).
- **The GitHub issue is the plan object** from first draft (§7).
- **Approval = `workflow/approved` label**, applied by the owner or by the gateway on a `/approve` comment. Replaces `workflow/accepted`.
- **The webhook is unfiltered by source**; the gateway coalesces by time; Luna turns and tokens are measured per plan. Levers if quota is stressed, in order: coalescing window, alias effort, source filtering.
- **Service renamed to `gateway`.** One Matrix account with glyph prefixes: `◆ Astra`, `● Luna`, `▣ gateway`.
- **Luna triages; Astra answers plan content.**

### 1.5 Cluster repair list `[OBSERVED 2026-09-13]`

Prerequisites, unchanged from v3 except R2's target names.

| # | Fault | Fix |
|---|---|---|
| **R1** | `foreman-agent` and the gateway Deployments roll every 30 min (GitHub token secret refresh × Reloader `autoReloadAll`). Rolls drain the FleetNode, expire scout claims, and re-create Jobs for every AgenticTask including day-old successes. | `reloader.stakater.com/auto: "false"` on both Deployments (app-template `controllers.<name>.annotations`; kustomize patch for agent Deployments). `[VERIFIED 2026-09-14]` the long-lived supervisors need no `GITHUB_TOKEN`; execution Jobs receive the current App token at creation through `coderGitSecret`, and verifier clones of this public repository are anonymous. |
| **R2** | Coder and reviewer 404 (`qwen3-8-27b` requested, `qwen3.8-27b` served). | (a) `SERVED_MODEL_NAME=qwen3-8-27b` on the Qwen InferenceService; revert the three LiteLLM backends to `openai/qwen3-8-27b`. (b) All LLM-backed Agents to `provider: cloud-proxy` against LiteLLM with per-role aliases and keys (§3.3). |
| **R3** | Flux `llm` unhealthy since 09-08 (`flashnext-stage-v1` Failed); flashnext rollout stuck on a 76 Gi surge. | Remove flashnext manifests and the LiteLLM alias; delete the Job and ConfigMap; keep the PVC. |
| **R4** | Muse Agents sample at 0.2 / 0.1; scouts looped 78 turns. | Delete `temperature` from Muse Agents; pin sampling at the alias; scout turn timeout 900. |
| **R5** | Read-only scouts recorded NO-GO (coder no-diff gate on `freeform`). | Upstream issue; never key on scout `verdict`. |
| **R6** | PR 22 cannot reach quorum (pre-falsifier Workload). | Merge or close by hand; delete the Workload. |
| **R7** | GPU lanes roll with `RollingUpdate`; scouts got `connection refused`. | `rolloutPolicy.waitForIdle: true` on both GPU InferenceServices, plus a narrowly scoped `MutatingAdmissionPolicy` that forces `Recreate` on the two UUID-bound Deployments. LLMKube only selects `Recreate` when it owns a GPU resource allocation; these lanes intentionally bind UUIDs without one. |
| **R8** | `agent.maxSupervisedTasks: 1` serialises every task cluster-wide; the scout's `maxConcurrentTasks: 2` never applied. | `maxSupervisedTasks: 4`; re-check Muse host memory under a concurrent round. |
| **R9** | Gate is `git diff --check`; `main` unprotected; merge does not wait for CI. | Gate runs flux-local for `kubernetes/` changes; ruleset on `main` requiring `flux-local-status`; gateway waits for checks before merge. |

---

## 2. Roles and the conceptual hierarchy

```
You          ask in a room; answer questions in the thread; review and approve the plan issue on
             GitHub; comment on PRs; give Luna instructions in the implementation thread.
Astra        WHAT. `planner` alias, gpt-6-astra, effort high, Responses API. Tools: delegate_research,
             ask_owner, publish_plan (writes the issue body), update_notes. Never sees raw material.
Luna         HOW. `coordinator` alias, gpt-5.6-luna, effort max. An agent loop in the gateway with
             bounded tools: Workload create/status, task packets, spawn_scout, cancel, issue comment,
             PR/check metadata, Matrix post, ask_astra, request_revision, escalate. Never sees raw
             material either: transcripts, logs and diffs are read by scouts and returned as packets.
Gateway      deterministic. Matrix transport + outbox, GitHub webhook + API, Foreman client, SQLite,
             coalescing, truncation, and the hard limits: budgets, turn caps, guardrails, quorum,
             required checks, approval-hash freeze.
Foreman      executes one Workload per deliverable: coder → gate → two reviewers → PR.
Local        Muse and Qwen scouts (research, diagnosis, log reading, image description), Qwen coder,
             Qwen + Muse reviewers, gate Jobs.
```

Two phases, one durable object each:

- **Planning.** Thread in the project room ⇄ Astra, with scouts through Foreman. Output: a GitHub issue whose body is the plan.
- **Implementation.** Thread in the implementation room ⇄ Luna, with Foreman Workloads per deliverable and scouts for diagnosis. Output: one PR per deliverable, merged in order; the plan issue closes on the last merge.

Between them: the plan issue, reviewed on GitHub, approved by label.

---

## 3. Models and serving

Unchanged from v3 except where noted. Summary here; §3 of v3 has the measurements.

### 3.1 Card 1 (x16): Qwen 3.8-27B on the syv-ai stack `[DECISION: this must work]`

`InferenceService/qwen3-8-27b`, `runtime: generic`, syv-ai image (vLLM 0.28.0 + patches), env `SPEC=dflash2 PREFIX_CACHE=1 CTX=long MAX_SEQS=5 VISION=0` `[INHERITED from Jory's profile]`, `[OBSERVED]` 22.9 GB VRAM. R2 adds `SERVED_MODEL_NAME=qwen3-8-27b`. Profile kept to get moving; A/B `SPEC` and `CTX` on scout- and coder-shaped prompts before calling it settled (milestone 5). Consumers: coder, one reviewer, the new Qwen scout.

### 3.2 Card 2 (x4): Muse Glimmer 30B, two slots `[DECISION]`

`InferenceService/muse-glimmer-30b`, llama.cpp `server-cuda` (b10920 → b1093x), Q4_K_M + DFlash drafter + mmproj in host RAM, `[OBSERVED]` 17.1 GB VRAM with one 131k slot. v4 config: `parallelSlots: 2`, `contextSize: 262144`, `--kv-unified` removed (2 × 131,072 fixed, est. ~18.5 GB). Only useful with R8. `reasoningBudget: 16384` `[INHERITED]` kept with turn timeout 900 and a p95 rule (cut to 8192 if p95 turn > 600 s). Consumers: Muse scout, falsifier reviewer, vision for owner images.

### 3.3 LiteLLM: the single routing authority

Every consumer calls LiteLLM. Foreman Agents use `provider: cloud-proxy` with `providerConfig.baseURL: http://litellm.llm.svc.cluster.local:4000/v1`, `providerConfig.model: <alias>`, `providerConfig.apiKeySecretRef: litellm-key-<role>`.

| Alias | Backend | Pins | Key, scope, parallel |
|---|---|---|---|
| `planner` | `chatgpt/gpt-6-astra` | Responses, effort **high** | `planner`, existing |
| `coordinator` | `chatgpt/gpt-5.6-luna` | Responses, effort **max**, drop `temperature` | `coordinator`, existing (30 rpm, 4 parallel) |
| `coder` | `openai/qwen3-8-27b` | timeout 3600, ctx 131072 | `coder` → `[coder]`, 1 |
| `reviewer-qwen` | `openai/qwen3-8-27b` | timeout 1800 | `reviewer` → `[reviewer, reviewer-qwen]`, 2 |
| `reviewer` (exists) | `openai/muse-glimmer-30b`, vision | drop sampling params, timeout 900 | same key |
| `scout` | `openai/muse-glimmer-30b` | drop sampling params, timeout 900 | `scout` → `[scout, scout-qwen]`, 3 |
| `scout-qwen` (new) | `openai/qwen3-8-27b` | timeout 900 | same key |
| `worker`, `worker-escalated`, `reviewer-escalated`, `planner-local`, `Qwen/…`, `Muse-Glimmer-30B`, `vision`, `embedder`, `reranker` | as today | | `flashnext` removed |

Rules: no fallbacks; escalation is a Luna action through the `escalation` key; subscription models are capped by rate and turns, not USD; Foreman's `allowCloudProviders` and `allowCloudReviewers` flip to true and the local/cloud boundary is key scope.

### 3.4 Version notes

vLLM pinned inside the syv-ai image; llama.cpp by digest; `--kv-unified` defaults on under auto `--parallel`, so always set `parallelSlots`. Retest non-streaming on `chatgpt/` at the next LiteLLM bump.

---

## 4. Architecture overview (after §13)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ PHONE (Commet)                                     GitHub Mobile           │
│  #project-cogito    plan threads; mentions only    plan issue: read, edit, │
│  #implementation    one thread per plan; mentions  comment, label          │
│  #github            Hookshot firehose; muted       PRs: diff, inline       │
│  #agent-runs        scout transcripts; muted       comments                │
│  #agent-alerts      alertmanager; mentions                                 │
│  push: Synapse → ntfy → UnifiedPush → Commet                               │
└──────────────┬─────────────────────────────────────────────┬───────────────┘
               │ /sync (maubot, E2EE)                        │ repo webhook (HMAC)
┌──────────────▼─────────────────────────────────────────────▼───────────────┐
│ gateway (EXISTING service, renamed, adapted)                               │
│  transport + outbox (send/edit/react/upload) · SQLite v11 · reconciler     │
│  webhook ingest → coalesce (30 s) → Luna turn                              │
│  Astra client (Responses + 4 tools) · Luna agent loop (Responses + tools)  │
│  Foreman client · GitHub client · truncation of everything models see      │
│  hard limits: approval hash, turn caps, guardrails, quorum, required checks│
└───┬──────────────────────────┬─────────────────────────┬───────────────────┘
    │ Responses API            │ k8s API                 │ GitHub REST (App)
    ▼                          ▼                         ▼
┌────────────────────┐  ┌──────────────────────┐  ┌────────────────────────┐
│ LiteLLM            │  │ Foreman 0.9.27       │  │ GitHub                 │
│ planner (Astra)    │◄─│ Agents: cloud-proxy  │  │ plan issue (body=plan, │
│ coordinator (Luna) │  │ maxSupervisedTasks 4 │  │ edits=versions, label= │
│ coder, scout(-qwen)│  │ Workload pipeline    │  │ approval), sub-issues, │
│ reviewer(-qwen)    │  │ gate: flux-local     │  │ PRs + inline reviews,  │
│ keys = boundary    │  └──────────────────────┘  │ ruleset on main        │
└────┬───────────────┘                            └────────────────────────┘
     ▼
┌─────────────────────────────────────────────────────────────┐
│ iggy  x16: Qwen 3.8-27B  syv-ai vLLM 0.28 (Jory profile)    │
│       x4:  Muse Glimmer 30B llama.cpp, 2 × 131k slots       │
│ cloud via chatgpt/ OAuth: Astra, Luna                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. The gateway: adapt `services/matrix-coordinator`, renamed

### 5.1 What exists (measured)

9 stdlib-Python modules, 1,656 lines of source, 45 tests (~900 lines), a 152-line maubot plugin; 51 commits over three days. Durable outbox with deterministic `txn_id`s, replay idempotency, append-only audit, two-phase GitHub writes, Astra over Responses with SSE reassembly, deterministic scout task names, redacted transcripts, plan issue + sub-issues with `parent_issue_id` and `blocked_by`, SHA-pinned `merge-async`, serial Workloads, two-distinct-reviewer quorum, metrics, alerts, dashboard, RUNBOOK.

### 5.2 Gap table at proposal time

This is the 2026-09-13 implementation baseline, retained for design review;
`Missing` and `Partial` below do not describe the current deployed state. See
the status header and `kubernetes/acceptance/async-agentic-v4.md` for current
evidence.

| Capability | Status | Adapt cost (est. lines) | Notes |
|---|---|---|---|
| Rename to `gateway` | — | ~30 + manifests | Directory, image name, workflow, HelmRelease, Kustomization, dashboards. Matrix account unchanged. |
| Astra planning loop with scout delegation | Exists | ~30 | Add a `model` hint (`scout` / `scout-qwen`) to `delegate_research`; default alternates. |
| Owner interjection mid-research | Dropped today | ~30 | Queue as context for Astra's next turn. |
| Ask the owner a question | Exists | ~40 | Explicit `NEEDS_INPUT`; mention. |
| Session `notes.md` working memory | Missing | ~100 | `plan_notes`; re-injected on resume. |
| **Plan issue as the plan object** | Partial (issue created at approval) | ~150 | `publish_plan` creates or edits the issue body; each write and each owner body edit records a `plan_versions` row with the body hash; the thread gets a link and a mention. Section messages, attached file, in-Matrix changelog and ✏️ collection from v3 are **dropped**. |
| **Approval by label or `/approve`** | Partial (`!cogito approve`) | ~80 | Webhook `issues.labeled` or `issue_comment` `/approve` → gateway applies label if needed, freezes the hash, refuses if the body changed since. |
| **Repository webhook ingest** | Dead route | ~150 | HMAC `X-Hub-Signature-256`, idempotent by delivery id (`inbound_events`), coalesce per plan for 30 s, one Luna turn per batch. |
| **Luna agent loop** | Missing | ~300 | Responses API with tools (§8.2); every tool result truncated; per-plan turn cap; transcript of Luna's turns in SQLite for the card. |
| Luna triage routing | Missing | ~60 | Revision → Astra; plan question → Astra; process question → Luna; instruction → Luna. |
| Sub-issues at approval | Exists | ~20 | Nested deliverables → nested sub-issues. |
| **Implementation room threads** | Missing | ~80 + Terraform | Luna opens one thread per approved plan linking the plan thread and issues; phase updates as card edits. |
| Session card + progress edited in place | Missing | ~150 | Outbox action `edit`. |
| Reactions as controls | Missing | ~90 | ⏹ ⏸ 🔄 🔍 on the card; ✅ no longer needed. |
| @mention on transitions only | Missing | ~30 | |
| Routing by state, no prefix | Partial | ~40 | Top-level message in a project room starts a session. |
| Per-room project config | Missing | ~50 + Terraform | |
| Prefix protocol + hash logging | Missing | ~50 | |
| Result packets with schema (file/line evidence) | Partial | ~80 | |
| **Inline PR review comments from packets** | Missing | ~100 | Gateway posts a PR review with line comments from reviewer packets, using the App token. Reviewer Agents keep no GitHub access. |
| **Owner PR comments → Luna** | Missing | ~40 | Webhook `pull_request_review_comment` / `pull_request_review` → Luna turn; Luna decides repair Workload or reply. |
| Wait for required checks before merge | Missing | ~40 | |
| `allowCloudReviewers: True` | One line | 1 | |
| Escalation and replanning | Partial | ~120 | Luna decides; gateway enforces limits; replanning reopens the plan issue and removes the label. |
| Luna token accounting | Missing | ~60 | Turns and tokens per plan from LiteLLM usage fields; card and `/metrics`; cap → `NEEDS_INPUT`. |
| Direct sessions (§9) | Implemented with Hermes | Existing isolated pod + backed-up PVC; scoped LiteLLM key. Owner-device DM remains to verify. |
| Images from the phone | Deployed | ~120 | Bounded 8 MiB encrypted Matrix download; dedicated local Muse `image` alias/key; only the text description reaches Astra or Luna. In-cluster vision and key-scope probes passed; owner-device check remains. |
| Multi-persona senders | Missing | 0 now | Glyph prefixes. Appservice later. |

Adapt total: roughly **2,000–2,400 lines** on top of 3.2k that stay. The Luna loop and the webhook path are the two new subsystems; everything else is extension.

### 5.3 State machine

```
NEW ─► DISCOVERING ─► NEEDS_INPUT ─► DISCOVERING     (rounds of scouts; owner questions)
                 └──► DRAFTED  ─► REVISING ─► DRAFTED   (plan issue exists; comments; body edits)
                            └──► APPROVED ─► EXECUTING ─► DONE
                                                ├──► BLOCKED ─► EXECUTING | NEEDS_INPUT
                                                └──► REPLANNING ─► DRAFTED   (label removed, issue reopened)
Any ─► PAUSED (⏸) ─► previous · Any ─► CANCELLED (⏹)
```

| Phase | Existing state | Change |
|---|---|---|
| `NEW` | `intake` | none |
| `DISCOVERING` | `researching` → `synthesizing` | none |
| `NEEDS_INPUT` | `intake` after `clarify`/`pushback`; `research_failed` | explicit; mention |
| `DRAFTED` | `review` | plan is the issue body; thread has link; mention |
| `REVISING` | `review` + comments + `revise` | triggered by Luna's triage of issue comments, or by owner request in the thread |
| `APPROVED` | `accepted` → `decomposed` | by label; hash frozen; sub-issues created |
| `EXECUTING` | `running` | Luna owns; implementation thread |
| `BLOCKED` | deliverable `failed` | Luna decides retry / diagnose / escalate; mention on escalate |
| `REPLANNING` | none | Luna requests; gateway removes the label, reopens the issue, calls Astra with the failure packets |
| `DONE` | `completed` | last PR merged; issue closed; mention |
| `PAUSED` / `CANCELLED` | none | gateway suspends dispatch / closes issues |

Who acts in each phase: `DISCOVERING`, `NEEDS_INPUT`, `DRAFTED`, `REVISING`: Astra, via the gateway, with Luna triaging GitHub events from `DRAFTED` on. `APPROVED` → `DONE`: Luna. Every transition: the gateway edits the card.

### 5.4 Rewrite versus adapt

Unchanged verdict: adapt. The Luna loop is new code either way; the outbox, replay, GitHub graph, quorum and merge code are what a rewrite would have to reproduce first.

### 5.5 Idempotency and restart

Matrix events by `event_id`, webhook deliveries by `X-GitHub-Delivery`, outbox with `txn_id`, Luna turns recorded before their actions are enqueued so a restart mid-turn re-issues the turn from the same inputs. After R1, restarts are voluntary again.

---

## 6. The gateway's clients

### 6.1 Foreman client

```
create_workload(deliverable_issue)        exists → one Workload, pipeline coder → gate → reviewers → PR
workload_status(name)                     exists
task_packet(task)                         exists → status.result + bounded summary (never the transcript)
spawn_scout(question, model, repo, ref)   exists as delegate_research → AgenticTask freeform
cancel(task)                              new → delete AgenticTask (RBAC)
```

Seats: FleetNode `maxSupervisedTasks: 4`; Agent `maxConcurrentTasks` (scouts 2+1, coder 1, reviewers 1+1); key `maxParallelRequests` equal to the Agent's.

### 6.2 Prefix protocol

`[system prompt for role] [repo preamble] [plan excerpt] [task]`, byte-identical above `[task]`, prefix hash logged as an AgenticTask annotation. Passes through LiteLLM unchanged.

### 6.3 Result packet

Scouts and reviewers return v1's packet shape in the `submit_result` summary: `conclusion`, `confidence`, `evidence: [{path, lines, note}]`, `uncertainty`, `suggested_followups`, `artifacts`. The gateway validates, stores, and for review tasks posts `evidence` as PR line comments (§8.5).

### 6.4 Worker pods

One Job per task; all LLM-backed Agents use the derived image (`gh`, `jq`, `unzip`), renamed `cogito-foreman-agent`; `[VERIFIED 2026-09-14]` scout Jobs project only the intentionally empty credential Secret and the scout supervisor has no `GITHUB_TOKEN`.

### 6.5 GitHub client and webhook

- **Outbound:** App installation token, re-read per request. Creates and edits the plan issue, applies labels, creates sub-issues, posts PR reviews with line comments, polls check rollups, merges.
- **Inbound:** a **repository webhook** on `cogito-ops` pointing at the gateway's public `POST /events/github` (the HTTPRoute exists), with its own secret. The App's webhook stays on Hookshot. Subscribed events: `issues`, `issue_comment`, `pull_request`, `pull_request_review`, `pull_request_review_comment`, `check_suite`, `push`. No source filtering `[DECISION]`; the gateway's own writes are recognised by marker and not fed back as owner input, but they still wake Luna as state changes.
- **Coalescing:** events for the same plan within 30 s form one Luna turn. Tunable; the first lever if quota is stressed.

---

## 7. Plans: the GitHub issue is the plan

### 7.1 Draft

When Astra returns `ready`, the gateway creates the plan issue: title `[plan] <first heading>`, labels `workflow/plan`, body = `plan_markdown` (front matter with `steps`, `depends_on`, `acceptance`, `guardrails.never_touch`, then prose), a `## Deliverables` checklist with nested sub-deliverables, markers for plan id and hash, and a matrix.to link to the thread. The thread gets `◆ Astra: Plan drafted → <issue link>` with a mention. The plan text is **not** posted in Matrix.

### 7.2 Review and revision

The owner reads, edits, and comments on the issue from GitHub Mobile. Every `issues.edited` and `issue_comment` event reaches Luna (coalesced). Luna triages:

- a revision request → `request_revision`; the gateway calls Astra with the current body, the comments since the last revision, and the notes; Astra returns a new body and a changelog; the gateway edits the issue body and posts the changelog as an issue comment, then a one-line `◆ Astra: revised (v3) → <link>` in the thread.
- a plan-content question → `ask_astra`; the answer is posted as an issue comment, attributed to Astra.
- a process or status question → Luna answers as an issue comment.

Versions are `plan_versions` rows keyed by body hash; GitHub's edit history is the human-readable diff. Sub-issues are **not** created before approval.

### 7.3 Approval

`workflow/approved` applied by the owner, or a `/approve` comment that the gateway converts into the label. The gateway freezes the body hash, refuses if the body changed after the approving event, creates sub-issues from the checklist (nested → nested, `blocked_by` in order), and moves to `APPROVED`. Removing the label, or Luna's `request_replan`, reopens review.

### 7.4 Anchoring

Issue comments are not line-anchored; quote-reply is the convention and GitHub Mobile supports it. This is the accepted trade for a single, editable, mobile-native review surface.

---

## 8. Execution

### 8.1 Luna at the Workload level `[DECISION: initial implementation]`

On `APPROVED`, the gateway opens a thread in `#implementation` (`● Luna: Implementing <plan> → plan thread, issues`) and starts Luna's loop. Per deliverable, in dependency order, Luna:

1. Calls `create_workload(sub_issue)`; Foreman runs coder → gate → two reviewers → PR with one repair round.
2. Receives the Workload outcome and the reviewer packets (bounded). The gateway has already posted inline review comments (§8.5) and waited for required checks.
3. On success and quorum: the gateway merges (SHA-pinned); Luna posts the deliverable's summary in the thread and moves on.
4. On failure: Luna decides among `spawn_scout` for diagnosis (log spelunking is a scout's job), a new Workload with the diagnosis appended to the issue body, `escalate` to the owner (`BLOCKED`, mention), or `request_replan`.
5. Owner messages in the implementation thread and owner PR comments arrive as Luna turns; Luna replies or acts.

Luna never reads a transcript, a gate log, or a diff. Any tool that would return one returns a summary and a scout suggestion instead.

### 8.2 Luna's tools (all bounded by the gateway)

```
create_workload(issue)                 workload_status(name)          task_packet(task)
spawn_scout(question, model, ref)      cancel(task)
issue_comment(issue, text)             pr_summary(pr)                 checks_status(pr)
post_thread(text)                      ask_owner(question)            ask_astra(question)
request_revision(reason)               request_replan(reason, packets)
escalate(reason)
```

Not available to Luna: merge (gateway, on quorum + checks), label changes (gateway), raw transcripts, shell, kubectl, secrets.

### 8.3 Concurrency

`maxSupervisedTasks: 4`: a coder plus two reviewers, or two scouts and a coder. Deliverables remain serial.

### 8.4 Escalation boundary

Luna makes implementation decisions; the gateway enforces limits; the owner makes planning decisions.

| Event | Who | Action |
|---|---|---|
| Gate fails, reviewer NO-GO | Foreman | one repair round inside the Workload |
| Workload fails | Luna | diagnose via scout, retry with findings, or escalate |
| Merge conflict on a later deliverable | Luna | new Workload against current `main` |
| Required check fails | gateway → Luna | never merged; Luna diagnoses or escalates |
| Deliverable text intersects `never_touch` | gateway | `NEEDS_INPUT` before any Workload |
| Two consecutive deliverables blocked, or the approach is wrong | Luna | `request_replan` → issue reopened → Astra → re-approval |
| Per-plan Luna turn cap reached | gateway | `NEEDS_INPUT`; owner raises the cap or cancels |
| Reviewers disagree repeatedly | Luna | re-review via `reviewer-escalated` (explicit, logged) |

### 8.5 Code review and merge safety

- **Inline review.** Reviewer packets' `evidence` becomes a PR review with line comments, posted by the gateway as the App; the summary and verdict become the review body. Both reviewers' reviews appear on the PR; the falsifier's NO-GO findings are what Foreman's repair round feeds to the coder.
- **Owner review.** PR comments and reviews come through the webhook to Luna; Luna answers on the PR or creates a repair Workload with the comment appended to the issue.
- **Gate.** flux-local for `kubernetes/` changes, the repo's tests otherwise, `git diff --check` as lint.
- **Ruleset on `main`** requiring `flux-local-status`; no bypass actors.
- **Merge.** Gateway only, after quorum and checks, SHA-pinned squash. Optional owner-gate flag.
- Hookshot mirrors all PR and issue activity into `#github`, muted.

### 8.6 Observability and token accounting

- Card fields: phase, plan version, open question, Astra turns, **Luna turns and tokens**, scout tasks, deliverables done/total, links.
- Prometheus: `gateway_luna_turns_total{plan}`, `gateway_luna_tokens_total{plan,kind}`, `gateway_astra_turns_total{plan}`, webhook batches per plan, coalesced-events per batch.
- Per-plan caps `[DECISION]`: Luna 200 turns, Astra 20 turns, scouts 40 tasks; hitting a cap is `NEEDS_INPUT`.
- LiteLLM sees every call, so per-key usage for `coordinator`, `planner`, `coder`, `scout`, `reviewer` is on the existing dashboard.

### 8.7 Future: Luna at the task level

Not built in v4. If Workload-level supervision proves too coarse (for example, deliverables that need a scout between coder and review, or per-step model choice), Luna could submit `AgenticTask`s directly: coder, gate, and review tasks per plan step with `depends_on` forming a DAG, an integration branch stacked from step branches, and acceptance per step as v1 §8 described. Costs: an order of magnitude more Luna turns per deliverable, Luna owning git integration (conflicts, rebases), and duplicating Foreman's pipeline logic in prompts. Preconditions before considering it: measured Luna tokens per deliverable at the Workload level, and a concrete deliverable class that the fixed pipeline cannot serve. The tool surface in §8.2 is designed so the task-level tools (`submit_task`, `integrate`) can be added without changing the gateway's limits.

---

## 9. Direct coordinator sessions

Hermes was evaluated first and retained. Its existing Matrix adapter already
provides E2EE, an owner allowlist, per-user/per-thread persistent sessions, model
switching, and a backed-up PVC. The failed legacy `llm-switch` provider was the
missing piece, not a capability gap requiring a new harness bridge.

GitOps now reconciles the provider-owned portion of Hermes' mutable
`config.yaml` at startup. Luna's `coordinator` alias is the default over
LiteLLM's Responses endpoint; `/model qwen` and `/model muse` select the local
models over chat completions. `litellm-key-hermes` is limited to exactly those
three aliases, and the pod has no Kubernetes service-account token or GitHub
credential. Session and Matrix crypto state remain on the VolSync/Kopia-backed
PVC. `[VERIFY]` complete an owner-device E2EE DM turn with `@hermes`.

Live acceptance on 2026-09-14: Flux applied exact `main` revision
`15203aebc8570d5351ea5c07607c507a0e9e5ad1`; the provider migration init
container completed and the replacement pod became Ready with zero restarts;
one-shot turns returned the expected sentinel through `coordinator`, `qwen`,
and `muse`; Matrix logged in as `@hermes`, enabled E2EE on stable device
`HERMES_BOT`, completed initial sync, and rejected non-owner invitations. The
existing-key operator gap required one `/key/update`; afterwards `/key/info`
reported only the three intended aliases and a `planner-gpt-pro` probe failed
with HTTP 403 `key_model_access_denied`. The short-lived update pod was deleted.

---

## 10. Matrix conventions

| Room | Purpose | Rule |
|---|---|---|
| `#project-cogito` (one per project) | Owner's request starts a thread; Astra questions and status card live there; plan lands as a link | Mentions only |
| `#implementation` (new) | One thread per approved plan; Luna's updates and the owner's instructions | Mentions only |
| `#github` (new) | Hookshot firehose | Muted; debugging stream |
| `#agent-runs` | Scout transcripts | Muted |
| `#agent-alerts` | alertmanager | Mentions only |
| DM `@hermes` | direct sessions (§9) | Normal |

The workflow personas share one `@coordinator` account with glyph prefixes `◆ Astra`, `● Luna`, `▣ gateway`; Hermes keeps its existing separate account for direct sessions. Thread anatomy: root, card (edited), progress (edited), turns, links. Verbs: reactions ⏹ ⏸ 🔄 🔍 on the card; bare `status`, `stop`; `!cogito` kept as an alias. Routing by phase: planning-phase thread messages go to Astra (queued between rounds); implementation-thread messages go to Luna.

---

## 11. Notifications

Synapse → ntfy → UnifiedPush → Commet (done). Mentions only on `NEEDS_INPUT`, `DRAFTED`, `BLOCKED`, `DONE`, `CANCELLED`, and on every Astra revision link. GitHub's own notifications for the repo can be muted on the phone; everything arrives in Matrix, with `#github` as the muted mirror.

---

## 12. Security and budgets

- Astra: four tools, no world access. Luna: the §8.2 tools only; no merge, no labels, no shell, no secrets. Gateway SA: `workloads` create/get/list/watch, `agentictasks` create/get/list/delete, `configmaps` get.
- Local/cloud boundary = LiteLLM key scope; Foreman's gates documented as flipped.
- Worker pods: scoped; verify scout token scope.
- Webhook: HMAC-verified, idempotent by delivery id, public route limited to `POST /events/github`.
- `never_touch` enforced by the gateway before Workload creation; R9 independently keeps `kubernetes/` changes behind flux-local.
- Budgets: turn caps per plan (§8.6); key rate and parallel caps; USD only on `escalation`.
- Prompt injection: packets and issue comments are data to the gateway; Luna's and Astra's system prompts mark them untrusted; the gateway never executes text from either.

---

## 13. Build order

| # | Milestone | Done when |
|---|---|---|
| **R0** | **Cluster repair** (R1–R9) | No involuntary roll for 2 h; a coder turn completes via the `coder` key; Flux all Ready; iggy < 50 % memory requests; Muse 2 slots and FleetNode capacity 4; ruleset on `main`; PR 22 resolved. |
| 1 | **Rename + webhook + plan issue + label approval** | Service is `gateway`; a repository webhook delivers to it; Astra drafts land as an issue body with a link in the thread; `/approve` and the label both freeze the hash and create sub-issues. |
| 2 | **Luna loop at the Workload level** | An approved two-deliverable plan runs two Workloads under Luna in an `#implementation` thread; both merge after checks and quorum; Luna turns and tokens appear on the card. |
| 3 | **Triage and revision on GitHub** | Owner comments on the plan issue produce an Astra revision (body edit + changelog comment) or an answer, routed by Luna; owner PR comments produce a Luna reply or repair Workload. |
| 4 | **Inline review + card + reactions + mentions** | Reviewer evidence appears as PR line comments; card edited on every transition; ⏹ ⏸ 🔄 🔍 work; pings only on the listed transitions. |
| 5 | **Scouts on both cards, notes, prefix protocol, Qwen A/B** | Qwen and Muse scouts in one round; notes-based resume; prefix hit rate measured; `SPEC`/`CTX` A/B in `bench-notes.md`. |
| 6 | **Escalation and replanning exercised** | Forced `BLOCKED`, `REPLANNING` via label removal, guardrail intercept, failed required check, turn cap. |
| 7 | **Direct sessions** | Implemented with Hermes; owner-device E2EE DM check remains. |
| 8 | **Phone images** | Deployed; local Muse described a generated image through the scoped route, while the same key was denied access to `reviewer`. Owner-device encrypted-media check remains. |
| 9 | **Polish** | Deployed dashboard and prefix-free `#project-cogito` intake; `!cogito` remains an alias. Appservice personas are explicitly optional and deferred. |

---

## 14. Open items to verify

1. `[VERIFIED 2026-09-14]` R1 token handling: neither long-lived supervisor
   receives `GITHUB_TOKEN`; execution coder/reviewer Jobs project the rotating
   App token at creation through `coderGitSecret`. A credential-free execution
   supervisor resolved the public repository at the exact deployed `main` SHA.
2. `[VERIFIED 2026-09-14]` all LLM-backed Agents use `cloud-proxy`; both Ready
   FleetNodes advertise `qwen3-8-27b` and `muse-glimmer-30b` without an
   `inferenceServiceRef` dependency.
3. `[VERIFIED 2026-09-14]` Muse capacity: 2x131k through 16x32k passed on the
   RTX 3090; see `glimmer-benchmark-2026-09-14.md`. Real scout quality remains
   part of the milestone-5 exercise.
4. `[VERIFIED 2026-09-14]` the single `gateProfile.image` ran the repository's
   flux-local gate successfully for both accepted deliverables (PRs #98 and
   #100).
5. `[VERIFIED 2026-09-14]` the scout supervisor has no `GITHUB_TOKEN`, and its
   Job projection names the intentionally empty `foreman-scout-github-token`.
6. `[VERIFY]` A repository webhook alongside the App's Hookshot webhook delivers all subscribed events without duplication.
7. `[VERIFY]` GitHub Mobile: label application, body editing, and quote-reply are all usable one-handed.
8. `[VERIFIED 2026-09-14]` the first accepted two-deliverable plan used 56 Luna
   turns, 1,472,890 input tokens, and 28,419 output tokens at effort max.
9. `[VERIFY]` Commet renders `m.poll`.
10. `[VERIFY]` Complete an owner-device E2EE direct-session turn with `@hermes`.
11. `[VERIFY]` Send an encrypted image from Commet in a planning and an
    implementation thread; confirm only the bounded Muse description reaches
    Astra or Luna.
12. Measure: Qwen `SPEC`/`CTX` A/B; Muse Glimmer's DFlash boundary, real
    concurrent scout turn p95, prefix hit ratio, and mixed vision/text behavior
    on its RTX 3090; coder effort. The synthetic Glimmer capacity frontier is
    complete through 16 slots.
13. Upstream: Foreman's no-diff gate on `freeform` tasks. Terminal-task drain and
    orphaned in-cluster FleetNode cleanup shipped in Foreman 0.9.26 and are
    deployed here via 0.9.27.

---

## 15. Glossary

- **Astra** — `planner` alias, the brains. **Luna** — `coordinator` alias, the coordinator agent. **K3** — `reviewer-escalated`.
- **Gateway** — the deterministic service (formerly `matrix-coordinator`): transport, state, webhook, clients, limits.
- **Plan issue** — the GitHub issue whose body is the plan; versions are body edits; approval is the `workflow/approved` label.
- **Implementation thread** — one Matrix thread per approved plan in `#implementation`, owned by Luna.
- **Workload** — Foreman's per-deliverable pipeline: coder → gate → reviewers → PR.
- **Scout** — a read-only local task (Muse or Qwen) for research or diagnosis, returning a packet.
- **Packet** — structured result: conclusion, confidence, evidence with file/line, uncertainty, follow-ups, artifacts.
- **Coalescing** — the gateway's batching of webhook events per plan into one Luna turn.

## 16. Sources consulted (2026-09-13)

- Repo `timblakely/cogito-ops` @ `5c850664`: `services/matrix-coordinator/`, `kubernetes/apps/llm/{llmkube,foreman,litellm}/`, `kubernetes/apps/home-infra/{matrix,matrix-coordinator,matrix-hookshot}/`, `.github/workflows/flux-local.yaml`, the two pathway documents, `plans/llm/*`, `GEMINI.md`.
- Live cluster: Foreman CRDs (`Agent.spec.provider`, `Workload.spec.*`, FleetNode `supervisionCapacity`), AgenticTask statuses and transcripts, serving pods (`nvidia-smi`, llama.cpp `/props`), InferenceService `/v1/models`, `gh api` for PR 25's reviews (none) and `main`'s protection (none).
- Foreman chart values 0.9.25; syv-ai README; llama.cpp server README and releases; vLLM releases and Muse recipe; RedHatAI W4A16 card; Hardware Corner 3090 measurements; defilantech/llmkube README.
- v1 audit page — https://claude.ai/code/artifact/8342d002-3e65-4ae8-a140-9bf27ddafea8
