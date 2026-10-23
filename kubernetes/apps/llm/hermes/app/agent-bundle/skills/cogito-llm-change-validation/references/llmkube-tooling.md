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
Grafana variables matched against query-created labels. It also runs a
STRUCTURAL gate (duplicate refIds across one panel's targets make the whole
panel render "No data" in Grafana 12 even when every expr is valid — a bug
class Prometheus-side checks cannot see). Run it on any dashboard you edit,
not just this one. Prove the gate can fail with `--self-test`:

```bash
python3 scripts/validate-grafana-dashboard.py http://127.0.0.1:9091 \
    kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json --self-test
```

It asserts a broken expr FAILS and a known-real expr returns series (so an
all-green run implies a live endpoint, not a dead gate).

## Flux: one KS object per app

Every app directory is its own Flux Kustomization in the app namespace
(`llmkube`, `litellm`, ... -> `.../apps/<app>/app`), plus `<app>-resources`
for the InferenceService layer. `flux reconcile kustomization llmkube -n llm`
does NOT apply litellm-app files. When a change spans two apps (e.g. the
llm-serving dashboard plus its cross-link on litellm.json), reconcile BOTH,
each with `--with-source`, or half the change sits unreconciled and looks
broken. Check `kubectl get kustomization -n <ns>` before assuming coverage.
Every app KS (`llmkube`, `llmkube-resources`, `litellm`, ...) lives in the `llm`
namespace, so bare `flux reconcile kustomization llmkube-resources` dies with
"not found" and bare `flux get kustomizations` lists only the root `llm` KS.
That "not found" is not a stuck deploy: reconciling the root KS, or even just
`flux reconcile source git flux-system`, triggers the children, so read each
KS's `Ready`/applied revision instead of trusting the chain. Never judge a
reconcile from an `&&` chain piped through `tail` — the pipe reports tail's exit
0, so a failed `flux reconcile` still falls through into any wait loop behind it.

## Two ways to shoot yourself in the foot while verifying

- Never kill a port-forward by pattern from the same shell that started it: `pkill -f`
  and `ps -eo pid,args | awk '/[p]ort-forward .../'` both match the *current command's
  own command line* (it contains the literal string you are searching for), so the
  kill terminates your own shell and the result comes back as `signal 15` with the
  tail of your output missing. Launch with `nohup ... & echo $! > pf.pid` and kill the
  recorded pid.
- During a LiteLLM proxy roll the OLD pod stays Ready and keeps serving with the
  STALE model catalogue. A request fired at that moment fails with
  `InternalServerError ... OpenAIException - Connection error` for a model whose
  backend you just deleted — that reads like your repoint is broken when it is only
  the retiring pod. Wait for the new replicaset Ready AND the old pod absent
  (`kubectl get endpointslices -l kubernetes.io/service-name=litellm`) before judging
  a model-catalogue change.

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
