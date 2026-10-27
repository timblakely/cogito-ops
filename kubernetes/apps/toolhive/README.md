# toolhive

Toy [ToolHive](https://github.com/stacklok/toolhive) deployment for trying
out managed MCP servers before wiring anything into LiteLLM/Hermes.

- `toolhive-operator/` — Stacklok operator v0.58.0 via the two official OCI
  charts (`toolhive-operator-crds` then `toolhive-operator`), RBAC scoped to
  this namespace only (`storageVersionMigrator` must stay `false` for
  namespace scope).
- `unifi-mcp/` — `MCPServer` CR running `enuno/unifi-mcp-server` (third-party,
  Apache-2.0; Ubiquiti publishes no official MCP server) as a **stdio**
  backend that the ToolHive proxy exposes as Streamable HTTP. Local UniFi OS
  console API at `192.168.1.1` with a locally generated Network API key,
  `UNIFI_READ_ONLY=true` so no mutating tool is ever registered.

Credentials: the single secret is the UniFi Network API key, stored in the
1Password `unifi` item (vault `kubernetes`, field `UNIFI_API_KEY`) and synced
by ExternalSecret into Secret `unifi-mcp`. (Running the backend over stdio
removes the server's own bearer-token requirement; this cluster's
external-secrets v0.20.4 removed `backfill`, so a cluster-generated token
would rotate on every refresh — stdio avoids that whole problem.)

## Access (cluster-internal only)

`http://mcp-unifi-mcp-proxy.toolhive.svc.cluster.local:8080/mcp`

No auth anywhere: no OIDC on the ToolHive proxy and no token on the stdio
backend — anything in the cluster that can reach the Service can call the
(read-only) UniFi tools. Do not expose it via envoy until an
`MCPOIDCConfig`/`oidcConfigRef` exists. Manual test:

```sh
kubectl -n toolhive port-forward svc/mcp-unifi-mcp-proxy 8080:8080
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Known loosening for toy phase: `UNIFI_LOCAL_VERIFY_SSL=false` (self-signed
console cert) — see upgrade note in `unifi-mcp/app/mcpserver.yaml`.
