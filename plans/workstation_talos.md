# Workstation → Talos gaming worker

Status: proposed implementation plan; no infrastructure changes made.
Research date: 2026-09-26. Owner/operator: Tim, using the Fedora laptop.

## Decision

Convert the Ryzen 9900X / 64 GB / RTX 5070 Ti 16 GB workstation into a **dedicated Cogito worker**. Physically remove and preserve its existing NVMe, install a fresh blank NVMe, and administer everything from the Fedora laptop. Start with one Moonlight client and one Steam session through Fenrir and Games on Whales Wolf. First establish a working official-driver baseline: Steam must launch and at least one installed game must be playable over Moonlight. Only after that baseline passes, create and test a newer-driver image to assess feasibility. A custom build pipeline is a future milestone contingent on a successful experiment; pipeline design and implementation are outside this plan’s current scope.

Use Talos 1.13.5 with **official open NVIDIA production kernel modules**, a matching NVIDIA container toolkit, and Cogito's existing Cilium BGP/shared LoadBalancer IP facilities. A custom Image Factory schematic is required; a custom-compiled kernel is **not the expected starting requirement**. NVIDIA explicitly requires open kernel modules for Blackwell, including the 5070 Ti. Reusing a proprietary `nonfree-kmod-nvidia-production` extension would be wrong. [NVIDIA 595.71.05 documentation](https://download.nvidia.com/XFree86/Linux-x86_64/595.71.05/README/kernel_open.html)

This plan uses Shrinedogg's work only for the Talos image, Fenrir, and Games on Whales. It does not adopt his unrelated infrastructure, database, caching, or security architecture. His deployment is useful evidence, but its working RTX 5090 configuration is not proof that this workstation has passed validation.

## 1. Evidence and current Cogito configuration

Reviewed Cogito tree corresponding to GitHub `main` commit `5fb7dc3026bf1404f6c3f4416f3b9f1dfd7e9e5b`. Live cluster inspection hit a DNS/connectivity failure from the execution environment and was stopped. The following describes **GitOps intent**, not a fresh live-health certification. Laptop verification is a prerequisite to removing the disk.

| Area | Current configuration | Consequence |
| --- | --- | --- |
| Cluster | Five existing control planes: iggy, kristeva, nuc-1/2/3; Talos 1.13.5 and Kubernetes 1.34.2 in source | Add a worker; do not bootstrap a new cluster or add etcd membership |
| Cilium | Chart 1.19.2, kube-proxy replacement, native routing, direct node routes, netkit, endpoint routes | Keep these defaults for the first deployment |
| Load balancing | BGP enabled, L2 announcements disabled, Maglev, **global DSR**, acceleration best-effort | Use existing BGP and IPAM; no MetalLB or second announcement system |
| Addressing | Nodes `192.168.42.0/24`; pods `10.42.0.0/16`; Services `10.43.0.0/16`; LB pool `192.168.69.0/24` | Reserve one unused gaming VIP after a live inventory |
| BGP | All Linux nodes selected; local ASN 64514, router `192.168.1.1`, peer ASN 64513 | New worker is automatically eligible; verify router neighbor acceptance and advertisements |
| Talos API proxy | Cilium uses KubePrism `127.0.0.1:7445`; API identity `k8s.internal` | Retain the established API/CA and laptop DNS path |
| GPU | NVIDIA device plugin 0.18.0 in `cluster-infra`, RuntimeClass `nvidia`, GFD plus separate NFD | Extend existing plugin configuration only for the new worker |
| Sharing | Current default plugin config has no time slicing | Add a node-selected gaming profile; leave Iggy unchanged |
| Storage | Rook Ceph default; OpenEBS hostpath available at `/var/mnt/local-hostpath` | Explicitly select local storage for games |
| Ceph | Explicit nuc-1/2/3 devices, `useAllNodes: false`, `useAllDevices: false` | New disk stays outside Ceph; do not apply Ceph node labels |

Source files:

- [Cilium values](../kubernetes/apps/cilium/cilium/app/helm/values.yaml) and [BGP/IPAM resources](../kubernetes/apps/cilium/cilium/networking/networking.yaml).
- [Cluster settings](../kubernetes/flux/meta/cluster-settings.yaml).
- [Talos base](../talos/machineconfig/base.yaml.j2), [Iggy config](../talos/machineconfig/iggy.yaml.j2), [Talos recipes](../talos/mod.just).
- [NVIDIA deployment](../kubernetes/apps/cluster-infra/nvidia-device-plugin/app/helmrelease.yaml), its adjacent configuration, and [OpenEBS](../kubernetes/apps/storage/openebs/app/helmrelease.yaml).

### What actually needs smoothing out in Cilium

Fenrir publishes a Moonlight proxy Service and dynamically creates session Services. They must share one VIP while retaining distinct port/protocol tuples. Keep them in the same `dreamcast` namespace, set `lbipam.cilium.io/sharing-key: direwolf` consistently, and pass `--lb-sharing-key=direwolf` to the operator. Assign the reserved VIP to the proxy using `lbipam.cilium.io/ips`; confirm session Services join that same allocation. Conflicting port tuples can prevent sharing. [Cilium 1.19.2 IPAM documentation](https://github.com/cilium/cilium/blob/v1.19.2/Documentation/network/lb-ipam.rst)

Use `externalTrafficPolicy: Cluster` initially. Proxy and session Services select different pods; `Local` complicates shared-IP eligibility and can send traffic to a node without the required backend. Verify the proxy-on-another-node case explicitly.

Shrinedogg adds a Fenrir-specific admission policy to request DSR because his shared VIP suffered a remote-node SNAT return-path problem. **Cogito already requests global DSR**, so do not copy that policy or change cluster-wide LB mode preemptively. Check the actual Cilium ConfigMap and agent configuration, DSR dispatch method, routes, and packet captures before deciding a change is necessary. His `MutatingAdmissionPolicy` manifest also needs API-version review against Cogito's Kubernetes 1.34; it is not a drop-in requirement.

Start with native LoadBalancer Services. Fenrir's inspected session controller says Gateway support is unfinished. An HTTPRoute, generic Envoy Gateway route, or Cloudflare proxy will not carry the game's arbitrary UDP streams. Host networking would require deliberate operator/network changes, not a simple Cilium workaround.

## 2. Talos / Blackwell conclusion and artifact selection

The [official Talos 1.13.5 extension catalog](https://factory.talos.dev/version/v1.13.5/extensions/official) currently includes the required pair:

| Artifact | Version | Catalog digest |
| --- | --- | --- |
| `siderolabs/nvidia-open-gpu-kernel-modules-production` | `595.71.05-v1.13.5` | `sha256:620835af320adae38d5d4788491131023be7430f3000c52f0fb54661eaef4e1d` |
| `siderolabs/nvidia-container-toolkit-production` | `595.71.05-v1.19.1` | `sha256:91e6bb19cefddd5322ffa5aa98bf665ccb862b44aadac5438c27979189194cee` |

The toolkit suffix is its own version, not a Talos version. Preserve the common NVIDIA driver version. Record the resulting schematic ID, installer digest, boot ISO checksum, and extension identities in the implementation PR; verify the catalog again when executing.

Proposed schematic extension set:

```yaml
customization:
  systemExtensions:
    officialExtensions:
      - siderolabs/amd-ucode
      - siderolabs/realtek-firmware
      - siderolabs/nvidia-open-gpu-kernel-modules-production
      - siderolabs/nvidia-container-toolkit-production
```

Confirm the final NIC and firmware requirements before generating it. Add Cogito-specific optional extensions only when this node needs them. Use matching Image Factory boot and installer artifacts for the same schematic and Talos version.

Shrinedogg's current relevant notes describe Sidero-signed open modules. They do not establish that an old custom-kernel workaround is still required. Iggy's local custom image addresses patched dual-3090 P2P and module-signature constraints; do not copy its kernel patch, module-signature bypasses, or P2P modifications to the 5070 Ti.

Load `nvidia`, `nvidia_uvm`, `nvidia_modeset`, and `nvidia_drm`, retain CDI discovery directories and the existing NVIDIA runtime integration. Verify DRM modesetting, the actual render device, driver version, GPU recognition, Vulkan rendering, and NVENC in containers. An `nvidia-smi` success alone is insufficient.

Baseline failure gate: if official artifacts fail, collect extension status, kernel/module logs, PCI identity, firmware configuration, and a minimal container reproducer. First resolve version mismatch, firmware, runtime/CDI, render-node selection, or missing capabilities. Investigate a custom Talos kernel/extension remedy only for a demonstrated unresolved kernel/module incompatibility, with source pinning and a bootable rollback image. Such a failure does not satisfy the official-driver baseline gate or trigger the planned newer-driver experiment. Do not disable signature enforcement speculatively.

### Newer-driver feasibility experiment, after the official baseline

This is a separate experiment after M4 succeeds. Preserve the official-driver installer, configuration, application digests and measured game-streaming results as the recovery and comparison baseline.

1. Select and pin a then-current NVIDIA Linux release newer than the official baseline. Record the release, source commit and checksums; do not use a floating `latest` reference.
2. Create a one-off image on a builder available independently of the gaming worker. Build the open NVIDIA modules for the selected Talos kernel, with matching NVIDIA GSP firmware and userspace driver libraries. Use a compatible container toolkit. Keep the Talos/Linux versions and configuration unchanged where feasible to limit variables.
3. Account for module signing: Talos requires a trusted signing key, so independently built modules require a coherent custom kernel/module build with matching signatures. Assemble an installer and recovery boot artifact for this worker. [Talos custom kernel requirements](https://docs.siderolabs.com/talos/v1.13/build-and-extend-talos/custom-images-and-development/customizing-the-kernel)
4. Back up saves and pairing state, stop the session, install the experimental image on the gaming worker, and reboot. Retain the same Fenrir, Wolf, Steam/game images, game, codec, resolution and bitrate for comparison.
5. Repeat GPU recognition, Vulkan/NVENC, Cilium connectivity, Steam launch and the same game’s 30-minute streaming test. Check audio/input, driver resets, latency, restart/reboot persistence and recovery to the official image.
6. Record whether building, booting, gaming and rollback succeeded, plus any regressions and manual work required. If unsuccessful, return to the official baseline and document the blocker. If successful, record the exact artifacts as a feasible option; success does not imply automatic adoption or future automatic upgrades.

**Future milestone, contingent on feasibility:** create a maintained custom driver/image build pipeline. Its design and implementation are deferred; the current deliverable is the one-off feasibility result and a working official-driver fallback.

## 3. Fenrir source and image selection

Reviewed [biggs.dog snapshot](https://github.com/shrinedogg/biggs.dog/tree/9ff1da94b86aa6680c68e9733164c16220e09b63), especially its Dreamcast manifests and [relevant engineering notes](https://github.com/shrinedogg/biggs.dog/blob/9ff1da94b86aa6680c68e9733164c16220e09b63/docs/NOTES.md#dreamcast-engineering-notes).

The deployed manifests are more specific than the prose:

| Component | Image tag used by the reviewed deployment |
| --- | --- |
| Operator | `docker.io/shrinedogg/operator:v0.1.3` |
| Agent | `docker.io/shrinedogg/wolf-agent:v0.1.3` |
| Moonlight proxy | `docker.io/shrinedogg/moonlight-proxy:v0.1.2` |
| Wolf | `docker.io/shrinedogg/wolf:v0.1.0` |

These are **candidate tags, not verified immutable release artifacts**. Public Fenrir tags did not contain `v0.1.3` during review. The [main snapshot](https://github.com/shrinedogg/fenrir/tree/9501ab4a58c31575cdc5e6c7b6d87d0124352c47) still had fixed session ports and broad session-Service cleanup. The [multi-user branch snapshot](https://github.com/shrinedogg/fenrir/tree/29eb075afe1ab61490196a7272fd21b5b6313cfc) contains dynamic ports, scoped cleanup, `--proxy-service-name`, and input isolation. Do not assume `main`, the published images, and that branch contain identical fixes.

Before the disk swap:

1. Select one coherent chart/CRD/operator/agent/proxy/Wolf set. Pin chart/source commits and every container digest, including Steam/compositor images.
2. Inspect OCI metadata/build provenance and command-line support. Verify that the chosen operator accepts both sharing-key and proxy-service-name flags and implements the needed CRD fields.
3. If image provenance cannot be established, build reviewed source commits in an independently available builder/CI and publish immutable images to a controlled registry. Do not depend on this workstation to rebuild its replacement environment.
4. Verify cold-start timeout/retry behavior, scoped Service cleanup, session port allocation, runtime PodSpec propagation, fake-udev input support, and the Wolf compositor compatibility patch. The inspected multi-user branch is a starting point for review, not proof that every fix is in every image.
5. Render the chart with explicit overrides; reject default `main` tags or generated snapshot tags such as `7/merge`. Validate CRDs against the selected operator and Kubernetes version.

Use one user/session initially. Preserve the ability to add sessions later, but first prove restart, cleanup, storage retention, and input isolation. The workstation has one physical GPU; time slicing does not add GPU memory or performance.

## 4. Prepare the Fedora laptop before touching hardware

### Required handoff

- Clone Cogito on the laptop and verify GitHub read **and push** access. The workstation's `gh-cogito-ops` SSH alias and keys are not provided by a clone.
- Install verified `talosctl` 1.13.5, a Kubernetes-1.34-compatible `kubectl`, Flux CLI, Helm, Kustomize, `just`, the repository's rendering tools, and 1Password CLI. Set up Moonlight as the test client and confirm its available hardware decoders.
- Use the project's toolchain when needed. Avoid a blanket fresh-cache Mise install with `latest` declarations. Any resolving Mise command uses `MISE_JOBS=2`, the normal persistent cache, and `--locked` if a lockfile exists. Stop on the first network/resource failure.
- Securely provision `kubeconfig`, `talosconfig`, 1Password authentication and required vault access, SOPS/age material where needed, and Git credentials. Generated configuration and secrets stay in ignored files with restricted permissions. Do not commit or paste credentials into this plan.
- Verify the existing render workflow (`minijinja-cli` followed by `op inject`) works from the laptop; inspect the rendered worker without printing secrets into logs.
- Verify laptop DNS resolves `k8s.internal` and management node names, the API certificate validates, Talos authentication works, and LAN/VPN routes reach the management subnet. Do not bypass Kubernetes TLS verification.
- Stage the ISO, installer reference/digest, checksums, rendered worker configuration, recovery notes, and Talos client on the laptop. Have a USB boot device and local keyboard/monitor available.
- Preserve any unpushed repositories, unique workstation credentials, SSH configuration, desired Steam saves, and personal files separately. Keeping the old NVMe is rollback, not the only backup of irreplaceable data.

Example read-only preflight, run with laptop-installed binaries and the correct context:

```sh
COGITO_DIR="$HOME/git/cogito"
export KUBECONFIG="$COGITO_DIR/kubeconfig"
export TALOSCONFIG="$COGITO_DIR/talosconfig"
kubectl config current-context
kubectl get nodes -o wide
kubectl -n cilium get cm cilium-config -o yaml
kubectl -n cilium get ds cilium
kubectl get ciliumloadbalancerippools,ciliumbgpclusterconfigs,ciliumbgppeerconfigs,ciliumbgpadvertisements
kubectl get svc -A -o wide
kubectl get storageclass
kubectl -n flux-system get kustomizations,helmreleases
```

Also inspect Talos versions/extensions on the existing control planes, GPU plugin ConfigMap and node labels, router BGP sessions, current Flux health, and storage health. Use authenticated Talos endpoints already in the laptop configuration. Stop on the first connectivity/authentication failure and diagnose it before proceeding.

**Acceptance:** repeat management and Git checks with this workstation powered off. The laptop must not depend on its DNS, SSH agent, local credential store, cached files, or a service it hosts. Restore power only to finish backups if needed; do not swap disks until this test passes.

### Fill in the execution record

| Required value | How to choose/verify |
| --- | --- |
| `GAME_NODE` and management FQDN | Unique worker hostname, reflected in Talos, DHCP/DNS, labels and manifests |
| `GAME_NODE_IP`, wired MAC and interface | Reserved address in the Cogito node subnet; inspect the actual RTL8125 interface |
| New NVMe model, serial, capacity | Physically verify and match Talos disk discovery before installation |
| `GAME_VIP` and gaming DNS name | Unused IP in the existing pool, checked against Services, router and reservations |
| Disk budgets | EPHEMERAL, game filesystem, free-space margin, initial PVC sizes |
| Display target | Start SDR 1080p60; then select intended resolution, refresh rate and codec |
| Test games | At least one small known-working Proton/Linux game and the actual desired games |
| Artifact lock | Schematic, ISO checksum, installer/extension/container digests, source and chart commits |

Check the desired games' Proton/anti-cheat support individually before committing to Talos as the daily gaming host. A functioning stream cannot make an unsupported game run. Keep Windows-only/unsupported game requirements in the go/no-go decision.

## 5. Prepare Cogito's worker support and GitOps changes

Make implementation changes in reviewed commits, with node onboarding and application enablement separate. This document does not authorize running them immediately.

### Worker rendering

Add `talos/schematics/<GAME_NODE>.yaml.j2` and `talos/machineconfig/<GAME_NODE>.yaml.j2` using the existing cluster identity. Set `machine.type: worker`; preserve the existing API URL, CNI-none configuration, kube-proxy choice, pod/service ranges, and KubePrism integration.

Review these first-worker assumptions in `talos/mod.just`:

- `controller` selects the first filename from all nodes. Select an actual control plane explicitly so an alphabetically earlier worker cannot become the bootstrap/config endpoint.
- `add-nodes` currently adds all machines as both Talos nodes and endpoints. Keep endpoints restricted to control planes; workers may be node targets.
- Validate `machine-controller` and the exported `IS_CONTROLLER` value through the real renderer. A worker must not receive control-plane configuration or CA signing material through string/truthiness mistakes.
- Existing apply helpers assume resolvable installed nodes. Document the fresh node's maintenance-IP initial apply separately.

Use the new NIC's MAC/interface, not Iggy's bond members or Intel-specific kernel arguments. Iggy uses MTU 9000; verify the new link, VLAN and Cilium path before selecting an MTU. A 1500-byte baseline is useful only when compatible with the effective node/CNI configuration; do not introduce an unexplained mixed-MTU path. Preserve current cluster settings until measured evidence requires a change.

The base already enables unprivileged user namespaces needed by Steam. Review inherited hugepages and broad GPU labels rather than copying Iggy's performance tuning, dual-3090 power limits, or P2P settings.

### Scheduling and GPU allocation

Use a dedicated gaming node label and a proposed `workload.cogito/gaming=true:NoSchedule` taint. Audit tolerations **before** applying the taint: Cilium, NFD, NVIDIA plugin/GFD, input-device plugin, storage helpers/CSI, and required monitoring must still run. Existing NFD control-plane tolerations alone are insufficient for the proposed taint.

Add a named gaming configuration to the existing NVIDIA plugin ConfigMap:

```yaml
version: v1
sharing:
  timeSlicing:
    resources:
      - name: nvidia.com/gpu
        replicas: 2
```

Select it only on `GAME_NODE` with `nvidia.com/device-plugin.config: <gaming-profile>`. Keep the existing default configuration for Iggy. Check the rendered ConfigMap namespace: the app Kustomization targets `cluster-infra`, despite the namespace written in the raw ConfigMap.

The Wolf container and the game container each request one `nvidia.com/gpu` allocation. With two advertised shares they can use the same physical 5070 Ti. Confirm plugin allocation settings support this arrangement. This provides neither VRAM isolation nor two physical GPUs. Admit one session and do not schedule LLM workloads there initially.

Set `runtimeClassName: nvidia`, the worker selector and required tolerations through supported User/App PodSpec fields. Inspect the resulting Deployment: the selected operator must actually preserve them. Request sensible CPU/memory for the game and sidecars, leave OS headroom, and measure before adding restrictive CPU limits. Start with a 4 GiB memory-backed `/dev/shm`; include its consumption in the pod memory budget.

### Single fresh NVMe storage

Set the EPHEMERAL limit **in the initial machine configuration**, before its first provisioning. A reasonable starting budget is 200 GiB for container images/logs, adjusted for the actual disk. Changing this later does not shrink an existing filesystem. [Talos system volume documentation](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/system)

Create a partition-backed `UserVolumeConfig` named `local-hostpath` on the verified installation disk. Its `/var/mnt/local-hostpath` mount matches the existing OpenEBS base path. Example shape, to validate with Talos 1.13.5 and size for the actual replacement disk:

```yaml
apiVersion: v1alpha1
kind: VolumeConfig
name: EPHEMERAL
provisioning:
  maxSize: 200GiB
---
apiVersion: v1alpha1
kind: UserVolumeConfig
name: local-hostpath
provisioning:
  diskSelector:
    match: system_disk
  minSize: 500GiB
  grow: true
```

The example requires a sufficiently large disk; choose a bounded `maxSize` instead if reserving unallocated space. Keep 15–20% filesystem free space operationally. Verify `u-local-hostpath` is ready and mounted before creating any game PVC; otherwise a hostpath helper can write to an unintended filesystem. [Talos user volume documentation](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/user)

Explicitly use `openebs-hostpath` with delayed binding and correct PV node affinity. Do not inherit default Ceph storage accidentally. Persist `/home/retro`, Steam libraries, Proton prefixes and saves. Choose capacity from the game list; hostpath PVC size is not a filesystem quota.

Inspect Fenrir's PVC owner references and deletion behavior before storing real data. Stopping/deleting a Session must preserve the user's library and saves. Use independently managed PVCs or change ownership/lifecycle if the operator would garbage-collect them. Set a suitable reclaim policy and test backup/restore; `Retain` alone is not a backup.

## 6. Hardware transition and worker onboarding

1. Complete laptop independence, source/artifact and game-compatibility gates. Record baseline cluster health and take the normal cluster configuration/etcd recovery backup to independently accessible storage.
2. Shut down the workstation. Remove and label the original NVMe; store it disconnected. Install the fresh blank NVMe. Do not leave the original disk available to Talos installation.
3. Record firmware settings. Verify UEFI boot, GPU detection, virtualization/IOMMU settings needed by the selected configuration, and the wired link. Do not blindly disable Secure Boot or copy unrelated kernel flags.
4. Boot the staged Talos image. From the laptop, identify the maintenance IP, NIC and **new disk serial**. Match the install target to that evidence, not an assumed `/dev/nvme0n1` name.
5. Validate the rendered worker config, disk budgets, installation artifact and worker role. Apply it once to the maintenance IP using Talos's initial unauthenticated maintenance mode. `--insecure` here is only for the initial Talos maintenance API; subsequent administration uses authenticated Talos configuration.
6. Let installation finish and reboot from NVMe. Do not run `talosctl bootstrap`, generate new cluster CAs, or change existing control-plane membership.
7. Verify the worker registers, Cilium is healthy, pod DNS/egress and cross-node traffic work, BGP is established, and the new node does not disrupt existing VIPs. Check Talos logs, extensions and storage mounts.
8. Validate required daemon tolerations and apply the gaming taint/labels. Keep game workloads disabled until GPU and storage checks pass.
9. Reboot once more and confirm node readiness, GPU allocation and storage mounts survive.

Go/no-go: existing cluster remains healthy, the new worker is Ready, control-plane count remains five, and all checks can be performed from the laptop. If the node cannot join, stop and diagnose the specific failure; do not rebuild the functioning cluster around it.

## 7. GPU, display, audio and input proof

Run short-lived GPU test pods pinned to the worker using the intended RuntimeClass:

- Verify 5070 Ti identity, 16 GB VRAM, expected driver version and absence of driver/API mismatch.
- Run a Vulkan render test and a short H.264/HEVC NVENC encode; test AV1 separately with a capable Moonlight client. Check kernel logs for NVIDIA Xid errors.
- Identify the NVIDIA DRM render node by PCI vendor/device mapping. The Ryzen also has an AMD iGPU; neither `renderD128` nor Shrinedogg's `renderD129` is a safe assumption. Device existence alone does not prove correct selection.
- Confirm the selected GBM/Vulkan libraries load inside both Wolf and the game image. Carry over the relevant GBM backend search path and NVIDIA Vulkan ICD selection when required by those images.

Use the selected patched Wolf image and **Sway for initial SDR validation**: the reviewed deployed App manifest sets `RUN_SWAY: true`, even though portions of the notes discuss Gamescope. Treat Gamescope/HDR as a later compatibility test, especially if Xid 109 occurs.

Preserve the fork's entrypoint initialization/root ownership workaround where required by the actual image; validate writable home, XDG runtime, compositor and Pulse socket readiness. Do not duplicate operator-injected environment entries such as PUID or NVIDIA driver capabilities. The reviewed Steam image lacks `pactl`; do not depend on it or impose unverified Pulse sink/source names.

Cogito currently has no generic input-device plugin. Add a worker-scoped, pinned generic-device-plugin configuration exposing `/dev/uinput` as the `squat.ai/uinput` resource expected by the selected User configuration; verify the device and kernel support exist. Audit its taint tolerations and resource availability. Keep resource requests consistent with the plugin actually installed.

Retain the fork's pod-private `/dev/input` and fake-udev mechanism. Validate agent capability requirements, `/run/udev` visibility and device creation. Avoid importing the whole host input directory as a shortcut. Wolf privilege in Shrinedogg's dual-NVIDIA setup addresses a specific encoding problem; test what this single-NVIDIA worker requires. If privileged operation is needed, confine it to the dedicated gaming workload and record why.

Test keyboard, mouse, controller hotplug/disconnect, focus, rumble where available, and reconnect. Steam Input may need to be disabled per game if its kernel-global virtual devices are not visible in the session's private device tree. Verify sound without running a second host audio stack.

DLSS/NVAPI is a later milestone: if a game needs it, use version-matched driver DLLs and the appropriate Proton/DXVK NVAPI settings. Pin and verify the extraction source, persist files with the game data, and coordinate updates with the driver. This is container/game setup, not installing a `.run` driver on Talos.

## 8. Deploy and validate Fenrir through Cilium

Create a `dreamcast` namespace and a Cogito app subtree under `kubernetes/apps/dreamcast/`, using the repository's Flux source/Helm/Kustomize conventions. Include ordered dependencies for CRDs/operator, configuration/Secrets, User/App resources and the proxy. Permit required workload privileges through the namespace's applicable admission controls. Keep pairing material and authentication secrets in Cogito's existing secret workflow.

Deploy the pinned operator/proxy first, then one User and one small test App. Place the GPU session on `GAME_NODE`; proxy/operator may use an existing node. Explicitly set the sharing key, proxy service name, reserved VIP and `externalTrafficPolicy: Cluster`. Confirm there is one shared external IP and distinct Service port tuples.

The reviewed feature branch allocates blocks starting with:

| Function | First session port | Protocol |
| --- | --- | --- |
| Agent API | 8443 externally, target 8443 | TCP |
| RTSP | 48010 | TCP |
| Stream control | 47999 | UDP |
| Video | 48100 | UDP |
| Audio | 48200 | UDP |

Later blocks add 1000 to each external port. These values describe the inspected branch, not a guaranteed published-image contract. Derive firewall rules from the **actual pinned code, Session status and generated Services**, including proxy pairing/control ports. Do not substitute a generic Sunshine port list. Restrict the agent API to its required callers; if the selected controller exposes it on the shared VIP, account for that in the actual service/firewall policy.

Keep initial access on trusted LAN networks; allow only required client subnets and intercomponent traffic. Verify any existing network policies and router ACLs, including return paths. Add VPN testing after LAN succeeds; public port forwarding is outside the initial rollout.

Validation order:

1. Proxy reachable, manual host addition in Moonlight works, pairing survives proxy restart. Routed discovery need not work automatically.
2. Session launches from cold and warm states; the client receives the shared VIP and correct allocated ports. Test the selected fork's extended cold-start timeout/retry behavior.
3. Confirm pod sockets, Service endpoints and session allocation agree. Exercise a BGP ingress node different from the GPU backend, plus proxy on a different node.
4. Use Hubble/Cilium drop evidence and targeted captures to trace UDP from client to GPU pod and replies back. Check route symmetry requirements, DSR dispatch support and PMTU, including ICMP handling.
5. On the official drivers, launch Steam, sign in, install at least one selected game, and play it over Moonlight. Run that game at SDR 1080p60 H.264 at a modest bitrate for 30 minutes. Record Moonlight network loss, dropped frames, encode/decode timing, GPU utilization, thermals and Xid events. Require no sustained network loss, no driver resets, working audio/input, and no accumulating latency.
6. Advance separately to target resolution/refresh, HEVC or AV1, higher bitrate and VPN. Compare against LAN baseline; do not mix all changes into one test.
7. Stop/start a session, restart operator/proxy, reboot the worker and reconnect. Confirm pairing and saves survive, stale Services disappear, the VIP remains stable, and other cluster Services stay healthy.

If streaming stalls, classify it before changing Cilium:

| Evidence | Next action |
| --- | --- |
| No VIP or different session IP | Inspect pool eligibility, sharing-key/namespace, port collisions and Service conditions |
| VIP advertised but connection fails | Inspect BGP next hops, node/router routes, ACLs, endpoints and readiness |
| Control works, UDP loses packets | Inspect actual allocated ports, DSR replies, drops and PMTU; test the cross-node path |
| Low network loss but high encode time | Inspect NVENC selection, compositor, GPU contention and power/thermal behavior |
| Xid or Vulkan/GBM failure | Inspect driver/image/render-node pairing; stop codec/compositor changes until stable |
| Black screen with input/audio | Check compositor/display negotiation and frame capture before altering routing |
| Pairing works but cold launch fails | Inspect proxy timeout, operator reconciliation and image startup time |

BBR and BIG TCP are not proof of healthy UDP streaming. Preserve Cogito's global networking settings initially. If a Cilium-specific change becomes necessary, reproduce it in a small scoped test, change one variable, record before/after evidence, and verify existing VIPs before retaining it.

## 9. Milestones, gates and rollback

| Milestone | Deliverable and acceptance gate | Rollback |
| --- | --- | --- |
| M0: laptop and artifacts | Workstation-off administration succeeds; coherent source/image pins and installation media staged; desired games assessed | Workstation remains usable on original NVMe |
| M1: configuration | Worker rendering fixed and validated; disk/NIC/IP verified; manifests render without secrets or floating images | Revert unpublished/implementation configuration changes |
| M2: worker | Ready node, healthy BGP/Cilium, mounted local volume, reboot passed; existing cluster unchanged in health | Remove only new worker resources if abandoning; reinstall preserved old NVMe |
| M3: devices | Vulkan, NVENC, input and local PVC persistence pass on 5070 Ti | Disable test workloads; correct or roll back node image/config |
| M4: official-driver gaming baseline | Official Talos NVIDIA artifacts; Steam launches and at least one installed game is playable over Moonlight for 30 minutes with audio/input; restart/reboot retention proven and artifacts/results recorded | Suspend new app reconciliation, stop sessions, preserve PVCs and pairing material |
| M5: newer-driver feasibility | After M4, create a one-off newer-driver image and compare the same Steam/game streaming tests; document build, boot, runtime and rollback results, including failure if infeasible | Restore the verified official-driver image and confirm the same game works |
| M6: intended use | Actual games, target quality/codec and VPN if wanted pass on the selected validated image; restore drill completed; M5 success is not required | Return to the official-driver M4 baseline or last validated configuration |
| M7: optional expansion | Only then evaluate Gamescope/HDR, DLSS, extra users or GPU sharing with other workloads | Revert the individual extension to baseline |
| Future: custom build pipeline | Contingent on M5 demonstrating feasibility; separately scope a maintained image build pipeline, with no pipeline design or implementation in the current work | Continue using the official-driver baseline |

Before rollback, export nonsecret resource definitions, preserve secret material securely, and back up game saves/configuration. Local hostpath data cannot fail over automatically to another node. Preserve the new NVMe too if reverting to the old workstation; its new game data is not present on the old disk.

For application rollback, suspend the relevant Flux reconciliation before manual intervention so it does not recreate workloads. Revert the introducing manifests and pinned images through GitOps; inspect prune behavior so PVCs and CRDs are not inadvertently deleted. For node removal, stop sessions, cordon/drain with local-data consequences understood, and remove only this worker's Kubernetes/Talos/DNS/BGP configuration. A worker has no etcd member to remove. Never reset existing control planes as part of this rollback.

For upgrades, retain the last known-good schematic/installer and all application digests. Validate a new Talos/kernel/driver/toolkit combination with the same GPU smoke tests before changing compositor/game images. Back up pairing data, User/App definitions, persistent home/saves and any version-matched DLSS files. Perform a restore test, not just a successful backup job.

## 10. Implementation checklist and remaining decisions

- [ ] Laptop independently manages Cogito and can push Git changes with workstation off.
- [ ] Live Cilium/Talos/Kubernetes versions and health match the assumptions or this plan is updated.
- [ ] Hostname, MAC, node IP, gaming VIP, disk serial/capacity and display target recorded.
- [ ] Official open-module schematic, installer and ISO verified and staged.
- [ ] Fenrir chart/CRD/source/image provenance resolved; compatible immutable artifacts recorded.
- [ ] First-worker renderer and Talos endpoint assumptions corrected.
- [ ] New node disk layout and mounted OpenEBS path validated before PVC provisioning.
- [ ] GPU sharing profile is node-scoped; runtime/selector/tolerations survive operator generation.
- [ ] NVIDIA render device, Vulkan, NVENC, uinput, compositor and audio pass independently.
- [ ] Shared VIP, dynamic port allocation and cross-node DSR path verified.
- [ ] Pairing, game data retention, reconnect, reboot and restore tests pass.
- [ ] Official drivers run Steam and at least one installed game over Moonlight; baseline artifacts and results recorded before trying newer drivers.
- [ ] One-off newer-driver image attempted after baseline success; feasibility and rollback results documented.
- [ ] If feasible, custom build pipeline recorded as a future milestone with design and implementation deferred.
- [ ] Actual intended games and quality target pass before declaring conversion complete; newer-driver feasibility is not required for a usable official-driver deployment.

The principal uncertainties are runtime image provenance, actual 5070 Ti graphics/encoding behavior under the selected container stack, and the live routed UDP path. Availability of official Blackwell-compatible Talos modules is established, so the initial deployment uses them. The subsequent newer-driver experiment assesses whether maintaining a custom image is practical after Steam and a game are proven on the official baseline.

This plan lives at the explicitly requested `plans/workstation_talos.md`. It is outside the automated `plans/review/*.md` implementation queue contract; publishing its draft PR does not enqueue deployment or authorize the hardware transition.
