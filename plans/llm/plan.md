# LLM stack implementation plan

Interleaved execution plan across the five research documents. Waves are ordered;
tracks inside Wave 2 run in parallel. Every task lists its subtasks, the files it
touches, and an explicit **done when**. Milestones at the bottom.

| Source document | To-do section | Artifact |
| --- | --- | --- |
| The Idle Bench | §8 | https://claude.ai/code/artifact/5a86a824-fbd0-4771-b5bc-cc7c1ff759ac |
| LiteLLM Routing Teardown | §13 | https://claude.ai/code/artifact/48d11ee1-4b07-4663-a58a-e85a57fd2a96 |
| The Portable Coordinator | §8 | https://claude.ai/code/artifact/04ec2542-d4ac-4b25-8ffe-9ff428379a73 |
| Foreman and ToolHive | §12 | https://claude.ai/code/artifact/3bbe6e0b-d8af-4a5f-a596-7e266605951e |
| The Contested GPU | §6 | https://claude.ai/code/artifact/68ddd1e2-92ee-49fd-bc97-abad5fff7b9c |

External references: `joryirving/home-ops` (GitHub) and Phor's `ops/flux`
(https://x0r.li/ops/flux, `clusters/core-k3s/apps/llm`) — the two comparison
clusters. Phor's contributes the same-model-fallback rule, the Flux `dependsOn`
ordering, the `chatgpt/` LiteLLM provider precedent, the cache-prime Job
pattern, `--language-model-only`, and the MTP token-count warning.

## Locked decisions (do not re-litigate during implementation)

- **Coordinator pattern, not autorouting.** No `auto` alias, no complexity router,
  no tier maps. Cloud coordinator delegates to role-aliased local workers.
- **FP8 spanning both 3090s** (2026-08-21, by decision). The single-card W4A16
  A/B is deliberately deferred; if ever run, KV dtype must match across arms.
- **Seats over ceiling:** `max-model-len 131072`, `max-num-seqs 6` (sweep toward 8).
- **Role aliases stay in LiteLLM** (and additionally as role names in the harness).
  Jory's alias-layer deletion is the counter-experiment, not the model.
- **Retrieval floor on kristeva's A380, never on preemptible hardware.**
- **The 5070 Ti utility roster ships as one pod** holding the node's whole
  advertised GPU budget (all-or-nothing eviction).
- **Gaming node is last.** Nothing on the critical path waits for it.
- **Escalation is coordinator-driven; no cross-model proxy fallbacks.**
  (Decided 2026-08-21, from Phor's finding that LiteLLM does not re-check a
  key's model allowlist on the fallback path.) A cross-model fallback would
  both leak past key scopes and turn the worker key's 429 backpressure into a
  paid spillway. The coordinator escalates after reading a failure — which is
  the §11 pattern anyway. Any future proxy fallback must be **same model,
  different host**, its targets granted to no key directly, and every key's
  scope must contain its aliases' fallback closure (validator-enforced).
  This supersedes the routing teardown's `worker → [worker-escalated]`
  routerSettings entry; sync the doc after implementation.
- **Ordering via Flux `dependsOn`, not file moves.** (Decided 2026-08-21,
  Phor's shape.) The serving CRs stay in their own tree/Kustomization; the
  litellm Kustomization depends on it. The T1.3 consolidation move is dropped
  — it risked a prune/adopt race on the only serving pod for a guarantee
  `dependsOn` provides for free.

## Conventions

- Commit/deploy via jj: `jj describe -m`, `jj bookmark set main`, `jj git push`,
  then `flux reconcile` the affected Kustomization. Same for `~/git/llm-operator`
  (manual image + chart release, then digest bump in cogito).
- One live intervention at a time; verify each before the next.
- Record benchmark results and negative results as comments **in the manifest
  that holds the tunable** (the practice worth copying from Jory's tuning
  DaemonSet), plus a running log in `plans/llm/bench-notes.md`.
- Single-operator homelab: prefer the simplest mechanism that answers the
  question; skip production-grade ceremony unless a failure mode demands it.
- **Layout convention (revised — Phor's shape):** serving CRs keep their own
  directory and Flux Kustomization; the litellm Kustomization declares
  `dependsOn` it, so backends always exist before the catalogue names them.
  New backends (the A380 floor, the 5070 Ti roster) get their CRs beside the
  existing serving tree.
- **Weight staging via cache-prime Jobs** (Phor's pattern): a Job running the
  official `hf` CLI against the cache PVC — immutable Job names rotated per
  change, `kustomize.toolkit.fluxcd.io/force: Enabled` — instead of ad-hoc
  curl loops. Solves the documented llmkube multi-file HF gap.

---

## Wave 0 — Two gates, day one

### T0.1 · Make the GPU counts truthful  *(Idle Bench §8.1 — unblocked now)*

Files: `kubernetes/apps/cluster-infra/nvidia-device-plugin/app/` (time-slicing
config), no others.

- [x] Capture current allocation from inside the running pod:
      `kubectl -n llm exec deploy/qwen-3-8-fp8 -c vllm -- nvidia-smi -L`
      and `... -- env | grep CUDA_VISIBLE_DEVICES` — expect **two distinct GPU
      UUIDs**. Save output into bench-notes.
- [x] Locate the `timeSlicing` block (teardown records `replicas: 4`) and set
      `replicas: 1` for iggy's config.
- [x] Push, reconcile, let the device-plugin DaemonSet roll.
- [x] Verify `kubectl get node iggy -o jsonpath='{.status.capacity.nvidia\.com/gpu}'`
      returns `2`.
- [x] Verify the qwen pod is Running with `nvidia.com/gpu: 2` of 2, and run one
      smoke completion through LiteLLM.

**Done when:** iggy advertises 2 units, qwen serves at 2/2, smoke test passes.
**Risk:** the pod may briefly go Pending while the plugin rolls — do it in an
idle window; blast radius is the one model.

### T0.2 · Build the validator  *(Teardown §13.1 — no cluster dependency, start in parallel)*

Files: new `scripts/validate-llm-catalogue.py` (or `.sh`), optional GitHub
workflow / pre-push hook.

- [x] Render the full output (`kustomize build` over the llm namespace paths)
      and build the set of published `modelName`s.
- [x] Assert: every `LiteLLMVirtualKey.spec.models` entry resolves (the
      silent-scope trap).
- [x] Assert: every `fallbacks` / `context_window_fallbacks` target resolves.
- [x] Assert: any `LiteLLMModel.apiBase` naming an in-cluster Service has a
      matching InferenceService/Deployment in the same rendered output.
- [x] Assert: `maxInputTokens` on the qwen entry equals the backend's
      `maxModelLen` (131072/131072 after T1.1).
- [x] Assert: `coordinator` has **no** fallback entry (encodes the cache
      argument); every alias whose backend sits on a preemptible node **has** one.
- [x] Assert: any declared fallback target is the **same underlying model** as
      its primary, and every key's scope contains the transitive fallback
      closure of its aliases (Phor's scope-leak rule).
- [x] Assert: `embedder`/`reranker`, once declared, resolve to live backends.
- [x] Assert: model names referenced in consumer env/ConfigMaps (open-webui,
      hermes) resolve.
- [x] Negative test: break one scope name locally and confirm the script fails.

**Done when:** green on current rendered output; red on a deliberately broken
scope; wired to run before push (hook or CI).

---

## Wave 1 — Proxy restructure, retune folded in

Order within the wave: T1.1 → T1.2 → T1.3 → T1.4 (T1.4 can trail or overlap T1.3).

### T1.1 · Seat retune  *(Idle Bench §8.2 — gated on T0.1)*

Files: `kubernetes/apps/llm/llmkube/resources/inferenceservices.yaml`,
`kubernetes/apps/llm/litellm/app/models/qwen-3-8-fp8.yaml`.

- [x] **Check for a resident vision tower first:** read the model's
      `config.json` architectures in the serving pod; if the build is
      multimodal, add vLLM's `--language-model-only` (Phor runs it on the same
      model family) — freed VRAM goes straight into the KV pool.
- [x] InferenceService: `maxModelLen 262144 → 131072`, `maxNumSeqs 2 → 6`.
      Keep chunked prefill, prefix caching, `maxNumBatchedTokens 8192`, and the
      MTP speculative config exactly as they are.
- [x] Same commit: LiteLLM entry `maxInputTokens 262144 → 131072`.
- [x] On restart, read the vLLM startup log's KV-cache block count and record it
      as a comment next to `maxNumSeqs` (the number future tuning reasons from).
- [x] Smoke: 6 concurrent short completions all succeed; one 100k-token prompt
      succeeds.
- [x] Validator green (context mirror assertion now bites).

**Done when:** endpoint serves 6 concurrent seats at the 131k ceiling, mirror
matches, KV block count recorded.
**Note:** the worker-key rpm/parallel cap lands in T1.2 with the key itself.

### T1.2 · Role aliases, per-role keys, fallbacks, timeouts  *(Teardown §13.2–4)*

Files: new `litellm/app/models/{coordinator,worker,reviewer,worker-escalated,reviewer-escalated}.yaml`,
new `litellm/app/virtualkeys/{coordinator,worker,reviewer,escalation}.yaml`,
`litellm/app/litellmproxy.yaml`.

- [x] `worker` and `reviewer` aliases over the qwen backend, pointed **directly
      at the InferenceService's Service** (verify the Service name with
      `kubectl -n llm get svc`) — this pre-empts the ModelRouter deletion in
      T1.3 so the apiBase never needs a second touch.
  - [x] `worker`: default `reasoning_effort: low`; `reviewer`: default `medium`;
        both keep `allowed_openai_params: [reasoning_effort]` and zero costs.
- [x] `coordinator` alias initially over `openai/gpt-5.5` (the planner-gpt
      backend) as a stand-in until T1.4 seats Luna.
- [x] `worker-escalated` / `reviewer-escalated` aliases created but pointed at
      the planner-gpt backend as placeholders until T1.4 (they must exist for
      the fallback graph and validator).
- [x] Virtual keys, one per role, each with a budget (values: **your call**,
      placeholders in the manifests):
  - [x] `worker` key: scope `[worker]` only, `rpm`/`max_parallel_requests` ≈ 8
        (a notch above the seat count).
  - [x] `coordinator` key: scope `[coordinator]`, monthly budget.
  - [x] `escalation` key(s): scope the two escalated aliases, monthly budget.
- [x] `routerSettings.fallbacks`: **none.** Escalation is coordinator-driven
      (locked decision above); the escalated aliases exist as explicit
      delegation targets, never as automatic fallbacks. The worker key's 429
      backpressure therefore queues instead of spilling to paid rungs, and
      "a worker key cannot spend money" stays literally true.
- [x] Per-alias timeouts: worker/reviewer tight (~300s), coordinator long
      (~1800s), escalations ~900s.
- [x] Enforcement test: a `worker`-key request naming `planner-gpt` is refused
      by the proxy.

**Done when:** `/v1/models` lists all five; scoped-key smoke tests pass;
enforcement test refuses; validator green.

### T1.3 · Delete the swap machinery, shrink the catalogue  *(Teardown §13.6–7)*

Files: `llmkube/resources/{modelpool,modelrouter,rbac-prefetch}.yaml` (delete),
`llmkube/resources/{models,inferenceservices}.yaml` (prune),
`litellm/app/models/*` (prune), `litellm/app/virtualkeys/*` (scopes),
`litellm/app/litellmproxy.yaml`.

- [x] **First:** set the qwen InferenceService to explicit `replicas: 1` — the
      ModelPool owned residency until now (every member ships at 0); deleting
      the pool without this scales the only local model to zero. Reference the
      Flux/ModelPool replica-fight fix (f77bb0a4) in the commit message.
- [x] Delete `modelpool.yaml`, `modelrouter.yaml`, `rbac-prefetch.yaml` and
      their kustomization entries.
- [x] Prune the nine retiring backends from `models.yaml` and
      `inferenceservices.yaml` (everything except qwen-3-8-fp8; muse's weights
      stay archived for the 5070 Ti later).
- [x] Prune the nine retiring LiteLLMModels, including `gemma4-agentic` (its
      backend retires; its consumers move to `worker`).
- [x] **Same commit:** update every virtual-key scope that names a retiring
      alias (`open-webui` scopes eight; check `hermes` and `pi` too).
- [x] `litellmproxy.yaml`: `timeout 1900 →` a real inference ceiling (600);
      rewrite the `num_retries: 2` comment (the swap-wait reasoning is dead).
- [x] Confirm qwen's LiteLLM entry apiBase points at the Service (done in T1.2).
- [ ] Optional chore: delete retired weights from the hot-tier PVC to free NVMe
      (the NFS archive keeps the durable copies); leave the PVC size alone.
      (Left undone deliberately - disk is not tight.)
- [x] **Wire the ordering, Phor's shape (supersedes the consolidation move).**
      Keep the serving CRs where they live; ensure they render from their own
      Flux Kustomization and add `dependsOn` from the litellm Kustomization to
      it, so backends always exist before the catalogue names them. No file
      moves, no ownership transfer, serving pod untouched.
- [x] Soak: qwen stays Ready across a full `flux reconcile` cycle (no replica
      fight); Open WebUI and Hermes still answer.

**Done when:** no ModelPool/ModelRouter CRs exist; the litellm Kustomization
depends on the serving-CR Kustomization; `/v1/models` lists exactly the
expected set; validator green; consumers unaffected after reconcile; qwen pod
uptime unbroken throughout.

### T1.4 · Seat the cloud providers  *(Teardown §13.5 / Idle Bench §6)*

> STATUS 2026-08-22 (evening): **the OAuth path is LIVE.** coordinator +
> both escalated seats run on the ChatGPT subscription via the chatgpt/
> provider (device-flow tokens on the litellm-chatgpt-token PVC; streaming
> required until upstream fixes non-streaming - see bench-notes). Remaining
> here: GLM 5.3 and K3 as the real escalation seats (account actions), and
> real budget numbers. The OpenAI API account stays unfunded by decision.

Files: `litellm/app/models/*.yaml`, `litellm/app/externalsecret.yaml`,
1Password items.

- [x] **coordinator → GPT Luna via the ChatGPT subscription's OAuth path.**
  - [x] Research LiteLLM's Codex/Responses-style OAuth support; document the
        token acquisition + refresh flow.
  - [x] Tokens live on a PVC, not a Secret (refresh rotates single-use;
        1Password copies go stale - rebuild path is a fresh device flow).
  - [x] Repoint the `coordinator` alias; keep `planner-gpt`/`-pro` as the
        documented manual hedge (ToS-gray path: nothing may work *only* if it
        survives).
- [x] **worker-escalated → Luna@max on the subscription** (rescoped
      2026-08-22: with escalation coordinator-driven and no volume cloud
      lane, GLM's coding-plan economics have nothing to bite on — GLM
      SKIPPED, recorded as the alternative if a volume lane ever returns).
- [ ] **reviewer-escalated → K3** (council family-diversity + understudy).
      Kimi Code sub is WAITLISTED (2026-08-23), so: Moonshot metered first
      (`MOONSHOT_API_KEY`), sub endpoint promotes to rung 1 when the
      waitlist clears, metered demotes to same-model fallback.
  - [ ] AWAITING MOONSHOT_API_KEY in the litellm 1Password item; target
        recorded in reviewer-escalated.yaml's header.
  - [ ] `reasoning_effort` pinned `high`, NEVER `none` ("none routes to
        K2.6 instead of K3" — Phor). Optional same-model Moonshot/Fireworks
        PAYG rung behind it later.
- [x] **Luna@`max` pinned** on coordinator + both escalated seats (credit
      arbitrage: thinking bills as output at the model's rate, Luna 30/M vs
      Sol 500/M); **`coordinator-heavy` → Terra** as the explicit-choice
      splurge (10x window burn, never a fallback).
- [ ] Optional (decide later): a cheap PAYG backstop rung under
      `worker-escalated` (neuralwatt-class), order 2 — "order encodes
      preference, not cost." Skip until the GLM cap actually bites.
- [ ] Budgets: set real numbers on the coordinator and escalation keys.
- [ ] Smoke each seat through its own key; confirm per-key spend attribution in
      the LiteLLM dashboard.

**Done when:** all three seats answer through their keys, spend is attributed
per role, hedge procedure is written down.

---

## Wave 2 — Parallel tracks (all unblocked once T1.2's aliases exist)

### Track A · Benchmarks  *(Idle Bench §8.3 — background work)*

- [ ] **A1 seat sweep.** Set the backend to `maxNumSeqs 8`; drive 2/4/6/8
      client-side concurrent synthetic worker loads (4–16k prompts, 0.5–2k
      completions); record ITL, TTFT, and `vllm:num_preemptions` from
      `/metrics` per level; pin the final `maxNumSeqs` from the data and record
      the table in the manifest comment + bench-notes.
- [ ] **A2 MTP, three arms** at the pinned seat count: off / 2 tokens / 3
      tokens (current). Phor's manifest cites the model card recommending 2 and
      a vLLM warning that >1 lowers acceptance on the same MTP layer — cogito
      runs 3, so the middle arm may win. Keep the winner; record all three.
- [x] **A3 kristeva identity + bandwidth.** Privileged debug pod (or talosctl):
      `lscpu` + a STREAM-class run. This gates D2 and calibrates D1.
- [x] **A4 A380 embedding throughput** (after B2): chunks/minute at int8 batch
      embed; decides whether bulk indexing ever needs the 5070 Ti reranker slot.

**Done when:** all four numbers recorded; `maxNumSeqs` and MTP pinned by data.

### Track B · Retrieval floor  *(Idle Bench §8.4)*

- [x] **B1** Confirm the A380 from the PCI id (debug pod `lspci` or node
      labels), not just the NFD label.
- [x] **B2** Serving path: check `~/git/llm-operator` for non-CUDA accelerator
      support; if absent, plain Deployment (OpenVINO Model Server or a
      llama.cpp SYCL/Vulkan image) requesting `gpu.intel.com/i915: 1`, pinned
      to kristeva. Stage embedder (bge-m3-class, int8) + reranker
      (bge-reranker-v2-class) weights into the NFS archive first. Manifests
      live under `litellm/app/` per the layout convention — beside the aliases
      that will name them.
- [x] **B3** LiteLLM entries: `embedder` (mode embedding). For `reranker`,
      note Jory's finding — the `openai/` provider shape rejects rerank; keep
      the rerank entry explicit with a provider LiteLLM's `/v1/rerank` accepts.
- [x] **B4** Repoint Open WebUI RAG at the proxy alias (RAG embedding engine →
      OpenAI-compatible, base URL + a key whose scope includes `embedder`;
      extend the open-webui key scope in the same commit — validator watches).
- [x] **B5** Vector DB near storage: Qdrant (or pgvector via the existing CNPG
      pattern) with a NUC node selector; point Open WebUI's vector store at it.
- [x] Verify: a RAG query embeds on the A380 (drm-exporter shows GPU activity;
      LiteLLM logs show the alias); re-index a real doc set end-to-end.

**Done when:** retrieval runs through the proxy on always-on silicon, reindex
works, validator asserts both aliases.

### Track C · Harness lift  *(Portable Coordinator §8 — dotfiles, not cluster)*

- [x] **C1** Port the workflow extension + the three definitions
      (implement-and-review, debug-until-green, review-pr) into the
      chezmoi-managed pi config; keep run state machine-local.
- [x] **C2** Extend the trusted check registry with fixed argvs **in source
      before any workflow names them**: `git diff --check`, `kustomize build`
      over the rendered path.
- [x] **C3** Coordinator system prompt, inverted for cogito's economics: local
      seats free → fan out `worker`/`reviewer` by default; escalation entered
      on failure; per-key budgets as the hard backstop. Include the delegation
      contract: objective, settled decisions inlined, files owned,
      out-of-scope, observable success check.
- [x] **C4** Role agent files (worker, reviewer, worker-escalated,
      reviewer-escalated) + `models.json` against cogito's LiteLLM; update the
      `pi` virtual key's scope to the role aliases (validator watches).
- [x] **C5** Council workflow: review-pr's fan-out-then-synthesize across three
      families — local Qwen, GLM 5.3, K3.
- [x] **C6** Mutation stages run in disposable jj worktrees; write the
      convention into the workflow README.
- [ ] **C7 · PENDING YOUR CALL:** a persistent in-cluster coordinator pod
      (pi or opencode server, hermes/open-webui deployment pattern, own
      virtual key, backed-up home) — the one Jory item not yet on any list.
      Approve, defer, or decline.
- [ ] End-to-end proof: run implement-and-review on a toy change in a worktree
      — approval gate fires, check runs, delegation shows up under the worker
      key in the dashboard.

**Done when:** the E2E proof passes and spend/attribution is visible per role.

### Track D · Kristeva CPU lanes  *(Idle Bench §8.5)*

- [x] **D1** CPU VLM: llama.cpp CPU deployment of a small multimodal (+ its
      mmproj) on kristeva with CPU/memory limits that protect camofox; publish
      as a `vision` alias; measure seconds/image encode and record it.
- [ ] **D2** MoE lane (gated on A3's bandwidth number): llama.cpp CPU with
      DeepSeek V4 Flash UD-IQ3_S from the NFS archive, ~115Gi memory limit,
      kristeva-pinned; measure tok/s.
  - [ ] ≥ ~5 tok/s → keep as a `batch-lane` alias, clearly labeled
        non-interactive, no fallback semantics that could route interactive
        traffic here.
  - [ ] < ~5 tok/s → delete the manifests without regret; record the number.

**Done when:** vision has a working CPU path; the MoE lane is kept-with-numbers
or deleted-with-numbers.

---

## Wave 3 — Rails bookkeeping  *(Foreman §12 — rides on Waves 1–2)*

- [ ] **Escalation log.** Keep it proportional to one operator: a Grafana panel
      filtered to the escalation key(s) answers "what escalated, how often,
      what did it cost"; the *why* lives in workflow artifacts (C1 saves
      review/repair artifacts per run). No new service.
- [ ] **Verify the caps compose:** per-role budgets (T1.2/T1.4) +
      workflow `maxAttempts` (C1) + `maxNumSeqs` backpressure (T1.1) — walk one
      runaway scenario on paper and confirm each layer catches it.
- [ ] **Deferred, recorded as deferred:** ToolHive-style MCP gateway (revisit
      once the A380 embedder is live and MCP tool count actually hurts);
      overnight batch lane (revisit only if unattended work outgrows six seats).

**Done when:** the escalation question is answerable from the dashboard +
artifacts; the runaway walkthrough is written into bench-notes.

---

## Wave 4 — The gaming node  *(Contested GPU §6 — lowest priority, self-contained)*

- [ ] **G1 machine swap.** Back up the desktop, install Talos, join the
      cluster; laptop becomes daily driver + Moonlight client.
- [ ] **G2 node provisioning.** NVIDIA extensions matching iggy's pair
      (nonfree-kmod + container-toolkit), runtime class, and a per-node device
      plugin config advertising **exactly 2 units** (one card, time-sliced ×2 —
      the number a Wolf session consumes).
- [ ] **G3 utility roster as one pod at −100.** Single pod requests
      `nvidia.com/gpu: 2`; llama.cpp serving the roster subset (VLM + Whisper +
      optional reranker, or Muse alone); `gpu-preemptible` PriorityClass;
      weights on node-local hot tier.
- [ ] **G4 preemption proof before anything else lands:** a synthetic
      default-priority pod requesting 2 units must evict the roster pod whole;
      roster reschedules after its deletion.
- [ ] **G5 Wolf by the bisection ladder:** `runtimeClassName: nvidia` on
      session pods first; all Apps agreed on the dGPU's render node; Test Ball
      → Firefox (GBM_BACKENDS_PATH on both containers) → Steam (VK_DRIVER_FILES,
      4Gi shm, user namespaces); DSR annotation before judging stream quality.
- [ ] **G6 VRAM gate:** DCGM exporter on the node; MutatingAdmissionPolicy
      gating session pods at CREATE; small ungate on a free-VRAM threshold with
      a bounded timeout (gating half only — no replica scaling).
- [ ] **G7 Muse re-quant:** source or build ≤ ~12GB, fix the inherited 200k-ctx
      KV config, stage to archive + node hot tier, then join the roster.
- [ ] **G8 acceptance:** validator green (fallback behind every alias this node
      backs); play a session end-to-end while confirming worker/retrieval paths
      are untouched.

**Done when:** a game streams, the roster yields and returns, and nothing on
the critical path noticed.

---

## Milestones

| # | Name | Means |
| --- | --- | --- |
| M0 | Honest hardware | T0.1 + T0.2 done: counts truthful, validator guarding |
| M1 | Six seats | T1.1 live; sweep + MTP numbers pin the config (A1/A2) |
| M2 | Roles live, pool gone | T1.2–T1.4: aliases, keys, budgets, seats; swap machinery deleted; spend attributable per role |
| M3 | Retrieval + lanes | Track B live (RAG on the A380); Track D decided with numbers |
| M4 | Coordinator end-to-end | Track C proof passes: plan → approve → implement → check → review through role keys, escalation logged |
| M5 | Game night | Wave 4 acceptance: session streams, roster yields, critical path unaffected |

## Open questions (answers needed, none blocking Wave 0)

1. **C7 — in-cluster coordinator pod:** approve / defer / decline.
2. **Budget values** for the coordinator and escalation keys.
3. ~~Reviewer fallback~~ — resolved by the no-cross-model-fallback decision:
   both escalations are coordinator-driven delegation targets.
4. **PAYG backstop for escalation:** if added, Phor's refinement applies —
   the **same model on a metered host** (e.g. GLM 5.3 on a PAYG provider) as
   an explicit coordinator target or same-model fallback, never a different
   cheap model. Default: leave until the GLM caps bite.
5. **Muse re-quant source:** hunt an existing ≤12GB build vs. quantize locally
   (only matters at Wave 4).
6. ~~chatgpt-token PVC RWX migration~~ — done 2026-08-23 (pre-seed-then-swap;
   see bench-notes).
