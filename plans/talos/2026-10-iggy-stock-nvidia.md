# Iggy: independent RTX 3090s with stock NVIDIA drivers

Iggy (`192.168.42.13`) has two RTX 3090s again on the existing CPU x16 /
chipset x4 motherboard. The cards are intended for independent workloads,
so neither the historical patched P2P driver nor Amnesia's custom kernel and
gaming extensions are needed. The Radeon AI PRO R9700s now belong to Deleuze.

Two 16 GiB DIMMs remain after the user removed a faulty stick and its partner.
Talos reports about 31,986 MiB total RAM. The `high-mem` role is removed;
future workload requests and limits must fit the shared 32 GiB host budget.

## Image and upgrade path

The official Talos v1.14.4 catalog provides
`nonfree-kmod-nvidia-production:595.91.07-v1.14.4` and the matched
`nvidia-container-toolkit-production:595.91.07-v1.19.1`. The Iggy schematic
replaces AMDGPU with these extensions while retaining AMD CPU microcode,
Realtek firmware, NUT client, and the existing kernel arguments. The machine
configuration loads `nvidia`, `nvidia_uvm`, `nvidia_modeset`, and `nvidia_drm`.
It also explicitly loads `nct6775` for the NCT6797 board fan sensor/control:
this driver is a loadable module in Talos 1.14 and was not auto-loaded after
the upgrade. Applying this addition loaded the module without another reboot.

This is an in-place `talosctl upgrade` from v1.13.5 using normal/default reboot
mode. Never use `powercycle` or shut down Iggy. Do not reset or wipe: the
separate 970 EVO 1 TB holds model caches and retained volumes, and EPHEMERAL
also holds the retained Flash Next n-gram PV. Disk selectors, `wipe: false`,
and the `local-hostpath` volume specification remain unchanged.

The generic `just talos upgrade-node iggy` recipe can now use the checked-in
stock image; its old custom-driver refusal is removed. The shutdown guard
remains in place.

## Cluster configuration

The explicit `nvidia.com/device-plugin.config=config.yaml` profile advertises
one `nvidia.com/gpu` unit per physical card, without time slicing. A workload
requesting one unit receives one card; two such workloads receive distinct
cards. Amnesia keeps its existing gaming profile and custom image.

The stale `amd.com/gpu.present` label is removed so the AMD device plugin and
AMD fan controller stop targeting Iggy. NVIDIA fan control and DCGM telemetry
select the explicit inference-host list `[iggy, kristeva]`, preserving
Amnesia's existing gaming setup. Iggy uses a 280 W per-card power cap;
Kristeva retains its 250 W setting.

The old `flashnext-iggy` AMD/ROCm TP=2 service is suspended. Its model data,
PVCs, routes, and the other already-suspended inference profiles remain
available for deliberate migration or replacement. No new model is selected
as part of the OS/driver change.

Iggy was already cordoned before this work. The user requested return to
normal scheduling after driver verification.

## Post-upgrade verification (2026-10-20 America/Denver)

Talos v1.14.4 boots kernel `6.18.57-talos`. `/proc/driver/nvidia/version`
confirms the proprietary NVIDIA UNIX kernel module `595.91.07`; the installed
kernel-module and container-toolkit extensions match the official catalog.
Kubernetes reports two allocatable `nvidia.com/gpu` resources, GPU count two,
and sharing strategy `none`. The stale AMD and high-memory labels are absent.

| GPU UUID | PCI address | Link during concurrent computation |
| --- | --- | --- |
| `GPU-787b1f07-4246-5ccd-5074-4bb2120f2c14` | `0000:23:00.0` | PCIe 4.0 ×4, behind the X570 chipset |
| `GPU-a5982685-6ed7-6fce-8096-52d29e241396` | `0000:2d:00.0` | PCIe 4.0 ×16 |

Both cards report 24,576 MiB physical VRAM and the existing 250 W power limit.
The new `talos/tests/nvidia_single_gpu.py` exercises CUDA's driver API without
PyTorch or a toolkit install. Two temporary, concurrent Jobs each requested
one GPU and had a 512 MiB system-memory limit. Each saw exactly one device,
with different UUIDs, JIT-compiled an SM86 increment kernel, and checked the
results of repeated computations and host transfers over 1,048,576 elements
for 45 seconds. They passed 66,849 and 52,921 iterations, respectively, and
both Jobs exited successfully. P2P is intentionally not an acceptance test.

The test processes also printed `ERROR: init 250 result=11` after their
successful result lines. This is recorded as an observed driver diagnostic;
neither Job failed, and the checked kernel log showed no NVIDIA Xid, GPU
fall-off, initialization failure, or driver/API mismatch. It does not negate
the compute checks, but a full model workload was not benchmarked here.

Etcd is healthy. All 11 Iggy-local PVs remain Bound, including the retained
weights and n-gram volumes. The existing Radiance model file and n-gram
directories are present. Linux renumbered the NVMe devices on reboot; the
serial/model selectors and existing partition labels selected the correct
system and data disks. No storage was reset, repartitioned, or wiped.

The pinned flux-local check passes all 175 checks with the repository's two
configured deselections. Talos metal validation passes with the existing
shared-base `.machine.files` deprecation warning. Temporary test Jobs and
their script ConfigMap were removed after verification.

The restored fan controller reports both GPU fans at the configured 50%
floor and board PWM outputs 3–7 at the corresponding duty. DCGM exports both
GPUs' temperatures. The original 250 W caps were active, the NVIDIA device plugin and
fan/telemetry Pods are healthy, and BGP is established with UniFi. Iggy was
uncordoned after these checks and is Ready for normal scheduling.

## Power-cap update (2026-10-21)

The user requested 280 W on both of Iggy's RTX 3090s. The existing
`nvidia-power-limit` DaemonSet selects its setting using the node name from
the Downward API: 280 W for Iggy and the existing 250 W for Kristeva.
It applies the cap when the Pod starts and every 300 seconds afterward,
restoring it after node reboots or driver resets without modifying Talos.
Both cards support 280 W (their reported ranges are 100–450 W and 100–366 W).
