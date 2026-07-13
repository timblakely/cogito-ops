# Knowledge corpus

`knowledge` is the shared RAG service for Hermes and Open WebUI. It keeps the
GPU LLM deployment untouched: BGE-M3 runs in `knowledge-embeddings`, a separate
CPU-only vLLM server with the OpenAI-compatible `/v1/embeddings` endpoint.

## Sources

Add approved web roots to `app/sources.yaml`; the scheduled ingestion job uses
the internal Firecrawl API and updates only changed content. Do not commit large
documents. Place them in the OpenCloud **RAG Inbox** and configure the
`knowledge` 1Password item with the OpenCloud WebDAV credentials before enabling
file ingestion.

## Required 1Password item

Create an item named `knowledge` containing the OpenCloud WebDAV URL, username,
and password/token. The service also requires Pocket ID to issue tokens with a
`knowledge-readers` or `knowledge-admins` group claim.

## Hermes

Configure Hermes to use the self-hosted web stack for live research:

```yaml
# ~/.hermes/config.yaml
web:
  search_backend: searxng
  extract_backend: firecrawl
```

```sh
# ~/.hermes/.env
FIRECRAWL_API_URL=https://firecrawl.<internal-domain>
```

Then add the persistent knowledge corpus as an OAuth-protected MCP server. Use
the client ID created for `knowledge-mcp` in Pocket ID; the fixed callback port
must remain `37949` because it is registered with Pocket ID.

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  knowledge:
    url: https://knowledge.<internal-domain>/mcp
    auth: oauth
    oauth:
      client_id: "<Pocket-ID knowledge-mcp client ID>"
      redirect_port: 37949
      scope: "openid profile email groups knowledge.read"
```

Complete the initial browser login, then verify the connection:

```sh
hermes mcp login knowledge
hermes mcp test knowledge
```

Hermes can now use `knowledge_search` for the persistent corpus, while
`web_search` and `web_extract` continue to use SearXNG and Firecrawl for live
web research.
