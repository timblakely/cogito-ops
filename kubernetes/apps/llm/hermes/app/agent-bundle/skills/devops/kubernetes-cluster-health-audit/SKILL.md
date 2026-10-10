---
name: kubernetes-cluster-health-audit
description: Use when auditing Kubernetes clusters.
---

# Kubernetes Cluster Health Audit

## When to Use

Use this skill for read-only reviews of a deployed Kubernetes cluster, including workload health, scheduling failures, storage/backup state, GitOps drift, and secret synchronization.

Audit the live cluster before proposing changes. Prefer read-only inspection, preserve active workloads, and distinguish confirmed faults from watch items.

## Procedure

1. Establish scope and safety.
   - Confirm the current kube context and cluster reachability.
   - Run read-only checks first; do not delete resources, restart workloads, or alter GitOps sources during an audit.
   - Protect active GPU/LLM and gaming workloads from disruptive scheduling, eviction, or deletion.

2. Check control-plane and workload health.
   - Inspect nodes, namespaces, pods, deployments/statefulsets, PVCs, certificates, operators, and recent warning events.
   - Look for Pending, Failed, CrashLoopBackOff, ImagePullBackOff, unavailable replicas, repeated restarts, and unsatisfied conditions.
   - For restart findings, inspect container `lastState.terminated.reason`, timestamps, limits, and previous logs; do not treat every restart as an application fault because completed jobs and intentional rollouts also restart.

3. Validate storage and backups.
   - Check storage-system health, volume attachment/binding, database cluster status, backup schedules, and the newest successful backup/snapshot.
   - Verify snapshot resources using the actual CRD's phase/status fields and schema; do not assume CSI `readyToUse` semantics for a custom snapshot controller.
   - Separate current successful snapshots from historical warning events and stale backup CRs.

4. Trace scheduler failures to their source.
   - For Pending pods, inspect events, node selectors/affinity, taints, resource requests, and available node labels.
   - Compare required labels with every eligible node and then inspect the feature-discovery configuration that creates those labels. A missing label can be caused by detector configuration, not missing hardware.
   - Prefer the smallest safe fix: restore the required feature detector when the workload's constraint is valid; otherwise change the workload constraint only after confirming the hardware requirement.

5. Check GitOps convergence and drift.
   - Inspect GitRepository/OCI sources and Kustomizations/HelmReleases for Ready status, reconciliation errors, path-not-found messages, suspended resources, and stale objects.
   - Compare failing paths against the checked-out repository before calling an object orphaned. If the source deleted a path but the live object remains, report the exact owning resources and recommend pruning through the GitOps lifecycle rather than issuing an unreviewed destructive command.

6. Check secret synchronization without exposing credentials.
   - Inspect ExternalSecret status and events, but never print secret values, tokens, or full Secret manifests.
   - Identify the referenced provider, item, and vault metadata only as needed. A `key not found` error may indicate a vault-scope mismatch rather than an application outage; verify the service account's permitted vaults before recommending a move or repoint.
   - Before repointing or restoring a vault item, grep the app's rendered manifests and env/secret references for the target Secret name. A secret produced by a shared kustomize component (e.g. one ClusterExternalSecret per app, named after the app) is often dead weight the app never consumes — then the fix is removing the generator component from that app's Kustomization, not fixing the provider. Note target Secrets with `creationPolicy: Owner` cascade-delete when the ExternalSecret is pruned, so confirm no consumer first.
   - Treat stale synced Secrets as a rotation/reconciliation risk even when the consuming application is currently running.

7. Correlate and classify findings.
   - Confirm each issue with at least two signals where practical: status plus event, scheduler reason plus labels, or GitOps error plus repository state.
   - Classify findings as active outage, degraded/reliability risk, configuration drift, backup/rotation risk, or watch item.
   - Include namespace, resource, evidence, root cause, impact, and a minimally disruptive remediation. Call out assumptions and unresolved checks explicitly.

8. Report concisely.
   - Lead with overall health and the small set of confirmed problems, ordered by impact.
   - Keep watch items separate from faults and mention intentional suspended/cold lanes as assumptions rather than failures.
   - Do not claim a fix was applied unless a later write and verification actually occurred.

## Common Pitfalls

- Do not infer that a live service is healthy from `Running` alone; readiness, restarts, events, and dependency status can show silent degradation.
- Do not interpret a single historical warning event as a current failure; compare it with current resource status and recent successful runs.
- Do not recommend deleting stale resources until ownership and GitOps prune behavior are established; an apparently orphaned object may still be managed outside the path being inspected.
- Do not use a generic JSON field parser across different snapshot or backup CRDs; first inspect `kubectl api-resources` and one representative object.
- Do not report a node-feature label as absent until checking the exact escaped label key and feature-discovery worker configuration; label-source overrides can suppress entire detector families.
- Do not treat provider lookup errors as proof that credentials are invalid; vault visibility and item naming are separate failure dimensions.
- Do not remediate a per-app generator (shared component producing one object per app) before checking consumers — many apps may already omit the component, and pruning it is the smallest fix.
- After a repo-push remediation, verify the effect, not just the reconcile success: reconcile `flux reconcile source git flux-system` then `flux reconcile kustomization NAME -n NS --with-source`, and confirm (a) pruned objects return NotFound, (b) the warning-event storm's lastTimestamp has stopped advancing, (c) consumer pods and HelmReleases are still Ready. `✔ applied revision` alone does not prove pruning or repair.

## References

- For reusable commands and interpretation tables, see `references/cluster-health-checks.md`.
