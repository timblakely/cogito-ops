# LLM cache-manager

This app is the active M5 standalone cache-manager. `vllm-proxy` now uses
`CACHE_MANAGER_URL=http://cache-manager:8090`; its former localhost sidecar has
been removed. The ServiceMonitor continues to expose the manager's health and
cache metrics.

`llm-huggingface-cache` and `laguna` are hostpath `ReadWriteOnce` claims. The
Deployment must remain a single `Recreate` replica on `iggy`, colocated with
vLLM. Moving it to another node risks an RWO mount failure.

The proxy runs with `ENABLE_DEPLOYMENT_MUTATIONS=false`; the operator owns the
canonical Gemma activation and has verified a hot cache ensure through this
Service. TODO: add runtime/container integration coverage for successful and
failed transitions, including cache-manager behavior and rollback.
