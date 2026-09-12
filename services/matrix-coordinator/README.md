# Matrix coordinator

This is a deliberately narrow planning gateway. It accepts authenticated,
decrypted Matrix events from the maubot sidecar, versions plans, records exact
approvals, creates a GitHub parent issue plus native sub-issues, and submits one
serial Foreman `Workload` per deliverable. Foreman owns coding, verification,
repair, branch publication, and a two-profile reviewer quorum. The coordinator
queues a SHA-pinned GitHub merge only after that quorum and starts the next
deliverable only after the prior pull request merges.

The `planner` role is Astra, used only for conversation and synthesis. When it
needs repository facts, upstream research, or command output, it delegates up
to four focused tasks to local read-only Foreman planning scouts. The durable
coordinator passes only their bounded summaries back to Astra, permits at most
two research rounds, and has no automatic paid-model fallback.

The service uses only the Python standard library. Run its checks with:

```sh
python -m unittest discover -s tests -v
```

See [RUNBOOK.md](RUNBOOK.md) for the remaining commands and failure boundaries.
