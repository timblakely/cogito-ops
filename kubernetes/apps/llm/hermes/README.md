# Hermes

The Hermes gateway and dashboard run in one supervised container and share the
VolSync/Kopia-backed `hermes` PVC mounted at `/opt/data`.  The dashboard is
available at `https://hermes.${DOMAIN_NAME}` through the internal Envoy gateway.

Before Flux can start the pod, create a `hermes` item in 1Password.  Its fields
is synced to the `hermes` Kubernetes secret. Add model-provider credentials and
optional integrations (for example, `OPENAI_API_KEY`, `FIRECRAWL_API_URL`, and
messaging tokens) to it as they are enabled.

The dashboard authenticates through PocketID using Hermes' native OIDC + PKCE
provider. Access is limited to the `hermes` PocketID user group, which currently
contains `tim`. The former `HERMES_DASHBOARD_BASIC_AUTH_*` fields are explicitly
masked so they cannot enable a second login method if they remain in 1Password.

The gateway connects to the private Matrix homeserver as
`@hermes:matrix.${DOMAIN_NAME}`. Its password is stored as `MATRIX_PASSWORD` in
the existing `hermes` item in the 1Password `Kubernetes` vault and synced into
the `hermes-matrix` Secret. Matrix E2EE is required and uses the stable
`HERMES_BOT` device ID, with crypto state retained on the backed-up Hermes PVC.
On first connection, Hermes writes its cross-signing recovery key once to
`/opt/data/matrix-recovery-key` with mode `0600`; this file is also backed up.
Only `@tim:matrix.${DOMAIN_NAME}` may invoke the bot. Hermes automatically accepts
room invitations; set `MATRIX_ALLOWED_ROOMS` after choosing permanent rooms if
access should be narrower than the user allowlist.

Hermes' provider is reconciled automatically before every pod start. The init
container preserves user-owned settings on the backed-up PVC while replacing
the retired `llm-switch` provider with two named LiteLLM transports. Direct
sessions use the `coordinator` alias over the Responses API by default; `/model
qwen` and `/model muse` select the local Qwen and Muse models over chat
completions. The key comes from `litellm-key-hermes` and is limited to exactly
those three model aliases, so Hermes cannot invoke planning or metered
escape-hatch models.

The provider catalogue is deliberately static. This keeps a newly restored PVC
and an old mutable one on the same v4 contract and prevents unrelated LiteLLM
catalogue additions from becoming reachable through the direct-session key.
