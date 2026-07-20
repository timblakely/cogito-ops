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

On every pod start, Hermes synchronizes the active model catalog from the
in-cluster `llm-proxy`. This installs the `custom:llm-proxy` provider using the
public `https://llm-switch.${DOMAIN_NAME}/v1` base URL and keeps its context
limits aligned with the active vLLM model. Select `custom:llm-proxy` in Hermes
once to make it the active model provider; subsequent starts update that
selection when the LLM switch changes models.
