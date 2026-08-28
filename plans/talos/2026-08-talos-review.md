# Talos Linux review — cogito, 2026-08-28

Read-only review of how cogito uses Talos, checked against every patch and minor
release up to the latest stable (**v1.13.9**, 2026-08-19) and the latest
pre-release (**v1.14.0-rc.2**, 2026-08-25; 1.14.0 GA is slated for 2026-08-27
but is not tagged yet). Nothing was changed.

## 1. Where we are

| Node | Talos | Kernel | containerd | Install image path | Schematic in git == running? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `iggy` | **1.13.5** | 6.18.36 | 2.2.5 | `metal-installer/e81751…` | **no** |
| `kristeva` | 1.12.5 | 6.18.15 | 2.1.6 | `metal-installer/28e765…` | yes |
| `nuc-1` | 1.12.5 | 6.18.15 | 2.1.6 | `installer/f409fc…` (old path) | yes |
| `nuc-2` | 1.12.5 | 6.18.15 | 2.1.6 | `installer/f409fc…` (old path) | yes |
| `nuc-3` | 1.12.5 | 6.18.15 | 2.1.6 | `installer/f409fc…` (old path) | yes |

Kubernetes is 1.34.1 on every node. `talosctl` from mise is v1.13.5 (pinned to
`latest`, so it is simply stale). The live tooling is `talos/mod.just`
(`just talos …`) driving minijinja templates + 1Password.

Talos 1.12.5 was released 2026-03-09. Four of five nodes have not been touched
in ~6 months.

## 2. Materially important

### 2.1 Talos 1.12 is out of community support, and its containerd has a known CVE

Per the 1.13 support matrix, **1.12's End of Community Support was the 1.13.0
release (2026-04-27)**. Four nodes are on an unsupported branch.

More concretely, the v1.12.8 release note says verbatim:

> This release includes an update to containerd v2.2.4 due to v2.1.x releases
> being EOL and affected by CVE-2026-46680.

`kristeva`, `nuc-1`, `nuc-2`, `nuc-3` are all still on **containerd 2.1.6**.
That alone justifies a roll, independent of any feature work.

### 2.2 `iggy`'s committed schematic does not match the machine that is running

This is the highest-risk item in the repo.

* `talos/schematics/iggy.yaml.j2` asks for `siderolabs/nonfree-kmod-nvidia` and
  `siderolabs/nvidia-container-toolkit` → schematic `e817517519355d95c2…`,
  which is what `talos/machineconfig/iggy.yaml.j2` pins as `.machine.install.image`.
* `iggy` is actually running schematic `cfd03958b772d5edc19…`, whose extensions
  are `nonfree-kmod-nvidia-**production**` and
  `nvidia-container-toolkit-**production**` at driver **595.71.05**.

The unsuffixed extension names do not exist in the Image Factory's official
extension list for 1.12, 1.13 or 1.14 — only `-lts` (580.x) and `-production`
(595.x) are published. So the committed schematic is at best relying on a
factory alias that resolves to the LTS line.

`just talos upgrade-node iggy` reads `.machine.install.image` straight out of
git. **The next upgrade of `iggy` would therefore push it off the 595 production
driver it is running today**, underneath the vLLM/llmkube stack, with no warning.
Fix the schematic and regenerate the ID *before* any upgrade touches `iggy`.

### 2.3 Renovate is not watching `talos/`

`.renovaterc.json5` scopes the `flux`, `kubernetes`, `kustomize` and `helmfile`
managers to `kubernetes/**` and `helmfile*`. Nothing matches `talos/**`. So:

* the installer image tags in `talos/machineconfig/*.yaml.j2`, and
* the `kubelet` / `kube-apiserver` / `kube-controller-manager` / `kube-scheduler`
  / `kube-proxy` image tags in `talos/machineconfig/base.yaml.j2`

are invisible to Renovate. That is the mechanical reason everything drifted.
The repo already has a `customManagers` regex that keys off
`# renovate: datasource=docker depName=…` comments — extending its
`managerFilePatterns` to cover `talos/**` (or adding a dedicated entry for the
`factory.talos.dev/metal-installer/<id>:vX.Y.Z` shape) would make Talos and
Kubernetes bumps arrive as PRs like everything else.

### 2.4 Version skew

`iggy` is a full minor ahead of the rest. Supported, but it means the LLM node is
the only one getting kernel and containerd fixes. Worth closing.

## 3. Things 1.13 already offers that we are not using

These apply today; `iggy` is already on 1.13 and the rest get them on upgrade.

**`talosctl reboot --drain` / `talosctl upgrade --drain`** (new in 1.13, with
`--drain-timeout`, default 5m). `upgrade` defaults to `--drain=true`; `reboot`
defaults to false. Our `just talos reboot-node` is a bare
`talosctl reboot -m powercycle` with no cordon and no drain — the exact manual
dance the node-reboot procedure requires. Adding `--drain` to that recipe folds
the cordon/drain/uncordon cycle into the tool.

**New streaming upgrade API** (`LifecycleService.Upgrade`) with `--progress` and
safe parallel upgrades. There is a known limitation —
`.machine.install.extraKernelArgs` is *not* applied by the new API on GRUB nodes
with `grubUseUKICmdline: false`, so the node silently reboots with a kernel
command line that no longer matches its config. **We are not affected**: commit
`383ad799` moved the kernel args into the boot-image schematic, and
`.machine.install.extraKernelArgs` is unset everywhere. That turns out to have
been a good call.

**OOM-handler fixes.** Talos ships a userspace low-memory monitor, enabled by
default since 1.12, that kills whole cgroups on memory *pressure* before the
kernel OOM killer would fire. It has had a run of corrections `iggy` does not
have: cooldown for the QoS trigger (1.13.6), pod-runtime protection (1.13.7),
strict QoS class ordering (1.12.9 / default-on in 1.14). On a node running vLLM
at a 262k-token ceiling this is not academic — 1.13.9 on `iggy` alone is worth it.

**NVIDIA is now on a different supported path.** 1.13's upgrade notes ask users
to uninstall the `nvidia-device-plugin` Helm chart, delete the `nvidia`
RuntimeClass, and move to the NVIDIA **gpu-operator** with
`driver.enabled=false`, `toolkit.enabled=false`,
`hostPaths.driverInstallDir=/usr/local` (operator ≥ v26.3.1). We are still on the
device-plugin chart + `nvidia` RuntimeClass, and it works on 1.13.5 — but it is
now the legacy path. Migration is *not* trivial here: the GPU time-slicing
config, the DCGM exporter, the power-limit job and the fan-control DaemonSet all
hang off that release. Treat it as its own project, not part of a version bump.
Related: CDI is on by default from 1.13, so the `cdi_spec_dirs` line in our CRI
customization may now be redundant — verify against the default before removing.

## 4. Talos 1.14 (rc.2) — what would actually help us

Kubernetes support is 1.33–1.37, so our 1.34.1 stays supported. This is a large
release; the parts relevant to cogito:

**Worth having**

* **`FilesystemTrimConfig`** — periodic `fstrim`, scheduled with a hash over node
  ID and volume ID so trims spread across the cluster. Every disk here is
  SSD/NVMe (970 PRO/EVO, 990 EVO Plus, PNY, CT1000T500SSD8). It is *opt-in for
  upgraded clusters* — the document is absent unless we add it, so trimming
  stays off by default. Cheap, real win.
* **`CRICustomizationConfig`** — replaces the
  `/etc/cri/conf.d/20-customization.part` `.machine.files` entry with a first
  class document, and **CRI configuration changes no longer require a reboot**.
  Given how much GPU/CDI tuning lives in that file, that is a meaningful
  iteration-speed change.
* **`EtcFileConfig`** — same idea for `/etc/nfsmount.conf` (our `nconnect=16`
  NFS tuning).
* **XFS allocation-group geometry.** `mkfs.xfs` sizes AG count to CPU count,
  which on high-core machines with a modest disk yields hundreds of tiny AGs,
  squeezing reflink/rmap metadata and producing spurious `ENOSPC` while the
  filesystem still has free space. 1.14 floors AGs at 64 GiB
  (`filesystem.xfs.minAllocationGroupSize`). `kristeva` hosts the shared
  Kopia/VolSync repository — a reflink- and metadata-heavy workload on a
  high-core box — so this is squarely on point. Caveat: geometry is fixed at
  format time, so it only helps volumes created by 1.14+ (i.e. it needs a wipe of
  the user volume to take effect).
* **`FilesystemScrubConfig`** — periodic `xfs_scrub`. Off by default.
* **`UdevRulesConfig` / `SysctlConfig` / `KernelModuleConfig`** — replace
  `.machine.udev.rules` (the Thunderbolt `authorized` rule on the NUCs),
  `.machine.sysctls` and `.machine.kernel.modules`. That is most of
  `base.yaml.j2`'s tuning surface.
* **`WatchdogTimerConfig`** — there is already a `TODO(blakely): Look into
  watchdog?` commented out in `base.yaml.j2`. It is a supported document and is
  the right answer to the class of hardware lockup the
  `nvme_core.default_ps_max_latency_us=0` arg was chasing.

**Approach with care**

* **Workload isolation (`sandboxd`)** — CRI, kubelet and all pods move into a
  dedicated PID and mount namespace. **New clusters get it on; upgraded clusters
  do not** (`SecurityProfileConfig` is absent, so nothing changes on upgrade).
  Enabling it deprecates all in-tree volume plugins — in particular the in-tree
  iSCSI plugin stops working because the kubelet can no longer reach the host
  `iscsid`. Rook-Ceph goes through CSI so it should be fine, but the NVIDIA
  RuntimeClass path and the hostpath/OpenEBS volumes want testing before we flip
  this on. Do not enable it as part of the version bump.
* **etcd HTTP endpoints move from 2379 to a dedicated 2383 listener.** The
  release note adds: "If `--listen-metrics-urls` was customized, the metrics
  should not move." We already set
  `listen-metrics-urls: http://0.0.0.0:2381` explicitly, so the existing
  Prometheus etcd scrape is safe — but re-verify after the upgrade.
* **NRI is no longer disabled by default** for CRI containerd.
* **`--mode=reboot` is removed** from `talosctl apply-config`; config is applied
  without a reboot by default. `just talos apply-node` passes `*args` through, so
  nothing breaks unless we habitually type `--mode=reboot`.
* **`ghcr.io/siderolabs/installer` stops being published.** We already use
  factory images, but `nuc-1/2/3` still use the *old*
  `factory.talos.dev/installer/…` path while `iggy`/`kristeva` use
  `metal-installer/…`. Normalize all five to `metal-installer`.
* The 1.14 "before upgrade" warning is about migrating `multipath-tools` from
  `ExtensionServiceConfig` to `EtcFileConfig`. **Not applicable** — we do not use
  that extension. Our only extension service is `nut-client`, which is unaffected.

**Not needed here**

Native BGP (we terminate via Cloudflare Tunnel + Envoy), btrfs, declarative
LVM/RAID (Rook-Ceph owns the storage), external virtiofs volumes, DoT/DoH
resolvers, veth pairs, dedicated ETCD/CRI/KUBELET/LOG partitions.

## 5. Config debt worth noting

* **`.machine.network` has been deprecated since 1.12.0** (KubeSpan excepted).
  All of cogito's `bond0` + VLAN 70/90 + Thunderbolt ring config is on the
  deprecated path. Still fully supported in 1.14 — no urgency — but a future
  migration to `BondConfig` / `VlanConfig` / `LinkAliasConfig` is coming. One
  concrete sweetener: `LinkAliasConfig` gained `%d` pattern aliases in 1.13,
  which would give the Thunderbolt links stable names instead of the
  `busPath: 1-*` / `busPath: 0-*` device selectors on `nuc-1/2/3`.
* **`.taskfiles/talos/Taskfile.yaml` is dead code.** It is talhelper-based and
  its preconditions reference `talos/talconfig.yaml` and `talos/talenv.sops.yaml`,
  neither of which exists. Everything real goes through `talos/mod.just`.
  `.taskfiles/bootstrap/Taskfile.yaml` also references `TALOS_DIR`. Candidate for
  deletion.
* **`kubernetesTalosAPIAccess.allowedKubernetesNamespaces`** grants `os:admin`
  to `actions-runner-system` and `system-upgrade`. Neither namespace exists in
  the cluster. Harmless, but it is a live Talos-API grant to namespaces nobody
  owns — either deploy something there or drop them.
* **`kexec_load_disabled=1` on every node.** Talos normally reboots via `kexec`,
  which is why the docs say the extra reboot "adds very little time". With kexec
  disabled *and* `-m powercycle` hard-coded in `upgrade-node`, every upgrade is
  two full cold boots per node. The kernel arg is inherited from an upstream
  home-ops schematic where it is commented "Meteor Lake CPU & Intel iGPU" — but
  `iggy` is AMD + RTX 3090 and none of the NUCs are Meteor Lake. If the
  powercycle is not deliberately there for the Thunderbolt ring or the NVMe APST
  quirk, dropping both would make rolls dramatically faster.
* Comment drift in the schematics: `iggy` carries `i915.enable_guc=3 # Meteor
  Lake CPU & Intel iGPU` on an AMD/NVIDIA box; `kristeva` has
  `siderolabs/intel-ucode # AMD CPU`; `iggy` has `siderolabs/amd-ucode # AMD CPU`
  (correct) next to `siderolabs/i915`-style Intel args. Cosmetic, but confusing
  next time.
* `talosctl` is `latest` in `.mise.toml` but the installed binary is v1.13.5 —
  `mise up talosctl` gets 1.13.9.

## 6. Suggested sequence (nothing done yet)

1. `mise up talosctl` → v1.13.9.
2. **Fix `talos/schematics/iggy.yaml.j2`** to name the `-production` extensions,
   regenerate the schematic ID (`just talos gen-schematic-id iggy`, expect
   `cfd03958b772d5edc19…`) and update `.machine.install.image`, so git matches
   the running node. Do this *before* anything upgrades `iggy`.
3. Normalize `nuc-1/2/3` from `factory.talos.dev/installer/…` to
   `factory.talos.dev/metal-installer/…`.
4. Roll the 1.12.5 nodes. Sidero's supported path is "latest patch of every
   intermediate minor", so **1.12.5 → 1.12.11 → 1.13.9**. Order:
   `kristeva` first, then `nuc-1`, `nuc-2`, `nuc-3` strictly one at a time,
   waiting for Ceph `HEALTH_OK` and etcd quorum between each. Then `iggy`
   1.13.5 → 1.13.9. Use `--drain` (or the existing drain procedure).
5. Add the Renovate manager for `talos/**` so this does not silently drift again.
6. Then consider Kubernetes 1.34 → 1.36 (`just talos upgrade-k8s`). **Audit
   `base.yaml.j2`'s apiServer `extraArgs` first**: both `ImageVolume` and
   `MutatingAdmissionPolicy` graduated to GA in Kubernetes 1.36, and the
   `runtime-config: admissionregistration.k8s.io/v1beta1=true` entry may no
   longer be needed or valid. A stale feature gate will refuse to start the
   apiserver.
7. Hold 1.14 until GA plus a patch or two. When it lands it is mostly a
   config-modernization project (the multi-document migration), with two items
   that stand on their own merit: `FilesystemTrimConfig` and reboot-free CRI
   config changes.

## Sources

- [Talos releases](https://github.com/siderolabs/talos/releases)
- [Talos 1.13 support matrix](https://docs.siderolabs.com/talos/v1.13/getting-started/support-matrix)
- [Talos 1.14 support matrix](https://docs.siderolabs.com/talos/v1.14/getting-started/support-matrix)
- [Upgrading Talos — v1.13](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/lifecycle-management/upgrading-talos)
- [Upgrading Talos — v1.14](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/lifecycle-management/upgrading-talos)
- [NVIDIA GPU (proprietary drivers) — v1.13](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/hardware-and-drivers/nvidia-gpu-proprietary)
- [OOM handler — v1.14](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/system-configuration/oom)
- [Kubernetes v1.36 release notes](https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/)
