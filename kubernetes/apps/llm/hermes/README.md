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

On a new PVC, Hermes bootstraps a `custom:llm-proxy` provider from the
in-cluster `llm-proxy`, using the public
`https://llm-switch.${DOMAIN_NAME}/v1` base URL and the proxy's current active
model as the initial default. The bootstrap is non-destructive: later Dashboard
and CLI model/provider changes remain Hermes-owned.

The provider uses live model discovery, so `/model` and `hermes model --refresh`
query the proxy's `/v1/models` catalog rather than copying a static model list
into `config.yaml`. If a locally selected default is later removed from the
proxy, Hermes receives `model_not_found` until a user selects an available
model; the next pod start does not overwrite that choice.

The catalog can also contain GitOps-managed virtual model overlays. For example,
`gemma4-agentic` selects the Gemma 4 QAT base model while providing default
chat-template kwargs for thinking and preserved tool-turn reasoning. Clients
can override those defaults in an individual request; the base model remains
available as a separate catalog entry.
