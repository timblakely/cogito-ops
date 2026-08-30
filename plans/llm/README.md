# LLM stack research notes

Source HTML for six published Artifacts. Each file redeploys to the URL below
it — **pass that URL when republishing**, or a new artifact is created instead of
the existing one being updated.

| File | Artifact | URL |
| --- | --- | --- |
| `litellm-routing-teardown.html` | LiteLLM Routing Teardown | https://claude.ai/code/artifact/48d11ee1-4b07-4663-a58a-e85a57fd2a96 |
| `the-contested-gpu.html` | The Contested GPU | https://claude.ai/code/artifact/68ddd1e2-92ee-49fd-bc97-abad5fff7b9c |
| `foreman-and-toolhive.html` | Foreman and ToolHive | https://claude.ai/code/artifact/3bbe6e0b-d8af-4a5f-a596-7e266605951e |
| `the-idle-bench.html` | The Idle Bench | https://claude.ai/code/artifact/5a86a824-fbd0-4771-b5bc-cc7c1ff759ac |
| `the-portable-coordinator.html` | The Portable Coordinator | https://claude.ai/code/artifact/04ec2542-d4ac-4b25-8ffe-9ff428379a73 |
| `the-punch-list.html` | The Punch List | https://claude.ai/code/artifact/85ac2080-ee4b-4647-a696-315e49cd3023 |

The documents cross-link to each other by those URLs, so a link that changes
has to be updated in the other files as well.

Each document ends with a scoped implementation to-do list. Serial order across
the five: The Idle Bench -> LiteLLM Routing Teardown -> The Portable
Coordinator -> Foreman and ToolHive -> The Contested GPU (the gaming node is
deliberately last; nothing on the critical path waits for it).

## What each one covers

- **LiteLLM Routing Teardown** — how `llmkube`, `litellm-operator` and LiteLLM
  compose in `joryirving/home-ops`: which models serve, how the `auto` complexity
  router decides (and why it currently never routes), the fallback graph, and the
  plan for cogito — a cloud coordinator delegating to local subagents rather than
  per-request autorouting.
- **The Contested GPU** — GPU arbitration and game streaming: how a Wolf session
  preempts `llama-nvidia` on the 3090, why the video half produces no picture,
  what `shrinedogg/biggs.dog` had to get right, and how to plan a preemptible
  5070 Ti node.
- **Foreman and ToolHive** — the agentic half: GitHub issues to reviewed PRs on
  self-hosted models, the reviewer's deterministic rails, and the MCP gateway
  whose embedding-based tool optimizer runs through the same LiteLLM proxy.
- **The Idle Bench** — the hardware allocation for the coordinator era: retuning
  the Qwen endpoint for parallel-agent seats over context ceiling, kristeva's
  Arc A380 (a discrete card, not an iGPU) as the always-on embedding/rerank
  floor, the 5070 Ti as a preemptible utility node, why the Ceph NUCs keep no
  serving role, and which cloud provider sits in each role alias.
- **The Portable Coordinator** — the harness half, from `joryirving/dotfiles`:
  the pi.dev role agents priced like a market, subagents as isolated processes,
  the durable workflow layer (approval gates, trusted check registry, bounded
  repair), the same roles mirrored into opencode and Zed, and what cogito's own
  pi setup should lift.
- **The Punch List** — the glanceable status board over `plan.md`: what
  shipped, what is parked with triggers, what waits on events. Last updated
  2026-08-24, so it predates the 262k ceiling restore.

## Provenance and staleness

The first three documents read from `joryirving/home-ops` at
`eed15dcc0a05cdfefb365af7b7d3c99404865f70`, verified against the `litellm`
1.97.0 wheel, and compared with cogito at `674d1e0d`; the routing teardown's
S12 addendum reads home-ops through `695556bd` and `joryirving/dotfiles` at
`dde72c28` (both 2026-08-21). The Idle Bench reads from cogito's working tree
at `a94e24ce` plus live cluster state (kubectl) on 2026-08-21. The Portable
Coordinator reads `joryirving/dotfiles` at `dde72c28`. Line references and
file paths are to those commits and will drift.

Settled by decision rather than measurement (2026-08-21): the worker endpoint
runs FP8 spanning both 3090s; the single-card W4A16 A/B is deliberately
deferred and recorded as the fallback in the routing teardown's S10.

A third comparison cluster informs the implementation plan: Phor's ops/flux
(https://x0r.li/ops/flux, clusters/core-k3s/apps/llm) — one RTX Pro 6000
Blackwell with fractional co-tenancy, a hand-written LiteLLM ConfigMap, and
the same-model-only fallback rule plan.md adopts.

Claims explicitly labelled hypotheses rather than confirmed findings: the
missing `runtimeClassName: nvidia` as the cause of Wolf's black stream; the
device-plugin time-slicing arithmetic meaning `gpu: 2` may not span two physical
cards once two models run at once; kristeva's A380 identity (one NFD label) and
memory bandwidth; and The Idle Bench's seat arithmetic, which is a linear-KV
approximation its own §7 benchmark sweep exists to replace with data.

## Editing

These are self-contained pages — inline CSS, hand-authored inline SVG, Google
Fonts as the only external request. No build step: edit the HTML and republish
the same file path with its URL.
