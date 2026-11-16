# LAN image registry (Zot)

Private custom images live at `registry.${DOMAIN_NAME}/timblakely/<image>`.
Build them in-cluster and push over the LAN; never fall back to a public
registry or send large image layers through the workstation's WAN uplink.

## Deployment

- Zot v2.1.23 is digest-pinned and runs on Kristeva, not a dedicated GPU node.
- `registry-data` is an 80Gi replicated Ceph RBD volume.
- The HTTPRoute attaches only to `envoy-internal`, with the existing wildcard
  TLS certificate. UniFi external-dns creates the internal DNS alias.
- There are no Talos registry changes, mirrors, or boot-path dependencies.
- `http.compat: ["docker2s2"]` preserves Docker schema-2 manifest digests.
- HTTP read/write deadlines are 30 minutes. Zot's 60-second defaults abort
  multi-GiB layer uploads even on the LAN, remove the upload session, and make
  the client's retry fail with `blob upload unknown to registry`.
- Retention keeps the newest 20 tags or tags pulled within 90 days. Untagged
  manifests and referrers are preserved for digest-pinned deployments.
- `maxRepoBytes` is a 30Gi logical per-repository publication guard, not a
  filesystem quota. The Ceph volume is the actual provisioned capacity.

A nightly Kopiur `SnapshotSchedule/registry` snapshots the whole volume to the
existing NAS `VolsyncKopia` repository, with 14 daily and 8 weekly snapshots.
It reuses that repository's existing maintenance owner and password. All mover
placement is restricted to ordinary nodes. This captures digest-only manifests
and registry metadata, unlike a per-tag image export. Trigger and verify a new
snapshot after the first image publication; restore testing remains a separate
required disaster-recovery exercise.

## Credentials

The 1Password `kubernetes/registry-template` item has these case-sensitive fields:

- `HTPASSWD`: newline-separated bcrypt entries for users `ci` and `pull`.
- `CI_PASSWORD`: password matching the `ci` entry.
- `PULL_PASSWORD`: different password matching the `pull` entry.

External Secrets creates three separate Secrets in `cluster-infra`:

- `registry-auth`: only the htpasswd content mounted by Zot.
- `registry-build-auth`: Docker config for builders (read/create/update under
  `timblakely/**`; no delete and no writes to other namespaces).
- `registry-pull-auth`: Docker config for image-pull verification (read-only).

Workloads in other Kubernetes namespaces need their own narrowly scoped
ExternalSecret/imagePullSecret; Kubernetes Secrets are namespace-local. Do not
copy plaintext passwords into manifests, Docker build arguments, shell arguments
or logs. Automation must use the existing `op-headless` service account.

## Verify

Read back the Flux GitRepository revision and `cluster-infra/registry`
Kustomization, HelmRelease, ready Pod and bound PVC. The default unauthenticated
`GET /v2/` must return **401**, not 200. Through the real TLS route, verify:

| Action | Anonymous | pull | ci |
| --- | --- | --- | --- |
| GET `/v2/` | 401 | 200 | 200 |
| POST blob upload in `timblakely/**` | denied | 403 | allowed |
| POST blob upload outside `timblakely/**` | denied | 403 | 403 |
| DELETE manifest | denied | 403 | 403 |

Compare the pushed manifest digest with the exact registry read-back, and pull
by that digest from a fresh Pod using `registry-pull-auth`. Do not equate a push
exit code with a verified deployment. Build/pull large images on cluster nodes,
not the workstation. A workstation may temporarily cache NXDOMAIN from before
the registry existed; query the UniFi resolver separately before altering DNS.

## Maya-M

The manual image build is in
`../../llm/llmkube/resources/manual/maya-m/image/`. It runs a bounded,
digest-pinned, privileged BuildKit Job on Kristeva and publishes only to Zot.
It requests no GPUs, mounts no model PVC, and includes no serving weights.
The manual build directory is deliberately not a registered Flux resource.
Publishing the recipe alone does not start the build or roll Maya-M.

Removing the app is not approval to destroy its image store: the PVC has Flux
pruning disabled. Destroying it requires a separate, deliberate decision and a
verified backup.
