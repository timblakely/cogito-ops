# Node tenancy

GPU hosts are reserved with `workload.cogito/dedicated` `NoSchedule` taints.
The persistent source is each host's `talos/machineconfig/*.yaml.j2`;
apply only the `machine.nodeTaints` patch in `no-reboot` mode when changing
this policy on an active host. A full machine-config apply is not required.

| Hosts | Taint value | Allowed application workloads |
| --- | --- | --- |
| iggy, deleuze | ml | Inference, training, experiments, and model-cache support |
| amnesia | gaming-ml | Fenrir gaming and preemptible GPU ML |
| kristeva, nuc-1, nuc-2, nuc-3 | none | Ordinary services, databases, and controllers |

Networking, storage node plugins, device discovery/plugins, and node telemetry
are necessary exceptions. Their tolerations do not turn them into ordinary
application placement targets. Do not add namespace-wide tolerations: a service
in namespace `llm` is not necessarily a GPU workload.

## Gaming reclamation

Keep `gaming-interactive=20000` with `PreemptLowerPriority`. Both Steam and
Test Ball use it. ComfyUI remains at 5000; Gemma remains at 1000. Amnesia's
single physical GPU advertises two time-sliced units; a heavy ML tenant requests
both, and a gaming session requests one each for its app and Wolf containers.
Gaming therefore preempts either ML tenant through the existing scheduler
resource claims and priority hierarchy. Never raise an Amnesia ML workload to
or above gaming priority, or give it a non-preemptible allocation.

The existing `nvidia` RuntimeClass supplies dedication tolerations at **Pod
creation admission**. This also covers newly launched Fenrir pods without
changing an active Session-owned Deployment or either App template. Existing
pods are not rolled by a RuntimeClass update. This is a scheduling convention,
not a security boundary: callers selecting this RuntimeClass are trusted to
respect the node selectors and priority policy.

NVIDIA plugin, Multus, and Ceph CSI nodeplugin DaemonSets use `OnDelete`
to disable normal rolling replacement during gaming. This does not prevent an
owning operator from deleting and recreating a DaemonSet or Pod: verify the live
agent identities as well as the strategy during a rollout. Inspect the updated
template, then replace agent pods deliberately in a **gaming-idle maintenance
window** when applying future image/config updates.
An unchanged agent pod during such an upgrade is intentional, not convergence
proof; check its template and arrange the maintenance replacement separately.

## Storage and ordinary services

CNPG's shared base requires one of the four ordinary hosts, retaining required
hostname anti-affinity. A bound OpenEBS PV cannot move with a Pod: use CNPG's
`destroy CLUSTER INSTANCE` lifecycle only for a freshly verified non-primary,
after checking healthy survivors, to provision a new replica on eligible
storage. Never edit a local PV's node affinity to pretend the data moved.

The LLMKube manager remains ML support on Iggy because it mounts the shared
node-local hot model cache. Preserve that cache and the inference/model PVCs.
Foreman's execution supervisor instead uses a portable Ceph RBD cache and runs
on Kristeva. Its previous chart-owned Iggy cache is deliberately still present
for rollback; the Helm post-render patch redirects only the consumer volume.

LiteLLM's proxy token volume is CephFS and ntfy's application volume is Ceph RBD;
move their Pods, not their data. ntfy's volume includes its authentication DB.

Matrix, Hookshot, the Matrix coordinator, and ntfy backup movers use ephemeral
Kopia caches plus ordinary-node affinity. Their source data, repository identity,
retention and snapshots are unchanged. Previously bound Amnesia cache PVCs are
preserved, unused, for rollback; they are not application data to delete during
this change. Completed historical Jobs need not be moved. New ad-hoc ML Jobs
must include the appropriate dedication toleration (or the NVIDIA RuntimeClass
when they actually need that runtime).

## Verification

Check live taints and `spec.unschedulable` separately. A dedication toleration
does not override a cordon. Taint GPU hosts before uncordoning them; do not
uncordon them while non-ML Pods can still return to their old local volumes.
Verify every rebuilt database's primary, ready count, streaming replicas, and
new PV hostname. Check running ordinary Pods and backup movers are on ordinary
hosts, the active Steam Pod UID/start time/restart counts are unchanged, and
Flux has applied the published revision. `NoSchedule` alone never evicts an
existing ordinary Pod: relocate those consumers explicitly after the policy
lands.
