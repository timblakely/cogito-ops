set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

scripts_dir := justfile_dir() + '/scripts'
talos_dir := justfile_dir() + '/talos'
cluster_name := shell("cat $1/machineconfig/base.yaml.j2 | grep -i clustername | awk '{print $2}'", talos_dir)
list_nodes := "find " + talos_dir + "/machineconfig -type f -name '*.yaml.j2' -not -name 'base.yaml.j2' -printf '%f\\n' | sed 's/\\.yaml\\.j2$//' | sort"
controller := shell(list_nodes + ' | head -1')
nuc_nodes_pattern := "^nuc-[1-3]$"

[private]
default:
    just -l talos

[doc('Apply Talos config to a node')]
apply-node node *args:
    just talos render-config "{{ node }}" | talosctl -n "{{ node }}" apply-config -f /dev/stdin {{ args }}

[doc('Download Talos machine image')]
download-image version schematic:
    #!/usr/bin/env bash
    ISO_FILE="{{ talos_dir }}/talos-{{ version }}-{{ replace_regex(schematic, '^(.{8}).*', '$1') }}.iso"
    if [ -f "$ISO_FILE" ]; then
        just log info "Talos image already exists" version "{{ version }}" schematic "{{ schematic }}"
    else
        gum spin --title "Downloading Talos {{ version }} ..." -- \
        curl -sfL --remove-on-error --retry 5 --retry-delay 5 --retry-all-errors \
            -o "$ISO_FILE" \
            "https://factory.talos.dev/image/{{ schematic }}/{{ version }}/metal-amd64.iso"
        just log info "Downloaded Talos" version "{{ version }}" schematic "{{ schematic }}"
    fi

[doc('Generate schematic ID from Talos schematic')]
gen-schematic-id node:
    curl -sX POST --data-binary @<(just template "{{ talos_dir }}/schematics/{{ node }}.yaml.j2") "https://factory.talos.dev/schematics" | jq -r '.id'

[doc('Reboot a node')]
reboot-node node *args:
    gum confirm "Reboot node {{ node }}?" --default="No" && \
        talosctl -n {{ node }} reboot -m powercycle {{ args }} || exit 0

[doc('Render Talos config for a node')]
render-config node:
    export IS_CONTROLLER="$(just talos machine-controller {{ node }})"; \
    talosctl machineconfig patch <(just template "{{ talos_dir }}/machineconfig/base.yaml.j2") \
        -p @<(just template "{{ talos_dir }}/machineconfig/{{ node }}.yaml.j2") \
    | yq eval -P --indent=2 - 

[doc('Reset a node')]
reset-node node *args:
    gum confirm "Reset node {{ node }}?" --default="No" && \
        talosctl -n "{{ node }}" reset --graceful=false --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --system-labels-to-wipe u-local-hostpath {{ args }} --reboot || exit 0

[doc('Perform a full reset of the cluster')]
full-reset:
    gum confirm "Reset the cluster?" --default="No" && \
        gum confirm "Are you really sure you want to do this?" --default="No" && \
        nodes=$({{ list_nodes }}) && \
        ceph_nodes=$(echo "$nodes" | grep -E "{{ nuc_nodes_pattern }}" || true) && \
        other_nodes=$(echo "$nodes" | grep -vE "{{ nuc_nodes_pattern }}" || true) && \
        for node in $other_nodes $ceph_nodes ; do \
            talosctl -n "$node" \
              --graceful=false \
              reset \
              --system-labels-to-wipe STATE \
              --system-labels-to-wipe EPHEMERAL \
              --system-labels-to-wipe u-local-hostpath --reboot; \
            sleep 10; \
        done

[doc('Shutdown a node')]
shutdown-node node *args:
    gum confirm "Shutdown node {{ node }}?" --default="No" && \
        talosctl -n "{{ node }}" shutdown --force {{ args }} || exit 0

[doc('Upgrade Kubernetes version on the cluster')]
upgrade-k8s version:
    talosctl -n "{{ controller }}" upgrade-k8s --to {{ version }}

[doc('Upgrade Talos version on a node')]
upgrade-node node *args:
    talosctl -n "{{ node }}" upgrade -i "$(just talos machine-image {{ node }})" -m powercycle --timeout=10m {{ args }}

# gum confirm "Generate config, blowing away previous talosconfig?" --default="No" && \
private_talos_dir := justfile_dir() + '/.private/talos'
[doc('Generate talos config from control plane')]
gen-config ttl_hours="8760":
    mkdir -p "{{ private_talos_dir }}"
    echo "$(op item get --vault kubernetes talos --field MACHINE_CA_CRT | base64 -d)" > "{{ private_talos_dir }}/ca.crt"
    echo "$(op item get --vault kubernetes talos --field MACHINE_CA_KEY | base64 -d)" > "{{ private_talos_dir }}/ca.key"
    cd "{{ private_talos_dir }}" && \
        talosctl gen key --name admin --force
    cd "{{ private_talos_dir }}" && \
        talosctl gen csr --key admin.key --ip 127.0.0.1 --force
    cd "{{ private_talos_dir }}" && \
        talosctl gen crt --ca ca --csr admin.csr --name admin --hours {{ ttl_hours }} --force
    touch "$TALOSCONFIG"
    yq -i '.context="{{ cluster_name }}" | \
        with(.contexts.{{ cluster_name }}; \
            .endpoints = [] | \
            .nodes = [] | \
            .ca = "PENDING" | \
            .crt = "PENDING" | \
            .key = "PENDING" \
        )' \
        "$TALOSCONFIG"
    just talos add-nodes "{{ cluster_name }}" "$TALOSCONFIG"
    just talos add-ca "$TALOSCONFIG"

add-ca talosconfig:
    cat "{{ private_talos_dir }}"/ca.crt | base64 -w0 | \
        yq '.contexts.{{ cluster_name }}.ca=load_str("/dev/stdin")' -i "{{ talosconfig }}"
    cat "{{ private_talos_dir }}"/admin.crt | base64 -w0 | \
        yq '.contexts.{{ cluster_name }}.crt=load_str("/dev/stdin")' -i "{{ talosconfig }}"
    cat "{{ private_talos_dir }}"/admin.key | base64 -w0 | \
        yq '.contexts.{{ cluster_name }}.key=load_str("/dev/stdin")' -i "{{ talosconfig }}"


[private]
add-nodes context talosconfig:
    NODES=$(ls "{{ talos_dir }}/machineconfig" | grep -v 'base.yaml.j2' | xargs -I {} basename {} .yaml.j2) && \
    for n in $NODES; do \
        just talos add-node "$n" "{{ context }}" "{{ talosconfig }}"; \
    done

[private]
add-node node context talosconfig:
    yq -i '.contexts.{{ context }}.endpoints = \
    ((.contexts.{{ context }}.endpoints // []) + ["{{ node }}"] | unique)' \
    "{{ talosconfig }}" && \
    yq -i '.contexts.{{ context }}.nodes = \
    ((.contexts.{{ context }}.nodes // []) + ["{{ node }}"] | unique)' \
    "{{ talosconfig }}"

[private]
machine-controller node:
    just template "{{ talos_dir }}/machineconfig/{{ node }}.yaml.j2" | yq -e 'select(.machine) | (.machine.type == "controlplane") // ""'

[private]
machine-image node:
    just template "{{ talos_dir }}/machineconfig/{{ node }}.yaml.j2" \
    | yq -e 'select(.machine) | .machine.install.image'
