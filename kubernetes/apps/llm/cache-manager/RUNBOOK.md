# Cache Manager Runbook

## M6 standalone ownership

`cache-manager` is the standalone cache lifecycle service. Its ServiceMonitor
is the only source of `llm_cache_manager_*` telemetry; the proxy no longer
forwards those metrics.

Watch filesystem use and hydration/archive activity in **LLM Model Cache**.
On `LLMHotModelCacheNearlyFull`, verify inactive artifacts can be evicted
before the admission limit. On `LLMModelCacheHydrationFailure`, inspect the
cache-manager Pod logs and artifact manifests; incomplete staged artifacts must
not be exposed to a runtime.

Rollback configuration through Cogito Git and Flux. Do not remove cache files
manually while a cache-manager operation is active.
