#!/usr/bin/env -S just --justfile

set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

mod bootstrap "bootstrap"
mod bs "kubernetes/bootstrap"
mod kick "kubernetes/flux"
mod kube "kubernetes"
mod talos "talos"
mod unifi "scripts/unifi"

talos_dir := justfile_dir() + '/talos'

[private]
default:
    just -l

[private]
log lvl msg *args:
    gum log -t rfc3339 -s -l "{{ lvl }}" "{{ msg }}" {{ args }}

[private]
template file *args:
    minijinja-cli "{{ file }}" {{ args }} | op inject

[private]
inject file:
    cat "{{ file }}" | op inject

# TODO(blakely): Move to k8s folder?
[doc('Install kubectl plugins')]
kubectl-plugins:
    krew install krew
    kubectl krew install view-secret

[doc('Flush DNS cache')]
flush-dns:
    sudo resolvectl flush-caches
