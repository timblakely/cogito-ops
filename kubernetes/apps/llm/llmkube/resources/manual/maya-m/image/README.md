# Pinned Maya-M runtime image (manual build)

This directory is intentionally not registered in Flux. Rendering is inert;
applying the rendered Job builds and pushes an image. It does not change or
restart `llm/maya-m-trial`, allocate a GPU, mount an Iggy PVC, prepare a pack,
or download weights (including vision weights and drafters).

## Inputs and image layout

- Maya 1.1.64: `d93d1499021b98a39bede20d33368907f1ea4ad8`; the exact codeload
  tarball is SHA256-gated in the Dockerfile.
- llama.cpp: `3cf03257f219afbe7334045ff7c6a06ac68c627d`; its exact codeload
  ZIP is also SHA256-gated. Maya's vision patch runs through upstream helpers.
- CUDA 13.0.0 / Ubuntu 24.04 devel: pinned linux/amd64 manifest. NCCL runtime
  and headers are pinned to `2.27.7-1+cuda13.0`.
- Python 3.12, with package versions observed in the running trial captured in
  `requirements.txt`. This is not a hash-locked Python environment or an apt
  snapshot: Ubuntu packages, pip bootstrap and package indexes remain external
  availability/reproducibility dependencies. Resolved pip and dpkg inventories
  remain under `/opt/maya-build`.
- BuildKit 0.26.2: linux/amd64 manifest digest resolved with `skopeo inspect
  --raw` and re-inspected by digest. Overlayfs snapshotter (mount-tested in
  the actual builder Pod); one Dockerfile vertex at a time. The CUDA and vision
  compiles both force four concurrent jobs. Native snapshotting duplicates the
  large CUDA root filesystem at every step and is intentionally avoided.

`build_runtime.py` calls only upstream `tools_step`, `compile_engine` and
`compile_vision`, preserving their pip/native stamps. It adds
`STRATA_PORTABLE=ON` (AVX2 baseline, not Kristeva's native CPU flags), pins
`sm_86` for Iggy's RTX 3090s, and bounds upstream's host-based `-j` calculation.
It never calls the setup orchestration/model preparation path. Only the GLM
engine `build/maya` and `build-vision/bin/maya-vision` are built; no DeepSeek,
MiniMax or DFlash2 artifact is promised. The pinned CUDA development base stays
in the final image intentionally, avoiding unverified library stripping; this
is not a small production-hardened image.

The runnable tree and Python venv live at the exact upstream path:

```text
/model/maya-work/project-maya
```

A second complete copy lives at `/opt/maya-image/project-maya`, because a model
PVC mounted at `/model` hides the image's `/model` contents. A future serving
Pod should mount a separate emptyDir at `/model/maya-work/project-maya` in both
init and application containers, then have the init container copy:

```sh
cp -a /opt/maya-image/project-maya/. /model/maya-work/project-maya/
```

The destination must be an empty, separately mounted workspace, NOT the current
trial's retained source directory. Do not launch directly from `/opt`: the venv
has absolute shebangs, and native metadata uses the original path. Keep the
retained server config separately accessible. Copy a ConfigMap-provided config
into a writable location before passing its absolute path with `--config`:
upstream touches the config file at startup. Preserve its external pack, GGUF,
vision mmproj/vocab paths and memory/GPU settings.
The config and all model files remain external. This directory does not provide
or deploy that future serving Pod.

Default entrypoint is upstream `setup.sh`; default command is harmless `--help`.
A future start must explicitly pass `--config /path/to/retained-config.json
--plain --yes --host 127.0.0.1`. Never use `--setup --no-start` for an image
build or a normal retained-config start: it still prepares/downloads models.
Disable/avoid dashboard self-updates for this pinned image; the environment
sets `MAYA_UPDATE_CHECK=0`. Keep loopback-only exposure until authentication is
added. GPU runtime, driver-provided `libcuda.so.1`, GPU requests, memlock and
capabilities must be provided by a future serving Pod, not this build Job.

## Operator prerequisites and build

Only run after explicit deployment/push approval:

1. Recheck Kristeva's CPU, memory **and backing filesystem** headroom after the
   Zot registry is running. The Job requests/limits 8 CPU and 16Gi RAM, with an eight-hour deadline
   and no automatic retries. A separate 60Gi Ceph RBD cache survives failed
   Jobs; ephemeral storage is limited to 2Gi for container files/logs.
   Native snapshotting is avoided; the duplicated final tree still increases
   scratch usage. The 60Gi value is a bound, not a measured peak. The Job cannot
   preempt other Pods. `build.sh` requires Talos cgroup-v2 placement, checks finite
   Pod CPU/memory quotas, moves the daemon back into its container cgroup and
   sets the OCI worker's daemon-level `defaultCgroupParent` to the Pod cgroup.
   Using the frontend `cgroup-parent` option would include the Pod UID in RUN
   cache keys and defeat reuse after replacement. Without cgroup containment,
   privileged BuildKit creates host-root cgroups outside Kubernetes accounting.
   A real lightweight build verified both daemon/worker placement and inherited
   1-CPU/1Gi limits before this recipe was published.
2. Confirm `cluster-infra` permits privileged BuildKit, `llmkube-batch` exists,
   and Kristeva can pull the pinned BuildKit/CUDA images and reach HTTPS package
   indexes/GitHub. The Job uses neither hostPath nor a model PVC nor a service-account
   token; its own dedicated build-cache PVC contains no model weights. Privileged is still a broad node trust boundary.
3. The Zot app provisions `cluster-infra/registry-build-auth`, with Docker auth
   JSON under key `.dockerconfigjson` and permission to push the target repo.
   It is mounted read-only at `/root/.docker/config.json`; do not place its
   contents in this directory or logs. No secret is generated here.
4. Confirm `https://registry.timblakely.com` serves the Zot registry with a
   trusted certificate and working authenticated push. No HTTP/insecure fallback
   is enabled. Check that the target tag does not already contain an artifact
   you intend to preserve: rebuilding this recipe pushes the same tag.

From the repository root, with `KUBECONFIG` set:

```sh
image=kubernetes/apps/llm/llmkube/resources/manual/maya-m/image
kustomize build "$image" | kubectl apply --dry-run=server -f -
# The following commands build and PUSH; they are not local validation.
kustomize build "$image" | kubectl apply -f -
kubectl -n cluster-infra logs -f job/maya-m-image-build-v1
kubectl -n cluster-infra wait --for=condition=complete \
  job/maya-m-image-build-v1 --timeout=8h
```

The only output target is HTTPS
`registry.timblakely.com/timblakely/maya-m:1.1.64-d93d1499`. No registry auth is
passed as a Dockerfile build argument or copied into the image. BuildKit's
metadata JSON is at `/scratch/image-metadata.json` on the retained cache PVC;
BuildKit state survives Job/Pod replacement.
Compilation is committed separately from the final verification layer, so an
adjusted verifier can reuse successful native compilation. Python bytecode
writes are disabled to keep upstream recursive source hashes stable.
The Job/Pod expires one day after completion, so capture logs/metadata first.
Before claiming publication, read back the exact tag with `skopeo inspect`,
record its immutable linux/amd64 digest, and use that digest for any future
serving recipe. A successful build/push is not a GPU inference or vision test.

If a rerun is approved, delete only this completed/failed build Job before
reapplying (Job Pod templates are immutable). Generated ConfigMaps have hash
suffixes so source changes are reflected in the Pod; clean old generated maps
only after their Job no longer references them. Do not use broad prune/delete
commands or touch the running trial/PVC.

## Published Artifact

Verified 2026-11-16:

- Tag: `registry.timblakely.com/timblakely/maya-m:1.1.64-d93d1499`.
- Immutable linux/amd64 image:
  `registry.timblakely.com/timblakely/maya-m@sha256:5e82c10d8b7e042f40eac275fcf9ced54f583faacbc63c0ed352b764ab06763c`.
- Registry manifest read-back matches the BuildKit exporter byte-for-byte;
  compressed layers total 4,610,073,271 bytes (4.61 GB), across 20 layers.
- `cluster-infra/maya-m-image-smoke-v1` pulled that exact digest with the
  read-only credential on Kristeva, exited 0, and passed the GPU-free verifier.
  Native binaries and provenance files in the `/opt` seed copy match the baked
  `/model` workspace by SHA-256. No GPU or model PVC was used.
- Post-publication NAS backup `registry-maya-m-published-v1` succeeded:
  Kopia snapshot `21cb1921e981377eed9e9063e1b5d2e2` (entire registry volume).
- The 60Gi build-cache PVC is retained. A publication retry reused every
  Dockerfile build step, including native compilation, from that cache.

The serving manifests remain unchanged. This receipt verifies the image, not
GPU inference, model loading, or vision ingestion; the earlier trial Pod has
completed and was not restarted by this work.

## Validation

```sh
image=kubernetes/apps/llm/llmkube/resources/manual/maya-m/image
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$image" -p test_image.py -v
sh -n "$image/build.sh"
kustomize build "$image"
```

During the real cluster build, `verify.py` checks Python version, source pin,
upstream engine/vision/pip stamps, AVX2-portable and CUDA architecture cache
settings, executable presence, `pip check`, upstream launcher help and `ldd`
for both native helpers. Only missing `libcuda.so.1` is permitted without a GPU;
other unresolved libraries fail the build. It does not inject a fake driver,
run native kernels, load a model, or claim vision answer correctness. Run the
same verifier after the future init-copy, then separately test actual loaded
health, completions and image ingestion with both GPU UUIDs and memory peaks.

Local recipe validation alone does not prove native compilation, package-index
availability or image publication. No workstation CUDA compilation is intended.
