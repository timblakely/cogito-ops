# Cogito gateway runbook

The gateway owns durable transport and hard policy. Astra owns plan content,
Luna coordinates implementation, GitHub is the plan/review surface, and
Foreman is authoritative for coding, gates, and review state.

> **Retired 2026-10-21/23 — read before troubleshooting.** The agent-tier alias
> cleanup (`ab8324d`, `ced129f`, `52d949f`, `e117d35`) removed the planning
> scout fleet, the reviewer role, and the `planner`/`coordinator`/`reviewer`/
> `scout` LiteLLM aliases that this runbook used to describe. Foreman now runs
> one execution pool and the pipeline is coder → deterministic gate. The
> gateway still carries the scout and reviewer code paths (`coordinator/
> foreman.py`, `coordinator/luna.py`) and still defaults to the deleted
> `planner` and `coordinator` aliases (`coordinator/service.py:46,65`) with no
> `PLANNER_MODEL`/`COORDINATOR_MODEL` set in
> `kubernetes/apps/home-infra/matrix-coordinator/app/helmrelease.yaml` — so
> plan drafting and Luna turns resolve to aliases the catalogue no longer
> serves. Set those two variables to a live alias (currently
> `flashnext-deleuze`) before relying on intake, or wait for the announced
> agent-topology redesign. Do not re-add `planner` to a Foreman pool to
> "fix" a scout failure: the alias does not exist to serve it.

## Commands

- A top-level owner message in the configured Cogito project room opens
  conversational intake in a new thread. `!cogito plan <objective>` remains an
  alias in any room where the bot is joined. The
  Astra planner may ask up to two rounds of material questions or push back.
  It drafts from the conversation and the context you supply; local read-only
  Foreman scouts no longer perform repository exploration.
- `!cogito draft` ends intake or research immediately and drafts from
  completed work plus stated assumptions.
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
  progress before approval.
- `stop` in a plan thread cancels further orchestration. The plan card accepts
  ⏹ cancel, ⏸ pause, 🔄 resume/retry, and 🔍 investigate.

There is no Matrix merge command. Each deliverable gets its own Workload and
pull request. Foreman runs a coder and the deterministic gate. The two-profile
local review stage is retired: `kubectl -n llm get agents` lists exactly
`cogito-coder` (role `coder`, model `coder`) and `cogito-gate` (role
`verifier`), and the execution pool advertises `worker`/`coder`/`verifier`.
The gateway then asks GitHub for an asynchronous squash merge pinned to the
exact coder SHA. GitHub applies repository rules and required checks. A new
commit, draft PR, changed branch, foreign fork, non-`main` base, failed check,
or merge conflict blocks automation.

Deliverables run in checklist order. The next Workload is created only after
GitHub reports the preceding PR merged. A coder may use multiple commits inside
one PR. The plan completes only after every approved PR merges.

The originating `Cogito` thread is Astra's planning surface and contains an
edited gateway status card. Approval opens one Luna-owned thread in
`Implementation`; owner messages in that thread become Luna turns. Hookshot's
repository firehose lives in the muted `GitHub` room. The muted `Agent Runs`
room remains the destination for Foreman run notices; per-scout thread fan-out
is gone with the scout fleet. Foreman persists its detailed transcript at task
completion, so commands and outputs appear then rather than streaming live.

Foreman runs one role-routed FleetNode on `iggy`, `foreman-execution-agent`,
advertising `worker`/`coder`/`verifier` and receiving the push-capable GitHub
App token (`kubernetes/apps/llm/foreman/app/helmrelease.yaml`: the shared
default `githubToken.secretName` is empty precisely so a credential-free pool
can never inherit the rotating token). The credential boundary is still the
pool's advertised roles — a task requiring a role no pool advertises stays
unscheduled rather than landing on a credentialed agent.
While Astra synthesis or a Luna turn is active, the Cogito bot refreshes its
room-level Matrix typing indicator. Matrix does not provide a thread-scoped
typing indicator, so concurrent work in any Cogito thread makes the bot appear
to type in the room as a whole.
Inference-connectivity failures are reduced to a bounded classification before
Astra sees them; raw Job logs are not copied into paid-model context.

## Plan-to-merge acceptance check

The acceptance path is complete when, in order:

1. Astra's draft appears as the plan issue and Matrix link.
2. GitHub label or `/approve` freezes its current hash and creates sub-issues.
3. Luna opens an implementation thread and dispatches one Workload.
4. Coder and gate succeed; evidence appears on the PR.
5. The required `Flux Local Success` check passes and the SHA-pinned merge lands.

[Async agentic v4 acceptance evidence](../../kubernetes/acceptance/async-agentic-v4.md)

## Inspect and recover

```sh
kubectl -n llm get workloads,agentictasks,fleetnodes
kubectl -n llm describe workload <name>
kubectl -n llm get agents
kubectl -n llm logs deploy/foreman-operator
kubectl -n llm logs deploy/foreman-execution-agent
kubectl -n home-infra logs deploy/gateway -c main --tail=100
```

`deploy/foreman-agent` does not exist; the agent deployment is
`deploy/foreman-execution-agent`.

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
remain deleted. Scout-era rows are historical only — nothing writes new ones.
