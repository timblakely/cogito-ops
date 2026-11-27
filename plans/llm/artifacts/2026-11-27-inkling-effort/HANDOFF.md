# Inkling effort rollout verification

The task change is `mplsqsul` in `/workspace/cogito-inkling-effort`. Its parent
`psvwytuu` (published as `6237aec0151670970b6519910bc9bc89cbd30bbf`) raised the local
OpenCode key's concurrency to eight and repaired the existing LiteLLM database
record. The subscription key, model scopes, budgets, and rate limits are unchanged.

The reasoning change adds all seven upstream named efforts to LiteLLM metadata,
the shared capability publisher, OpenCode variants, both Paseo provider catalogues,
and Hermes' handling of minimum effort. The Hermes tarball and pod checksum were
regenerated; changing plugin source alone does not deploy it.

## Evidence before publication

- All sixteen final effort-conditioning probes passed through the Hermes and
  OpenCode keys: default, none, minimal, low, medium, high, xhigh, and max.
- `none` is minimum conditioning, not guaranteed off; max aliases xhigh.
- The OpenCode/Hermes/capability-publisher unit suites passed; two optional
  environment-dependent tests are skipped. Reports are also in this thread's
  persistent GenUI storage as `inkling-unit-tests.json` and
  `inkling-runtime-tests.json`.
- Catalogue validation, provider-bootstrap tests, deterministic Hermes bundle
  freshness, and local Kustomize renders passed.
- Complete Flux-component renders were passed to owner-aware server diffs.
  The changed resources can be dry-run, but RBAC prevents a complete server
  dry-run of unrelated kinds; do not claim that every resource passed.
- The pinned legacy flux-local 8.4.0 test cannot discover this isolated jj
  workspace (no colocated `.git`). Do not alter VCS metadata or the unrelated
  validation migration in `/workspace/cogito` to bypass it.

## Verify after the OpenCode/Paseo restart

The ConfigMap changes trigger a rollout of the pod hosting the initiating agent,
so a one-time scheduled continuation must verify the expected published SHA.
Use the expected SHA supplied in that continuation, not merely whatever main
happens to point to later.

- Read `GitRepository/flux-system/flux-system` and
  `Kustomization/llm/{litellm,hermes,opencode}`. Confirm the expected source
  revision applied and all three are Ready. Reconcile through the Flux tools
  if necessary; never treat a reconcile request as completion.
- Wait for deployments `model-caps`, `hermes`, and `opencode` to be Available.
- Fetch `http://model-caps.llm.svc.cluster.local:8090/v1/models`; the
  `inkling-deleuze` reasoning metadata must list the seven efforts and
  `mandatory: true` (there is no guaranteed hard-off switch).
- Use the built-in `opencode.models` tool, provider `cogito`, query `inkling`.
  Its variants must contain exactly the seven levels.
- Discover and call Paseo's `paseo_list_models` through the agents gateway for
  providers `opencode` and `opencode-worker`, NOT provider `cogito`. Their Inkling
  `thinkingOptions` must list the same seven levels.
- Verify the live Hermes bundle checksum matches the committed generated bundle
  and the restarted deployment is healthy. The sixteen authenticated probes
  already verified both consumer keys; do not repeat them merely to get longer
  answers or infer effort solely from response length.
- No further key-limit repair is needed: `concurrency-sync/result.json` verifies
  four before and eight after, preserving all other tested limits.

Do not report the reasoning rollout complete until the live catalogues and
deployed revision are verified. Keep any deployment repair in the existing task
change and repush through jj, preserving unrelated main commits.
