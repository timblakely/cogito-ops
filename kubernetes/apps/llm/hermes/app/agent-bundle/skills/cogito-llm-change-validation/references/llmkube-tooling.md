# llmkube tooling and the dashboard split

## Scripts (run from repo root)

- `scripts/validate-llm-catalogue.py [--config <litellm config>] [--self-test]`
  — catalogue validator (run with the repo venv; see SKILL.md gate 1 of
  cogito-llm-change-validation).
- `scripts/llm/build_llm_serving_dashboard.py <out.json>` regenerates
  `kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json`. That JSON is
  GENERATED — never hand-edit it; edit the generator, regenerate, revalidate.
- `scripts/validate-grafana-dashboard.py <prom-url> <dashboard.json> [--series N]`
  parses and evaluates EVERY Prometheus target in a dashboard JSON (instant +
  range) against a live endpoint, substituting `$lane`/`$datasource`/`$__*`
  like Grafana. Empty results report as EMPTY, not failures — a panel whose
  engine is scaled to zero legitimately returns nothing.

```bash
kubectl -n observability port-forward pod/prometheus-kube-prometheus-stack-0 9091:9090 &
python3 scripts/validate-grafana-dashboard.py http://127.0.0.1:9091 \
    kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json
```

It caught real bugs a JSON lint cannot see: PromQL string-literal escape
rules, `rate(label_replace(...))` being illegal, fully-anchored regexes, and
Grafana variables matched against query-created labels. Run it on any
dashboard you edit, not just this one. A green run that finishes
suspiciously fast is suspect — spot-check the gate can fail (add one bogus
expr to a copy of the JSON).

## Flux: one KS object per app

Every app directory is its own Flux Kustomization in the app namespace
(`llmkube`, `litellm`, ... -> `.../apps/<app>/app`), plus `<app>-resources`
for the InferenceService layer. `flux reconcile kustomization llmkube -n llm`
does NOT apply litellm-app files. When a change spans two apps (e.g. the
llm-serving dashboard plus its cross-link on litellm.json), reconcile BOTH,
each with `--with-source`, or half the change sits unreconciled and looks
broken. Check `kubectl get kustomization -n <ns>` before assuming coverage.

## Dashboard ownership

- `litellm` app (`litellm.json`, uid `cogito-litellm`): what the PROXY
  observes — spend, cost, tokens, RPS, latency, key/team accounting. Keep
  engine metrics out of it.
- `llmkube` app (`llm-serving.json`, uid `cogito-llm-serving`): engine
  telemetry per serving lane — prompt/generation tok/s, concurrency, KV
  occupancy, cache hit rate, engine coverage caveats. Families come from the
  `llmkube-inference` PodMonitor; see skill `llm-engine-metrics-dashboard`
  for the PromQL pitfalls.

Both ship as `configMapGenerator` + fixed name
(`disableNameSuffixHash: true`) + `substitute: disabled` annotation + a
`GrafanaDashboard` CR with `configMapRef` — the litellm and dcgm apps both
use this; the inline-CR pattern is not required.

## Verifying a dashboard actually reached Grafana

`GrafanaDashboard` CR status `DashboardSynchronized=True` is necessary but
not sufficient (the operator can lag or half-apply). The real check is the
Grafana API:

```bash
kubectl -n observability port-forward deploy/grafana-deployment 3000:3000 &
AUTH=$(printf 'admin:%s' "$(kubectl -n observability get secret grafana-admin-credentials \
  -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d)" | base64)
curl -s -H "Authorization: Basic $AUTH" http://127.0.0.1:3000/api/dashboards/uid/<uid>
```

Panels inside collapsed rows are nested under the row panel's `panels` key in
the API response, not top-level. The
`/api/datasources/proxy/uid/<ds-uid>/api/v1/query` route re-runs a panel expr
through Grafana's own datasource — the strongest end-to-end proof a panel
works.
