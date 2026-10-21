# Deleuze installation and hardware

Deleuze is the new ML server at `192.168.42.16/24`, installed from the
Talos v1.14.4 USB environment on 2026-10-20 (America/Denver). The installer
was reachable at `.71`; the initially supplied `.72` did not respond.

## Hardware verified

| Component | Observed configuration |
| --- | --- |
| Board / BIOS | ASUS ROG STRIX B550-XE GAMING WIFI / 3644 |
| CPU | Ryzen 5 5600, 6 cores / 12 threads |
| RAM | Four G.Skill F4-3200C16-32GTZR DIMMs, 128 GiB total; SMBIOS configured speed 3200 MT/s on all four |
| GPUs | Two Radeon AI PRO R9700, 32 GB each; 64 GB total VRAM |
| GPU host links | CPU root ports `00:03.1` and `00:03.2`, PCIe 4.0 ×8 each; the cards' internal PCIe 5.0 ×16 links do not represent host bandwidth |
| NVMe | Samsung SSD 990 EVO Plus 2TB, serial `S7U6NJ0Y436315F`; PCIe 4.0 ×4 at both drive and CPU port |
| Network | Realtek RTL8127, MAC `1c:86:0b:3a:1e:08`, 10,000 Mb/s full duplex confirmed by Talos and UniFi |

The NIC is connected through the B550 chipset at PCIe 3.0 ×1. Its host link
has about 7.88 Gb/s of encoded PCIe bandwidth before protocol overhead, so
the negotiated 10 Gb/s Ethernet link cannot deliver full line rate to host
memory. Keep it connected: the user chose it over the onboard 2.5 GbE port.

The GPU host links downshift to 2.5 GT/s while idle. Both CPU root ports and
card upstream ports were also checked under sustained cross-GPU copy load:
all four report 16 GT/s ×8. Memory runs at its rated 3200 MT/s; SMBIOS does
not expose whether the BIOS selected the named XMP/DOCP profile or equivalent
manual settings. Talos does not configure BIOS memory profiles.

## Persistent configuration

`talos/machineconfig/deleuze.yaml.j2` follows the existing control-plane and
schedulable-worker pattern. It fixes the address at `.16`, gateway and DNS
at `192.168.42.1`, and selects the connected NIC by MAC. UniFi also reserves
`.16` for that MAC, outside its `.20`–`.254` dynamic pool, with client name
`deleuze`. Its enabled local DNS record is `deleuze.internal`, verified
through an uncached resolver query. The ignored local `talosconfig` also
includes Deleuze among its nodes and endpoints.

The installer is pinned by digest and uses the schematic in
`talos/schematics/deleuze.yaml.j2`: AMD microcode, AMDGPU firmware/kernel
modules (including KFD), Realtek firmware, and NUT client. ROCm userspace
belongs in workload containers. Kernel arguments enable AMD IOMMU with
passthrough mode.

The user authorized erasing the sole internal NVMe, which previously held
Windows/Linux partitions. Only the initial private install configuration
enabled `wipe`; the persistent and live configurations use `wipe: false`.
The installer USB was excluded by the NVMe model and serial selector.

After discussing image-cache needs, the user selected 256 GiB for EPHEMERAL
instead of the original 512 GiB. `local-hostpath` grows into the remaining
space on the same disk and mounts at `/var/mnt/local-hostpath` for OpenEBS.
Talos boot/state partitions consume a small additional amount. Do not reset
this node once model data is stored: reset recipes wipe `u-local-hostpath`.

The AMD device plugin selects `amd.com/gpu.present=true` so it can advertise
both cards on Deleuze. Iggy's board-specific fan controller remains scoped
to Iggy. Existing inference services and model PVCs retain their placement;
onboarding does not migrate their data or change production model routing.

## Validation

The rendered machine configuration passes Talos metal validation. The shared
base emits an existing `.machine.files` deprecation warning. The repository's
pinned flux-local image passes all 175 checks with its two configured
deselections. The isolated validation copy was needed because flux-local
generates missing kustomization files while traversing the repository.

Deleuze is Kubernetes Ready, its etcd member is promoted and healthy, and
the node's control-plane, networking, device-plugin, and storage CSI Pods
are healthy. The installed schematic and all four extensions match the
pinned installer. The live machine configuration has been reapplied with
`wipe: false` after the successful initial install.

A temporary Job pinned to Deleuze requested both `amd.com/gpu` devices and
used the existing repository smoke-test image, pinned to
`docker.io/vllm/vllm-openai-rocm@sha256:2e7da1ad1c66836802072588adea75f9f4991da5f9545b4318e91d422c22ce6a`.
With ROCm `7.2.53211`, it verified a 1024×1024 matrix multiplication on each
GPU, bidirectional peer-access capability, and the contents of a 32 MiB
cross-GPU copy after 45 seconds of repeated transfers. Each device reports
34,208,743,424 bytes of usable VRAM. This is a functional smoke test, not a
full performance or stability benchmark.

The same Job mounted a dynamically provisioned 1 GiB `openebs-hostpath`
PVC, wrote and fsynced a file, and verified its contents. The PVC was bound
to Deleuze's `/var/mnt/local-hostpath` partition. Both tests passed; the
temporary Job and PVC were deleted afterward. The system partition reports
about 275 GB and the hostpath filesystem about 1,722 GB in Talos mounts.

## Router verification

`kubernetes/apps/cilium/cilium/bgp.conf` now includes
`neighbor 192.168.42.16 peer-group k8s`. The user applied the matching live
UniFi router configuration. Deleuze's Cilium BGP session established at
2026-10-20 22:57:19 America/Denver (2026-10-21 04:57:19 UTC), with local AS
64514 and router AS 64513 at `192.168.1.1`.

Both the live Cilium peer and the CiliumBGPNodeConfig status confirm the
established session, two advertised IPv4 routes, and four received routes.
The advertised service prefixes are `192.168.69.100/32` and
`192.168.69.25/32`, both with next hop `192.168.42.16`. The router address
remains valid and reachable; no Cilium peer-address change was needed.
