set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + '/kubernetes'

[private]
default:
    just -l kube

[doc('Apply local Flux Kustomization')]
apply-ks ns ks:
    just kube render-local-ks "{{ ns }}" "{{ ks }}" | kubectl apply --server-side --field-manager=kustomize-controller -f /dev/stdin

[doc('Browse a PVC')]
browse-pvc namespace claim *args:
    kubectl browse-pvc -n {{ namespace }} {{ args }} -i mirror.gcr.io/alpine:latest {{ claim }}

[doc('Delete local Flux Kustomization')]
delete-ks ns ks:
    just kube render-local-ks "{{ ns }}" "{{ ks }}" | kubectl delete -f /dev/stdin

[doc('Open a shell on a node')]
node-shell node:
    kubectl debug node/{{ node }} -n default -it --image="mirror.gcr.io/alpine:latest" --profile sysadmin
    kubectl delete pod -n default -l app.kubernetes.io/managed-by=kubectl-debug

[doc('Prune pods in Failed, Pending, or Succeeded state')]
prune-pods:
    for phase in Failed Pending Succeeded; do \
        kubectl delete pods -A --field-selector status.phase="$phase" --ignore-not-found=true; \
    done

[doc('Snapshot VolSync PVCs')]
snapshot:
    kubectl get replicationsources --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" patch replicationsources "$name" --type merge -p '{"spec":{"trigger":{"manual":"$(date +%s)"}}}'; \
    done

[doc('Suspend or resume Keda ScaledObjects')]
keda state:
    kubectl get scaledobjects --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite so "$name" autoscaling.keda.sh/paused{{ if state != "suspend" { "-" } else { "=true" } }}; \
    done

[doc('Suspend or resume VolSync')]
volsync state:
    flux -n volsync-system {{ state }} kustomization volsync
    flux -n volsync-system {{ state }} helmrelease volsync
    kubectl -n volsync-system scale deployment volsync --replicas {{ if state != "suspend" { "1" } else { "0" } }}

[doc('Sync ExternalSecrets')]
sync-es:
    kubectl get es --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite es "$name" force-sync="$(date +%s)"; \
    done

[doc('Sync GitRepositories')]
sync-git:
    kubectl get gitrepo --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite gitrepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('Sync HelmReleases')]
sync-hr:
    kubectl get hr --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite hr "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)" reconcile.fluxcd.io/forceAt="$(date +%s)"; \
    done

[doc('Sync Kustomizations')]
sync-ks:
    kubectl get ks --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ks "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('Sync OCIRepositories')]
sync-oci:
    kubectl get ocirepo --no-headers -A | while read -r ns name _; do \
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite ocirepo "$name" reconcile.fluxcd.io/requestedAt="$(date +%s)"; \
    done

[doc('View a secret')]
view-secret namespace secret:
    kubectl view-secret -n {{ namespace }} {{ secret }}

[doc('Backup a cnpg database')]
backup-cnpg namespace cluster:
    kubectl cnpg backup {{ cluster }} --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io -n {{ namespace }}

# The former split/dark/normal mutation recipes were retired with the
# two-service DRA migration. They suspended Flux and overwrote the old shared
# qwen-3-8-fp8 object, which is neither safe nor meaningful for UUID-bound
# devices. Keep status read-only; change serving state through Git.
[doc('Show local LLM and NVIDIA DRA status')]
llm-mode:
    kubectl -n llm get kustomizations.kustomize.toolkit.fluxcd.io llmkube-resources \
        --ignore-not-found \
        -o custom-columns='FLUX-KS:.metadata.name,SUSPENDED:.spec.suspend'
    kubectl -n cluster-infra get kustomizations.kustomize.toolkit.fluxcd.io nvidia-dra-driver \
        --ignore-not-found \
        -o custom-columns='FLUX-KS:.metadata.name,SUSPENDED:.spec.suspend'
    kubectl -n llm get inferenceservice qwen3-8-27b muse-glimmer-30b \
        --ignore-not-found \
        -o custom-columns='SERVING:.metadata.name,RUNTIME:.spec.runtime,MODEL:.spec.modelRef,WANT:.spec.replicas,PHASE:.status.phase'
    kubectl -n llm get resourceclaimtemplates qwen-gpu-x16 muse-gpu-x4 --ignore-not-found
    kubectl get deviceclass gpu.nvidia.com --ignore-not-found
    kubectl -n llm get pods \
        -l 'inference.llmkube.dev/service in (qwen3-8-27b,muse-glimmer-30b)' \
        -o wide

[private]
render-local-ks ns ks:
    flux-local build ks --namespace "{{ ns }}" --path "{{ kubernetes_dir }}/flux/cluster" "{{ ks }}"
