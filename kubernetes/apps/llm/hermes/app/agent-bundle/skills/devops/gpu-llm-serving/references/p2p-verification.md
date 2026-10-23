# Confirming tensor-parallel P2P between GPUs on a node

Answer "does this lane actually use peer-to-peer between its GPUs?" with an
evidence ladder, not the engine's log line alone and not a guess from the model
name. Read-only end to end.

## 1. What the lane asked for

`kubectl -n llm get deploy <lane> -o yaml` — look for the engine's peer flags in
`spec.template.spec.containers[].args`. Radiance: `--p2p auto|requires|off`
(`auto` asks the driver, `requires` refuses to start without peer access, `off`
bounces through pinned host memory) plus `--tp N` and `--tp-wire`.
Absent flag = the engine's default, which for Radiance is `auto` — a *soft*
request, so the answer must come from runtime evidence.

## 2. What the engine resolved it to

The startup banner is the engine's own resolution, and it survives in the pod log
even days later (`kubectl logs <pod> | head`, plus the DERIVED/HARDWARE block):

- `I device: the 2 cards reach each other's memory directly (peer to peer)`
- config echo: `--p2p  peer to peer  [auto]` — resolved value + where it came from
- `I HARDWARE` → `iommu passthrough (...)`, `amdgpu ... boot parameters: amd_iommu=on iommu=pt`
- per-card `link` lines and any `note link-capped:` note (that note is about the
  **host**-memory path, not the peer path — do not read it as P2P being broken)

Restart count must be 0, otherwise the banner describes a dead process.

## 3. Kernel-level proof (the decisive step)

Run inside the serving pod — `/sys` is the host's, so this reads the driver's own
record without any node shell:

```sh
kubectl -n <ns> exec -i <pod> -- sh -s < probe.sh
```

Pipe a script in with `sh -s <`; a quoted `sh -c '...$(...)...'` through
`kubectl exec` breaks on nested quotes. In kernel 6.18 each `io_links/<i>` and
`p2p_links/<i>` is a **directory** whose data is in `properties` — `cat`ing the
directory yields nothing and looks like "no link".

```sh
for n in /sys/devices/virtual/kfd/kfd/topology/nodes/*; do
  grep -E '^(name|io_links_count)' $n/properties
done
for l in /sys/devices/virtual/kfd/kfd/topology/nodes/<gpu node>/p2p_links/*; do
  echo "$l:"; cat $l/properties
done
```

Read the result:

- A `p2p_links` entry from GPU node → GPU node **is** the kernel granting peer
  access. Absent = no peer path, whatever the engine says.
- `type 2` = PCIe-routed peer (through the CPU/IO die). `type 5` = xGMI/Infinity
  Fabric (real card-to-card; only on Threadripper/EPYC/multi-GPU boards).
  Consumer AM4/AM5 is always type 2 — say so rather than implying a direct link.
- `max_bandwidth` is MB/s as the kernel sees it (16000 = ~16 GB/s, i.e. PCIe
  Gen4 x8-class), and it can sit below the card's own link width.
- Also read `/sys/module/amdgpu/parameters/{pcie_p2p,use_xgmi_p2p}` and
  `cat /sys/kernel/iommu_groups/*/type | sort | uniq -c`. P2P on AMD consumer
  needs `pcie_p2p=Y` **and** IOMMU groups of type `identity` (passthrough);
  translated IOMMU is the usual reason a working-looking stack loses peer access.
- `rocm-smi` is normally absent from serving images — do not conclude anything
  from `rocm-smi: not found`.
- Cross-check the PCI path with `readlink -f /sys/class/drm/card*/device` to see
  which root port each card hangs off; separate CPU root ports (e.g. `00:03.1`
  vs `00:03.2`) mean peer traffic traverses the fabric, not a switch.

## 4. Phrasing the answer

State the transport (PCIe vs xGMI), the kernel evidence, and the softness of the
config: with `--p2p auto` a future driver/Talos/IOMMU change falls back to pinned
host memory silently instead of failing. Recommend `--p2p requires` only if the
user wants a hard gate. Keep peer traffic separate from host traffic in the
answer: expert/host-pool streaming still crosses PCIe through the capped
host-side link even when the collectives are peer-to-peer.
