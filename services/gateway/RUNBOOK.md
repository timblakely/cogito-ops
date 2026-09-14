# Cogito gateway runbook

The gateway owns durable transport and hard policy. Astra owns plan content,
Luna coordinates implementation, GitHub is the plan/review surface, and
Foreman is authoritative for coding, gates, and review state.

## Commands

- `!cogito plan <objective>` opens conversational intake in a new thread. The
  Astra planner may ask up to two rounds of material questions or push back. It
  delegates repository exploration, research, and command execution to local
  read-only Foreman scouts before posting version 1.
- `!cogito draft` ends intake or research immediately and drafts from completed
  scout summaries plus stated assumptions.
- The first draft is a `workflow/plan` GitHub issue. Matrix receives its link,
  not a second copy of the plan body. Ordinary planning-thread replies answer
  Astra during intake and become revision feedback after the first draft.
- `!cogito revise` creates a new plan version from those comments.
- Apply `workflow/approved` on the plan issue, or comment `/approve`. The
  allowlisted owner action freezes the exact current body hash and creates the
  native sub-issue hierarchy. The legacy Matrix approval command remains an
  alias during migration.
- `!cogito status [workload]` reads current Foreman status. Without a name it
uses the Workload associated with the current plan thread, or reports planning
  scout progress before approval.
- `stop` in a plan thread cancels further orchestration. The plan card accepts
  ⏹ cancel, ⏸ pause, 🔄 resume/retry, and 🔍 investigate.

There is no Matrix merge command. Each deliverable gets its own Workload and
pull request. Foreman runs a coder, deterministic gate, and two distinct local
reviewer profiles. Both reviewers must return `GO` against the final branch.
The gateway then asks GitHub for an asynchronous squash merge pinned to the
exact coder SHA. GitHub applies repository rules and required checks. A new
commit, draft PR, changed branch, foreign fork, non-`main` base, reviewer
`NO-GO`, failed check, or merge conflict blocks automation.

Deliverables run in checklist order. The next Workload is created only after
GitHub reports the preceding PR merged. A coder may use multiple commits inside
one PR; reviewers cover the complete final diff and any later commit invalidates
their SHA-bound authorization. The plan completes only after every approved PR
merges.

The originating `Cogito` thread is Astra's planning surface and contains an
edited gateway status card. Approval opens one Luna-owned thread in
`Implementation`; owner messages in that thread become Luna turns. Hookshot's
repository firehose lives in the muted `GitHub` room. Detailed scout traces
remain in the muted `Agent Runs` room.
Each delegated planning scout gets one durable thread in `Agent Runs`. Its root
records the exact delegated prompt and the plan/round correlation; replies show
scheduling and phase changes followed by the completed structured trace
(model-authored notes, tool calls, commands, bounded outputs, and evidence
summary). The originating plan thread receives Matrix links to those scout
threads after their root events are acknowledged. Private model reasoning is
never forwarded. Trace messages are size/count bounded and common credentials
are redacted, but operators should still avoid asking scouts to print secrets.
Foreman currently persists the detailed transcript at task completion, so
commands and outputs appear then rather than streaming live.

Foreman uses two role-routed FleetNodes on `iggy`: `execution` advertises
worker/coder/verifier/reviewer with two supervised slots and receives the
push-capable GitHub App token; `scouts` advertises planner with two slots and
receives only an intentionally empty token for anonymous public-repository
clones. A planning Agent's `requiredCapability.roles: [planner]` is the hard
credential boundary—do not remove it or add `planner` to the execution pool.
While local planning scouts or the subsequent Astra synthesis are active, the
Cogito bot refreshes its room-level Matrix typing indicator. Matrix does not
provide a thread-scoped typing indicator, so concurrent work in any Cogito
thread makes the bot appear to type in the room as a whole. During scout work,
typing is also refreshed in `Agent Runs`.
Repo-backed read-only scouts may be reported by Foreman as `NO-CHANGES` because
they correctly produce no diff. The gateway uses Foreman's preserved model
summary as research evidence rather than treating the no-diff wrapper as the
scout's answer.
The planning scout disables Foreman's coder-oriented edit-free detector while
retaining repeated-call and context guards. Inference-connectivity failures are
reduced to a bounded classification before Astra sees them; raw Job logs are
not copied into paid-model context.

## Commet acceptance check v2

The acceptance path is complete when, in order:

1. Astra's draft appears as the plan issue and Matrix link.
2. GitHub label or `/approve` freezes its current hash and creates sub-issues.
3. Luna opens an implementation thread and dispatches one Workload.
4. Coder, gate, and two distinct reviewers succeed; evidence appears on the PR.
5. The required `Flux Local Success` check passes and the SHA-pinned merge lands.

[Async agentic v4 acceptance evidence](../../kubernetes/acceptance/async-agentic-v4.md)

## Inspect and recover

```sh
kubectl -n llm get workloads,agentictasks,fleetnodes
kubectl -n llm describe workload <name>
kubectl -n llm logs deploy/foreman-operator
kubectl -n llm logs deploy/foreman-agent
```

The Workload name is deterministic from the plan ID, hash, and deliverable
position, so retrying an approval cannot create a second execution. A rejected or failed Workload should
be diagnosed directly from its conditions and child `AgenticTask` objects.
Delete and recreate it only when intentionally starting the experiment over;
there is no compatibility bridge or imported Argo history.

## Credentials

The gateway and Foreman each receive a namespace-local token from
the same GitHub App installation. The gateway needs issue write access;
Foreman needs contents and pull-request write access. External Secrets rotates
both projected tokens. The gateway reloads its token on every request. The
repository webhook has a separate HMAC secret and delivery IDs are replay-safe.

## State and backup

The SQLite volume contains durable planner-intake conversation, bounded planning
scout tasks and summaries, plan versions, comments, exact approvals, ordered
deliverable correlation, Workload names, the SHA-pinned asynchronous merge
receipt, Matrix replay/outbox records, idempotent issue-creation actions, and
audit records. Schema v11 adds coalesced coordinator events, replayable Luna
turns and token usage, plan notes, pause state, and Matrix edits. Foreman CRs
contain execution and review state; GitHub contains check and merge state. v10
added parent-notification correlation
so replies wait for Matrix to acknowledge their Agent Runs thread root; v9 adds
delegated planning research, v8 added planner intake, and v7 added the
serial-delivery boundary. Retired run, delivery, control, and work-item tables
remain deleted.
