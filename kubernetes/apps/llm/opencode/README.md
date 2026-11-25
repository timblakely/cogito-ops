# OpenCode browser tools

OpenCode has built-in web search and URL fetching; Camofox adds an interactive
browser for JavaScript pages, screenshots, clicks, forms, and authenticated
browsing. The existing Camofox Deployment is reused, not replaced.

The pod installs the pinned, standalone `@askjo/camofox-browser-mcp@1.13.0`
adapter in an init container. Only its small MCP dependencies are installed;
the browser stays in the Camofox pod. The adapter is mounted read-only in the
main container, so connecting an MCP server does not require an npm download.
This version exposes the core browser tools supported by our Camofox 1.8.0
server rather than newer tools requiring a browser-server upgrade.

The MCP server is named `camofox` under `mcp.servers`, using OpenCode V2's
configuration format. Its tools are discoverable through Code Mode. Use
`opencode mcp list` or `/mcps` to check the connection.

Credentials come from the existing `camofox-secrets` Kubernetes Secret,
maintained by External Secrets from 1Password; no token is stored in the
OpenCode configuration. Reloader rolls the pod when the secret changes.

The adapter uses `userId=tim`, matching the existing VNC desktop and persisted
browser profile, with `sessionKey=opencode` for newly created tabs. This
intentionally shares logged-in cookies with the browser at
`https://browser.timblakely.com/`; it is not a sandbox or a per-conversation
identity. OpenCode conversations share this browser identity and should close
only their own tabs when done. Snapshot before clicking or typing, and take a
new snapshot after navigation because element references change.
