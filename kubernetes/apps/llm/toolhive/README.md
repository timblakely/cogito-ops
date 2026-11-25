# toolhive

Toy [ToolHive](https://github.com/stacklok/toolhive) deployment for trying
out managed MCP servers before wiring anything into LiteLLM/Hermes.

- `app/` — Stacklok operator v0.58.0 via the two official OCI
  charts (`toolhive-operator-crds` then `toolhive-operator`), RBAC scoped to
  this namespace only (`storageVersionMigrator` must stay `false` for
  namespace scope).
- `unifi-mcp/` — `MCPServer` CR (its own Kustomization, dependsOn `toolhive`)
  running `enuno/unifi-mcp-server` (third-party,
  Apache-2.0; Ubiquiti publishes no official MCP server) as a **stdio**
  backend that the ToolHive proxy exposes as Streamable HTTP. Local UniFi OS
  console API at `192.168.1.1` with a locally generated Network API key,
  `UNIFI_READ_ONLY=true` so no mutating tool is ever registered.
- `vmcp/` — `MCPGroup` + `VirtualMCPServer` with ToolHive's **MCP optimizer**
  enabled, so an agent searches for the tool it needs instead of receiving every
  backend tool schema in its context (see "Tool search" below).

Credentials: the single secret is the UniFi Network API key, stored in the
1Password `unifi-mcp` item (vault `kubernetes`, field `UNIFI_API_KEY`) and
synced by ExternalSecret into Secret `unifi-mcp`. (The `unifi` item's own
`UNIFI_API_KEY` field is an unrelated older key and must stay unwired.
Running the backend over stdio removes the server's own bearer-token
requirement; this cluster's external-secrets v0.20.4 removed `backfill`, so
a cluster-generated token would rotate on every refresh — stdio avoids that
whole problem.)

## Access (cluster-internal only)

`http://mcp-unifi-mcp-proxy.llm.svc.cluster.local:8080/mcp`

No auth anywhere: no OIDC on the ToolHive proxy and no token on the stdio
backend — anything in the cluster that can reach the Service can call the
(read-only) UniFi tools. Do not expose it via envoy until an
`MCPOIDCConfig`/`oidcConfigRef` exists. Manual test:

```sh
kubectl -n llm port-forward svc/mcp-unifi-mcp-proxy 8080:8080
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Tool search (the optimizer)

`http://vmcp-agents.llm.svc.cluster.local:4483/mcp` — a `VirtualMCPServer` in
front of the `agents` `MCPGroup` (the operator names the Service `vmcp-<name>` on
its own default port 4483). With the optimizer enabled the gateway advertises
exactly two meta-tools:

- `find_tool` — hybrid keyword + semantic search over the group's tools;
- `call_tool` — invoke a tool that `find_tool` returned.

The full tool manifests stay on the gateway, which is the point: a client that
would otherwise carry every backend schema pays for a shortlist
(`maxToolsToReturn: 8`) per search instead. Adding another server to the group
therefore costs nothing in agent context, and
`aggregation.conflictResolution: prefix` keeps same-named tools from different
backends distinct (`unifi-mcp_…`).

Embeddings come from the cluster's shared embedder rather than a dedicated model:
`embeddingProvider: openai` against `http://litellm.llm.svc.cluster.local:4000/v1`
with model `embedder` (the always-on bge-m3 lane that Open WebUI's RAG also
uses). `embeddingServerRef` is the alternative and deliberately not used — it
would stand up a second HuggingFace TEI model server for the same job. The
credential is `LiteLLMVirtualKey` `toolhive-optimizer`
(`kubernetes/apps/llm/litellm/app/virtualkeys/`, scoped to `embedder`), injected
as `OPENAI_API_KEY` on the `vmcp` container because that is the only channel the
optimizer reads it from; `embeddingHeaders` cannot carry secrets by design.

Three things to know before debugging:

- Enabling the optimizer pins this instance to MCP protocol `2025-11-25`; the
  meta-tools are session-scoped, so newer-capable clients are negotiated down
  (upstream stacklok/toolhive#6089).
- An `incomingAuth.authzConfig` Cedar policy cannot be configured here: vMCP
  exits at startup because "Config.Authz and Config.OptimizerConfig are mutually
  exclusive" (the meta-tools are not in its admission layer). Access to this
  gateway is therefore all-or-nothing, and today it is "all" to anyone in the
  cluster.
- `toolhive-unifi-mcp` must be Ready before the gateway indexes anything: with an
  empty group `find_tool` answers "no results" rather than an error.

`flux-ops` is intentionally **not** in this group: it sits behind its own OIDC
and Cedar policy, so fronting it here would need a second credential chain
(gateway→backend token, audience `cogito-flux-mcp`) plus a policy change to admit
the gateway identity. Its client keeps the existing direct, authenticated path.

Manual test (cluster-internal):

```sh
kubectl -n llm port-forward svc/vmcp-agents 4483:4483
curl -s -X POST http://localhost:4483/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# expect only find_tool and call_tool, then
# {"name":"find_tool","arguments":{"tool_description":"list wifi clients","tool_keywords":"clients,wifi"}}
# (the arguments are tool_description and tool_keywords; a bare "query" is rejected)
```

Known loosening for toy phase: `UNIFI_LOCAL_VERIFY_SSL=false` (self-signed
console cert) — see upgrade note in `unifi-mcp/mcpserver.yaml`.
