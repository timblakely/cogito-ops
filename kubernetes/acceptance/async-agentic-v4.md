# Async Agentic Homelab v4 — Acceptance Evidence

**Status:** acceptance-evidence record. This document does **not** change runtime behavior.
**Plan:** `plans/llm/async-agentic-homelab-v4.md` (v4, 2026-09-13).
**Deliverable:** #75 — Deliverable 1.

## Purpose

This document records **acceptance evidence** for the v4 async agentic homelab plan.
It is a record of what an operator observed when walking the documented
**Astra → GitHub → Luna → Foreman** path, with compact places to capture a run
identifier, a timestamp, and a sanitized evidence reference for each handoff and
the final outcome.

It does **not** change runtime behavior, and it does **not** assert that
acceptance has passed. Every checkbox below is intentionally left unchecked until
an operator records evidence for that step.

## Operator checklist

Each item is grounded in the v4 plan. Before checking a box, record a **run id /
timestamp** and a **sanitized evidence reference** (a link or identifier only —
no secrets, tokens, or raw transcripts).

- [ ] **Entry — Astra drafts and publishes the plan (Astra).**
  Astra returns `ready` and the gateway creates the plan issue: title
  `[plan] <first heading>`, labels `workflow/plan`, body = the plan, a
  `## Deliverables` checklist, and a matrix.to link to the thread (v4 §7.1).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

- [ ] **Handoff — Astra → GitHub (plan object reviewed).**
  The plan lives as the GitHub issue body; the owner reads, edits, and comments
  from GitHub; each body edit is a version (v4 §7.1–7.2).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

- [ ] **Handoff — GitHub → Luna (approval and decomposition).**
  Approval is the `workflow/approved` label (owner-applied, or a `/approve`
  comment the gateway converts into the label); the gateway freezes the body
  hash and creates the sub-issues in dependency order (v4 §7.3).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

- [ ] **Handoff — Luna → Foreman (Workloads created).**
  On approval Luna opens the implementation thread and, per deliverable in
  dependency order, calls `create_workload(sub_issue)` (v4 §8.1).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

- [ ] **Execution — Foreman runs the Workload pipeline.**
  Foreman runs coder → gate → two reviewers → PR with one repair round per
  deliverable (v4 §8.1).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

- [ ] **Final outcome — PR merged, plan issue closed.**
  The deliverable PR is merged (SHA-pinned async squash merge) and the plan
  issue closes on the last merge (v4 §8).
  - Run id / timestamp: `____`
  - Evidence (sanitized): `____`

## Implementation handoff

- **Repository gate selected for this path:** the `flux-local` job in
  `.github/workflows/flux-local.yaml` (summary check `flux-local-status`).
- **Selection rationale:** v4 repair R9 — "Gate runs flux-local for `kubernetes/`
  changes; ruleset on `main` requiring `flux-local-status`; gateway waits for
  checks before merge." This deliverable changes only
  `kubernetes/acceptance/async-agentic-v4.md`, a `kubernetes/` path, so the
  flux-local gate applies.
- **Required to pass before proceeding to Deliverable 2:**
  - the `flux-local` gate (`.github/workflows/flux-local.yaml`) passes, and
  - `git diff --check` passes.
- **Diff scope:** this deliverable changes only
  `kubernetes/acceptance/async-agentic-v4.md`.
