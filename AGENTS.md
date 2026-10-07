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

# 1Password authentication for every agent session

All automated 1Password operations MUST use the existing service account.
Use `~/.local/bin/op-headless` instead of invoking `op` directly. This helper
loads `OP_SERVICE_ACCOUNT_TOKEN` from the workstation Secret Service keyring
using `service=1password-service-account` and `account=codex`. Omit the keyring
`host` attribute: its stored value may predate a hostname change.

Do not assume a login shell or the Codex shell snapshot sources `.bashrc` or
inherits the token. If the helper is absent, load the token explicitly into
the child process environment using `secret-tool lookup service
1password-service-account account codex`, then run `/usr/bin/op` with
`OP_SERVICE_ACCOUNT_TOKEN` set and `OP_BIOMETRIC_UNLOCK_ENABLED=false`.
Never print the token, put it in command arguments, store it in a repository,
or turn on shell tracing while handling credentials.

NEVER fall back to desktop, biometric, personal-account, or interactive
1Password authentication for automation. If the service account is missing or
lacks access, stop the credential-dependent operation and report the exact
missing access. Do not retry with plain `op`, `op-me`, or `op signin`, and do
not create repeated approval prompts. Personal-account authentication is
allowed only when the user explicitly requests it for that operation.

Chezmoi secret templates must use the same headless helper (or inline its
source before the helper exists on a fresh restore). The LiteLLM API key must
be fetched from `op://kubernetes/litellm/LITELLM_HERMES_API_KEY` on apply and
must never be stored in the chezmoi repository, even encrypted.
