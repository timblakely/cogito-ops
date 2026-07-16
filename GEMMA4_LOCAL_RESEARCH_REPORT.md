# Gemma 4, Open WebUI, and local web research

Research date: 2026-07-16  
Scope: diagnosis and community practice only. This report makes **no changes** to the cluster.

## Executive summary

The observed behavior—Gemma calls SearXNG, receives a stale or incorrect
snippet, and treats that snippet as the answer—is a known failure mode of
Open WebUI's current native/agentic web-search design. It is not simply a
SearXNG caching issue and it is not evidence that Gemma's function calling is
disabled.

In native mode, Open WebUI gives the model two separate tools:

1. `search_web` returns titles, URLs, and snippets only.
2. `fetch_url` returns extracted page content, but **only if the model decides
   the snippet is inadequate**.

This shifts the entire search -> choose URLs -> fetch -> compare evidence loop
onto the model. Gemma 4 can emit the required tool-call protocol, but local
users repeatedly report that it often stops after the first search, does not
fetch URLs, or becomes unreliable on multi-turn tool chains. Open WebUI now
documents this exact distinction, and an upstream issue describes the same
behavior for both Gemma 4 and Qwen local models.

The practical local-LLM community answer is not one magic prompt. It is to
reduce model discretion in the evidence pipeline, use a correct model-native
chat template/runtime, and route tasks to the model/interface that actually
passes measured tool-use tests. For interactive chat, Gemma can still be a
good generalist; for deep web research or autonomous workflows, many users
prefer a stronger agentic model or a harness that automatically retrieves and
ranks page content.

## What is happening in this cluster

### Confirmed local facts

* Open WebUI is pinned at **v0.10.2**.
* It exposes the official Google Gemma 4 31B QAT Compressed-Tensors model
  through vLLM with `--enable-auto-tool-choice`, the `gemma4` tool and
  reasoning parsers, and a mounted canonical Gemma 4 chat template.
* The model has Open WebUI's `web_search` and built-in-tools capabilities, and
  web search is selected by default. This rules out the simple case where
  Open WebUI never supplied the tools to Gemma.
* Open WebUI has SearXNG configured as the search engine but has **no web
  loader configured**. The cluster does already contain an internal Firecrawl
  deployment for extraction.
* SearXNG's upstream request timeout is set to **1.0 second**. SearXNG's own
  documentation describes 2.0 seconds as its example/default and explicitly
  notes that a larger timeout waits for slower engines. One second can make
  results more partial and biased toward whichever upstream engine responds
  first; it does not by itself prove that an individual snippet was cached.
  See [SearXNG outgoing settings](https://docs.searxng.org/admin/settings/settings_outgoing.html).
* `knowledge` is a separate BGE-M3/pgvector RAG service. Its configured web
  source list is empty, and its live database currently contains **0 sources
  and 0 chunks**. It cannot currently ground an answer.

### Why a bad snippet becomes “truth”

Open WebUI states that native `search_web` returns only titles, links, and
snippets; it performs no automatic retrieval, chunking, or embedding. The
model sees search-results-page material and must independently decide to call
`fetch_url` for full-page context. This is precisely why a plausible but wrong
snippet can end the process. [Open WebUI: Agentic Search & URL
Fetching](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search/)

That tool sequence asks the model to do five things correctly:

1. Notice that the answer is time-sensitive or weakly supported.
2. Distrust a fluent snippet.
3. Select one or more source URLs.
4. Issue more tool calls correctly.
5. Reconcile often-large page payloads into a cited answer.

For an agentic frontier model that may be acceptable. For a local model,
especially one serving a quantized checkpoint and a long conversational
context, it is a demanding planning problem rather than a simple search
problem.

An Open WebUI issue reports exactly this: Gemma 4 and Qwen 3.6 often answer
from snippets even after being instructed to fetch several sources. The
proposal is to restore automatic fetch/chunk/retrieval for native search so a
model that only calls search still receives grounded passages.
[Issue #26229](https://github.com/open-webui/open-webui/issues/26229)

## Gemma 4-specific findings

### It supports tools, but the protocol is unusually sensitive

Gemma 4 uses its own special-token function-call protocol. Google requires the
application to execute a tool call and append the result back to the message
history in Gemma's expected tool-response format. vLLM supports this with the
Gemma parser and the model's matching chat template. [Google function-calling
guide](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
and [vLLM Gemma 4 recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html)

That makes the template/parser/result-history contract much more important than
for ordinary chat. The cluster is already using the right broad approach, but
the wider ecosystem still reports problems in the corners that matter for
agents:

* A vLLM issue reports Gemma 4 leaking reasoning or tool-call text in
  multi-turn coding/tool sessions and tracks template/parser fixes.
  [vLLM #39043](https://github.com/vllm-project/vllm/issues/39043)
* A Hugging Face discussion identifies multi-round turn handling and placement
  of OpenAI-style `tool` content as a continuing template problem.
  [Gemma 4 discussion #115](https://huggingface.co/google/gemma-4-31B-it/discussions/115)
* A vLLM report found concurrent Gemma tool calls yielding `<pad>` output while
  the same requests succeeded sequentially. This is relevant because the
  current server permits two sequences at once.
  [vLLM #39392](https://github.com/vllm-project/vllm/issues/39392)
* Another vLLM issue documents repetition loops, especially with JSON-schema
  constrained decoding, across both 31B and 26B Gemma 4 variants and multiple
  serving platforms. [vLLM #40080](https://github.com/vllm-project/vllm/issues/40080)

These reports do **not** prove that every Gemma failure is a runtime bug. They
do support treating long, interleaved, schema-heavy agent loops as an area that
needs a small regression suite rather than confidence from a successful
one-tool demo.

### Thinking plus tools is not a blanket cure

vLLM documents that Gemma 4 can use thinking with tools. In practice, user
reports are mixed: some see better planning; others see lost reasoning after a
web call or malformed follow-up calls. A current Open WebUI thread describes
Gemma failing to reason between calls while Qwen worked for that user; another
reporter says vLLM with the non-GGUF model improved their case. These are
valuable field reports, but not controlled benchmarks.
[Open WebUI community report](https://www.reddit.com/r/OpenWebUI/comments/1uq12pp/gemma_4_12b_unable_to_reason_after_web_tool_with/)

The reasonable conclusion is: enable thinking only if it demonstrably improves
the exact multi-step workflow, and test tool-call syntax, follow-up reasoning,
and completion separately. Do not assume “more thinking” makes retrieval more
truthful.

## What local-LLM users are doing instead

| Pattern | Why people use it | Limits / evidence quality |
| --- | --- | --- |
| **SearXNG + a real extractor** (Firecrawl, Playwright, Crawl4AI) | Separates discovery from readable page extraction; avoids asking the model to reason over raw SERP text alone. | Still needs either model-driven fetch or a harness that fetches automatically. Local users explicitly report SearXNG + Crawl4AI as a self-hosted combination. [Example](https://www.reddit.com/r/LocalLLM/comments/1tj39rv/web_search_for_local_models/) |
| **An MCP web tool rather than Open WebUI's built-in web path** | Lets the tool return cleaner, more opinionated data and can combine search/extract in one call. A Gemma/Open WebUI user reported doing this after finding built-in search used snippets only. | Merely renaming the tool does not make Gemma plan better. Tool output and the server's fetch policy still matter. [Community thread](https://www.reddit.com/r/OpenWebUI/comments/1scfjys/gemma4_web_search_hang/) |
| **Auto-retrieve top results before synthesis** | Removes the weak “will the model decide to fetch?” hop. This is the direction proposed in Open WebUI issue #26229. | More latency, egress, and extraction failures; needs page/rank limits and source-quality policy. |
| **Use Qwen for agentic/coding work; Gemma for chat, vision, writing** | This is a common anecdotal split. Some users say Qwen searches/fetches more persistently, while Gemma is preferred as a conversational or multimodal model. | Not a benchmark or universal rule. One LocalLLaMA discussion reports Qwen 3.5 routinely fetching several URLs, while another user uses Qwen 3.6 for coding/agents and Gemma 4 for general work. [Discussion](https://www.reddit.com/r/LocalLLaMA/comments/1sp6qy7/best_local_llm_for_web_search/), [workload split](https://www.reddit.com/r/LocalLLaMA/comments/1tqy2iv/shoutout_to_gemma4_as_a_conversational_assistant/) |
| **Use a scheduler/agent harness for monitors, not a chat UI** | Monitoring Xfinity availability or eBay listings is a repeatable workflow: fetch, normalize, diff, notify. It should not depend on a chat model rediscovering the workflow every day. | An LLM may still add value for extraction ambiguity or summaries, but the source-of-truth check should be deterministic. |

## What `knowledge` is good for—and what it is not

`knowledge` is appropriate for your STM32 example, provided it is made
provenance-aware. It is a persistent vector corpus: documents are extracted,
chunked, embedded with BGE-M3, and searched through a small API/MCP tool. It
is not a live-web browser and should not answer “what did the market do today?”

Best uses:

* vendor manuals, datasheets, errata, and application notes;
* project repositories and design documents;
* stable personal documentation;
* an offline, cited corpus for technical Q&A.

For a 2,000-page reference manual, the current character-window chunking is
not enough to guarantee safe register answers: it does not preserve page or
section metadata in returned results. A trustworthy version should ingest by
page/heading, store document revision and file hash, return page/section
citations, and instruct the answering model to say “not found in the indexed
revision” when retrieval does not support a claim.

Open WebUI can connect to OAuth-protected remote MCP servers, but the tool
must be manually enabled for a user’s first authorization; OAuth MCP tools
should not be default tools because the browser consent flow cannot happen
mid-completion. [Open WebUI MCP documentation](https://docs.openwebui.com/features/extensibility/mcp/)

## Recommended experiments before changing architecture

These are tests to run later, not implementation instructions.

1. **Prove the evidence path.** Use three fixed prompts: a static page, a
   JavaScript-rendered page, and a deliberately misleading search snippet.
   Record whether the model calls `fetch_url`, whether extraction succeeds,
   and whether the final statement cites page content rather than the snippet.
2. **Hold the backend constant; compare models.** Run Gemma 4 31B and the
   available Qwen model against the same tool definitions, system prompt,
   SearXNG results, and Firecrawl output. Measure fetch rate, correct answer
   rate, citation coverage, malformed-call rate, and loop/timeout rate.
3. **Test sequentially first.** Keep tool-chain evaluation at one active
   sequence before interpreting failures as model intelligence; there is a
   reported Gemma/vLLM concurrent tool-call failure mode.
4. **Compare forced retrieval with model-chosen retrieval.** Feed the same
   question: once through native `search_web` + voluntary `fetch_url`, and
   once through a harness that fetches the top two or three sources and passes
   only relevant extracted chunks. This isolates planning failure from search
   quality.
5. **Treat monitors as programs first.** For Xfinity/eBay, create a
   deterministic fetch/parse/diff fixture and let an LLM summarize only the
   structured change. It is safer, cheaper, and easier to debug than a fully
   agentic daily run.
6. **Make an adversarial RAG set.** For the STM32 manual, include real
   register questions, absent-register questions, and revision-conflict
   questions. Pass only if answers cite the correct page/section or decline
   unsupported claims.

## Bottom line

Gemma 4 is not “dumb” in the narrow sense of being unable to call tools. It is
being used in a workflow that asks a local model to make a second-order
epistemic judgment—“is this SERP snippet insufficient, and which pages should
I fetch?”—and Gemma 4 is frequently reported to be conservative or unreliable
at that step. The native chat-template/tool-result protocol adds another
failure surface.

The most robust local path is therefore layered:

* use Gemma where it tests well as an interactive generalist;
* use an extraction-aware, evidence-first pipeline for live research;
* use Hermes or deterministic jobs for repeatable monitoring and repo agents;
* use the `knowledge` service for versioned, cited source material rather than
  current events.

That architecture lets you improve truthfulness without betting every task on
one model autonomously choosing the right next tool call.
