# In-cluster Hermes ops loop for cogito

Goal: the cluster Hermes agent edits, validates, deploys, and verifies cogito
from inside the cluster, with the workstation as an explicit fallback ladder.
Today all of that runs from the workstation.

## Verified current state (2026-10-09)

- Pod: `nousresearch/hermes-agent:v2026.9.24`, Debian 13, uid 0 (gid 1000),
  PVC `/opt/data` (2.0G, ~650M used, Kopia-snapshotted).
- Present in pod: git 2.47, python3 + pyyaml + uv. Missing: jj, gh, kubectl,
  kustomize, flux, helm. `HERMES_DISABLE_LAZY_INSTALLS=1` → runtime installs
  do not persist across pod rolls.
- Egress: api.github.com, ghcr.io, pypi all reachable.
- `automountServiceAccountToken: false`, default SA, no RBAC → zero cluster
  API access from inside the pod.
- `secret/hermes` is ExternalSecret-managed (1Password) and already delivers
  LITELLM_API_KEY + MATRIX_* to the pod.
- `age.key`, `kubeconfig`, `talosconfig`, `creds/` are git-ignored →
  the in-cluster agent cannot decrypt secrets and never holds admin
  kubeconfig. Blast radius is capped by construction; keep it that way.
- Repo: private `timblakely/cogito-ops`, no branch protection, .git ~38M,
  jj-only (`vibe(<scope>): <outcome>`), flux-local CI on PRs only.

## Target loop

edit /work/cogito (jj) → gates → `jj git push` →
`flux reconcile kustomization hermes -n llm --with-source` →
verify (init log `configure: bundle ... synced`, bundle-sha annotation,
rollout status, `hermes chat -q` smoke) → Matrix report.

## Build items

1. **Push credential.** Fine-grained PAT, cogito-ops only, contents:rw.
   New 1Password item → extend the existing ExternalSecret → git-credential-store
   file on the PVC + `git config credential.helper store`. jj uses git's
   transport, so `jj git push` works. Rotate via 1Password, no image change.
2. **Toolchain: derived image.** New `hermes-runner-image.yaml` workflow in
   `.github/workflows/` (pattern already exists four times): FROM
   nousresearch/hermes-agent, mise-install pinned jj, gh, kubectl, kustomize,
   flux, helm. Bake it — lazy installs are disabled, boot-time installs make
   every restart a network gamble.
3. **Working tree: separate ~5G PVC at `/work`, NO Kopia policy** (the remote
   is the backup; keep the big snapshots out of the 2G home). configure.py
   init: `jj git clone --colocate` on fresh PVC + safe.directory.
4. **RBAC.** Dedicated `hermes-ops` SA (+ mount the token, replacing
   automountServiceAccountToken:false only for that SA). Decision pending:
   - *namespaced admin* (recommended): full `apply --dry-run=server` + write
     on all namespaces; cluster-scoped objects (ClusterRole, StorageClass…)
     stay workstation/PR-only.
   - *read-only (view)*: no server-dry-run; validator + kustomize build +
     CI flux-local are the gates.
   - *cluster-admin*: matches workstation power; largest blast radius.
5. **Self-deploy protocol** (the agent lives inside what it deploys):
   - Self-relevant change = touches `kubernetes/apps/llm/hermes/**` (image
     tag, bundle-sha annotation, provider-bootstrap, GitOps-reconciled config
     keys) → these can roll the agent's own pod.
   - Push first, write `pending-deploy.json` marker on the PVC, then trigger
     the reconcile. Being killed mid-tool-call is safe: the change is already
     durable in git; worst case is a truncated session, never a lost change.
   - Post-roll watchdog (startup cron): marker + clean init log + smoke test
     → Matrix "deployed clean". Marker older than ~15 min → Matrix alert
     embedding the exact `jj revert-change` + repush commands. The pod cannot
     self-heal from its own brick; the watchdog converts a silent brick into
     an instant, specific alert for the fallback ladder.
   - Standing prohibitions (skill-enforced): never suspend/force-sync other
     apps' KS/HRs; never touch GPU/session priorities — Amnesia gaming
     preemption rules stay inviolate.
6. **Fallback ladder (workstation remains root of trust).**
   - Pod crashloop after self-deploy: `jj undo`/`jj revert-change` in the
     workstation clone → `jj git push` → reconcile. No access to the dead pod
     needed; branch protection is off so a straight revert push works.
   - Bad mutable state on PVC (pod runs, behaves wrong): delete path on PVC
     via kubectl, restart, bundle re-seeds one-time semantics.
   - Whole-cluster: volsync replica + Kopia snapshots as-is.
   - **Ownership protocol**: one owner at a time. When the workstation takes
     over, the cluster agent must not push (fetch-only). Encode as a marker
     file / skill rule, not discipline alone.
7. **Parity glue.**
   - Extend bundle skill `cogito-hermes-cluster-parity` with the ops loop +
     prohibitions (bundle edits roll the pod once, via the normal protocol).
   - `scripts/agent-prepush.sh` in cogito: catalogue validator self-test,
     kustomize builds, server-dry-run of touched objects — same contract CI
     (flux-local) enforces, so agent checks and PR checks agree.
   - Note: agent-authored skills on the PVC survive every deploy (one-time
     seeding), so the agent iterates its own skills without pod rolls;
     promotion into the GitOps bundle is the deliberate step.

## Optional fast-follow

Flux Notification Receiver + GitHub webhook → push-to-reconcile in seconds
instead of the 1h KS interval. Out of scope for v1 if manual
`flux reconcile` feels fine.

## Open decisions

- [ ] RBAC tier (namespaced admin recommended)
- [ ] Build now vs. skeleton vs. doc-only (this doc = doc-only baseline)
- [ ] Webhook receiver now or later
- [ ] PAT creation + 1Password item (needs your hand at the GitHub UI)
