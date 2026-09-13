# Async Agentic Homelab: Matrix-driven planning and execution on a Talos Kubernetes cluster

**Status:** design proposal, v1 (2026-09-12)
**Audience:** a reviewer (human or model) with *no* prior context about this cluster. Everything needed to evaluate the design is in this document; things that could not be verified are marked `[VERIFY]`, and deliberate choices that a reviewer might reasonably challenge are marked `[DECISION]`.

> Archival copy. This is the proposal exactly as reviewed on 2026-09-13; the review's findings and the corrected design are in `async-agentic-homelab-v2.md`.

---

## 0. Executive summary

The owner runs a self-hosted Kubernetes cluster (Talos Linux, GitOps-managed) with two RTX 3090s serving two local LLMs, a Matrix homeserver used from an Android phone via the Commet client, an existing in-house Kubernetes agent scheduler called **Foreman**, and a LiteLLM gateway that fronts both local and cloud models. They currently have a newborn and will be operating almost entirely from a phone in short bursts. The goal is an **asynchronous, notification-driven agentic system** where:

1. An expensive cloud planner model ("Astra") investigates a problem using cheap local workers, asks the owner questions, and produces a plan the owner reviews and approves **from the phone, inside Matrix**.
2. After approval, a cheaper coordinator (cloud "Luna Max Thinking", or a local model) executes the plan over local worker agents scheduled by Foreman, escalating only when a *planning* assumption breaks.
3. The owner can also open a direct, Codex-like coding session with a coordinator from Matrix, without SSH/tmux.
4. All of this runs on the existing cluster with **one** new custom component (`planner-gateway`) and configuration of things that already exist.

Key design decisions, each argued below:

- Foreman (Kubernetes CRDs) is the *only* orchestration substrate. No LangGraph; durable session state is a CRD.
- Plan review happens in Matrix (section-per-message + reactions), with git as the audit store. GitHub PRs are used only for **code**, not for plans.
- `planner-gateway` is a Matrix **appservice** (not a bot account) so it can puppet multiple personas and receive events by push.
- Direct coordinator sessions reuse an off-the-shelf headless harness (Codex CLI, pi, or opencode) running in a pod, bridged to a Matrix thread; the harness is not reimplemented.
- One 3090 serves Qwen 3.8-27B (via the `syv-ai/qwen38-27b-rtx3090` stack, vLLM 0.28.0-pinned), the other serves Meta's Muse Glimmer 30B (vLLM 0.29.0, W4A16 with an extra int8 requant of embeddings/lm_head to fit). Model diversity is the motivation, not a claimed quality ranking.
- Notifications collapse to one channel: Matrix push via UnifiedPush with self-hosted ntfy as the distributor, mention-gated so only state transitions ping the phone.

---

## 1. Context for the reviewer

### 1.1 The owner and the operating constraint

- Newborn at home; the owner is on an **Android phone**, in **limited attention spans**, for the foreseeable future.
- Preferred interaction: chat + push notifications. **Not** termux + ssh + tmux + a TUI. Every design choice is scored against "can this be done with one thumb, interrupted, and resumed three days later."
- The owner is an experienced infrastructure engineer: Talos Kubernetes, GitOps (Flux-style reconciliation), runs their own Matrix server, has written their own agent scheduler. Do not simplify the infrastructure; simplify the *interaction surface*.

### 1.2 Existing infrastructure (inventory)

Everything in this table already exists unless marked *new*.

| Component | What it is | Notes relevant to this design |
|---|---|---|
| **Talos Kubernetes cluster** | Immutable-OS k8s cluster, GitOps-managed (manifests in git, reconciled by a controller). | All new components must be deployable as manifests. No pets, no SSH-configured hosts. |
| **llmkube** | Kubernetes operator/tooling that runs LLM inference servers (vLLM-based) as k8s workloads. | Assumed to be the mechanism that deploys the two vLLM servers below. `[VERIFY]` whether llmkube can run a llama.cpp server if the Glimmer fallback path is needed. |
| **LiteLLM** (on node NUC-2) | OpenAI-compatible gateway/proxy. | Configured with **role aliases**, per-role API keys, budgets, and cloud fallbacks: `coordinator → Luna`, escalated roles → `GLM 5.3` / `K3`. This is where model routing, retries, and spend caps live. |
| **Foreman** | Owner-written Kubernetes agent scheduler. CRDs: `Agent`, `AgenticTask`, `Workload`. Features: capability-aware scheduling, tool whitelists, per-Agent concurrency limits, k8s Jobs, worker lifecycle management. | Its own docs say the *autonomous LLM planner* is explicitly **not** what Foreman provides. This design supplies that missing top layer and nothing else. |
| **Matrix homeserver** (Synapse assumed `[VERIFY]`) | Self-hosted chat server. | Owner already runs an agent bot there ("cogito") with awkward triggers such as `!cogito review sha256:<digest>`. Replacing that interface is a primary goal. |
| **Commet** | Android/desktop Matrix client (Flutter). Supports threads, spaces, E2EE, push notifications, UnifiedPush (since v0.2.0). | The owner's only UI. `[VERIFY]` whether Commet renders Matrix polls (`m.poll`) — affects one optional feature. |
| **ntfy** | Self-hostable pub/sub push service. Can act as a UnifiedPush distributor on Android and implements the Matrix push-gateway API. | Assumed already deployed or trivially deployable. |
| **GitHub** | Hosts the owner's repos. | Used for code PRs and as immutable storage for plan revisions. Not used as the plan-review UI. |
| **Matrix Hookshot** | Bridge that posts GitHub PR/review events into Matrix rooms. | Optional; used only for code PR visibility. |
| **Cloud models via LiteLLM** | "Astra" (expensive planner-class model), "Luna Max Thinking" (cheaper coordinator-class model), "GLM 5.3", "K3" (escalation targets). These are the owner's LiteLLM alias names. | Vendors are irrelevant to the design; the design only assumes Astra is expensive/high-quality and Luna is cheap/long-running-tolerant. |

### 1.3 Cluster hardware

| Node | Hardware | Role |
|---|---|---|
| **iggy** | Ryzen 9 desktop, 128 GB DDR4-3200, **2× RTX 3090 (24 GB each)** — the only Ampere (SM8.6) hardware in the cluster. Not enough PCIe 4.0 lanes for 3–4 GPUs. | LLM serving. One model per card (see §3). |
| **Kristeva** | Dual Xeon, 128 GB DDR3, Intel Arc A380, 40 GbE. Always on, never evicted. | Embedder/reranker, vision encode, CPU lane for MoE models. Not for the 3090s. |
| **5070 Ti node** | Single RTX 5070 Ti. | Compact VLM, "muse", Whisper. **Preemptible**: evicted whenever a game streams ("wolf session"). Anything scheduled here must tolerate eviction. |
| **NUC-1/2/3** (Meteor Lake) | Small nodes. | Ceph OSDs, vector DB, immich-ml. Deliberately no LLM serving. LiteLLM runs on NUC-2. |

Network constraint: the owner's desktop upload is ~40 Mbit/s, so pushing large container images from the desktop is slow. Prefer pulling public images or building in-cluster.

### 1.4 Prior design discussion (what a reviewer should know was already decided)

An earlier design pass (with another model) proposed and then partly retracted:

- **Retracted:** putting the coordinator (Luna) *between* Astra and the workers during planning. Rejected because it adds a lossy "telephone game" and a second paid model with no clear win. Astra talks to workers through a deterministic broker during planning; Luna only appears after plan approval. This document keeps that split.
- **Proposed there, rejected here:** LangGraph + Postgres as a durable "upper state machine." Rejected in §5.3 because Foreman already provides durable, reconciling, inspectable state and a second orchestration runtime with a different mental model is not worth it for an eight-state machine.
- **Proposed there, rejected here:** GitHub PRs as the plan-review surface. Rejected in §7 in favor of in-Matrix review with git as storage.
- **Kept:** structured result packets from workers (conclusion / evidence / uncertainty / follow-ups / artifacts) rather than transcripts; explicit escalation boundary between implementation decisions (Luna) and planning decisions (Astra/owner).

---

## 2. Roles and the conceptual hierarchy

```
You            set intent, answer questions, approve plans, approve code PRs.
Astra          decides WHAT should be done. Epistemic. Expensive, sparse, kept away from the world.
Luna           decides HOW to get approved work done. Operational. Cheap, persistent, babysits execution.
Local workers  DO the work: read code, write code, run tests, review. Qwen 3.8-27B and Muse Glimmer 30B.
Foreman        schedules the workers on GPUs and enforces limits. Deterministic.
planner-gateway  translates between Matrix ↔ session state ↔ Astra/Luna ↔ Foreman ↔ git. The only new code.
```

Two phases with different shapes:

**Planning / discovery** — `You ⇄ Matrix ⇄ Astra ⇄ (deterministic broker) ⇄ workers`. No Luna. Astra has exactly four conceptual tools: *delegate research to workers*, *inspect a result/artifact*, *ask the owner a question*, *publish/revise a plan*. It never has kubectl, shell, git, or filesystem tools.

**Implementation** — `Approved plan @ commit → Luna → workers → integration branch → code PR → You`. Astra is only re-entered when a *planning* assumption is broken (escalation table in §8.4).

---

## 3. Models and serving

### 3.1 Card 1: Qwen 3.8-27B on RTX 3090 #1

Served with the `syv-ai/qwen38-27b-rtx3090` stack (https://github.com/syv-ai/qwen38-27b-rtx3090), deployed via a colleague's ("Jory") 5-slot configuration. Facts from that repository that constrain this design:

- **vLLM pinned to 0.28.0** with a patch set applied at build; `verify.sh` gates the image. Do **not** independently bump this to vLLM 0.29 (see §3.4).
- Quantization: W4A16 AutoRound body + **int8 requantized lm_head and embeddings** (frees ~2.6 GB of KV pages — this trick is reused for Glimmer) + int4 GPTQ draft head. GSM8K 95–96.5% across configs; IFBench within one point of unquantized.
- Two serving modes, one per boot (a restart takes minutes — mode is not a runtime knob):
  - `batch` — plain continuous batching, 64 concurrent requests, ~1,000 tok/s aggregate, ~46 tok/s per stream, no speculation.
  - `single-user` — speculative decoding, either `SPEC=mtp` (default, 8 request slots, 64k context) or `SPEC=dflash2` (block drafter, faster per stream, smaller residency).
- **Residency is a prompt-length number, not a fixed seat count.** A resident request reserves recurrent-state pages before it holds any context. Under DFlash2 (`CTX=fast`): ~7 residents with 128-token prompts, **5 with 4k prompts, 2 with 16k prompts**. Under MTP: 8 residents, 4 of them at 16k. `MAX_SEQS` controls *admission*, not residency. "Jory's 5 slots" is therefore the 4k-prompt DFlash2 figure; agentic prompts carrying 16k+ of repo context get 2–4.
- Per-stream decode falls steeply with residency: DFlash2 137 → 97 → 46 → 33 tok/s at 1/2/4/8 streams; MTP 126 → 103 → 46 → 23. MTP keeps scaling to 8 streams; DFlash2 exhausts its pool at 5. The repo's guidance: point one person at DFlash2; point a team at MTP or batch mode.
- **Shared prefixes are worth ~10×.** Eight independent 16k-token streams: ~16 tok/s end-to-end aggregate. Same eight streams with one shared prefix and `PREFIX_CACHE=1`: ~148 tok/s. A second turn over a cached 25k-token document: 0.56 s to first token vs 22.4 s cold. This is the single most important serving fact for the broker design (§6.2).
- Tool calling: `--enable-auto-tool-choice --tool-call-parser qwen3_coder` (Qwen emits XML-style calls; the `hermes` JSON parser is wrong for this model). `TOOLS=0` disables. `VISION=0` by default drops the vision tower weights.
- Power: all numbers at 250 W. 200 W loses ~a third; >250 W thermal-throttles to the same throughput.
- Launch scripts use `single-user/start_qwen.sh` / `batch/start_qwen.sh`; check whether they still use the `python -m vllm.entrypoints.openai.api_server` entrypoint (deprecated in vLLM 0.29 in favor of `vllm serve`).

**Mode choice for this design `[DECISION]`:** run Qwen in `SPEC=mtp` single-user mode, `PREFIX_CACHE=1`, `--mamba-cache-mode align` (keeps recurrent-state pages resident for cached prefixes). It is the compromise that still batches to C8 for worker fan-out while giving ~100+ tok/s to an interactive stream. Switch to `batch` only if measured worker fan-out routinely exceeds ~6 concurrent long-context tasks. Foreman's Qwen `Agent` concurrency limit: start at **3** for long-context worker tasks; tune from measurement.

### 3.2 Card 2: Muse Glimmer 30B on RTX 3090 #2

Muse Glimmer 30B (Meta Superintelligence Labs, released 2026-08-10, Apache 2.0): dense ~29.6B vision-language model, 52-layer text decoder (hidden 6656), ~1.8B ViT-G/14 perception encoder, 128k trained context, ~202k vocabulary, untied lm_head. Positioned by Meta for "always-on local agents": tool use, long tasks, failure recovery. Independent benchmarks show it beating Qwen 3.6-27B on many but not all tasks; Qwen 3.8-27B shipped shortly after. Treat it as a **peer** of Qwen 3.8, not an upgrade. The reason to run it is model diversity (two independent views of the same problem, cross-review).

**Serving status (verified 2026-09-12):**

- vLLM support merged and released in **v0.28.0** (2026-08-26). v0.29.0 (2026-09-09) adds a Muse-Glimmer LoRA fix. The official vLLM recipe (https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B, updated 2026-09-09) pins `vllm/vllm-openai:v0.28.0`; either 0.28 or 0.29 works.
- Output format is unusual: **channel-scoped messages** with XML-style "ATEM" tool calls, not JSON and not `<think>` tags. Requires **both** `--tool-call-parser muse_glimmer --reasoning-parser muse_glimmer`; the reasoning parser forces `skip_special_tokens=False`. Without both, reasoning and content collapse together.
- `tool_choice="required"` and named `tool_choice` are **unsupported** (vLLM's guided decoding assumes JSON tool calls). Any harness step that forces a tool call must use prompting/JSON mode instead.
- Sampling must be `temperature=1.0, top_p=0.95, top_k=64`. Do not run greedy (non-reproducible anyway). Reasoning effort is set by a line in the system prompt: `Reasoning strength: low|medium|high|xhigh` — use `high`/`xhigh` for coding/agentic work. **Harnesses will not add this line; the LiteLLM alias or broker preamble must.**
- `max_tokens` must be generous: a tight budget can truncate before the final channel closes, returning empty `content` with `finish_reason: stop`. A harness that treats empty content as "done" silently loses turns.
- Speculative decoding: a DFlash draft head exists (5.11 GB, BF16). On a 32 GB RTX 5090 with the NVFP4 build it already OOMs. **There is no room for it on a 24 GB card in vLLM.** Plan for ~45 tok/s single-stream without speculation.
- The official quantized build is **NVFP4 (Blackwell-only kernels)** — not usable on Ampere. (This is the same gap the owner's separate "DL-NVFP4" project targets: running NVFP4 quants on Ampere INT8 tensor cores. Out of scope here.)

**The 24 GB VRAM problem.** Community W4A16 int4 checkpoints exist that load on Ampere via Marlin: `RedHatAI/Muse-Glimmer-30B-W4A16` (int4 g128, GPTQ via llm-compressor, compressed-tensors), `aisquared/Muse-Glimmer-30B-W4A16-LLMCompressor`, `Vishva007/Muse-Glimmer-30B-W4A16-AutoRound`, `kaitchup/Muse-Glimmer-30B-autoscheme-3.5bit`. All of them keep **embeddings, lm_head, and the vision tower in BF16**. Back-of-envelope: ~13 GB int4 decoder + ~2.7 GB embeddings + ~2.7 GB lm_head + ~3.6 GB vision ≈ **22 GB before KV cache**, leaving effectively nothing on a 3090. (Corroboration: the vLLM recipe notes the NVFP4 build is 25 GB "rather than the ~15 GB a uniform 4-bit quant would give" for exactly this reason.)

**Fix `[DECISION]`:** apply the same recipe syv-ai used for Qwen — requantize `embed_tokens` and `lm_head` to int8 with llm-compressor on top of the RedHatAI W4A16 checkpoint. Then:

| Config | Weights (est.) | KV budget (est., 0.92 util, ~1.5 GB graphs/activations) | Slots |
|---|---|---|---|
| int4 decoder + int8 embed/head + **BF16 vision** | ~19 GB | ~2.5 GB | 2 × ~64k (Glimmer KV/token is small — ~17 KB/token inferred from the recipe's RTX 5090 figures: 179,647-token KV in ~3 GB — thanks to GQA + alternating sliding-window layers) |
| int4 decoder + int8 embed/head + **vision dropped** | ~15.5 GB | ~6 GB | 4–6 × 64k, or 2 × 128k |

Keep vision on `[DECISION]`: the owner is on a phone; sending a screenshot or a photo of a whiteboard into a coordinator session is a real ergonomic win, and two 64k slots is the stated requirement ("at least two slots"). Re-evaluate if worker fan-out on Glimmer is ever the bottleneck.

**Fallback path: llama.cpp.** If the requant is more trouble than it is worth: Unsloth GGUF Q4_K_M (14.78 GiB on disk) + `mmproj` BF16 file + `dflash-kquant.gguf` drafter under `llama-server`, `--parallel 2`. Measured on a 3090 (Hardware Corner, llama.cpp, text-only): **16 GB VRAM through 32k context, 20 GB at 256k; 45 tok/s at 4k → 35 tok/s at 256k**. Notable: this path *does* get speculative decoding on Ampere (a k-quant drafter exists), which vLLM cannot. Costs: a second serving stack beside vLLM, and `[VERIFY]` that `llama-server --jinja` parses Glimmer's ATEM tool calls into OpenAI `tool_calls` (Meta announced day-0 llama.cpp support; parser behavior unconfirmed).

**Suggested vLLM launch (0.29.0 image):**

```
vllm serve /models/muse-glimmer-w4a16-int8head \
  --served-model-name muse-glimmer \
  --max-model-len 65536 --max-num-seqs 2 \
  --gpu-memory-utilization 0.92 \
  --enable-auto-tool-choice --tool-call-parser muse_glimmer \
  --reasoning-parser muse_glimmer \
  --generation-config auto \
  --enable-prefix-caching \
  --prefix-cache-retention-interval <set explicitly; see §3.4>
```

### 3.3 LiteLLM role aliases (proposed)

LiteLLM already routes by role. Proposed alias table (names illustrative; keep the owner's existing ones where they exist):

| Alias | Backend | Purpose | Notes |
|---|---|---|---|
| `planner` | Astra (cloud) | Planning/discovery reasoning | Hard per-session budget. Prompt caching if the vendor supports it. |
| `coordinator` | Luna Max Thinking (cloud), fallback `GLM 5.3`/`K3` | Execution coordination, direct sessions | Existing alias. Try `coordinator-local` (Glimmer) as a cheaper alternative once measured. |
| `coordinator-local` | Glimmer (local) | Same, local | Inject `Reasoning strength: high` into the system prompt at the alias level. Sampling pinned to 1.0/0.95/64. |
| `worker-scout` | Qwen or Glimmer (local) | Breadth: repo mapping, symbol tracing, narrow questions | Read-only tools. Small `max_tokens`. |
| `worker-deep` | Qwen (local) | Cross-file reasoning, coding, tests | Read/write tools inside a worker pod. |
| `reviewer` | the *other* local model from whichever did the work | Independent review | Model diversity is the point. |
| `escalation` | GLM 5.3 / K3 (cloud) | When local workers fail N times | Existing fallback. |

LiteLLM must translate the OpenAI **Responses API** to chat completions for backends that only speak chat completions — Codex CLI speaks Responses only. `[VERIFY]` end-to-end: (a) Qwen `qwen3_coder` tool calls and (b) Glimmer `muse_glimmer` tool calls + `reasoning_content` survive the LiteLLM translation for both chat-completions clients (pi, opencode) and Responses clients (Codex). This is the most likely first integration failure and should be tested before any gateway code is written.

### 3.4 vLLM version notes (0.28.0 vs 0.29.0)

- **Run the two cards on different vLLM versions.** Qwen stays on the syv-ai 0.28.0-pinned image until syv-ai rebases their patches; Glimmer runs 0.29.0. Separate pods, separate images — normal Kubernetes practice.
- 0.29.0 makes **Model Runner V2 the default for all models**; MRV1 is deprecated, removal targeted for v0.32. MRV2 does not yet support sequence parallelism, dual-batch overlap, custom logits processors, or some speculative methods (vLLM falls back to MRV1 if those are configured). The syv-ai stack already forces the V2 runner for DFlash2; its MTP mode is the one to re-verify after a rebase.
- 0.29.0 changes `prefix_cache_retention_interval` to a CLI argument **defaulting to 0 for SWA/SSM models**, with dense retention automatically restored only for hybrid models using EAGLE/MTP. Glimmer has sliding-window layers and no MTP; Qwen has SSM-style layers *with* MTP. Because §6.2's shared-prefix strategy depends on prefix-cache hits landing, **measure hit rates on both servers and set the interval explicitly** if hits drop.
- 0.29.0 adds `--per-request-spec-decode-metrics` (per-request acceptance stats in API responses) — the right instrument for choosing DFlash2 vs MTP on the owner's actual prompts — and `--max-num-queued-reqs` / `--max-num-queued-tokens` admission control, which should be set to agree with Foreman's per-Agent limits so vLLM is not the only thing without backpressure.
- 0.29.0 adds Mamba internal prefill checkpoints (9–25% TTFT improvement) — a free win for Qwen after the rebase.
- 0.29.0 deprecates `python -m vllm.entrypoints.openai.api_server` in favor of `vllm serve`.

---

## 4. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHONE (Commet)                                                             │
│   Space "Lab"                                                               │
│   ├─ #proj-<repo>  (one per project; thread = session)                      │
│   ├─ #fleet        (Luna/Foreman ops chatter, muted)                        │
│   ├─ #alerts       (Hookshot code-PR events, alertmanager; mentions only)   │
│   └─ DM @lab-luna  (direct coordinator sessions)                            │
│   push: Synapse → ntfy (Matrix push gateway) → UnifiedPush → Commet        │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │ appservice transactions (push) / client API (send/edit/react)
┌──────────────▼──────────────────────────────────────────────────────────────┐
│  planner-gateway  (NEW; Matrix appservice + k8s controller)                 │
│   • puppets @lab-astra, @lab-luna, @lab-fleet                               │
│   • owns PlanningSession CRD (state machine, §5.3)                          │
│   • routes owner messages by session state / mention / reaction            │
│   • renders + edits the session card and progress message                  │
│   • calls Astra/Luna via LiteLLM; calls Foreman via the broker (MCP)        │
│   • commits plan revisions to the agent-plans git repo                      │
│   • starts/stops harness pods for direct sessions                          │
└────┬───────────────────────┬─────────────────────────────┬──────────────────┘
     │ OpenAI/Responses API  │ MCP (submit/inspect/results/ │ git push / gh API
     ▼                       │        cancel/followup)      ▼
┌──────────┐            ┌────▼────────────────────┐   ┌──────────────┐
│ LiteLLM  │            │ Foreman broker (MCP)    │   │ GitHub       │
│ NUC-2    │            │ deterministic; enforces │   │ agent-plans/ │
│ aliases, │            │ seats, prefix protocol, │   │ code repos   │
│ budgets, │            │ result-packet schema    │   │ (PRs)        │
│ fallback │            └────┬────────────────────┘   └──────────────┘
└────┬─────┘                 │ AgenticTask CRs
     │                  ┌────▼────────────────────────────────────────┐
     │                  │ Foreman (existing k8s operator)             │
     │                  │ Agent / AgenticTask / Workload CRDs, Jobs,  │
     │                  │ tool whitelists, per-Agent concurrency      │
     │                  └────┬───────────────────────┬────────────────┘
     │                       │ worker Jobs           │ harness pods
     │                  ┌────▼───────┐        ┌──────▼──────────────────┐
     │                  │ worker pod │        │ harness pod (Codex/pi/  │
     │                  │ ephemeral  │        │ opencode, headless)     │
     │                  │ clone @SHA │        │ PVC session dir,        │
     │                  │ result pkt │        │ scoped worktree         │
     │                  └────┬───────┘        └──────┬──────────────────┘
     │                       │ OpenAI API             │
     ▼                       ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ iggy: RTX 3090 #1  Qwen 3.8-27B (vLLM 0.28.0, syv-ai, MTP, prefix cache)     │
│       RTX 3090 #2  Muse Glimmer 30B (vLLM 0.29.0, W4A16 + int8 head, vision) │
│ cloud (via LiteLLM): Astra (planner), Luna Max Thinking (coordinator),        │
│                      GLM 5.3 / K3 (escalation)                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. `planner-gateway` (the one new component)

### 5.1 Responsibilities

1. Matrix appservice: receive all events in its namespace rooms, send/edit/react as virtual users.
2. Kubernetes controller for the `PlanningSession` CRD: reconcile state, drive Astra/Luna turns, resume after restart.
3. Router: map an incoming owner message/reaction to (session, phase, recipient).
4. Renderer: session card, progress message, plan-as-sections, question prompts.
5. Git client: commit plan revisions, open code PRs (or delegate to Luna's tools).
6. Pod launcher for direct harness sessions (§9).

It does **not** contain an agent loop, tool sandbox, or scheduler. Those are Foreman, the broker, and the harness.

### 5.2 Why an appservice, not a bot account `[DECISION]`

- Events are **pushed** to the gateway via appservice transactions; no `/sync` long-poll, no sync-token persistence, no lost events across restarts.
- One registration can **puppet multiple users** (`@lab-astra`, `@lab-luna`, `@lab-fleet`) under a namespace like `@lab-.*`. Distinct senders with distinct avatars are what make a thread readable on a phone without prefixes.
- Appservice registration YAML is a static file mounted into Synapse — GitOps-friendly.

**E2EE is off in agent rooms `[DECISION]`.** Appservice end-to-end encryption remains the most painful part of the Matrix bot ecosystem; this is the owner's own homeserver on their own hardware, and the owner's attention is the scarce resource. Rooms carrying agent traffic are created unencrypted. Personal rooms are unaffected.

### 5.3 `PlanningSession` CRD (replaces LangGraph) `[DECISION]`

Rationale: the "durable upper state machine" has ~8 states and one blocking primitive (wait for a human). Foreman already gives durable, reconciling, `kubectl`-inspectable state; a CRD keyed by the Matrix thread-root event ID gives free restart semantics and shows up in the same tooling as everything else. LangGraph + Postgres would be a second orchestrator with a Python runtime, its own checkpointer, and a different mental model, maintained forever for an eight-state machine.

```yaml
apiVersion: lab.example/v1alpha1
kind: PlanningSession
metadata:
  name: sess-<short-hash-of-thread-root-event-id>
  namespace: agents
spec:
  matrix:
    roomId: "!abc:example.org"
    threadRootEventId: "$xyz"
    cardEventId: "$card"          # the session card (edited in place)
    progressEventId: "$progress"  # the worker table (edited in place)
  project:
    repo: "github.com/owner/homelab"
    baseSha: "a1b2c3d"
    allowedAgents: [worker-scout, worker-deep, reviewer]
  budget:
    plannerUsdCap: 5.00
    coordinatorUsdCap: 3.00
    workerTaskCap: 40
  request: "Replace the auth middleware with X; keep websocket auth working."
status:
  phase: DISCOVERING   # see state machine
  planRevision: 3
  planCommitSha: "..."          # agent-plans repo
  approvedCommitSha: ""         # frozen at APPROVED
  openQuestion: { eventId: "$q7", text: "...", options: [...] }
  activeTasks: [ {foremanTask: "task-238", role: worker-deep, model: qwen, state: running} ]
  integrationBranch: "session/sess-…/integration"
  spend: { plannerUsd: 1.42, coordinatorUsd: 0.31, workerTasks: 9 }
  notesArtifact: "agent-plans/sessions/sess-…/notes.md"
  lastTransition: "2026-09-12T20:11:00Z"
  conditions: [...]
```

**State machine:**

```
NEW ─► DISCOVERING ─► NEEDS_INPUT ─► DISCOVERING (loop)
                 └──► PLAN_READY ─► REVISING ─► PLAN_READY (loop)
                                └──► APPROVED ─► EXECUTING ─► DONE
                                                   ├──► BLOCKED ─► EXECUTING | NEEDS_INPUT
                                                   └──► REPLANNING ─► PLAN_READY  (planning assumption broken)
Any state ─► PAUSED (owner ⏸) ─► previous state
Any state ─► CANCELLED (owner ⏹)
```

Transitions are recorded as `status.conditions`; the gateway edits the session card on every transition and @mentions the owner only on `NEEDS_INPUT`, `PLAN_READY`, `BLOCKED`, `DONE`, `CANCELLED` (§10).

**Session notes (working memory).** Every session keeps `notes.md` (current understanding, open questions, decisions, what was tried) in the `agent-plans` repo. Astra updates it each turn; it is re-injected on resume instead of raw history, which keeps Astra's context bounded across a multi-day session and is the owner's re-entry point after three days away.

### 5.4 Idempotency and restart

- Matrix transactions can be redelivered; the gateway records processed `txn_id`s in the CRD status (or a small ConfigMap) and is idempotent per event ID.
- All LLM calls are resumable from the CRD: phase + notes + last packet. A gateway pod restart mid-Astra-turn re-issues the turn; nothing is lost because the inputs are durable.
- Foreman tasks are referenced by ID; the gateway never holds task state in memory.

---

## 6. The broker (Foreman as an MCP server)

### 6.1 Interface

The broker is the *only* way models touch Foreman. It is deterministic (no LLM) and exposed as an MCP server so the same tool set is used by Astra during planning, by Luna during execution, and by whichever harness is playing coordinator in a direct session.

```
submit(objective, role="worker-scout"|"worker-deep"|"reviewer",
       repo, base_sha, mode="read-only"|"write",
       files_hint=[...], max_tokens, timeout) -> task_id
inspect(task_id)      -> {state, elapsed, seat, model, tail_of_log(truncated)}
results(task_id)      -> ResultPacket
cancel(task_id)
followup(task_id, question) -> task_id   # spawns a follow-up sharing the parent's prefix
list(session_id)      -> [task summaries]
```

Broker responsibilities: choose the model from role/rules (Glimmer vs Qwen), enforce per-model seat limits (Foreman `Agent` concurrency), queue, build the canonical prompt (§6.2), create the `AgenticTask`, capture artifacts to object storage/git, truncate logs, validate and return the result packet.

### 6.2 Prefix protocol (mandatory)

Because shared prefixes are worth ~10× on the Qwen server (§3.1) and prefix caching is on for both models, every worker prompt for a given repo is assembled in this **byte-identical** order:

```
[system prompt for role]           (stable per role; versioned)
[repo preamble]                    (repo map / AGENTS.md-equivalent; regenerated only when base_sha changes)
[plan excerpt, if executing]       (stable per plan revision)
[task]                             (varies)
```

Rules: no timestamps, task IDs, or per-task data above the `[task]` boundary; the broker computes and logs a prefix hash so cache hits can be verified; all tasks for one repo go to the same server (they do anyway — one model per card).

### 6.3 Result packet schema

Workers return **packets, not transcripts**. The worker system prompt requires this shape and the broker validates it (schema failure → one retry with the validation error appended, then `FAILED`).

```yaml
task_id: task-238
role: worker-deep
model: qwen3.8-27b
objective: "Determine whether replacing the auth middleware would break websocket auth."
conclusion: "Probably yes."
confidence: 0.7
evidence:
  - { path: server/auth/foo.go, lines: "41-80", note: "..." }
  - { path: websocket/bar.go, lines: "12-30", note: "..." }
  - { test: "integration/ws_auth_test.go::TestRefresh", note: "..." }
uncertainty:
  - "mobile client token-refresh path not inspected"
suggested_followups:
  - "Inspect mobile token-refresh path."
artifacts:
  - "s3://agents/task-238/report.md"
  - "s3://agents/task-238/transcript.jsonl"   # full log, for humans
tokens: { prompt: 18211, completion: 2140, cached_prefix: 16000 }
```

### 6.4 Worker pods

- One k8s Job per task (Foreman `AgenticTask` → Job). Ephemeral **clone at `base_sha`** into the pod; no shared checkout, ever.
- Tool whitelist by role (Foreman feature): `worker-scout` = read-only fs + grep/ctags-style tools; `worker-deep` = fs read/write + test runner + git commit to `session/<id>/<step>` branch; `reviewer` = read-only + diff.
- No cluster credentials, no kubectl, no secrets beyond a scoped git push token for the session branch namespace. Network egress limited to LiteLLM, the git host, and package registries.
- Worker runtime is a headless harness (same image family as §9) or a thin agent loop — either is acceptable for workers; the harness route avoids maintaining two agent loops.
- Output: commit(s) on the step branch + result packet. The broker records the commit SHA in the packet's `artifacts`.

---

## 7. Plans: format, storage, and review

### 7.1 Plan file format (machine + human)

Astra emits `plan.md` with a structured block Luna executes and prose the owner reads. Both live in one file so "did Luna do what was approved" is checkable.

```markdown
---
session: sess-…
revision: 4
base_sha: a1b2c3d
steps:
  - id: s1
    title: Introduce TokenVerifier abstraction
    depends_on: []
    mode: write
    files_likely: [server/auth/*.go]
    acceptance: "go test ./server/auth/... passes; reviewer(model!=author) approves"
  - id: s2
    title: Migrate HTTP authentication
    depends_on: [s1]
    mode: write
    acceptance: "go test ./server/... passes"
  - id: s3
    title: Migrate websocket authentication
    depends_on: [s1]
    mode: write
    acceptance: "integration/ws_auth_test.go passes"
  - id: s4
    title: Remove old middleware
    depends_on: [s2, s3]
    mode: write
    acceptance: "go vet; full test suite; reviewer approves"
guardrails:
  never_touch: [k8s/, talos/, secrets/]
---

## §1 Introduce TokenVerifier abstraction
…prose the owner reviews…

## §2 Migrate HTTP authentication
…
```

`acceptance` is mandatory per step; without it "Luna makes reality converge toward the plan" is undefined.

### 7.2 Storage: git (`agent-plans` repo)

- Layout: `agent-plans/projects/<repo>/<session>/plan.md`, `notes.md`, `packets/`.
- Every revision is a **commit**; the session card links the commit SHA and the raw file. On approval the SHA is frozen into `status.approvedCommitSha`.
- Audit trail: "this exact plan was approved; this exact plan was executed" — without needing a PR.

### 7.3 Review surface: Matrix, not GitHub `[DECISION]`

Why not GitHub PRs for plans: reviewing a rewritten prose document as a line diff shows churn rather than meaning; line-anchored comments break when Astra restructures v3→v4; it is a second app with a second notification stream in the one phase where attention is scarcest. GitHub's real value (approval state, immutable SHA, webhooks) is retained by §7.2 without the PR UI. GitHub PRs remain the right tool for **code** (§8.5).

How plan review works in a Commet thread:

1. Gateway posts a one-line summary, then **one message per section** (`§1 … §n`, as `@lab-astra`), then attaches the full `plan.md` as a file for a single-scroll read.
2. **Anchored comment** = reply to the section message. Any reply to `§3` is an anchored comment on §3.
3. **Approve** = ✅ reaction on the session card (or the bare word `approve` in the thread).
4. **Request changes** = ✏️ reaction on the card; the owner's following messages until the next card edit are collected as the change request. Or just reply to sections and react ✏️ when done.
5. Revision: Astra posts a **semantic changelog** ("§3 rewritten per your comment; §5 dropped; new §6 added") and re-posts only changed sections, plus the new full file. No line diffs.
6. Fallback if a plan is too long for thread review: Outline (self-hosted docs with text-anchored comments and an agent API/MCP) — deferred until the Matrix flow is shown insufficient.

---

## 8. Execution

### 8.1 Coordinator

After `APPROVED`, the gateway hands `(approved plan commit, session)` to the coordinator. The coordinator is a harness pod (§9) with the broker MCP server as its tools, running under the `coordinator` alias (cloud Luna) or `coordinator-local` (Glimmer). Luna converts the plan's `steps` block into an execution DAG (it is already a DAG — `depends_on`), submits worker tasks, watches, retries bounded failures, resolves ordinary complications, and integrates.

### 8.2 Git model (workspace state)

- Session pins `base_sha`. Every worker task clones at the SHA it is told (initially `base_sha`, later the integration branch head).
- Each step's worker commits to `session/<id>/<step>`; Luna rebases step branches onto **one integration branch** `session/<id>/integration` in DAG order. Conflicts are Luna's job (ordinary complication).
- Step acceptance runs on the integration branch after rebase, as its own worker task (`reviewer` role, *other* model).
- Final artifact: a **code PR** from the integration branch to the repo's main branch (§8.5).

### 8.3 Concurrency

- Foreman per-Agent seats: Qwen start at 3 (long-context), Glimmer at 2. The broker never exceeds; extra tasks queue.
- vLLM `--max-num-queued-reqs` set slightly above Foreman's seat count so a leaked request fails fast rather than piling up.
- Luna may keep an arbitrarily long *logical* queue; only the broker admits.

### 8.4 Escalation boundary

Luna may make **implementation** decisions; it may not silently make **planning** decisions.

| Discovery during execution | Action |
|---|---|
| Test needs a different fixture | Luna |
| Worker needs another repo search | Luna |
| Merge conflict | Luna |
| Planned API doesn't exist exactly as expected | Luna (note it in packet) |
| Step fails acceptance N=3 times | `BLOCKED` → owner (@mention) |
| Session budget cap hit | `NEEDS_INPUT` → owner |
| Change would touch `guardrails.never_touch` (k8s manifests, Talos config, secrets, RBAC) | `NEEDS_INPUT` → **owner**, never Astra |
| Proposed architecture fundamentally won't work | `REPLANNING` → Astra → plan v(N+1) → owner approves |
| Requirement conflicts with approved plan | `REPLANNING` → Astra/owner |
| Need to drop a major plan step | `REPLANNING` → Astra → revision |

### 8.5 Code review in GitHub

The integration branch becomes a real PR. This is where diff review is the correct artifact and GitHub Mobile is fine. Hookshot posts PR/review events into `#alerts`; the session card links the PR. Merging the code PR = `DONE`. Optional: Luna auto-merges only after the owner's GitHub approval.

### 8.6 Observability

- Full transcripts and logs go to object storage (Ceph RGW/S3) under `agents/<task>/`; packets link them. Humans can drill down; models never see them by default.
- Session card shows spend (planner USD, coordinator USD, worker task count) from LiteLLM's per-key accounting.
- vLLM `--per-request-spec-decode-metrics` and the broker's prefix-hash logging feed a small dashboard: cache hit rate, acceptance rate, per-role success rate. Those numbers decide the Glimmer-vs-Qwen role assignment over time.

---

## 9. Direct coordinator sessions ("Codex over Commet")

Goal: from a Matrix DM or project room, get what Codex CLI gives on a workstation — system prompt, tools, sandbox, retries, context compaction, `AGENTS.md` conventions — without SSH.

**Approach `[DECISION]`:** do not reimplement the harness. Run a real headless harness in a Foreman-managed pod and bridge it to a thread.

- **Harness candidates:** Codex CLI, pi (owner has tried; likes its minimalism), opencode (a peer's cluster runs it in k8s; it has a server mode). All three accept custom OpenAI-compatible providers via config.
- **Codex specifics:** custom providers in `~/.codex/config.toml` (`[model_providers.x]` with `base_url`, `env_key`); Codex speaks the **Responses API only**, so LiteLLM must translate for backends that don't; profiles allow one profile per model; the app-server protocol supports thread-level provider selection (`ThreadStartParams.modelProvider`).

```toml
model = "coordinator"
model_provider = "litellm"
[model_providers.litellm]
name = "LiteLLM"
base_url = "http://litellm.nuc-2.svc:4000"
env_key = "LITELLM_API_KEY"
wire_api = "responses"
```

- **Pod shape:** harness image + scoped git worktree + **PVC-backed session directory** (so the pod can be evicted and `resume`d), no secrets beyond a scoped git token, approval mode set to non-interactive ("never ask") because the sandbox is the pod and the gate is git (nothing merges without a PR the owner approves).
- **Bridge:** the gateway starts the pod on thread creation, forwards owner messages as turns, streams the harness's output into an **edited-in-place progress message** and posts a final reply per turn, and maps any harness approval prompt to a reaction on the message.
- **Images from the phone:** an `m.image` in the thread is downloaded by the gateway and passed as an image input when the model is Glimmer (vision on). For text-only models the gateway runs it through Glimmer first for a description. Screenshots of errors and photos of whiteboards are first-class inputs.
- **Unification:** workers, the execution coordinator, and direct sessions are the same harness pod with different tool sets (broker MCP vs. local fs tools) and different LiteLLM aliases. One image family, one config schema.

---

## 10. Matrix conventions (the interface)

### 10.1 Space and rooms

| Room | Purpose | Notification rule |
|---|---|---|
| `#proj-<repo>` (one per project) | The room *is* the default context: repo, base branch, allowed agents, budget caps. Each **top-level owner message starts a session**; the **thread is the session**. Commet's room list becomes the project list. | Mentions only. |
| `#fleet` | Luna/Foreman operational chatter, GPU evictions, wolf-session notices, queue depth. | Muted. |
| `#alerts` | Hookshot (code PRs), alertmanager. | Mentions only. |
| DM with `@lab-luna` | Direct coordinator sessions not tied to a project; ad-hoc questions. | Normal DM rules. |

Virtual users: `@lab-astra` (planner), `@lab-luna` (coordinator / direct sessions), `@lab-fleet` (broker/status). Distinct avatars.

### 10.2 Thread anatomy

1. **Root** — the owner's request (plain language).
2. **Session card** — first reply from `@lab-fleet`, edited in place (`m.replace`) on every transition, pinned while active: phase, plan revision, open question, spend, links (plan SHA, integration branch, PR, notes).
3. **Progress message** — second reply, edited in place: worker table (task, role, model, state, elapsed). Never 40 separate status messages.
4. **Substantive turns** — `@lab-astra` findings/questions; `@lab-luna` execution notes.
5. **Questions** (`NEEDS_INPUT`) — @mention the owner; discrete options as a Matrix poll if Commet renders `m.poll` `[VERIFY]`, otherwise numbered options answered by number.
6. **Plan** — section messages `§1…§n` + attached full file (§7.3).

### 10.3 Interaction verbs (no command prefixes)

Replaces `!cogito review sha256:…`.

- **Routing by state.** Typing in a thread means the obvious thing: in `NEEDS_INPUT` it is the answer; in `DISCOVERING`/`REVISING` it goes to Astra; in `EXECUTING` it is an instruction/question for Luna. Explicit override with `@lab-astra` / `@lab-luna` mentions.
- **Reactions as controls** on the session card: ✅ approve · ✏️ request changes · ⏹ cancel · ⏸ pause · 🔄 retry current step · 🔍 post verbose details. One tap, no keyboard.
- **Reply-to as reference.** Every artifact (image, report, plan section, review result) is its own message carrying its identity (digest/path/task ID) in a custom content field. "Review this" as a *reply* to that message resolves the reference server-side. The owner never types a hash.
- **Three bare words** the gateway understands anywhere in a thread for keyboard users: `status`, `stop`, `approve`.
- Operational questions (`status`, `stop that Qwen task`, `retry`) are answered by the gateway/Luna **without waking Astra**.

### 10.4 Example thread

```
you        Replace the auth middleware with TokenVerifier; websocket auth must keep working.
@lab-fleet ▣ Session sess-3f1a · DISCOVERING · rev 0 · $0.00 · notes ↗           (card, pinned, edited)
@lab-fleet ▤ tasks: (none yet)                                                    (progress, edited)
@lab-astra I need to understand server auth, websocket auth, client token handling, and test coverage. Sent 4 tasks.
@lab-fleet ▤ tasks: scout/repo-map ✔ · deep/ws-auth ▶ · scout/client-tokens ▶ · scout/tests ✔
@lab-astra One ambiguity. @you Do you want backwards compatibility with the old endpoint?   → NEEDS_INPUT (push)
you        No.
@lab-astra Plan ready (rev 1). 4 steps. Summary: …                                → PLAN_READY (push)
@lab-astra §1 Introduce TokenVerifier abstraction …
@lab-astra §2 Migrate HTTP authentication …
@lab-astra §3 Migrate websocket authentication …
@lab-astra §4 Remove old middleware …
@lab-astra 📎 plan.md (rev 1, a9f0c2e)
you        ↳ reply to §3: also cover the mobile token-refresh path
you        ✏️ on card
@lab-astra rev 2: §3 extended with mobile refresh path; §1,2,4 unchanged. 📎 plan.md (b71d…)
you        ✅ on card                                                             → APPROVED, SHA frozen
@lab-luna  Executing rev 2 @ b71d…: s1 ▶
@lab-fleet ▤ tasks: deep/s1 ▶ (qwen) · reviewer/s1 queued (glimmer)
… (owner ignores for two days; no pushes) …
@lab-luna  ⚠ s3 failed acceptance 3× (ws integration test). Details ↗ @you        → BLOCKED (push)
you        🔍 on card
@lab-fleet (verbose: last packet, test output tail, links)
you        retry with the fixture from s2
@lab-luna  s3 ✔ · s4 ▶ … PR #412 opened ↗                                          → DONE on merge (push)
```

---

## 11. Notifications

- Commet supports UnifiedPush; ntfy can serve as the UnifiedPush distributor on Android and implements the Matrix push-gateway endpoint, so **self-hosted ntfy is both the distributor and the gateway**. Synapse's pusher points at ntfy; Commet registers with the local ntfy distributor. No Google services, one channel.
- Project rooms and `#alerts` are **mentions-only**; `#fleet` is muted. The gateway @mentions the owner **only** on `NEEDS_INPUT`, `PLAN_READY`, `BLOCKED`, `DONE`, `CANCELLED`. Everything else is a silent edit to the card/progress message.
- One raw ntfy topic remains for out-of-band alerts: "planner-gateway is down", "Synapse is down". These are the only things that should not depend on Matrix itself.
- Tapping a notification opens the thread, whose top (pinned card) states where things are. That is the re-entry experience.

---

## 12. Security and budgets

- Astra: no tools that touch the world; only the four conceptual tools via the gateway. Luna: only the broker MCP (no kubectl, no cluster credentials).
- Worker/harness pods: scoped git tokens (branch-namespace-limited), no cluster secrets, egress allow-list (LiteLLM, git host, package registries), read-only root filesystem where the harness permits.
- `guardrails.never_touch` in every plan; the broker refuses `write` tasks whose `files_hint` intersect it; anything touching k8s manifests, Talos config, secrets, or RBAC routes to the owner.
- Budgets: LiteLLM per-key caps by role plus per-session caps in the CRD; cap hit → `NEEDS_INPUT`.
- Prompt-injection posture: worker packets are data, not instructions; the gateway never executes text from packets; Astra's system prompt marks packet content as untrusted.

---

## 13. Build order and acceptance criteria

Ordered so that the "talk to a coding agent from the couch" experience arrives early, because with a newborn that is worth more than a fully automated DAG.

| # | Milestone | Done when |
|---|---|---|
| 0 | **LiteLLM round-trip tests** | A Responses-API client (Codex) and a chat-completions client (pi/opencode) each complete a tool-calling turn against *both* Qwen (`qwen3_coder`) and Glimmer (`muse_glimmer`) through LiteLLM, with reasoning content preserved for Glimmer. |
| 1 | **Glimmer serving** | RedHatAI W4A16 + int8 embed/head requant loads on 3090 #2 under vLLM 0.29.0 with vision on, ≥2 slots at 64k, tool calls parsed; or llama.cpp fallback validated. Prefix-cache hit rate measured. |
| 2 | **Broker MCP + read-only workers** | `submit/inspect/results/cancel/followup` over MCP; Qwen and Glimmer scout Jobs return schema-valid packets; prefix hash logged; seats enforced. |
| 3 | **Appservice gateway + CRD + notifications** | Multi-persona posting; session card and progress message edited in place; reactions routed; ntfy/UnifiedPush push arrives on the phone only on state transitions; restart of the gateway loses nothing. |
| 4 | **Direct coordinator sessions** | DM thread → harness pod (Codex or pi) on a PVC; turns round-trip; pod eviction + resume works; image input works via Glimmer. *This is the Codex replacement.* |
| 5 | **Astra planning loop** | Full DISCOVERING → NEEDS_INPUT → PLAN_READY → REVISING → APPROVED flow in Matrix; plan revisions committed to `agent-plans`; approved SHA frozen. |
| 6 | **Execution** | Luna runs the steps DAG over write-mode workers; integration branch; acceptance via reviewer (other model); escalation table exercised (force a `BLOCKED` and a `REPLANNING`); code PR opened. |
| 7 | **Hookshot + polish** | PR events in `#alerts`; dashboard for cache hits / acceptance / per-role success; retire `!cogito`. |

---

## 14. Open items to verify (for the reviewer and the owner)

1. `[VERIFY]` LiteLLM Responses↔chat translation preserves `qwen3_coder` and `muse_glimmer` tool calls and `reasoning_content` (milestone 0). Highest-risk integration point.
2. `[VERIFY]` Commet renders `m.poll`; if not, numbered options.
3. `[VERIFY]` llama.cpp `--jinja` parses Glimmer ATEM tool calls into OpenAI `tool_calls` (only matters on the fallback path).
4. `[VERIFY]` llmkube can express a second vLLM version (0.29.0) alongside the syv-ai 0.28.0 image, and (fallback) a llama.cpp server.
5. `[VERIFY]` Marlin NVFP4 W4A16 kernel on Ampere (would allow the QUASAR NVFP4-W4A16 Glimmer checkpoint) — otherwise int4 W4A16 as designed.
6. `[VERIFY]` Actual VRAM after the int8 embed/head requant on Glimmer; the ~19 GB figure is an estimate.
7. `[VERIFY]` Prefix-cache hit rates on both servers under vLLM 0.29's new `prefix_cache_retention_interval` default.
8. `[VERIFY]` Which headless harness (Codex vs pi vs opencode) has the cleanest programmatic session API for the bridge; Codex's app-server protocol vs opencode's HTTP server vs pi's extension model.
9. `[VERIFY]` Foreman's current `AgenticTask` API surface matches the broker's needs (follow-up tasks sharing a parent prefix; artifact capture).
10. `[VERIFY]` Whether the homeserver is Synapse (affects appservice/push configuration details only).

---

## 15. Glossary

- **Astra / Luna Max Thinking / GLM 5.3 / K3** — the owner's LiteLLM aliases for cloud models: planner, coordinator, and two escalation targets respectively.
- **Foreman** — owner-written Kubernetes operator that schedules agent tasks (`Agent`, `AgenticTask`, `Workload` CRDs).
- **Broker** — deterministic MCP server in front of Foreman (`submit/inspect/results/cancel/followup`).
- **planner-gateway** — the new Matrix appservice + controller.
- **PlanningSession** — CRD holding one session's durable state; keyed by Matrix thread root.
- **Session card / progress message** — two Matrix messages per thread, edited in place.
- **Packet** — structured worker result (conclusion, evidence, uncertainty, follow-ups, artifacts).
- **Harness** — a headless coding-agent runtime (Codex CLI, pi, opencode) running in a pod.
- **Commet** — the Matrix client on the owner's phone. **Hookshot** — GitHub↔Matrix bridge. **ntfy** — push service used as UnifiedPush distributor and Matrix push gateway.
- **syv-ai stack** — the `qwen38-27b-rtx3090` serving repo (vLLM 0.28.0 + patches) for Qwen on one 3090.
- **Wolf session** — the owner's term for a game-streaming session that evicts workloads from the 5070 Ti node.
- **DL-NVFP4** — the owner's separate research project to run NVFP4 quants on Ampere via INT8 tensor cores; out of scope here but explains why Blackwell-only NVFP4 checkpoints are mentioned.

---

## 16. Sources consulted (2026-09-12)

- syv-ai/qwen38-27b-rtx3090 README — https://github.com/syv-ai/qwen38-27b-rtx3090
- vLLM Muse Glimmer recipe (updated 2026-09-09) — https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B
- vLLM v0.28.0 and v0.29.0 release notes — https://github.com/vllm-project/vllm/releases
- vLLM PR #51655 (Muse Glimmer support) — https://github.com/vllm-project/vllm/pull/51655
- Muse Glimmer W4A16 checkpoints — https://huggingface.co/RedHatAI/Muse-Glimmer-30B-W4A16 (and aisquared, Vishva007, kaitchup, QUASAR-QAT variants)
- Hardware Corner: Muse Glimmer 30B on RTX 3090/4090/5090 (llama.cpp) — https://www.hardware-corner.net/hardware-for-muse-glimmer-30b-llm/
- Meta Muse Glimmer announcement and HF model card — https://research.meta.ai/blog/introducing-muse-glimmer-open-agentic-model, https://huggingface.co/meta-models/Muse-Glimmer-30B
- Commet client — https://github.com/commetchat/commet ; UnifiedPush app list — https://unifiedpush.org/users/apps/
- Codex custom providers / Responses-API requirement (community docs, 2026-04/06) — https://codex.danielvaughan.com/2026/04/23/codex-cli-custom-model-providers-configuration-guide/
