# Gemma 4 as a local agent: field report for Cogito

Research date: 2026-07-16
Scope: configuration and operating guidance only. This document makes no
changes to the cluster.

## Executive take

You are not simply “holding it wrong.” Gemma 4 can chat well, reason, and emit
native tool calls, but local agents turn those strengths into a fragile chain:

```text
client -> OpenAI request -> chat template -> model -> parser -> tool runner
       -> tool result -> reconstructed history -> model again
```

Every link must agree on Gemma's special-token protocol. Even when that chain
is correct, a useful agent must choose the right tool, use the result rather
than inventing an answer, recover from failure, and stop. Community experience
is that Gemma 4 is capable but inconsistent at long, interleaved tool loops;
Qwen 3.6 is commonly preferred for coding and tool-heavy work. That is a
workload observation, not a claim that Gemma is bad at ordinary chat.

Your live server is already on a strong baseline:

* official `google/gemma-4-31B-it-qat-w4a16-ct` weights;
* vLLM `v0.25.0`, which includes the earlier Gemma 4 streaming/parser fixes;
* Google’s canonical chat template; and
* the native `gemma4` reasoning and tool-call parsers.

The earlier community AWQ profile and old vLLM example template remain useful
historical comparisons, but they are **not** the active configuration. The
more likely explanation for present frustration is a combination of Gemma's
agentic limits, disabled-by-default thinking in the active template profile,
and Open WebUI’s intentionally model-driven web-research loop.

## Current setup, as observed

| Layer | Current state | Consequence |
| --- | --- | --- |
| Serving | vLLM `v0.25.0`, TP=2, 185k context cap, two sequences, GPU utilization 0.95 | Optimized for fitting a huge context and some concurrency, not for a single reliable agent loop. |
| Model | Official 31B QAT W4A16 Compressed-Tensors checkpoint | This removes a major unknown from third-party AWQ quant/template combinations. |
| Template | Mounted Google canonical Gemma 4 template | Correct direction; the active profile does not pass `enable_thinking=true` as default template kwargs. |
| Tooling | `--enable-auto-tool-choice`, `--tool-call-parser gemma4`, `--reasoning-parser gemma4` | Required for native OpenAI-compatible function calls. |
| Open WebUI | `v0.10.2`, SearXNG configured as its web-search engine | Search works, but the manifest does not configure Firecrawl as Open WebUI’s search or page-loader backend. |
| Firecrawl | A self-hosted deployment is defined in Git, but its Flux Kustomization is currently failing validation and no Firecrawl service/pod is live | It cannot currently improve Open WebUI or Hermes live extraction. |
| Hermes | The vLLM proxy can generate a `custom:llm-proxy` provider configuration | Hermes can consume the local server cleanly; whether it succeeds still depends on Gemma’s multi-turn tool behavior. |

Two details are easy to miss:

1. The pod requests four GPUs but uses tensor parallelism two. That may be a
   capacity/cost issue, but it does not explain poor decisions or tool loops.
2. A 185k maximum context does not make answers smarter. It allows an agent to
   retain much more noisy history, tool output, and instructions. Long contexts
   can make local agents slower and harder to steer.

## Why normal chat quality does not predict agent quality

An agent has at least four independent competencies:

1. **Tool selection:** know when a tool is needed and choose the right one.
2. **Schema compliance:** produce valid names and arguments every time.
3. **State tracking:** treat tool results as new evidence, not as prose to
   ignore; remember what has already happened.
4. **Task control:** make a plan, validate work, recover from errors, and stop.

Gemma may perform well on the final answer after it has the needed material,
yet fail at one of the first three. This produces the very convincing but
unhelpful behavior of saying “I’ll search that,” calling SearXNG once, then
answering from a misleading snippet—or saying it completed a repo action that
no tool result proves it completed.

This is also why an enormous system prompt is usually counterproductive. It
adds another long instruction block to preserve across every turn without
fixing the tool protocol or giving the model a verifier.

## Gemma 4’s protocol and vLLM

### Non-negotiable setup

Google documents six special tokens for tool definition, calls, and results.
The client should send OpenAI-style `tools`; the template renders Gemma’s
native syntax; the server parses the native response into OpenAI-style
`tool_calls`; the harness executes it; and the next request sends role `tool`
results back. Do not replace that with tool syntax described in a system prompt.

Required vLLM settings are exactly the ones your active profile already has:

```text
--enable-auto-tool-choice
--tool-call-parser gemma4
--reasoning-parser gemma4
--chat-template <matching Gemma 4 template>
```

See [Google’s prompt-format specification](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4)
and the [vLLM Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html).

### Thinking

Gemma thinking is switched on by `<|think|>` in the first system turn. The
canonical template exposes this as `enable_thinking`; it defaults to false if
the caller does not provide it. That explains why your server can advertise a
reasoning parser but not necessarily start every conversation in thinking mode.

For an agent, test a profile with default chat-template kwargs equivalent to:

```json
{"enable_thinking": true}
```

Do not conclude that more hidden reasoning is automatically better. Google says
to strip thoughts from ordinary subsequent turns, while preserving them within
the same tool-use turn. The canonical template handles this history format;
clients that save, replay, or stream messages incorrectly can still corrupt it.
Use a short “think efficiently; use tools only when evidence is needed” system
instruction rather than asking for maximal private reasoning.

### Can Open WebUI enable it?

**Not as a reliable Gemma-specific UI switch.** `enable_thinking` is a vLLM
chat-template argument, not an OpenAI-standard sampling parameter. The vLLM
OpenAI-compatible API accepts it at request level as:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": true
  }
}
```

An OpenAI Python client passes that body using:

```python
extra_body={"chat_template_kwargs": {"enable_thinking": True}}
```

Request-level kwargs override the server default. vLLM documents both that
form and the server-wide `--default-chat-template-kwargs` flag in its
[reasoning outputs guide](https://docs.vllm.ai/en/v0.20.1/features/reasoning_outputs/).

Open WebUI's familiar Advanced Parameters UI is primarily for standard fields
such as temperature, top-p, max tokens, and tool-calling mode. Its public docs
do not promise a per-model/per-chat passthrough for arbitrary
`chat_template_kwargs`, and its historical Qwen feature request demonstrates
why assuming that a generic “reasoning” control maps to a template kwarg is
unsafe. Check the actual request in Open WebUI's server logs or browser network
tools before relying on any UI field for this.

For this cluster, the robust choices are therefore:

1. **Keep the present default (thinking off)** for ordinary chat; or
2. **Create a separate vLLM model profile** with
   `--default-chat-template-kwargs '{"enable_thinking":true}'`, then select
   that model in Open WebUI for agent/research chats.

The second approach is preferable to turning thinking on globally: it does not
make lightweight chats pay an avoidable latency/token cost, and it avoids
depending on undocumented Open WebUI request passthrough. Verify that Open
WebUI still receives `reasoning` separately from normal assistant content and
that a tool call after a thought is parsed correctly.

### Can Hermes enable it?

**Yes, most safely at the vLLM server/profile level; possibly per request if
your installed Hermes version forwards arbitrary request extras.** Hermes has
two different concepts that should not be conflated:

* `agent.reasoning_effort` and `/reasoning` are Hermes' provider-neutral
  controls. They set a generic reasoning preference; they do **not** prove that
  a local Gemma template received `enable_thinking=true`.
* `chat_template_kwargs.enable_thinking` is the Gemma/vLLM-specific control
  that actually inserts the Gemma thinking token in this template.

Hermes' current documentation confirms that it supports provider/request
`extra_body` forwarding in several configuration paths, but it does not
publish a stable top-level main-model `extra_body` example for this exact
Gemma/vLLM setting. Recent Hermes development explicitly mentions adding
`chat_template_kwargs` forwarding for open-source backends, so version matters.

Practical order of operations:

1. Use a dedicated vLLM profile with server-default `enable_thinking=true`.
   Hermes needs no special request support and cannot accidentally omit the
   flag on retries, tool continuations, compression, or a different client.
2. In Hermes, keep `agent.tool_use_enforcement: auto` (Gemma is in the default
   matched set) and set `/reasoning show` only if you want to display the
   returned reasoning. Showing it is a display choice; it does not enable it.
3. If you later want a per-session switch, inspect the exact installed Hermes
   version and capture an outbound request. Only use a main-model `extra_body`
   configuration after confirming it emits the exact vLLM field above on every
   request in a tool loop.

Do not set `agent.reasoning_effort: high` as a substitute and assume it worked:
with a local custom endpoint it may be ignored, translated to a different
provider field, or add no Gemma `<|think|>` token at all. Hermes documents the
generic reasoning controls and Gemma-specific tool-use enforcement separately:
[Hermes reasoning and tool-use configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/).

### When to leave thinking off

Thinking is not a truthfulness switch. Leave it off for simple factual chat,
single deterministic tool dispatch, high-volume monitoring, and any client
that has not passed the `thought -> tool call -> tool result -> follow-up`
regression test. Turn it on first for bounded repo work or multi-source
research, then compare completion rate, malformed calls, tool turns, latency,
and grounded-answer accuracy against the non-thinking control.

### Sampling

Your active `temperature=1.0`, `top_p=0.95`, `top_k=64`, and no repetition
penalty match the common Gemma 4 baseline. Community reports are mixed about
lower temperatures: `0.2–0.4` can make a fixed extraction task more repeatable,
but can also make Gemma refuse to take a needed exploratory action. Treat
sampling as per-workload:

| Workload | Starting point | Why |
| --- | --- | --- |
| Direct tool/schema regression test | `temperature=0.2–0.4` | Isolates formatting and state failures from creative variation. |
| Coding agent | `0.4–0.7` | Favors repeatable edits and validation, while retaining planning latitude. |
| General chat / open-ended research | current `1.0 / 0.95 / 64` | Matches the Gemma default behavior community members most often use. |

Use a request-level override for experiments. Do not mutate the server-wide
generation config until one profile wins a measured test set.

### Context, batching, and concurrency

For a single interactive agent, start testing at 32k–64k context and one active
sequence. That is not because Gemma cannot use more context; it is because it
reduces stale history, makes failures reproducible, and avoids a known class of
concurrent Gemma/vLLM tool-call issues. A report of `<pad>`-token output under
concurrent tool calls succeeded sequentially with the same prompt:
[vLLM #39392](https://github.com/vllm-project/vllm/issues/39392).

vLLM 0.25.0 contains many earlier Gemma fixes, so upgrading blindly is not the
first remedy. Still regression-test every vLLM or template upgrade. Historical
bugs included raw tool calls leaking into content, incomplete streaming parsing,
argument corruption, repetition, and tool calls ending at a turn boundary.
Relevant upstream threads include [#39043](https://github.com/vllm-project/vllm/issues/39043),
[#40080](https://github.com/vllm-project/vllm/issues/40080), and the
[vLLM release notes](https://github.com/vllm-project/vllm/releases).

One community-proposed workaround removes `<turn|>` from the EOS set during
tool calls. It can help premature stops in a particular older stack, but it is
not a safe default. A/B test it only if the current vLLM profile demonstrably
terminates before a valid call; changing EOS tokens can create new run-on
generation failures.

## What the local community reports

This section intentionally separates repeatable upstream evidence from
anecdotes. Reddit, model discussions, and Discord-like reports are excellent
for discovering failure modes; they are not controlled benchmarks.

### Strong recurring themes

| Theme | Evidence and practical meaning |
| --- | --- |
| Correct template is decisive | Users who pass native schemas but use an old/partial template see no calls, raw control tokens, or wrong turn closures. This is consistent with Google’s protocol and vLLM bugs. |
| One successful tool call proves little | Multi-round `think -> call -> result -> think -> call` is the failure boundary repeatedly reported for Gemma 4 across Open WebUI, Hermes, PI, and coding clients. |
| Native tools beat prompt-injected tools | Open WebUI has deprecated Legacy function calling. Legacy changes the prompt every turn, breaks prefix caching, and parses a brittle natural-language format. [Open WebUI tools documentation](https://docs.openwebui.com/features/extensibility/plugin/tools/) |
| Smaller tool menus help | Users with local models report better selection when tools are narrow, uniquely named, and described in concrete action/outcome language. A model given dozens of overlapping MCP tools is asked to solve a tool-routing problem before it solves the user’s task. |
| Qwen is a useful control | Hermes users and local coding users frequently characterize Qwen 3.6 as more reliable for agentic/coding work. This does not mean it will be better on your hardware or task; it gives a control when diagnosing Gemma versus harness failure. [Hermes community AMA summary](https://www.reddit.com/r/hermesagent/comments/1szctp1/ama_summary_from_rlocalllama_42926/) |
| Some users have success | Current vLLM/llama.cpp/Ollama users do report successful Gemma 4 tool loops after updating templates and parsers, especially for bounded tasks. Success is not universal and should be verified in your exact client. |

### Tools people combine successfully

| Need | Common local combination | Caveat |
| --- | --- | --- |
| Coding | Hermes, PI, OpenCode, or a coding IDE client + filesystem/shell tools | Keep only repo-relevant tools available; require tests/commands as evidence. |
| Discovery | SearXNG | It gives SERP data, not ground truth. Upstream engines can be stale, rate-limited, or return bad snippets. |
| Extraction | Firecrawl, Crawl4AI, or Playwright | These make pages readable; they do not make the model verify claims. |
| Browser-only pages | Playwright or browser-use style control | Needs strict domain/action allowlists; pages change and anti-bot defenses are common. |
| Persistent reference material | BGE-M3/RAG plus an MCP query tool | Requires document revision, page/section provenance, and negative-answer tests. |
| Repeating checks | CronJob/systemd timer + fetch/parse/diff + notification | Prefer this to an LLM deciding every day how to inspect a site. |

## Hermes: use it as a coding harness, not magic

Hermes provides tools, approvals, MCP support, web backends, and an
OpenAI-compatible custom provider. Its provider configuration can point to the
proxy-generated `custom:llm-proxy` model catalog. [Hermes configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/)

Recommended operating practice:

1. Start each repo task with a fresh, scoped session. Do not carry a giant
   research/tool history into a code change.
2. Offer a small coding toolset: list/search files, read, edit, shell/test,
   and optionally one issue/search tool. Disable overlapping aliases.
3. Keep the system prompt operational, not theatrical. For example:

   ```text
   You are working in the provided repository. Inspect before editing.
   Use tools for every claim about files, commands, or test results.
   Make the smallest coherent change. Run the relevant validation.
   If a command or tool fails, report the failure and revise the plan; never
   claim success without a corresponding tool result.
   ```

4. Cap turns or require a checkpoint after a bounded number of tool actions.
   This converts a Gemma loop into a visible failure instead of unlimited cost.
5. Evaluate non-streaming and streaming separately. A client that displays
   streaming text can mishandle a parser edge case even when an ordinary API
   completion works.
6. Give Gemma no ability to mutate external systems outside the repo workflow.
   It should propose or stage consequential work, not deploy, buy, post, or
   change infrastructure autonomously.

For web tools in Hermes, the repository already documents the useful split:
SearXNG for search and Firecrawl for extraction. That is a better primitive
than asking the model to infer reliable facts from a search-result snippet.

## Open WebUI: why it feels especially bad for live research

### Native agentic search is deliberately model-driven

Open WebUI’s Native mode exposes two distinct tools:

* `search_web(query, count)` returns titles, URLs, and snippets.
* `fetch_url(url)` fetches/extracts page text, capped at 50,000 characters.

The model must decide when snippets are insufficient and call `fetch_url`.
Open WebUI explicitly describes agentic search as a frontier-model-oriented
workflow and warns that small/local models may struggle with the multistep
reasoning. [Agentic Search & URL Fetching](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

So your observation is expected: “SearXNG returned something” is not the same
as “the model inspected the source.” Snippets may be stale, mismatched to the
query, truncated, generated by an upstream search engine, or reflect cached
page metadata.

### Settings to verify in the UI

For the Gemma model specifically:

1. **Function Calling:** Native, not Legacy.
2. **Capability:** Web Search enabled.
3. **Default feature:** Web Search enabled, or explicitly toggled on per chat.
4. **Context budget:** at least 16k for page content; 32k–64k is more practical
   for multi-source research.
5. **Tool count:** do not inject every available builtin/MCP tool into a basic
   research chat.

Open WebUI documents that both the capability and feature/toggle are necessary
for `search_web`/`fetch_url` to be injected. [Web-search setup](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

### Better evidence policy prompt

Use this as a **research-profile** system prompt or saved workspace prompt, not
as the universal prompt for all chats:

```text
For current facts, products, prices, availability, laws, schedules, and news,
search results are leads only—not evidence. After search, fetch at least two
relevant primary or authoritative URLs before answering, unless the user asks
for a quick unverified answer. Prefer official pages, filings, documentation,
or the seller/provider itself. State the retrieval date. Cite each factual
claim with its fetched URL. If pages disagree or cannot be fetched, explain
the uncertainty instead of guessing.
```

This improves the odds but does not enforce retrieval. A strong solution moves
the policy into the harness: automatically fetch/rank a limited set of results
and give the model extracted material. An Open WebUI issue requests exactly
that alternative because local models can stop at snippets even when prompted
to fetch: [#26229](https://github.com/open-webui/open-webui/issues/26229).

### Firecrawl and the present blocker

Open WebUI supports Firecrawl as a web-search/provider and as a loader; it can
point at a self-hosted API. [Open WebUI Firecrawl guide](https://docs.openwebui.com/features/chat-conversations/web-search/providers/firecrawl/)

However, do not point Open WebUI at the in-cluster Firecrawl name yet. The
current Firecrawl Flux Kustomization is failing because a one-instance CNPG
cluster inherits a synchronous-standby requirement that is invalid with no
standbys. There is no Firecrawl service or pod live. Until that is repaired and
tested, the working live path is SearXNG only.

When Firecrawl is live, test both designs rather than assuming one wins:

* **SearXNG discovery + Firecrawl page loader:** retains private discovery and
  gives `fetch_url` a better extractor; Gemma still must choose to fetch.
* **Firecrawl search provider:** asks Firecrawl to search and return
  model-ready content; it reduces snippet-only answers but costs more latency
  and extraction work.

Use a browser-like User-Agent and low loader concurrency for difficult sites.
Open WebUI’s troubleshooting guide covers empty content, content-loader choice,
and proxy behavior: [Web Search troubleshooting](https://docs.openwebui.com/troubleshooting/web-search/).

## Automation: do not make a chat agent your scheduler

For “check Xfinity every day” or “watch eBay listings,” build a deterministic
workflow first:

```text
timer -> fetch permitted page/API -> normalize selected fields -> save snapshot
      -> compare with last snapshot -> notify human on meaningful change
```

The LLM may summarize a diff or categorize a listing after the deterministic
collector has produced structured data. It should not decide which account to
use, log in, submit a form, buy an item, or accept terms. This is both safer
and more reliable than assigning a generic browsing agent a daily natural-
language task.

For pages that require rendering, use Playwright/Firecrawl with a fixed domain,
fixed selectors/extraction schema, explicit rate limit, and no credentials.
Record the URL, timestamp, HTTP/render result, parsed fields, and raw snapshot
so a notification can be audited. Make “observe and notify” the hard action
boundary until a separate approval workflow exists.

## A pragmatic evaluation plan

Do not decide from one good or bad chat. Create a tiny local scorecard.

| Test | Pass condition |
| --- | --- |
| Direct single tool call | Valid parsed call, exact arguments, no leaked control tokens. |
| Two tool calls in one turn | Both calls parsed and executed once. |
| Tool result then follow-up | Model uses returned data, not a fabricated continuation. |
| Error recovery | Model changes the request or reports the error; no retry loop. |
| Streaming vs non-streaming | Same successful structured outcome. |
| Misleading SERP snippet | Model fetches source pages or marks the answer unverified. |
| Static/JS/protected page | Correctly distinguishes fetched, unavailable, and blocked content. |
| Repo task | Inspects, edits, and runs a relevant verification command. |
| Daily monitor fixture | Emits a notification only for an actual normalized-field change. |

Run each Gemma test at least ten times sequentially. Compare it with the
existing Qwen 3.6 27B profile using identical tools, prompt, context limit, and
tool output. Record: valid-call rate, correct-source rate, task-completion
rate, turns, latency, raw-control-token leaks, and loops. This answers the
useful question: “is Gemma the limitation, or is the harness?”

## Recommended posture

* Keep Gemma 4 as an interactive generalist and test it seriously with the
  official checkpoint/template already running.
* Enable and measure thinking for bounded agent tasks; do not assume it fixes
  factual grounding.
* Use Native tools only, concise role-specific prompts, narrow tool menus,
  sequential tool runs, and bounded loops.
* Treat SearXNG as discovery. Require fetched primary sources for answers that
  can change or cost money.
* Repair and validate Firecrawl before integrating it into Open WebUI.
* Use Hermes for scoped repo work and deterministic jobs for scheduled checks.
* Keep Qwen 3.6 as a fair agentic/coding control. If it wins the fixed suite,
  that is useful routing information—not a failure of the local setup.

## Source quality note

Google, vLLM, Open WebUI, and Hermes documentation above establishes protocol
and product behavior. GitHub issues establish observed bugs in particular
versions. Community reports are cited as operational anecdotes only; they are
helpful for finding patterns but should not override your own measured results.
