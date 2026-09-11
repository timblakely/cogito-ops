# Matrix coordinator

This is a deliberately narrow planning gateway. It accepts authenticated,
decrypted Matrix events from the maubot sidecar, versions plans, records exact
approvals, creates a GitHub parent issue plus native sub-issues, and submits one
Foreman `Workload` for the approved plan. Foreman owns coding, verification,
review, retries, branch publication, and draft pull requests. Execution
failures are diagnosed from the Foreman `Workload` and its child
`AgenticTasks`.

The service uses only the Python standard library. Run its checks with:

```sh
python -m unittest discover -s tests -v
```

See [RUNBOOK.md](RUNBOOK.md) for the remaining commands and failure boundaries.
