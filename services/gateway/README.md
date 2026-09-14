# Cogito gateway

This is the deterministic transport and policy boundary for Cogito's agentic
workflow. It accepts authenticated decrypted Matrix events and signed GitHub
webhooks, versions plans, records exact approvals, maintains an idempotent
outbox, and enforces serial Foreman delivery plus SHA-pinned merge safety.

The `planner` role is Astra, used only for conversation and synthesis. When it
needs repository facts, upstream research, or command output, it delegates up
to four focused tasks to local read-only Foreman planning scouts. The durable
gateway passes only their bounded summaries back to Astra, permits at most
two research rounds, and has no automatic paid-model fallback.

Images up to 8 MiB sent in a Cogito plan or implementation thread are
downloaded and decrypted by the maubot sidecar, described through the dedicated
local Muse `image` alias, and reduced to bounded text before Astra or Luna sees
them. A root-level image starts a plan when sent in the configured project room;
elsewhere it is handled only when its caption begins with `!cogito`.

The `coordinator` role is Luna. Repository and Matrix events are durably
coalesced into restart-safe Luna turns. Luna can act only through the gateway's
bounded tools; it cannot merge, change approval labels, read raw transcripts or
diffs, run a shell, or access secrets. Foreman owns coding, gates, repair, and
two-profile review. The gateway publishes reviewer evidence and merges only
after quorum and the required GitHub checks succeed.

The service uses only the Python standard library. Run its checks with:

```sh
python -m unittest discover -s tests -v
```

See [RUNBOOK.md](RUNBOOK.md) for the remaining commands and failure boundaries.
