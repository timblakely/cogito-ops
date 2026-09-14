# Async Agentic Homelab v4 — Acceptance Evidence

**Status:** acceptance-evidence record, not yet accepted. Every checkbox below is intentionally left unchecked. This document records evidence that the v4 flow ran end-to-end; it does **not** change runtime behavior.

## Purpose

This is the acceptance-evidence record for the v4 async agentic homelab flow described in `plans/llm/async-agentic-homelab-v4.md`. For a single run it captures the operator-observed evidence that the documented path **Astra → GitHub → Luna → Foreman** executed and produced its documented final outcome. It is a record of evidence only: nothing in this file alters the gateway, Foreman, or any cluster component.

## Run record

- Run identifier: `________`
- Run timestamp (UTC): `________`

## Operator checklist

Each item is grounded in the v4 plan. Keep every box unchecked until the operator has filled in the sanitized evidence line beneath it.

### Entry action (owner → Astra)

- [ ] The owner triggered a plan in a Matrix room (`!cogito plan`); Astra drafted the plan and wrote it as the GitHub issue body (the plan object from first draft).
  - Evidence (sanitized): issue `#____`, room `____`

### Handoff 1 — Astra → GitHub

- [ ] Astra wrote the plan as the GitHub issue body; revisions were body edits; the owner reviewed via issue comments; approval was recorded as the `workflow/approved` label (applied by the owner or by the gateway on a `/approve` comment), with the body hash frozen at that moment.
  - Evidence (sanitized): issue `#____`, approval label/comment `____`

### Handoff 2 — GitHub → Luna

- [ ] The repository webhook delivered the GitHub event to the gateway (unfiltered by source); the gateway coalesced it by time; the resulting batch became a Luna turn in which Luna triaged the event.
  - Evidence (sanitized): webhook/batch ref `____`, Luna turn `____`

### Handoff 3 — Luna → Foreman

- [ ] Luna supervised execution at the Workload level and opened one Workload per deliverable; Foreman ran the fixed pipeline per issue (coder → gate Job → reviewer(s) → PR) with `maxReviewIterations` repair rounds and a two-reviewer quorum.
  - Evidence (sanitized): Workload `____`, PR `#____`

### Final outcome

- [ ] The PR reached quorum and was merged (SHA-pinned async squash merge); the deliverable is complete and the required checks passed.
  - Evidence (sanitized): merge commit `____`, checks `____`

## Implementation handoff — repository gate

- **Gate selected for this path:** the **Flux Local** gate — workflow `.github/workflows/flux-local.yaml`, summary job `flux-local-status`.
- **Selection rationale:** this deliverable changes only `kubernetes/acceptance/async-agentic-v4.md`, a path under `kubernetes/`, which is the Flux Local gate's trigger scope (`files: kubernetes/**`). Because the only changed file is a Markdown document, it matches the workflow's `files_ignore: kubernetes/**/*.md`, so the `test` and `diff` jobs are skipped (`any_changed == false`) and the gate is satisfied by the `flux-local-status` summary job reporting all jobs passed or skipped. This matches the v4 plan's R9 ("Gate runs flux-local for `kubernetes/` changes").
- **Required to pass:** the Flux Local gate (`flux-local-status`) **and** `git diff --check` (no whitespace errors).

## Acceptance status

Acceptance has **not** been asserted. The boxes below are the places to record it once the run evidence above is complete.

- [ ] All checklist items above are checked and their evidence lines are filled in.
- [ ] The Flux Local gate (`flux-local-status`) and `git diff --check` both pass.

> This document records acceptance evidence. It does not assert that acceptance has passed, and it does not change runtime behavior.
