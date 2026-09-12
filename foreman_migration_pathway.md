# Foreman migration pathway

Status: Foreman migration implemented; quorum auto-merge acceptance remains

Owner: Tim

Target: LLMKube Foreman owns the coding pipeline after plan approval

Primary human interface: Commet over Matrix

Infrastructure source of truth: this repository

## Decision

Replace Cogito's custom post-approval execution platform with LLMKube Foreman.
Keep the part that is actually specific to Cogito: plan drafting and revision in
an encrypted Matrix thread, approval of an exact plan version, creation of the
GitHub parent issue and deliverable issues, and concise status back to that
thread.

After approval, Foreman owns scheduling, workspaces, the agent loop, gates,
review, repair/escalation, branch publication, and pull-request creation.
Approval also authorizes each listed deliverable to merge after two distinct
Foreman reviewer profiles return `GO` against the final coder revision. The
thin gateway pins that exact SHA in an asynchronous GitHub merge request;
GitHub remains authoritative for repository rules, checks, and the merge.

This is a replacement, not a compatibility project. There will be no parallel
production path, soak period, historical run import, generic harness adapter,
or local mirror of Foreman state. One successful real workload is sufficient
to cut over; Git history is the rollback mechanism.

Upstream references reviewed for this plan:

- [Foreman overview](https://llmkube.com/docs/foreman)
- [Foreman language gates](https://llmkube.com/docs/foreman/language-gates)
- [LLMKube releases](https://github.com/defilantech/LLMKube/releases)

The repository currently pins LLMKube core 0.9.18. At the time of this review,
0.9.25 is the current upstream release and publishes `llmkube` and `foreman` as
separate sibling charts. Implementation should select one reviewed release and
pin both charts by OCI digest rather than copying version numbers from this
document.

## Current workflow

The current path works, but its ownership boundary is much larger than the
Matrix feature requires:

```text
Commet / Matrix
  -> maubot plugin
  -> Python coordinator + SQLite
  -> GitHub parent issue and sub-issues
  -> Argo Workflow
  -> custom agent-runtime image
  -> Pi or OpenCode
  -> custom Git workspace and branch publisher
  -> coordinator PR, review, repair, merge, and issue reconciliation
  -> SQLite outbox
  -> Matrix thread
```

The maintained surface visible in this repository includes:

| Area | Current implementation | Migration result |
| --- | --- | --- |
| Matrix E2EE and commands | maubot plugin plus coordinator HTTP boundary | Keep, then reduce to planning, approval, dispatch, and status |
| Planning | direct LiteLLM `planner` client with versioned Matrix review | Keep |
| Accepted work | GitHub parent issue and native sub-issues | Keep; these are Foreman inputs |
| Durable orchestration | `argo.py`, `runs.py`, eight agent-run WorkflowTemplates plus approval/smoke templates, Argo controller/UI/RBAC | Delete |
| Execution | custom Pi/OpenCode adapters and `cogito-agent-runtime` image | Delete |
| Workspace and publication | custom clone, path checking, commit, push, and artifact code | Delete |
| Delivery control | `deliveries.py` implements PR creation, reviews, repair, risk, and merge | Delete |
| Mirrored state | SQLite run, delivery, external-action, audit, and outbox records | Retain only plan/approval, dispatch idempotency, and Matrix notification state |
| Artifacts | Argo stores run artifacts in a dedicated Garage bucket | Delete the Argo integration; do not replace it unless Foreman proves it needs configuration |
| Observability | custom coordinator and Argo dashboards/alerts | Delete execution-specific views; use Foreman/Kubernetes status |
| Model serving | digest-pinned LLMKube core 0.9.18 and LiteLLM role endpoints | Keep; install the sibling Foreman chart at the selected release |

In concrete terms, the coordinator service is about 2,400 lines of Python, the
Argo template file is about 1,100 lines, and the coordinator schema owns fourteen
tables. The target is not to port these lines to a Kubernetes watcher. It is to
remove the responsibilities they encode.

Argo currently has no repository-managed workload other than these agent-run
templates. Once Foreman is authoritative, the entire Argo Workflows app can be
removed from Cogito rather than retained speculatively. Garage itself remains
because other cluster services use it; only its Argo bucket credentials and
dependency are in scope for removal.

## Target boundary

```text
Commet / Matrix
  -> thin planning gateway
  -> GitHub parent issue and deliverable issues
  -> one serial Foreman Workload per deliverable
  -> Foreman AgenticTasks / Agents / FleetNodes
  -> pull request + two-reviewer GO quorum
  -> SHA-pinned asynchronous merge in GitHub

Foreman Workload status
  -> thin planning gateway
  -> originating Matrix thread
```

| Responsibility | Owner after migration |
| --- | --- |
| Encrypted conversation and Android wake-up | Commet, Matrix, Synapse, and ntfy |
| Plan generation, revision, version hash, and approval identity | Thin Matrix gateway |
| Accepted plan and deliverables | GitHub issues |
| Translation of each accepted deliverable into a serial `Workload` | Thin Matrix gateway |
| Coding pipeline and execution state | Foreman `Workload` and `AgenticTask` |
| Agent roles, tool access, and concurrency | Foreman `Agent` |
| Execution placement | Foreman `FleetNode` scheduler |
| Workspace, branch, gate, review, repair, and PR creation | Foreman |
| Quorum policy and exact reviewed SHA authorization | Thin Matrix gateway |
| Required checks, repository rules, queueing, and merge | GitHub |
| Human-readable execution status | Matrix projection of Foreman conditions; Hookshot may continue to show GitHub events |
| Inference | Existing LLMKube and LiteLLM endpoints |

The gateway may persist Matrix event IDs, plan versions and hashes, approval
identity, GitHub issue IDs, Foreman Workload names/UIDs, the exact merge SHA and
asynchronous request receipt, and Matrix outbox transaction IDs. It must not
persist task lifecycle, attempt counts, transcripts, or check state merely to
mirror Foreman or GitHub.

Use deterministic correlation rather than reconciliation machinery:

- label the Workload with the plan ID;
- annotate it with the accepted plan hash, Matrix room/thread IDs, and parent
  issue URL;
- derive its name from the plan ID, accepted hash, and deliverable position;
- use one GitHub deliverable issue number per Workload and dispatch the next
  only after its predecessor merges;
- treat creation of an already-identical Workload as success and a conflicting
  spec under the same name as an error.

## Milestone F — Foreman replaces custom coding execution

Outcome: approving a plan in Commet creates exactly one Foreman Workload;
Foreman produces a gated and reviewed draft PR; useful status returns to the
originating Matrix thread; and Cogito no longer deploys or builds its own
coding executor.

The submilestones are intentionally short. Each ends in a usable state and
moves ownership directly to Foreman.

Implementation evidence (2026-09-11): LLMKube and Foreman 0.9.25 reconciled
Ready; all three Cogito Agent CRs validated; a FleetNode registered on `iggy`; and
documentation issue #21 completed as Workload `foreman-acceptance-21-v5` with
coder `GO`, deterministic `GATE-PASS`, reviewer `GO`, and draft PR #22. The
retired Argo Flux applications, managed resources, CRDs, and terminal workflow
history were removed. The remaining unchecked items deliberately require a
normal plan initiated in Commet and Tim's manual GitHub merge; the direct
Workload acceptance does not pretend to cover that human boundary.

### F1 — Pin and install the upstream control plane

- [x] **F1.1** Review the releases since the repository's LLMKube 0.9.18 pin,
  choose one LLMKube/Foreman release, and record both OCI digests.
- [x] **F1.2** Upgrade LLMKube core to that reviewed release and add the sibling
  Foreman OCIRepository and HelmRelease through Flux.
- [x] **F1.3** Configure the chart's existing GitHub and model credential
  interfaces from 1Password/External Secrets; do not add a credential adapter.
- [x] **F1.4** Give the Foreman operator and agent pools only the namespace,
  GitHub, workspace, Job, and inference access required by upstream.
- [x] **F1.5** Reconcile and verify the pinned charts, CRDs, controller, webhook,
  Agent validation conditions, and at least one registered FleetNode.

Acceptance: the matching pinned LLMKube and Foreman releases are Ready, with no
Cogito fork or custom controller.

### F2 — Describe Cogito as Foreman configuration

- [x] **F2.1** Define a coder `Agent` using the existing worker model endpoint
  and the smallest upstream tool whitelist that can edit this repository.
- [x] **F2.2** Define a reviewer `Agent` using the existing reviewer endpoint;
  use Foreman's reviewer and escalation fields rather than coordinator code.
- [x] **F2.3** Define the minimal gate profile needed for Cogito. Reuse an
  upstream or already-pinned tool image where possible; do not create a general
  replacement for the current Argo template library.
- [x] **F2.4** Set Foreman concurrency at the Agent/pool level so the shared
  inference endpoint is not oversubscribed.
- [x] **F2.5** Manually apply one Workload for a harmless real documentation
  issue and confirm coder, gate, reviewer, branch, and draft PR completion.

Acceptance: an upstream-only Foreman pipeline turns one Cogito issue into a
reviewed draft PR. A failure here is a reason to stop and file an upstream gap,
not to build a local executor.

### F3 — Reduce the Matrix coordinator to a gateway

- [x] **F3.1** Replace Argo dispatch after `!cogito approve` with deterministic
  creation of one Foreman Workload containing the generated deliverable issue
  numbers and correlation metadata.
- [x] **F3.2** Replace run/delivery polling with a watch of Workload conditions
  and selected AgenticTask failure reasons. Post only phase changes, actionable
  failures, the draft PR link, and completion to the original thread.
- [x] **F3.3** Make `!cogito status` read Foreman directly. Remove custom
  pause/resume/retry/merge semantics unless the selected Foreman release exposes
  the same operation natively.
- [x] **F3.4** Remove direct GitHub PR/review/merge reconciliation from the
  coordinator. Keep only accepted-plan issue creation; let Hookshot report
  ordinary GitHub activity.
- [x] **F3.5** Reduce the state schema to plan/approval identity, Workload
  correlation, and Matrix send idempotency. Do not migrate completed run or
  delivery history; Matrix, GitHub, and Git already retain the experiment's
  useful record.
- [x] **F3.6** Narrow coordinator RBAC to Foreman Workload create/get/watch and
  read-only task status. It must not create or mutate AgenticTasks.

Acceptance: replaying the same Matrix approval finds the same Workload, and the
gateway contains no scheduler, agent loop, workspace, review, repair, or merge
implementation.

### F4 — Cut over on one real plan

- [x] **F4.1** Stop accepting new custom runs and ensure any currently active
  Argo agent run is terminal. Do not build a traffic switch or dual writer.
- [x] **F4.2** Make Foreman dispatch the only post-approval path.
- [ ] **F4.3** Complete one real Commet-originated plan through issue creation,
  Workload execution, gate, review, draft PR, manual GitHub merge, and final
  Matrix status.
- [ ] **F4.4** Record only the accepted plan hash, GitHub issue/PR links,
  Workload UID, and final Foreman conditions as acceptance evidence.

Acceptance: the normal path works once end to end. No soak window, synthetic
failure campaign, equivalent parallel run, Android network matrix, or legacy
state reconstruction is required for this experimental cluster.

### F5 — Delete the superseded platform

- [x] **F5.1** Remove `argo.py`, `runs.py`, `deliveries.py`, the AgentRun/result
  schemas, Pi/OpenCode adapters, harness runtime, and their obsolete tests.
- [x] **F5.2** Remove `Dockerfile.agent` and the agent-runtime build/publish job;
  keep only the thin gateway image build if it still exists as a separate
  service.
- [x] **F5.3** Remove the Argo Workflows app, all agent-run templates, its UI,
  OIDC client, RBAC, dashboard, alerts, Garage credentials, and the
  matrix-coordinator dependency on Argo resources.
- [x] **F5.4** Remove coordinator execution metrics, secrets, state tables,
  backup instructions, and runbooks that no longer describe a deployed
  responsibility.
- [x] **F5.5** Update `matrix_development_coordination.md`, the coordinator
  README/runbook, and architecture diagrams so Foreman is the sole execution
  owner and GitHub is the merge interface.
- [x] **F5.6** Run the remaining unit tests and repository manifest validation,
  render both charts, and reconcile the deletion through Flux.

Acceptance: `rg` finds no deployed Argo agent-run path, custom autonomous agent
runtime, harness adapter, or coordinator delivery loop. A fresh Flux install
reconstructs the Matrix gateway plus upstream LLMKube/Foreman without any
retired execution component.

### G — Quorum-authorized automatic delivery

Outcome: approving a plan authorizes its exact checklist. Each deliverable runs
from current `main`, receives two independent Foreman reviews, and is merged by
GitHub at the reviewed SHA before the next deliverable starts. This deliberately
supersedes F3.4's original human-merge boundary without restoring the retired
custom delivery engine.

- [x] **G1** Configure a validator reviewer and a separate falsification
  reviewer profile. Require both Foreman tasks to return `GO`; retain the
  deterministic gate and one bounded repair round.
- [x] **G2** Bind merge authorization to the final successful coder SHA and
  reject a draft PR, changed head, unexpected branch or fork, non-`main` base,
  missing reviewer, or reviewers that disagree on the PR.
- [x] **G3** Submit the authorized SHA through GitHub's asynchronous merge API
  so repository rules and required checks remain authoritative. Persist only
  its UUID and terminal result for crash-safe correlation.
- [x] **G4** Execute multi-deliverable plans serially: one issue, Workload, and
  PR at a time; dispatch the next item only after the prior merge completes.
  Multiple commits inside that PR are allowed and reviewed as one final diff.
- [x] **G5** Limit proactive Commet messages to acceptance/start, actionable
  blocked states, each merged PR, and final plan completion. Keep intermediate
  task counts behind `!cogito status`.
- [ ] **G6** Complete one new Commet-originated plan with at least two
  deliverables and record both reviewer identities, reviewed head SHAs,
  asynchronous merge results, PR links, and final Matrix completion.

Acceptance: the approved plan reaches `Completed` only after all of its PRs are
merged. A changed head or failed reviewer/check leaves the affected deliverable
blocked and does not dispatch its successors. No soak test, stacked-PR bridge,
or parallel legacy path is required for this experiment.

## Explicit non-goals

- preserving Pi/OpenCode interchangeability for autonomous runs;
- running old and new executors side by side;
- importing historical Argo or delivery records into Foreman;
- adding a second Matrix merge approval after the exact plan was approved;
- adding a generic Foreman executor, scheduler, state mirror, or PR bridge;
- creating custom dashboards before upstream status proves insufficient;
- proving controller/node-loss recovery, backup restore, long soaks, or every
  failure path before cutover;
- keeping Argo installed for hypothetical future workflows.

## Stop conditions

Pause the milestone rather than adding Cogito machinery if any of these are
true:

- Foreman cannot use the current GitHub repository/fork arrangement;
- its native loop cannot produce an acceptable change with the available
  tool-calling models;
- a Cogito gate cannot be expressed as `gateProfile` configuration;
- it cannot create a reviewable draft PR or surface a stable terminal result;
- the missing feature is generally useful and upstream will not own it.

Those results would mean Foreman is not yet the right replacement. They would
not justify rebuilding the current platform as a compatibility layer.

## Rollback

Before F5, stop creating Foreman Workloads and revert the F3/F4 gateway change.
After F5, revert the F5 deletion and the gateway cutover commits. Do not keep a
live legacy stack solely to make rollback instant; this is an experiment, and
Git plus the existing immutable image references are sufficient.
