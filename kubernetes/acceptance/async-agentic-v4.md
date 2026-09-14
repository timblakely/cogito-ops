# Async Agentic Homelab v4 — Acceptance Evidence

**Status:** accepted on 2026-09-14. This document does **not** change runtime behavior.
**Plan:** `plans/llm/async-agentic-homelab-v4.md` (v4, 2026-09-13).
**Acceptance run:** `plan-e30c8265b297db54`, GitHub plan issue
[#72](https://github.com/timblakely/cogito-ops/issues/72).

## Purpose

This document records **acceptance evidence** for the v4 async agentic homelab plan.
It is a record of what an operator observed when walking the documented
**Astra → GitHub → Luna → Foreman** path, with compact places to capture a run
identifier, a timestamp, and a sanitized evidence reference for each handoff and
the final outcome.

It does **not** change runtime behavior. The checklist below records the
sanitized evidence observed for the completed two-deliverable acceptance run.

## Operator checklist

Each item is grounded in the v4 plan. Before checking a box, record a **run id /
timestamp** and a **sanitized evidence reference** (a link or identifier only —
no secrets, tokens, or raw transcripts).

- [x] **Entry — Astra drafts and publishes the plan (Astra).**
  Astra returns `ready` and the gateway creates the plan issue: title
  `[plan] <first heading>`, labels `workflow/plan`, body = the plan, a
  `## Deliverables` checklist, and a matrix.to link to the thread (v4 §7.1).
  - Run id / timestamp: `plan-e30c8265b297db54` / `2026-09-14T03:11:17Z`
  - Evidence (sanitized): [plan issue #72](https://github.com/timblakely/cogito-ops/issues/72), whose body carries the plan ID, frozen content hash, deliverables, and Matrix thread link.

- [x] **Handoff — Astra → GitHub (plan object reviewed).**
  The plan lives as the GitHub issue body; the owner reads, edits, and comments
  from GitHub; each body edit is a version (v4 §7.1–7.2).
  - Run id / timestamp: plan version `1` / `2026-09-14T03:11:41Z`
  - Evidence (sanitized): owner [`/approve` comment](https://github.com/timblakely/cogito-ops/issues/72#issuecomment-5658453104) on the versioned plan issue.

- [x] **Handoff — GitHub → Luna (approval and decomposition).**
  Approval is the `workflow/approved` label (owner-applied, or a `/approve`
  comment the gateway converts into the label); the gateway freezes the body
  hash and creates the sub-issues in dependency order (v4 §7.3).
  - Run id / timestamp: gateway approval `2026-09-14T03:11:41Z`; sub-issues created `2026-09-14T03:23:14Z` and `03:23:16Z`
  - Evidence (sanitized): approved [plan #72](https://github.com/timblakely/cogito-ops/issues/72) and ordered deliverables [#75](https://github.com/timblakely/cogito-ops/issues/75) and [#76](https://github.com/timblakely/cogito-ops/issues/76).

- [x] **Handoff — Luna → Foreman (Workloads created).**
  On approval Luna opens the implementation thread and, per deliverable in
  dependency order, calls `create_workload(sub_issue)` (v4 §8.1).
  - Run id / timestamp: successful Workloads created `2026-09-14T07:31:05Z` and `08:07:38Z`
  - Evidence (sanitized): `plan-e30c8265b297db54-a0dbe97b8101-d1-a38` and `plan-e30c8265b297db54-a0dbe97b8101-d2-a2`, both correlated to implementation thread `$v4-acceptance-20260914-03`.

- [x] **Execution — Foreman runs the Workload pipeline.**
  Foreman runs coder → gate → two reviewers → PR with one repair round per
  deliverable (v4 §8.1).
  - Run id / timestamp: deliverable attempts `38` and `2`
  - Evidence (sanitized): both terminal Workloads report `Completed`, `4/4` child tasks succeeded; their outputs became [PR #98](https://github.com/timblakely/cogito-ops/pull/98) and [PR #100](https://github.com/timblakely/cogito-ops/pull/100), each with successful required checks.

- [x] **Final outcome — PR merged, plan issue closed.**
  The deliverable PR is merged (SHA-pinned async squash merge) and the plan
  issue closes on the last merge (v4 §8).
  - Run id / timestamp: `2026-09-14T08:16:36Z`
  - Evidence (sanitized): PRs [#98](https://github.com/timblakely/cogito-ops/pull/98) and [#100](https://github.com/timblakely/cogito-ops/pull/100) merged in order; both deliverable issues and final plan issue [#72](https://github.com/timblakely/cogito-ops/issues/72) closed.

## Run observations

- Luna completed `56` turns using `1,472,890` input and `28,419` output
  tokens for the plan.
- Deliverable 1 required 38 Workload attempts under Foreman 0.9.25. The
  post-acceptance reliability rollout upgraded Foreman and LLMKube to 0.9.27
  ([PR #108](https://github.com/timblakely/cogito-ops/pull/108)), rebuilt and
  deployed the matching planning-scout image
  ([PR #109](https://github.com/timblakely/cogito-ops/pull/109)), and forced
  `Recreate` for the two UUID-bound GPU lanes
  ([PR #110](https://github.com/timblakely/cogito-ops/pull/110)). Live
  validation found two Ready FleetNodes with four aggregate slots, no active
  Foreman Jobs, and both inference lanes Ready after the strategy change.

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
- **Recorded outcome:** both deliverable gates and required GitHub checks
  passed before their SHA-pinned squash merges.
