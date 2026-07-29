# llm-operator

Flux installs the operator from the pinned OCI chart in `app/repo.yaml`. The
release is deliberately configured for observation mode:

- the controller image is digest-only;
- leader election is enabled across two replicas;
- `transitions.enabled` is `false`;
- the cache-manager integration is unset; and
- Helm creates or replaces the bundled CRDs on install and upgrade.

## Artifact promotion

The release cannot install until both immutable artifacts have been published:

1. Publish `ghcr.io/timblakely/llm-operator@sha256:<digest>`.
2. Publish chart `0.1.0` to
   `oci://ghcr.io/timblakely/charts/llm-operator`, then commit its reviewed OCI
   digest in `app/repo.yaml`.
3. Commit the reviewed manager image digest directly in `app/helmrelease.yaml`. The
   digest is deployment metadata, not a credential, and keeping it in Git
   makes the promotion auditable.
4. Reconcile the Cogito Git source, the `llm` Kustomization, the
   `llm-operator` OCIRepository, and then the HelmRelease.

Do not substitute a mutable tag or a placeholder digest to bypass this gate.

## Observation check

After reconciliation, verify the source and release are ready and inspect the
live Deployment arguments. They must contain exactly
`--enable-transitions=false`. Then follow the observation-mode validation plan
from the llm-operator repository before adding any resources from the reserved
`resources/` directory.
