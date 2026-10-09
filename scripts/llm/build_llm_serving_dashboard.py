#!/usr/bin/env python3
"""Generate kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json.

The dashboard visualises what the inference engines themselves expose —
prompt-processing and generation speed, concurrency, KV-cache occupancy and
prefix-cache hit rate, per serving lane — because LiteLLM exports none of it
(scope line: llmkube/app/grafanadashboard.yaml).

Keep the committed JSON in sync when editing panels:

    python3 scripts/llm/build_llm_serving_dashboard.py \\
        kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json

Then validate every PromQL target against the live cluster:

    kubectl -n observability port-forward pod/prometheus-kube-prometheus-stack-0 9091:9090
    python3 scripts/validate-grafana-dashboard.py http://127.0.0.1:9091 \\
        kubernetes/apps/llm/llmkube/app/dashboard/llm-serving.json

The validator caught real bugs during authoring (PromQL string escapes,
rate(label_replace(...)) being illegal, fully-anchored regexes) that no JSON
lint would see. Do not hand-edit the generated JSON.
"""
import json

DS = {"type": "prometheus", "uid": "${datasource}"}

# --- shared PromQL fragments -------------------------------------------------

# Metric-family presence is the ONLY reliable engine discriminator: the
# llmkube PodMonitor's `runtime` label says "generic" for both the llama.cpp
# muse-glimmer-30b service and the radiance flashnext-iggy service, because
# both are generic-args InferenceServices.
LANE_MATCH = '{__name__=~"llamacpp:requests_processing|vllm:num_requests_running|radiance:http_queue_depth"}'
ENGINE_TABLE = (
    '  label_replace(count by (service, model) (radiance:http_queue_depth), "engine", "radiance", "", "")\n'
    'or label_replace(count by (service, model) (\n'
    '     llamacpp:requests_processing\n'
    '     unless on (service) (count by (service) (radiance:http_queue_depth))\n'
    '   ), "engine", "llama.cpp", "", "")\n'
    'or label_replace(count by (service, model) (\n'
    '     vllm:num_requests_running\n'
    '     unless on (service) (\n'
    '       count by (service) (radiance:http_queue_depth)\n'
    '       or count by (service) (llamacpp:requests_processing)\n'
    '     )\n'
    '   ), "engine", "vllm", "", "")'
)

# node comes from kube_pod_info, joined on the pod that reports the metrics.
NODE_JOIN = (
    'count by (service, node) (\n'
    '  (up{job="llmkube-inference"} == 1)\n'
    '  * on (pod) group_left (node) (count by (pod, node) (kube_pod_info{namespace="llm"}))\n'
    ')'
)

# LiteLLM's requested_model only equals the llmkube service name for one lane
# (flashnext-iggy); the others are catalogue aliases like google/gemma-4-12b-it.
# The deployment-level metrics carry api_base, whose hostname IS the service,
# so lane identity is label_replace'd from there. label_replace regexes are
# RE2 full-match, hence the trailing .* .
LANE_LABEL = (
    'label_replace({metric}, "lane", "$1", "api_base", "https?://([^./]+)[.:].*")'
)
LOCAL_ONLY = '{api_base=~".*svc.cluster.local.*"}'


def lane(metric, rate=None, window=None, filtered=True):
    """LiteLLM deployment-level series relabelled to the serving lane name.

    The $lane variable filters on api_base INSIDE the selector: PromQL cannot
    apply a matcher to the output of label_replace, so the host regex carries
    the variable. Grafana's $lane interpolation yields `.*` for All and
    `(a|b)` for a multi-select, both valid RE2 fragments here.
    """
    sel = lane_selector(metric, filtered)
    inner = sel
    if rate:
        inner = f"rate({inner}[{window or '$__rate_interval'}])"
    return LANE_LABEL.replace("{metric}", inner)


def lane_selector(metric, filtered=True):
    # Raw string: PromQL processes escapes in its own string literals, so the
    # emitted expression must carry `\\.` (which the selector then reads as
    # the regex `\.`). A single `\.` is a PromQL parse error, not an RE2 one.
    # The tail is `.*` not `[^/]*`: PromQL regexes are fully anchored and
    # api_base continues with `:8080/v1`, which a slash-free class cannot span.
    host = "$lane" if filtered else ".*"
    return r'%s{api_base=~"https?://%s\\.[^/]*svc\\.cluster\\.local.*"}' % (metric, host)


def lane_histogram(metric, q="0.95", filtered=True):
    """p95 of a LiteLLM histogram per serving lane.

    label_replace must sit OUTSIDE rate() (rate() takes only selectors), and
    flat-counter lanes are gated out via the _count rate so Grafana does not
    render NaN legend rows.
    """
    count = lane_selector(metric.replace("_bucket", "_count"), filtered)
    return (f'histogram_quantile({q}, sum by (le, lane) (\n'
            f'  label_replace(rate({lane_selector(metric, filtered)}[$__rate_interval]),\n'
            f'    "lane", "$1", "api_base", "https?://([^./]+)[.:].*")\n'
            f'))\n'
            f'and on (lane) (\n'
            f'  sum by (lane) (label_replace(rate({count}[$__rate_interval]),\n'
            f'    "lane", "$1", "api_base", "https?://([^./]+)[.:].*")) > 0\n'
            f')')


# --- panel builders ----------------------------------------------------------

_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def row(title, y):
    return {
        "id": nid(), "type": "row", "title": title, "collapsed": False,
        "panels": [], "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    }


def timeseries(title, desc, targets, x, y, w=12, h=8, unit="short", legend="{{service}}"):
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": [target(e, l or legend) for e, l in targets],
    }


def stat(title, desc, expr, x, y, w=6, h=4, unit="short", reduce="lastNotNull",
         color="value"):
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"colorMode": color, "graphMode": "area",
                    "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": [reduce], "fields": "", "values": False},
                    "textMode": "auto"},
        "targets": [target(expr)],
    }


def table(title, desc, targets, x, y, w=24, h=8, format="table", instant=True):
    return {
        "id": nid(), "type": "table", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"},
                                                "inspect": False}}, "overrides": []},
        "options": {"showHeader": True, "footer": {"show": False, "reducer": [], "fields": ""},
                    "sortBy": []},
        "targets": [target(e, fmt=format, instant=instant) for e in targets],
    }


def histogram(metric_bucket, q="0.95", by=("le", "service"), gate_by=("service",)):
    """p-quantile per label set, for lanes that actually have observations.

    Filtering bucket rates at > 0 would delete legitimately-empty LOWER
    buckets and skew the interpolation, so lanes with no observations in the
    window are dropped by gating on the _count rate instead. Without the gate,
    a lane whose counters sit flat yields NaN and draws a NaN legend row.
    """
    count_metric = metric_bucket.replace("_bucket", "_count")
    inner_by = ", ".join(by)
    gate = " and on (%s) (\n  sum by (%s) (rate(%s[$__rate_interval])) > 0\n)" % (
        ", ".join(gate_by), ", ".join(gate_by), count_metric)
    return (f'histogram_quantile({q}, sum by ({inner_by}) (\n'
            f'  rate({metric_bucket}[$__rate_interval])\n'
            f')){gate}')


def target(expr, legend=None, fmt=None, instant=None):
    t = {"datasource": DS, "expr": expr, "refId": "A"}
    if legend:
        t["legendFormat"] = legend
    if fmt:
        t["format"] = fmt
    if instant is not None:
        t["instant"] = instant
    return t


# --- the dashboard -----------------------------------------------------------

panels = []
y = 0

# ---- Row: Overview ----------------------------------------------------------
panels.append(row("Overview", y)); y += 1
panels.append(stat(
    "Serving lanes",
    "Distinct llmkube inference services reporting engine metrics right now. "
    "A lane disappears when its pods stop being scraped (scaled to zero, suspended, or recreated).",
    f"count(count by (service) ({LANE_MATCH}))", 0, y, unit="short"))
panels.append(stat(
    "Engine families",
    "How many distinct engine metric families are live: llama.cpp, vLLM and Radiance "
    "each contribute their own prefix, all scraped by the llmkube-inference PodMonitor.",
    'count(count by (__name__) (group by (__name__) ({__name__=~"llamacpp:requests_processing|vllm:num_requests_running|radiance:http_queue_depth"})))',
    6, y, unit="short"))
panels.append(stat(
    "Scrape targets down",
    "llmkube-inference targets whose last scrape failed. Engine metrics only exist where the server "
    "is reachable on its /metrics endpoint - a lane with --metrics missing shows as absent, not down.",
    'count(up{job="llmkube-inference"} == 0) or vector(0)', 12, y, unit="short"))
panels.append(stat(
    "LiteLLM in-flight",
    "HTTP requests in flight on the proxy (summed across uvicorn workers). Proxy-level only: "
    "this is NOT engine concurrency - see the Concurrency row for slots.",
    "sum(litellm_in_flight_requests)", 18, y, unit="short"))
y += 4

panels.append(table(
    "Serving lanes: engine, node, model",
    "One row per inference service. Engine is derived from which metric family the pod emits, "
    "NOT from the runtime label: the PodMonitor's `runtime` is 'generic' for any InferenceService "
    "that overrides container args, which covers both the llama.cpp muse-glimmer-30b lane and the "
    "Radiance flashnext-iggy lane.",
    [f'({ENGINE_TABLE})\n* on (service) group_left (node)\n({NODE_JOIN})'],
    0, y, h=8, format="table", instant=True))
y += 8

# ---- Row: Token throughput --------------------------------------------------
panels.append(row("Token throughput by serving model", y)); y += 1
panels.append(timeseries(
    "Prompt processing speed (tok/s)",
    "Prompt/prefill tokens computed per second, per inference service. Unified across engines from "
    "counters: llama.cpp prompt_tokens_total excludes cached tokens, so a cache-hit-heavy lane reads "
    "lower than its real wall-clock prefill; Radiance and vLLM prompt counters include cached work.",
    [("sum by (service) (rate(llamacpp:prompt_tokens_total{%s=~\"$lane\"}[$__rate_interval]))\n"
      "or sum by (service) (rate(vllm:prompt_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % ("service", "service"),
      "{{service}}")], 0, y, unit="none"))
panels.append(timeseries(
    "Generation speed (tok/s)",
    "Generated tokens per second per inference service, summed across replicas - lane throughput, "
    "not per-stream speed. Per-stream decode is the native-gauge panel on the right.",
    [("sum by (service) (rate(llamacpp:tokens_predicted_total{%s=~\"$lane\"}[$__rate_interval]))\n"
      "or sum by (service) (rate(vllm:generation_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % ("service", "service"),
      "{{service}}")], 12, y, unit="none"))
panels.append(timeseries(
    "Prompt processing - engine-native rate (tok/s)",
    "Engine's own prompt-processing rate. Radiance reports prefill_tokens_per_second over the "
    "scheduler's recent window; llama.cpp reports prompt_tokens_seconds as a per-scrape bucket that "
    "resets on EVERY scrape, so it must be read as an instant gauge - rate() over it is always 0/NaN. "
    "Idle lanes read 0 by design.",
    [("max by (service, pod) (radiance:prefill_tokens_per_second{%s=~\"$lane\"})\n"
      "or max by (service, pod) (llamacpp:prompt_tokens_seconds{%s=~\"$lane\"})" % ("service", "service"),
      "{{service}} {{pod}}")], 0, y, unit="none"))
panels.append(timeseries(
    "Decode speed - engine-native rate (tok/s)",
    "Engine's own decode throughput. Radiance decode_tokens_per_second is a live scheduler-window "
    "gauge; llama.cpp predicted_tokens_seconds is the same reset-per-scrape bucket trick (it is NOT "
    "a counter-rate), and llama.cpp counts generated tokens so a spec-decoding lane's accepted "
    "drafts appear here too.",
    [("max by (service, pod) (radiance:decode_tokens_per_second{%s=~\"$lane\"})\n"
      "or max by (service, pod) (llamacpp:predicted_tokens_seconds{%s=~\"$lane\"})" % ("service", "service"),
      "{{service}} {{pod}}")], 12, y, unit="none"))
panels.append(timeseries(
    "Decode speed per active stream (tok/s)",
    "Lane decode throughput divided by running requests - what one user perceives. "
    "Only meaningful on vLLM/Radiance surfaces (Radiance re-exports the vLLM-compat metrics, "
    "so num_requests_running covers it); llama.cpp parallel slots are per-slot, not aggregate-safe.",
    [("max by (service) (radiance:decode_tokens_per_second{%s=~\"$lane\"})\n"
      "  / clamp_min(max by (service) (vllm:num_requests_running{%s=~\"$lane\"}), 1)" % ("service", "service"),
      "{{service}} (radiance)")], 0, y, unit="none"))
panels.append(timeseries(
    "Prompt vs generated tokens (rate)",
    "The prompt:generation ratio per lane tells you whether a lane is doing agentic re-feeding "
    "(huge prompt column) or long single generations.",
    [("sum by (service) (rate(llamacpp:prompt_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} prompt (llama.cpp)"),
     ("sum by (service) (rate(vllm:prompt_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} prompt (vLLM/Radiance)"),
     ("sum by (service) (rate(llamacpp:tokens_predicted_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} generated (llama.cpp)"),
     ("sum by (service) (rate(vllm:generation_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} generated (vLLM/Radiance)")],
    12, y, unit="none"))
y += 8

# ---- Row: Concurrency ------------------------------------------------------
panels.append(row("Concurrency & queueing", y)); y += 1
panels.append(timeseries(
    "Requests in flight (engine view)",
    "llama.cpp counts busy slots (requests_processing); vLLM and Radiance count running requests "
    "(num_requests_running). Radiance re-exports the vLLM-compat surface, so one expression covers "
    "both; the `or` keeps llama.cpp lanes visible when a vLLM lane is absent.",
    [("sum by (service) (llamacpp:requests_processing{%s=~\"$lane\"})\n"
      "or sum by (service) (vllm:num_requests_running{%s=~\"$lane\"})" % ("service", "service"), "{{service}}")],
    0, y))
panels.append(timeseries(
    "Queued / deferred at the engine",
    "llama.cpp defers a request when no slot or KV space is free; vLLM/Radiance keep a waiting queue. "
    "Sustained nonzero here with idle replicas means the lane is KV- or slot-bound.",
    [("sum by (service) (llamacpp:requests_deferred{%s=~\"$lane\"})\n"
      "or sum by (service) (vllm:num_requests_waiting{%s=~\"$lane\"})" % ("service", "service"), "{{service}}")],
    12, y))
panels.append(timeseries(
    "Radiance admission: queue depth & rejects",
    "http_queue_depth is admitted-but-unfinished at the HTTP layer; admission_rejected counts 429s "
    "when the admission queue is full. Radiance-specific.",
    [("sum by (service) (radiance:http_queue_depth{%s=~\"$lane\"})" % "service", "{{service}} depth"),
     ("sum by (service) (rate(radiance:http_admission_rejected_total{%s=~\"$lane\"}[$__rate_interval]))" % "service",
      "{{service}} rejected/s")], 0, y))
panels.append(timeseries(
    "llama.cpp effective batch width",
    "n_busy_slots_per_decode: average slots fed into each llama_decode() call. ~1 means the lane "
    "never actually batches (parallel slots configured but unused); N means real batch sharing.",
    [("avg by (service) (llamacpp:n_busy_slots_per_decode{%s=~\"$lane\"})" % "service", "{{service}}")],
    12, y))
panels.append(timeseries(
    "Proxy concurrency vs engine concurrency",
    "litellm_in_flight_requests is proxy-side HTTP concurrency (no model label, uvicorn-worker "
    "livesum) - the gap against engine in-flight is LiteLLM + network overhead, not model work.",
    [("sum by (lane) (%s)" % lane("litellm_deployment_total_requests_total", rate=True), "{{lane}} started/s"),
     ("sum(litellm_in_flight_requests)", "proxy total in-flight")], 0, y))
panels.append(timeseries(
    "Request rate per serving lane (LiteLLM view)",
    "Which engine lane LiteLLM actually routed to, derived from deployment api_base's service "
    "hostname - reliable where requested_model is a catalogue alias (google/gemma-4-12b-it) "
    "rather than the service name.",
    [("sum by (lane) (%s)" % lane("litellm_deployment_total_requests_total", rate=True), "{{lane}}")],
    12, y))
y += 8

# ---- Row: KV cache ---------------------------------------------------------
panels.append(row("KV cache: usage & hit rate", y)); y += 1
panels.append(timeseries(
    "KV cache usage (% of pool)",
    "vLLM and Radiance only: kv_cache_usage_perc is the fraction of the KV block pool in use. "
    "llama.cpp has NO KV-occupancy metric at all - it pre-allocates slots - so llama.cpp lanes "
    "legitimately never appear here.",
    [("max by (service) (vllm:kv_cache_usage_perc{%s=~\"$lane\"})" % "service", "{{service}}")],
    0, y, unit="percentunit"))
panels.append(timeseries(
    "Prefix-cache hit rate (unified)",
    "One curve per lane from whatever the engine reports: Radiance/vLLM expose gpu_prefix_cache_hit_rate "
    "or hits/queries counters; llama.cpp derives it from prompt_tokens_cached_total against "
    "cached+uncached prompt tokens (its prompt_tokens_total EXCLUDES cached tokens, so the denominator "
    "has to add them back).",
    [('max by (service) (vllm:gpu_prefix_cache_hit_rate{%s=~"$lane"})\n'
      'or (\n'
      '  sum by (service) (rate(llamacpp:prompt_tokens_cached_total{%s=~"$lane"}[$__rate_interval]))\n'
      '  / clamp_min(\n'
      '      sum by (service) (rate(llamacpp:prompt_tokens_cached_total{%s=~"$lane"}[$__rate_interval]))\n'
      '    + sum by (service) (rate(llamacpp:prompt_tokens_total{%s=~"$lane"}[$__rate_interval])), 1)\n'
      ')\n'
      'or (\n'
      '  sum by (service) (rate(vllm:prefix_cache_hits_total{%s=~"$lane"}[$__rate_interval]))\n'
      '  / clamp_min(sum by (service) (rate(vllm:prefix_cache_queries_total{%s=~"$lane"}[$__rate_interval])), 1)\n'
      ')' % (("service",) * 6), "{{service}}")],
    12, y, unit="percentunit"))
panels.append(timeseries(
    "KV tokens in use (Radiance)",
    "kv_cache_usage_perc x kv_cache_max_tokens gives absolute context tokens resident in the KV "
    "cache. Radiance publishes the capacity gauge directly (486788 on flashnext-iggy at 262k "
    "context); vLLM carries capacity in the vllm:cache_config_info info-metric labels, which are "
    "gone when the lane is suspended, so this panel is Radiance-shaped on purpose.",
    [("max by (service) (\n"
      "  vllm:kv_cache_usage_perc{%s=~\"$lane\"}\n"
      "  * on (service, pod, instance) group_left () radiance:kv_cache_max_tokens{%s=~\"$lane\"}\n"
      ")" % ("service", "service"), "{{service}} tokens")],
    0, y, unit="none"))
panels.append(timeseries(
    "llama.cpp context pressure (largest sequence)",
    "n_tokens_max: largest observed prompt+generation sequence since start. llama.cpp's closest "
    "analogue to KV pressure - compare against the lane's --ctx-size (65536 gemma, 393216 muse). "
    "Approaching ctx means slot eviction, not a KV percentage.",
    [("max by (service) (llamacpp:n_tokens_max{%s=~\"$lane\"})" % "service", "{{service}}")],
    12, y, unit="none"))
panels.append(timeseries(
    "Radiance cache internals: evictions & preemptions",
    "prefix_cache_evictions_total is attention blocks pushed out of the prefix cache; "
    "num_requests_preempted counts requests kicked back for recompute. Both are Radiance-only "
    "and both explain a hit-rate drop better than the ratio itself.",
    [("sum by (service) (rate(radiance:prefix_cache_evictions_total{%s=~\"$lane\"}[$__rate_interval]))" % "service",
      "{{service}} evictions/s"),
     ("sum by (service) (rate(radiance:prefix_cache_ckpt_evictions_total{%s=~\"$lane\"}[$__rate_interval]))" % "service",
      "{{service}} ckpt evictions/s"),
     ("max by (service) (radiance:num_requests_preempted{%s=~\"$lane\"})" % "service", "{{service}} preempted")],
    0, y))
panels.append(timeseries(
    "vLLM/Radiance preemptions",
    "A preempted request must recompute its prompt - preemption spikes alongside KV usage near 1 "
    "mean the lane is overcommitted on context.",
    [("sum by (service) (rate(vllm:num_preemptions_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}}")],
    12, y))
y += 8

# ---- Row: Cache hit accounting at the router --------------------------------
panels.append(row("Speculative decoding & router-side cache accounting", y)); y += 1
panels.append(timeseries(
    "Speculative-decoding acceptance",
    "Fraction of draft tokens accepted. Radiance: draft_acceptance_ratio gauge; llama.cpp and vLLM: "
    "accepted/draft counter pairs. Below ~0.5 the drafter is costing more than it saves; muse-glimmer "
    "runs a dflash drafter, flashnext-iggy runs --num-speculative-tokens 3.",
    [('max by (service) (radiance:draft_acceptance_ratio{%s=~"$lane"})\n'
      'or (\n'
      '  sum by (service) (rate(llamacpp:spec_decode_num_accepted_tokens_total{%s=~"$lane"}[$__rate_interval]))\n'
      '  / clamp_min(sum by (service) (rate(llamacpp:spec_decode_num_draft_tokens_total{%s=~"$lane"}[$__rate_interval])), 1)\n'
      ')\n'
      'or (\n'
      '  sum by (service) (rate(vllm:spec_decode_num_accepted_tokens_total{%s=~"$lane"}[$__rate_interval]))\n'
      '  / clamp_min(sum by (service) (rate(vllm:spec_decode_num_draft_tokens_total{%s=~"$lane"}[$__rate_interval])), 1)\n'
      ')' % (("service",) * 5), "{{service}}")],
    0, y, unit="percentunit"))
panels.append(timeseries(
    "Radiance acceptance by draft position",
    "Conditional acceptance at each draft position given all earlier ones were taken - where the "
    "drafter starts losing the thread. Radiance-only.",
    [("max by (service, position) (radiance:draft_position_acceptance_ratio{%s=~\"$lane\"})" % "service",
      "{{service}} pos {{position}}")],
    12, y, unit="percentunit"))
panels.append(timeseries(
    "Router-reported prompt-cache reads (LiteLLM usage accounting)",
    "NOT KV cache: these are usage.prompt_tokens_details reported by the upstream per response. "
    "For local OpenAI-compatible lanes the engine fills this in, so it cross-checks the engine-side "
    "hit rate above; for API lanes it is the provider's own prompt cache.",
    [("sum by (requested_model) (rate(litellm_input_cached_tokens_metric_total[$__rate_interval]))", "{{requested_model}} cached-in"),
     ("sum by (requested_model) (rate(litellm_provider_cache_read_input_tokens_metric_total[$__rate_interval]))", "{{requested_model}} provider-read")],
    0, y, unit="none"))
panels.append(timeseries(
    "Radiance cached-token sources",
    "attn_cached_tokens_total (paged attention prefix cache) vs linear_cached_tokens_total "
    "(linear-state checkpoints) against prefill_tokens_total - which of the two cache tiers is "
    "actually paying on a hybrid model. Radiance-only.",
    [("sum by (service) (rate(radiance:attn_cached_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} attn cached"),
     ("sum by (service) (rate(radiance:linear_cached_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} linear ckpt"),
     ("sum by (service) (rate(radiance:draft_refill_tokens_total{%s=~\"$lane\"}[$__rate_interval]))" % "service", "{{service}} draft refill")],
    12, y, unit="none"))
y += 8

# ---- Row: Engine-side latency ------------------------------------------------
panels.append(row("Engine-side latency (vLLM-compat surface: vLLM + Radiance)", y)); y += 1
panels.append(timeseries(
    "Time to first token p95",
    "Histogram exists on the vLLM surface, which Radiance re-exports, so both appear; llama.cpp "
    "lanes have no TTFT histogram - use the LiteLLM dashboard's TTFT panel for those. Lanes with "
    "no streamed responses in-window drop out (bucket-rate > 0 filter) instead of drawing a NaN.",
    [(histogram('vllm:time_to_first_token_seconds_bucket{%s=~"$lane"}' % "service"), "{{service}}")],
    0, y, unit="s"))
panels.append(timeseries(
    "Inter-token latency p95",
    "Stream-level decode cadence at the engine, before proxy buffering. The inverse is per-stream "
    "tok/s without the batch-division guesswork.",
    [(histogram('vllm:inter_token_latency_seconds_bucket{%s=~"$lane"}' % "service"), "{{service}}")],
    12, y, unit="s"))
panels.append(timeseries(
    "Scheduler queue wait p95",
    "Time a request sat in the engine scheduler before prefill - the KV/concurrency-bound signal "
    "for gaming-box lanes sharing a GPU. vLLM-only today: Radiance exports the other vLLM-compat "
    "families but not request_queue_time, so this stays empty until a real vLLM lane runs "
    "(qwen3-8-27b is suspended). Radiance's equivalent is http_queue_depth + its engine_step "
    "step-time counters.",
    [(histogram('vllm:request_queue_time_seconds_bucket{%s=~"$lane"}' % "service"), "{{service}}")],
    0, y, unit="s"))
panels.append(timeseries(
    "Proxy per-output-token latency p95 per lane",
    "litellm_deployment_latency_per_output_token: what LiteLLM measured between the backend's "
    "first and last token. Covers llama.cpp lanes too, at the cost of proxy-side measurement noise.",
    [(lane_histogram("litellm_deployment_latency_per_output_token_bucket"), "{{lane}}")],
    12, y, unit="s"))
y += 8

# ---- Row: Engine coverage notes ---------------------------------------------
panels.append(row("Coverage: what each engine does NOT expose", y)); y += 1
panels.append({
    "id": nid(), "type": "text", "title": "Engine metric coverage",
    "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
    "options": {"mode": "markdown",
                "content": (
                    "Derived from the live `/metrics` endpoints and the 197 series the "
                    "`llmkube-inference` PodMonitor scrapes, not from documentation.\n\n"
                    "| Capability | llama.cpp (`llamacpp:`) | vLLM (`vllm:`) | Radiance (`radiance:` + vLLM-compat) |\n"
                    "|---|---|---|---|\n"
                    "| Prompt speed | `prompt_tokens_seconds` gauge, resets per scrape | derive: `rate(prompt_tokens_total)` | native `prefill_tokens_per_second` |\n"
                    "| Generation speed | `predicted_tokens_seconds` gauge, resets per scrape | derive: `rate(generation_tokens_total)` | native `decode_tokens_per_second` |\n"
                    "| Concurrency | `requests_processing` slots + `requests_deferred` | `num_requests_running` / `waiting` | `http_queue_depth` + compat `num_requests_*` |\n"
                    "| KV usage % | **absent** (pre-allocated slots; watch `n_tokens_max` vs ctx-size) | `kv_cache_usage_perc` | `kv_cache_usage_perc` (compat) x `kv_cache_max_tokens` |\n"
                    "| Cache hit rate | derive from `prompt_tokens_cached_total` | `gpu_prefix_cache_hit_rate`, hits/queries | compat hit-rate + `linear_prefix_cache_hit_rate` |\n"
                    "| TTFT / ITL | **absent** (use LiteLLM proxy histograms) | native histograms | compat histograms |\n\n"
                    "**Scrape precondition:** llama.cpp lanes need `--metrics` (all current ones have it); "
                    "Radiance exports its own and vLLM-compat families unconditionally. "
                    "A lane with no series here is unsraped or scaled to zero, not idle.\n\n"
                    "**LiteLLM contributes none of these**: the proxy exports request/token/spend/latency "
                    "families only (verified against 81 live families, v1.97.0). KV-cache, slots and "
                    "engine tok/s exist only at the engines. Its `*_cached_tokens` counters are provider "
                    "usage accounting, not KV occupancy. Spend/cost stays on the LiteLLM dashboard.\n\n"
                    "**`runtime` label is not an engine label** - it reports `generic` for every "
                    "InferenceService that overrides container args. Engine identity above comes from "
                    "metric-family presence."
                )},
})
y += 10

def layout(panels):
    """Recompute gridPos: rows flow top-to-bottom, panels pack left-to-right.

    Rows are 1-unit banners; non-row panels fill the current grid line until the
    next one would exceed w=24, then a new line starts. This packs the four
    w=6 stats onto one line and pairs of w=12 panels onto one line without any
    hand-tracked y bookkeeping.
    """
    y = 0
    x = 0
    line_h = 0
    for p in panels:
        g = p["gridPos"]
        if p["type"] == "row":
            y += line_h
            x, line_h = 0, 0
            g.update({"x": 0, "y": y, "w": 24, "h": 1})
            y += 1
            continue
        if x > 0 and x + g["w"] > 24:
            y += line_h
            x, line_h = 0, 0
        g["x"] = x
        g["y"] = y
        x += g["w"]
        line_h = max(line_h, g["h"])
        if x >= 24:
            y += line_h
            x, line_h = 0, 0
    return panels


panels = layout(panels)

dash = {
    "title": "LLM Serving Engines",
    "uid": "cogito-llm-serving",
    "tags": ["llm", "llmkube", "inference"],
    "editable": True,
    "graphTooltip": 1,
    "timezone": "browser",
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "schemaVersion": 39,
    "version": 1,
    "templating": {"list": [
        {"name": "datasource", "label": "Datasource", "type": "datasource",
         "query": "prometheus", "current": {}, "hide": 0, "refresh": 1},
        {"name": "lane", "label": "Serving lane", "type": "query",
         "datasource": DS,
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"},
         "refresh": 2, "sort": 1, "hide": 0,
         # Regex-anchored metric-family selector instead of a job+up selector:
         # the engine detector has to match the panels' own definition of a lane.
         "query": "label_values(%s, service)" % LANE_MATCH},
    ]},
    "annotations": {"list": []},
    "panels": panels,
}

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/llm-serving.json"
    with open(out, "w") as f:
        json.dump(dash, f, indent=2)
        f.write("\n")
    print(f"wrote {out}: {len(panels)} panels, {sum(1 for p in panels if p['type'] != 'row')} visual panels")
