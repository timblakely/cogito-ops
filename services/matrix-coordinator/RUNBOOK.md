# Matrix-to-Foreman runbook

The coordinator owns planning, approval, serial deliverable dispatch, and the
narrow merge policy. GitHub stores accepted work and performs merges; Foreman
is authoritative for coding, gates, and review state.

## Commands

- `!cogito plan <objective>` creates a versioned plan in a new thread.
- Ordinary thread replies are revision comments.
- `!cogito revise` creates a new plan version from those comments.
- `!cogito approve [sha256:…]` accepts the current exact version, creates the
  GitHub issue hierarchy, and starts the first deliverable. Approval authorizes
  every listed deliverable to merge when its policy gates pass.
- `!cogito status [workload]` reads current Foreman status. Without a name it
  uses the Workload associated with the current plan thread.

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

Routine task progress is intentionally silent. Commet receives the approval/
start message, actionable blocked states, each merged PR, and final plan
completion. Use `!cogito status` for intermediate task counts.

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

The SQLite volume contains plan versions, comments, exact approvals, ordered
deliverable correlation, Workload names, the SHA-pinned asynchronous merge
receipt, Matrix replay/outbox records, idempotent issue-creation actions, and
audit records. Foreman CRs contain execution and review state; GitHub contains
check and merge state. The v7 migration adds only the serial-delivery boundary;
retired run, delivery, control, and work-item tables remain deleted.
