# LLM stack research notes

Source HTML for four published Artifacts. Each file redeploys to the URL below
it — **pass that URL when republishing**, or a new artifact is created instead of
the existing one being updated.

| File | Artifact | URL |
| --- | --- | --- |
| `litellm-routing-teardown.html` | LiteLLM Routing Teardown | https://claude.ai/code/artifact/48d11ee1-4b07-4663-a58a-e85a57fd2a96 |
| `the-contested-gpu.html` | The Contested GPU | https://claude.ai/code/artifact/68ddd1e2-92ee-49fd-bc97-abad5fff7b9c |
| `foreman-and-toolhive.html` | Foreman and ToolHive | https://claude.ai/code/artifact/3bbe6e0b-d8af-4a5f-a596-7e266605951e |
| `the-idle-bench.html` | The Idle Bench | https://claude.ai/code/artifact/5a86a824-fbd0-4771-b5bc-cc7c1ff759ac |

The documents cross-link to each other by those URLs, so a link that changes
has to be updated in the other files as well.

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

## Provenance and staleness

The first three documents read from `joryirving/home-ops` at
`eed15dcc0a05cdfefb365af7b7d3c99404865f70`, verified against the `litellm`
1.97.0 wheel, and compared with cogito at `674d1e0d`. The Idle Bench reads from
cogito's working tree at `a94e24ce` plus live cluster state (kubectl) on
2026-08-21. Line references and file paths are to those commits and will drift.

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
