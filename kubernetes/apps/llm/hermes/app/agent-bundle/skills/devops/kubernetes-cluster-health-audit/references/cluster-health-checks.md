# Cluster Health Checks

Use these as read-only probes and adapt resource names to the installed CRDs.

## Baseline

```sh
kubectl config current-context
kubectl get nodes -o wide
kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
kubectl get pvc -A
kubectl get certificaterequests,certificates -A
```

Filter for likely faults without assuming every non-Running pod is broken:

```sh
kubectl get pods -A --field-selector=status.phase!=Running
kubectl get pods -A -o wide
kubectl get deploy,statefulset -A
```

For a suspicious container:

```sh
kubectl -n NAMESPACE get pod POD -o json
kubectl -n NAMESPACE logs POD -c CONTAINER --previous
kubectl -n NAMESPACE describe pod POD
```

## Scheduler diagnosis

```sh
kubectl -n NAMESPACE describe pod POD
kubectl get nodes --show-labels
kubectl get node NODE -o json
```

Read the pod's `nodeSelector`, required node affinity, taints/tolerations, and resource requests together. If a feature label is missing, inspect the feature-discovery worker ConfigMap and running worker arguments before changing the workload.

## GitOps diagnosis

```sh
kubectl get gitrepositories,ocirepositories -A
kubectl get kustomizations,helmreleases -A
kubectl -n NAMESPACE get kustomization NAME -o yaml
kubectl -n NAMESPACE get helmrelease NAME -o yaml
```

Confirm a path-not-found error against the repository tree and identify whether pruning is enabled before recommending cleanup. Report the complete resource chain (source -> Kustomization -> HelmRelease/OCIRepository) so remediation does not leave dependent objects behind.

When validating a repo edit locally, a standalone `kustomize build` failure on an app dir that assembles shared components (component patches reaching outside the component root trip kustomize's path-security check even on pristine main) is not a real gate — reproduce on a pristine baseline before blaming the change, and rely on the cluster-side Flux render for validation.

## Backups and custom CRDs

```sh
kubectl api-resources | grep -iE 'snapshot|backup|replication'
kubectl get RESOURCE -A
kubectl get RESOURCE OBJECT -n NAMESPACE -o yaml
```

Use the CRD's `phase`, `conditions`, timestamps, and source references. For custom controllers, inspect the CRD schema or a successful object before writing a status query; similarly named resources frequently use incompatible status fields.

## Secret synchronization

```sh
kubectl get externalsecrets.external-secrets.io -A
kubectl -n NAMESPACE describe externalsecret NAME
kubectl get clustersecretstores,secretstores -A
```

Capture only metadata, condition reasons, and provider references. Never dump Secret data or credential values. Determine whether the failure is item missing, vault inaccessible, provider unhealthy, or target-secret conflict.
