---
name: talos-custom-extensions
description: "Build and deploy custom Talos system extensions and images."
version: 0.1.0
author: Tim, Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [talos, system-extensions, nvidia, ghcr, kubernetes]
    related_skills: [gpu-llm-serving]
---

# Talos Custom Extensions & OS Images

## When to Use

- A Talos node needs a driver/kernel-module version the Factory does not ship (e.g. a newer NVIDIA driver line).
- Building custom system-extension images or a custom installer image.
- Cutting a single Talos node over to a custom OS image without a self-hosted Image Factory.

Talos has no ad-hoc module install: everything is baked into the OS image by the schematic, and siderolabs extension versions are pinned to the Talos minor version — a newer driver line than the official extension registry carries requires a custom build.

## Procedure

1. Establish live state before planning. Read the running driver version from GFD node labels, the node's schematic ID from `https://factory.talos.dev` API, and the Talos version. Check the official extension registry (`skopeo list-tags` / OCI tag list on `ghcr.io/siderolabs/<ext>`) to confirm the wanted version really is unavailable — it decides between a schematic bump and a custom build. Completion criterion: driver version, schematic, Talos version, and registry availability all observed, not inferred.

2. For a custom build, fork a working extension repo (e.g. a community nvidia-open extension) and make the fork PUBLIC — nodes and CI then pull extension images anonymously and no PAT is needed anywhere. Prefer GITHUB_TOKEN + `packages: write` permission over Docker Hub secrets for ghcr pushes from Actions.

3. Repin the fork coherently before triggering CI: driver version, TOOLS tag matching the target Talos version, kernel version, and the tarball SHASUMS for the new driver release. Checksums are usually computed by an earlier CI job — if you edit pins while a run is in flight, CANCEL the stale run before it burns an hour compiling against old checksums. Generate a module signing key and set it as an Actions secret (`module.sig_enforce=1` is on the Talos kernel cmdline, so unsigned modules simply will not load).

4. Build the installer image locally with the imager instead of deploying a self-hosted Image Factory service — for a single-node cutover `install.image` is just a plain image reference; no factory needed. Run the imager container privileged with `--net=host`:

   ```
   podman run --rm --privileged --net=host -v "$WORK:/out:z" \
     ghcr.io/siderolabs/imager:vX.Y.Z installer \
     --system-extension-image=<ext1> \
     --system-extension-image=<ext2> ...
   ```

   The positional argument is a built-in BASE PROFILE NAME from `profile.Default` (`installer`, `metal`, `iso`, …) — `installer` is an output KIND inside the profile, not a subcommand. A custom profile YAML goes over stdin as `-` with `baseProfileName` for merging. Version defaults to the imager's own build tag and the base installer is pulled at that matching tag, so use an imager pinned to the node's Talos version. Output is `installer-amd64.tar` in the output dir; `podman load` it and push to your ghcr repo.

5. Verify image internals before touching the node: the extension ID/version/compatibility live in `/manifest.yaml` INSIDE each extension image's layers, not in OCI manifest annotations — but the imager itself validates them and rejects incompatible extensions, so a successful installer build is the strongest check.

6a. Before proposing cutover, prove the node is actually idle: query GPU utilization and compute processes via the node's device-plugin pod (`nvidia-smi` through `kubectl exec`), and check hostname-pinned GPU workloads by their resource limits — a hostname-selected Deployment/StatefulSet can't escape the reboot but reschedules and reloads itself afterward, so it is a wait/ask decision, not a blocker. Run `talosctl apply-config --dry-run` with the rendered machine config first and read the full diff — expect reordering noise in list sections (e.g. kernel modules); the real deltas should be exactly the intended ones. Ask the user to confirm the window whenever the node hosts interactive workloads (gaming, GPU sessions).

6b. Before any destructive cutover, inventory node-local data. On k8s nodes, list hostpath PVs (including `local-hostpath` provisioner volumes) and any retained PVs on the node: `reset-node` wipes `u-local-hostpath` and destroys retained hostpath data; `talosctl upgrade` does not. Prefer `talosctl upgrade --insecure-skip-verify --reboot-mode --image <your-installer>@sha256:...` — in v1.14 the reboot flag is `--reboot-mode` (older docs say `--on-reboot`). The upgrade sequence drains, runs the installer rebase (rewrites only OS partitions; STATE/EPHEMERAL and user volumes survive), then kexec/reboots.

6c. To verify what actually went into a pushed installer image without booting it: pull it with skopeo and inspect the UKI — the installer UKI embeds its own profile/kernel sections, so kernel version (`uname -r` string like `6.18.54-talos`) and cmdline (`module.sig_enforce=1`) are readable directly from the artifact; bsdtar parses the concatenated-cpio initramfs segments that GNU tar and hand-rolled parsers choke on.

7. Post-cutover verify: Talos version, `install.image` pinned by digest in the machine config, extension modules loaded (`lsmod`, driver version endpoint), GPU visible to the workloads that need it, and PVs still bound.

## Pitfalls

- Never guess a CLI contract from `--help` output when the tool vendors a config struct: read the flag-to-config mapping in source (`cmd/.../root.go` + the profile struct's yaml tags) before hand-writing an invocation. Both the 'installer is a subcommand' and 'positional is a path' misreads came from help-text shape, not behavior.
- Never assume a newer official extension exists for a Talos version: extension images are pinned to the Talos minor line; check the registry tag list first.
- Never edit version pins mid-CI-run and let the old run finish — earlier-phase checksums go stale and later phases fail an hour later.
- Never reset-node a k8s node without first checking for retained hostpath PVs; `talosctl upgrade` preserves them, reset does not.
- Never rely on OCI manifest annotations for extension identity — read `/manifest.yaml` inside the image, or trust the imager's compatibility rejection as the gate.
- GHCR push failing with `received unexpected HTTP status: 403 Forbidden` on the bearer token means the pushing credential lacks `write:packages`, not bad auth: `gh auth refresh -s write:packages` (the device flow parks waiting for Enter before polling — send it, then wait for the browser authorize).
- When node hostnames don't resolve through local systemd-resolved, talosctl fails to dial: pass explicit `--nodes <ip> --endpoints <ip>` instead of debugging DNS.
- In jj-managed repos (cogito): `jj describe` the cutover change locally, push only after the node validates — a rolled-back node should not leave a pushed config pinning a broken image.

## Quick reference

- Schematic inspect: `curl -s https://factory.talos.dev/v1alpha/schematics/<id>`
- Registry tags: `skopeo list-tags docker://ghcr.io/siderolabs/installer` (or crane/podman)
- Node driver truth: GFD (geforce-go-deployment) node labels / `kubectl get nodes -o json | grep -i nvidia`
- Cutover: `talosctl upgrade --reboot-mode --image ghcr.io/<you>/installer-amd64:<tag>@sha256:<digest>`

Related: `gpu-llm-serving` covers the k8s GPU lane on the node after the OS change; this skill covers the OS/extension layer beneath it.
