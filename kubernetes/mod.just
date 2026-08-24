set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + '/kubernetes'
llm_modes := kubernetes_dir + '/apps/llm/llmkube/modes'

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

# --- LLM serving modes -------------------------------------------------------
# Git is always NORMAL. SPLIT and DARK hand one or both of iggy's GPUs to the
# CUDA dev pod by suspending Flux and server-side applying a complete
# replacement object under Flux's OWN field manager, so `llm-normal` - which is
# only `flux resume` plus a reconcile - restores git exactly. Never switch
# modes with patch/edit/scale: those record a different field manager, and
# Flux cannot then remove what they set. Details in
# kubernetes/apps/llm/llmkube/modes/README.md.

[doc('Show the current LLM serving mode')]
llm-mode:
    kubectl -n llm get kustomizations.kustomize.toolkit.fluxcd.io llmkube-resources cuda-dev \
        -o custom-columns='FLUX-KS:.metadata.name,SUSPENDED:.spec.suspend'
    kubectl -n llm get inferenceservice qwen-3-8-fp8 \
        -o custom-columns='SERVING:.metadata.name,RUNTIME:.spec.runtime,MODEL:.spec.modelRef,WANT:.spec.replicas,GPU:.spec.resources.gpu,PHASE:.status.phase'
    kubectl -n llm get deploy cuda-dev \
        -o custom-columns='DEV:.metadata.name,READY:.status.readyReplicas,GPU:.spec.template.spec.containers[0].resources.limits.nvidia\.com/gpu'
    kubectl -n llm get pods -l app.kubernetes.io/name=cuda-dev --no-headers

[doc('LLM mode SPLIT: degraded single-card serving, one GPU to the dev pod (variant a|b)')]
llm-split variant='a':
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ variant }}" in
      a) spec="{{ llm_modes }}/split-a-llamacpp.yaml" ;;
      b) spec="{{ llm_modes }}/split-b-vllm-nvfp4.yaml" ;;
      *) echo "unknown SPLIT candidate '{{ variant }}' (expected a or b)" >&2; exit 1 ;;
    esac
    echo "$(date -Is)  mode SPLIT candidate {{ variant }}  ($(basename "$spec"))"
    flux suspend kustomization -n llm llmkube-resources
    flux suspend kustomization -n llm cuda-dev
    # Serving first: it holds both GPUs, and the dev pod cannot schedule until
    # the Recreate releases one. It carries PreemptionPolicy Never, so a
    # momentary shortage makes it wait rather than evict a model.
    kubectl apply -n llm --server-side --field-manager=kustomize-controller -f "$spec"
    kubectl apply -n llm --server-side --field-manager=kustomize-controller -f "{{ llm_modes }}/cuda-dev-1gpu.yaml"
    # Assert the apply actually landed BEFORE waiting on rollouts. A rollout
    # check against an object the apply never touched passes instantly and
    # reports success for a switch that did not happen - which is exactly what
    # a namespace mistake looks like from the outside.
    want_model=$([ "{{ variant }}" = a ] && echo qwen-3-8-ud-q4 || echo qwen-3-8-nvfp4)
    got_model=$(kubectl -n llm get inferenceservice qwen-3-8-fp8 -o jsonpath='{.spec.modelRef}')
    got_gpu=$(kubectl -n llm get inferenceservice qwen-3-8-fp8 -o jsonpath='{.spec.resources.gpu}')
    dev_gpu=$(kubectl -n llm get deploy cuda-dev -o jsonpath='{.spec.template.spec.containers[0].resources.limits.nvidia\.com/gpu}')
    if [ "$got_model" != "$want_model" ] || [ "$got_gpu" != "1" ] || [ "$dev_gpu" != "1" ]; then
      echo "SPLIT did not take effect: modelRef=$got_model (want $want_model)," >&2
      echo "  serving gpu=$got_gpu (want 1), dev gpu=$dev_gpu (want 1)" >&2
      echo "Run 'just kube llm-normal' to return to a known state." >&2
      exit 1
    fi
    kubectl -n llm rollout status deploy/cuda-dev --timeout=15m
    # Serving last and generously: a first serve of a candidate copies its
    # weights from the NFS archive to the NVMe hot tier before the engine loads.
    kubectl -n llm rollout status deploy/qwen-3-8-fp8 --timeout=30m
    just kube llm-mode

[doc('LLM mode DARK: no local serving, dev pod takes both GPUs (gpus=1|2)')]
llm-dark gpus='2':
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ gpus }}" in 1|2) ;; *) echo "gpus must be 1 or 2" >&2; exit 1 ;; esac
    echo "$(date -Is)  mode DARK  dev pod holds {{ gpus }} GPU(s); local seats are gone until llm-normal"
    flux suspend kustomization -n llm llmkube-resources
    flux suspend kustomization -n llm cuda-dev
    kubectl apply -n llm --server-side --field-manager=kustomize-controller -f "{{ llm_modes }}/dark-serving.yaml"
    # Wait for the card to actually come back, not just for the spec to land:
    # rollout status can pass against the pre-scale generation. `wait --for=delete`
    # errors when nothing matches, which is the success case here, so the
    # assertion below is what decides.
    kubectl -n llm wait --for=delete pod -l inference.llmkube.dev/service=qwen-3-8-fp8 --timeout=10m 2>/dev/null || true
    if [ -n "$(kubectl -n llm get pods -l inference.llmkube.dev/service=qwen-3-8-fp8 --no-headers 2>/dev/null)" ]; then
      echo "serving pod is still present; refusing to hand its GPU to the dev pod" >&2
      exit 1
    fi
    kubectl apply -n llm --server-side --field-manager=kustomize-controller -f "{{ llm_modes }}/cuda-dev-{{ gpus }}gpu.yaml"
    dev_gpu=$(kubectl -n llm get deploy cuda-dev -o jsonpath='{.spec.template.spec.containers[0].resources.limits.nvidia\.com/gpu}')
    if [ "$dev_gpu" != "{{ gpus }}" ]; then
      echo "DARK did not take effect: dev gpu=$dev_gpu (want {{ gpus }})" >&2
      echo "Run 'just kube llm-normal' to return to a known state." >&2
      exit 1
    fi
    kubectl -n llm rollout status deploy/cuda-dev --timeout=15m
    just kube llm-mode

[doc('LLM mode NORMAL: restore git state - TP=2 serving, dev pod CPU-only')]
llm-normal:
    #!/usr/bin/env bash
    set -euo pipefail
    # Rollback from anywhere, and deliberately independent of dev-pod state:
    # nothing below reads or waits on it.
    echo "$(date -Is)  mode NORMAL  restoring git state"
    flux reconcile source git -n flux-system flux-system
    flux resume kustomization -n llm llmkube-resources
    flux resume kustomization -n llm cuda-dev
    flux reconcile kustomization -n llm llmkube-resources
    flux reconcile kustomization -n llm cuda-dev
    just kube llm-mode

[private]
render-local-ks ns ks:
    flux-local build ks --namespace "{{ ns }}" --path "{{ kubernetes_dir }}/flux/cluster" "{{ ks }}"
