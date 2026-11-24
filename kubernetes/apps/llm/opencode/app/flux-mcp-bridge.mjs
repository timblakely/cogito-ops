// Relay MCP transports, rereading the projected identity on every HTTP request.
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire("/usr/local/lib/node_modules/@getpaseo/cli/package.json");
const { StreamableHTTPClientTransport } = require("@modelcontextprotocol/sdk/client/streamableHttp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const endpoint = new URL("http://mcp-flux-ops-proxy.llm.svc.cluster.local:8080/mcp");
const tokenFile = "/var/run/secrets/flux-mcp/token";
const upstream = new StreamableHTTPClientTransport(endpoint, {
  fetch: async (url, init) => {
    // Never forward the bearer identity to an OAuth redirect or another host.
    if (new URL(url).origin !== endpoint.origin) throw new Error("Unexpected MCP origin");
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${(await readFile(tokenFile, "utf8")).trim()}`);
    return fetch(url, { ...init, headers, redirect: "error" });
  },
});
const downstream = new StdioServerTransport();
let closing = false;
async function shutdown() {
  if (closing) return;
  closing = true;
  await Promise.allSettled([upstream.close(), downstream.close()]);
}
function report(error) {
  if (closing) return;
  // The SDK can recover from request/SSE errors; do not kill its reconnect loop.
  process.stderr.write(`Flux MCP transport error: ${error.message}\n`);
}
function fatal(error) {
  report(error);
  process.exitCode = 1;
  void shutdown();
}
upstream.onmessage = message => {
  if (message.result?.protocolVersion) upstream.setProtocolVersion(message.result.protocolVersion);
  void downstream.send(message).catch(fatal);
};
downstream.onmessage = message => {
  void upstream.send(message).catch(error => {
    report(error);
    if (message.id !== undefined) {
      // A lost write response is ambiguous: report it, never replay writes blindly.
      void downstream.send({
        jsonrpc: "2.0", id: message.id,
        error: { code: -32603, message: "Flux MCP request failed; verify state before retrying." },
      }).catch(fatal);
    }
  });
};
upstream.onerror = report;
downstream.onerror = fatal;
upstream.onclose = () => { void shutdown(); };
downstream.onclose = () => { void shutdown(); };
process.on("SIGTERM", () => { void shutdown(); });
process.on("SIGINT", () => { void shutdown(); });
await upstream.start();
await downstream.start();
