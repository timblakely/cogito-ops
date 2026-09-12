# Matrix-to-Foreman runbook

The coordinator owns planning, approval, serial deliverable dispatch, and the
narrow merge policy. GitHub stores accepted work and performs merges; Foreman
is authoritative for coding, gates, and review state.

## Commands

- `!cogito plan <objective>` opens conversational intake in a new thread. The
  Astra planner may ask up to two rounds of material questions or push back. It
  delegates repository exploration, research, and command execution to local
  read-only Foreman scouts before posting version 1.
- `!cogito draft` ends intake or research immediately and drafts from completed
  scout summaries plus stated assumptions.
- Ordinary thread replies answer the planner during intake and become revision
  comments after the first draft.
- `!cogito revise` creates a new plan version from those comments.
- `!cogito approve [sha256:…]` accepts the current exact version, creates the
  GitHub issue hierarchy, and starts the first deliverable. Approval authorizes
  every listed deliverable to merge when its policy gates pass.
- `!cogito status [workload]` reads current Foreman status. Without a name it
  uses the Workload associated with the current plan thread, or reports planning
  scout progress before approval.

There is no Matrix merge command. Each deliverable gets its own Workload and
pull request. Foreman runs a coder, deterministic gate, and two distinct local
reviewer profiles. Both reviewers must return `GO` against the final branch.
The coordinator then asks GitHub for an asynchronous squash merge pinned to the
exact coder SHA. GitHub applies repository rules and required checks. A new
commit, draft PR, changed branch, foreign fork, non-`main` base, reviewer
`NO-GO`, failed check, or merge conflict blocks automation.

Deliverables run in checklist order. The next Workload is created only after
GitHub reports the preceding PR merged. A coder may use multiple commits inside
one PR; reviewers cover the complete final diff and any later commit invalidates
their SHA-bound authorization. The plan completes only after every approved PR
merges.

The originating `Cogito` thread is the control surface: planner conversation,
drafts, approval, actionable blockers, and final plan completion stay there.
Routine Foreman status changes, review quorum, per-deliverable merge messages,
and the Hookshot GitHub feed go to `Agent Runs`. Mute that room in Commet to
retain the workflow record without receiving operational notification spam.
Use `!cogito status` in the control thread for an on-demand snapshot.
While local planning scouts or the subsequent Astra synthesis are active, the
Cogito bot refreshes its room-level Matrix typing indicator. Matrix does not
provide a thread-scoped typing indicator, so concurrent work in any Cogito
thread makes the bot appear to type in the room as a whole.
Repo-backed read-only scouts may be reported by Foreman as `NO-CHANGES` because
they correctly produce no diff. The coordinator uses Foreman's preserved model
summary as research evidence rather than treating the no-diff wrapper as the
scout's answer.
The planning scout disables Foreman's coder-oriented edit-free detector while
retaining repeated-call and context guards. Inference-connectivity failures are
reduced to a bounded classification before Astra sees them; raw Job logs are
not copied into paid-model context.

## Commet acceptance check v2

The acceptance path is complete when, in order:

1. The plan is accepted.
2. The Foreman Workload completes with three successful tasks.
3. A draft pull request is opened.

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

The Matrix coordinator and Foreman each receive a namespace-local token from
the same GitHub App installation. The coordinator needs issue write access;
Foreman needs contents and pull-request write access. External Secrets rotates
both projected tokens. The coordinator reloads its token on every request.

## State and backup

The SQLite volume contains durable planner-intake conversation, bounded planning
scout tasks and summaries, plan versions, comments, exact approvals, ordered
deliverable correlation, Workload names, the SHA-pinned asynchronous merge
receipt, Matrix replay/outbox records, idempotent issue-creation actions, and
audit records. Foreman CRs contain execution and review state; GitHub contains
check and merge state. The v9 migration adds delegated planning research; v8
added planner intake and v7 added the serial-delivery boundary. Retired run,
delivery, control, and work-item tables remain deleted.
