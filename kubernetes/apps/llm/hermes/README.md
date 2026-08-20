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

Hermes no longer bootstraps its provider automatically. The
`bootstrap-llm-proxy` initContainer was removed with the M7 decommission,
because it seeded the provider by querying the retired `llm-proxy` and would
block startup now that Service is gone.

The existing PVC already carries a bootstrapped `config.yaml`, so running
Hermes is unaffected. On a **new** PVC the provider must be configured by
hand: point it at `https://litellm.${DOMAIN_NAME}/v1` (now served by
LiteLLM rather than llm-proxy) with a LiteLLM virtual key as the credential.
Model names are unchanged - LiteLLM advertises the same Hugging Face-style
identifiers the old proxy did.

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
