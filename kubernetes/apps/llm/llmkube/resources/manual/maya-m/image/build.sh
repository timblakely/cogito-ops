#!/bin/sh
set -eu
# Called only inside the bounded BuildKit Job, not as a workstation image build.
context=/scratch/context
mkdir -p "$context" /scratch/buildkit
for file in Dockerfile build_runtime.py verify.py requirements.txt; do
    cp "/scripts/$file" "$context/$file"
done
# A privileged OCI worker otherwise creates host-root /buildkit cgroups and
# moves its daemon to /init, bypassing the Pod's CPU/memory limits on Talos.
container_cgroup=
while IFS=: read -r hierarchy controllers location; do
    if [ "$hierarchy" = 0 ]; then container_cgroup=$location; fi
done < /proc/self/cgroup
case "$container_cgroup" in
    /kubepods/pod*/*) pod_cgroup=${container_cgroup%/*} ;;
    *) echo 'Expected a Talos cgroup-v2 Pod container; refusing unbounded build' >&2; exit 1 ;;
esac
read -r quota period < "/sys/fs/cgroup$pod_cgroup/cpu.max"
read -r memory < "/sys/fs/cgroup$pod_cgroup/memory.max"
[ "$quota" != max ] && [ "$memory" != max ]
# Set this at daemon level: putting the Pod UID in a frontend cgroup-parent
# option changes RUN cache keys and defeats cache reuse after Pod replacement.
while IFS= read -r line; do
    printf '%s\n' "$line"
    if [ "$line" = '[worker.oci]' ]; then
        printf '  defaultCgroupParent = "%s"\n' "$pod_cgroup"
    fi
done < /scripts/buildkitd.toml > /scratch/buildkitd.toml
addr=unix:///scratch/buildkit.sock
buildkitd --root /scratch/buildkit --config /scratch/buildkitd.toml --addr="$addr" \
    > /scratch/buildkitd.log 2>&1 &
daemon=$!
trap 'kill "$daemon" 2>/dev/null || true; wait "$daemon" 2>/dev/null || true' EXIT
attempt=0
until buildctl --addr="$addr" debug workers >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then cat /scratch/buildkitd.log >&2; exit 1; fi
    sleep 1
done
printf '%s\n' "$daemon" > "/sys/fs/cgroup$container_cgroup/cgroup.procs"
grep -Fx "0::$container_cgroup" "/proc/$daemon/cgroup"
printf 'BUILD_POD_LIMITS cpu=%s/%s memory=%s parent=%s\n' "$quota" "$period" "$memory" "$pod_cgroup"
buildctl --addr="$addr" build \
    --frontend dockerfile.v0 \
    --local context="$context" \
    --local dockerfile="$context" \
    --opt platform=linux/amd64 \
    --output type=image,name=registry.timblakely.com/timblakely/maya-m:1.1.64-d93d1499,push=true \
    --metadata-file /scratch/image-metadata.json \
    --progress plain
