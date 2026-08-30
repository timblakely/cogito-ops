# LLM stack implementation plan

Execution tracker for the five research documents (artifact links in
`README.md`; glanceable status board: The Punch List). Waves 0-3 and every
parallel track have shipped; evidence lives in `bench-notes.md` and as
comments in the manifests that hold each tunable. This file keeps what is
still in force: the locked decisions, the working conventions, and the
remaining work (Wave 4 plus the deliberately parked items).

External references: `joryirving/home-ops` (GitHub) and Phor's `ops/flux`
(https://x0r.li/ops/flux, `clusters/core-k3s/apps/llm`) — the two comparison
clusters several locked decisions cite.

## Locked decisions (do not re-litigate)

- **Coordinator pattern, not autorouting.** No `auto` alias, no complexity router,
  no tier maps. Cloud coordinator delegates to role-aliased local workers.
- **FP8 spanning both 3090s** (2026-08-21, by decision). The single-card A/B
  was later run for the *degraded SPLIT mode* (2026-08-24, llmkube/modes/):
  candidate A (GGUF) won; that does not reopen the FP8 primary decision.
- **Seats over ceiling:** `max-num-seqs 8` (pinned by the A1 sweep). Amended
  2026-08-28: the ceiling was not actually what bought the seats — the KV
  pool is sized by weights and `gpuMemoryUtilization`, not `max-model-len`
  (277,007 tokens at 262144, 275,656 at 131072), so `max-model-len` is back
  at **262144** and the 131072 budget moved to the role aliases, which
  advertise it via `maxInputTokens`. Seats are unchanged; the full window is
  reachable only through the direct `Qwen/Qwen3.8-27B-FP8` alias.
- **Role aliases stay in LiteLLM** (and additionally as role names in the harness).
  Jory's alias-layer deletion is the counter-experiment, not the model.
- **Retrieval floor on kristeva's A380, never on preemptible hardware.**
- **The 5070 Ti utility roster ships as one pod** holding the node's whole
  advertised GPU budget (all-or-nothing eviction).
- **Escalation is coordinator-driven; no cross-model proxy fallbacks.**
  (Decided 2026-08-21, from Phor's finding that LiteLLM does not re-check a
  key's model allowlist on the fallback path.) A cross-model fallback would
  both leak past key scopes and turn the worker key's 429 backpressure into a
  paid spillway. The coordinator escalates after reading a failure. Any
  future proxy fallback must be **same model, different host**, its targets
  granted to no key directly, and every key's scope must contain its
  aliases' fallback closure (validator-enforced).
- **Ordering via Flux `dependsOn`, not file moves.** (Decided 2026-08-21,
  Phor's shape.) The serving CRs stay in their own tree/Kustomization; the
  litellm Kustomization depends on it.
- **Luna@`max` on the subscription seats** (coordinator, worker-escalated;
  Terra only behind the explicit-choice `coordinator-heavy`). GLM 5.3
  SKIPPED for worker-escalated (2026-08-22) — with escalation
  coordinator-driven there is no volume lane for coding-plan economics to
  bite on; on record as the alternative if one returns.
- **reviewer-escalated = K3.** Moonshot metered now; the Kimi Code sub
  endpoint promotes to rung 1 when its waitlist clears, metered demotes to
  same-model fallback. NeuralWatt (K3 at Moonshot parity) is the recorded
  rung 3. Effort: on the sub endpoint, `reasoning_effort high, NEVER none`.

## Conventions

- Commit/deploy via jj: `jj describe -m`, `jj bookmark set main`, `jj git push`,
  then `flux reconcile` the affected Kustomization.
- One live intervention at a time; verify each before the next.
- Record benchmark results and negative results as comments **in the manifest
  that holds the tunable**, plus a running log in `plans/llm/bench-notes.md`.
- Single-operator homelab: prefer the simplest mechanism that answers the
  question; skip production-grade ceremony unless a failure mode demands it.
- **Layout:** serving CRs keep their own directory and Flux Kustomization;
  the litellm Kustomization declares `dependsOn` it, so backends always exist
  before the catalogue names them. New backends (e.g. the 5070 Ti roster)
  get their CRs beside the existing serving tree.
- **Weight staging via cache-prime Jobs** (Phor's pattern): a Job running the
  official `hf` CLI against the archive PVC — immutable Job names rotated per
  change, `kustomize.toolkit.fluxcd.io/force: Enabled`. Works around the
  documented llmkube multi-file HF gap.

## Shipped (Waves 0–3, Tracks A–D) — summary only

Complete as of 2026-08-24 (ceiling restore amended 2026-08-28): truthful GPU
counts on iggy (2/2); `scripts/validate-llm-catalogue.py` guarding the
catalogue; one always-on FP8 backend at 262144 ctx / 8 seats / MTP=3
(A1/A2-pinned); role aliases + per-role keys (worker/reviewer budgets as
tripwires, coordinator rate caps, escalation $15/30d); cloud seats live and
smoked through their keys; A380 retrieval floor + Qdrant hybrid RAG behind
Open WebUI; kristeva CPU vision lane (D1) live and the MoE lane (D2) trialed
and deleted at 0.6 tok/s; pi harness lift with the delegation chain proven
end to end; escalation dashboard row and the caps-compose walkthrough.
Numbers and gotchas: `bench-notes.md`; per-tunable rationale: the manifests.

The delegation chain was proven non-interactively as of 2026-08-24. The
interactive shakedown the punch list left open — a live coordinator-seated pi
session driving a workflow to completion — closed on 2026-08-31: the harness
default seat moved to `coordinator` on 2026-08-30 16:44, and that session ran
`debug-until-green` (22:51 UTC) and `implement-and-validate` (02:17 UTC) to
`completed`, each fanning out worker and reviewer children at $0. Run ledgers
live outside this repo, under `~/.agents/local/pi/workflows/runs/`.

### Task-ID index

Comments across `kubernetes/` cite the task IDs this plan used to enumerate.
The checklists are gone; the IDs are kept here so those citations resolve.

- **T0.2** — `scripts/validate-llm-catalogue.py`, the catalogue guard.
- **T1.1** — the "seats over ceiling" retune (context traded for concurrency).
- **T1.2** — role aliases and per-role virtual keys.
- **T1.3** — fleet prune to one backend, and the ModelPool/ModelRouter teardown.
- **T1.4** — the escalation seat decisions (GLM skipped, Luna at max, K3 ladder).
- **Track A** — the LiteLLM lift and the proxy becoming the capability authority.
- **Track B / B5** — the retrieval floor: embedder, reranker, Qdrant hybrid RAG.
- **Track C** — the pi harness and the delegation chain.
- **Track D1** — the kristeva CPU vision lane.

`Idle Bench S*` citations point at `bench-notes.md`, which is unchanged.

## Remaining

### Parked with triggers

- **ToolHive-style MCP gateway** — revisit once MCP tool count actually hurts.
- **Overnight batch lane** — revisit only if unattended work outgrows the
  eight seats.
- **C7 · persistent in-cluster coordinator pod** — deferred, tied to Wave 4
  (2026-08-23): every benefit is about not sitting at the desktop, which
  starts mattering when Wave 4 absorbs the desktop into the cluster.
- **Hot-tier weight cleanup** — retired weights still occupy the 450Gi cache
  PVC; deliberately left (disk is not tight, NFS archive keeps the durable
  copies).
- **PAYG backstop under escalation** — if ever added, it must be the **same
  model on a metered host**, never a different cheap model. Default: skip.
- **Muse re-quant source** (Wave 4 G7): hunt an existing ≤12GB build vs.
  quantize locally.

### Waiting on events

- **Kimi Code waitlist** clears → promote the sub endpoint to
  reviewer-escalated rung 1 (see the alias manifest for the ladder).
- **Next litellm image bump** → re-test non-streaming on the chatgpt/
  provider (broken upstream at 1.97.0; every real consumer streams).

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
- [ ] **G9 revisit C7** (deferred 2026-08-23): once this wave retires
      the desktop as the daily driver, decide the persistent in-cluster
      coordinator pod for real.

**Done when:** a game streams, the roster yields and returns, and nothing on
the critical path noticed. (Milestone M5 — the one still open.)
