set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

kubernetes_dir := justfile_dir() + '/kubernetes'


[doc('Bang on the cluster')]
everything:
    for ns in $(kubectl get ns -o name | cut -d'/' -f2); do \
        echo "Toggling namespace: $ns"; \
        just kick ks $ns 0 || true; \
        just kick hr $ns 0 || true; \
    done

[doc('Toggle flux kustomization')]
ks ns sleep="3":
    just kick type ks {{ ns }} {{ sleep }}

[doc('Toggle flux helmrelease')]
hr ns sleep="3":
    just kick type hr {{ ns }} {{ sleep }}

[private]
type type ns sleep="3":
    flux suspend {{ type }} --all -n "{{ ns }}";
    sleep {{ sleep }};
    flux resume {{ type }} --all -n "{{ ns }}";
