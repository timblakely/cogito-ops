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
- `paseo/` — `MCPServerEntry` + `MCPExternalAuthConfig` + a derived
  `ExternalSecret`: the agent host's own agent-control MCP endpoint, registered as
  a group member with no new pods and no new secret *material* (one derived
  Secret holds the same password with its `Bearer ` prefix). Details below.
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
- Paseo: the daemon password, in Secret `paseo-server`, key `server-password` —
  the key the `paseo` container reads (`../opencode/app/helmrelease.yaml`). The
  gateway cannot use that key directly: its only usable static strategy is a header
  whose value is injected verbatim, and the daemon wants `Authorization: Bearer
  <password>`. So `paseo/externalsecret.yaml` derives Secret `paseo-gateway-auth`
  (key `authorization`, value `"Bearer " + password`) from the same 1Password field
  the PushSecret writes. That is one more Secret holding the same bytes, and the
  trade-off is deliberate: a second key on `paseo-server` would change a Secret the
  agent host pod references, and Reloader hashes referenced Secrets into the pod
  template — so a header prefix would restart every live agent session. No
  PushSecret exists for `paseo-gateway-auth` and nothing writes it to 1Password. No
  RBAC is added either: the operator's `Role/agents-vmcp` already grants
  `get`/`list`/`watch` on secrets in this namespace, and the derived value reaches
  the gateway through the aggregator rather than as a pod env var.

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

> **Outgoing-auth verdict, measured on v0.58.0.** The gateway authenticates to this
> backend with `MCPExternalAuthConfig type: headerInjection`, `headerName:
> Authorization`, and a Secret whose value is the whole `Bearer <token>` string —
> the value is injected **verbatim**, so the prefix has to be in the credential
> (`paseo/externalsecret.yaml` derives it). It is not `type: bearerToken`, even
> though that is the field you would reach for: `spec.type` enumerates
> `bearerToken` and admission reports `Valid=True`, but the runtime has no
> converter for it, and the failure is invisible until you look for the tools:
>
> ```
> ERROR failed to discover auth config for MCPServerEntry entry=paseo
>       error="failed to get converter for auth type bearerToken: unsupported auth type: bearerToken"
> WARN  skipping server entry due to conversion failure entry=paseo
> WARN  aggregation.tools entry matches no backend in the group; its filter/overrides are not applied workload=paseo
> ```
>
> That is not a version skew (the aggregator reports `v0.58.0`, the same release as
> the CRDs). The strategies the dial-out actually implements are `unauthenticated`,
> `header_injection`, `token_exchange`, `upstream_inject`, `aws_sts`, `obo`, `xaa`;
> `bearerToken` exists only in the operator's proxy runner, which turns it into
> `--bearer-token <secret>,target=bearer_token` on `MCPServer`/`MCPRemoteProxy`
> pods. So an `MCPServerEntry` can carry a static header or nothing at all.
>
> Corollary worth remembering when someone next wants per-caller behaviour:
> `headerForward` on an `MCPServerEntry` is a dead end too — it is defined in the
> CRD and accepted at admission but never sent on outbound requests when the entry
> is consumed as a vMCP static backend (upstream stacklok/toolhive#4996); only
> `MCPRemoteProxy` wires it. `paseo/mcpserverentry.yaml` leaves the field absent on
> purpose.
>
> Two rules the vendor documents and this cluster now depends on: the header value
> must come from a Secret (plaintext inline is refused at the CRD layer), and
> **rotating the credential requires restarting the vMCP pods**, because the
> aggregator resolves it at process start. Rotation is doubly indirect here: Secret
> `paseo-server` is *generated* in-cluster by `ClusterGenerator
> cnpg-pass-generator` and PushSecret-copied **into** 1Password (item `paseo`, field
> `server-password`), so the vault is the backup and `paseo-gateway-auth` is a
> derived copy that only catches up after the PushSecret (1h) plus its own refresh
> (1h) — and then needs the gateway restarted. After any daemon-password rotation,
> verify with `call_tool paseo_list_hosts` rather than assuming.
>
> Verified after this change (`f5da6d87`): `ExternalSecret paseo-gateway-auth`
> `Ready=True/SecretSynced`; on the VirtualMCPServer,
> `DiscoveredAuthConfig-paseo=True (ConversionSucceeded)` and
> `BackendsDiscovered=True — Discovered 2 backends`, with the paseo backend
> `status=ready message=Healthy mcpRevision=2025-11-25`; the gateway still
> advertises exactly `find_tool` and `call_tool`. The daemon side shows no `401`
> for the gateway and answers a real tool call through it
> (`paseo_list_hosts` → `hosts_count=0`, `self.label=opencode-…`).
>
> One log line you will see forever, and should not chase: the daemon logs a
> level-50 `Agent MCP transport error: Bad Request: Unsupported protocol
> version: 2026-07-28` about once per ~30 s, with bursts of 3–4 on (re)connect —
> 29 in 12 minutes measured. The cause is precise: `initialize` negotiates down
> cleanly (an `initialize` offering `2026-07-28` answers `200` with
> `2025-11-25`), but the gateway's health prober then POSTs with the
> `Mcp-Protocol-Version: 2026-07-28` **header**, and the MCP SDK's
> `validateProtocolVersion` 400s any non-initialize request whose header names
> an unsupported version (measured both: header `2026-07-28` → 400, header
> `2025-11-25` → 202). The prober gives up on the newest version and the backend
> stays `Healthy`. Annoying but harmless — except that it keeps the daemon's
> error counter busy, so alert on `401`, not on transport errors.

**The URL is not the Service DNS name, and that is the daemon's rule.** Paseo
applies a Vite-style Host allowlist (its `hostnames.js`): `localhost`,
`*.localhost`, any IP literal, and the names in `PASEO_HOSTNAMES`. Measured
2026-11-26 from two separate containers: `Host: paseo.timblakely.com` and
`Host: 127.0.0.1:6767` answer 200 with the 42-tool catalog;
`Host: opencode-paseo.llm.svc.cluster.local:6767` (and `.svc`, and the bare
service name, and the pod name) answer `403 {"error":"Invalid Host header"}`.
`headerForward` cannot repair this either: Go's transport takes the Host from
`Request.Host` and ignores a `Host` entry set on the request's Header map (and on
an entry that field is never sent at all, per #4996 above).

**Test the allowlist by dialing the Service, because the obvious test lies.** The
daemon's `403 {"error":"Invalid Host header"}` only appears on a direct
`http://opencode-paseo.llm.svc.cluster.local:6767/mcp/agents` with an explicit
`Host` header. Sent through the public URL instead, a rejected `Host` is a **404
from envoy** (unknown virtual host), which reads like a routing fault and is not
one. Measured against the Service on 6767: every cluster DNS name 403s, with or
without the port; `paseo.timblakely.com`, `paseo.timblakely.com:6767` and
`PASEO.TIMBLAKELY.COM` all return 200 with the 42-tool catalog. So the matcher
compares a port-stripped, case-folded host against the list — which is what makes
a plain hostname entry in `PASEO_HOSTNAMES` sufficient rather than hopeful.

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
once `PASEO_HOSTNAMES` (`../opencode/app/helmrelease.yaml`) lists that hostname.
The staged change names the exact hostname, which is enough: the matcher compares
the port-stripped, case-folded host against the list (measured, above). A
leading-dot pattern such as `.cluster.local` is the alternative that covers the
whole namespace family in one entry — accepted by the same matcher, but not
exercised here, so it is not what the file ships. Half a flip is a permanent 403,
and the symptom is
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
**4,757**, and the two meta-tools a client actually loads are **419**. What a
search costs back is in "Retrieval, measured" below: **729 tokens** average for a
Paseo shortlist, because hits arrive with full `inputSchema`s. A worker that
searches once and calls what it found pays 419 + 729 where two tool groups alone
would have cost it 10,213; a worker that searches nothing pays 419.

Those numbers are per-member, measured with Paseo as the group's only backend.
With both members live the same client registers `tools.agents.find_tool` and
`tools.agents.call_tool` and the gateway's own `tools/list` baseline is
**10,671 tokens** — that is what carrying all 64 tools would cost — and the
shortlists measured through the live gateway come back at **1,039–1,596** tokens
rather than 729–988. Restated against the live figure, the gateway is cheaper
than carrying the catalog below roughly **eight** searches a session, not five.

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
  (upstream stacklok/toolhive#6089). Measured: offering `2026-07-28` in
  `initialize` to either this gateway or the Paseo daemon returns `2025-11-25`.
  The negotiation only covers `initialize` though — later requests carry the
  `Mcp-Protocol-Version` header, and a header naming an unsupported version is a
  hard 400 on both (see the Paseo member's health-probe note above).
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

Two things that are easy to get wrong, one of them measured differently than the
docs read:

- **Measured on this build, the filter is stricter than the CRD text suggests.**
  The docs describe `filter` as gating *advertising* while the tool stays in the
  routing table. Through the optimizer's meta-tools it is gone instead:
  `call_tool paseo_create_terminal` returns
  `{"isError":true,"text":"tool not found: paseo_create_terminal"}`, and in 4
  queries written to hit exactly the withheld tools, none of them appeared (0/4).
  Inside the gateway, then, this is enforcement, not presentation. What it is
  **not** is a boundary against anything holding the daemon credential: a caller
  that dials `/mcp/agents` directly still sees and calls all 42 tools.
- MCP has no per-caller tool policy. Anyone who can reach 4483 gets whatever the
  gateway advertises, and behind that the gateway holds credentials (the Paseo
  bearer header, the UniFi read-only key) that those callers do not have
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

With Paseo in the group (38 queries, one per advertised tool, against the live
gateway): **recall@8 0.974**, **recall@1 0.816**, mean shortlist **5.89 of 8**
slots. One miss: *"see which agent sessions are running on this host right now"*
wanted `paseo_list_agents` and got `paseo_set_agent_mode`, `paseo_kill_agent`,
`paseo_get_agent_status` — the semantic neighbourhood is right, the exact tool
lost. UniFi's 3 controls are **unchanged** by adding a 38-tool workload
(recall@8 1.000, recall@1 0.333, mean 5.67), which is the guard that the new
filter and the new member did not swallow the existing group. The 4 queries
written for the withheld tools hit them 0/4, while all 4 of those shortlists still
contained *other* Paseo tools — the filter removes tools, not the workload. The
2 controls aimed at `find_tool`/`call_tool` themselves never match: the meta-tools
are what the client already holds, so they are not in the index.

**What a search costs, measured** (`cl100k_base` over the JSON a client actually
reads): a Paseo shortlist averages **729 tokens** (3,215 characters, max 1,382 in
this run) because `find_tool` returns full `inputSchema`s for its hits, not names.
The catalog a client would otherwise carry is 4,927 tokens for the same 38 tools,
and the two meta-tools cost 419. So one search plus the meta-tools is 1,148
tokens (23% of carrying the catalog), two searches 1,877 (38%), and it only breaks
even past ~11 searches — the argument for the gateway is not raw token arithmetic
on a single turn but that a worker with 5 unused tool groups pays 419 tokens plus
what it searches, instead of every group's catalog.

Shortlists are shorter than the 8 allowed because `find_tool` prunes weak hits
(`semanticDistanceThreshold` defaults to 1.0), and this build returns `score: null`
for every hit, so ranking can only be inferred from order.

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
this measurement: 38 queries for the tools this filter advertises, 4 for the
withheld ones (where a hit would be a bug), 2 aimed at the gateway's own
meta-tools (which must miss), and 3 UniFi controls to prove the new member did not
swallow the existing group. Two caveats found while using it, both of which will
bite whoever writes the next one: the shortlist arrives as JSON inside
`result.content[0].text`, not as `structuredContent`, and every hit's `score` is
`null` on this build.

## How an agent should talk to `find_tool`

Same gateway, same 30 Paseo tools, same ranker — only the query text changed:

| How the query was written                                     | recall@8 | recall@1 |
| ------------------------------------------------------------- | -------- | -------- |
| the gold tool's own `description` string                        | 1.000    | 1.000    |
| task intent, hand-picked `tool_keywords`                        | 1.000    | 0.567    |
| task intent, keywords scraped out of the sentence               | 0.967    | 0.567    |
| task intent, no keywords at all                                 | 1.000    | 0.567    |

Two things follow. `tool_keywords` do not decide ranking — three regimes scored
identically — but they are not useless: they rescue a tool the semantic arm
misses outright, which is how `list_hosts` went from absent to rank 5 for "which
machines can I run agents on". And top-1 is largely an artefact of how a harness
writes its queries: a query paraphrased from a tool's description matches the
description it was paraphrased from, so any harness that writes one query per
tool while looking at that tool measures 0.8–1.0 top-1 and predicts nothing.
Use recall@8 (~0.97 here) as the design number and 0.567 as the honest
expectation for real traffic.

What to tell an agent that only has the two meta-tools:

1. `tool_description` drives ranking and it matches *descriptions*, so write it
   as a capability sentence in the tool's own register — "creates an isolated
   workspace and starts a coding agent in it" — not as a user request.
2. `tool_keywords` must be a JSON array (a comma-joined string fails the
   gateway's own unmarshaller). Two to four discriminative nouns, picked for the
   word a description would not contain.
3. Expect two to six plausible candidates and read them all: the right tool is
   frequently second or third. The confusable families are
   `get_agent_status`/`get_agent_activity`/`list_agents`,
   `create_workspace`/`list_workspaces`, and `create_heartbeat` against
   `create_schedule` and `schedule_logs`.
4. If a shortlist looks wrong, re-query with different capability wording rather
   than repeating the same words.
5. One search costs **730–990** tokens against a Paseo-only group and
   **1,039–1,596** through the live two-member gateway (cl100k), and it stays in
   the transcript for the rest of the session — nothing reclaims a tool result.
   Reuse a name already found; `call_tool` needs no fresh `find_tool`.

The short form lives in the worker profile's `notes` in
`kubernetes/apps/llm/opencode/app/paseo-config.yaml`, surfaced by `list_profiles`.
Whether a launched worker sees its own profile notes is unverified, so the lead
profile's notes tell the orchestrator to copy them into the worker's first prompt.

### The worker split has never actually run

The intent was that only a lead carries Paseo's catalog and every launched
worker reaches tools through this gateway instead. `list_profiles` shows both
profiles, the config validates, and the unit tests pass — and the first real
`create_agent` on the worker provider failed before a session started:

```
Custom OpenCode MCP servers or process environment require an isolated server
and cannot be used with a shared OpenCode service.
```

That is the daemon's own gate, not a misconfiguration of this gateway. A session
joins the shared OpenCode service only when its launch config asks for nothing
per-session (`agent/providers/opencode/v2/configuration.js`, where
`requiresDedicatedV2Server` returns true for any non-empty `mcpServers` and for
any launch env beyond `PASEO_AGENT_ID`/`PASEO_AGENT_CWD`/`PASEO_WORKSPACE_ID`),
and the check that follows it throws rather than downgrading.

What the worker provider set was `paseoTools: {enabled: false}`. That switch is
correct about *what* it removes and wrong about *where* it lands: Paseo strips
the internal `paseo` MCP server from a launch only on the native-tools path
(`agent-manager.js`, `return launchContext.paseoTools ?
stripInternalPaseoMcpServer(merged) : merged`), and `enabled: false` is not the
native-tools path — `isPaseoToolPolicyEnabled` is `policy?.enabled !== false`,
so a disabled policy skips that branch and leaves the launch asking for a server
of its own. Do not reach for the global knobs either: `daemon.mcp.enabled:
false` unmounts `/mcp/agents`, which is the endpoint this gateway dials.

The mechanism that stays on the working side of the gate is the per-tool list
the same policy reader supports — `paseoTools: {enabled: true, disabledTools:
[…every tool name]}`, which keeps `isPaseoToolPolicyEnabled` true (so native
tools are in use and the internal server is stripped) while `isPaseoToolEnabled`
returns false for every name. `kubernetes/apps/llm/opencode/app/paseo-config.yaml`
carries that shape. It is **reasoned from the code above and not yet measured**:
that ConfigMap is the one Reloader watches, so testing it costs a rollout and
every live session. If a launched worker still fails to start, the fallback is
to delete the worker provider and profile and leave every agent injected, which
costs context and nothing else. Until a worker has been launched and its context
counted, treat "workers get no Paseo catalog" as intended behaviour, not as a
property of this deployment.

## Exposure, and why the narrowing steps are load-bearing

**The `agents` gateway is unauthenticated inside the cluster and it now holds a
working credential for this pod's agent control plane.** That posture was chosen
deliberately, not inherited by accident, and it is worth stating plainly: whoever
reaches `vmcp-agents:4483` can launch agents, create workspaces and read terminals
on this host without a credential of their own -- for a while that meant every pod
in the cluster, which is what step 1 below exists to have narrowed. That
is not hypothetical — during verification an unauthenticated Streamable HTTP
session (no token, no client certificate, just cluster routing) called
`paseo_list_hosts` through the gateway and got a real answer
(`hosts_count=0, self.label=opencode-…`). The gateway paid for it with the
`paseo-gateway-auth` header, which is exactly the aggregate credential the ladder
below is about.

The steps below are not nice-to-have hygiene, because the usual mitigations do
not apply here:

- **MCP has no per-caller tool policy**, so the gateway cannot answer "which
  tools may *this* caller use". There is no caller identity to ask about.
- **`filter` does gate advertising, and on this build it also blocks the
  meta-tool path** — `call_tool` answers `tool not found` for a withheld tool. But
  that is a property of the optimizer, not a security boundary: anything holding
  the daemon credential can dial `/mcp/agents` directly and see all 42 tools,
  filtered or not.
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

1. **Done: `paseo/networkpolicy.yaml` limits 4483 to the opencode pods.** It
   follows the `flux-ops` pair in this directory -- a backend policy admitting only
   the proxy, a proxy policy admitting only `app.kubernetes.io/name=opencode` --
   with the gateway's own labels (`app=virtualmcpserver, toolhive-name=agents`) and
   its real port, which is 4483 rather than the 8080 the older members use. What
   was checked before applying it: the selector matches exactly one pod
   cluster-wide; the only client of the gateway in the repo is the `agents` MCP
   server in the opencode config; no HTTPRoute or Ingress anywhere has a
   virtualmcpserver backendRef, so remote Paseo clients reach the daemon on 6767
   through envoy-internal and never traverse this pod; no monitor scrapes it; and
   the same policy shape has kept an httpGet-probed pod ready for days under
   `flux-ops-backend`, which is why no probe rule is included. What it does not do:
   confine anything inside the opencode pod.
2. **Then: a policy on 6767 admitting only the vmcp pod plus the envoy-internal
   gateway.** That trims the blast radius around the Paseo bearer token, but it is
   not just another YAML: selecting the opencode pod default-denies *every* ingress
   port on it, and 4096 is published to the same envoy gateway by HTTPRoute
   `opencode`, so the allow-list has to carry 6767 and 4096 from
   `envoy-system`/`envoy`/`owning-gateway-name=envoy-internal`, the gateway pod,
   and a decision about kubelet-sourced `tcpSocket` probes from the node addresses.
   Loopback stays outside any policy's reach either way.
3. **`incomingAuth.type: oidc` on the vMCP if it ever leaves the namespace.**
   Until then there is no caller identity at all. `authzConfig` (Cedar) is not an
   option at any point: the optimizer refuses to start with it
   (stacklok/toolhive#6089), so a policy here crash-loops the gateway instead of
   narrowing it.

The audience is now the agent pod and nothing else, by
`kubernetes/apps/llm/toolhive/paseo/networkpolicy.yaml` (step 1 below). The
anonymous posture inside that audience was accepted deliberately and is still true
in every other respect: the gateway holds a working credential, it authenticates
nobody who is allowed to reach it, and nothing inside the opencode pod is bound by
any of this. Step 2 is the next one to take.

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
