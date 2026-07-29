# llm-operator

Flux installs the operator from the pinned OCI chart in `app/repo.yaml`. The
release is deliberately configured for observation mode:

- the controller image is digest-only;
- leader election is enabled across two replicas;
- `transitions.enabled` is `false`;
- the cache-manager integration is unset; and
- Helm creates or replaces the bundled CRDs on install and upgrade.

## Verified live status

The observation-mode installation was verified live on 2026-07-28:

- chart `0.1.0` and the manager image are pinned by immutable digest;
- the `llm-operator` OCIRepository and HelmRelease are both Ready;
- the Helm release successfully reconciled;
- both manager pods are Running and Ready with zero restarts; and
- the live Deployment contains `--enable-transitions=false`.

The four operator CRDs are established, but no `LLMBackend`, `LLMModel`,
`LLMModelOverlay`, or `LLMActiveModel` resources exist yet.

## Remaining observation work

1. Inventory the live backend Deployments, Services, container names, ports,
   model revisions, and the fields that must remain unchanged.
2. Add only Cogito-specific resources reviewed against that inventory to the
   reserved `resources/` directory.
3. Activate its separate, operator-dependent Flux Kustomization as described in
   `resources/README.md` while keeping `transitions.enabled: false`.
4. Compare operator status with the existing proxy and workload state, and
   confirm the operator does not change backend replicas, arguments, or active
   model annotations throughout the observation window.

Do not enable transitions until the observation comparison and remaining
transition-safety gates pass.
