# Cogito coordinator and local-LLM operator lessons

This is the short, current companion to the dated research artifacts in this
directory. It records the sharp edges found while replacing Cogito's custom
workflow plumbing with Matrix, Foreman, LLMKube, and two heterogeneous local
model lanes. Prefer observed repository or live-cluster evidence over these
notes when they disagree.

## Matrix and coordinator workflow

- Treat the Matrix thread root event as the workflow correlation ID. A command
  such as approval or revision in that thread should resolve the current plan
  version from durable state; humans should not need to paste a plan SHA.
- Persist a command response before attempting Matrix delivery. Transport can
  retry or replay events, so event IDs and state transitions must be idempotent.
- Put human conversation in the plan thread and noisy lifecycle/status events
  in a dedicated activity room that users can mute. Hookshot/GitHub delivery
  belongs there too. Do not suppress useful workflow events merely to control
  notifications.
- Planning intake should be conversational. Let the planner ask a bounded
  clarification or push back before drafting; keep an explicit draft command as
  the escape hatch when the human wants planning to start immediately.
- With streamed Responses API output, the acknowledgement is not the result.
  Reassemble output items through the terminal completion event and store the
  completed planner text before posting it to Matrix.
- An expensive planner should coordinate, not explore. Delegate repository
  search, research, and every shell command to bounded local scouts; return
  concise evidence summaries to the planner. Cap rounds and summary size so
  delegation does not become an unbounded loop.
- Merge authority belongs to the coordinator only after at least two distinct
  reviewer agents approve the final coder commit. Bind every review to that
  exact SHA; a new coder commit invalidates earlier approvals. For a long plan,
  repeat this per serial deliverable/PR instead of creating one giant review.

## Model diversity is a routing property

- Different prompts against one backend are not independent model review.
  Foreman `Agent` objects pin `spec.model` and `inferenceServiceRef`, so assign
  reviewer agents to different services explicitly. LiteLLM aliases alone do
  not change a pinned Foreman backend.
- Keep stable role aliases (`worker`, `reviewer`, `planner-local`) for clients,
  and expose model-specific aliases for diagnosis and interactive use.
- A practical two-model split is Qwen for coding/mechanical work and Muse
  Glimmer for a second reviewer/research/vision perspective. With only two
  models, put one reviewer on each family; otherwise a two-review quorum can
  still be same-model consensus.

## Two heterogeneous NVIDIA GPUs

Current status (2026-09-12): **do not deploy NVIDIA DRA 0.5.0 on Talos with
the system-extension NVIDIA driver.** Kubernetes was safely upgraded to 1.34.2
and the feature gates remain enabled, but the DRA/model rollout was rolled back
to the legacy device plugin and two-GPU Qwen FP8 service.

The DRA init container searches standard driver-root locations such as
`usr/bin/nvidia-smi` and `usr/lib64/libnvidia-ml.so.1`. Talos installs those
pieces under separate `/usr/local/bin` and `/usr/local/lib` paths, so no valid
`nvidiaDriverRoot` exists. Upstream issue
[`kubernetes-sigs/dra-driver-nvidia-gpu#605`](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu/issues/605)
documents the same failure; its Talos support PR #695 was closed without merge.
The published workaround needs a custom driver image plus CDI-path
post-rendering. That creates local maintenance ownership and is intentionally
out of scope for Cogito.

- `nvidia.com/gpu: 1` does not select a physical card. The legacy NVIDIA device
  plugin exposes identical RTX 3090s as interchangeable units even when their
  PCIe links differ. `deviceIDStrategy: uuid` changes the injected identifier
  only after allocation; it is not a scheduler selector.
- On iggy, the stable mapping observed on 2026-09-12 is:

  | Link | PCI address | UUID | Intended lane |
  | --- | --- | --- | --- |
  | x16 | `00000000:2D:00.0` | `GPU-a5982685-6ed7-6fce-8096-52d29e241396` | Qwen |
  | x4 | `00000000:23:00.0` | `GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14` | Muse |

- Once upstream Talos support exists, use NVIDIA's DRA driver and
  UUID-selecting `ResourceClaimTemplate` objects for deterministic assignment.
  Until then, keep the shared legacy service; do not rely on pod startup order
  and do not hand-set `NVIDIA_VISIBLE_DEVICES`, because both bypass scheduler
  correctness.
- LLMKube 0.9.25 supports DRA under
  `Model.spec.hardware.gpu.resourceClaims`. When using it, omit both
  `hardware.gpu.count`/`resourceName` and `InferenceService.spec.resources.gpu`.
  Setting either count makes LLMKube request a legacy GPU in addition to the
  DRA claim, causing double allocation or an unschedulable pod.
- NVIDIA DRA v0.5.0 requires Kubernetes 1.34.2 or newer for this cluster. Avoid
  1.34.0/1.34.1 because of the documented DRA defect. DRA also needs CDI in
  containerd; Cogito's Talos config already includes `/var/run/cdi`.
- Do not let the legacy NVIDIA device plugin and DRA driver advertise the same
  cards concurrently. Preserve legacy `nvidia.com/gpu` consumers by enabling
  `DRAExtendedResource` on kube-apiserver, controller-manager, scheduler, and
  kubelet before removing the device plugin.
- Rollout order is load-bearing: upgrade/apply the Kubernetes component and
  feature-gate configuration first; remove the old device plugin; install the
  DRA driver; verify its `DeviceClass` and `ResourceSlice`; only then activate
  UUID-bound model claims.
- A generated root Kustomization with `spec.prune: false` will leave a removed
  child Kustomization behind. During the rollback, the orphaned DRA child kept
  its HelmRelease alive beside the restored device plugin and had to be deleted
  explicitly so its Flux finalizer could uninstall the chart.

## Runtime and cache details

- The deferred target for Jory's single-card Qwen recipe uses
  `dbirks/Qwen3.8-27B-W4A16-AutoRound` through Syv AI's 3090 image with
  `SPEC=dflash2`, `CTX=long`, prefix caching, and `MAX_SEQS=5`. Five is an
  admission ceiling, not five guaranteed resident long-context requests.
- Syv's default `VISION=0` removes Qwen's vision tower. It is vLLM/safetensors,
  not llama.cpp/GGUF, so there is no external `mmproj` to offload. Keep Qwen
  text-only when Muse owns vision; this returns VRAM to recurrent/KV state.
- Muse Glimmer is a 30B model. Its GGUF target, DFlash draft, and projector are
  separate files. Pass the projector path explicitly and use
  `--no-mmproj-offload` to keep it in host RAM.
- Inspect the actual hot PVC before adding downloads. Cogito already had both
  model families staged, but the Qwen directory was a Vishva007 build rather
  than Syv's exact dbirks input. The Syv image prepares its expected checkpoint
  and derived DFlash artifacts under `/app/models`; mount persistent storage
  there if cold starts should not repeat that work.
- Retiring a model does not require deleting its definition or weights. Move
  its manifests under an inactive `disabled/` path and omit them from
  Kustomization resources. This keeps an obvious rollback without leaving two
  controllers competing for GPU residency.
- Search operator recipes and runbooks for a retired service name, not only
  active manifests. The legacy `llm-split`/`llm-dark` helpers suspend Flux and
  overwrite the shared two-GPU service. Remove them when a future DRA split
  actually lands, but restore them together with the shared service during a
  rollback so documentation and operator behavior do not disagree.

## Validation shortcuts and traps

- Bypass mise shims for read-only inspection. In this repository, the direct
  binaries live under the persistent mise install tree; sandboxed shim startup
  can fail while trying to write mise state even when no tool installation is
  needed. Resolve the real binary first; do not assume tools such as `rg` live
  under `/usr/bin`.
- Check the node's live allocated requests before splitting one service into
  two. On iggy, 90% of allocatable RAM was already requested; replacing a
  10-GiB service with initial 16-GiB and 8-GiB requests would have made the
  second pod unschedulable even though both GPUs had enough VRAM. Budget the
  replacement delta, not just each new pod in isolation.
- Root app Kustomizations use components outside their directory. Validate them
  with Kustomize's `--load-restrictor LoadRestrictionsNone`; a plain
  `kubectl kustomize` rejects the component path even though Flux accepts it.
- `flux-local` 7.11 treats an OCIRepository `ref.digest` as a Helm semver
  constraint for `chartRef` sources. Keep the verified digest in a comment and
  use the fixed chart release tag when this false failure blocks local/CI
  inflation; verify the pulled digest independently with Helm.
- Talos templates contain 1Password placeholders in fields that must decode as
  base64. `talosctl machineconfig patch` therefore cannot validate a raw
  MiniJinja render; either inject secrets through the normal recipe or use a
  YAML query to validate the changed non-secret fields without exposing them.
- Run `scripts/validate-llm-catalogue.py` after every backend/alias change. It
  catches missing services and advertised-context mismatches.
- `kubectl apply --dry-run=server` is useful for installed CRD/webhook checks.
  Fully rendered app bundles may still fail on unsubstituted Flux variables
  such as `${DOMAIN_NAME}`; validate the changed resource subset separately.
- For acceptance, verify the generated claim's allocated UUID and then run
  `nvidia-smi --query-gpu=uuid,pci.bus_id,pcie.link.width.current` inside each
  serving pod. A Ready pod alone does not prove it received the intended card.
