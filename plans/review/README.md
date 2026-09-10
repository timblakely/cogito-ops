# Agent plan reviews

This directory is the durable handoff between planning agents, human review,
and implementation harnesses. Each plan gets its own draft pull request and
changes exactly one Markdown file in this directory.

1. A planning agent creates `plans/review/<short-name>.md` on a branch and opens
   a draft pull request.
2. Reviewers use GitHub line comments and normal review threads. The planning
   agent pushes revisions to the same pull request.
3. Tim marks the pull request ready and applies `workflow/plan-approved`.
4. GitHub records the approved commit and adds
   `workflow/implementation-queued`. A compatible harness may then claim it.
5. The harness pins the approved commit, implements in an isolated workspace,
   and opens a separate implementation pull request.

Pushing another plan revision removes approval and all implementation-state
labels. Plan approval authorizes implementation and opening an implementation
pull request; it does not authorize merge or unrelated changes.

The queue is deliberately independent of Matrix, LiteLLM, and any one harness.
Matrix carries notices and links. LiteLLM role aliases choose model capacity.
Pi, Hermes, OpenCode, or another runner consumes the same GitHub request.
Run one dispatcher for this repository at a time. GitHub label updates are not
an atomic compare-and-swap queue, so several independent pollers could race to
claim the same request. The dispatcher may choose any harness or model role
behind this contract.

## Queue contract

Discover work with GitHub's API or CLI:

```sh
gh pr list \
  --label workflow/implementation-queued \
  --state open \
  --json number,title,url,headRefOid,files,labels
```

A consumer must verify all of these immediately before mutation:

- the pull request is open and no longer a draft;
- its sole changed file matches `plans/review/*.md`;
- both `workflow/plan-approved` and `workflow/implementation-queued` exist;
- the current head SHA equals the SHA in the approval comment;
- the plan content is fetched from that pinned SHA.

Claiming replaces `workflow/implementation-queued` with
`workflow/implementation-running` and records the harness and workflow run ID
in a comment. Completion adds `workflow/implementation-complete` and links the
implementation pull request. A blocked or failed run adds
`workflow/implementation-failed` with a resumable run identifier. A consumer
must never treat a Matrix reply, notification delivery, or elapsed time as plan
approval.

The first consumer is Pi's durable delivery workflow. Its `worker` role performs
the implementation with local Qwen, and `reviewer` performs the independent
read-only pass. The escalated roles remain fallback seats selected by the
coordinator when evidence justifies their cost. Matrix Hookshot can mirror pull
request and review events into `#project-cogito`; GitHub remains authoritative
because Hookshot does not provide a transactional agent queue or guarantee one
Matrix thread per pull request.
