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
- A Matrix thread root created by the coordinator has no event ID until the
  transport acknowledges it. Persist replies against the root notification ID,
  withhold them from the outbox until that acknowledgement arrives, then resolve
  the returned event ID at delivery time. Use the same durable ID to generate
  cross-room links back to the control thread.
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
- Foreman `freeform` tasks clone a repository only when `payload.repo` is set;
  putting a URL in the natural-language prompt leaves an empty workspace and
  disables workspace-backed tools. Repo-backed read-only tasks can then receive
  a coder-style `NO-CHANGES` wrapper, so consume the preserved `modelSummary`.
- A planning scout should retain repeated-call and context stuck-loop guards but
  disable the edit-free signal: reading without writing is its intended work.
  Size the local model's host-memory limit for multi-turn context growth, not
  only idle residency; Muse idled near 4.4 GiB and exceeded a 6 GiB limit after
  21 research turns.
- Merge authority belongs to the coordinator only after at least two distinct
  reviewer agents approve the final coder commit. Bind every review to that
  exact SHA; a new coder commit invalidates earlier approvals. For a long plan,
  repeat this per serial deliverable/PR instead of creating one giant review.
- Foreman's completed transcript ConfigMap is useful operator evidence, not
  planner context. Publish structured assistant notes, tool calls, commands, and
  bounded outputs in a muteable Agent Runs thread; never publish raw private
  reasoning fields. Redact credential-shaped values, cap event size/count, and
  keep the concise final summary as the planner-facing boundary. Detailed live
  streaming needs a structured Foreman event stream; do not scrape pod logs to
  imitate one.

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

- `nvidia.com/gpu: 1` does not select a physical card. The legacy NVIDIA device
  plugin exposes identical RTX 3090s as interchangeable units even when their
  PCIe links differ. `deviceIDStrategy: uuid` changes the injected identifier
  only after allocation; it is not a scheduler selector.
- On iggy, the stable mapping observed on 2026-09-12 is:

  | Link | PCI address | UUID | Intended lane |
  | --- | --- | --- | --- |
  | x16 | `00000000:2D:00.0` | `GPU-a5982685-6ed7-6fce-8096-52d29e241396` | Qwen |
  | x4 | `00000000:23:00.0` | `GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14` | Muse |

- For this experimental node, bind each service with `runtimeClassName: nvidia`
  and an exact `NVIDIA_VISIBLE_DEVICES` UUID. Keep the LLMKube `Model`
  scheduler-neutral and omit `InferenceService.spec.resources.gpu`, otherwise
  LLMKube adds an interchangeable `nvidia.com/gpu` request as well.
- This direct binding is deterministic but scheduler-blind: Kubernetes still
  advertises both GPUs as free. Treat the two serving manifests as the sole GPU
  owners and do not schedule another GPU workload on iggy while they run.
- NVIDIA DRA v0.5.0 does not currently work with Talos's system-extension
  driver layout. Its init code expects the NVIDIA binaries and libraries under
  one conventional driver root, while Talos exposes them under `/usr/local`.
  Upstream Talos support was not merged. Avoid a custom DRA image and CDI
  post-render bridge here; reconsider DRA after upstream support matures.
- The Kubernetes 1.34.2 upgrade and `DRAExtendedResource` feature gates may
  remain enabled. They are inert without DRA claims/driver and avoid another
  control-plane change merely to undo preparatory work.

## Runtime and cache details

- Jory's single-card Qwen recipe uses
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
- Search operator recipes and runbooks for the retired service name, not only
  active manifests. The old `llm-split`/`llm-dark` helpers suspended Flux and
  overwrote a shared two-GPU service; leaving those commands exposed after the
  fixed-UUID split would turn a convenient old workflow into a destructive
  footgun.

## Validation shortcuts and traps

- A planning scout's final summary is an API boundary. Foreman does not forward
  the task transcript to Astra, so a statement such as "inspected workflows and
  reported findings" discards the evidence even when the transcript contains
  it. Prompts must tell scouts to restate paths, commands, errors, and conclusions
  in the final summary and to stop exploring once the question is answered.
- The upstream Foreman coder image includes `git`, `curl`, and `wget`, but not
  GitHub's `gh` CLI. Repository-only scouts work without it; PR/check-log scouts
  do not. Use Cogito's thin, digest-pinned planning-scout derivative rather than
  teaching the model to install tools at task time.
- GitHub Actions job logs are delivered as zip archives. Include `unzip` and
  `jq` alongside `gh`; run metadata alone is not enough for evidence-first CI
  diagnosis, and missing extraction tools can send a local scout through a long
  sequence of unproductive fallback commands.
- Debian's `gh` 2.46 returned zero bytes for `gh run view --job ... --log` on a
  run whose current `gh` 2.82.1 client returned 2.69 MB. Install the official
  release with a pinned checksum in the scout image; do not make the model work
  around an old client's Actions-log behavior with raw API headers.
- Long-running llama.cpp research traffic exceeded Muse's 12Gi host-memory
  cgroup after several sequential scouts. The endpoint was OOM-killed at the
  same instant an active scout received `connection refused`. Match the server's
  slot count to actual Foreman supervision, reserve the full per-scout context,
  and size host memory from sustained traffic rather than idle RSS.

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
