# Matrix coordinator

This is a deliberately narrow planning gateway. It accepts authenticated,
decrypted Matrix events from the maubot sidecar, versions plans, records exact
approvals, creates a GitHub parent issue plus native sub-issues, and submits one
serial Foreman `Workload` per deliverable. Foreman owns coding, verification,
repair, branch publication, and a two-profile reviewer quorum. The coordinator
queues a SHA-pinned GitHub merge only after that quorum and starts the next
deliverable only after the prior pull request merges.

The service uses only the Python standard library. Run its checks with:

```sh
python -m unittest discover -s tests -v
```

See [RUNBOOK.md](RUNBOOK.md) for the remaining commands and failure boundaries.
