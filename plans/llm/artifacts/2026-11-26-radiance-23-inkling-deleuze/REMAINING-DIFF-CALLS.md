# Remaining owner-aware diff calls (copy of REMAINING-DIFF-CALLS.md) (continuation sheet)

Nothing in this section has run since the RBAC fix. No `serverdiff2-*` artifact
exists yet, and none may be inferred from the pre-RBAC files in this directory:
`serverdiff-ks-*.txt` (4 files) are verbatim **denials** recorded before
`tqkkqomn c86a6597` added `Role llm/flux-mcp-substitution-reader`, and
`serverdiff-hr-hermes.txt` is marked `RETRACTED` (un-substituted render).

## Why the first attempt produced nothing

Worker `d7b9e35e-d2fe-4f6e-b461-92134373bb5f` (started 01:19Z) made exactly two
tool calls — a directory listing and a `search` for the MCP tool signature — then
produced no further output for ~35 min with 64 output tokens. No `diff_kubernetes_manifest`
call was ever made, so there is no result and no explanation beyond "it stalled
before the first call". I cancelled it (`paseo_cancel_agent`, reported as an errored
event) rather than let it idle, and relaunched the same work with explicit
per-call instructions (read in slices → inline the bytes into one `execute` call →
write the output immediately), split 2 + 3 across two workers so no worker holds
the 361 KB total at once. If those workers also return nothing, stop delegating and
run the five calls below directly.

## The five calls

`diff_kubernetes_manifest` needs the **complete file contents verbatim** as
`yaml_content`; Code Mode has no filesystem access, so the bytes must be inline.
Read each file with the Read tool in ~300-line slices and concatenate. Save the
output with three header lines (`# source manifest:`, `# owner:`, `# generated:`),
a blank line, then the tool output verbatim.

| # | file (in /tmp/opencode/radiance-230-deploy) | bytes | owner_kind | owner_name | output |
|---|---|---|---|---|---|
| 1 | `hr-hermes.yaml` | 5 953 | HelmRelease | hermes | `serverdiff2-hr-hermes.txt` |
| 2 | `ks-llmkube-resources.yaml` | 56 477 | Kustomization | llmkube-resources | `serverdiff2-ks-llmkube-resources.txt` |
| 3 | `ks-opencode.yaml` | 59 370 | Kustomization | opencode | `serverdiff2-ks-opencode.txt` |
| 4 | `ks-litellm.yaml` | 118 682 | Kustomization | litellm | `serverdiff2-ks-litellm.txt` |
| 5 | `ks-hermes.yaml` | 126 539 | Kustomization | hermes | `serverdiff2-ks-hermes.txt` |

Call shape (all five, only the four string values change):

```js
await tools.flux.diff_kubernetes_manifest({
  yaml_content: `<complete file contents, verbatim>`,
  owner_kind: "Kustomization",         // or "HelmRelease" for #1
  owner_name: "llmkube-resources",     // per table
  owner_namespace: "llm",
})
```

## How to read the results

* Expected for #2–#5: only the objects this change touches. The offline
  equivalent (`offline-diff-ks-llm.patch`) lists exactly nine:
  `InferenceService/llm/radiance`, `ConfigMap/llm/radiance-fleet-config`,
  `LiteLLMVirtualKey/llm/{hermes,opencode}`, `LiteLLMModel/llm/inkling-deleuze`,
  `ConfigMap/llm/{paseo-config,opencode-config}`, `HelmRelease/llm/hermes`,
  `ConfigMap/llm/hermes-provider-bootstrap`. Anything else in a server-side diff is
  either render noise or a real surprise and must be explained before publishing.
* Known render noise to expect and account for, not to be mistaken for a cluster
  change: `config.kubernetes.io/index` / `internal.config.kubernetes.io/index`
  annotations that `flux-local` adds, and for #1 the fact that it is an
  un-substituted chart render (see the RETRACTED note). The authoritative
  substituted comparison for #1 stays `offline-diff-hr-hermes.patch`, which renders
  against the live HelmRelease values and shows a single annotation delta.
* Any `forbidden`/`cannot get` line means the grant is not effective for that path:
  record it verbatim, do not retry more than once, do not seek another identity.

## State this sheet was written against

`@ = vyulpmvo f5e94a6d` (change kept, rebased on `tqkkqomn`), `main@origin =
tqkkqomn c86a6597`, live `radiance-fleet-config` still
`990640aa9027a3a744892735db3a3e852e737b5326d5bed2c2d1d7afa4f49118`, weight staged
and digest-verified, `radiance --check` exit 0. Publication and the key-scope Job
are both pending: the key-scope Job needs explicit user authorisation (dry-run
first, then apply), and publication waits for these five diffs plus that decision so
the two clients are not shipped an alias that 403s.
