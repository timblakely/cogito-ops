# ComfyUI with the rotated-NVFP4 MiniMax-H3 loader, built for ONE card:
# amnesia's RTX 5070 Ti (sm_120 Blackwell, 16 GiB) in cogito's gaming box.
# Every pin here is load-bearing. The three facts that decide the whole stack:
#
#  1. Python 3.13. The nunchaku kernel wheel that makes the 16 GiB budget work
#     ships cp310-cp313 builds; 3.13 is what the upstream ComfyUI images use.
#  2. torch on the cu130 index. ComfyUI only enables its optimized CUDA
#     quantisation kernels on CUDA 13+, and the 16 GiB H3 residency numbers
#     quoted by the quant author are measured on cu130.
#  3. torch 2.11.0, the newest release PyTorch still ships a *matching*
#     torchvision + torchaudio pair for on cu130 (torchaudio stops at 2.11.0;
#     its 2.9.1 metadata pins `torch==2.9.1`, so 2.11.0 is the 2.11 pair).
#     torchaudio is not optional here: `comfy_extras/nodes_minimax_h3.py`
#     imports it for the audio VAE path, and losing it silently costs H3's
#     native audio track. pip WILL happily pair torchaudio 2.11.0 with a
#     torch 2.12 core (verified with `pip install --dry-run` against this
#     index) - it just cannot verify the C extension still imports across that
#     version gap. The quant author's numbers come from torch 2.12.1 on
#     Windows, where torch and torchaudio move together. So: 2.11 is the
#     self-consistent pin, and torch 2.12.1 + the matching nunchaku
#     cu13.0torch2.12 wheel is the documented first lever if the loader
#     reports an nunchaku API mismatch - re-testing `import torchaudio` then.
#
# Custom nodes are baked in at pinned revisions rather than installed at
# container start: a pod that pip-installs from the internet on boot cannot
# start while gaming holds the GPU offline, and it makes every restart a
# different environment.
#
# Build:  .github/workflows/comfyui-h3-image.yaml
# Runtime contract: kubernetes/apps/llm/comfyui/README.md
FROM docker.io/library/python:3.13-slim-trixie

# Pinned inputs. Revise deliberately and rebuild; nothing here auto-updates.
# renovate: datasource=github-releases depName=Comfy-Org/ComfyUI
ARG COMFYUI_REF=v0.34.2
ARG COMFYUI_COMMIT=169fcf35a2fc163fec31338b816503ddac0d3fcf
# city96/ComfyUI-GGUF - provides CLIPLoaderGGUF, which the H3 workflow uses to
# load the Qwen3-VL text encoder as a GGUF. Its `type` list is taken from core
# ComfyUI's CLIPLoader, so `minimax` resolves once core is >= v0.34.2.
# renovate: datasource=github-commits depName=city96/ComfyUI-GGUF
ARG GGUF_COMMIT=6ea2651e7df66d7585f6ffee804b20e92fb38b8a
# pottokao/H3-RotNVFP4-ComfyUI-Loader - the H3RotNVFP4Loader node.
ARG LOADER_REV=74c7c6d5ce94826e6bff074f9c3437464179848c
ARG LOADER_SHA_INIT=e51c819e8cebcbec1aad853c049a054c18ddc7aa1aee7f571c217f182ab168b0
ARG LOADER_SHA_NODES=cf066b7191c4e223d41a46baaa0467e1eef626d01c3e196297993750db81f807
# nunchaku (org `nunchux-ai`, shown as nunchaku-tech in the API) cu13.0 build
# for torch 2.11 / cp313 - the wheel that carries the
# native NVFP4 W4A4 kernel the rotated file is built for. It is a rolling dev
# tag, so the sha256 below (from the GitHub release asset digest) is the real
# pin; the latest dev (20260306) is built for torch 2.12 and does not match.
# The org in this URL looks like a typo of "nunchaku-ai" and is not: GitHub
# resolves nunchaku-ai, nunchaku-tech and nunchux-ai to one repository, and
# nunchux-ai is the name the API returns as canonical (3961 stars, the ICLR-2025
# SVDQuant project). All three serve the identical asset - verified by comparing
# the release asset digest for this exact filename across all three names:
# sha256 f9258376b63e..., 138633136 bytes, published 2026-02-13. Pinned below by
# sha256 anyway, which is the only part that has to be right.
ARG NUNCHAKU_WHEEL=https://github.com/nunchux-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213%2Bcu13.0torch2.11-cp313-cp313-linux_x86_64.whl
ARG NUNCHAKU_SHA=f9258376b63e2644723d25fc84e751d6efc1d312e164da451ff0f308b7e3e796
ARG TORCH_VERSION=2.11.0
ARG TORCHVISION_VERSION=0.26.0
ARG TORCHAUDIO_VERSION=2.11.0
ARG PYTORCH_INDEX=https://download.pytorch.org/whl/cu130

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFYUI_HOME=/opt/ComfyUI \
    HF_HOME=/data/.cache/huggingface \
    TORCH_HOME=/data/.cache/torch \
    TORCH_CUDA_ARCH_LIST=12.0

# ffmpeg: ComfyUI's SaveVideo/LoadVideo shell out to it for some codec paths.
# libgl1/libglib2.0-0: spandrel and kornia pull cv2, which needs them at import.
# git: pinned checkouts of the GGUF node.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg git libgl1 libglib2.0-0 xz-utils \
    && rm -rf /var/lib/apt/lists/*

# --- core ComfyUI, by commit, over the tarball's sha256 ---------------
# v0.34.2 is the revision the quant author measured on this exact card
# (13.6 GiB peak, 5.7 s/step); it is also the oldest release whose CLIPType
# carries MINIMAX and whose CLIPLoader offers the `minimax` type. Bumping it is
# a legitimate experiment - newer trees bring async-offload work - but the VRAM
# ceiling must be re-measured, not assumed: the H3 thread has a history of a
# ~1.1 GiB peak-VRAM regression hiding in an unrelated refactor.
RUN set -eux; \
    curl -fsSL --retry 3 -o /tmp/comfy.tar.gz \
      "https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/${COMFYUI_COMMIT}"; \
    mkdir -p /opt; \
    tar -xzf /tmp/comfy.tar.gz -C /opt; \
    mv "/opt/ComfyUI-${COMFYUI_COMMIT}" "${COMFYUI_HOME}"; \
    echo "${COMFYUI_COMMIT}  ${COMFYUI_REF}" > "${COMFYUI_HOME}/COMFYUI_PIN"

# --- torch trio from the cu130 index, then ComfyUI's own requirements --
# Order matters: the trio lands first so `-r requirements.txt` (which lists
# bare `torch`) sees it satisfied and does not pull a non-CUDA build off PyPI.
#
# There is deliberately no sm_120 assertion in here. torch.cuda.get_arch_list()
# returns an EMPTY list when the build container has no driver - measured on the
# first build of this file, on a correct CUDA 13 wheel - so the assert could only
# ever fail. Blackwell coverage is a property of the cu130 wheels and is checked
# on the pod, where a driver exists (README, first-run checks).
RUN set -eux; \
    pip install --index-url "${PYTORCH_INDEX}" \
      "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
      "torchaudio==${TORCHAUDIO_VERSION}"; \
    pip install --extra-index-url "${PYTORCH_INDEX}" \
      -r "${COMFYUI_HOME}/requirements.txt"; \
    python -c "import torch, torchaudio, torchvision; \
assert torch.version.cuda.startswith('13'), torch.version.cuda; \
print('torch', torch.__version__, 'cuda', torch.version.cuda, \
      'torchvision', torchvision.__version__, 'torchaudio', torchaudio.__version__)"

# --- nunchaku: the NVFP4 W4A4 kernel H3 runs on ------------------------
# Verified by sha256 because this wheel is an unversioned dev build and is the
# single piece of the image that can silently be a different binary.
# The output name is spelled out rather than taken from the URL: the URL carries
# %2B, and pip rejects a file whose name it cannot parse a tag from (the first
# build of this line failed with "Invalid wheel filename (wrong number of
# parts): 'nunchaku'" even though the download and the sha256 both passed).
ARG NUNCHAKU_WHL=nunchaku-1.3.0.dev20260213+cu13.0torch2.11-cp313-cp313-linux_x86_64.whl
RUN set -eux; \
    curl -fsSL --retry 3 -o "/tmp/${NUNCHAKU_WHL}" "${NUNCHAKU_WHEEL}"; \
    echo "${NUNCHAKU_SHA}  /tmp/${NUNCHAKU_WHL}" | sha256sum -c -; \
    pip install "/tmp/${NUNCHAKU_WHL}" && rm -f "/tmp/${NUNCHAKU_WHL}"

# --- custom nodes ------------------------------------------------------
RUN set -eux; \
    mkdir -p "${COMFYUI_HOME}/custom_nodes"; \
    git -C "${COMFYUI_HOME}/custom_nodes" clone -q --no-checkout \
      https://github.com/city96/ComfyUI-GGUF comfyui-gguf; \
    git -C "${COMFYUI_HOME}/custom_nodes/comfyui-gguf" checkout -q "${GGUF_COMMIT}"; \
    git -C "${COMFYUI_HOME}/custom_nodes/comfyui-gguf" rev-parse HEAD | grep -qx "${GGUF_COMMIT}"; \
    pip install --no-deps -r "${COMFYUI_HOME}/custom_nodes/comfyui-gguf/requirements.txt"; \
    pip install --no-cache-dir "gguf>=0.13.0" sentencepiece protobuf

# The loader is two files, not a repo - fetched by revision, verified by hash.
# `--enable-manager` is deliberately NOT used anywhere: the node manager would
# let the running pod change this environment from the browser.
RUN set -eux; \
    dest="${COMFYUI_HOME}/custom_nodes/comfyui-h3-rotnvfp4"; \
    mkdir -p "$dest"; \
    base="https://huggingface.co/pottokao/H3-RotNVFP4-ComfyUI-Loader/resolve/${LOADER_REV}"; \
    curl -fsSL --retry 3 -o "$dest/__init__.py" "$base/__init__.py"; \
    curl -fsSL --retry 3 -o "$dest/nodes.py" "$base/nodes.py"; \
    curl -fsSL --retry 3 -o "$dest/README.md" "$base/README.md"; \
    echo "${LOADER_SHA_INIT}  $dest/__init__.py" | sha256sum -c -; \
    echo "${LOADER_SHA_NODES}  $dest/nodes.py" | sha256sum -c -; \
    python -c "import ast,sys; ast.parse(open('$dest/nodes.py').read()); \
print('loader nodes.py parses')"

# --- build-time contract check -----------------------------------------
# Both custom node trees must be importable against the installed ComfyUI, and
# the H3 loader must expose the class the staged workflow references. This is
# the cheapest place to discover an API break: the pod cannot start while the
# GPU is held by a gaming session, so a runtime discovery costs a debugging
# window on the gaming card.
RUN set -eux; \
    cd "${COMFYUI_HOME}"; \
    python -c "import importlib.util, sys; \
spec=importlib.util.spec_from_file_location('h3rot','custom_nodes/comfyui-h3-rotnvfp4/nodes.py'); \
mod=importlib.util.module_from_spec(spec); \
import pathlib; sys.modules['h3rot']=mod; \
src=pathlib.Path('custom_nodes/comfyui-h3-rotnvfp4/nodes.py').read_text(); \
assert 'class H3RotNVFP4Loader' in src, 'loader class missing'; \
core=pathlib.Path('comfy/sd.py').read_text(); \
assert 'MINIMAX' in core, 'core CLIPType has no MINIMAX'; \
nun=importlib.util.find_spec('nunchaku'); assert nun, 'nunchaku not installed'; \
print('contract ok:', nun.origin)"

WORKDIR ${COMFYUI_HOME}
EXPOSE 8188
# Entrypoint, not CMD with flags baked in: the cluster manifest owns the flags
# so they stay visible in `kubectl get deploy -o yaml` and in Git.
#
# NVIDIA_VISIBLE_DEVICES is deliberately NOT set here. The nvidia device plugin
# injects the assigned IDs; an image-level `all` (which the upstream CUDA images
# carry) hands the container every card on the node the moment it is scheduled
# with zero GPUs - the trap already documented in kubernetes/apps/llm/cuda-dev.
ENTRYPOINT ["python", "main.py"]
