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
# this repo uses for cluster images), so this child image is reproducible and a
# floating upstream tag can never silently change what the pod runs.

ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.4.1@sha256:3759026602e055d93cc357dbc59a4d5c8120a4323f99573de130ba3c59fc2d52
FROM ${OPENCODE_IMAGE}

USER root

# git + openssh-client: snapshots, commits, cloning work repos.
# bash: upstream ships only busybox ash; agent shell tool calls and any
#   shell-oriented helper script written into a workspace expect bash.
# ca-certificates + curl: HTTPS egress for provider APIs, MCP servers and
#   plugin installs, plus a usable in-pod health probe.
# nodejs + npm: the Paseo sidecar's runtime (`paseo daemon run`) and the
#   build-time bridge materializer below.
# jujutsu: the agent workspaces under /workspace are jj checkouts; the
#   agent commits, diffs and squashes with jj.
# python3: runtime tooling for the Node/npm stack in-pod.
RUN apk add --no-cache \
      git \
      openssh-client \
      bash \
      ca-certificates \
      curl \
      tzdata \
      nodejs \
      npm \
      jujutsu \
      python3

# Paseo CLI, pinned to the exact version the sidecar runs. Optional native
# deps (e.g. msgpackr-extract) may compile at install time, so make and g++
# ride along as a virtual package set and are removed once npm is done.
RUN apk add --no-cache --virtual .npm-build-deps make g++ \
    && npm install --global --omit=dev @getpaseo/cli@0.17.3 \
    && npm cache clean --force \
    && apk del .npm-build-deps

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

USER 1000
ENV HOME=/home/opencode
WORKDIR /workspace

# Entrypoint is inherited from upstream (`opencode`); the HelmRelease supplies
# the `serve --hostname ... --port ...` arguments, and the Paseo sidecar
# overrides the command with `paseo daemon run`.
