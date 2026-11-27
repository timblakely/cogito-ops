# Existing OpenCode key concurrency repair

The user authorized raising the local OpenCode key from four to eight concurrent
requests to match Inkling's Radiance `max-num-seqs: 8`. The subscription key is
unchanged, and these slots are shared with other runtime consumers.

The GitOps declaration applied successfully, but the operator reported Ready
while LiteLLM's existing `role-opencode` database record still enforced four.
This one-shot Job closes that existing-key reconciliation gap without rotating
the credential or changing scopes, budgets, or request/token rate limits.

The script projects the existing admin and OpenCode credentials read-only into
the pod. It exports no credential, key handle, headers, raw responses, or error
bodies. It has no ServiceAccount token. Updates are refused unless the alias is
exactly `role-opencode`, the existing scope is nonempty, and the current limit is
four or eight. The only update payload fields are the existing key handle and
`max_parallel_requests: 8`.

This LiteLLM version returns 404 for `/key/info/self`, so the script falls back
to bounded admin key discovery and requires exactly one matching alias. That
fallback follows the previously used key-scope repair API pattern.

Offline check and rendering:

```sh
python3 plans/llm/artifacts/2026-11-27-inkling-effort/concurrency-sync/sync.py --self-test
kustomize build plans/llm/artifacts/2026-11-27-inkling-effort/concurrency-sync \
  --load-restrictor=LoadRestrictionsNone
```

Preview the complete output before applying. The Job is deliberately outside
the cluster's GitOps resource tree; it is a bounded repair, not a recurring
admin-credential workload. `result.json` records the sanitized successful read
back: four before, eight after, with scope, budget, and rate limits unchanged.
