---
name: jj-managed-dotfiles-push
description: "Push in jj-managed repos after git commit detaches HEAD."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [dotfiles, jj, git, chezmoi]
    related_skills: []
---

# Pushing to jj-managed repos (e.g. ~/git/blakely-dotfiles)

## When to Use

Any push/commit in a repo containing a `.jj/` directory (jj's colocated git layout) — most reliably the blakely-dotfiles chezmoi repo — especially after a plain `git commit` there.

These repos have a `.jj/` directory even though `.git/` also exists. Git porcelain still works but interacts badly:

- A plain `git commit` leaves the repo on a **detached HEAD** (jj keeps HEAD detached by design); a follow-up `git push origin HEAD` fails with "not a full refname".
- The commit itself is fine — jj absorbs it into the change graph on the next jj command.

## Correct flow after a plain git commit (or for any change)

```bash
cd <repo>
jj status                      # jj absorbed the commit; note its change id
jj bookmark set master -r <change_id>
jj git push --dry-run          # should show only the intended bookmark move
jj git push
git ls-remote origin master    # verify remote sha
```

## Notes

- `jj log` shows `master*` = bookmark differs from remote.
- Uncommitted `@` working-copy changes stay detached and are NOT pushed by the bookmark move — safe to push with a dirty tree.
- `chezmoi add --force ~/.file` updates the source file; empty `chezmoi diff` = target/source converged.
