# Async agentic homelab v4 — acceptance evidence

## Purpose

This document records acceptance evidence for the async agentic homelab v4
acceptance path: **Astra -> GitHub -> Luna -> Foreman**. It is a template for
an operator to fill in after running the path once. It does **not** change
runtime behavior, does **not** execute the operational acceptance exercise,
and does **not** assert that acceptance has passed. Every checkbox below
starts unchecked; an operator marks a box only after recording the
corresponding sanitized evidence.

Each checklist item is grounded in `plans/llm/async-agentic-homelab-v4.md`
(§7 Plans, §8 Execution). This document records evidence only; it does not
define transport, approval, or success semantics beyond what the plan states.

## Run

- Run identifier: `<run-id>`
- Timestamp (UTC): `<YYYY-MM-DDTHH:MM:SSZ>`
- Operator: `<operator>`

## Operator checklist

- [ ] **Entry — Astra drafts the plan.** The owner starts a thread in
  `#project-cogito`; Astra returns `ready` and the gateway creates the plan
  issue (title `[plan] <first heading>`, label `workflow/plan`, body =
  `plan_markdown`).
  - Evidence (sanitized): `<plan issue link>`
- [ ] **Handoff — Astra -> GitHub.** The plan issue is created and the
  `#project-cogito` thread receives `◆ Astra: Plan drafted → <issue link>`
  with a mention. The plan text is not posted in Matrix.
  - Evidence (sanitized): `<issue link / thread reference>`
- [ ] **GitHub — review and approval.** The owner reviews the issue and
  approves it via the `workflow/approved` label or an `/approve` comment; the
  gateway freezes the body hash, creates the sub-issues from the checklist,
  and moves the plan to `APPROVED`.
  - Evidence (sanitized): `<approval label / comment reference>`
- [ ] **Handoff — GitHub -> Luna.** On `APPROVED`, the gateway opens a thread
  in `#implementation` and starts Luna's loop.
  - Evidence (sanitized): `<implementation thread reference>`
- [ ] **Handoff — Luna -> Foreman.** For a deliverable, Luna calls
  `create_workload(sub_issue)`; Foreman runs coder -> gate -> two reviewers ->
  PR with one repair round.
  - Evidence (sanitized): `<workload / PR reference>`
- [ ] **Outcome — merge and summary.** On success and quorum, the gateway
  merges SHA-pinned and Luna posts the deliverable's summary in the
  `#implementation` thread.
  - Evidence (sanitized): `<merge SHA / summary reference>`

## Non-runtime statement

This document records acceptance evidence only. It does not change runtime
behavior, does not perform deployments, does not trigger agent jobs, and does
not modify live infrastructure. Checking a box records that the operator
observed the corresponding handoff or outcome; it does not, by itself,
establish that acceptance has passed.

## Implementation handoff — repository gate

- Path: `kubernetes/acceptance/async-agentic-v4.md`
- Selected gate: `flux-local` (the repository gate for `kubernetes/` changes,
  per `plans/llm/async-agentic-homelab-v4.md` §8.5: "flux-local for
  `kubernetes/` changes ... `git diff --check` as lint"), plus `git diff --check`.
- Selection rationale: the only changed file is a Markdown document under
  `kubernetes/`. The `flux-local` workflow's `pre-job` uses
  `files_ignore: kubernetes/**/*.md`, so a Markdown-only change yields
  `any_changed=false`; the `test` and `diff` jobs are skipped and
  `flux-local-status` passes with all jobs skipped. No cluster, no
  `flux-local` binary, and no runtime state are required or touched.
  `git diff --check` is the lint gate for whitespace errors.
- Required to pass: `flux-local` (skipped for this path) and `git diff --check`.
- Result: `<record result>`
