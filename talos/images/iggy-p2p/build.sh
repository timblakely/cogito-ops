#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../../.." && pwd)
build_dir=${1:-/tmp/iggy-p2p-build}
kernel_dir=$build_dir/linux
driver_dir=$build_dir/nvidia
context_dir=$build_dir/extension-context
archive_dir=$build_dir/extension-archive
pkg_ref=v1.13.0-36-g6b315f7
kernel_version=6.18.36
driver_commit=51edebee79919b54f498c19a0be31982cd97646e

mkdir -p "$build_dir" "$kernel_dir" "$context_dir/modules" "$archive_dir" "$build_dir/out"

kernel_tar=$build_dir/linux-$kernel_version.tar.xz
if [[ ! -s "$kernel_tar" ]]; then
  curl -fsSL "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-$kernel_version.tar.xz" -o "$kernel_tar"
fi
printf '%s  %s\n' \
  fbab86c9f471c81075b280cca30bd85d790c060063a1245859b6344b07c9c44e \
  "$kernel_tar" | sha256sum --check --status

if [[ ! -f "$kernel_dir/Makefile" ]]; then
  tar -xf "$kernel_tar" -C "$kernel_dir" --strip-components=1
  curl -fsSL "https://raw.githubusercontent.com/siderolabs/pkgs/$pkg_ref/kernel/build/config-amd64" \
    -o "$kernel_dir/.config"
  for patch_name in \
    0001-net-macb-flush-PCIe-posted-write-after-TSTART-doorbe.patch \
    0002-net-macb-insert-PCIe-read-barrier-before-TX-completi.patch \
    0003-net-macb-add-TX-stall-watchdog-to-recover-from-lost-.patch \
    0004-PCI-prevent-shrink-bridge-window.patch \
    0005-slab-backport-flex-allocator-helpers.patch \
    0006-mm-page_table_check-do-not-track-special-PFN-mapped-PTEs.patch; do
    curl -fsSL "https://raw.githubusercontent.com/siderolabs/pkgs/$pkg_ref/kernel/build/patches/$patch_name" \
      -o "$build_dir/$patch_name"
    patch -d "$kernel_dir" -p1 < "$build_dir/$patch_name"
  done
fi

docker build -f "$script_dir/Dockerfile.build" -t iggy-talos-kernel-build:6.18.36 "$script_dir"
docker run --rm --cpus=12 --memory=24g \
  -v "$kernel_dir:/src" -w /src -e LLVM=1 -e ARCH=x86 \
  --entrypoint /bin/bash iggy-talos-kernel-build:6.18.36 \
  -lc 'make olddefconfig && make -j8 vmlinux modules'
test "$(cat "$kernel_dir/include/config/kernel.release")" = 6.18.36-talos
test -s "$kernel_dir/Module.symvers"

if [[ ! -d "$driver_dir/.git" ]]; then
  git clone --depth 1 --branch 595.71.05 \
    https://github.com/NVIDIA/open-gpu-kernel-modules.git "$driver_dir"
fi
test "$(git -C "$driver_dir" rev-parse HEAD)" = "$driver_commit"
if ! git -C "$driver_dir" apply --reverse --check "$repo_dir/talos/patches/nvidia-595.71.05-p2p.patch" 2>/dev/null; then
  git -C "$driver_dir" apply --check "$repo_dir/talos/patches/nvidia-595.71.05-p2p.patch"
  git -C "$driver_dir" apply "$repo_dir/talos/patches/nvidia-595.71.05-p2p.patch"
fi

docker run --rm --cpus=12 --memory=24g \
  -v "$kernel_dir:/src" -v "$driver_dir:/nvidia" -w /nvidia \
  -e LLVM=1 -e IGNORE_CC_MISMATCH=1 \
  --entrypoint /bin/bash iggy-talos-kernel-build:6.18.36 \
  -lc 'make -j8 modules SYSSRC=/src LD=ld.lld OBJDUMP=llvm-objdump'

for module in nvidia nvidia-uvm nvidia-modeset nvidia-drm nvidia-peermem; do
  cp "$driver_dir/kernel-open/$module.ko" "$context_dir/modules/"
done
cp "$script_dir/Dockerfile" "$script_dir/manifest.yaml" "$context_dir/"
docker build -t iggy-nvidia-p2p:595.71.05-v1.13.5 "$context_dir"

extension_container=$(docker create --entrypoint /nonexistent iggy-nvidia-p2p:595.71.05-v1.13.5)
trap 'docker rm "$extension_container" >/dev/null 2>&1 || true' EXIT
docker cp "$extension_container:/manifest.yaml" "$archive_dir/manifest.yaml"
docker cp "$extension_container:/rootfs" "$archive_dir/rootfs"
tar -C "$archive_dir" -cf "$build_dir/iggy-p2p-extension.tar" manifest.yaml rootfs
docker rm "$extension_container" >/dev/null
trap - EXIT

docker run --rm -i \
  -v "$build_dir/iggy-p2p-extension.tar:/input/iggy-p2p-extension.tar:ro" \
  -v "$build_dir/out:/out" \
  ghcr.io/siderolabs/imager:v1.13.5 - < "$script_dir/installer-profile.yaml"

printf 'Built installer assets in %s/out\n' "$build_dir"
