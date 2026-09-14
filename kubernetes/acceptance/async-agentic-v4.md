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

## Post-acceptance phone image path

- Runtime and GitOps support merged in
  [PR #115](https://github.com/timblakely/cogito-ops/pull/115) at
  `2d5196c81aeb1f41e172bc515c2600794149a18a`; the immutable image pin merged in
  [PR #116](https://github.com/timblakely/cogito-ops/pull/116) at
  `33f04cc9ff443a329cf9be6f3a35ed09f3791d7c`.
- Flux applied the exact pin revision. The replacement gateway pod became Ready
  with both containers at zero restarts and main image digest
  `sha256:fd19eb5d50b8967960a0abcbf18cd68594681688871dde3e7d89f31ea8ce0754`.
- `LiteLLMModel/image`, `LiteLLMVirtualKey/image`, and its PushSecret reconciled;
  the downstream gateway Secret contains `LITELLM_IMAGE_API_KEY`.
- A generated 64 × 64 PNG split evenly between red and blue was described
  correctly through the deployed gateway `ImageClient` and local Muse route.
  The image-role key's attempt to call `reviewer` was rejected with HTTP 403.
- The running maubot sidecar contains the `m.image` handler and encrypted
  attachment decryption path. An owner-device Commet send remains the only
  uncompleted media-path check because it requires an event from the owner's
  logged-in device.

## Post-acceptance prefix-free project intake

- Prefix-free room routing merged in
  [PR #118](https://github.com/timblakely/cogito-ops/pull/118) at
  `c431555c7d0f93635a299697a11693b0890264bf`; its immutable image pin merged in
  [PR #119](https://github.com/timblakely/cogito-ops/pull/119) at
  `3a0679ff8d260d2b8ce4c085703bf2af21b90f8e`.
- The Matrix Terraform resource reconciled the exact source revision and wrote
  `cogito_project_room_id` to `matrix-rooms-outputs`. The bot and gateway each
  receive that output; ordinary top-level owner messages elsewhere stay ignored.
- Flux applied the exact pin revision. The replacement pod became Ready with
  zero restarts and main image digest
  `sha256:d62ee4ea6fc28ded0390b890334746f77d2c4c9c1491e45f018635baa312f3f2`.
  The bot startup log reports one configured project room.
- A side-effect-free probe against the running image used fake state and no
  network clients. The deployed handler converted `prefix free acceptance`
  into a plan objective and selected
  `https://github.com/timblakely/cogito-ops.git`; it did not create an issue or
  send a Matrix event.

## Post-acceptance Foreman credential and fleet audit

- The execution-supervisor credential fix merged in
  [PR #121](https://github.com/timblakely/cogito-ops/pull/121) at
  `60cf91c917d0c89ba89087244b0a4100e7dc734a`; Flux applied that exact `main`
  revision and Foreman reconciled at 0.9.27.
- The replacement execution Deployment became Ready with zero restarts. Its
  environment contains only `FLEET_NODE_NAME` and `POD_NAMESPACE`; it retains
  `--coder-git-secret=foreman-github-token` so new coder/reviewer Jobs receive
  the current rotating App token without projecting it into the long-lived
  supervisor.
- From the credential-free execution pod, anonymous `git ls-remote` resolved
  the public repository's `HEAD` to the exact merged revision above.
- The replacement FleetNode is Ready with roles worker, coder, verifier, and
  reviewer; maximum supervision capacity 2; and installed models
  `qwen3-8-27b` and `muse-glimmer-30b`. The separate scout FleetNode remains
  Ready with capacity 2 and no push-capable credential.

## Pre-owner fresh-start cleanup

- The clean-slate configuration merged in
  [PR #123](https://github.com/timblakely/cogito-ops/pull/123) at
  `2ae8fc4763275ca594ee4ff6f5c2907c02ab906f`; Flux applied that exact `main`
  revision and both `home-infra` and Matrix Terraform returned Ready.
- The unused `Agent Plans` and `Agent Alerts` rooms were removed from the
  Terraform room map, detached from state, and purged from Synapse. Their
  canonical aliases return HTTP 404. The retained agent rooms are Cogito,
  Implementation, Agent Runs, GitHub, and Agent Control; Personal rooms were
  not changed.
- Before repairing a Matrix-provider destroy-order failure, the complete state
  was copied to `tfstate-default-matrix-rooms-pre-cleanup-20260914`. The repair
  removed only the two obsolete room instances and their remaining membership
  instances; the next controller run produced a no-change, Ready state.
- The retained rooms had 2,261 non-state timeline events redacted, then their
  histories were purged. A client-API verification returned zero timeline
  events in four rooms and one membership state event in GitHub, with no old
  messages.
- The gateway now opens `/data/gateway.sqlite3`; plans, outbox records, Luna
  turns, and audit rows all started at zero. The prior
  `/data/coordinator.sqlite3` remains on the backed-up PVC as a recoverable
  archive.
- The one-use Synapse cleanup administrator was deactivated and erased, its
  access token and helper files were removed, and the temporary GitOps-account
  rate-limit override was removed.

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
