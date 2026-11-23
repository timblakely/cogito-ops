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
# So: keep the pinned upstream binary exactly as published, add the tooling an
# agent needs, and create the uid 1000 user the HelmRelease runs as.
#
# The base is pinned by its amd64 digest (the same digest convention the rest of
# this repo uses for cluster images), so this child image is reproducible and a
# floating upstream tag can never silently change what the pod runs.

ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.3.2@sha256:43d4d0fb1d94fed8db615f865df7661104a39af6ca94dad631c09844b5e3ff22
FROM ${OPENCODE_IMAGE}

USER root

# git + openssh-client: snapshots, commits, cloning work repos.
# bash: upstream ships only busybox ash; agent shell tool calls and any
#   shell-oriented helper script written into a workspace expect bash.
# ca-certificates + curl: HTTPS egress for provider APIs, MCP servers and
#   plugin installs, plus a usable in-pod health probe.
RUN apk add --no-cache \
      git \
      openssh-client \
      bash \
      ca-certificates \
      curl \
      tzdata

# uid/gid 1000 is what the HelmRelease pod securityContext runs as; the PVCs
# mounted over /home/opencode and /workspace are chowned by fsGroup.
RUN adduser -D -u 1000 -h /home/opencode opencode \
    && mkdir -p /workspace \
    && chown -R opencode:opencode /home/opencode /workspace

USER 1000
ENV HOME=/home/opencode
WORKDIR /workspace

# Entrypoint is inherited from upstream (`opencode`); the HelmRelease supplies
# the `serve --hostname ... --port ...` arguments.
