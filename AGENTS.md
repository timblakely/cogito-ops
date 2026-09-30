# Repository agent instructions

Use Jujutsu (`jj`) for all version-control operations in this repository. Do not
invoke Git directly for status, diffs, commits, branches, merges, or pushes.
`jj git fetch` and `jj git push` are the intended GitHub transport commands.

Before changing or publishing repository content, read and follow
[the jj workflow](.claude/skills/jj-workflow/SKILL.md). These instructions apply
to every agent, including delegated agents.

- Sync before decomposing overlapping work; preserve unrelated user changes.
- Make coherent changes with descriptive `vibe(<scope>): <outcome>` titles.
- Repair a failed deployment in the existing task change and repush it through
  jj, rather than accumulating separate retry commits.
- Push and reconcile when authorized by the task. Do not create a PR unless
  requested. Check the deployed revision and health before reporting success.
