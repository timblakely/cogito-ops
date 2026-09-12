FROM ghcr.io/defilantech/llmkube-foreman-agent-coder@sha256:70622d517f626d8e25cb6a5c1d4a70dc5803ceaddf4615ef6d0e371fb8a68ba9

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gh jq unzip \
    && rm -rf /var/lib/apt/lists/*
USER 65532:0
