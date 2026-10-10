---
name: talos-custom-nvidia-driver
description: Use when Talos needs an NVIDIA driver beyond Factory.
version: 1.0.0
author: timblakely
license: MIT
metadata:
  hermes:
    tags: [talos, nvidia, kubernetes, gpu]
    related_skills: [talos-schematic-node-upgrade, cogito-llm-change-validation]
---

## When to use

A Talos node needs an NVIDIA driver version that is not published in Factory /
GHCR stock extensions (e.g. 615.x while Factory caps at 595.x), or the node's
GPU requires an out-of-tree module build. Not needed for routine driver bumps
that track a Talos version upgrade — use talos-schematic-node-upgrade for that.

# Custom NVIDIA driver stack on Talos

Stock Talos drivers are locked to the Talos version (Factory schematic / GHCR
`siderolabs/nvidia-open-gpu-kernel-modules-production` tags). Any driver not
published there requires a custom signed kernel: the stock Talos kernel boots
with `module.sig_enforce=1` and only accepts modules signed with its built-in
key, so out-of-tree modules need a kernel built with your own signing key.

Build pipeline fork: `github.com/timblakely/talos-nvidia-open-extension`
(fork of shrinedogg/talos-nvidia-open-extension). Images publish to
`ghcr.io/timblakely/*` via CI (`GITHUB_TOKEN`, `packages: write`).

## Key facts / pitfalls

- Kernel and modules MUST come from the same fork/CI run (same signing key).
- `vars.yaml` needs the driver's source checksums refreshed (`hack/update-checksums.sh`;
  needs `shasum` — on Fedora shim it to `sha256sum`/`sha512sum`).
- CI needs repo secret `MODULE_SIGNING_KEY` (private PEM; cert committed at
  `certs/module-signing.crt`; local copy `~/.cache/talos-nvidia-open-extension/`).
- Repin set for a new Talos: `TALOS_VERSION`, `PKGS`, `TOOLS` in Makefile;
  glibc image in vars.yaml must match pkgs' glibc; driver version in vars.yaml.
- GHCR visibility gotcha: packages pushed with a PAT are **private by default**
  and do NOT inherit repo visibility. Only CI pushes via `GITHUB_TOKEN` link to
  the repo and inherit public visibility. Talos nodes pull anonymously, so a
  private installer package fails with `connection reset` during upgrade pull.
  Fix: push via CI, or Settings → Danger Zone → Make public (UI only for
  user-owned packages; REST PATCH is org-only). Anon 401 on raw `/manifests/`
  is normal bearer-challenge; real test is token then 200.
- `talosctl upgrade --image=` rejects combined `tag@digest` refs (containerd
  store lookup fails); pass pure digest `repo@sha256:...` or plain tag. Pin
  machine configs with digest-only form too.
- Crane/podman on this host can't attach OCI source annotations (`--annotation`
  unknown); don't chase the annotation route — use CI publish.
- `nvidia-open-toolkit` extension requires `machine.sysctls.net.core.bpf_jit_harden: "1"`.
- Boot-order noise: ext-nvidia-cdi-gen may log "Driver Not Loaded" once before
  modules load; if GFD labels are correct, ignore.
- Rootless podman on Fedora: bind mounts need `:Z` or SELinux blocks reads.

## Cutover (amnesia-style node, rebase preserves data)

1. GPU idle check: `nvidia-smi` via device-plugin pod on that node
   (`kubectl -n cluster-infra exec <ds-pod>` — daemonset exec may land on
   another node; target the pod explicitly).
2. `talosctl -n <node> upgrade --image=<digest-only installer ref> -m default --drain --drain-timeout=5m`
   (kexec; ~3-5 min; STATE/EPHEMERAL/user volumes incl. Retain hostpath PVs survive).
3. NEVER `reset-node` on nodes with Retain hostpath PVs (wipes `u-local-hostpath`).
4. Validate: node `kernelVersion` = custom kernel, label
   `nvidia.com/cuda.driver-version.full`, `/proc/modules` nvidia loaded, no
   signature denials in dmesg, device-plugin Ready, workload pods self-heal.
5. `just talos render-config <node> && talosctl apply-config --mode auto` to
   land install.image + sysctls without reboot; then push the cogito jj bookmark.

## Repo pins (cogito)

- `talos/machineconfig/amnesia.yaml.j2`: `install.image` = digest-only custom
  installer ref; comment points at the fork + `hack/rebase-amnesia.sh`.
- Future driver bumps: bump fork pins → CI → run `hack/rebase-amnesia.sh` →
  repin cogito → same cutover.
