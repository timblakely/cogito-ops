FROM ghcr.io/defilantech/llmkube-foreman-agent-coder@sha256:7aa935563ab6a28e6bd8b28eef0fe22d9b87f002cc189e068094de64829a6c5c

ARG GH_VERSION=2.82.1
ARG GH_SHA256=afada88676dfccea384e6cc28ae990b3e31bbc55f9d75c4697f902c757fa462b

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates jq unzip \
    && curl --fail --location --silent --show-error \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
      --output /tmp/gh.tar.gz \
    && echo "${GH_SHA256}  /tmp/gh.tar.gz" | sha256sum --check - \
    && tar --extract --gzip --file /tmp/gh.tar.gz --directory /usr/local/bin \
      --strip-components=2 "gh_${GH_VERSION}_linux_amd64/bin/gh" \
    && rm -rf /var/lib/apt/lists/* /tmp/gh.tar.gz \
    && cp /foreman-agent /foreman-agent.real
COPY --chmod=0755 foreman-agent-entrypoint /foreman-agent
USER 65532:0
