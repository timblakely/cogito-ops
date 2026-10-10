---
name: pocket-id-oidc-login-debug
description: Use when Pocket ID OIDC login fails with wrong-password.
version: 1.0.0
author: tim
license: MIT
metadata:
  hermes:
    tags: [kubernetes, oidc, pocket-id, homelab, flux]
    related_skills: [gpu-llm-serving]
---

# Debugging Pocket ID OIDC "user or password is wrong" in cogito

## When to Use
An app fronted by Pocket ID OIDC (Open WebUI, litellm, immich, ...) shows
"the user or password is wrong" / "email or password is incorrect" at login,
or an OIDC callback 401s, in the cogito cluster.

Apps (Open WebUI, litellm, immich, ...) authenticate via Pocket ID
(pid.<domain>) using operator-managed Secrets `<app>-oidc-credentials`
(created by PocketIDOIDCClient CRs, pocket-id-operator v0.5.0).

## Key insight
The app's generic "email or password is incorrect" login flash usually means
NOT the user's credentials — it means the **app's** client credentials failed
at Pocket ID's token endpoint. Pocket ID itself may have signed the user in
fine; the code->token exchange 401s and the app renders a bogus message.

## Diagnosis order (fast, all read-only)
1. App pod logs: `kubectl -n <ns> logs deploy/<app> | grep -iE 'oauth|invalid client secret'`
   - `OAuth callback failed: Invalid client secret` = client secret mismatch.
2. Reproduce directly: read `client_id`/`client_secret` from
   `<app>-oidc-credentials` Secret and probe
   `curl -u "$CID:$SECRET" -d grant_type=client_credentials https://pid.<domain>/api/oidc/token`
   - 401 `Invalid client secret` confirms the server rejects it; then the app
     side is innocent.
3. Compare pod env vs Secret (hash, don't print values):
   `kubectl exec deploy/<app> -- printenv OAUTH_CLIENT_SECRET | sha256sum` vs the
   Secret's decoded value. Equal => drift is inside Pocket ID.
4. Pocket ID's own DB (CNPG cluster `pocket-id-db` in home-infra, db name is
   `app`, NOT `pocket-id`):
   `kubectl -n home-infra exec pocket-id-db-2 -c postgres -- psql -U postgres -d app -Atc "select id,name,is_public,left(secret,7),length(secret) from oidc_clients"`
   - Confidential clients (`is_public=f`) must show a `$2a$10$` bcrypt hash.
     An EMPTY secret on a confidential client = broken; no secret can ever verify.
   - Column names are `id` (the client_id), `name`, `secret`; no `updated_at`.
   - `oidc_clients.secret=''` with `is_public=f` is the signature. hermes/
     opencloud-* are legitimately empty (public + PKCE).

## Root cause pattern
The CR reports Ready/"OIDC client is in sync" even when Pocket ID stores no
secret — operator/server state can diverge (seen after a client
re-registration; Secret written the same second the client row was created,
Jul 2026, with a `chore(pocket-id): potentially fix name collision` commit
nearby). The K8s Secret then holds a value Pocket ID never stored.

## Fix (re-register; requires user authorization)
1. Snapshot: CR yaml + hash of current secret to the scratch dir.
2. `kubectl -n <ns> delete pocketidoidcclient <app>` — operator deletes it in
   Pocket ID (watch operator logs: "Deleting from PocketID"/"Successfully
   deleted"; verify the row is gone in oidc_clients).
3. `kubectl -n <ns> annotate kustomization <app> reconcile.fluxcd.io/requestedAt=$(date +%s) --overwrite`
   — Flux recreates the CR, operator registers a fresh client WITH a bcrypt
   secret and rewrites `<app>-oidc-credentials` (new client_id).
4. Probe the token endpoint again (step 2) — expect HTTP 200 with an
   access_token.
5. Roll the pod: Reloader will NOT fire — proven by A/B probe (2026-10-07):
   in-place Secret UPDATE rolls the annotated Deployment; Secret DELETE+RECREATE
   is silently ignored (recreate test: no log line, pod unchanged). The
   operator recreates `<app>-oidc-credentials` on re-registration, which is the
   ignored pattern. Reloader runs `--auto-reload-all=true` with default
   reloadOnCreate=false; upstream docs/issues #299 #810 #1089 confirm creates
   are skipped by design (enabling reloadOnCreate risks mass restart storms
   on every reloader restart). Just `kubectl -n <ns> rollout restart
   deploy/<app>` and verify pod env `OAUTH_CLIENT_ID` equals the new
   `status.clientID`.
6. Nothing in the repo hardcodes client IDs (verified 2026-10) — grep first
   anyway: `rg <old-client-id>`. Custom claims (`open_webui_role` etc.) live on
   PocketIDUserGroups (`custom_claims.user_group_id`), not the client, so they
   survive re-registration; user groups stay in sync.

## Aftermath
User re-authorizes the app once on first login (old
`user_authorized_oidc_clients` row is for the dead client id). Final proof is
interactive — ask the user to log in.

## Unrelated noise seen
pocket-id-operator livelogs `User is referenced by PocketIDUserGroup,
blocking deletion` every 5s for PocketIDUser `tim` (deletionTimestamp set
2026-01-27, finalizer-blocked). Harmless to logins; clean up separately.

## Reloader facts (cluster-infra, v1.4.12, verified 2026-10-07)
- Healthy: informer alive; reacts instantly to Secret/ConfigMap UPDATEs
  (probe deploy + 490 real rolls). Ignore `--namespaces-to-ignore` for others.
- Blind spot: Secret/CM CREATE (incl. delete+recreate) is ignored by default
  (`reloadOnCreate=false`). Any flow that GCs and recreates a consumer Secret
  bypasses Reloader: Pocket ID OIDC re-registration, and LiteLLM key-alias
  reclaim (key Secrets are ownerRef'd to LiteLLMVirtualKey — CR recreate GCs
  the Secret). The `reloader.stakater.com/auto` comments in llm helmreleases
  over-promise for those paths.
- ntfy restart storm (FIXED 2026-10-08, commit 06e1feed): ExternalSecret
  `ntfy-credentials` (observability, was refreshInterval 1h) templates
  `auth_users` with `htpasswd` = bcrypt, random salt -> content differs EVERY
  sync -> Reloader rolled the ntfy pod hourly, forever (490/523 log lines).
  refreshInterval is now 24h. The deploy itself triggers one final sync+roll;
  expect exactly one restart when it lands, then quiet. Force a sync anytime:
  `kubectl -n observability annotate externalsecret ntfy-credentials
  force-sync=$(date +%s) --overwrite` (annotation on the ExternalSecret works
  for any ES in the cluster).
