# Matrix-to-Foreman runbook

The coordinator owns only planning and approval. GitHub stores the accepted
work items, and Foreman is authoritative for all execution state.

## Commands

- `!cogito plan <objective>` creates a versioned plan in a new thread.
- Ordinary thread replies are revision comments.
- `!cogito revise` creates a new plan version from those comments.
- `!cogito approve [sha256:…]` accepts the current exact version, creates the
  GitHub issue hierarchy, and creates one Foreman `Workload`.
- `!cogito status [workload]` reads current Foreman status. Without a name it
  uses the Workload associated with the current plan thread.

There is no Matrix merge command. Foreman opens a draft pull request after its
coder, deterministic gate, and reviewer succeed; a human handles it in GitHub.

## Inspect and recover

```sh
kubectl -n llm get workloads,agentictasks,fleetnodes
kubectl -n llm describe workload <name>
kubectl -n llm logs deploy/foreman-operator
kubectl -n llm logs deploy/foreman-agent
```

The Workload name is deterministic from the plan ID and hash, so retrying an
approval cannot create a second execution. A rejected or failed Workload should
be diagnosed directly from its conditions and child `AgenticTask` objects.
Delete and recreate it only when intentionally starting the experiment over;
there is no compatibility bridge or imported Argo history.

## Credentials

The Matrix coordinator and Foreman each receive a namespace-local token from
the same GitHub App installation. The coordinator needs issue write access;
Foreman needs contents and pull-request write access. External Secrets rotates
both projected tokens. The coordinator reloads its token on every request.

## State and backup

The SQLite volume contains plan versions, comments, exact approvals, Workload
correlation, Matrix replay/outbox records, idempotent issue-creation actions,
and audit records. Foreman CRs contain execution state. The v6 migration drops
the retired run, delivery, control, and work-item tables by design.
