# Firecrawl

This is an internal-only, self-hosted web extraction service. It combines the
existing SearXNG instance for discovery with Firecrawl's crawler and Playwright
renderer for extraction. It is exposed only through the internal Envoy Gateway
at `https://firecrawl.<internal-domain>`. In-cluster callers may instead use
`http://firecrawl-api.tools.svc.cluster.local:3002`.

## Components

| Component | Role |
| --- | --- |
| SearXNG | Finds candidate URLs. |
| Firecrawl API | Scrapes, crawls, and converts pages into LLM-ready content. |
| Firecrawl Playwright service | Renders JavaScript-heavy pages for Firecrawl. |
| RabbitMQ | Firecrawl job queue. |
| Dragonfly | Firecrawl cache and rate-limit store (database 5). |
| CloudNativePG | Firecrawl queue/job persistence. |

## Use

After Flux reconciles the `firecrawl` Kustomization, test it from the LAN:

```sh
curl -sS https://firecrawl.<internal-domain>/v2/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/aclerici38/home-ops","formats":["markdown"]}'
```

SearXNG is configured in Firecrawl through `SEARXNG_ENDPOINT`; Firecrawl is the
fetch/extract layer that Hermes lacks when it uses SearXNG alone. Hermes
supports self-hosted Firecrawl directly:

```yaml
# ~/.hermes/config.yaml
web:
  backend: firecrawl
```

```sh
# ~/.hermes/.env
FIRECRAWL_API_URL=https://firecrawl.<internal-domain>
```

For a split setup, retain SearXNG discovery and use Firecrawl only for fetches:

```yaml
web:
  search_backend: searxng
  extract_backend: firecrawl
```

The Envoy route intentionally stays on the internal gateway but Firecrawl has
no API authentication in this self-hosted mode. Do not expose it publicly
without adding authentication, rate limits, and egress controls.
