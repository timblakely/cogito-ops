# Rebuild only Wolf's C++ binary; retain the tested compositor, GStreamer,
# fake-udev, audio supervisor and runtime from Shrinedogg's pinned image.
ARG WOLF_BASE=docker.io/shrinedogg/wolf@sha256:9d062c45ed7533ba5949db3d739448a83aa6c85a712a41193c496d4b6c1158f8
FROM ${WOLF_BASE} AS builder
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build pkg-config ccache git patch ca-certificates \
      libboost-thread-dev libboost-locale-dev libboost-filesystem-dev libboost-log-dev \
      libboost-stacktrace-dev libboost-container-dev libboost-json-dev \
      libcurl4-openssl-dev libssl-dev libevdev-dev libpulse-dev libunwind-dev \
      libudev-dev libdrm-dev libpci-dev libglib2.0-dev libegl-dev libgles-dev \
      libopengl-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev && \
    rm -rf /var/lib/apt/lists/*
COPY wolf/ /build/wolf/
COPY cogito/patches/wolf-held-modifiers.patch /build/modifiers.patch
COPY cogito/scripts/tests/wolf-held-modifiers.cpp /build/wolf/held-modifiers-test.cpp
WORKDIR /build/wolf
RUN cp src/moonlight-server/control/input_handler.cpp input-handler-before.cpp && \
    patch --dry-run --fuzz=0 -p1 < /build/modifiers.patch && \
    patch --fuzz=0 -p1 < /build/modifiers.patch && \
    printf '\nadd_executable(held-modifiers-test held-modifiers-test.cpp)\ntarget_link_libraries(held-modifiers-test PRIVATE wolf::runner)\nadd_executable(held-modifiers-before held-modifiers-test.cpp input-handler-before.cpp)\ntarget_link_libraries(held-modifiers-before PRIVATE wolf::runner)\n' >> CMakeLists.txt
ARG BUILD_JOBS=2
RUN cmake -S . -B /build/cmake -G Ninja \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CXX_EXTENSIONS=OFF \
      -DCMAKE_CXX_FLAGS=-Wno-missing-template-arg-list-after-template-kw \
      -DBUILD_SHARED_LIBS=OFF -DBoost_USE_STATIC_LIBS=ON \
      -DBUILD_TESTING=OFF -DBUILD_FAKE_UDEV_CLI=OFF -DLINK_RUST_WAYLAND=OFF && \
    cmake --build /build/cmake --target wolf held-modifiers-test held-modifiers-before --parallel ${BUILD_JOBS} && \
    if /build/cmake/held-modifiers-before > /build/before.log 2>&1; then \
      echo 'ERROR: regression test did not reject the original handler'; exit 1; \
    fi && \
    grep -F 'FAIL: Letter key released a physically held modifier' /build/before.log && \
    /build/cmake/held-modifiers-test

FROM ${WOLF_BASE}
COPY --from=builder /build/cmake/src/moonlight-server/wolf /wolf/wolf
LABEL org.opencontainers.image.source="https://github.com/timblakely/cogito-ops" \
      org.opencontainers.image.revision="5ee830ae0e03322a6cf044652f5ea271f60161f0" \
      org.opencontainers.image.base.name="docker.io/shrinedogg/wolf@sha256:9d062c45ed7533ba5949db3d739448a83aa6c85a712a41193c496d4b6c1158f8" \
      io.cogito.wolf.modifier-fix="579e72adc88b593c1c5e3805a7baffeb14942e29"
