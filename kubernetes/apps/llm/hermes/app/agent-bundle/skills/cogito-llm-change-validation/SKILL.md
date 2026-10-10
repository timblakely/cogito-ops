---
name: cogito-llm-change-validation
description: Use when editing cogito's llm/dreamcast k8s manifests.
---

# Validating cogito LLM-stack changes (home/tim/git/cogito)

Gates for changes under `kubernetes/apps/llm/**` or `dreamcast/session-config`:

1. `scripts/validate-llm-catalogue.py --self-test` — run with the repo venv:
   `/home/tim/git/cogito/.venv/bin/python scripts/validate-llm-catalogue.py --self-test`
   (system/hermes python lack pyyaml; venv has it after one `pip install pyyaml`).
   Checks key scopes → modelNames, context mirror (maxInputTokens == backend
   contextSize/maxModelLen, or annotate `cogito.dev/context-budget: deliberate`).
   Removing a model from a Kustomization REQUIRES removing it from every
   LiteLLMVirtualKey `models:` scope in the same change.
2. `kustomize build kubernetes/apps/llm/llmkube/resources` — standalone-clean.
   For litellm/app: copy to /tmp, `sed 's/\${APP}/litellm/g'` all yamls, then build.
   The resources kustomization lists files EXPLICITLY: a new YAML in
   resources/ is dead until added to its `resources:` list.
   Mise shims for kubectl/kustomize/gh/jj can be inactive ("No version is
   set for shim"); call binaries directly under
   ~/.local/share/mise/installs/... instead of `mise use`.
3. Fastest real gate: `kubectl apply --dry-run=server` on the rendered docs of
   just the touched objects (export KUBECONFIG=/home/tim/git/cogito/kubeconfig).
   Exercises CRD schema + llmkube webhook admission; persists nothing.
4. CI parity flux-local (`.github/workflows/flux-local.yaml`, image
   ghcr.io/allenporter/flux-local v8.4.0) via podman requires ALL of:
   - workspace copy under /var/tmp (SELinux: `:z` on $HOME fails; scratch dirs
     with mode 700 break container traversal), `chmod -R a+rwX`, keep age.key
   - `-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory
     -e GIT_CONFIG_VALUE_0=/github/workspace` (root-in-container git distrust)
   - deselections go through `PYTEST_ADDOPTS="--deselect=kubernetes/flux::NAME::ns/NAME"`
     — there is no --skip-tests flag
   - the llm/dreamcast kustomization tests fail even on a PRISTINE baseline
     copy under podman ("Invalid stdin cannot be passed to build command") —
     environmental; diff failures against a baseline copy (jj file show -r
     <main-rev> -- path restores originals; `--` needed or path is parsed as
     a rev) before blaming the change.

# Preemption facts (Amnesia gaming GPU)

- gaming-interactive=20000 PreemptLowerPriority (dreamcast/session-config);
  llmkube classes: critical 1e6/high 1e5/normal 1e4/low 1e3/batch 100.
  InferenceService `priority: low` → llmkube-low. Direwolf App template
  `spec.template.spec.priorityClassName` IS propagated to live session pods.
- Amnesia device plugin time-slices ONE 5070 Ti into 2 units (replicas:2,
  family blackwell, `nvidia.com/device-plugin.config: gaming.yaml`); a full
  Steam session needs both. A pending gaming pod preempts lower-priority GPU
  pods that hold them.
- LLMKube `spec.suspend: true` is the field-safe off switch (operator co-owns
  .spec.replicas); Flux GC on removal from a Kustomization deletes PVCs —
  archive weights BEFORE letting a Kustomization removal through Flux.
- `pvc://` Model sources mount the claim at /model-source read-only with NO
  init container (vision-cpu pattern); shared llmkube-model-cache PVC is
  pinned to iggy — don't route Amnesia/Kristeva models through it.
- Terminal output masks literal `***`-looking strings: copying an apiKey line
  from terminal output into a new file wrote a literal `***`. Patch such
  values programmatically from the source file without echoing them.

# A380 / llama.cpp intel runtime facts

- Kristeva Arc A380 VRAM usage: NOT in sysfs (Talos i915/6.18 has no mem_info_vram_*), not in
  Prometheus (no intel exporter; dcgm is nvidia-only, pinned to iggy), not via Level Zero sysman
  (loader 1.27 + driver 1.15 reject zesDeviceEnumMemoryModules even after zeContextCreate).
  Authoritative source: kernel TTM debugfs via a node debug pod (busybox, /host mount):
  `cat /host/sys/kernel/debug/dri/0000:07:00.0/gem_info` -> `total: 6088MiB, free: NNNN MiB`
  and `local0 usage:` bytes; `clients` file there lists per-process llama-server handles.
- Kristeva GPUs: A380 = PCI 0000:07:00.0 (8086:56a5, card0 in pods); RTX 3090 = 02:00.0 (nvidia).
  NFD label intel.gpu-type=A380 maps device id 56a5. llama.cpp server-intel pods see the GPU in
  Level Zero only with ZE_ENABLE_PCI_ID_DEVICE_ID=1; plain loader init enumerates CPU-only.

- ghcr.io/ggml-org/llama.cpp:server-intel is a FLOATING tag whose amd64
  content can lag the tag push: floor pods ran build b10548 (Aug 21) while
  the tag pointed at b11459 (Oct 7). New architectures need the digest pinned
  (sha256:6ccaeb... = b11459 = first intel build with embeddinggemma2 via
  upstream 4fbc76de). Probe tag content via ghcr token API + config blob
  label org.opencontainers.image.version.
- embeddinggemma-2 Q8_0 GGUF: arch `gemma-embedding2`, 271M text-only lane
  (~310MB), 768d out, GGUF context_length=262144 but published at 8k — serve
  ctx 8192; pooling_type=1 (LAST) is in the GGUF, no --pooling flag needed.
  Multimodal encoders (mmproj) NOT servable via llama.cpp OpenAI API.
- Shadow/A/B endpoints deliberately skip LiteLLMModel wiring — catalogue
  validator only counts LiteLLM backends, so no key-scope change is needed
  and the `embedder` alias stays on bge-m3 until an explicit switch.

# Grafana dashboards in this repo

Every app directory is its own Flux Kustomization object in the app namespace
(`llmkube`, `litellm`, ... -> `apps/<app>/app`, plus `<app>-resources`).
Reconcile EVERY KS whose path contains a file you changed or half the change
sits unreconciled; see `references/llmkube-tooling.md`. Dashboards ship as
configMapGenerator + fixed name (`disableNameSuffixHash`) +
`kustomize.toolkit.fluxcd.io/substitute: disabled` + GrafanaDashboard CR with
configMapRef (litellm and dcgm pattern). That annotation is load-bearing: the
KS postBuild envsubst would otherwise eat the `${datasource}` / `${__range}` /
`$__rate_interval` Grafana tokens in dashboard JSON. After Flux applies,
confirm via the Grafana API, not just CR status. Engine-level metrics (tok/s,
concurrency, KV cache) are NOT in LiteLLM — see skill
`llm-engine-metrics-dashboard`.
