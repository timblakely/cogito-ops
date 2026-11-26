# toolhive

[ToolHive](https://github.com/stacklok/toolhive) deployment for trying managed
MCP servers before wiring anything into LiteLLM/Hermes. It has grown one real
consumer: the agent host in `../opencode`, which reaches tools through the
search gateway below instead of carrying every backend schema.

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
- `paseo/` — `MCPServerEntry` + `MCPExternalAuthConfig`: the agent host's own
  agent-control MCP endpoint, registered as a group member with no new pods and
  no new credential. Details below.
- `vmcp/` — `MCPGroup` + `VirtualMCPServer` with ToolHive's **MCP optimizer**
  enabled, so an agent searches for the tool it needs instead of receiving every
  backend tool schema in its context (see "Tool search" below).

`flux-ops` is intentionally **not** in this group: it sits behind its own OIDC
and Cedar policy, so fronting it here would need a second credential chain
(gateway→backend token, audience `cogito-flux-mcp`) plus a policy change to admit
the gateway identity. Its client keeps the existing direct, authenticated path.

Credentials: two, both already existing elsewhere.

- UniFi: the Network API key, in the 1Password `unifi-mcp` item (vault
  `kubernetes`, field `UNIFI_API_KEY`) synced by ExternalSecret into Secret
  `unifi-mcp`. (The `unifi` item's own `UNIFI_API_KEY` field is an unrelated
  older key and must stay unwired. Running the backend over stdio removes the
  server's own bearer-token requirement; this cluster's external-secrets
  v0.20.4 removed `backfill`, so a cluster-generated token would rotate on every
  refresh — stdio avoids that whole problem.)
- Paseo: Secret `paseo-server`, key `server-password` — **the same key the
  `paseo` container already reads** (`../opencode/app/helmrelease.yaml`).
  Nothing here creates a Secret, adds an ExternalSecret, or pushes a new field
  to 1Password. The gateway's own ServiceAccount Role (created by the operator
  for the `agents` vMCP) already grants `get`/`list`/`watch` on secrets in this
  namespace, so no RBAC is added for the hop either — though note that the
  gateway cannot use a bearer token at all today (see "The Paseo member"), so
  the credential is currently consumed by nothing.

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

## The Paseo member

`paseo/mcpserverentry.yaml` registers `POST /mcp/agents` on the agent host's
Paseo daemon. An `MCPServerEntry` is a registration, not a workload: the gateway
dials the URL directly, so this adds no Deployment, no Service, and no proxy hop.
Its 42 tools are the agent-control plane of this pod — launch and message
agents, create workspaces, read terminals, manage schedules.

> **Status as deployed (measured 2026-11-26, revision `ee60f8b9`): the entry is
> live but the gateway refuses it, so Paseo contributes nothing yet.** The
> aggregator converts each discovered backend's auth config and this build has no
> bearer-token strategy; the entry is skipped and its tool filter is inert.
>
> ```
> ERROR failed to discover auth config for MCPServerEntry entry=paseo
>       error="failed to get converter for auth type bearerToken: unsupported auth type: bearerToken"
> WARN  skipping server entry due to conversion failure entry=paseo
> WARN  aggregation.tools entry matches no backend in the group; its filter/overrides are not applied workload=paseo
> ```
>
> `VirtualMCPServer agents` still reports `Ready` with `backendCount: 1`
> (`unifi-mcp` only) and the gateway still advertises exactly `find_tool` and
> `call_tool`, so no existing client changed behaviour; the cost of leaving this
> in is a `False` condition (`DiscoveredAuthConfig-paseo`) and two log lines per
> reconcile. Not a version skew: the aggregator reports `v0.58.0`, the same
> release as the CRDs, and its own config surface enumerates its outgoing
> strategies as `unauthenticated`, `header_injection`, `token_exchange`,
> `upstream_inject`, `aws_sts`, `obo`, `xaa` — there is no bearer type to point at.
> `MCPExternalAuthConfig type: bearerToken` is accepted by the API and honoured
> only by the operator's proxy runner (`MCPServer`/`MCPRemoteProxy`), never by the
> gateway's dial-out. The fix is one of: gateway-side `header_injection` (the
> daemon accepts only `Authorization: Bearer <password>` — a bare token, a
> lowercase scheme and no header all measure `401`), or an `MCPRemoteProxy`, whose
> runner does implement bearer. See `mcpexternalauthconfig.yaml` for why the
> bearer form is kept in the tree.

**The URL is not the Service DNS name, and that is the daemon's rule.** Paseo
applies a Vite-style Host allowlist (its `hostnames.js`): `localhost`,
`*.localhost`, any IP literal, and the names in `PASEO_HOSTNAMES`. Measured
2026-11-26 from two separate containers: `Host: paseo.timblakely.com` and
`Host: 127.0.0.1:6767` answer 200 with the 42-tool catalog;
`Host: opencode-paseo.llm.svc.cluster.local:6767` (and `.svc`, and the bare
service name, and the pod name) answer `403 {"error":"Invalid Host header"}`.
`headerForward` cannot repair this: Go's transport takes the Host from
`Request.Host` and ignores a `Host` entry in the request's Header map.

So the live `remoteUrl` is `https://paseo.timblakely.com/mcp/agents`, which the
allowlist admits. What that costs while it stands:

- The tool path leaves the pod, hairpins through the LAN VIP and the
  envoy-internal gateway (`../opencode/app/paseo-gateway.yaml`, no OIDC there
  because Paseo authenticates itself), and comes back. Cluster-internal traffic
  takes a public-ish route, so the "never leaves the namespace" intuition does
  not hold for this hop.
- The certificate is a real public-CA cert for `*.timblakely.com`, so no
  `caBundleRef` is needed today; if the gateway's trust store ever disagrees,
  mount a CA bundle rather than disabling verification.

**`remoteUrl` and `PASEO_HOSTNAMES` are one switch.** The in-cluster variant is
`http://opencode-paseo.llm.svc.cluster.local:6767/mcp/agents`, and it works only
once `PASEO_HOSTNAMES` (`../opencode/app/helmrelease.yaml`) lists that hostname —
the daemon matches a leading-dot pattern as a suffix, so `.cluster.local` covers
the whole namespace family. Half a flip is a permanent 403, and the symptom is
not an error page: the backend simply never becomes ready, so `find_tool` stops
returning Paseo tools. Both halves live in the same (deliberately unpushed,
because it restarts the agent host) change as the OpenCode gateway entry, and
that change also carries this pair's rollback line. Expect a brief 403 window
when it lands: `toolhive-paseo` and the opencode app are intentionally not
ordered, so the gateway may dial the new hostname seconds before the restarted
daemon accepts it, and `best_effort` absorbs that.

## Tool search (the optimizer)

`http://vmcp-agents.llm.svc.cluster.local:4483/mcp` — a `VirtualMCPServer` in
front of the `agents` `MCPGroup` (the operator names the Service `vmcp-<name>` on
its own default port 4483). With the optimizer enabled the gateway advertises
exactly two meta-tools:

- `find_tool` — hybrid keyword + semantic search over the group's tools;
- `call_tool` — invoke a tool that `find_tool` returned.

The full tool manifests stay on the gateway, which is the point: a client that
would otherwise carry every backend schema pays for a shortlist
(`maxToolsToReturn: 8`) per search instead. Measured with `cl100k_base` over the
`tools[]` array each backend returns from `tools/list`: Paseo's 42 tools are
**5,456 tokens** (the 38 this group advertises, 4,927), the UniFi 26 are
**4,757**, and the two meta-tools a client actually loads are **419**. A real
shortlist of UniFi hits measured 1,285 tokens. So a worker that searches twice
pays roughly a third of what carrying Paseo's catalog costs, and a worker that
searches nothing pays almost nothing.

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
  (upstream stacklok/toolhive#6089). Measured: offering `2026-07-28` to either
  this gateway or the Paseo daemon returns `2025-11-25`.
- An `incomingAuth.authzConfig` Cedar policy cannot be configured here: vMCP
  exits at startup because "Config.Authz and Config.OptimizerConfig are mutually
  exclusive" (the meta-tools are not in its admission layer). Access to this
  gateway is therefore all-or-nothing, and today it is "all" to anyone in the
  cluster.
- Every backend must be Ready before the gateway indexes it: with an empty group
  `find_tool` answers "no results" rather than an error.

### Tool filtering, and what it does not do

`vmcp/virtualmcpserver.yaml` lists 38 of Paseo's 42 tools and hides four:
`create_terminal`, `send_terminal_keys`, `kill_terminal`,
`respond_to_permission`. Those are the interactive surfaces of a session a human
owns — raw keystrokes into a shell, and approvals on another agent's pending
permissions — and none of them is a search-and-call task. `unifi-mcp` has no
entry and `defaultToolVisibility` stays at its `allow` default on purpose:
setting `deny` would silently hide UniFi's 26 tools too.

Two limits that are easy to forget:

- `filter` gates **advertising**. A hidden tool stays in the gateway's routing
  table, exactly as the CRD documents it, so this is presentation, not a control
  boundary. Not yet demonstrated on this gateway: while the Paseo backend is
  absent every `call_tool paseo_*` answers `{"isError":true,"text":"tool not
  found: paseo_create_terminal"}` regardless of the filter (measured), so the
  routability of the four hidden tools can only be probed once the backend
  registers.
- MCP has no per-caller tool policy. Anyone who can reach 4483 gets whatever the
  gateway advertises, and behind that the gateway holds credentials (the Paseo
  bearer token, the UniFi read-only key) that those callers do not have
  individually.

Two things this change measured about the mechanism itself, because both are easy
to get wrong:

- The filter lives at `spec.config.aggregation.tools` (**not** `spec.aggregation`,
  which is not a field of this CRD and would be pruned by the API server without
  a word). The live object after deploy holds exactly one entry,
  `{workload: paseo, filter: [...38]}`, `conflictResolution: prefix`,
  `prefixFormat: "{workload}_"`, and the 38 names are the daemon's 42-tool
  `tools/list` minus precisely `create_terminal`, `send_terminal_keys`,
  `kill_terminal`, `respond_to_permission` — no typos, nothing extra.
- The workload key is the backend's resource **name**, and an unmatched key is
  **not** silent: the aggregator logs
  `WARN aggregation.tools entry matches no backend in the group; its filter/overrides are not applied workload=paseo`.
  So a renamed backend shows up in the gateway log rather than quietly
  un-filtering a workload.

### Retrieval, measured

Numbers below come from the live optimizer with `embedder` behind LiteLLM, not
from a simulation. Shortlists come back shorter than the 8 slots allowed because
`find_tool` prunes weak hits (`semanticDistanceThreshold` defaults to 1.0).

UniFi's 26 tools alone (the state before this change, and still the state after
it, because the Paseo backend does not register — see "The Paseo member"): a
47-query harness against the gateway measured UniFi **recall@8 1.000** (3/3),
recall@1 0.333, mean shortlist 5.67 of 8 slots.

What Paseo's 38 advertised tools do to those numbers, and what Paseo recall looks
like, **cannot be measured until the backend registers**. One observation is
already available and worth knowing: with Paseo absent, agent-shaped queries do
not come back empty — `find_tool("create a git worktree workspace for a coding
task", [workspace, worktree, create])` returns four UniFi tools
(`list_site_internal_ap_neighbors_v2` first). A group member that is configured
but not reachable still costs a caller in misleading hits, which is the concrete
argument for fixing the auth gap rather than leaving the entry half-deployed.

To reproduce, from anywhere that can reach `vmcp-agents:4483`: initialize a
Streamable HTTP session, then call `find_tool` once per query and read the
shortlist out of `result.content[0].text` (it is a JSON document inside text
content, not `structuredContent`):

```sh
curl -s -X POST http://localhost:4483/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","name":"find_tool",
       "arguments":{"tool_description":"list the clients currently connected to the wifi network",
                    "tool_keywords":["wifi","clients","connected"]}}'
```

recall@8 is then just "was the tool the query describes inside the returned
`tools[]`", averaged over the queries. The 47-query harness used for the numbers
above is not vendored in this repo; it was assembled in a scratch directory for
this measurement (40 queries for the tools this filter advertises, 4 for the
hidden ones — where a hit would be a bug — and 3 UniFi controls to prove the new
filter did not swallow the group).

## Exposure, and why the narrowing steps are load-bearing

**The `agents` gateway is unauthenticated inside the cluster and it now fronts
this pod's agent control plane.** That posture was chosen deliberately, not
inherited by accident, and it is worth stating plainly: any pod in this cluster
that can reach `vmcp-agents:4483` can launch agents, create workspaces and read
terminals on this host, without a credential of its own.

The steps below are not nice-to-have hygiene, because the usual mitigations do
not apply here:

- **MCP has no per-caller tool policy**, so the gateway cannot answer "which
  tools may *this* caller use". There is no caller identity to ask about.
- **ToolHive's `filter` only gates advertising.** Hidden tools stay in the
  routing table, so the four excluded tools are excluded from the menu, not from
  the reach of anyone who guesses the name.
- **`PASEO_PASSWORD` is already in every agent terminal environment in this
  pod.** It is set on the `paseo` container (`helmrelease.yaml:182`) and Paseo
  injects it into the terminals it hands agents; pid 1 of the `main` container
  has no such variable, so it arrives through the agent path, not through the
  container's own environment. Measured: a shell in this pod can call
  `/mcp/agents` with that bearer token and get the full 42-tool catalog today,
  with no gateway and no filter involved.
- **The gateway is anonymous**, so it cannot tell a request from that agent from
  a request from anything else in the namespace.

In other words: this pod is **one trust domain**. Everything running in it can
already do everything the gateway can do, and the gateway adds no capability
that a determined in-pod process lacks. What the gateway does is expose that
capability to a wider audience — the rest of the namespace, then the rest of the
cluster. Narrowing it is therefore about who *outside* this pod can reach it:

1. **First: a NetworkPolicy limiting 4483 to the opencode pods.** This is the
   step that actually matters, because it converts "any pod in the cluster" into
   "the agent host", which is the only consumer and already the trust domain
   that holds the credential. The `flux-ops` pair in this directory is the
   working pattern: a backend policy admitting only the proxy, and a proxy
   policy admitting only `app.kubernetes.io/name=opencode`.
2. **Then: a policy on 6767 admitting only the vmcp pod plus the envoy-internal
   gateway.** That trims the blast radius around the Paseo bearer token. While
   `remoteUrl` is the public hostname this is only partly meaningful (the
   envoy-internal path is still there), and it becomes fully meaningful once the
   in-cluster pair above is applied.
3. **`incomingAuth.type: oidc` on the vMCP if it ever leaves the namespace.**
   Until then there is no caller identity at all. `authzConfig` (Cedar) is not an
   option at any point: the optimizer refuses to start with it
   (stacklok/toolhive#6089), so a policy here crash-loops the gateway instead of
   narrowing it.

No NetworkPolicy ships with this change: the anonymous cluster-internal posture
was explicitly accepted by the operator for now. Step 1 is the next one to take.

Manual test (cluster-internal):

```sh
kubectl -n llm port-forward svc/vmcp-agents 4483:4483
curl -s -X POST http://localhost:4483/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# expect only find_tool and call_tool, then
# {"name":"find_tool","arguments":{"tool_description":"list wifi clients","tool_keywords":["clients","wifi"]}}
# (the arguments are tool_description and tool_keywords; tool_keywords is a LIST
# of strings, and a bare "query" is rejected)
```

Known loosening for toy phase: `UNIFI_LOCAL_VERIFY_SSL=false` (self-signed
console cert) — see upgrade note in `unifi-mcp/mcpserver.yaml`.
