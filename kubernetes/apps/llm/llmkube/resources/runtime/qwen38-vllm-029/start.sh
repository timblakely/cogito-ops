#!/usr/bin/env bash
set -euo pipefail

artifact_id="$${FA2_ARTIFACT_ID:?FA2_ARTIFACT_ID is required}"
artifact_manifest="/opt/club3090/fa2-artifacts/$${artifact_id}/manifest.json"

# Flux creates the artifact-export Job and this workload in one apply. Wait for
# the digest-pinned exporter to finish rather than racing it into CrashLoopBackOff.
for _ in $(seq 1 450); do
  test -f "$${artifact_manifest}" && break
  sleep 2
done
test -f "$${artifact_manifest}" || {
  echo "[fa2] artifact export did not complete: $${artifact_manifest}" >&2
  exit 1
}

if test -n "$${QWEN38_TARGET_PATH:-}"; then
  target_path="$${QWEN38_TARGET_PATH}"
  target_sha256="$${QWEN38_TARGET_SHA256:?QWEN38_TARGET_SHA256 is required}"
  mmproj_path="$${QWEN38_MMPROJ_PATH:?QWEN38_MMPROJ_PATH is required}"
  mmproj_sha256="$${QWEN38_MMPROJ_SHA256:?QWEN38_MMPROJ_SHA256 is required}"

  # The cache-prime Job and serving object reconcile together. Wait for its
  # atomic hot-tier installs, then reject a truncated or replaced model before
  # vLLM allocates either GPU.
  for _ in $(seq 1 1800); do
    test -f "$${target_path}" && test -f "$${mmproj_path}" && break
    sleep 2
  done
  test -f "$${target_path}" && test -f "$${mmproj_path}" || {
    echo "[gguf] Q6_K target or BF16 projector did not arrive in the hot cache" >&2
    exit 1
  }
  printf '%s  %s\n%s  %s\n' \
    "$${target_sha256}" "$${target_path}" \
    "$${mmproj_sha256}" "$${mmproj_path}" | sha256sum --check --strict

  # Fail closed if a future image rebuild omits the pinned CUDA extension or
  # silently changes the vLLM base underneath these source overlays.
  python3 -c 'from importlib.metadata import version; assert version("vllm") == "0.29.0"; import vllm_gguf_plugin.ops as ops; assert ops._CUDA_AVAILABLE'
fi

# These anchor-checked overlays are the exact club-3090 v0.29.0 profile set.
# Every script is idempotent and refuses startup if the vLLM source has drifted.
python3 /runtime/patch_mamba_drop_eagle_block.py
python3 /runtime/patch_gdn_mtp_async_spec_order.py
python3 /runtime/patch_dflash_dense_kv.py
python3 /runtime/patch_gguf_dflash2_arch.py
mkdir -p /etc/club3090
python3 /runtime/install_artifact.py --tp 2
source /etc/club3090/fa2-runtime.env

# Iggy's cards have no NVLink. Enable NCCL PCIe peer transfers only when the
# driver reports every off-diagonal read path as OK; custom all-reduce stays
# disabled, matching the validated profile.
if nvidia-smi topo -p2p r 2>/dev/null | awk '
  $1 ~ /^GPU[0-9]+$/ {
    has_x = 0
    for (i = 2; i <= NF; i++) if ($i == "X") has_x = 1
    if (!has_x) next
    rows++
    for (i = 2; i <= NF; i++) if ($i != "X" && $i != "OK") bad = 1
  }
  END { exit (rows > 0 && !bad) ? 0 : 1 }
'; then
  export NCCL_P2P_DISABLE=0
  export NCCL_P2P_LEVEL="$${NCCL_P2P_LEVEL:-PHB}"
  echo "[p2p] driver confirms PCIe peer access; NCCL P2P enabled at $${NCCL_P2P_LEVEL}"
else
  export NCCL_P2P_DISABLE=1
  unset NCCL_P2P_LEVEL || true
  echo "[p2p] peer access unavailable; NCCL P2P disabled"
fi

exec vllm serve --disable-custom-all-reduce "$@"
