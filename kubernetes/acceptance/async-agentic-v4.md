# Async Agentic Homelab v4 — Acceptance Evidence

**Status:** acceptance-evidence record. Every checkbox below is intentionally **unchecked**; nothing in this document asserts that acceptance has passed.

## Purpose

This document records the acceptance evidence for the async agentic homelab v4 flow described in `plans/llm/async-agentic-homelab-v4.md`. It is a record of what an operator observed when running that flow end to end. It **records acceptance evidence only; it does not change any runtime behavior.** It exists so that, once the flow is implemented, an operator can capture a run identifier, a timestamp, and sanitized evidence for each handoff and the final outcome, and only then mark the matching checkbox.

The flow under acceptance is the v4 path: **Astra → GitHub → Luna → Foreman**.

## Operator checklist

Every box starts unchecked. Check a box only after the matching evidence is recorded in the `Run` and `Evidence` lines for a single run.

- [ ] **Entry action — Astra drafts the plan as a GitHub issue.** The owner's request in the Matrix room causes Astra to write the plan as the GitHub issue body; the issue is the plan object from first draft.
  - Run (id / timestamp): `____`
  - Evidence (sanitized): `____`
- [ ] **Handoff — Astra → GitHub.** The plan issue is created carrying the deliverables checklist (nested for sub-deliverables).
  - Run (id / timestamp): `____`
  - Evidence (sanitized): `____`
- [ ] **Handoff — GitHub → Luna.** The repository webhook delivers the GitHub event to the gateway; Luna triages it, and approval is recorded as the `workflow/approved` label (applied by the owner, or by the gateway on an `/approve` comment).
  - Run (id / timestamp): `____`
  - Evidence (sanitized): `____`
- [ ] **Handoff — Luna → Foreman.** Luna opens one Workload per deliverable; Foreman runs the fixed pipeline per issue (coder → gate Job → reviewer(s) → PR).
  - Run (id / timestamp): `____`
  - Evidence (sanitized): `____`
- [ ] **Final outcome.** The PR reaches quorum (two distinct reviewer Agents) and is merged (SHA-pinned async squash merge).
  - Run (id / timestamp): `____`
  - Evidence (sanitized): `____`

## Implementation handoff

- **Gate selected for this path:** the repository's `flux-local` GitHub Actions workflow (`.github/workflows/flux-local.yaml`), in addition to the universal `git diff --check`.
- **Selection rationale:** This deliverable changes only `kubernetes/acceptance/async-agentic-v4.md`, a Markdown file under `kubernetes/`. The `flux-local` workflow's pre-job uses `tj-actions/changed-files` with `files: kubernetes/**` and `files_ignore: kubernetes/**/*.md`, so a Markdown-only change yields `any_changed = false`; the `test` and `diff` jobs are skipped and the workflow reports "All jobs passed or skipped". `git diff --check` is the base whitespace/conflict-marker check that applies to every change.
- **Required before proceeding to Deliverable 2:** the `flux-local` gate and `git diff --check` must both pass, and the diff must be inspected to confirm this deliverable changes only `kubernetes/acceptance/async-agentic-v4.md`.

## Notes

- This document records acceptance evidence only; it does not change runtime behavior.
- Do not mark any checkbox as passed until the matching run's evidence is recorded above.
