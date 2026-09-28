# Workstation → Talos gaming control plane

Status: Fedora laptop preparation complete; `amnesia` has joined as a control plane and booted from its replacement SSD with the installer USB removed. Gaming setup remains.
Research date: 2026-09-26. Owner/operator: Tim, using the Fedora laptop.

## Decision

Convert the Ryzen 9900X / 64 GB / RTX 5070 Ti 16 GB workstation into a **Cogito control plane named `amnesia` that also hosts dedicated gaming workloads**. Physically remove and preserve its existing NVMe, install a fresh blank NVMe, and administer everything from the Fedora laptop. Start with one Moonlight client and one Steam session through Fenrir and Games on Whales Wolf. First establish a working official-driver baseline: Steam must launch and at least one installed game must be playable over Moonlight. Only after that baseline passes, create and test a newer-driver image to assess feasibility. A custom build pipeline is a future milestone contingent on a successful experiment; pipeline design and implementation are outside this plan’s current scope.

Use Talos 1.13.5 with **official open NVIDIA production kernel modules**, a matching NVIDIA container toolkit, and Cogito's existing Cilium BGP/shared LoadBalancer IP facilities. A custom Image Factory schematic is required; a custom-compiled kernel is **not the expected starting requirement**. NVIDIA explicitly requires open kernel modules for Blackwell, including the 5070 Ti. Reusing a proprietary `nonfree-kmod-nvidia-production` extension would be wrong. [NVIDIA 595.71.05 documentation](https://download.nvidia.com/XFree86/Linux-x86_64/595.71.05/README/kernel_open.html)

This plan uses Shrinedogg's work only for the Talos image, Fenrir, and Games on Whales. It does not adopt his unrelated infrastructure, database, caching, or security architecture. His deployment is useful evidence, but its working RTX 5090 configuration is not proof that this workstation has passed validation.

## 1. Evidence and current Cogito configuration

Reviewed Cogito tree corresponding to GitHub `main` commit `5fb7dc3026bf1404f6c3f4416f3b9f1dfd7e9e5b`. A laptop preflight on 2026-09-27 reached the live cluster: all five control planes were Ready on Kubernetes 1.34.2; Iggy reported Talos 1.13.5, while kristeva and nuc-1/2/3 reported Talos 1.12.5. Cilium agents were Running, the listed Flux Kustomizations were Ready, and `openebs-hostpath` was available. These are point-in-time checks, not a health certification for the hardware transition. Repeat laptop-independence checks before removing the disk.

| Area | Current configuration | Consequence |
| --- | --- | --- |
| Cluster | Five existing control planes: iggy, kristeva, nuc-1/2/3; source specifies Talos 1.13.5 and Kubernetes 1.34.2. Live preflight found Talos 1.13.5 on Iggy and 1.12.5 on the other four; all report Kubernetes 1.34.2 | Add `amnesia` as a sixth control plane and etcd member using the existing cluster identity; do not bootstrap a new cluster. Keep the Talos version difference in view when selecting artifacts |
| Cilium | Chart 1.19.2, kube-proxy replacement, native routing, direct node routes, netkit, endpoint routes | Keep these defaults for the first deployment |
| Load balancing | BGP enabled, L2 announcements disabled, Maglev, **global DSR**, acceleration best-effort | Use existing BGP and IPAM; no MetalLB or second announcement system |
| Addressing | Nodes `192.168.42.0/24`; pods `10.42.0.0/16`; Services `10.43.0.0/16`; LB pool `192.168.69.0/24` | Reserve one unused gaming VIP after a live inventory |
| BGP | All Linux nodes selected; local ASN 64514, router `192.168.1.1`, peer ASN 64513 | New node is automatically eligible; verify router neighbor acceptance and advertisements |
| Talos API proxy | Cilium uses KubePrism `127.0.0.1:7445`; API identity `k8s.internal` | Retain the established API/CA and laptop DNS path |
| GPU | NVIDIA device plugin 0.18.0 in `cluster-infra`, RuntimeClass `nvidia`, GFD plus separate NFD | Extend existing plugin configuration only for `amnesia` |
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

The tags now exist, but their OCI build attestations expose a mismatch: operator `v0.1.3` is based on `14b57e1`, agent `v0.1.3` on `29eb075`, and proxy `v0.1.2` on `9501ab4` (the old main). The proxy lacks the later username-aware pairing flow. A one-off pinned-source proxy build is required before deployment; record its pushed digest, not just its tag. The selected Wolf `v0.1.0` OCI index is `sha256:9d062c45ed7533ba5949db3d739448a83aa6c85a712a41193c496d4b6c1158f8` (AMD64 manifest `sha256:f58ff22962a601441bb5abd8dffaf69113e18ccbfa46346fc8988fd7fcf0ed31`).

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
- Verify the existing render workflow (`minijinja-cli` followed by `op inject`) works from the laptop; inspect the rendered control-plane configuration without printing secrets into logs.
- Verify laptop DNS resolves `k8s.internal` and management node names, the API certificate validates, Talos authentication works, and LAN/VPN routes reach the management subnet. Do not bypass Kubernetes TLS verification.
- Stage the ISO, installer reference/digest, checksums, rendered control-plane configuration, recovery notes, and Talos client on the laptop. Have a USB boot device and local keyboard/monitor available.
- The current NVMe will be removed intact and kept; Talos will be installed only on the fresh replacement drive in the same slot. This swap does not erase or migrate data from the current NVMe. Identify any files that also need an independently accessible copy before the swap, such as unpushed repositories or credentials, and copy only those selected files. A full home-directory backup is not required for this disk swap.

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

**Acceptance:** repeat management and Git checks with this workstation powered off. The laptop must not depend on its DNS, SSH agent, local credential store, cached files, or a service it hosts. Restore power only if selected files still need to be copied; do not swap disks until this test passes.

### Laptop preflight record (2026-09-27)

- Fedora 44. Installed Talos CLI 1.13.5 and used it explicitly; this checkout's Mise configuration still selects Talos CLI `latest` (1.14.1) by default. `kubectl` 1.34.0, Flux 2.7.3, Helm 4.3.0, Kustomize 5.7.1, `just` 1.58.0, Minijinja 2.13.0, and 1Password CLI 2.39.0 are available. Moonlight 6.1.0 is installed.
- Kube context `main` connects to `k8s.internal` at `192.168.42.10` with TLS verification enabled. All five control planes were Ready. The Cilium agent pods were Running, the listed Flux Kustomizations were Ready, and the expected storage classes were present.
- Talos config context `main` was generated with mode-600 credentials. Authenticated Talos API access to Iggy succeeded. Its admin certificate expires 2027-09-27. The temporary local copy of the Talos CA private key was removed after generation.
- GitHub SSH read access and a no-write push dry run succeeded. With Siff powered off, a real push of a temporary branch at the existing `main` commit succeeded, and the temporary branch was deleted. The GitHub CLI itself is not logged in; Git operations use SSH.
- Created the host-scoped 1Password service account `codex-frogtop` with `read_items` access to the `kubernetes` vault only. Its token is stored in the laptop's Secret Service keyring and in a recovery API Credential item in the `Private` vault, which the service account cannot access. Load it into only the needed process from the keyring; do not put it in the repo or a plaintext file. The service-account render and Talos config generation succeeded, and authenticated access to Iggy succeeded.
- The protected age key is available to this checkout; SOPS decryption succeeded with plaintext discarded. Moonlight is installed. The laptop's VAAPI device reports H.264, HEVC Main/Main10, and VP9 decode profiles; it did not report AV1.
- Staged the Talos 1.13.5 `amnesia` schematic and 1.4 GB metal ISO on the laptop. Schematic ID: `6527b5fb5bd39e8b5e6716d98b2aed15cff58d2e133cde984120603315146eeb`; ISO SHA-256: `5d67b45d199d5eb202e3fc92da0824dfffc31a6f9dcffe0250084fe921f9047a`; installer OCI index digest: `sha256:48662d546376390f97e80df973cd8bed0e4f2090d39ae74c0289d8568143f35d`. The laptop-local artifact lock, recovery notes, and mode-600 control-plane configuration are in `~/Workstation-Talos/amnesia/v1.13.5/`. The final control-plane configuration, including 400 GiB `EPHEMERAL` and the observed disk and NIC identities, passed Talos 1.13.5 strict metal validation before apply.
- Copied Talos CLI 1.13.5 into the laptop artifact bundle. Wrote the ISO to the operator-authorized 32 GB PNY USB drive (serial `07012B2999F6FC08`); the drive presents Talos and EFI partitions, and direct readback of the ISO-sized region matched the staged SHA-256.
- With Siff powered off, its IP did not answer ping; laptop DNS still resolved `k8s.internal`, authenticated Talos access to Iggy succeeded, all five pre-existing Kubernetes control planes were Ready, Flux Kustomizations were Ready, laptop-local 1Password service-account access to its `kubernetes` vault succeeded, and GitHub read/push access succeeded. The section 4 workstation-off independence gate passed. The gaming VIP, games, and application image artifacts remain to be selected.

### Hardware and node onboarding record (2026-09-27/28)

- The original Samsung SSD 990 EVO Plus 2TB, serial `S7U6NJ0Y436315F`, was removed intact and preserved. The replacement Samsung SSD 9100 PRO 2TB, serial `S7YCNJ0L214027M`, occupies the same slot. The original disk's data was not erased or migrated.
- A protected etcd snapshot was saved on the laptop at `~/Workstation-Talos/amnesia/recovery/etcd-2026-09-28T0015Z.snapshot`; its SHA-256 is `1a53177d1aa66c44a4aa91b4fb0faab6419fe85577d11998a3d9e44f993d60f6`.
- An initial worker configuration was applied to the replacement disk before the operator clarified that every node must be a control plane. Only Amnesia's new system disk was reset; the control-plane configuration was rendered, strictly validated and applied to that disk. Do not use the retained `initial-worker-applied.yaml` audit artifact as a current configuration.
- The final configuration pins the install target by replacement SSD model and serial, uses DHCP on wired MAC `10:ff:e0:bb:53:d2`, allocates 400 GiB to `EPHEMERAL`, and uses the remaining allocatable disk for `u-local-hostpath`. Talos reported `/dev/nvme0n1` as its system disk, `EPHEMERAL` on partition 4, and `u-local-hostpath` on partition 5. The installer USB is a separate PNY `/dev/sda`.
- Amnesia joined Kubernetes at `192.168.42.15` as a Ready control plane, and etcd promoted it from learner to voting member. It was shut down cleanly, the installer USB was removed, and the operator powered it on again. Talos returned to machine stage `running` with `READY=true`; Kubernetes reports it Ready and schedulable. This confirms independent SSD boot.
- Talos hardware inventory sees two 32 GiB Silicon Power DIMMs (64 GiB installed). Linux exposes about 60.4 GiB to Kubernetes; 2 GiB is configured as hugepages in the shared Talos base configuration, and Kubernetes reports about 57.8 GiB allocatable to ordinary pods. Review whether Amnesia needs the inherited hugepage reservation before gaming workloads.
- The NVIDIA 595.71.05 open modules and container toolkit extensions are present, and all four NVIDIA kernel modules are loaded. NFD publishes `feature.node.kubernetes.io/pci-0300_10de.present=true`; the NVIDIA chart's default affinity expected a different label. The HelmRelease now targets the observed PCI label, so its plugin and GFD DaemonSets run on Amnesia and Iggy. Amnesia selects `gaming.yaml`, advertises two time-sliced `nvidia.com/gpu` units from its single RTX 5070 Ti, and GFD labels it as shared. Iggy retains its default two-physical-GPU profile.
- The router now accepts `192.168.42.15` as a BGP neighbor. Amnesia's Cilium BGP session to `192.168.1.1` is established and advertises the existing `192.168.69.25/32` VIP. Cilium health reaches all six nodes and their pod endpoints. A disposable non-host-network Wolf pod successfully fetched packages, confirming pod DNS and outbound access. Application VIP behavior remains to be checked.
- A short-lived GPU allocation pod identified the RTX 5070 Ti, 16,303 MiB VRAM, and driver 595.71.05. A disposable Wolf-based pod with temporary tools identified the NVIDIA Vulkan device and completed short H.264 and HEVC NVENC encodes. NVIDIA DRM modesetting is on; PCI vendor `0x10de` maps to `/dev/dri/renderD128`. No NVIDIA Xid appeared in the kernel log after these checks. The container runtime printed `ERROR: init 250 result=11` despite zero exit codes; keep that observation for the real session check.
- The first acceptance game is [DAVE THE DIVER](https://store.steampowered.com/app/1868140/DAVE_THE_DIVER/), Steam app 1868140. Steam currently lists it as Steam Deck Verified. The operator selected `192.168.69.100` and `ophelia.internal` for the gaming service. The VIP is now assigned and reachable; the DNS name is pending an external-dns domain-filter update.
- Published Fenrir image attestations show operator `v0.1.3` built from `14b57e1`, agent `v0.1.3` from `29eb075`, and proxy `v0.1.2` from older main commit `9501ab4`. The proxy therefore predates the multi-user pairing code in `29eb075`; do not deploy that proxy with the selected branch's CRDs/operator. Build the proxy from the pinned `29eb075` source and use its immutable digest.
- The pinned multi-user proxy build completed in [GitHub Actions run 36366361406](https://github.com/timblakely/cogito-ops/actions/runs/36366361406). Public pull inspection resolves `ghcr.io/timblakely/fenrir-moonlight-proxy@sha256:9c8576cc92cfcbf20ddc8e2e34b9c198958cdc51dae00e6c07b89bd0433b340c`, with source revision label `29eb075afe1ab61490196a7272fd21b5b6313cfc`.
- The pinned Fenrir session controller creates each app's PVC with a controller owner reference to its `User`, not to the transient `Session`. Session deletion therefore preserves the PVC, but deleting the User causes Kubernetes garbage collection of the PVC. Keep the User managed with pruning disabled, avoid deleting it, and take an independent backup of the library and saves before any User replacement or removal.
- The `dreamcast` GitOps subtree pins the chart by OCI digest, applies vendored CRDs from source commit `29eb075` before the Helm release, skips the chart's older bundled CRDs, and reserves `192.168.69.100` with the external-DNS hostname `ophelia.internal`. PR #169 merged as `7211e9c`; CRDs, Helm release, both pods and the VIP reconciled successfully. The User, input plugin, test App and Steam App are subsequent deployment steps.
- `ophelia.internal` initially did not resolve because UniFi external-dns filtered only `${DOMAIN_NAME}` (`timblakely.com`). PR #170 added the exact `ophelia.internal` filter and merged as `30bbd3d`; the UniFi resolver now returns `192.168.69.100`.
- Before the uinput image upgrade, Amnesia had no `/dev/uinput` and did not register uinput in `/proc/misc`. The 1.13.5 official extension catalog offers `siderolabs/uinput` at `ghcr.io/siderolabs/uinput:v1.13.5` (digest `sha256:a0f5c8a2946d9d6cc09a81136f765e552dfa2ac8b9b7809428dedb6c598d6821`). The updated Amnesia schematic ID is `2b5d5bac65ac2e1f4d620f4b7f29320708cef681a5ffa025cf8e5b48bc4862dd`, and its 1.13.5 metal-installer OCI index digest is `sha256:7ad6bb3742a2316d993a7ac93d528d98a6ab060889c40ec086a1790f0f883a1f`.
- PR #171 merged as `a6888ee`; the pinned image upgrade drained and rebooted Amnesia successfully. The official `uinput` extension appears in Talos, `/proc/modules` lists `uinput`, `/dev/uinput` exists, and the control plane returned Ready. A dedicated `uinput-device-plugin` DaemonSet is staged to advertise two `squat.ai/uinput` shares only on Amnesia, matching the node's two time-sliced GPU units.

### Fill in the execution record

| Required value | How to choose/verify |
| --- | --- |
| `amnesia` and management FQDN | Control-plane hostname is `amnesia`; verify its management FQDN in DHCP/DNS and use the name consistently in Talos, labels and manifests |
| `amnesia` management IP, wired MAC and interface | Talos maintenance mode reports `enp7s0`, MAC `10:ff:e0:bb:53:d2`, DHCP address `192.168.42.15/24`, gateway `192.168.42.1`; reserve the final address and verify DNS |
| New NVMe model, serial, capacity | Talos maintenance mode reports Samsung SSD 9100 PRO 2TB, serial `S7YCNJ0L214027M`, 2,000,398,934,016 bytes at `/dev/nvme0n1`; the preserved original SSD is absent |
| `GAME_VIP` and gaming DNS name | Operator selected `192.168.69.100` and `ophelia.internal`; neither is assigned to a current Service or resolves in laptop DNS yet. Reserve through the final proxy Service and DNS workflow |
| Disk budgets | EPHEMERAL, game filesystem, free-space margin, initial PVC sizes |
| Display target | Start SDR 1080p60; then select intended resolution, refresh rate and codec |
| Test games | DAVE THE DIVER (Steam app 1868140) for first session; add actual desired games after the baseline |
| Artifact lock | Schematic, ISO checksum, installer/extension/container digests, source and chart commits |

Check the desired games' Proton/anti-cheat support individually before committing to Talos as the daily gaming host. A functioning stream cannot make an unsupported game run. Keep Windows-only/unsupported game requirements in the go/no-go decision.

## 5. Prepare Cogito's control-plane gaming support and GitOps changes

Make implementation changes in reviewed commits, with node onboarding and application enablement separate. Node onboarding was authorized and performed; application enablement remains to be implemented.

### Control-plane rendering

Add `talos/schematics/amnesia.yaml.j2` and `talos/machineconfig/amnesia.yaml.j2` using the existing cluster identity. Set `machine.type: controlplane` and `machine.network.hostname: amnesia`; preserve the existing API URL, CNI-none configuration, kube-proxy choice, pod/service ranges, and KubePrism integration.

Review these node-rendering assumptions in `talos/mod.just`:

- `controller` selected the first filename from all nodes. Select `nuc-1` explicitly as the bootstrap/config endpoint.
- `add-nodes` added all machines as both Talos nodes and endpoints. Keep endpoints restricted to control planes; any future workers may be node targets.
- Validate `machine-controller` and the exported `IS_CONTROLLER` value through the real renderer. `amnesia` must receive the existing control-plane identity and etcd signing material.
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

Select it only on `amnesia` with `nvidia.com/device-plugin.config: <gaming-profile>`. Keep the existing default configuration for Iggy. Check the rendered ConfigMap namespace: the app Kustomization targets `cluster-infra`, despite the namespace written in the raw ConfigMap.

The Wolf container and the game container each request one `nvidia.com/gpu` allocation. With two advertised shares they can use the same physical 5070 Ti. Confirm plugin allocation settings support this arrangement. This provides neither VRAM isolation nor two physical GPUs. Admit one session and do not schedule LLM workloads there initially.

Set `runtimeClassName: nvidia`, the worker selector and required tolerations through supported User/App PodSpec fields. Inspect the resulting Deployment: the selected operator must actually preserve them. Request sensible CPU/memory for the game and sidecars, leave OS headroom, and measure before adding restrictive CPU limits. Start with a 4 GiB memory-backed `/dev/shm`; include its consumption in the pod memory budget.

### Single fresh NVMe storage

The NUCs install Talos on a PNY SATA SSD and use a separate `CT1000T500SSD8` disk for a 400 GB `local-hostpath` user volume plus a Rook raw volume. `amnesia` instead has one fresh 2 TB NVMe: Talos boot/state and `EPHEMERAL` live on that system disk, and a separate partition-backed `local-hostpath` user volume takes the remaining allocatable space. Do not add a Rook raw volume to this worker.

Set the EPHEMERAL limit **in the initial machine configuration**, before its first provisioning. Allocate 400 GiB for container images and logs on this 2 TB disk. Changing this later does not shrink an existing filesystem. [Talos system volume documentation](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/system)

Create a partition-backed `UserVolumeConfig` named `local-hostpath` on the verified installation disk. Its `/var/mnt/local-hostpath` mount matches the existing OpenEBS base path. Example shape, to validate with Talos 1.13.5 and size for the actual replacement disk:

```yaml
apiVersion: v1alpha1
kind: VolumeConfig
name: EPHEMERAL
provisioning:
  maxSize: 400GiB
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

## 6. Hardware transition and control-plane onboarding

1. Complete laptop independence, source/artifact and game-compatibility gates. Record baseline cluster health and take the normal cluster configuration/etcd recovery backup to independently accessible storage.
2. Shut down the workstation. Remove and label the original Samsung SSD 990 EVO Plus 2TB (observed serial `S7U6NJ0Y436315F`) without modifying it; store it disconnected. Install the fresh blank Samsung SSD 9100 PRO 2TB in the vacated slot. Do not leave the original disk available to Talos installation. Its existing data remains on that preserved drive.
3. Record firmware settings. Verify UEFI boot, GPU detection, virtualization/IOMMU settings needed by the selected configuration, and the wired link. Do not blindly disable Secure Boot or copy unrelated kernel flags.
4. Boot the staged Talos image. From the laptop, identify the maintenance IP, NIC and **new disk serial**. Match the install target to that evidence, not an assumed `/dev/nvme0n1` name.
5. Validate the rendered control-plane config, disk budgets, installation artifact and node role. Apply it once to the maintenance IP using Talos's initial unauthenticated maintenance mode. `--insecure` here is only for the initial Talos maintenance API; subsequent administration uses authenticated Talos configuration.
6. Let installation finish and reboot from NVMe. Do not run `talosctl bootstrap` or generate new cluster CAs. Allow `amnesia` to join the existing etcd cluster as a learner and then promote to voter.
7. Verify the control plane registers, Cilium is healthy, pod DNS/egress and cross-node traffic work, BGP is established, and the new node does not disrupt existing VIPs. Check Talos logs, extensions and storage mounts.
8. Validate required daemon tolerations and apply the gaming taint/labels. Keep game workloads disabled until GPU and storage checks pass.
9. Reboot once more and confirm node readiness, GPU allocation and storage mounts survive.

Go/no-go: existing cluster remains healthy, `amnesia` is Ready as the sixth control plane and an etcd voter, and all checks can be performed from the laptop. If the node cannot join, stop and diagnose the specific failure; do not rebuild the functioning cluster around it.

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

Deploy the pinned operator/proxy first, then one User and one small test App. Place the GPU session on `amnesia`; proxy/operator may use an existing node. Explicitly set the sharing key, proxy service name, reserved VIP and `externalTrafficPolicy: Cluster`. Confirm there is one shared external IP and distinct Service port tuples.

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
| M1: configuration | Control-plane rendering fixed and validated; disk/NIC/IP verified; manifests render without secrets or floating images | Revert unpublished/implementation configuration changes |
| M2: control plane | Ready node and etcd voter, healthy BGP/Cilium, mounted local volume, SSD-only boot passed; existing cluster remains healthy | Remove `amnesia` from etcd before removing its node resources if abandoning; reinstall preserved old NVMe |
| M3: devices | Vulkan, NVENC, input and local PVC persistence pass on 5070 Ti | Disable test workloads; correct or roll back node image/config |
| M4: official-driver gaming baseline | Official Talos NVIDIA artifacts; Steam launches and at least one installed game is playable over Moonlight for 30 minutes with audio/input; restart/reboot retention proven and artifacts/results recorded | Suspend new app reconciliation, stop sessions, preserve PVCs and pairing material |
| M5: newer-driver feasibility | After M4, create a one-off newer-driver image and compare the same Steam/game streaming tests; document build, boot, runtime and rollback results, including failure if infeasible | Restore the verified official-driver image and confirm the same game works |
| M6: intended use | Actual games, target quality/codec and VPN if wanted pass on the selected validated image; restore drill completed; M5 success is not required | Return to the official-driver M4 baseline or last validated configuration |
| M7: optional expansion | Only then evaluate Gamescope/HDR, DLSS, extra users or GPU sharing with other workloads | Revert the individual extension to baseline |
| Future: custom build pipeline | Contingent on M5 demonstrating feasibility; separately scope a maintained image build pipeline, with no pipeline design or implementation in the current work | Continue using the official-driver baseline |

Before rollback, export nonsecret resource definitions, preserve secret material securely, and back up game saves/configuration. Local hostpath data cannot fail over automatically to another node. Preserve the new NVMe too if reverting to the old workstation; its new game data is not present on the old disk.

For application rollback, suspend the relevant Flux reconciliation before manual intervention so it does not recreate workloads. Revert the introducing manifests and pinned images through GitOps; inspect prune behavior so PVCs and CRDs are not inadvertently deleted. For node removal, stop sessions, cordon/drain with local-data consequences understood, and remove only `amnesia`'s Kubernetes/Talos/DNS/BGP configuration. Remove `amnesia` from etcd membership deliberately before permanently retiring it. Never reset the five pre-existing control planes as part of this rollback.

For upgrades, retain the last known-good schematic/installer and all application digests. Validate a new Talos/kernel/driver/toolkit combination with the same GPU smoke tests before changing compositor/game images. Back up pairing data, User/App definitions, persistent home/saves and any version-matched DLSS files. Perform a restore test, not just a successful backup job.

## 10. Implementation checklist and remaining decisions

- [x] Laptop independently manages Cogito and can push Git changes with workstation off.
- [ ] Live Cilium/Talos/Kubernetes versions and health match the assumptions or this plan is updated.
- [ ] `amnesia` management FQDN, MAC, node IP, gaming VIP, disk serial/capacity and display target recorded.
- [x] Official open-module schematic, installer and ISO verified and staged.
- [ ] Fenrir chart/CRD/source/image provenance resolved; compatible immutable artifacts recorded.
- [x] Control-plane renderer and Talos endpoint assumptions corrected.
- [x] New node disk layout and mounted OpenEBS path validated before PVC provisioning (`/dev/nvme0n1p5` at `/var/mnt/local-hostpath`).
- [x] GPU sharing profile is node-scoped; the existing plugin and GFD run on Amnesia and advertise two shares while Iggy retains its default profile. Fenrir-generated pod placement and tolerations remain to be checked.
- [ ] NVIDIA render device, Vulkan, NVENC, uinput, compositor and audio pass independently.
- [ ] Shared VIP, dynamic port allocation and cross-node DSR path verified.
- [ ] Pairing, game data retention, reconnect, reboot and restore tests pass.
- [ ] Official drivers run Steam and at least one installed game over Moonlight; baseline artifacts and results recorded before trying newer drivers.
- [ ] One-off newer-driver image attempted after baseline success; feasibility and rollback results documented.
- [ ] If feasible, custom build pipeline recorded as a future milestone with design and implementation deferred.
- [ ] Actual intended games and quality target pass before declaring conversion complete; newer-driver feasibility is not required for a usable official-driver deployment.

The principal uncertainties are runtime image provenance, actual 5070 Ti graphics/encoding behavior under the selected container stack, and the live routed UDP path. Availability of official Blackwell-compatible Talos modules is established, so the initial deployment uses them. The subsequent newer-driver experiment assesses whether maintaining a custom image is practical after Steam and a game are proven on the official baseline.

This plan lives at the explicitly requested `plans/workstation_talos.md`. It is outside the automated `plans/review/*.md` implementation queue contract; publishing its draft PR does not enqueue deployment or authorize the hardware transition.
