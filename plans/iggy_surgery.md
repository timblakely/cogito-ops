# Iggy surgery: dual RTX 3090 to dual Radeon AI PRO R9700

Status: cutover manifests prepared on 2026-09-28. Hardware and Talos are still
unchanged. The ROCm vLLM image pre-pull completed on Iggy through the temporary
`llm/iggy-rocm-image-prepull` Job; no GPU workload was migrated yet.

## Tonight's verified inputs and go/no-go

- Cards: two ASRock Radeon AI PRO R9700 Creator 32GB blower cards, each
  271 × 112 × 39 mm, with one 12V-2x6 power socket. Budget 300 W per card.
- PSU: Corsair RM1000x with one native 12V-2x6 GPU cable. The second card's
  bundled 3× PCIe 8-pin adapter needs **three separate Corsair PCIe cables**,
  one per adapter socket. Confirm the exact physical cable routing, full
  insertion, and connector bend clearance at the machine before shutdown.
  Do not mix modular PSU cables from another model.
- User will be at Iggy with local power and BIOS access. Verify both cards
  fit without blocking each other's blower intake. If any of these physical
  checks fail, keep the 3090s installed tonight.
- Cluster baseline: six Ready control planes; Iggy's etcd member reported no
  errors; Talos 1.13.5, Kubernetes 1.34.2. The `llmkube-model-cache` PVC is
  Bound (450 GiB, OpenEBS hostpath). Iggy's running kernel command line
  already includes `amd_iommu=on iommu=pt`.
- AMD Talos image factory schematic:
  `8f5597684d02cedd54a852b60a13f03bd1d65aa6c48e455e54268163e877ac15`.
  v1.13.5 installer OCI index digest:
  `sha256:e69839bf73217ac00445d7593e7e9e4d0a26c81c4c29e403816067878780b57c`.
  Factory lists `siderolabs/amdgpu:20260519-v1.13.5`.
- The installed LLMKube CRD accepts `accelerator: rocm`, `vendor: amd`, and
  `resourceName: amd.com/gpu`. The first Qwen profile uses digest-pinned
  `vllm/vllm-openai-rocm:v0.30.0`, 32k context, two GPUs, and the existing
  W8A16 checkpoint. Loading that exact checkpoint on R9700 is a cutover gate,
  not a pre-verified result. A validated manual GGUF fallback manifest is at
  `kubernetes/apps/llm/llmkube/resources/manual/iggy-r9700-gguf-fallback.yaml`.
- A dedicated AMD device plugin, case-fan controller, ServiceMonitor, and
  R9700 Grafana dashboard are staged in Git. The NVIDIA plugin and dashboard
  stay available for Amnesia. The manual two-GPU smoke Job is at
  `kubernetes/apps/llm/llmkube/resources/manual/iggy-r9700-smoke.yaml`.

### Operator sequence at the machine

1. Wait for `kubectl -n llm get job iggy-rocm-image-prepull` to show Complete
   if possible. Confirm physical cables and clearance. Record BIOS settings.
2. Suspend only Iggy's active Qwen InferenceService, drain its GPU pod, and
   confirm other control planes and Amnesia's NVIDIA GPU are healthy. Keep
   Flux reconciliation controlled while changing the live service.
3. Power off Iggy locally; swap the cards. Seat power plugs fully, route cables
   without tight bends, then boot through BIOS setup. Keep UEFI, Above 4G
   decoding, and Re-Size BAR enabled; inspect both PCIe devices there.
4. Let Iggy return on its current Talos image. Apply the AMD machine config,
   then upgrade with the pinned AMD installer using Talos default reboot mode.
   Watch local console and cluster membership; never use Talos `powercycle`.
5. Reconcile the AMD plugin and cooling ServiceMonitor. Require
   `amd.com/gpu: 2`, two `/dev/dri/renderD*` nodes, `/dev/kfd`, healthy GPU
   temperatures, and no firmware/reset errors. Run the manual two-card smoke
   Job. Check the case fans respond and sensor loss selects 100% duty.
6. Start the reduced Qwen ROCm profile and verify `/health` plus text, tool,
   and vision requests through the existing endpoint. If W8A16 fails, keep
   Qwen suspended and switch to a measured single-card GGUF/llama.cpp route
   before calling serving restored. Check AMD metrics show both cards.

## Goal and boundaries

Replace Iggy's two RTX 3090s with the two Radeon AI PRO R9700s, restore its
control-plane role and local inference, and observe both cards and the case
cooling. Keep NVIDIA support on Amnesia. Preserve Iggy's node-local model cache,
static FlashNext volume, network bond, and etcd identity; this is an in-place
hardware and software migration, not a Talos reinstall or cluster bootstrap.

The R9700 is an RDNA 4 `gfx1201` device with 32 GB VRAM and a 300 W reference
board-power rating. The actual cards' connector, dimensions, cooler behavior,
and power-control range must be checked by board model. Two cards can draw up
to 600 W at reference power before CPU and the rest of the system.

Iggy runs Talos 1.13.5 on an MSI MPG X570 GAMING EDGE WIFI. Its present image
contains a private patched NVIDIA P2P extension. The checked-in factory image
is an NVIDIA rollback image, not the running private image. The primary Qwen
service uses CUDA vLLM, a 3090-specific FlashAttention artifact, four source
patches, and NVIDIA P2P detection. The NVIDIA device plugin also serves
Amnesia, which must remain untouched by Iggy's removal from NVIDIA scheduling.
See [Iggy's P2P record](talos/2026-09-iggy-gpu-p2p.md) and
[the workstation Talos record](workstation_talos.md).

## Decisions to resolve before cutover

1. **Exact board fit and power.** Record both R9700 board models, connector
   requirements, cooler width, PSU model and available cables. Confirm the
   cards can be cooled in the two slots without starving the lower card. The
   motherboard gives the second card a narrower PCIe path; measure link width
   and two-card communication after installation.
2. **Talos version and image.** Prefer the existing 1.13.5 version for the
   hardware cutover to avoid combining a Talos version upgrade with a driver
   change. Confirm the Image Factory offers a compatible `siderolabs/amdgpu`
   extension with R9700 firmware for that version. If it does not, first
   qualify a newer Talos release and its kernel/extension pair separately.
3. **Serving route.** Check the *installed* LLMKube CRDs/controller for an AMD
   or ROCm hardware accelerator value and for how `resources.gpu: 2` chooses
   its Kubernetes resource name. Do not assume changing the Model's
   `resourceName` changes the InferenceService's resource request. If LLMKube
   cannot emit `amd.com/gpu`, use a Git-managed Kubernetes Deployment and
   Service for the first ROCm backend, retaining the API endpoint and LiteLLM
   model name. Remove or suspend the LLMKube-managed Service/Deployment first
   so two controllers do not claim the same objects. Migrate back to LLMKube
   only after that path is proven.
4. **Qwen profile.** Select a digest-pinned ROCm vLLM image that contains
   `gfx1201` kernels. Verify the exact Qwen 3.8 27B checkpoint, W8A16
   compressed-tensors loading, GDN/Mamba, MTP, vision, FP8 KV, and the desired
   attention backend on that image. The current `club3090` FA2 artifact and
   exact-source patches cannot be assumed portable. Keep a simpler,
   smaller-context, single-card profile ready for first service restoration.
5. **Monitoring implementation.** Qualify AMD's device metrics exporter on the
   R9700 and Talos before adopting its dashboard fields. AMD's GPU Operator
   compatibility table lists the R9700S, not explicitly the desktop R9700,
   and Talos is not among its validated operating systems. A direct AMD device
   plugin plus a separately qualified exporter is the smaller initial change.

## Prepare in Git before touching hardware

### Talos and BIOS

- Update `talos/schematics/iggy.yaml.j2`: retain `amd-ucode`, `realtek-firmware`, and
  `nut-client`; replace both NVIDIA extensions with `siderolabs/amdgpu`.
  Drop the irrelevant `i915.enable_guc=3` and `intel_iommu=on` arguments only
  after comparing the rendered new kernel command line with the running one.
  Keep the running image's `amd_iommu=on iommu=pt` initially; change it only
  to resolve a measured problem. The previous NVIDIA P2P test does not
  establish an AMD P2P setting.
- Update `talos/machineconfig/iggy.yaml.j2` to pin the new AMD installer by
  digest, remove the four NVIDIA module entries and
  `nvidia.com/gpu.present`, and add an AMD-specific node label only if a
  consumer needs it. Retain the disk selector, `wipe: false`, local volume,
  bond/VLANs, and general node-role labels. Save a rendered config and image
  schematic ID for review.
- Leave `talos/images/iggy-p2p/`, its patch, and the CUDA P2P tests as
  historical rollback/reproduction assets. Update `talos/mod.just` so Iggy's
  future upgrade route uses the new AMD image only after that image is proven;
  keep the existing guard against generic upgrade while preparing the change.
  Do not accidentally select the old NVIDIA factory image.
- Record current BIOS settings and boot order from setup. Keep UEFI, Above 4G
  decoding, and Re-Size BAR enabled. Inspect PCIe link speed/width and BAR
  mappings after the swap. Make any firmware changes in BIOS setup, never by
  writing EFI variables from Linux.

### Kubernetes allocation and runtime

- Add an AMD GPU device plugin under `kubernetes/apps/cluster-infra/`, scoped
  to Iggy, with the control-plane toleration and `amd.com/gpu` as its resource.
  Start with whole physical devices and no sharing. If using AMD's node
  labeller, arrange for standalone NFD to accept its label namespace; avoid a
  second NFD installation. Match Iggy by hostname or a verified GPU PCI
  feature, not merely by AMD CPU vendor. Verify that the plugin passes the
  allocated render node plus `/dev/kfd` to an ordinary ROCm pod.
- Keep `kubernetes/apps/cluster-infra/nvidia-device-plugin/` installed for
  Amnesia. Narrow NVIDIA-only DaemonSets and the NVIDIA chart's affinity so
  they no longer target Iggy after its PCI IDs change. Keep the `nvidia`
  RuntimeClass while Amnesia still uses it. Remove NVIDIA runtime selection
  only from Iggy workloads.
- Change active Iggy GPU requests, tolerations, runtime selection, images,
  and visibility variables in `llmkube/resources/{models,inferenceservices}.yaml`.
  Check `llmkube/resources/single-card-models.yaml` and the suspended Muse
  service before either is enabled. The Muse definition pins a 3090 UUID in
  `NVIDIA_VISIBLE_DEVICES`; replace that with AMD allocation and a ROCm
  llama.cpp image. Keep Amnesia's `flashnext-amnesia.yaml` on NVIDIA.
- Replace `llm/cuda-dev` and its GPU-bearing mode templates with a ROCm
  development image and `amd.com/gpu` requests, or retire those templates
  explicitly. The mode README says the split/dark mutation recipes are
  historical; do not reactivate them as part of surgery. Review Foreman's
  `accelerator: cuda` declarations against its installed schema and change
  them only if they control placement or execution on Iggy.
- Keep the Recreate rollout policy for the two exclusive Iggy lanes. Confirm
  that a replacement pod cannot start before the old pod releases its GPU.

### Cooling, power, and monitoring

- Remove Iggy from `nvidia-power-limit` and replace the 250 W `nvidia-smi`
  loop only if the exact R9700s support a useful AMD SMI power cap. Query
  supported min/max/default bounds first; start at board defaults and record
  actual sustained power and temperature before choosing a cap.
- Replace `fan-control.yaml` and `fanctl.py`. The current controller reads
  NVML from host NVIDIA libraries, controls card fans through NVML, and uses
  the hottest card to set NCT6797 case fan PWM3-7. First confirm the R9700s
  expose reliable temperatures and writable fan controls via AMD SMI/hwmon.
  Keep card firmware fan control if manual control is unavailable. Preserve a
  safe case-fan baseline during bring-up; test the controller's sensor-loss
  behavior and clean-stop restoration before allowing automatic case PWM.
- Replace Iggy's DCGM exporter scrape with a qualified AMD metrics exporter
  and ServiceMonitor. Migrate `gpu-thermal` dashboard queries and alerts from
  `DCGM_FI_*`/NVML-derived `fanctl_*` fields to observed AMD temperature,
  power, utilization, VRAM, fan, and case-sensor fields. Check that scrape
  targets are up and that the graphs show two distinct cards under load.

## Cutover sequence and gates

| Stage | Action | Gate before continuing |
| --- | --- | --- |
| 0. Baseline | Record five/six-node membership as currently configured, etcd health, Iggy's Talos version/extensions, current GPU allocation, inference endpoints, model-cache PVC/PV binding, and thermal readings. Save the old image digest and rendered config. | Recovery inputs and a local console/BIOS path are available. |
| 1. Stage | Render and review the AMD Talos image/config and Flux manifests. Pull and inspect the image and ROCm workload digests. Temporarily suspend Iggy serving through Git so failed CUDA pods do not churn during the swap. | Non-Iggy workloads, especially Amnesia's NVIDIA workloads, remain healthy. |
| 2. Physical change | With local access and a way to power Iggy back on, stop its workloads, allow etcd to settle, then power off for the physical swap. The historical rule against Talos `powercycle`/remote shutdown reflects a failure to power back on; physical card replacement necessarily requires local power-off. Swap cards and cables, inspect BIOS detection, then boot. | Iggy returns as a Ready control plane; network, etcd, and local storage are intact. |
| 3. Host GPU | Boot the AMD Talos image using the normal/default reboot mode, never `powercycle`. Inspect extension/module status, kernel logs, two PCI devices, two render nodes, `/dev/kfd`, BAR sizes, and negotiated link widths. | Both R9700s initialize without firmware errors or repeated GPU resets. |
| 4. Kubernetes GPU | Reconcile the AMD plugin and run a pinned small ROCm diagnostic pod with one and then two GPU requests. Check `kubectl get node iggy` capacity/allocatable equals two physical `amd.com/gpu` devices. | Each allocation sees the intended card(s), and Amnesia still advertises NVIDIA resources. |
| 5. Communication | Run HIP peer-access/copy checks in both directions and a two-rank RCCL all-reduce; record topology and throughput. Try `HSA_FORCE_FINE_GRAIN_PCIE=1` only with large BAR support and after a baseline measurement. | Two-card communication is correct; if P2P fails, select a measured single-card or host-staged serving profile instead of assuming tensor parallel will be fast. |
| 6. Service | Start with a small ROCm model. Bring up Qwen at a reduced context and simple features, then add quantization, TP=2, MTP, vision, FP8 KV, and the desired 262k context one at a time. Re-measure memory budget, throughput, and concurrency. | The OpenAI-compatible endpoints, LiteLLM routing, health checks, tool/reasoning responses, and image requests work under load. |
| 7. Operations | Enable the qualified case-fan policy, power cap if chosen, exporter, dashboards, and alerts. Soak under representative GPU load. | Temperatures, fan response, power, two-card metrics, node health, and serving remain stable. |

The current NVIDIA GPU P2P test scripts and 3090 benchmark numbers are
historical controls, not AMD acceptance tests. Add separate HIP/RCCL tests
that validate data integrity and report measured transfer/collective rates.
Track service acceptance against a freshly measured R9700 baseline and the
actual user-facing latency target, rather than assuming a 32 GB card yields
the 3090 profile's KV capacity or throughput.

## Recovery

- If Iggy fails POST or does not return to the network, use the local console
  and BIOS setup. Check card seating, power cables, boot order, UEFI, Above 4G,
  and Re-Size BAR. Do not repeat direct EFI-variable writes or Talos
  `powercycle`.
- If the AMD image boots but GPU initialization fails, keep Iggy in the
  control plane, leave Iggy GPU serving suspended, and diagnose firmware,
  extension, and PCI resources. Reverting only the Kubernetes manifests will
  not make R9700s work with the old NVIDIA image.
- A full hardware rollback requires reinstalling the 3090s, restoring the
  prior NVIDIA image/config and Iggy workloads, then verifying the old P2P,
  fan, and serving checks. The private patched NVIDIA installer requires
  temporary pull authentication; arrange access *before* the physical change.
  The existing `machine.install.image` factory fallback is a different,
  unpatched NVIDIA image, so record both exact digests.
- Keep the cluster's other control planes healthy and check etcd quorum after
  each Iggy restart. Preserve the node-local cache/PVs; do not wipe or reset
  Iggy as a troubleshooting shortcut.

## References

- [AMD R9700 specifications](https://www.amd.com/en/products/graphics/workstations/radeon-ai-pro/ai-9000-series/amd-radeon-ai-pro-r9700.html)
- [ROCm supported GPUs](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html)
- [Talos system extensions](https://github.com/siderolabs/extensions)
- [AMD Kubernetes device plugin](https://github.com/ROCm/k8s-device-plugin)
- [ROCm container device access](https://rocm.docs.amd.com/en/develop/install/docker-containers.html)
- [AMD vLLM on R9700](https://rocm.docs.amd.com/en/7.13.0-preview/ai-inference/vllm.html)
- [RCCL PCIe peer access](https://rocm.docs.amd.com/projects/rccl/en/latest/how-to/rccl-usage-tips.html)
- [AMD GPU Operator compatibility](https://instinct.docs.amd.com/projects/gpu-operator/en/release-v1.5.1/index.html)
