# Async agentic homelab v4 — acceptance evidence

## Purpose

This document records **acceptance evidence** for the async agentic homelab v4
path. It is a record of what an operator observed when exercising the
Astra → GitHub → Luna → Foreman flow; it does **not** change runtime behavior,
deploy anything, or trigger any agent job. Filling in the checklist below is an
operator action performed outside this repository's runtime; the checkboxes
start unchecked and remain unchecked until an operator has actually run the
exercise and recorded sanitized evidence.

The acceptance path is grounded in the existing v4 plan
(`plans/llm/async-agentic-homelab-v4.md`): the owner posts a request in the
Matrix room, the gateway creates the plan issue (Astra), Luna triages the
GitHub events from `DRAFTED` on, and Luna drives Foreman workloads to a merged
PR and a closed issue (`DONE`).

## Run record

- Run identifier: `_`
- Timestamp (UTC): `_`
- Operator: `_`

## Operator checklist

Each item is grounded in the v4 plan. Keep every box unchecked until the
corresponding handoff has actually been observed and its sanitized evidence
recorded below.

- [ ] **Entry action — Astra.** Owner posts a request in the Matrix room; the
      gateway creates the plan issue (title `[plan] <first heading>`, label
      `workflow/plan`, body = `plan_markdown`) and posts
      `◆ Astra: Plan drafted → <issue link>` in the thread.
      - Evidence (sanitized): `_`
- [ ] **Handoff — Astra → GitHub.** The plan issue exists on GitHub with the
      `## Deliverables` checklist, plan id/hash markers, and the matrix.to
      thread link; the plan text is not posted in Matrix.
      - Evidence (sanitized): `_`
- [ ] **Handoff — GitHub → Luna.** From `DRAFTED` on, Luna triages the GitHub
      events (`issues.edited`, `issue_comment`, …) and acts (revision,
      question, or status) as an issue comment.
      - Evidence (sanitized): `_`
- [ ] **Handoff — Luna → Foreman.** On `APPROVED`, Luna calls
      `create_workload(sub_issue)`; Foreman runs coder → gate → two reviewers →
      PR with one repair round.
      - Evidence (sanitized): `_`
- [ ] **Final outcome — DONE.** On success and quorum the gateway merges
      (SHA-pinned); the last PR is merged, the plan issue is closed, and a
      mention is posted in the thread.
      - Evidence (sanitized): `_`

## Non-runtime disclaimer

This document is evidence only. Recording entries here does not change runtime
behavior, modify cluster configuration, or assert that acceptance has passed.
Acceptance is established only when an operator has completed the checklist
above with real, sanitized evidence.

## Implementation handoff

- **Path changed:** `kubernetes/acceptance/async-agentic-v4.md` (new file).
- **Gate-selection config:** `gateProfile` in
  `services/gateway/coordinator/foreman.py`. For a change under `kubernetes/`
  the profile selects the flux-local gate:
  `flux-local test --enable-helm --all-namespaces --path kubernetes/flux/cluster -v`.
- **Selection rationale:** The only path changed is a new Markdown file under
  `kubernetes/`. The CI `flux-local.yaml` workflow uses
  `files_ignore: kubernetes/**/*.md`, so a Markdown-only change under
  `kubernetes/` is skipped by that gate; the flux-local gate therefore does not
  apply to this documentation-only change. The always-on gate
  `git diff --check HEAD^ HEAD -- .` is the applicable repository gate for this
  path and is required to pass.
- **Required gates:** `git diff --check` (always-on) — must pass. The
  flux-local gate is not applicable to a Markdown-only `kubernetes/` change.
- **Result:** `git diff --check` passed (clean). The flux-local gate was not
  run because the only change is a new Markdown file under `kubernetes/`, which
  the CI `flux-local.yaml` workflow ignores via `files_ignore: kubernetes/**/*.md`.
