# Hermes

The Hermes gateway and dashboard run in one supervised container and share the
VolSync/Kopia-backed `hermes` PVC mounted at `/opt/data`.  The dashboard is
available at `https://hermes.${DOMAIN_NAME}` through the internal Envoy gateway.

Before Flux can start the pod, create a `hermes` item in 1Password.  Its fields
are synced to the `hermes` Kubernetes secret and must include:

- `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`
- `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`
- `HERMES_DASHBOARD_BASIC_AUTH_SECRET` (a stable, high-entropy random value)

Add model-provider credentials and optional integrations (for example,
`OPENAI_API_KEY`, `FIRECRAWL_API_URL`, and messaging tokens) to the same item as
they are enabled.  The dashboard uses its own authentication gate; it is not
safe to expose its route publicly without replacing the basic-auth setup with
an OIDC provider.
