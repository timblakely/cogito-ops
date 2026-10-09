#!/usr/bin/env python3
"""Validate every Prometheus target in a Grafana dashboard JSON against a live
Prometheus: parse check, then real instant + range evaluation.

Grafana interpolates its own tokens before Prometheus sees the query, so
emulated here: $__rate_interval/$__interval -> 15m, $__range -> 6h, and every
$<var> -> the variable's allValue (regex variables) or a permissive default.

Usage (port-forward first):
    kubectl -n observability port-forward pod/prometheus-kube-prometheus-stack-0 9091:9090
    python3 scripts/validate-grafana-dashboard.py PROM_URL dash.json [dash2.json ...]
    python3 scripts/validate-grafana-dashboard.py http://127.0.0.1:9091 \
        kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json

Exit 0 = every expr parsed and evaluated; empty results are reported but are
NOT failures (a panel legitimately has no data while its engine is suspended).
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SUBST = [
    (r"\$__rate_interval", "15m"),
    (r"\$__interval\b", "15m"),
    (r"\$__range\b", "6h"),
]


def emulate(expr, var_defaults):
    for pat, rep in SUBST:
        expr = re.sub(pat, rep, expr)
    for name, default in var_defaults.items():
        expr = re.sub(r"\$\{%s(?::[^}]*)?\}" % re.escape(name), default, expr)
        expr = re.sub(r"\$%s\b" % re.escape(name), default, expr)
    return expr


def api(base, path, **params):
    url = base + path + "?" + urllib.parse.urlencode(params)
    last = RuntimeError("unreachable")
    for _ in range(4):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # Prometheus answers 4xx with a JSON body naming the real cause;
            # without surfacing it a parse error looks like a transport failure.
            try:
                return json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                return {"status": "error", "errorType": "http", "error": f"HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001 - port-forwards flap
            last = e
            time.sleep(2)
    raise last


def collect_targets(dash):
    out = []

    def walk(panels):
        for p in panels:
            if p.get("panels"):
                walk(p["panels"])
            for t in p.get("targets", []):
                if t.get("expr"):
                    out.append((p.get("title", "?"), t["expr"]))

    walk(dash.get("panels", []))
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    var_defaults = {}
    failures = 0
    for file in sys.argv[2:]:
        dash = json.load(open(file))
        for v in dash.get("templating", {}).get("list", []):
            if v.get("type") == "query":
                var_defaults[v["name"]] = v.get("allValue") or ".*"
        print(f"== {file}  ({dash.get('title')})")
        print(f"   variable emulation: {var_defaults}")
        for panel, expr in collect_targets(dash):
            q = emulate(expr, var_defaults)
            try:
                inst = api(base, "/api/v1/query", query=q)
                rng_start = int(time.time()) - 6 * 3600
                rng = api(base, "/api/v1/query_range", query=q, start=rng_start,
                          end=int(time.time()), step=900)
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"   FAIL  {panel}: {e}\n         {q[:160]}")
                continue
            if inst.get("status") != "success" or rng.get("status") != "success":
                failures += 1
                print(f"   FAIL  {panel}: {inst.get('error') or rng.get('error')}"
                      f"\n         {q[:160]}")
                continue
            ni = len(inst["data"]["result"])
            nr = len(rng["data"]["result"])
            flag = "ok   " if nr else "EMPTY"
            print(f"   {flag} instant={ni:2d} range={nr:2d}  {panel}")
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
