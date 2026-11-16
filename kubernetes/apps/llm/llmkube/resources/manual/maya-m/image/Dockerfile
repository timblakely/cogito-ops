FROM docker.io/nvidia/cuda:13.0.0-devel-ubuntu24.04@sha256:435220c0fef35cbf712e11999f8670a83835ef3cdd18564e5e8122f83078c88c
LABEL org.opencontainers.image.source="https://github.com/mw00/project-maya" \
      org.opencontainers.image.revision="d93d1499021b98a39bede20d33368907f1ea4ad8" \
      org.opencontainers.image.version="1.1.64"
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    MAYA_UPDATE_CHECK=0 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_CONSTRAINT=/opt/maya-build/requirements.txt
# Keep the pinned devel base: no unverified runtime CUDA-library surgery.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl git ninja-build python3 python3-venv python3-pip \
      libnccl2=2.27.7-1+cuda13.0 libnccl-dev=2.27.7-1+cuda13.0 \
    && rm -rf /var/lib/apt/lists/*
COPY build_runtime.py requirements.txt /opt/maya-build/
WORKDIR /model/maya-work/project-maya
RUN curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 --max-time 600 \
      https://codeload.github.com/mw00/project-maya/tar.gz/d93d1499021b98a39bede20d33368907f1ea4ad8 \
      -o /opt/maya-build/source.tar.gz \
    && echo '8ecdf7b255cd5912b5028ed8775e44c263ccb1bb283177c35bd5de56c36a1c7e  /opt/maya-build/source.tar.gz' | sha256sum --check \
    && tar -xzf /opt/maya-build/source.tar.gz --strip-components=1 -C . \
    && printf '%s\n' d93d1499021b98a39bede20d33368907f1ea4ad8 > .cogito-source-commit \
    && test "$(cat VERSION)" = 1.1.64 \
    && rm /opt/maya-build/source.tar.gz
# Preseed the upstream dependency at its pinned path, with an archive checksum gate.
RUN curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 --max-time 600 \
      https://codeload.github.com/ggml-org/llama.cpp/zip/3cf03257f219afbe7334045ff7c6a06ac68c627d \
      -o /opt/maya-build/llama.zip \
    && echo 'cbe23c594282ead2937abb3f008e51fcec4609d9256652fff42c7cc1c21ea47b  /opt/maya-build/llama.zip' | sha256sum --check \
    && python3 -m zipfile -e /opt/maya-build/llama.zip /opt/maya-build/unpack \
    && mv /opt/maya-build/unpack/llama.cpp-3cf03257f219afbe7334045ff7c6a06ac68c627d third_party/llama.cpp \
    && rm -rf /opt/maya-build/llama.zip /opt/maya-build/unpack
RUN python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
    && python3 -m venv .venv \
    && .venv/bin/python -m pip install --no-cache-dir -r /opt/maya-build/requirements.txt \
    && .venv/bin/python /opt/maya-build/build_runtime.py \
    && .venv/bin/python -m pip freeze > /opt/maya-build/pip-freeze.txt \
    && dpkg-query -W > /opt/maya-build/dpkg-packages.txt
# Commit expensive compilation independently of the final verification gate.
COPY verify.py /opt/maya-build/
RUN .venv/bin/python /opt/maya-build/verify.py
# The /opt copy survives a future PVC mounted at /model. Copy it back to the
# exact build path through a nested emptyDir init; venv shebangs are absolute.
RUN find build build-vision -type f \( -name '*.o' -o -name '*.a' \) -delete \
    && mkdir -p /opt/maya-image \
    && cp -a /model/maya-work/project-maya /opt/maya-image/project-maya
ENTRYPOINT ["/model/maya-work/project-maya/setup.sh"]
CMD ["--help"]
