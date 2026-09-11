# Matrix development coordinator runbook

Matrix through Commet is the normal human control plane. GitHub stores accepted
work and code review, Argo stores execution state, Garage stores artifacts, and
the coordinator SQLite volume stores reconciliation and audit state.

## Normal use

Start a plan in the applicable project room:

```text
!cogito plan <objective>
```

Reply in its thread with ordinary review comments. After all comments are
present, send `!cogito revise` in the same thread. For normal interactive
approval, the coordinator resolves and records the current version's hash:

```text
!cogito approve
```

Automation may pin a version explicitly with `!cogito approve sha256:<hash>`.
A delayed hashless command fails if its Matrix timestamp predates the current
plan version.

Approval creates a parent issue and native sub-issues, then queues bounded Pi
and OpenCode worker runs. Successful workers publish only an explicit
`agent/<run-id>` ref. The coordinator opens a PR, dispatches a different
role-scoped reviewer, records review evidence, waits for GitHub checks, and
merges low-risk changes. Workload and high-risk changes produce an approval
card. Approve the exact reviewed head from that card:

```text
!cogito merge <worker-run-id> <full-head-sha>
```

The approval becomes invalid if the PR head changes. Useful recovery commands
are `!cogito status <run-id>`, `cancel`, `pause`, and `resume` with the same run
ID. `!cogito stop` durably stops reconciliation and requests cancellation of
active runs. `!cogito start` clears the stop.

## Routine verification

Use the repository's direct tools and the checked-in kubeconfig:

```sh
kubectl get kustomization -n home-infra matrix-coordinator
kubectl get helmrelease -n home-infra matrix-coordinator
kubectl get pods -n home-infra -l app.kubernetes.io/name=matrix-coordinator
kubectl get workflows -n tools
kubectl logs -n home-infra deploy/matrix-coordinator -c main --tail=200
kubectl logs -n home-infra deploy/matrix-coordinator -c bot --tail=200
```

Healthy state means the Flux Kustomization and HelmRelease are Ready at the
same Git revision, the coordinator and bot containers are Ready, and no old
Workflow remains active unexpectedly. The `/healthz` endpoint checks process
availability. Prometheus and the Argo dashboard cover availability and workflow
failures; Matrix carries actionable run state.

## Replay and restart recovery

Matrix event IDs, GitHub delivery IDs, external actions, run IDs, and Matrix
outbox IDs are unique. Replaying a webhook or Matrix event is safe. Restart the
coordinator by deleting its pod or rolling its Deployment. On startup it opens
the existing SQLite volume, backfills older issue actions, finds Argo workflows
by `cogito.dev/run-id`, and resumes reconciliation.

For a missed GitHub webhook, redeliver it from the repository webhook page. The
signature and delivery ID are checked before processing. Periodic GitHub issue
reconciliation also repairs missed issue events. A Matrix send remains pending
in `matrix_outbox` until the encrypted maubot sidecar acknowledges its stable
transaction ID.

Do not resubmit an altered request under an existing run ID. Create a new run
ID or let the bounded repair loop derive one. A remote `agent/<run-id>` ref at a
different SHA fails closed.

## Stuck workflows

Inspect the Workflow phase, message, nodes, and controller logs. Cancel through
Matrix first so coordinator state remains aligned. If the service is down,
patch `spec.shutdown: Terminate`, restore the service, and let reconciliation
record the terminal result.

The artifact policy is `Never`: result manifests, patches, and logs remain in
Garage when Workflow CRs expire. This avoids artifact-GC finalizers consuming
the controller's parallelism allowance. If a Workflow created under the former
policy retains `workflows.argoproj.io/artifact-gc`, preserve its result evidence,
clear that finalizer, and delete only the completed CR.

## State and E2EE recovery

The coordinator PVC and maubot crypto PVC are protected by their VolSync
ReplicationSources. To restore, stop the coordinator workload, restore each PVC
from the selected Kopia snapshot using the repository's established VolSync
restore procedure, then restart the workload. Verify:

1. prior plans, deliveries, and audit rows are present;
2. an old Matrix event and GitHub delivery replay without duplicate objects;
3. the bot can decrypt an existing thread and send an encrypted reply;
4. an Argo run submitted before the backup is rediscovered by run ID.

Never initialize a fresh maubot crypto store under the existing bot account
until recovery has been ruled out; that loses access to prior encrypted events.

## Credential rotation

Credentials remain in the Kubernetes 1Password vault. Rotate one identity at a
time, update the existing item field, wait for External Secrets to refresh, and
roll only the consuming workload. Relevant scopes are:

- coordinator internal HMAC and GitHub webhook HMAC;
- narrow GitHub API identity;
- Matrix bot access and E2EE identity;
- planner, worker, and reviewer LiteLLM virtual keys;
- Argo Garage access key.

After rotation, make one authenticated call or signed replay for that identity
and verify logs contain no credential value. Worker and reviewer keys must stay
restricted to their role aliases. The planner key must stay restricted to
planner seats. A model/provider change belongs in LiteLLM model configuration;
the coordinator contract and harness commands continue to use role names.

For an operator-generated LiteLLM virtual key, leave its generated Secret in
place while deleting the `LiteLLMVirtualKey`. The finalizer reads that Secret to
revoke the upstream key. Wait for the custom resource to disappear, reconcile
the `litellm` Kustomization so Flux recreates it, and wait for the new Secret and
Ready condition. Force-sync its `PushSecret`, verify a newer refresh time, then
call `/v1/models` with the new key and confirm that only the intended role alias
is visible before making a completion request. Do not delete the generated
Secret first. If it is missing, temporarily recover the old field from
1Password through an `ExternalSecret` so the finalizer can revoke it; remove
that temporary projection before Flux issues the replacement.

## Hookshot and Android push

Hookshot is the general GitHub bridge; the coordinator webhook is the durable
Cogito state input. Both service accounts are non-admin users. Room membership
and power levels are GitOps managed. ntfy is the UnifiedPush distributor that
wakes Commet; Synapse remains the source of the encrypted notification event.

After Matrix, Commet, ntfy, or Hookshot upgrades, test an encrypted message with
the phone locked on Wi-Fi and again on cellular with WireGuard available. Also
test offline replay after reconnecting. Direct ntfy publication is reserved for
emergency transport diagnostics.

### GitHub App enrollment

Create one private GitHub App named `Cogito Matrix Coordinator` and install it
only on `timblakely/cogito-ops`. Use
`https://hookshot.timblakely.com/github/webhook` as its webhook URL, generate a
webhook secret in 1Password, and leave user authorization disabled. Grant these
repository permissions: Actions read, Checks read, Contents read/write, Issues
read/write, Metadata read, and Pull requests read/write. Subscribe only to
issue, issue comment, pull request, pull request review, pull request review
comment, push, and workflow run events.

Generate one private key from the App settings page and place it directly in a
1Password item; never paste it into Matrix, GitHub issues, or this repository.
The item needs `app-id`, `installation-id`, `private-key`, and `webhook-secret`
fields. Record the App ID and installation ID for the GitOps change. The
External Secrets Operator `GithubAccessToken` generators mint repository-bound
installation tokens every 30 minutes in `home-infra` and `tools`; the private
key is not itself a Git credential. The coordinator rereads its projected token
file for every request. New agent runs use `agent-run-v1alpha7` and receive the
current generated token. Compatibility environment variables also resolve to
generated tokens, so an older coordinator or WorkflowTemplate does not require
the retired PAT.

The `timblakely/cogito-ops` Hookshot connection is a Matrix state event managed
by Terraform in `#project-cogito`. Hookshot also stores a private grant scoped
to that room and repository. After a complete Matrix restore onto a server that
does not contain the grant, send
`!hookshot github repo https://github.com/timblakely/cogito-ops` once in the
project room as an authorized administrator, then reconcile `matrix` again.
Normal upgrades and pod or controller restarts retain the grant in Matrix and
need no bootstrap command.

### Physical Commet acceptance

Run the test from `#project-cogito` in Commet. Lock the phone before each
expected state transition so the test exercises UnifiedPush rather than an
already-open sync connection.

1. Send `!cogito plan Add matrix-e2e.txt containing exactly matrix-ok followed
   by one newline, with no other changes. Include one deliverable and explicit
   acceptance checks.`
2. Reply in the plan thread with `Require exactly one trailing newline and no
   unrelated file changes.`, then send `!cogito revise` in the same thread.
3. Compare the revised text and send `!cogito approve`. Confirm the parent
   issue, deliverable issue, run, PR,
   independent review, checks, merge, and completion updates stay in that
   thread.
4. Repeat with a harmless file under `kubernetes/` so policy requires an exact
   head approval. Send the displayed
   `!cogito merge <worker-run-id> <full-head-sha>` without editing either value.
5. Perform one run on locked-screen Wi-Fi, one on cellular with WireGuard
   available, and one while offline followed by reconnect. Confirm ntfy wakes
   Commet, the encrypted Matrix event appears once, and the offline event
   replays once after reconnect.

Record the Matrix event IDs, GitHub object URLs, workflow names, reviewed head
SHA, merge SHA, network path, and whether the screen was locked. If Commet
misses a wake while the event exists in Matrix, repeat that transition in
FluffyChat to separate a Commet client fault from the Synapse/ntfy path.

## Full disablement and rollback

Send `!cogito stop`, verify active runs are cancelling or terminal, then suspend
the `matrix-coordinator` Flux Kustomization. Disable the GitHub repository
webhook if inbound delivery must stop immediately. Leave Synapse, Commet, and
ntfy running; they serve communication outside this workflow.

Rollback by moving the coordinator image tag to a previously recorded immutable
tag and digest, reconciling only the `matrix-coordinator` Kustomization, and
checking the SQLite schema compatibility noted in the target commit. Argo
WorkflowTemplates are immutable by name, so an older coordinator continues to
reference its matching template. Re-enable reconciliation with `!cogito start`
only after the coordinator, GitHub, and Argo views agree.

## Upgrades

Upgrade one boundary at a time. Pin chart, application, package, and image
versions and digests in Git. Render manifests, run coordinator unit and adapter
conformance tests, use server-side dry-run for WorkflowTemplates, and reconcile
only the affected Flux Kustomization. Complete a contract workflow followed by
one real role-routed run before advancing another component.
