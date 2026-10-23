# Dreamcast — Moonlight game streaming on Cogito

`dreamcast` is Cogito's game-streaming stack: a Moonlight client pairs with a
**Fenrir** (upstream name: **Direwolf**) operator, which starts **Games on
Whales Wolf** session pods on the **`amnesia`** gaming node. Steam (or a
synthetic test app) renders into Wolf's virtual Wayland display, Wolf encodes
with NVENC, and Moonlight streams it over the LAN.

The name is the lineage: Games on Whales → Fenrir → Sega Dreamcast, and the
public endpoint is `ophelia.internal` (Felicia, the Dreamcast's mascot).

- App manifests: `kubernetes/apps/dreamcast/` (this directory)
- CRDs: `kubernetes/crds/fenrir/` (vendored, own Flux Kustomization)
- Host prerequisites: `amnesia` Talos machine config + schematics
  (`talos/machineconfig/amnesia.yaml.j2`, `talos/schematics/amnesia.yaml.j2`)
- Input device plugin: `kubernetes/apps/cluster-infra/uinput-device-plugin/`
- GPU sharing profile: `kubernetes/apps/cluster-infra/nvidia-device-plugin/app/gpu-sharing-config.yaml`
- Running differential log vs upstream/fork: [`plans/fenrir-upstream-findings.md`](../../../plans/fenrir-upstream-findings.md)
- Original plan + dated execution record: [`plans/archive/workstation_talos.md`](../../../plans/archive/workstation_talos.md)

> **This README is the operational reference.** The two `plans/` documents are
> historical: they carry the dated evidence trail and the open investigations.
> When they contradict this file about *current* pins or configuration, this
> file (and the manifests) are correct.

---

## 1. What runs where

| Piece | Runs on | Notes |
| --- | --- | --- |
| `direwolf-operator` | any node (`nuc-1` today) | Reconciles `User`/`App`/`Session`/`Pairing`; creates session Deployments + Services |
| `moonlight-proxy` | any node (`nuc-2` today) | Client-facing PIN/pairing/launch API, one replica |
| session pods (Wolf + wolf-agent + app) | `amnesia` only | Created transiently by the operator per launch; `nodeSelector: kubernetes.io/hostname: amnesia` |
| `uinput-device-plugin` | `amnesia` only | `squat.ai/uinput` ×2 |
| NVIDIA device plugin | `pci-0300_10de` nodes | `amnesia` selects the `gaming.yaml` time-slicing profile |
| `tim-steam` PVC (600 GiB) | `amnesia` hostpath | `openebs-hostpath-retain`, `/var/mnt/local-hostpath` |

Public endpoint: `http://ophelia.internal:47989/pin/` (plain HTTP) and
`:47984` (HTTPS), both on the shared LoadBalancer VIP `192.168.69.100`.

Verified live (2026-10-14): namespace `dreamcast` Active; operator + proxy
Running; `direwolf` Service `192.168.69.100` with `47989/TCP,47984/TCP`;
Apps `steam` (id 2) and `testball` (id 1); User `tim` with
`status.publicPinURL: http://192.168.69.100:47989/pin/`; `tim-steam` PVC Bound
at 600 GiB; three `Pairing` objects; no active Session.

## 2. End-to-end flow

1. Moonlight discovers/adds `ophelia.internal` and opens the PIN page served by
   `moonlight-proxy` (plain HTTP on 47989). The fork's pin page collects a
   **username** and binds the pairing to the matching `User` CR.
2. The proxy creates a `Pairing` CR; the operator materialises Wolf's client
   certificate, and the client completes pairing.
3. Launching an app `POST`s `/launch`; the proxy creates a `Session` CR named
   for user + app.
4. The operator creates the session Deployment — the app PodSpec from the `App`
   CR **plus injected Wolf and wolf-agent sidecars** — allocates a per-session
   TCP/UDP port block, and creates a per-session Service that shares the proxy's
   VIP via the LB sharing key.
5. The operator calls Wolf's API through the agent port: resolve the app by
   title, start the stream, and hand the client the RTSP endpoint.
6. Wolf owns the virtual Wayland display, the `uinput` gamepad, and the Pulse
   virtual sink. Gamescope runs inside the app container; NVENC encodes the
   capture; Moonlight decodes.
7. When the client disconnects, Wolf reports the session ended and the operator
   deletes the `Session`; the PVC and pairing survive.

## 3. GitOps topology — three Kustomizations, two prune settings

A subtree change only lands if **all** owning Kustomizations reconcile. The
`fenrir` app KS `dependsOn: fenrir-crds`; `session-config` `dependsOn: fenrir`.

| Kustomization | Path | Prune | Why |
| --- | --- | --- | --- |
| `fenrir-crds` (flux-system) | `kubernetes/crds/fenrir` | false | CRDs are never pruned |
| `dreamcast` (flux-system) | `kubernetes/apps/dreamcast` | false | namespace wrapper |
| `fenrir` (dreamcast ns) | `kubernetes/apps/dreamcast/fenrir/app` | **true** | operator + proxy: ordinary lifecycle |
| `session-config` (dreamcast ns) | `kubernetes/apps/dreamcast/session-config/app` | **false** | `User` and `App` CRs own the game PVC — see §7 |

Both app KSs render through the repo-standard `components/ks/app` component,
whose `postBuild.substituteFrom` runs Flux envsubst over the rendered objects.
That is why `wolf-entrypoint.yaml` writes `$${init_script}`: a single `$var`
would be substituted at build time into an empty string. This bit us in PR #174
("escape entrypoint variable from Flux substitution"). **Any shell you add to
this subtree must be written for envsubst.**

`kubernetes/flux/cluster/` wires the subtree into the cluster; nothing here
needs an Ingress or Gateway — game streams are arbitrary UDP and no L7 proxy can
carry them.

## 4. Image provenance and pins

Nothing in this stack floats. Everything is digest-pinned.

| Component | Image | Why this and not the published tag |
| --- | --- | --- |
| chart | `oci://ghcr.io/games-on-whales/charts/direwolf-operator@sha256:d097c154…` | Upstream chart, digest-pinned |
| CRDs | vendored at `kubernetes/crds/fenrir/`, from fork `29eb075` | HelmRelease runs `crds: Skip` (both install and upgrade) so the chart's **older bundled CRDs** can never clobber the vendored ones |
| operator | `ghcr.io/timblakely/fenrir-operator@sha256:7a73d323…` | shrinedogg `29eb075` + [`patches/fenrir-operator-fixes.patch`](../../../patches/fenrir-operator-fixes.patch), built by CI |
| moonlight proxy | `ghcr.io/timblakely/fenrir-moonlight-proxy@sha256:9c8576cc…` | shrinedogg `29eb075` as-is, built by CI |
| Wolf sidecar | `ghcr.io/timblakely/wolf@sha256:4e5d97f7…` | Wolf `5ee830a` + upstream held-modifier fix #459; retains Shrinedogg `9d062c45…` runtime/compositor layers |
| wolf-agent | `docker.io/shrinedogg/wolf-agent@sha256:f51e52ce…` | fork image |
| Steam app | `ghcr.io/games-on-whales/steam@sha256:4f88a5e3…` | upstream GoW image |
| uinput plugin | `ghcr.io/squat/generic-device-plugin:2cc50b0@sha256:dc192e16…` | upstream |

**Do not "helpfully" bump these tags or swap our builds for
`docker.io/shrinedogg/*`.** The published set is internally inconsistent: OCI
build attestations show operator `v0.1.3` ← `14b57e1`, agent `v0.1.3` ←
`29eb075`, proxy `v0.1.2` ← `9501ab4` (old main, pre multi-user pairing). The
published proxy does not understand the pin page's username field and cannot
pair against these CRDs.

### Rebuilding Wolf, the operator, or proxy

- Wolf: [`.github/workflows/amnesia-wolf-image.yaml`](../../../.github/workflows/amnesia-wolf-image.yaml)
  checks out the original image's Wolf source `5ee830ae0e03322a6cf044652f5ea271f60161f0`,
  applies [`patches/wolf-held-modifiers.patch`](../../../patches/wolf-held-modifiers.patch)
  from upstream commit `579e72adc88b593c1c5e3805a7baffeb14942e29`
  ([wolf#459](https://github.com/games-on-whales/wolf/pull/459)), and replaces
  only `/wolf/wolf` in the pinned Shrinedogg base. Its GStreamer, patched
  compositor, fake-udev and audio supervision remain from that base. The build
  verifies that the original handler fails and the backport passes an
  event-level regression test before publishing to GHCR. Push the
  `amnesia-wolf-held-modifiers` bookmark with a build-file change, or manually
  dispatch the workflow; pin the emitted digest as `WOLF_IMAGE` afterward.
  This backport retains Wolf's original API.
  Verify an anonymous pull before deploying: this namespace has no registry
  pull secret. If the package is private, change its visibility in GHCR
  package settings first. The published backport passed the anonymous check.
  After changing `WOLF_IMAGE`, end the old Session in Moonlight and launch
  again: this operator updates only metadata on an existing session Deployment,
  so a fresh Session is needed to adopt the new image and stream state. The
  Steam PVC survives this lifecycle (§7).
- Proxy: [`.github/workflows/amnesia-fenrir-proxy-image.yaml`](../../../.github/workflows/amnesia-fenrir-proxy-image.yaml)
  — plain build of pinned `29eb075`.
- Operator: [`.github/workflows/amnesia-fenrir-operator-image.yaml`](../../../.github/workflows/amnesia-fenrir-operator-image.yaml)
  — checks out `29eb075`, `git apply`s the repo patch (verified with
  `--check` first), builds, pushes to GHCR with `GITHUB_TOKEN`.
- The operator/proxy workflows are triggered by pushes to **specific legacy branch names**
  (`amnesia-operator-timeout`, `amnesia-app-selection`,
  `amnesia-wolf-app-registration`, `amnesia-steam-600-video`,
  `amnesia-gaming`). Pushing `main` builds nothing. Those bookmarks still exist
  in the repo; reuse one, or edit the workflow's `on.push.branches`, then pin
  the resulting digest in `fenrir/app/helmrelease.yaml`.

### What our patch actually changes (`patches/fenrir-operator-fixes.patch`)

Upstream and the fork both leave Wolf's app discovery/selection **commented
out**. Three behaviours, all live-verified:

1. **Bounded agent dial.** The session controller dials the fresh agent Service
   with no dial timeout; a cold CNI-programming path blocked ~90 s, the
   one-minute session reaper killed the `Session`, and the client sat on
   "Starting…". A 3-second `net.Dialer` timeout lets the fork's own workqueue
   retry do its job.
2. **App registration.** Resolve the requested title through Wolf `ListApps`
   (case-insensitive); if absent, `AddApp` using the K8s `App`'s numeric `id`
   as the Wolf app ID, copy the video/audio GStreamer pipelines from the
   `Wolf UI` entry (falls back to `apps[0]`), honour `App` `wolfConfig` flags,
   and fail loudly on an ID collision or an empty pipeline template.
3. **App selection.** The patched build sends `AppID` when starting the stream.
   Without it Wolf streams its default Wayland app: Moonlight goes fullscreen
   with *changing decoder statistics* and a black picture — which looks like a
   network failure and is not.

Default Wolf process runner is `/bin/sleep 86400`. The placeholder in
upstream's commented example (`sh -c 'while :; do …'`) **exits code 2 under
Wolf's runner**, Wolf then tears down the compositor, `wayland-1` disappears,
and the app container waits forever.

## 5. Fork vs upstream (source of truth: the two `plans/` docs)

**Upstream Fenrir** (`games-on-whales/fenrir`) is "the leader of the pack —
control multiple distributed instances of Wolf in K8S". At the reviewed
snapshot (`ec6c640`) it has no per-session port allocation, no shared-VIP
sharing key, no `--proxy-service-name`, no username-scoped pairing, and the
Wolf `ListApps`/`AddApp`/`AppID` paths are commented out.

**shrinedogg's fork** (`shrinedogg/fenrir`) adds what a real multi-user
deployment needs. Our baseline is `29eb075` on `feat/multi-user`:

- per-session port-block allocation and scoped Service cleanup;
- `--lb-sharing-key` / `--proxy-service-name` so every per-session Service
  shares the proxy's VIP;
- a `User` controller that publishes `status.publicPinURL`;
- pod-private `/dev/input` per session (see §6 input);
- wolf-agent implements Wolf's **fake-udev** protocol in Go: on hotplug it
  writes `/run/udev/data` entries and broadcasts synthetic libudev netlink
  events in the pod namespace, so SDL/Steam see controllers appear;
- stream-reconciliation retry and stale `trackedSessions` cleanup;
- the operator appends `NVIDIA_DRIVER_CAPABILITIES=all` to the app container
  itself (per the fork author's deployment notes) — never declare it yourself.

**shrinedogg's later work (2026-10-13, after our pin)** on the same branch:

- `c7a46898` — gate stream setup on a ready session pod, plus a 5 s connect /
  30 s request timeout on Wolf API calls. Overlaps our dial timeout; the fork
  also reports that a fresh Deployment's transient 0/0 status used to pass the
  readiness gate.
- `fb1663fa` — send `client_settings.motion_controller_override`. Wolf parses
  `client_settings` **strictly** (once the object is present every field is
  required), so newer Wolf images reject every `AddSession` from an older
  operator and the reaper kills the session ~60 s after launch.

**If you upgrade to Wolf ≥ 0.2.0, take these two commits too.** They are not
in `29eb075`, so our patched operator will fail against Wolf ≥ 0.2.0. The
held-modifier backport keeps the original API and does not need them. Note also
that the fork's author independently converged on the same diagnosis we made in
§9 (privileged Wolf for NVENC) and §12 (Steam Input pads can never be scoped
per session) — read his notes before re-deriving them.

**Our Wolf difference (2026-10-15):** Shrinedogg's pinned `9d062c45…` image
was created on June 11 and labels its Wolf source as `5ee830a`; it predates
the September 7 merge of [wolf#459](https://github.com/games-on-whales/wolf/pull/459).
Factorio Ctrl-click transfers failed from Moonlight on Linux with default
game bindings. We backport the upstream fix while preserving that image's
compositor and the older Fenrir API. This finding applies to the inspected
digest; it does not establish the contents of Shrinedogg's current tags or
the behavior of his current deployment.

## 6. Permissions — the part that actually cost time

**Namespace Pod Security is `privileged`** (`enforce`/`warn`/`audit`). That is
not local to this app: Cogito's `components/namespace` patch applies it to
every namespace, so it is inherited, not configured here. Wolf and Steam still
need it — Wolf hotplugs `uinput` devices mid-session and Kubernetes has no
equivalent of Docker's `device_cgroup_rules`, so opening late-appearing
`/dev/input/event*` requires `privileged: true`.

### GPU shares

One RTX 5070 Ti is time-sliced into **two** advertised `nvidia.com/gpu` units
(`gaming.yaml`, `replicas: 2`, selected by the node label
`nvidia.com/device-plugin.config: gaming.yaml`). A full Steam session consumes
**both**: one for the Wolf sidecar, one for the app container. The per-container
request is load-bearing — CDI driver/device injection is per-allocated-container,
so an app container with no `nvidia.com/gpu` request gets no render node and
produces a black stream. With two shares the node admits exactly **one**
session; delete the previous session's pod before launching another (verified:
node capacity `nvidia.com/gpu: 2`, `squat.ai/uinput: 2`).

`squat.ai/uinput` ×2 comes from the hostname-pinned
`uinput-device-plugin` DaemonSet and matches the GPU share count one-for-one.

### Input

Wolf creates the gamepad via `uinput`; the agent publishes it through fake-udev
into the pod-private `/dev/input` emptyDir. Deliberately **not** the host
`/dev/input`: uinput pads are kernel-global with no creator identity, so
mounting the host directory makes every session enumerate every other session's
pads. Consequence for games: **Steam Input's own emulated pads are also
kernel-global with no creator identity, so they can never be scoped per
session.** Per game, set controller options to *Disable Steam Input* so the game
reads Wolf's pad directly (menus keep working — Big Picture reads the Wolf pad).
The agent sidecar needs `NET_ADMIN` (netlink broadcast); it does not run a
udev daemon.

### Ctrl/Shift held input (Wolf #459)

Older Wolf synthesizes modifier presses/releases around keyboard packets but
only recognizes generic Ctrl/Shift codes when deciding whether the actual key
is itself a modifier. Moonlight can send left/right-specific codes; Wolf then
immediately releases the physical modifier. Text shortcuts can still work
because each letter packet briefly restores its modifier flag, while held-key
actions and modified mouse clicks fail. Inputtino's key-repeat can mask this
on `uinput`; the Wayland virtual keyboard has no such recovery.

The backport tracks physically held modifiers per session and synthesizes
only modifiers that are present in packet flags but not already held. The
build test calls the actual packet handler and records the compositor-bound
GStreamer events for ten generic/left/right modifier codes, subsequent letters,
left/right clicks, release, synthetic fallback, and session isolation. No
compositor switch or Factorio key remap is required. Factorio defaults are
**Shift-click** for a stack and **Ctrl-click** for inventory/fast entity
transfer; test both after connecting to the new session.

Verified live after rollout (2026-10-15): the Steam session was 4/4 Ready with
zero container restarts and Wolf image ID `sha256:4e5d97f7…`. The same
modifier-only API packets used before the fix were read through `XQueryKeymap`
on the session's Xwayland display after 150 ms. Both left/right Ctrl and
left/right Shift remained held, then released on key-up; left Ctrl and Shift
had failed this check before the backport. The retained Steam PVC UID stayed
`83553cba-070a-470a-9255-befb8bacb00f`. The user then confirmed both Ctrl-click
and Shift-click transfers work in Factorio.

### Privilege summary

| Container | Privilege | Reason |
| --- | --- | --- |
| app (Steam) | `privileged`, `runAsUser/Group: 0`, `hostIPC: true` | late-created `/dev/input` nodes; shared Wayland/Pulse sockets |
| wolf sidecar | `runAsUser/Group: 0`, `NVIDIA_*=all`, `squat.ai/uinput: 1` | GOW `gosu`/supervisord privilege-drop crash loop; opens the `uinput` pad |
| wolf-agent | `capabilities.add: [NET_ADMIN]` | fake-udev netlink broadcast |
| `uinput-device-plugin` | `privileged` | kubelet device-plugin socket + `/dev` |

### The Wolf root-entrypoint ConfigMap (`session-config/app/wolf-entrypoint.yaml`)

Mounted over Wolf's own `/entrypoint.sh`, and it does two things that are easy
to break:

1. Forces `UNAME=root PUID=0 PGID=0 HOME=/root` and sources
   `/etc/cont-init.d/*.sh` manually. The GOW image's default `gosu`/supervisord
   privilege-drop crashes in a loop as a non-root user. Do **not** re-declare
   `PUID`/`PGID`/`UNAME`/`NVIDIA_DRIVER_CAPABILITIES` as container env in
   `user.yaml`: the Wolf entrypoint exports the first three, the fork's operator
   appends the fourth, and duplicate env keys make the server-side-apply patch
   invalid — so the session Deployment is never created and the reaper kills the
   session after 60 s. No duplicate volume names either; same failure class.
2. Repairs the retained Wolf config (§11 audio bug) at every pod start.

`$${...}` escaping here is mandatory — see §3.

## 7. Storage and the PVC lifecycle trap

`tim-steam`: 600 GiB, `openebs-hostpath-retain`, `ReadWriteOnce`, mounted at
`/home/retro` — login state, library, Proton prefixes, saves.

Three sharp edges, all confirmed:

- **The `App` PVC is owned by the `User`, not the `Session`.** Deleting a
  Session keeps the data; **deleting the `User` garbage-collects the PVC**.
  That is precisely why `session-config` sets `prune: false` and why the
  `User`/`App` objects must never be removed from their Kustomization without
  first detaching the PVC. Flux GC on removal *will* delete the claim.
- **`Retain` is not a backup and hostpath has no failover.** `dreamcast` is in
  no backup system in this repo (the `kopiur` CRs cover other apps only). The
  data lives in a directory on `amnesia`. Take an independent backup before
  touching the `User`, a driver upgrade, or a node rebase.
- **Resizing is metadata-only.** Hostpath has no quota: enlarge the **bound PV
  first, then the PVC request**, and have `allowVolumeExpansion: true` on the
  class (the stock `openebs-hostpath` class has `reclaimPolicy: Delete` and no
  expansion, which is why `openebs-hostpath-retain` exists — same
  `/var/mnt/local-hostpath` base path, `Retain`, expansion on). Matching an
  already-enlarged PV/PVC does not resize any filesystem; actual free disk is
  the only limit.

The app container `chown -R`s its own `/home/retro` at startup because the
operator mounts a fresh per-app subdirectory of the shared PVC.

## 8. Networking

- Cilium LB-IPAM pool `192.168.69.0/24`, advertised over BGP to the router
  (`loadBalancer.mode: dsr`, Maglev, global DSR).
- **Sharing key on both sides.** The Service carries
  `lbipam.cilium.io/sharing-key: direwolf` and the operator runs
  `--lb-sharing-key=direwolf --proxy-service-name=direwolf`. Mismatched keys
  split the VIP across two addresses and the RTSP handshake times out. The chart
  also emits the legacy `metallb.universe.tf/allow-shared-ip` annotation.
- One VIP, distinct port tuples: proxy 47989/47984; per-session Services join
  the same address for agent API + RTSP + control/video/audio UDP. The fork
  allocates the first block at agent 8443, RTSP 48010/TCP, control 47999/UDP,
  video 48100/UDP, audio 48200/UDP, **+1000 per subsequent session**. Derive
  firewall rules from live `Session` status and generated Services, never from a
  generic Sunshine port list.
- `externalTrafficPolicy: Cluster` deliberately. `Local` complicates shared-IP
  eligibility and can send traffic to a node without the backend.
- DNS: `ophelia.internal` resolves via external-dns → UniFi. UniFi external-dns
  had a `domainFilters` allow-list, so the name needed an **explicit filter
  entry** (`kubernetes/apps/network/unifi-dns/app/helmrelease.yaml`) or it
  silently never resolved.
- TLS material is cert-manager-managed by the chart: `direwolf-self-signed-issuer`
  → `direwolf-ca-cert` → `direwolf-ca-issuer` → `direwolf-cert` (SANs
  `direwolf,direwolf.dreamcast,direwolf.dreamcast.svc`). No manual certificate
  work.

## 9. Talos host prerequisites (`amnesia`)

`amnesia` is a control plane **and** the gaming box: Ryzen 9900X, 64 GiB, one
RTX 5070 Ti 16 GB (Blackwell), Talos v1.14.2 / Kubernetes v1.34.2.

### Extensions actually installed (verified via `talosctl get extensions`)

```
amd-ucode 20260916            realtek-firmware 20260916
nvidia-open-modules 615.78.08-v1.14.2
nvidia-open-firmware 615.78.08-v1.14.2
nvidia-open-toolkit 615.78.08-v1.19.1
uinput v1.14.2                 modules.dep 6.18.54-talos
```

### Machine config requirements

```yaml
machine:
  sysctls:
    kernel.yama.ptrace_scope: "1"   # Wine (see below)
    net.core.bpf_jit_harden: "1"    # required by nvidia-open-toolkit
  kernel:
    modules: [nvidia, nvidia_uvm, nvidia_modeset, nvidia_drm, uinput]
  nodeLabels:
    workload.cogito/gaming: "true"
    nvidia.com/device-plugin.config: gaming.yaml
```

Plus `EPHEMERAL` capped at 400 GiB and a `local-hostpath` `UserVolumeConfig`
(`minSize: 500GiB, grow: true`) on the system disk, mounted at
`/var/mnt/local-hostpath` — the OpenEBS base path. Set `EPHEMERAL.maxSize` in
the **initial** config: it does not shrink an existing filesystem afterward.

**The four NVIDIA modules must be listed explicitly.** The custom modules
extension blacklists them in `modprobe.d`, so a node without `kernel.modules`
boots with no GPU at all. `uinput` is listed for the same reason.

### ptrace: Wine needs it

Talos defaults `kernel.yama.ptrace_scope=2` (admin-only). Hi-Fi RUSH exited ~10 s
under Proton: `strace` showed Wine's `process_vm_writev` and fallback
`PTRACE_ATTACH` failing `EPERM`, launcher exit `222`, plus kernel ptrace denials.
Kernel Yama docs explicitly describe Wine's use of *permitted tracers* under
mode `1`, so `ptrace_scope: "1"` is the fix — a deliberate host security
tradeoff, applied to `amnesia` only; other nodes keep their policy.

### User namespaces

Steam's pressure-vessel runtime requires `user.max_user_namespaces`, which
Talos defaults to `0`. Our shared `talos/machineconfig/base.yaml.j2` already
sets `user.max_user_namespaces: "11255"` cluster-wide. The symptom if it ever
regresses is distinctive: **Steam exits with code 71 in a ~2 s restart loop**
and `console-linux.txt` says "Steam now requires user namespaces to be enabled".
Check with `cat /proc/sys/user/max_user_namespaces` from any pod on the node.

### The custom NVIDIA stack, and why it is not a Factory image

NVIDIA 615.78.08 is newer than what Talos Factory ships for this Talos line.
Talos builds its kernel with `CONFIG_MODULE_SIG_ALL=y` and boots
`module.sig_enforce=1`, so out-of-tree modules are rejected with
`key was rejected by service` unless the *booted kernel* embeds the signing
certificate — and `module.sig_enforce=0` cannot override it (the parameter is
set-once). Any driver beyond Factory therefore needs a kernel built with your
own key, and kernel + modules + installer must come from the **same build**.

Pipeline: [`github.com/timblakely/talos-nvidia-open-extension`](https://github.com/timblakely/talos-nvidia-open-extension)
(fork of `shrinedogg/talos-nvidia-open-extension`; images under
`ghcr.io/timblakely/*`). `talos/machineconfig/amnesia.yaml.j2` pins the
installer **by digest only** (`ghcr.io/timblakely/installer-amd64@sha256:864d59e4…`)
— `talosctl upgrade --image=` rejects combined `tag@digest` refs. Never revert
that image to `factory.talos.dev`: the factory kernel rejects these modules.

Extension rules worth knowing before you rebuild:

- modules + firmware + toolkit must all be installed together and carry the
  **same driver version** (GSP firmware is version-locked); never mix with
  `siderolabs/nvidia-open-gpu-kernel-modules-*` or
  `siderolabs/nvidia-container-toolkit-*`.
- the toolkit registers the `nvidia` containerd handler and generates CDI at
  `/run/cdi/nvidia.yaml`; the cluster-wide kubelet config already adds
  `/var/run/cdi` to `cdi_spec_dirs`.
- CI needs the `MODULE_SIGNING_KEY` secret; the public cert is committed.
- **GHCR visibility:** packages pushed with a PAT are private by default and do
  *not* inherit repo visibility. Nodes pull anonymously, so a private installer
  fails with `connection reset` mid-upgrade. Publish via CI (`GITHUB_TOKEN`).
  An anonymous 401 on a raw manifest GET is the normal bearer challenge.

`ext-nvidia-cdi-gen` logging "Driver Not Loaded" once at boot is benign when GFD
labels come out right.

### Cutover procedure for a rebuilt image

1. Confirm the GPU is genuinely idle (`nvidia-smi` through the node's
   device-plugin pod — a DaemonSet `exec` can land elsewhere) **and** that no
   gaming session is running. This box is a gaming machine; ask before
   rebooting it.
2. `talosctl -n amnesia upgrade --image=<digest-only installer ref> --reboot-mode -m default --drain --drain-timeout=5m`
   (~3–5 min; STATE/EPHEMERAL/user volumes including Retain hostpath PVs
   survive). Note `--reboot-mode` is the v1.14 flag; older docs say `--on-reboot`.
3. **Never `reset-node` on this node** — it wipes `u-local-hostpath` and the
   Steam library with it.
4. Validate: `kernelVersion` matches the custom kernel, extension versions match,
   `nvidia.com/cuda.driver-version.full` label present, modules loaded, no
   signature denials in dmesg, `/dev/nvidia-modeset` present, device plugin Ready.
5. `just talos apply-node amnesia --mode auto` (renders the config and applies
   it) to land `install.image` + sysctls without another reboot, then push the
   bookmark.

## 10. Graphics: driver, devices, DLSS

`wolfConfig.runtimeVariables.renderNode: /dev/dri/renderD128` — the NVIDIA card
on this node. **Do not assume this number.** The host also exposes an AMD
adapter, and on a multi-GPU node the device plugin may allocate a different
card, in which case CDI injects *that* card's host-numbered node and Wolf fails
GPU vendor detection, silently falls back to software x264/x265, the Wayland
display never starts, the app loops on "Waiting for wayland display…", and
Moonlight connects with audio but no video.

| Env var | Where | Why |
| --- | --- | --- |
| `GBM_BACKENDS_PATH=/usr/local/lib/gbm:/usr/lib/x86_64-linux-gnu/gbm` | Wolf sidecar **and** Steam | the CDI hook drops the NVIDIA GBM backend in `/usr/local/lib/gbm`; Mesa only searches the distro path |
| `VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json` | Steam | Steam is privileged so it sees every adapter, and Mesa's loader enumerates AMD as device 0 → Gamescope aborts on modifier negotiation |
| `RUN_GAMESCOPE=true` | Steam | see below |
| `STEAM_STARTUP_FLAGS=-bigpicture` | Steam | Big Picture is the only sane UI at 4K over a stream |
| `dshm` 4 GiB `emptyDir: Memory` | Steam | the 64 MiB default exhausts under Steam's CEF UI → black screen with a cursor |

`RUN_SWAY=true` was removed in PR #210: Sway made the first Big Picture game
overlay run at ~1 fps when Steam was hidden; Gamescope (`gamescope-wl`) gives a
fast first launch and the second-launch-was-fast pattern disappeared. Note
shrinedogg's opposite finding on dual 5090s — Gamescope's Vulkan compositing
triggered NVRM Xid 109 there, so his deployment runs Sway. If Xid 109 shows up
after a driver change, that is the first tradeoff to revisit.

### `/dev/nvidia-modeset` (615 regression, black windows)

After the 615 cutover, DAVE THE DIVER and Endless Legend 2 launched to a black
window with a cursor. Diagnosis chain: DXVK reported
`Presenter: Failed to query present modes: -13`; a native Vulkan Xlib reproducer
also returned `-13` from `vkGetPhysicalDeviceSurfacePresentModesKHR`; the host
and the container both lacked `/dev/nvidia-modeset` even though
`nvidia_modeset` was loaded. Creating char device `195:254` fixed the query
(three present modes). X11 EGL library injection, primary DRM-node permissions,
PRIME offload and explicit-sync flags did **not** help.

Two layers of fix exist. The extension's udev rules now run
`nvidia-modprobe -m` when `nvidia_modeset` loads, so the node exists on the
host (verified: `/dev/nvidia-modeset` present on `amnesia`). The Steam
container additionally `mknod`s it in its **private** `/dev` with mode `0600`
owned by `PUID:PGID` — the fallback for a host without the fix, scoped to that
container. Keep both until a fresh-node check confirms the udev rule alone is
enough.

### DLSS under Proton

DLSS needs `nvngx.dll` and `_nvngx.dll` visible to Proton; without them the
in-game DLSS toggle greys out or the map renders black. Our extension originally
built the driver with `--no-wine-files`, stripping them.

- Now fixed at the host layer: `nvidia-open-toolkit` ships both DLLs at
  `/usr/local/lib/nvidia/wine/` and a CDI discovery patch mounts them read-only
  into NVIDIA containers (verified on `amnesia`:
  `/usr/local/lib/nvidia/wine/{nvngx.dll,_nvngx.dll,nvngx_dlssg.dll}`). Proton
  finds them relative to `libGLX_nvidia.so.0`.
- The Steam entrypoint keeps a **fallback**: symlink from
  `/home/retro/.local/share/nvidia/wine/$driver_version/` on the PVC when the
  host has not injected them. Do not delete it — it covers a fresh PVC and a
  driver/host mismatch, and that cache directory is part of the PVC's backup
  scope.
- Games also need `PROTON_ENABLE_NVAPI=1` and `DXVK_ENABLE_NVAPI=1`, otherwise
  DLSS stays greyed out despite an RTX card.
- After any driver bump the cached DLLs must match the new driver version.

## 11. Audio

Wolf's `POST /api/v1/apps/add` drops `start_audio_server` —
[wolf#465](https://github.com/games-on-whales/wolf/issues/465), fixed in
[wolf#466](https://github.com/games-on-whales/wolf/pull/466), merged into native
`stable` 2026-08-08. **The pinned `shrinedogg/wolf` image predates the fix**, so
apps our operator registers persist `start_audio_server = false` even though the
request sets it true. Steam had video and no sound; `pactl` showed only the
`auto_null` fallback sink. The log lines about creating a virtual sink and
starting an Opus consumer do **not** prove the sink exists — check `pactl` and
the persisted config.

The workaround is part of the Wolf root entrypoint (§6): it rewrites
`start_audio_server` to `true` for the retained `Steam` entry in
`/mnt/data/wolf/cfg/config.toml` before Wolf reads it. Verified symptom-free:
Wolf then logs `Starting audio producer: pulsesrc device="virtual_sink_…"` and
`Created virtual sink: N`.

Because the fix is a **string match** on
```
    start_audio_server = false\n    start_virtual_compositor = true\n    title = 'Steam'
```
it silently no-ops if Wolf's config layout changes or a second app appears.
After pinning a Wolf build that contains #466, delete the block.

Also: do **not** export `PULSE_SINK`/`PULSE_SOURCE` on the Steam container. The
image has no `pactl`, so upstream's lookup exports an empty/bogus name, and
libpulse treats a set-but-invalid device as an explicit request and fails the
stream instead of falling back to Wolf's virtual sink. Silent Steam.

## 12. Known issues and open investigations

| Symptom | Status |
| --- | --- |
| Ctrl-click transfers or held Ctrl/Shift actions fail, while some text shortcuts work | Upstream [wolf#459](https://github.com/games-on-whales/wolf/pull/459) fixes premature modifier release. Our pinned Wolf backports it onto `5ee830a` and tests the actual output events (§6). Verify Factorio Ctrl/Shift-click after reconnecting. |
| Apps registered via the Wolf API get **no video until Wolf restarts** — empty `video_producer_buffer_caps`, malformed `waylanddisplaysrc … ! , width=…`, no frames | **Open upstream** [wolf#489](https://github.com/games-on-whales/wolf/issues/489). Masked in practice: the app is registered once and the retained `config.toml` produces valid CUDA caps on the next Wolf pod. A first-ever registration on a fresh PVC needs a Wolf restart. |
| Controller prompts flip Xbox → keyboard within seconds (Steam Controller only; Xbox pad is stable; reproduces on stable and nightly Moonlight) | **Open, cause unproven.** No USB/IP anywhere in Fenrir or Wolf — input is Moonlight packets → Wolf `uinput`/`uhid`. Narrowed to the Steam Controller/client path. Needs live `/dev/input` inspection plus client mouse-event evidence before touching the host input design. Check the per-game *Disable Steam Input* setting first (§6). |
| Severe 10–15 s jitter every few minutes during long sessions | **Open.** Host side was clean (no NIC errors/drops, no Xid, BGP up). Client is 6 GHz Wi-Fi at ~−67 dBm with power saving on, pushed ~70 Mbps. Client profiles lowered to 1080p60/20 Mbps. Use the Moonlight overlay during a stall to separate network loss from encode/decode delay before changing Cilium. |
| `User.status.publicPinURL` stayed empty after the Service port fix, even after re-annotating the User | **Open.** The pairing fragment URL from proxy logs completes pairing manually; it now populates correctly (`http://192.168.69.100:47989/pin/`), root cause never established. |
| Test Ball audio ticks, sustained frame loss, reconnect, reboot persistence, backup/restore | **Never measured.** Not evidence of health. |

Upstream filing status: our local fixes exist only as the repo patch plus
merged Cogito PRs. **No upstream Fenrir issue or PR has been filed.** Wolf #465/#489
are upstream reports; #459 is an already-merged upstream fix backported here.
Ask the fork maintainer for a coherent versioned source/image set including
#459 and #466. The latter would remove the audio entrypoint workaround; the
modifier-only rebuild deliberately retains it.

## 13. Deploying this stack elsewhere

Requirements in order; each one has already cost someone a session.

1. **Talos node** with an NVIDIA Turing-or-newer GPU, the extension set from §9
   (NVIDIA modules + toolkit, `uinput`), the four NVIDIA modules plus `uinput`
   explicitly in `machine.kernel.modules`, `net.core.bpf_jit_harden=1`,
   `ptrace_scope=1` if Proton games matter, and `user.max_user_namespaces > 0`.
   A driver newer than Factory needs the custom-kernel installer (§9) — plan it
   before you need it, because it changes how you upgrade the node.
2. **NVIDIA RuntimeClass** (`nvidia`) and the device plugin. If the node shares
   the GPU with anything else, a node-selected time-slicing profile whose
   replica count equals *one full session's* demand. Note the plugin rejects
   `replicas < 2`, so "unshared" means no `sharing` block at all.
3. **NFD node affinity**: the device-plugin chart's default
   `…/pci-10de.present` label does not exist here — standalone NFD emits
   `feature.node.kubernetes.io/pci-0300_10de.present`. Same trap bites any
   hostname-plus-`nvidia.com/gpu.present` selector you copy in: that label
   exists on no node in this cluster.
4. **`/dev/uinput` plugin** advertising one share per GPU share the session
   needs.
5. **Pod Security**: the session needs `privileged`. If your namespace policy is
   stricter, nothing schedules and the reason is easy to miss.
6. **LB sharing**: Cilium LB-IPAM pool + BGP, a reserved VIP, the sharing key
   matching between operator flags and Service annotations. No Ingress/Gateway.
7. **DNS**: add the hostname to external-dns *and* to the provider's domain
   allow-list.
8. **Storage**: a hostpath class with `Retain` **and** `allowVolumeExpansion`,
   a real backup story, and a `User` that is never pruned.
9. **Priority**: a `gaming-interactive` PriorityClass above every co-resident
   inference lane (20000 vs `llmkube-low` 1000), on **both** app templates.
10. **Pins**: chart by OCI digest, CRDs vendored with `crds: Skip` on the
    HelmRelease, a source-coherent operator/proxy pair, Wolf and agent pinned,
    envsubst-safe shell.

Do not co-schedule the inference lane onto the gaming card without the priority
class in place and without understanding that a gaming pod preempts it
immediately (§14).

## 14. Co-residency with LLM workloads on `amnesia`

`amnesia` also hosts a preemptible inference lane (`gemma-4-12b`,
`priority: low` → `llmkube-low` = 1000, hostname-pinned).

`gaming-interactive` = **20000** with `PreemptLowerPriority`, so launching a
session reclaims the card from inference immediately. Design rule: **never raise
the LLM lane's priority on this node.** Both App templates carry the class —
Test Ball previously had none (value 0, below every lane) and could therefore
never preempt a running server, which is a silent failure, not a safe default.
Preemption is not a quota: the two time-sliced units are one card with no VRAM
isolation, so co-tenancy is a scheduling convenience, not a capacity plan.

Telemetry is deliberately kept off this box: `fan-control` and `dcgm-exporter`
are hostname-pinned to the inference nodes so no DaemonSet applies a MANUAL fan
policy or power limit to the GPU someone is gaming on. If you re-pin GPU
telemetry DaemonSets, keep that property.

To stop the LLM lane safely, use `spec.suspend: true` (the operator co-owns
`.spec.replicas`), never scale-to-zero by hand.

## 15. Validating a change

1. `kustomize build kubernetes/apps/dreamcast/{fenrir,session-config}/app` —
   the `app` dirs are what Flux reconciles. The **wrapper** dirs (the KS
   definitions) cannot be built standalone: the shared `components/ks/...`
   components load files above their own directory, so plain `kustomize build`
   fails with a "not in or below" security error. Use
   `--load-restrictor=LoadRestrictionsNone` if you must render the wrapper.
2. `kubectl apply --dry-run=server` on the rendered docs — exercises the CRD
   schema and persists nothing.
3. CI runs `flux-local test --enable-helm` (`.github/workflows/flux-local.yaml`,
   image digest-pinned) on any `kubernetes/flux` change. Note the known podman
   quirk: the dreamcast kustomization tests fail on a *pristine* baseline copy
   under podman ("Invalid stdin cannot be passed to build command") — diff
   failures against baseline before blaming your change.
4. `kubectl -n dreamcast get kustomization fenrir session-config` must report
   the pushed revision; then `kubectl -n dreamcast get pods,svc,pvc`.
5. Docs-only changes need no cluster reconcile.

## 16. Session debugging: symptom → first thing to check

| Symptom | Look at first |
| --- | --- |
| Client black but decoder stats changing | App selection / Wolf video source (§4, §10) — not the network |
| "Starting …" forever, then the session vanishes ~60 s later | The reaper. Operator → agent/Wolf API reachability and dial timeouts; check for the "app not found in wolf" message |
| App pod waits on "Waiting for Wayland and Pulse sockets" | Wolf sidecar never came up — its logs, then §10 render node and §12 #489 |
| Wolf tears the compositor down right after start | The Wolf process runner exited (needs `/bin/sleep 86400`) |
| Video, no audio | `pactl` sinks + the retained `start_audio_server` flag (§11) |
| No controller in game, works in menus | Steam Input not disabled (§6) |
| Game exits in ~10 s with no graphics | `ptrace_scope` (§9) |
| Black game window, working Steam UI | `/dev/nvidia-modeset` (§10) |
| DLSS black/greyed | NGX DLL injection + `PROTON_ENABLE_NVAPI` (§10) |
| Steam restart loop, exit 71 | `user.max_user_namespaces` (§9) |
| Session pod Pending | GPU/uinput share arithmetic (§6) |
| PIN page 404 / wrong port | 47989 is HTTP, 47984 HTTPS; the chart's port *names* were historically reversed and the `User` controller builds its URL from the port named `http` |

Session lifecycle gotchas worth internalising: the reaper kills sessions
aggressively, so a slow cold start looks like a hard failure; Wolf reads
`runtimeVariables` once at config load and every session app inherits them; Wolf
parses `client_settings` strictly; and the fork's operator appends
`NVIDIA_DRIVER_CAPABILITIES=all` to the app container itself (reported by the
fork author's deployment notes — our `steam.yaml` deliberately does not declare
it), so duplicate env keys in your template make the Deployment creation fail
outright rather than warn.
