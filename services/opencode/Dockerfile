# Cogito child image for the OpenCode coding agent.
#
# The upstream image (ghcr.io/anomalyco/opencode) is Alpine + the single
# `opencode` binary + ripgrep, and runs as root. Two gaps make it unusable as a
# long-lived cluster service rather than a one-off `docker run`:
#
#   * No git. Filesystem snapshots — the mechanism behind /undo and /redo —
#     require a Git worktree: upstream states plainly that outside a repository
#     "it cannot restore files". A coding agent that cannot inspect, commit or
#     diff a repository is also not doing its job.
#   * No non-root user. Every cogito workload runs with runAsNonRoot and a
#     read-only-ish root filesystem; upstream has no user at all, so the UID
#     has no HOME and no writable owner for the config/state/session volume.
#
# The same image also backs the Paseo sidecar: the pod's second container
# runs `paseo daemon run` with this image, the same HOME volume and the same
# /workspace, pointing at `opencode serve` over localhost. That needs Node,
# the pinned @getpaseo/cli, and the v2 bridge plugin OpenCode loads, so this
# image ships all three.
#
# So: keep the pinned upstream binary exactly as published, add the tooling an
# agent needs, and create the uid 1000 user the HelmRelease runs as.
#
# The base is pinned by its amd64 digest (the same digest convention the rest of
# this repo uses for cluster images). Base updates are explicit; OS packages
# and npm transitive dependencies can still change between clean rebuilds.

ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.4.1@sha256:3759026602e055d93cc357dbc59a4d5c8120a4323f99573de130ba3c59fc2d52
# Static musl binary, mise 2026.11.13 (linux/amd64).
FROM ghcr.io/jdx/mise@sha256:6115f8d37719375ccd8aa0003884384182e15695dac762649586cc41754ad2a0 AS mise
FROM ${OPENCODE_IMAGE}

USER root

# Keep OS dependencies in the image; per-project versions can use mise under
# the writable HOME. coreutils also fixes Paseo's env -S launcher on Alpine.
COPY packages.txt /tmp/packages.txt
RUN xargs apk add --no-cache < /tmp/packages.txt \
    && apk info -vv > /opt/opencode-apk-packages.txt \
    && rm /tmp/packages.txt
COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise

# Alpine's kubectl is newer than the cluster's supported client skew. Download
# the matching minor explicitly and verify against upstream's checksum.
ARG KUBECTL_VERSION=1.34.2
RUN curl --fail --silent --show-error --location \
      "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /tmp/kubectl \
    && curl --fail --silent --show-error --location \
      "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" -o /tmp/kubectl.sha256 \
    && printf '%s  /tmp/kubectl\n' "$(cat /tmp/kubectl.sha256)" | sha256sum -c - \
    && install -m 0755 /tmp/kubectl /usr/local/bin/kubectl \
    && rm /tmp/kubectl /tmp/kubectl.sha256

RUN npm install --global --omit=dev @getpaseo/cli@0.17.3 \
    && npm cache clean --force

# GenUI is immutable image content, not a package patched on the home claim.
# Unexpected upstream changes must fail compatibility checks before publication.
COPY genui-package.json /opt/paseo-genui/package.json
COPY genui-package-lock.json /opt/paseo-genui/package-lock.json
COPY patch-genui.py configure-paseo.py test_genui_compat.mjs test_genui_bootstrap.py /opt/paseo-compat/
RUN npm ci --prefix /opt/paseo-genui --omit=dev --ignore-scripts --no-audit --no-fund \
    && python3 /opt/paseo-compat/patch-genui.py /opt/paseo-genui/node_modules/paseo-plugin-genui \
    && GENUI_PACKAGE_ROOT=/opt/paseo-genui/node_modules/paseo-plugin-genui \
       PASEO_AGENT_ROOT=/usr/local/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server/dist/server/server/agent \
       node --test /opt/paseo-compat/test_genui_compat.mjs \
    && GENUI_PACKAGE_ROOT=/opt/paseo-genui/node_modules/paseo-plugin-genui \
       python3 -m unittest discover -s /opt/paseo-compat -p test_genui_bootstrap.py -v \
    && npm cache clean --force

# uid/gid 1000 is what the HelmRelease pod securityContext runs as; the PVCs
# mounted over /home/opencode and /workspace are chowned by fsGroup.
RUN adduser -D -u 1000 -h /home/opencode opencode \
    && mkdir -p /workspace \
    && chown -R opencode:opencode /home/opencode /workspace

# The OpenCode v2 bridge plugin, generated at build time by the installed
# server package's own materializeOpenCodeV2Plugin() — never a copy of
# developer-laptop files. The pod's initContainer seeds /opt/paseo-bridge
# into the OpenCode plugins directory on the shared HOME volume, where
# `opencode serve` loads it.
COPY materialize-bridge.mjs /tmp/materialize-bridge.mjs
RUN node /tmp/materialize-bridge.mjs "$(npm root -g)/@getpaseo/cli" /opt/paseo-bridge \
    && rm /tmp/materialize-bridge.mjs \
    && chown -R opencode:opencode /opt/paseo-bridge

COPY smoke.sh /usr/local/bin/opencode-image-check
RUN chmod 0755 /usr/local/bin/opencode-image-check

USER 1000
ENV HOME=/home/opencode
WORKDIR /workspace
RUN opencode-image-check

# Entrypoint is inherited from upstream (`opencode`); the HelmRelease supplies
# the `serve --hostname ... --port ...` arguments, and the Paseo sidecar
# overrides the command with `paseo daemon run`.
