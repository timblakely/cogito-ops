FROM docker.io/library/ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils ca-certificates curl g++ xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY compat.cpp /tmp/compat.cpp

RUN set -eux; \
    curl --fail --location --retry 3 \
      'https://repo.radeon.com/rocm/apt/7.1.1/pool/main/r/rccl7.1.1/rccl7.1.1_2.27.7.70101-38~24.04_amd64.deb' \
      -o /tmp/rccl.deb; \
    echo 'f5dd7cfde37daa0124d50e5cc6c2054e5cc1d5f7396753caf562c9a16384d5f8  /tmp/rccl.deb' | sha256sum -c -; \
    mkdir -p /tmp/rccl /payload; \
    ar p /tmp/rccl.deb data.tar.xz | tar -xJf - -C /tmp/rccl \
      ./opt/rocm-7.1.1/lib/librccl.so.1.0.70101; \
    cp /tmp/rccl/opt/rocm-7.1.1/lib/librccl.so.1.0.70101 /payload/librccl.so.1; \
    g++ -shared -fPIC -O2 /tmp/compat.cpp -o /payload/libiggy-rccl-compat.so; \
    test "$(stat -c %s /payload/librccl.so.1)" -gt 100000000; \
    ! grep -a -q hidden_hostcall_buffer /payload/librccl.so.1; \
    rm -rf /tmp/rccl /tmp/rccl.deb

FROM docker.io/library/busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e
LABEL org.opencontainers.image.source="https://github.com/timblakely/cogito-ops"
COPY --from=build /payload/ /payload/
CMD ["sh", "-ec", "cp /payload/librccl.so.1 /compat/librccl.so.1; cp /payload/libiggy-rccl-compat.so /compat/libiggy-rccl-compat.so; sha256sum /compat/librccl.so.1"]
