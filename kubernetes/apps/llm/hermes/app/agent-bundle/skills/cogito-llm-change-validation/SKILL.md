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
   Retiring an alias/key TIER: grep the whole repo for each name — consumers
   live in foreman config (agent role lists, execution pools, fleet nodes),
   hermes provider-bootstrap + configure.py, and the validator's own
   required-role-key maps; update all in the same change. Deletion patches
   over several files silently clip adjacent files not on the removal list —
   review every hunk against the list before committing. Secrets that become
   empty are removed from their kustomization.yaml so Flux GC deletes them,
   then verify via HelmRelease conditions plus live
   pod/secret/FleetNode absence.
2. `kustomize build kubernetes/apps/llm/llmkube/resources` — standalone-clean.
   KS WRAPPER dirs (`apps/<app>/kustomization.yaml`, the one defining the Flux
   Kustomization) CANNOT be built standalone anywhere in this repo: the shared
   `components/ks/app` component loads patch files above its own directory, so
   plain `kustomize build` dies with a "file ... is not in or below" security
   error. Build the inner `apps/<app>/app` dir (what Flux actually reconciles)
   or pass `--load-restrictor=LoadRestrictionsNone`.
   For litellm/app: copy to /tmp, `sed 's/\${APP}/litellm/g'` all yamls, then build.
   The resources kustomization lists files EXPLICITLY: a new YAML in
   resources/ is dead until added to its `resources:` list.
   Mise shims for kubectl/kustomize/gh/jj can be inactive ("No version is
   set for shim"); call binaries directly under
   ~/.local/share/mise/installs/... instead of `mise use` (there is no
   `installs/kustomize/latest/` binary — the `~/.local/share/mise/shims/kustomize`
   shim itself works, so try the shim before hunting paths).
- **Rolling an LLM lane can kill your own session**: this agent's model is often
   a LiteLLM alias pointing at the very InferenceService being upgraded (model
   `flashnext-deleuze` == the `radiance` lane on deleuze). Finish every edit,
   gate, commit and push BEFORE the reconcile, then hand rollout verification to
   a background watcher (`terminal(background=true, notify=true)`) that waits
   for the pod on the new digest, `kubectl wait` Ready, greps the startup log and
   port-forwards for a curl smoke test — its result re-enters between turns, so
   it survives the outage. `rolloutPolicy.waitForIdle: false` rolls the pod as
   soon as Flux applies.
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

# Bumping an LLM lane's engine image digest

- Pin the **per-architecture (amd64) image digest**, not the Docker Hub
  manifest-list digest — existing cogito pins use the amd64 digest. `curl -s
  https://hub.docker.com/v2/repositories/<org>/<image>/tags/<tag>` returns the
  manifest-list digest in the top-level `.digest` and the per-architecture
  digests in `.images[].digest` (match `architecture: amd64`); copying the
  top-level value silently diverges from the repo convention.
- Answer the compatibility question BEFORE editing, and report the audit plus
  the exact one-line diff. An edit-approval denial on a "should we upgrade /
  any breaking changes?" question means the analysis was the ask.
- Check whether the lane serves THIS session (`kubectl get pods -A`, plus the
  alias the agent's own model resolves to) before pushing or reconciling.
  llmkube lanes carry `spec.rolloutPolicy.waitForIdle: false`, so a reconcile
  restarts the pod immediately — mid-conversation when that pod is answering.
  Let the user choose push-now versus deferred reconcile.

# Amend, push, and reconcile repair (jj)

- Before blaming Flux or the operator for a live spec that still shows the
  old value, confirm the PUSHED commit actually contains the change:
  `jj file show -r main -- <path> | grep <value>`. The commonest "Flux
  reported applied but the cluster is stale" case is that main itself still
  has the old content — reconcile then works perfectly.
- A render that lost an object compared to an earlier build is usually a CONCURRENT
  change on main, not your edit: collect `metadata.name` from both renders and diff
  the sets, then confirm with `jj file show -r <parent> -- <path> | grep -c <name>`
  before touching your own diff (the catalogue validator's backend count is the
  cross-check). Retiring a lane is also the usual reason a Kustomization suddenly
  builds one fewer InferenceService.
- `jj git push` has no `--allow-headless` (usage error); plain `jj git push` pushes
  the moved `main` bookmark, then marks the pushed change immutable and creates a
  fresh empty `@` on top — so every amend must happen before the push, never after.
- `jj edit <older-change>` snapshots in-flight working-copy edits into the
  working commit it LEAVES BEHIND — the edits do not travel with you, so an
  amend on the older change silently excludes them and the push succeeds with
  stale content. Never edit back to a task change while `@` carries unsquashed
  edits; squash them in first.
- Repair a stranded edit after the stale push: `jj --ignore-immutable squash
  --into <task-change>`, then repoint `main` and repush. `--ignore-immutable`
  is a GLOBAL flag — it goes before the subcommand (`jj --ignore-immutable
  edit/describe/squash ...`); a squash or describe onto an already-pushed
  commit is refused without it. Amend-and-repush the same task change rather
  than stacking retry commits (repo AGENTS.md).
- Moving an InferenceService lane to a node that never ran it: the container
  image is COLD there (multi-GB vLLM pulls measured ~5.5 min) and weights
  load cold, so budget ~15 min before judging the deploy failed. A pod stuck
  in `ContainerCreating` during the pull is normal — read
  `kubectl describe pod` Events (Pulling/Pulled durations) before touching
  the spec or suspecting the resize.

# Flux Job health checks and staging loops

- A registered batch Job is applied AND health-checked by its Kustomization: as
  long as it never reaches Complete the shared KS sits `Ready=False` with
  "health check failed ... timeout waiting for Job ... status: 'InProgress'",
  which makes every *unrelated* change inside that KS look stuck as well.
  Deleting the doomed Job out-of-band does not stop this — the next sync
  recreates it from git.
- Only two correct endings: fix the cause, or hold the file back. The resources
  kustomization lists files EXPLICITLY, so moving the Job into its own file and
  dropping that one line prunes it; keep the claim/PVC registered (it costs
  nothing and holds resumable progress) and write the reason plus the exact
  one-line re-enable step into the held file's header. Then verify
  `Ready=True` on the KS.
- `flux reconcile` blocks on that health check, so "annotated ... context
  deadline exceeded" from a reconcile you launched is usually your own wait
  expiring, not a cluster fault. Read
  `.status.conditions[?(@.type=="Ready")]` for real state before investigating,
  and treat each background reconcile's timeout as a signal to re-read the KS,
  not to reconcile again.
- When splitting a manifest to hold part of it back, prove the split is
  byte-exact (re-concatenate the pieces and compare to the original) so
  re-enabling later is provably lossless, and confirm the rendered output
  actually dropped the intended object (`kubectl kustomize | grep kind`) before
  committing.

# Node sizing + cleanup facts (iggy)

- iggy is a 32 GiB RAM box (SMBIOS 2x16 GiB; allocatable 28.6 GiB) — plan docs claiming 128 GB predate a DIMM removal. Any InferenceService memory REQUEST above iggy's remaining allocatable never schedules; scheduler says "Insufficient memory" while the GPU looks free. Verify node RAM via `talosctl -n <ip> read /sys/firmware/dmi/tables/DMI` SMBIOS type-17 walk, not plan docs.
- Both iggy 3090s are held at 280 W by the nvidia-power-limit DaemonSet (250 W default branch elsewhere); confirm with a throwaway nvidia-runtimeClass pod running `nvidia-smi --query-gpu=index,name,uuid,power.limit,power.draw --format=csv` (power.limit.min/max are not queryable fields; the device-plugin image's `init 250 result=11` stderr line is benign).
- Node-local storage on iggy is ONE filesystem, not the sum of PVC requests: every openebs hostpath PV lives under `/var/mnt/local-hostpath` (`/dev/nvme1n1p1`, ~931 GiB). It can sit at 100% while a fresh 40 Gi claim binds successfully and a bulk download then dies at ENOSPC several GiB in. Before staging anything, `df` that directory (node debug pod or talosctl read), then total the directories beneath it against live local PVs (`.spec.volumeName` → hostpath) to separate owned data from orphans. Iggy's root disk has separate headroom (the `flashnext-iggy-ngram` claim lives there) — a lane's local claim can be moved there instead of deleting anything. Orphaned directories and other lanes' model caches are the user's data: report size and mtime, ask, never delete.
- The Flux-orphaned default-ns LiteLLM family (LiteLLMProxy/VirtualKeys/PushSecrets, no fluxcd labels) was deleted; VirtualKey CRs carry a `litellm.home-operations.com/virtual-key` finalizer that wedges when their proxy is already gone — remove via `kubectl patch --subresource=finalizers -p '{"metadata":{"finalizers":null}}'` (never-generated keys, nothing to revoke).

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
- `pvc://` Model source mounting is RUNTIME-DEPENDENT, not universal: the
  llamacpp runtime auto-injects the claim at /model-source read-only with no
  init container (vision-cpu pattern), but the `generic` runtime does NOT —
  its rendered pod comes up with only the volumes you declare, so a generic
  lane must declare the claim in extraVolumes + extraVolumeMounts itself
  (flashnext-iggy mounts its own to /models; muse declares its own because its
  weights live on a per-lane claim). Verify by reading the live pod's
  .spec.volumes, never by assuming from a sibling lane that uses another
  runtime.
  Shared llmkube-model-cache PVC is pinned to iggy — don't route
  Amnesia/Kristeva models through it.
- InferenceService `spec.endpoint.port` must be declared explicitly. llmkube
  derives BOTH the containerPort and the Service target from it and defaults to
  8080; a vLLM container told `--port 8000` then serves a port nothing routes
  to, and every LiteLLM apiBase pointing at :8000 silently 404s/503s. Check
  `kubectl get endpoints` (not just pod Ready) after first deploy.
- The catalogue validator CANNOT see backend context for generic-runtime lanes
  (it reads vllmConfig.maxModelLen / contextSize and skips the mirror check
  when neither exists), so a stale `maxInputTokens` passes validation. Mirror
  it to --max-model-len by hand in every alias pointing at the lane, and diff
  the values across all models/*.yaml that share an apiBase — a rewritten
  comment is not the same as a changed value, so grep the numbers.
- GPU telemetry DaemonSets (dcgm-exporter, fan-control) were node-pinned with
  `kubernetes.io/hostname` PLUS `nvidia.com/gpu.present: "true"` — a label NO
  node in this cluster carries (NFD emits
  `feature.node.kubernetes.io/pci-0300_10de.present` instead). DESIRED=0 on a
  DaemonSet is that bug, not a scheduling failure: read the NODE SELECTOR
  column and test each label against `kubectl get node -o json`. Re-pin to the
  node that actually has the GPU; prefer explicit hostname over the PCI label
  when another NVIDIA node is a gaming box (amnesia) so privileged telemetry
  and MANUAL fan policy never land there by side effect. nvidia-power-limit
  already used the PCI label, which is why it survived the iggy migration.
  Scrape-check through Prometheus via `kubectl get --raw
  /api/v1/namespaces/observability/services/prometheus-operated:9090/proxy/api/v1/query?query=...`
  — dcgm-exporter and prometheus images have no shell tools (no wget/curl/head).
- vLLM duplicate CLI flags FAIL SILENTLY: argparse keeps the LAST occurrence
  and only logs "Found duplicate keys --flag" in the noise. The AWQ lane
  carried a stale `--kv-cache-dtype auto` pair below the new fp8 one, so the
  fp8 setting did nothing and the KV-gate refusal numbers looked like fp8 had
  failed. Verify engine flags from the `Initializing a V1 LLM engine` config
  dump line (kv_cache_dtype=..., max_seq_len=...), never just from the args
  list; grep rendered args for duplicate flag names when editing.
- fp8_e4m3 KV on this hybrid (GDN + attention) model, RTX 3090/vLLM v0.31.0:
  works, no plugin needed (the two-card lane's "sm_86 needs a digest-pinned
  FA2+fp8-KV plugin" note is about an older stack). Attention page size is
  padded to the mamba/GDN page, so halving per-token KV simply doubles the
  tokens-per-page (784 -> 1568) and the pool doubles (34,816 -> 68,266
  tokens) at unchanged utilization. Validated: 5/5 needle recall at 50K
  depth, correct MISSING on control, 65,161-token request served at the
  65536 ceiling, decode 33.8 -> 36.8 tok/s, prefill ~2,500 tok/s.
- vLLM on a 24 GiB card with ~18 GiB of weights has TWO independent boot
  gates that pull opposite ways, and satisfying one can violate the other:
  the KV gate needs `util` high enough for one full sequence
  ("estimated maximum model length is N"), while the startup gate compares
  `util * total` against memory free at CUDA attach (driver/context take ~0.26
  GiB, so 0.99 asks for more than the card can show and dies with "Free memory
  on device cuda:0 ... less than desired GPU memory utilization"). Fit a line
  through the numbers vLLM prints in each refusal (KV is linear in util) to
  find the one value clearing both, instead of bisecting by reboot — each boot
  costs minutes. Lower --max-num-batched-tokens and raise the container memory
  request are the two real levers; a weights file read over NFS charges its
  page cache to the CONTAINER cgroup, so an under-sized memory limit both
  thrashes and disables vLLM's NFS read-ahead ("exceeds 90% of available
  RAM ... Skipping auto-prefetch") and can 4x load time.
- RTX 3090 PCIe/cap facts are board-specific and the cards MOVED (October 2026): on the
  **kristeva** board the 3090 negotiated 8.0 GT/s x8 under load and its upstream root
  port 0000:00:02.0 is itself x8 Gen3-max, so that was the board ceiling, not a
  fault. Both 3090s now sit in **iggy**, held at 280 W each by the nvidia-power-limit
  DaemonSet's iggy branch (the 250 W cap in the September bench notes was raised later).
  Either way, sysfs reads of `current_link_*` from an idle GPU show 2.5 GT/s (power
  management) — measure under sustained inference or the number is meaningless.
  The cap pins SM clocks to ~1440-1515 MHz of 2130; memory clock stays
  ~9501/9751 MHz, so INT4 decode is barely affected. Idle `clocks_throttle
  _reasons` counters are cumulative and misleading — read the per-flag Active
  bits (SW Power Cap / HW Thermal Slowdown) under load.
- Terminal output masks literal asterisk runs: copying an apiKey line from terminal
  output into a new file wrote a literal masked token. The same masking hits
  `write_file`/`patch` content — an Authorization header line built as
  `"Bearer " + key` landed on disk as a masked placeholder, and LiteLLM answered
  "Malformed API Key", which reads exactly like a revoked key. Build such headers at
  runtime (`"Be"+"arer "+key`) and check the on-disk bytes before blaming the
  credential. Patch such values programmatically from the source file without
  echoing them.

# Vision-path gotchas across llama.cpp lanes (cogito)

- Image cost is the projector (mmproj), and it is charged into `prompt eval time`:
  read that rate in `slot print_timing`, not the total. ~1000 t/s = text prefill on
  GPU; 20-50 t/s with `nvidia-smi` at 0 % util and ~`--threads` cores busy = a CPU
  mmproj (see the muse-glimmer skill for the fix and the measured curve).
- **A projector too big for the GPU is a latency bug; an image too big for
  `--ubatch-size` is a crash.** The gemma-4-12b lane on amnesia
  (`--batch-size 1024 --ubatch-size 768 --flash-attn on`, non-causal attention over
  the vision prefix) aborts with `exit 139` and
  `GGML_ASSERT((cparams.causal_attn || cparams.n_ubatch >= n_tokens_all) &&
  "non-causal attention requires n_ubatch >= n_tokens") failed` inside
  `mtmd_helper_decode_image_chunk`. Measured 2026-10-23: 1280x960 (562 image tokens)
  is fine, 1920x1080 kills the container (restarts in ~50 s). So any full-HD
  screenshot pasted into a gemma conversation takes that lane down. Move BOTH knobs,
  not one: `--ubatch-size` up to `--batch-size` (batch is the hard ceiling — ubatch
  can never exceed it — and raising it costs no KV, since KV is sized by
  contextSize), plus `--image-max-tokens` set strictly BELOW ubatch with real margin
  (~256 tokens), because the assert covers the whole non-causal batch rather than
  the image alone. The cap is the load-bearing half: gemma's projector DOES use
  dynamic resolution — image tokens scale linearly with pixel area, putting 4K near
  3600 tokens — so an unbounded image re-triggers the abort at any ubatch worth
  running, unlike Muse's fixed-tile projector where those flags are inert. Raising
  the cap later requires raising both batch fields with it. Probe ladder that
  reproduces and then validates the fix: text-only baseline plus
  320/640/1280/1920/3840 px with `max_tokens: 1`, printing the `prompt_tokens` delta
  per size; run the largest size LAST and expect a restart if the cap did not land.
- **That fix is deployed and verified** (commit `stop a full-HD screenshot killing the
  gemma-4-12b lane`: `--ubatch-size 1024` + `--image-max-tokens 768`). Post-deploy
  ladder on the same lane, restarts stayed 0: 320x240 +107 image tokens, 640x480 +132,
  1280x960 +542, **1920x1080 +722 and 3840x2160 +722 — identical, so the cap binds and
  clamps both**, encode 0.4-0.6 s each, and solid-colour answers still correct at both
  sizes (`teal`). Measured price of `--ubatch-size 768 -> 1024`: **118 MiB** of VRAM
  (13476 -> 13594 used; free 2458 -> 2340 of 16303). It is compute/graph buffer cost,
  not KV — this build logs no buffer breakdown at default verbosity, so measure
  `nvidia-smi` before/after rather than estimating.
- The crash class is NOT fleet-wide: it needs a model that asks for **non-causal**
  attention over the vision prefix. Measured 2026-10-23 on the CPU `vision-cpu` lane
  (live id `Huihui-Qwen3.5-9B-abliterated.Q4_K_M`, `--batch-size 512 --ubatch-size 512`,
  no image cap) a 1920x1080 frame produced +2031 image tokens — four times its ubatch —
  and encoded fine with zero restarts. Qwen multimodality stays causal, so the assert
  never applies. Test the hypothesis by looking at whether the lane aborts, not by
  assuming ubatch caps every vision lane.
- `vision-cpu` exists to back two LiteLLM aliases — `vision`, and `image` ("temporary
  image route while the R9700 Qwen GGUF fallback is text-only", i.e. a placeholder that
  keeps the `image` model name resolvable). Nothing outside `litellm/app/models/`
  references either alias, and the dedicated `role-image` key has never made a call.
- Who actually calls a LiteLLM alias: the proxy's own DB, not Prometheus. Cluster
  CloudNativePG `litellm-db-1`, database **`app`** (not `litellm`), container
  `postgres`:
  `select model, count(*), max("startTime") from "LiteLLM_SpendLogs" group by model`,
  and for attribution join `"LiteLLM_VerificationToken" v on v.token = s."api_key"` and
  read `v.key_name` (columns are snake_case: `total_tokens`). Terminal redaction masks
  key strings even when joined, so prefix them (`'K: '||v.key_name`) to tell keys apart.
  Measured 2026-10-23: `openai/vision-cpu` had **12 calls since 2026-08-22** (4 of them
  agent vision-verification probes on 2026-10-22) against 343 for Muse and 149 for gemma
  — so "who is this lane for?" is answered by 12 rows, not by the manifest's rationale
  comment.
- **Retired 2026-10-23** (commit `retire the CPU vision lane and the vestigial vision
  alias`): the `vision` alias, the `vision-cpu` Model/InferenceService and its
  `cache-prime-vision` staging Job are gone, and the `image` alias was repointed from
  the CPU lane onto the Muse lane. The lane's weights stay in the shared
  `llm-model-archive` claim (owned by `model-archive.yaml`, mounted by seven other
  pods), so removing the lane GCs nothing — and that claim is NOT lane-owned, so a
  Kustomization removal here cannot delete weights.
- **The `image` alias has a live consumer with a boot-time dependency**:
  `services/gateway/coordinator/image.py` posts owner-attached Matrix screenshots as
  `model: "image"` (max_tokens 4096, 900 s), and `service.py` reads
  `LITELLM_IMAGE_API_KEY` with `os.environ[...]` — so deleting the alias/secret makes
  the `home-infra/gateway` deployment crash-loop, not degrade. Removing it for real is
  a coordinated change across `coordinator/{service,image,matrix}.py`, the
  matrix-coordinator `externalsecret`, and the 1Password `LITELLM_IMAGE_API_KEY`
  field. Low spend-log traffic does NOT mean unused: check for `os.environ[...]`
  readers before concluding a key is dead.
- `vision-cpu` was cogito's slowest vision path — **retired 2026-10-23 by `49624bf`
  ("retire the CPU vision lane and the vestigial vision alias"); the numbers below are kept as
  the record, and the `pvc://` single-file pattern it pioneered is still reused by
  `gemma-4-12b-amnesia.yaml`.** It had no GPU to fix it with: encode-only
  640x480 = 17.8 s (+291 tok), 1280x960 = 74.7 s (+1191), 1920x1080 = 136.3 s (+2031) —
  ~67 ms/image-token, worse per token than Muse's old CPU path. It was a llama.cpp CPU
  build landing on **kristeva** (check `kubectl get pod -o wide`; the manifest name did
  not say the node), which does hold an Arc A380, but that container had no Intel/Level
  Zero runtime, so the card was not available to it without an image swap.
- Probe baselines must be TEXT-ONLY. A 1x1-pixel PNG still costs ~83 gemma image tokens
  (the encoder's minimum tile), so an "encode-only" baseline that carries a tiny image
  inflates the baseline by ~83 and silently subtracts it from every delta, which looks
  like the fix shrank small-image token counts when it did not.
- gemma-4-12b's projector is 175 MiB F16 and cheap on CPU: encode-only 320x240 =
  0.20 s, 640x480 = 0.24 s, 1280x960 = 0.43 s. Offloading it onto amnesia's 5070 Ti
  would fit (2444 MiB free of 16303 with the lane loaded) but buys nothing — do not
  copy Muse's mmproj fix sideways on latency grounds. Its `--no-mmproj-offload` also
  keeps ~150 MiB off a card gaming reclaims at will (the lane requests
  `nvidia.com/gpu: 2` = both time-slice replicas at `llmkube-low`).
- gemma-4-12b reasons like Muse: under a tight `max_tokens` (24) the answer lands in
  `reasoning_content` and `content` comes back `''` — that is a probe artifact, not a
  broken vision path. Use `max_tokens >= ~200` for a one-word colour answer there too.
- Measuring CPU inside a pod: `pgrep -f llama_server` from inside `sh -c '...'`
  self-matches the wrapper and reports a flat tick count. Use
  `ps -eo pid,comm --no-headers | awk '/llama-server/{print $1}'` or `/proc/1/stat`
  (llama-server is PID 1 in these images), sampling fields 14+15 at 100
  ticks/core-second.

# A380 / llama.cpp intel runtime facts

- Kristeva Arc A380 VRAM usage: NOT in sysfs (Talos i915/6.18 has no mem_info_vram_*), not in
  Prometheus (no intel exporter; dcgm is nvidia-only, pinned to iggy), not via Level Zero sysman
  (loader 1.27 + driver 1.15 reject zesDeviceEnumMemoryModules even after zeContextCreate).
  Authoritative source: kernel TTM debugfs via a node debug pod (busybox, /host mount):
  `cat /host/sys/kernel/debug/dri/0000:07:00.0/gem_info` -> `total: 6088MiB, free: NNNN MiB`
  and `local0 usage:` bytes; `clients` file there lists per-process llama-server handles.
- Kristeva GPUs: Arc A380 ONLY, PCI 0000:07:00.0 (8086:56a5, card0 in pods). The RTX 3090 that
  used to sit at 02:00.0 moved to iggy in October 2026; `kubectl get node kristeva -o
  jsonpath='{.status.capacity.nvidia\.com/gpu}'` returns 0, so never schedule an nvidia lane there.
  NFD label intel.gpu-type=A380 maps device id 56a5. llama.cpp server-intel pods see the GPU in
  Level Zero only with ZE_ENABLE_PCI_ID_DEVICE_ID=1; plain loader init enumerates CPU-only.

- ghcr.io/ggml-org/llama.cpp:server-intel is a FLOATING tag whose amd64
  content can lag the tag push: floor pods ran build b10548 (Aug 21) while
  the tag pointed at b11459 (Oct 7). New architectures need the digest pinned
  (sha256:6ccaeb... = b11459 = first intel build with embeddinggemma2 via
  upstream 4fbc76de). Probe tag content via ghcr token API + config blob
  label org.opencontainers.image.version. The same registry also
  garbage-collects OLD UNTAGGED DIGESTS — a digest pinned weeks ago can 404 at
  pull time (`ErrImagePull`), so re-verify pullability before wiring one in,
  and paginate the tags endpoint: an unpaginated listing is alphabetical and
  hides the newest builds.
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
sits unreconciled; see `references/llmkube-tooling.md`. Retiring a lane or alias is
where this bites hardest — `references/vision-lane-audit.md` covers spend attribution
from the LiteLLM postgres DB, finding live consumers before deleting an alias, and the
code-then-pin-then-secret ordering a removal must follow. Dashboards ship as
configMapGenerator + fixed name (`disableNameSuffixHash`) +
`kustomize.toolkit.fluxcd.io/substitute: disabled` + GrafanaDashboard CR with
configMapRef (litellm and dcgm pattern). That annotation is load-bearing: the
KS postBuild envsubst would otherwise eat the `${datasource}` / `${__range}` /
`$__rate_interval` Grafana tokens in dashboard JSON. After Flux applies,
confirm via the Grafana API, not just CR status. Engine-level metrics (tok/s,
concurrency, KV cache) are NOT in LiteLLM — see skill
`llm-engine-metrics-dashboard`.
