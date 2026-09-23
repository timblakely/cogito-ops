# Iggy GPU peer access and Talos image — 2026-09-22

## Current result (2026-09-23)

**GPU P2P is working on Iggy.** The user recovered the first failed boot via
BIOS setup and enabled UEFI mode, Above 4G decoding, Re-Size BAR, and XMP 2.
Linux now maps a 32 GiB BAR1 for each RTX 3090. The patched Talos installer
`ghcr.io/timblakely/iggy-talos-p2p-installer@sha256:431ad099a0921ca1f736ce3fcb280ff27f567fdd5764d23236e2d24145b4aa44`
is running, and its `nvidia-open-gpu-kernel-modules-p2p-production` extension
is active. `nvidia-smi topo -p2p r` reports `OK` both ways. CUDA enabled peer
access and verified 8 MiB copies in both directions. NCCL selected `P2P/IPC`
for both directions and passed a two-rank 16 MiB all-reduce. The vLLM startup
log reports `driver confirms PCIe peer access; NCCL P2P enabled at PHB`; its
pod reached Ready with zero restarts. Iggy and the other four nodes are Ready.

**Operational rule:** Talos `--reboot-mode=powercycle` left Iggy powered off
after the installer reboot; the user powered it back on manually. **Only
restart Iggy; never shut it down or use `powercycle`.** Use normal
`-m default` reboot mode for future Talos work.
Direct EFI-variable writes also caused a failed POST before the user recovered
the BIOS setup; future firmware changes should be made in BIOS setup.

The custom installer is private in GHCR. Temporary registry authentication
was removed from Iggy's persistent machine config after the upgrade; the
temporary local credential files were deleted. Its `.machine.install.image`
still names the known-good factory image as a fallback, so do not use the
generic `just talos upgrade-node iggy` workflow: it would revert the P2P
driver. Future Iggy upgrades require a newly built P2P installer and
temporary private-registry pull authentication, or an explicitly approved
change to image visibility.
The `upgrade-node` recipe now refuses Iggy; `reboot-node` and upgrades of
other nodes use Talos's normal `default` reboot mode. `shutdown-node` also
refuses Iggy.

Iggy has two GeForce RTX 3090 GPUs on an MSI MPG X570 GAMING EDGE WIFI
(MS-7C37). The GPUs have no active NVLink connection and `nvidia-smi topo -m`
reports a `PHB` path between them.

## Future Iggy upgrades and verification

`talos/images/iggy-p2p/build.sh` and `installer-profile.yaml` reproduce the
**current** v1.13.5/kernel 6.18.36/driver 595.71.05 image. They are pinned to
those versions; for a newer Talos version, update and verify the kernel source,
Sidero build inputs, NVIDIA driver, userspace toolkit, extension compatibility,
and imager version together. Recheck module vermagic and symbol CRCs against the
target kernel. Pin the published installer by digest.

Before an upgrade, arrange temporary authentication so Talos can pull the
private GHCR image, and confirm the digest is reachable with those credentials.
Do not leave broad-scope registry credentials in the persistent machine config.
Use Talos's **normal restart mode** for the upgrade. Do not use
`just talos upgrade-node iggy`: the factory image in `.machine.install.image`
would replace the patched driver. After Iggy returns, remove temporary pull
authentication and confirm it is absent from the live machine config.

Verify the patched extension, 32 GiB BAR1 on each GPU, `nvidia-smi topo -p2p r`
showing `OK` in both directions, both CUDA copy directions with
`talos/tests/iggy_gpu_p2p.py`, and NCCL `P2P/IPC` with
`talos/tests/iggy_nccl_p2p.py`. Then check both GPUs are allocatable, the vLLM
pod is Ready, and all five cluster nodes are Ready. These checks passed on the
current image. A [post-P2P Qwen benchmark](../llm/qwen-p2p-benchmark-2026-09-23.md)
also passed at the 250 W per-card cap. Its prompt differs from the old run, so
it does not prove a performance gain or loss.

The sections below record the investigation and failed recovery attempts in
chronological order. Their intermediate states are historical.

## Historical investigation: controlled IOMMU test

The original Talos v1.13.5 image used schematic
`cfd03958b772d5edc199bf09cee5e92965c5ef685dfeddfcab6b38fec043d6dc`,
with `intel_iommu=on iommu=pt` and NVIDIA production driver 595.71.05. The
checked-in schematic had unsuffixed NVIDIA extension names and an outdated image
ID; its corrected production-extension form reproduces the running schematic ID.

For the test, Image Factory generated schematic
`d619dc04056a97615c1d14def4b6c7c8fbdac31dac11ddb79323ec53d9235898`.
It differed only by replacing those two IOMMU arguments with `iommu=off`. Iggy
was upgraded to the same Talos version with the same NVIDIA driver. The booted
kernel command line contained `iommu=off`, and the driver and both GPUs loaded.

| Check | `iommu=pt` | `iommu=off` |
| --- | --- | --- |
| `nvidia-smi topo -m` GPU0 ↔ GPU1 | `PHB` | `PHB` |
| `nvidia-smi topo -p2p p` | `NS` | `NS` |
| `nvidia-smi topo -p2p r` | `CNS` | `CNS` |
| `torch.cuda.can_device_access_peer(0, 1)` and `(1, 0)` | `False`, `False` | `False`, `False` |

Disabling the IOMMU did not enable CUDA peer access. Iggy was restored to the
original `cfd03958…` schematic because the IOMMU change offered no P2P benefit.
`iommu=pt` is passthrough mode, not IOMMU disablement. NVIDIA's general
bare-metal P2P guidance calls for disabling the IOMMU, but the patched module
now passes P2P checks with `iommu=pt` on this hardware. This A/B test showed
that the IOMMU setting alone was not the blocker.

After rollback, Iggy was Ready with two allocatable GPUs, the NVIDIA device
plugin was healthy, the two-GPU vLLM pod reached `1/1 Running` with zero
restarts, and all CloudNativePG clusters reported healthy. The vLLM startup log
reported `[p2p] peer access unavailable; NCCL P2P disabled`. Iggy's persistent
`.machine.install.image` was corrected from an old v1.12.5 image to the running
`cfd03958…:v1.13.5` image without a reboot.

## Historical investigation: BAR1, firmware, and driver

The earlier inference that this motherboard needs replacing was incorrect. Both
RTX 3090s advertise PCIe Resizable BAR support up to 32 GiB in
`resource1_resize` (`0x000000000000ffc0`). Their active BAR1 windows were only
256 MiB at that point. The firmware's ACPI host bridge reported no PCIe memory
window above 4 GiB, so Linux had nowhere to place a full-size BAR1.

Iggy's motherboard BIOS is MSI `E7C37AMS.1K0` (2023-02-28). The matching
official BIOS image has UEFI IFR entries for `BIOS CSM/UEFI Mode` at `Setup`
offset `0xFF`, `Above 4G memory/Crypto Currency mining` at offset `0x133`,
and `Re-Size BAR Support` at offset `0x134`. Value `1` selects UEFI, Enabled,
and Enabled respectively. Before the change, the
`Setup-ec87d643-eba4-4bb5-a1e5-3f3e36b20da9` variable had `0` at all
three offsets. Talos booted via UEFI, but BIOS CSM was still enabled. A copy
of that original variable was kept at `/tmp/iggy-setup-original.bin` during
the attempt; it is not a persistent recovery asset. An initial automatic
approval review rejected the EFI-writing pod. The user later explicitly
authorized the write, but it caused a failed POST and the user recovered
the machine through BIOS setup. Future firmware changes belong in BIOS setup,
not direct EFI-variable writes. No BIOS flash was needed.

The stock NVIDIA driver also refuses GeForce PCIe P2P. The
`aikitoria/open-gpu-kernel-modules` fork has an exact `595.71.05-p2p` branch;
commit `97fdda0` contains the P2P change without its later experimental memory
change. It implements BAR1 P2P for RTX 3090s without NVLink. Its requirement is
`iommu=pt`, which Iggy already has, plus a sufficiently large BAR1. The P2P
module replaced the proprietary module extension while keeping the
`595.71.05` userspace toolkit. The original factory image had
`module.sig_enforce=1` on its kernel command line. Secure Boot is disabled,
and the Talos kernel config has
`CONFIG_MODULE_SIG_FORCE` unset. The custom image removes that boot argument
to load the unsigned patched module. Kernel module signature enforcement is
therefore reduced on the running Iggy image.

## Built and locally verified installer

`talos/patches/nvidia-595.71.05-p2p.patch` contains only upstream fork commit
`97fdda0`. `talos/images/iggy-p2p/build.sh` pins the NVIDIA source to official
tag `595.71.05` (commit `51edebee`), Linux `6.18.36`, and the Sidero Talos
kernel build inputs. Five NVIDIA modules were compiled with Sidero's LLVM
22.1.2 toolchain against `6.18.36-talos`. Each module reports driver version
`595.71.05` and the expected kernel vermagic. All imported symbol CRCs match
the corresponding official Talos open-module package; there were no missing
symbols or CRC mismatches.

The resulting custom installer was generated by Talos imager v1.13.5 with the
patched open-module extension and the same official firmware, microcode,
NVIDIA container toolkit, and nut-client extensions. Its embedded kernel
command line includes `amd_iommu=on iommu=pt` and omits
`module.sig_enforce=1`. Local installer tar SHA256:
`5bfc10cee27ac45879c60b3e10401ecad3db4a264c2df313f2ccfe183d4c20fa`.
The image was pushed to
`ghcr.io/timblakely/iggy-talos-p2p-installer:v1.13.5-595.71.05-r1` at manifest
digest `sha256:431ad099a0921ca1f736ce3fcb280ff27f567fdd5764d23236e2d24145b4aa44`.
An authenticated manifest read succeeded, but an anonymous read returned
`unauthorized`: GHCR created this new package as private. Temporary Talos
registry authentication was used successfully for the upgrade, then removed.

`talos/tests/iggy_gpu_p2p.py` checks CUDA peer capability both ways, enables
peer access, and verifies 8 MiB peer copies byte for byte. On the original
driver it reaches the expected failure, `GPU 0 cannot access GPU 1`.

## Historical incident: EFI-variable write and boot recovery (2026-09-23 UTC)

The user explicitly approved the temporary privileged EFI maintenance pod,
the three-setting firmware write, and reboot. Immediately before writing, the
live `Setup` variable SHA256 matched the 1919-byte backup at
`/tmp/iggy-setup-original.bin`:
`5ab44b2abd019c432ba738a1d193bb17047bcfefce4f84357f812e637b5df981`.
The candidate differed only at absolute byte offsets 259, 311, and 312,
corresponding to UEFI mode, Above 4G decoding, and Re-Size BAR. Its SHA256 was
`84ff5eb2a87407f78638140cd78acedc34e74a61c5088a75d5d97d02f4690ab2`.

A temporary `busybox:1.36.1` Pod on Iggy mounted efivarfs writable with
privileged security context and no host network or service-account token. It
removed the EFI variable's immutable flag, wrote the entire candidate without
truncation, and restored the immutable flag. Both the pod and an independent
Talos `read` confirmed the candidate SHA256 and all three value bytes `1`.
The pod was deleted. Temporary private GHCR authentication was applied to
Iggy's live machine configuration before reboot and removed after the upgrade;
the mode-0600 token patch and logs were deleted.

Iggy was then rebooted with Talos `--mode=powercycle` so the new firmware PCIe
settings could take effect. The custom installer was **not** installed before
this reboot. Talos's 15-minute reboot wait expired without Iggy returning;
`192.168.42.13` did not answer ping and Kubernetes reported Iggy `NotReady`.
The other four nodes remained `Ready`. At that point, recovery required local
access to inspect POST/BIOS and the UEFI boot option.

An existing host-networked Cilium pod on healthy `kristeva` sent one standard
Wake-on-LAN magic packet to Iggy's last ARP MAC `2c:f0:5d:3e:1a:ab`. After a
further minute, Iggy still did not answer IPv4 or Talos IPv6, and Kubernetes
still reported the node `Unknown`. The packet did not recover the boot.

The user subsequently recovered Iggy through BIOS setup, enabled UEFI,
Above 4G, ReBAR, and XMP 2, and restored cluster membership. Linux then
mapped 32 GiB BAR1 windows on both cards.

The user tentatively identified the persistent LED as `VGA`, which MSI defines
as a GPU detection or initialization failure. The successful recovery was
manual BIOS setup; no clear-CMOS or Linux BAR resize was needed.

The previous 256 MiB BAR1 was insufficient for persistent NCCL peer mappings.
After BIOS recovery, the private patched installer was applied. Its
`--reboot-mode=powercycle` reboot left the node powered off; the user turned it
back on manually. The checks in the current-result section passed after that
second recovery. Neither failure is a reason to shut down Iggy again.

## References

- [Linux kernel IOMMU boot parameters](https://docs.kernel.org/admin-guide/kernel-parameters.html)
- [NVIDIA CUDA multi-GPU and IOMMU guidance](https://docs.nvidia.com/cuda/cuda-programming-guide/03-advanced/multi-gpu-systems.html#host-iommu-hardware-pci-access-control-services-and-vms)
- [NVIDIA NCCL GPU P2P troubleshooting](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/gpu_troubleshooting.html)
- [MSI MPG X570 GAMING EDGE WIFI specifications](https://www.msi.com/Motherboard/MPG-X570-GAMING-EDGE-WIFI/Specification)
- [MSI AMD X570 BIOS guide](https://download-2.msi.com/archive/mnu_exe/mb/AMDX570BIOS.pdf)
- [aikitoria's exact-version RTX 3090 PCIe P2P patch](https://github.com/aikitoria/open-gpu-kernel-modules/tree/595.71.05-p2p)
- [QuixiAI's BAR1 and NCCL validation notes](https://github.com/QuixiAI/open-gpu-kernel-modules)
