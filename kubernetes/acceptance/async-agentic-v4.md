# Async Agentic Homelab v4 — Acceptance Evidence

**Purpose.** This document records acceptance evidence for the async agentic
homelab v4 path: **Astra → GitHub → Luna → Foreman**. It is a record of what an
operator observed when running the acceptance exercise. It does **not** change
runtime behavior, configuration, or infrastructure, and it does **not** assert
that acceptance has passed — every item below is left unchecked until an
operator records sanitized evidence in the field beneath it.

**Scope / non-runtime disclaimer.** This file is evidence-only. It does not
deploy, trigger agent jobs, modify manifests, or touch live infrastructure. The
acceptance path it documents is defined in
[`plans/llm/async-agentic-homelab-v4.md`](../../plans/llm/async-agentic-homelab-v4.md).

## Run record

- Run identifier: `_`
- Timestamp (UTC): `_`
- Operator: `_`

## Operator checklist — Astra → GitHub → Luna → Foreman

Each item is grounded in the v4 plan. Leave it unchecked until the operator
records sanitized evidence in the field beneath it.

- [ ] **Astra drafts and publishes the plan.** Astra (the planner) produces the
      plan and writes it as the GitHub issue body via `publish_plan`.
  - Evidence (sanitized): `_`
- [ ] **Astra → GitHub: the plan issue exists and is reviewed.** The plan issue
      is present with the plan as its body; the owner reviews it through issue
      comments.
  - Evidence (sanitized): `_`
- [ ] **GitHub → Luna: approval is recorded and the event reaches the gateway.**
      The owner applies the `workflow/approved` label (or posts `/approve`,
      which the gateway turns into the label); the body hash is frozen; the
      repository webhook delivers the event to the gateway, coalesced into a
      Luna turn.
  - Evidence (sanitized): `_`
- [ ] **Luna → Foreman: a Workload is created per deliverable.** Luna (the
      coordinator) creates a Foreman Workload for the deliverable.
  - Evidence (sanitized): `_`
- [ ] **Foreman executes the Workload and produces the outcome.** Foreman runs
      the Workload pipeline (coder → gate → two reviewers → PR); the PR is
      merged in order and the plan issue closes on the last merge.
  - Evidence (sanitized): `_`

## Gate record (implementation handoff)

- **Path-specific repository gate:** the `flux-local` workflow
  (`.github/workflows/flux-local.yaml`).
- **Selection rationale:** it is the only path-matching gate for `kubernetes/**`.
  Its pre-job `tj-actions/changed-files` uses `files: kubernetes/**` with
  `files_ignore: kubernetes/**/*.md`, so it is **skipped** for this markdown
  file (it validates k8s manifests, not docs). No other path-matching gate
  applies to `kubernetes/acceptance/*.md`.
- **Required checks:** the `flux-local` gate (skipped for this path) and
  `git diff --check`.
- **Result:** `_`
