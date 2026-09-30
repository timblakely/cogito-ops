---
name: jj-workflow
description: Manage this repository's changes with Jujutsu, descriptive atomic commits, GitHub pushes, and Flux verification. Use when editing, splitting, syncing, committing, pushing, or repairing a deployment in this repo.
---

# Jujutsu workflow

## Inspect and sync

Use `jj` exclusively for version control, including reads. `jj git` is jj's
transport interface, not permission to invoke Git directly. If a Mise shim
fails, locate an installed jj binary; do not fall back to Git.

Start with `jj status`, `jj diff`, `jj log`, and `jj bookmark list`. Identify
the task's change IDs, destination bookmark, and any unrelated user work.
Fetch with `jj git fetch --remote origin` before splitting overlapping changes.
Rebase the unpublished task stack onto the intended upstream bookmark, for
example `jj rebase -s <stack-root-change-id> -d main@origin`.

Resolve conflicts by comparing the base, upstream, and local intent. Previously
merged work often survives in an old local change: retain newer upstream
behavior and remove duplicates rather than restoring obsolete settings. Ask
the user when the intended behavior cannot be inferred. Review the resulting
diff and confirm the task stack has no unresolved conflicts.

## Compose meaningful changes

Jj snapshots edits automatically; there is no staging area to populate.
Keep one purpose per change, with all resources needed for that purpose.
Split unrelated work with `jj split -m '<description>' <paths...>`; use
`jj split -i` when independent changes share files. Do not manufacture extra
commits for work already upstream. Separate genuinely independent work, while
keeping required dependencies in a sensible stack.

Agent-written descriptions use the existing repository convention:
`vibe(<scope>): <specific outcome>`, for example
`vibe(llm): serve FlashNext at native 262k context`. Use `jj describe` to set
the title and, when useful, a body explaining the behavior, reason, and
validation. Avoid titles such as "updates", "fix stuff", or retry numbers.
Preserve descriptions on existing user-authored changes unless asked to edit
them. Update the task description as its final implementation changes.

Validate before publishing. For Kubernetes/Flux changes, use flux-local with
the test options and pinned image in `.github/workflows/flux-local.yaml`, plus
targeted rendering or application checks as appropriate. Report unavailable
checks honestly. Do not publish conflicts, empty descriptions, secrets, or
unrelated user changes.

## Push and verify

Push only the intended bookmark: `jj git push --remote origin --bookmark
<bookmark>`. Move that bookmark to the completed task revision first using
`jj bookmark set <bookmark> -r <change-id>`. Use `main` when direct publication
to main is authorized; do not invent a PR requirement. A skill does not grant
permission to deploy unrelated workloads or change GitHub rules.

For an authorized Flux deployment, inspect the live GitRepository and owning
Kustomization to confirm the source branch and resource names. Typical commands
for this repo are:

```sh
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization <owning-kustomization> -n <namespace> --with-source
flux get sources git -n flux-system
flux get kustomizations -A
```

Confirm that the source fetched the pushed commit and that the owning
Kustomization applied that revision. Check affected HelmReleases, Pods, and
application behavior when relevant. A successful push, a successful reconcile
request, or Ready at an older revision does not establish deployment success.
Documentation-only changes do not require a cluster reconcile.

## Repair the same change

Keep the task change ID and bookmark while iterating. A failed push or failed
reconciliation is part of the same task: diagnose the actual failure, amend
the existing task change, validate again, and repush. Do not create a chain of
"fix deployment" commits for successive attempts at the same outcome.

If still editing the task change, edit its files and update `jj describe`.
If an empty working change was created afterward, resume the task with
`jj edit <task-change-id>`, or put the repair in that working change and run
`jj squash --into <task-change-id>`. Preserve unrelated edits before doing
either. When the just-published task on main is immutable, use
`jj --ignore-immutable edit <task-change-id>` only after confirming it is the
task's own current remote tip, with no intervening work. Never rewrite older
shared history to absorb a repair.

Rewriting keeps the jj change ID but replaces its Git commit SHA. Move the
bookmark to the repaired revision and run the same `jj git push` command.
Jj performs the equivalent of a force push with a lease automatically; it has
no `--force` flag. Inspect `--dry-run` when the proposed update is unclear.

If the remote moved, fetch and inspect the new commits before retrying.
Preserve others' work and rebase or merge the task appropriately; never fetch
and blindly overwrite the new remote tip. If others have built on a published
attempt, preserve their history with a focused follow-up repair rather than
rewriting beneath them. For auth, network, or server failures, retry the
transport without changing good content. For Flux failures, inspect status,
events, and relevant logs, then fix the demonstrated cause and reconcile again.

Continue while each attempt makes evidence-based progress. Stop and ask when
resolution needs an unresolved product choice, unavailable access, or actions
outside the authorized scope. If the same failure persists after three repair
attempts without new evidence, report the blocker and ask for the missing
decision or access rather than pushing speculative changes indefinitely.

After verification, leave an empty working change with `jj new` if appropriate.
Report the published bookmark/revision, validation, and any remaining blocker.
