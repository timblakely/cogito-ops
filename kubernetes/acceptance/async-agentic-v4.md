# Async Agentic Homelab v4 — Acceptance Evidence

## Purpose

This document records acceptance evidence for the async agentic homelab v4 plan
(`plans/llm/async-agentic-homelab-v4.md`). It is an evidence record only: it does not
change any runtime behavior. Each checklist item is grounded in the v4 plan and is
checked by the operator only after the corresponding entry action, handoff, or outcome
has been observed. No item is pre-checked, and nothing here asserts that acceptance has
passed.

## Run

- Run identifier: `<run-id>`
- Timestamp (UTC): `<YYYY-MM-DDTHH:MM:SSZ>`

## Operator checklist

Check an item only after you have observed the corresponding step, and record a
sanitized evidence reference (no secrets, tokens, or raw transcripts).

### Entry — Astra

- [ ] A top-level message in the project room starts a planning session with Astra
      (v4 §5.2 "Routing by state"; §2 planning phase).
  - Evidence: `<sanitized reference>`

### Handoff — Astra → GitHub

- [ ] Astra returns a plan and the gateway creates or edits the plan issue whose body
      is the plan, linked in the thread (v4 §7.1; §5.2 "Plan issue as the plan object").
  - Evidence: `<sanitized reference>`

### Handoff — GitHub → Luna

- [ ] The owner approves the plan (label `workflow/approved` or `/approve`); the
      gateway freezes the body hash, creates sub-issues, and starts Luna's
      implementation loop (v4 §7.3; §8.1).
  - Evidence: `<sanitized reference>`

### Handoff — Luna → Foreman

- [ ] Luna creates a Workload for a deliverable and Foreman runs
      coder → gate → two reviewers → PR (v4 §8.1; §4 architecture).
  - Evidence: `<sanitized reference>`

### Final outcome

- [ ] On success and quorum the PR is merged (SHA-pinned) and the plan issue closes on
      the last merge (v4 §8.1; §2).
  - Evidence: `<sanitized reference>`

## Implementation handoff

- **Gate selected for this path:** Flux Local — the `Flux Local` workflow
  (`.github/workflows/flux-local.yaml`).
- **Selection rationale:** The v4 plan (§4 architecture) designates `flux-local` as the
  Foreman Workload pipeline gate, and this deliverable's path
  (`kubernetes/acceptance/async-agentic-v4.md`) is under `kubernetes/`, the path the
  Flux Local gate watches (`files: kubernetes/**`). For a markdown-only change under
  `kubernetes/` the gate's `test`/`diff` jobs are skipped
  (`files_ignore: kubernetes/**/*.md`), so the gate passes as "all jobs passed or
  skipped."
- **Required before proceeding to Deliverable 2** (verify, do not assume):
  - [ ] Flux Local gate passes (or is skipped for this markdown-only path).
  - [ ] `git diff --check` passes.
- **Diff scope:** this deliverable changes only `kubernetes/acceptance/async-agentic-v4.md`.
