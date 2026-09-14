# Async Agentic Homelab v4 — Acceptance Evidence

## Purpose

This document records **acceptance evidence** for the async agentic homelab v4
acceptance path: **Astra → GitHub → Luna → Foreman**. It is a record-keeping
artifact only. It does **not** change runtime behavior, deploy anything, trigger
agent jobs, or execute the operational acceptance exercise. Filling in the
checklist and evidence fields below is an operator action performed outside this
repository change; nothing in this file asserts that acceptance has passed.

The acceptance criteria below are grounded in the existing v4 plan
(`plans/llm/async-agentic-homelab-v4.md`): the documented entry action, each
handoff, and the final outcome. No transport, approval, or success semantics are
invented here beyond what that plan documents.

## Operator checklist (Astra → GitHub → Luna → Foreman)

Keep every box unchecked until the operator has actually performed and verified
the step. Do not check a box on the strength of this document alone.

- [ ] **Entry — Astra drafts and publishes the plan.** Astra (the planner)
      produces the plan and publishes it as the GitHub issue body
      (`publish_plan`), per the v4 plan's "GitHub issue from first draft" model.
- [ ] **Handoff Astra → GitHub — plan issue exists and is reviewed.** The plan
      issue exists with the plan as its body; the owner reviews it with issue
      comments (revisions are body edits, which GitHub keeps as edit history).
- [ ] **Approval on GitHub — plan is approved.** The owner applies the
      `workflow/approved` label, or posts an `/approve` issue comment that the
      gateway turns into that label; the body hash is frozen at that moment.
- [ ] **Handoff GitHub → Luna — approval reaches the coordinator.** The
      repository webhook delivers the approval event to the gateway; Luna (the
      coordinator) triages it and opens the implementation room — one thread per
      approved plan — linking the plan thread and the issues.
- [ ] **Handoff Luna → Foreman — Workloads are created.** Luna creates one
      Workload per deliverable and hands it to Foreman for execution.
- [ ] **Execution — Foreman runs the Workload.** Foreman executes the Workload
      pipeline: coder → gate Job → reviewer(s) → PR, with repair rounds up to
      `maxReviewIterations`.
- [ ] **Final outcome — PR merged, plan closed.** The resulting PR is merged in
      order and the plan issue closes on the last merge.

## Evidence record

Record a run identifier and timestamp for the acceptance run, then sanitized
evidence references (no credentials, secrets, or sensitive payloads) for each
handoff and the outcome.

- Run identifier: `_`
- Run timestamp (UTC): `_`
- Evidence — Astra → GitHub (plan issue / review): `_`
- Evidence — approval (`workflow/approved` label or `/approve`): `_`
- Evidence — GitHub → Luna (webhook event / implementation room): `_`
- Evidence — Luna → Foreman (Workload created): `_`
- Evidence — Foreman execution (coder → gate → reviewers → PR): `_`
- Evidence — final outcome (PR merged / plan issue closed): `_`

## Implementation handoff

- **Deliverable:** Deliverable 1 of issue #75 (parent plan #72) — create this
  acceptance-evidence document only.
- **Files changed:** `kubernetes/acceptance/async-agentic-v4.md` (new). No other
  file is changed by this deliverable.
- **Gate selected for this path:** `git diff --check`.
- **Selection rationale:** This change adds a single Markdown documentation file
  under `kubernetes/acceptance/`. It is not a Flux/Kustomize manifest and is not
  referenced by any `kustomization.yaml`, so the repository's `flux-local` gate
  (scoped by `GEMINI.md` to "k8s/flux changes" and run by
  `.github/workflows/flux-local.yaml`) does not apply to it. The applicable
  repository gate for this documentation-only path is therefore `git diff --check`
  (whitespace / merge-conflict-marker check), which the issue explicitly requires.
- **Gate status:** Not executed in this environment (the run monitor disabled
  shell access, so `git diff --check` and `flux-local` could not be run here).
  This is reported as **blocked pending execution**, not as passed. The
  executor / CI must run `git diff --check` (and, for completeness, confirm
  `flux-local` is unaffected) before this deliverable is accepted. No check is
  claimed to have passed on the strength of this document.
