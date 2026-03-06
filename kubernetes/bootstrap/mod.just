set positional-arguments := true
set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + '/kubernetes'
talos_dir := justfile_dir() + '/talos'
list_nodes := "find " + talos_dir + "/machineconfig -type f -name '*.yaml.j2' -not -name 'base.yaml.j2' -printf '%f\\n' | sed 's/\\.yaml\\.j2$//' | sort"
controller := shell(list_nodes + ' | head -1')
nodes := shell(list_nodes + ' | xargs')
kube_bootstrap_dir := kubernetes_dir + '/bootstrap'

[private]
default: talos k8s (kubeconfig "node") wait resources crds flux kubeconfig

[doc('Install Talos')]
talos:
    just log info "Running stage..." "stage" "$0"
    for n in {{ nodes }}; do \
        if ! op=$(just talos apply-node "$n" --insecure 2>&1); then \
            if [[ "$op" == *"certificate required"* ]]; then \
                just log info "Talos already configured, skipping apply of config" "stage" "$0" "node" "$n"; \
                continue; \
            fi; \
            just log fatal "Failed to apply Talos configuration" "stage" "$0" "node" "$n" "output" "$op"; \
        fi; \
    done

[doc('Install Kubernetes')]
k8s:
    just log info "Running stage..." "stage" "$0"
    just log info "Starting Kubernetes bootstrap on controller {{ controller }}" "stage" "$0"
    until op=$(talosctl -n "{{ controller }}" bootstrap 2>&1 || true) && [[ "$op" == *"AlreadyExists"* ]]; do \
        just log info "Kubernetes bootstrap in progress. Retrying in 5 seconds..." "stage" "$0"; \
        sleep 5; \
    done

[doc('Wait for nodes to be not-ready')]
wait:
    just log info "Running stage..." "stage" "$0"
    if ! kubectl wait nodes --for=condition=Ready=True --all --timeout=10s &>/dev/null; then \
        until kubectl wait nodes --for=condition=Ready=False --all --timeout=10s &>/dev/null; do \
            just log info "Nodes not available, waiting for nodes to be available. Retrying in 5 seconds..." "stage" "$0"; \
            sleep 5; \
        done \
    fi

[doc('Apply initial secrets and resources')]
resources:
    just log info "Running stage..." "stage" "$0"
    export FLUX_GITHUB_PUBLIC_KEYS=$( \
        curl -fsSL https://api.github.com/meta | \
          jq --raw-output '"github.com "+.ssh_keys[]')  &&\
    op run --env-file {{ kube_bootstrap_dir }}/.secrets.env --no-masking -- \
        bash -c 'export ONEPASSWORD_CREDENTIALS_B64=$(echo "$ONEPASSWORD_CREDENTIALS") && \
        minijinja-cli --env {{ kube_bootstrap_dir }}/apps/resources.yaml.j2' | \
        tee /tmp/bootstrap.yaml | \
        kubectl apply --server-side --filename -


[doc('Apply CRDs')]
crds:
    just log info "Running stage..." "stage" "$0"
    if ! helmfile -f "{{ kube_bootstrap_dir }}/apps/crds.yaml" template -q | kubectl apply --server-side --field-manager bootstrap --force-conflicts -f -; then \
        just log fatal "Failed to apply crds" "stage" "$0"; \
    fi;

[doc('Install Flux')]
flux: 
    export KUBERNETES_DIR={{ kubernetes_dir }} && \
      minijinja-cli --env {{ kube_bootstrap_dir }}/apps/helmfile.yaml.j2 | \
      tee /tmp/helmfile.yaml | \
      helmfile --file - sync --hide-notes



[doc('Fetch kubeconfig')]
kubeconfig lb="cilium":
    just log info "Running stage..." "stage" "$0"
    if ! talosctl kubeconfig -n "{{ controller }}" -f --force-context-name main {{ justfile_dir() }}; then \
        just log fatal "Failed to fetch kubeconfig" "stage" "$0"; \
    fi
    if [[ "{{ lb }}" != "cilium" ]]; then \
        if ! kubectl config set-cluster main --server "https://{{ controller }}:6443"; then \
            just log fatal "Failed to set kubectl cluster server address" "stage" "$0"; \
        fi; \
    fi    
