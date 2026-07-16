# Gemma 4, Open WebUI, and local web research

Research date: 2026-07-16  
Scope: diagnosis and community practice only. This report makes **no changes** to the cluster.

Source convention: claims about this cluster link to checked-in manifests;
product behavior links to first-party documentation or upstream issues; community
experience is explicitly labeled anecdotal.

## Executive summary

The observed behavior—Gemma calls SearXNG, receives a stale or incorrect
snippet, and treats that snippet as the answer—is a known failure mode of Open
WebUI's native/agentic web-search design. It is not simply a SearXNG caching
issue and it is not evidence that Gemma's function calling is disabled.

In native mode, Open WebUI gives the model two separate tools:

1. `search_web` returns titles, URLs, and snippets only.
2. `fetch_url` returns extracted page content, but **only if the model decides
   the snippet is inadequate**.

The search -> choose URLs -> fetch -> compare-evidence loop is therefore a
model-planning problem. Gemma 4 can emit the required tool-call protocol, but
local users repeatedly report that it often stops after the first search, does
not fetch URLs, or becomes unreliable on multi-turn tool chains. An upstream
Open WebUI issue reports the same behavior for both Gemma 4 and Qwen local
models. [Open WebUI agentic search docs](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/), [Open WebUI #26229](https://github.com/open-webui/open-webui/issues/26229)

The local-LLM community answer is not one magic system prompt. It is to reduce
model discretion in the evidence pipeline, use the model-native template and
parser, and route tasks to the model or harness that passes measured tool-use
tests. Gemma can remain a strong interactive generalist; deep research and
autonomous work benefit from automatic retrieval or a more tool-reliable model.

## Confirmed state in this cluster

* Open WebUI is pinned at **v0.10.2** in its [HelmRelease](app/helmrelease.yaml).
* Gemma is served through vLLM with `--enable-auto-tool-choice`, `gemma4`
  reasoning/tool parsers, and the mounted canonical chat template. The model
  has Open WebUI web-search and built-in-tool capabilities, so this is not the
  simple case where it was never offered tools.
* Open WebUI uses SearXNG but has no web loader configured. The cluster does
  have a separate internal Firecrawl deployment; see its [README](../../tools/firecrawl/README.md).
* SearXNG's upstream timeout is **1.0 second**. SearXNG documents 2.0 seconds
  as its example/default and notes that raising it permits slow engines to
  answer. One second can yield partial, fast-engine-biased results; it does not
  itself prove a particular snippet was cached. [SearXNG outgoing settings](https://docs.searxng.org/admin/settings/settings_outgoing.html)
* `knowledge` is a separate BGE-M3/pgvector RAG service. Its web list is empty
  in [sources.yaml](../knowledge/app/sources.yaml); its live database had zero
  sources and zero chunks when inspected. It cannot presently ground answers.

## Why the snippet wins

Open WebUI documents that native `search_web` returns only SERP-style
metadata—no automatic vector-store retrieval, chunking, or embedding. The
model must decide whether that evidence is enough and, if not, call
`fetch_url`. [Open WebUI: Agentic Search & URL Fetching](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

That requires the model to:

1. notice that the question is current or weakly supported;
2. distrust a fluent snippet;
3. choose primary URLs;
4. issue further calls correctly; and
5. reconcile potentially large page payloads into a cited answer.

Issue #26229 specifically says local Gemma 4 and Qwen 3.6 tests frequently
answered from snippets even after being told to fetch several sources. It
proposes automatic fetch/chunk/retrieval after search so the model need not
independently orchestrate every hop. [Open WebUI #26229](https://github.com/open-webui/open-webui/issues/26229)

## Gemma 4-specific findings

### Native tool support is real, but unusually sensitive

Gemma 4 uses special tokens for function declarations, calls, and responses.
Google requires the application to execute the call and append a result back in
the expected tool-response form. vLLM supports this using the Gemma parser and
a matching chat template. [Google function-calling guide](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4), [vLLM Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)

The exact template/parser/result-history contract matters. Upstream reports
identify several agent-relevant edge cases:

* [vLLM #39043](https://github.com/vllm-project/vllm/issues/39043) reports
  leaking reasoning/tool-call text in multi-turn tool sessions and tracks
  template/parser work.
* [Gemma Hugging Face discussion #115](https://huggingface.co/google/gemma-4-31B-it/discussions/115)
  describes multi-round turn handling and placement of OpenAI-style tool
  content as ongoing template concerns.
* [vLLM #39392](https://github.com/vllm-project/vllm/issues/39392) reports
  concurrent Gemma tool calls yielding `<pad>` output while sequential requests
  succeed. This matters because the live server permits two sequences.
* [vLLM #40080](https://github.com/vllm-project/vllm/issues/40080) documents
  structured-output repetition loops across Gemma 4 variants and serving
  platforms, especially with JSON-schema constraints.

These issues do not prove that every Gemma failure is a runtime bug. They do
mean long, interleaved, schema-heavy agent loops should be regression-tested,
not inferred from a one-tool demo.

### Thinking plus tools is not a blanket cure

vLLM supports Gemma thinking with tools, but user reports are mixed. Some find
it improves planning; others see lost reasoning after a web call or malformed
follow-up calls. One current Open WebUI thread reports that vLLM/non-GGUF
serving improved a user's case, while Qwen worked better for another tool
chain. This is anecdotal, not a controlled benchmark.
[r/OpenWebUI report](https://www.reddit.com/r/OpenWebUI/comments/1uq12pp/gemma_4_12b_unable_to_reason_after_web_tool_with/)

## What local-LLM users do instead

| Pattern | Rationale | Caveat |
| --- | --- | --- |
| SearXNG + Firecrawl/Playwright/Crawl4AI | Separates URL discovery from readable-page extraction. | The model still needs to fetch unless the harness does it automatically. [Local example](https://www.reddit.com/r/LocalLLM/comments/1tj39rv/web_search_for_local_models/) |
| MCP web tool instead of built-in web path | A custom tool can combine search/extract or return cleaner evidence. | Tool naming alone does not improve planning. [Gemma/Open WebUI anecdote](https://www.reddit.com/r/OpenWebUI/comments/1scfjys/gemma4_web_search_hang/) |
| Auto-fetch/rank top results | Removes the brittle “will the model choose `fetch_url`?” hop. | Costs latency and needs source/rank limits; this is the direction proposed by Open WebUI #26229. |
| Qwen for coding/agents; Gemma for general chat | Common workload split in community discussion. | Anecdotal, not universal: benchmark against the same harness. [Search discussion](https://www.reddit.com/r/LocalLLaMA/comments/1sp6qy7/best_local_llm_for_web_search/), [workload split](https://www.reddit.com/r/LocalLLaMA/comments/1tqy2iv/shoutout_to_gemma4_as_a_conversational_assistant/) |
| Deterministic monitors, LLM summaries | Xfinity/eBay checks are fetch/parse/diff/notify workflows; they should not depend on a chat model rediscovering the procedure daily. | LLMs can still summarize ambiguous changes, but should not define truth. |

## Why the same model acts differently in Open WebUI and Hermes

“Harness” means the software around the model: the messages it constructs, the
tools it exposes, how it executes calls, what it feeds back, and when it stops.
The model weights can be identical while the effective task is substantially
different.

```text
user request
    │
    ├─ Open WebUI native web mode
    │    search_web -> SERP snippets -> model chooses fetch_url -> page text
    │
    └─ Hermes web workflow
         web_search -> ranked URLs -> web_extract(url) -> extracted markdown
         (+ skills, persistent workflow instructions, scheduler, file/code tools)
```

### 1. Tool semantics and granularity

In Open WebUI native mode, `search_web` and `fetch_url` are independent
decisions. Search returns snippets and the model must decide to deepen the
investigation. This is the precise decision Gemma is often declining.
[Open WebUI agentic-search documentation](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

Hermes documents separate `web_search` and `web_extract` capabilities, and
explicitly supports a SearXNG-for-search + Firecrawl-for-extraction split. The
tool names, descriptions, result shape, and any tool-specific system guidance
are therefore different even when both ultimately use SearXNG and Firecrawl.
[Hermes Web Search & Extract](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search)

This does **not** mean Hermes automatically fixes Gemma: Hermes still needs a
model to choose `web_extract`. It does mean the tool contract may make the
intended next step more obvious, and it gives the harness a natural place to
apply workflow policy—such as always extracting an official URL for a
time-sensitive claim.

### 2. Prompt construction and tool-result history

Every harness serializes the same conceptual conversation differently. It may
inject a different system prompt, include more or fewer tool schemas, set a
different tool choice, truncate tool output differently, and represent an
assistant tool call plus returned data differently on the next turn. Gemma is
particularly sensitive here because its native protocol uses specialized
tokens, and upstream reports identify multi-round template/history issues.
[Google tool-calling format](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4),
[vLLM #39043](https://github.com/vllm-project/vllm/issues/39043),
[Gemma discussion #115](https://huggingface.co/google/gemma-4-31B-it/discussions/115)

Consequently, “works in Hermes but not Open WebUI” can reflect a better
rendered conversation rather than a smarter model. The inverse is also true:
a tool-rich coding harness can make a simple research question harder by
inflating the tool schema and distracting the model from the web path.

### 3. State, stopping rules, and deterministic work outside the model

Open WebUI chat is primarily an interactive, user-steered loop. Hermes can
attach reusable skills, select a narrow toolset for scheduled jobs, use a fixed
working directory, deliver results to a target, and skip an LLM invocation
entirely when a script determines that nothing changed. Those are harness
features, not model intelligence. [Hermes cron documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/cron.md)

For a daily Xfinity check, a harness can make HTTP retrieval, normalization,
state comparison, and alert suppression deterministic; the model only sees a
change event to summarize. Open WebUI can still be the better interface for
the follow-up question, “what does this new plan imply for me?”

### 4. Context budget and evidence selection

Page text is much larger and noisier than a snippet. A harness that injects
several raw pages can cause a local model to lose the relevant fact, while a
harness that extracts, chunks, ranks, and sends only relevant passages makes
the synthesis task easier. Open WebUI’s own native-search proposal calls this
out: direct page payloads are expensive and unreliable for local models, and
retrieval should occur before the final model turn. [Open WebUI #26229](https://github.com/open-webui/open-webui/issues/26229)

### Practical comparison

| Question | Open WebUI is usually the better fit when… | Hermes is usually the better fit when… |
| --- | --- | --- |
| One-off live question | You want a conversational answer, visible sources, and quick follow-ups. | You need an explicit search/extract workflow or access to local project tools. |
| Deep research | The UI/harness automatically retrieves and ranks source passages, or the chosen model is proven to use fetch reliably. | The work needs reusable instructions, source policy, files/code, or a repeatable report pipeline. |
| Coding/repo work | You only need discussion or review. | The agent needs repository-local instructions, terminal/file tools, or a controlled multi-step loop. |
| Scheduled monitoring | You are manually asking a question. | The job needs polling, state, diffing, delivery, and a narrow permission set. |

The right evaluation compares **end-to-end harnesses**, not model names alone:
same questions, known-good sources, fixed timeouts, recorded tool trace, and
claim-level citation checks.

## Can Open WebUI make multi-turn tool calls?

**Yes.** In Native/Agentic mode, Open WebUI can run an iterative tool loop
within one user message:

```text
model reasoning -> tool call(s) -> Open WebUI executes them -> tool results
                -> model continues reasoning -> more tool call(s) -> final answer
```

It supports both multiple calls in one model response and sequential rounds of
calls. Open WebUI calls this “multi-step chaining” and “interleaved thinking”;
its reasoning documentation says it preserves the prior reasoning, tool call,
and tool result when it builds the next model request. [Open WebUI tools
guide](https://docs.openwebui.com/features/extensibility/plugin/tools/),
[interleaved-thinking documentation](https://docs.openwebui.com/features/chat-conversations/chat-features/reasoning-models/)

The native agentic loop has an explicit safety ceiling:
`CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS`, default **256**, counts sequential
tool-calling rounds per user message. Several calls emitted in one response
count as one round; successful and failed calls both consume a round. The
counter resets on the next user message. [Open WebUI environment
reference](https://docs.openwebui.com/reference/env-configuration/)

For web research, the intended sequence is therefore supported:

```text
search_web("DJI close")
  -> inspect snippets
  -> fetch_url(relevant primary page)
  -> inspect page
  -> optionally search again or fetch a second source
  -> answer with citations
```

### Why this is not the same as Hermes

Open WebUI owns the **loop mechanics**—execute tool results, append them to
history, and ask the model again—but Native mode deliberately leaves the
**next-action decision** to the model. It will not automatically turn a
`search_web` result into `fetch_url` calls merely because that would be a good
research practice. Its own web-search documentation says snippets are all the
model receives after search, and that it calls `fetch_url` only if it determines
the snippet is insufficient. [Open WebUI agentic search](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

Hermes likewise needs its model to choose `web_extract` in an interactive
session, but it offers a more agent-oriented outer harness: skills, narrow
toolsets, reusable job prompts, workspace context, and scheduled workflows
where scripts can gate whether an LLM runs at all. That can make a workflow
more reliable without making the base model intrinsically better.

### What this means for this Gemma deployment

Your Open WebUI 0.10.2 deployment is new enough to support native multi-turn
tool loops. The relevant question is not “can it loop?” but “does Gemma make
the next call correctly after seeing this particular result?” The current
evidence says that is the weak point: local-model reports—and Open WebUI’s own
open enhancement proposal—describe models stopping after snippets rather than
calling `fetch_url`. [Open WebUI #26229](https://github.com/open-webui/open-webui/issues/26229)

There is an additional version-specific risk: an issue reports `fetch_url`
failing in Open WebUI 0.10.2 even when the model correctly invoked it. That is
separate from Gemma’s decision-making and should be tested before interpreting
every missing follow-up fetch as “the model was lazy.” [Open WebUI #26791](https://github.com/open-webui/open-webui/issues/26791)

In short: Open WebUI can perform Hermes-style multi-turn orchestration, but it
does not presently provide Hermes-style workflow policy. If Gemma emits
`search_web` then `fetch_url` then another search, Open WebUI can carry that
chain. If Gemma stops at the snippet, Open WebUI treats that as the model's
final decision unless a separate retrieval-oriented harness is added.

## What major LLM providers changed to make this work

Major providers generally do not present “a normal chat completion with a web
search function” as their deep-research product. They add an agent loop,
specialized training or prompting, source controls, long-running execution,
and auditability around the base model.

### 1. Separate quick search from a dedicated research mode

OpenAI explicitly distinguishes quick Search from Deep Research. The latter
plans, searches, evaluates sources, refines queries, and synthesizes a cited
report; the user can review the plan and constrain sources. [OpenAI research
overview](https://openai.com/academy/search-and-deep-research/), [OpenAI Help:
Deep Research](https://help.openai.com/en/articles/10500283-Deep-Research-fa)

Anthropic similarly presents Research as a mode that conducts multiple,
dependent searches and works systematically through open questions, rather
than treating web search as an occasional optional tool. [Claude Research
documentation](https://support.claude.com/en/articles/11088861-use-research-on-claude)

**Local lesson:** expose separate profiles/workflows for “quick lookup” and
“research report.” Do not expect one default chat tool configuration to behave
optimally for both latency-sensitive facts and multi-source due diligence.

### 2. Train and evaluate for persistent browsing, not only tool syntax

OpenAI says its Deep Research agent was trained for persistent browsing, and
its BrowseComp evaluation shows that merely adding browsing to a general model
gave little improvement; the research-specialized agent performed much better.
OpenAI attributes the gap to strategic search, source evaluation, flexible
reformulation, and synthesis across fragmented clues.
[BrowseComp results](https://openai.com/index/browsecomp/)

**Local lesson:** correct JSON/tool syntax is necessary but insufficient.
Evaluate the behavioral properties you care about: persistence after an empty
or conflicting result, primary-source selection, query reformulation, and
evidence-grounded refusal.

### 3. Make retrieval a managed, long-running workflow

Google’s Gemini Deep Research API treats research as asynchronous background
execution rather than a single chat response. One request triggers planning,
searching, reading, and reasoning; Google documents typical runs involving many
searches and large contexts. It also offers collaborative planning and
recommends reviewing citations. [Gemini Deep Research Agent](https://ai.google.dev/gemini-api/docs/deep-research?hl=en)

**Local lesson:** a serious local research workflow needs explicit budgets:
maximum searches/fetches, extraction timeout, page/chunk budget, wall-clock
deadline, stop conditions, and a trace. A chat UI can display this workflow,
but should not be the workflow's only control surface.

### 4. Control sources and make evidence reviewable

OpenAI lets users restrict or prioritize sites, use read-only connected sources,
review a research plan, inspect citations, and follow task progress. Claude and
Gemini likewise present citations as a core part of research rather than an
afterthought. [OpenAI Help](https://help.openai.com/en/articles/10500283-Deep-Research-fa),
[Claude Research](https://support.claude.com/en/articles/11088861-use-research-on-claude),
[Gemini Deep Research](https://ai.google.dev/gemini-api/docs/deep-research?hl=en)

**Local lesson:** add explicit source policy outside the model: prefer official
documents for specifications, require more than one source for recommendations,
and attach URL/title/extracted passage to every final citation. The model should
not be allowed to cite an un-fetched snippet as if it had read a page.

### 5. Isolate tools and bound autonomy

Google warns that web pages and uploaded files can contain prompt injection and
that combining private data with browsing creates exfiltration risk. Its managed
agent offering describes an isolated sandbox; OpenAI's research mode limits
connected-app research to read actions. [Gemini safety guidance](https://ai.google.dev/gemini-api/docs/deep-research?hl=en),
[OpenAI Deep Research controls](https://help.openai.com/en/articles/10500283-Deep-Research-fa)

**Local lesson:** use separate, least-privilege toolsets for research, coding,
and monitoring; treat web content as untrusted data; and keep purchases, form
submissions, and repository writes outside unattended research jobs.

## `knowledge`: the right tool for stable ground truth

`knowledge` is a persistent vector corpus, not a live-web browser. It is a
good fit for STM32 manuals, datasheets, errata, repositories, and personal
documents. It is not the right source for today's weather or market close.

For a 2,000-page reference manual, the current character-window chunking does
not preserve page/section metadata in returned results. A trustworthy technical
RAG should ingest by page/heading, retain revision and file hash, return
page/section citations, and tell the answer model to say “not found in the
indexed revision” when retrieval does not support a claim.

Open WebUI supports OAuth-protected remote MCP tools, but initial authorization
must be user-driven and OAuth MCP tools should not be enabled as default tools.
[Open WebUI MCP documentation](https://docs.openwebui.com/features/extensibility/mcp/)

## Experiments worth running later

1. Hold tools and retrieved pages constant while comparing Gemma and Qwen;
   record fetch rate, correct-answer rate, citation coverage, malformed calls,
   and loops/timeouts.
2. Test a static page, JS page, and deliberately misleading snippet; log whether
   the model fetched a primary source and cited page content rather than a SERP.
3. Test sequentially before concurrent calls, because concurrency itself has a
   reported Gemma/vLLM failure mode.
4. Compare voluntary `fetch_url` with automatic retrieval of the top two or
   three results and injection of only relevant extracted chunks.
5. Create an STM32 adversarial RAG set: known registers, absent-register traps,
   and revision conflicts. Pass only when the answer cites correct page/section
   evidence or declines the claim.

## Bottom line

Gemma 4 is not incapable of tools. It is being asked to make a second-order
judgment—whether a search snippet is insufficient and which pages to fetch—in a
fragile multi-turn protocol. It is frequently reported to be conservative or
unreliable at that step. The robust local strategy is to keep Gemma where it
tests well as an interactive generalist, but use evidence-first retrieval,
deterministic monitors, and a separately measured agentic model/harness for
tool-heavy tasks.

## Sources and evidence quality

### Primary documentation

* [Open WebUI: Agentic Search & URL Fetching](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)
* [Open WebUI: Web Search troubleshooting](https://docs.openwebui.com/troubleshooting/web-search/)
* [Open WebUI: environment configuration](https://docs.openwebui.com/reference/env-configuration/)
* [Open WebUI: Tools and Native Mode](https://docs.openwebui.com/features/extensibility/plugin/tools/)
* [Open WebUI: Interleaved Thinking with Tool Calls](https://docs.openwebui.com/features/chat-conversations/chat-features/reasoning-models/)
* [Google: Function calling with Gemma 4](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
* [vLLM: Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)
* [SearXNG outgoing settings](https://docs.searxng.org/admin/settings/settings_outgoing.html)
* [Open WebUI: MCP](https://docs.openwebui.com/features/extensibility/mcp/)
* [Hermes: Web Search & Extract](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search)
* [Hermes: Scheduled Tasks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/cron.md)
* [OpenAI: Search and Deep Research](https://openai.com/academy/search-and-deep-research/)
* [OpenAI Help: Deep Research](https://help.openai.com/en/articles/10500283-Deep-Research-fa)
* [OpenAI: BrowseComp](https://openai.com/index/browsecomp/)
* [Anthropic: Use Research on Claude](https://support.claude.com/en/articles/11088861-use-research-on-claude)
* [Google: Gemini Deep Research Agent](https://ai.google.dev/gemini-api/docs/deep-research?hl=en)

### Upstream issue trackers

* [Open WebUI #26229](https://github.com/open-webui/open-webui/issues/26229)
* [Open WebUI #26791](https://github.com/open-webui/open-webui/issues/26791)
* [vLLM #39043](https://github.com/vllm-project/vllm/issues/39043)
* [vLLM #39392](https://github.com/vllm-project/vllm/issues/39392)
* [vLLM #40080](https://github.com/vllm-project/vllm/issues/40080)
* [Gemma Hugging Face discussion #115](https://huggingface.co/google/gemma-4-31B-it/discussions/115)

### Community reports (anecdotal, not benchmark evidence)

* [Gemma4 Web Search Hang — r/OpenWebUI](https://www.reddit.com/r/OpenWebUI/comments/1scfjys/gemma4_web_search_hang/)
* [Gemma 4 unable to reason after a web tool — r/OpenWebUI](https://www.reddit.com/r/OpenWebUI/comments/1uq12pp/gemma_4_12b_unable_to_reason_after_web_tool_with/)
* [Best local LLM for web search — r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1sp6qy7/best_local_llm_for_web_search/)
* [Gemma 4 conversational assistant / agent — r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1tqy2iv/shoutout_to_gemma4_as_a_conversational_assistant/)
* [Web search for local models — r/LocalLLM](https://www.reddit.com/r/LocalLLM/comments/1tj39rv/web_search_for_local_models/)
