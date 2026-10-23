---
name: llm-provider-reasoning-config
description: "Use when configuring per-model reasoning effort."
version: 0.1.0
author: Tim, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [llm, reasoning, providers, configuration, litellm]
    related_skills: [hermes-agent, gpu-llm-serving]
---

# LLM Provider Reasoning Configuration

Use this skill when a model's thinking/reasoning levels need to be added, corrected, or validated in Hermes or an OpenAI-compatible gateway. The goal is observed provider behavior, not merely a config value that the gateway accepts.

## Procedure

1. Identify the exact provider/model route and inspect the current override with `hermes config get agent.reasoning_overrides`. Distinguish the provider-qualified model id from the bare model alias before editing.

2. Inspect the Hermes resolver and provider adapter that handle the setting. Confirm which keys are consumed (`enabled`, `effort`, or a provider-specific field) and whether capability metadata is published for that provider. Do not infer support from another provider's ladder.

3. Probe the live route with a fixed temperature, identical prompt, and the exact wire shape Hermes sends. Compare the field omitted, an explicit off value such as `none`, and each candidate effort. Record status, reasoning presence/length, and output differences. An accepted field with identical output is not evidence of graded support; it may be ignored or the backend may be binary.

4. Check passthrough requirements before interpreting failures. OpenAI-compatible gateways may reject or drop `reasoning_effort` unless it is listed in their allowed OpenAI parameters; nested fallback fields may be silently ignored. Validate the actual request path rather than testing only a local resolver.

5. Persist the smallest explicit correction through the CLI, never by hand-editing YAML: `hermes config set agent.reasoning_overrides.<provider>/<model> <effort>`. Use a mapping with `enabled`/`effort` only when the resolver requires it. Keep unrelated global and per-model settings untouched.

6. Validate resolution for both the qualified model id and its bare spelling, then re-check the config. Confirm that the intended model is explicitly on or off and that unrelated models retain their prior global or per-model values. Restart the CLI/gateway only when required for the config change to take effect.

## Shipped architecture: litellm-caps plugin + model-caps sidecar (Oct 2026)

- Publishing: cogito `kubernetes/apps/llm/litellm/app/model-caps.yaml` — a
  sibling Deployment (LiteLLMProxy CRD has no sidecar field) that proxies
  litellm's admin /v1/models server-side and merges an operator-curated
  caps.json into OpenRouter-schema blocks; served at
  https://litellm.timblakely.com/caps/v1/models via HTTPRoute /caps prefix
  (gateway does NOT strip prefixes — the server matches path.endswith).
  Curated in-git because backends don't publish truth; absent model =
  passthrough-unknown, never a guessed verdict.
- Consuming: ~/.hermes/plugins/model-providers/litellm-caps/ (user plugin,
  upgrades never touch it; stand-down mode if the bundled custom profile
  can't be imported). Overrides the `custom` profile via documented
  last-writer-wins register_provider. Reads providers.<name>.caps_url config
  key (defaults to <base_url>/models). Caps cache: memory + 24h disk mirror at
  ~/.hermes/cache/litellm_caps.json, background warm, never HTTP on hot path.
  **In the cluster agent these paths are under HERMES_HOME=/opt/data, not
  ~/.hermes** (plugins/model-providers/litellm-caps, cache/litellm_caps.json);
  the pod has no ~/.hermes at all, and `grep ~/.hermes/...` there returns
  nothing, which reads like a missing plugin.
- Effort-set semantics that matter: supported_efforts=[] + mandatory=true =
  "always thinking, omit reasoning fields" (Muse/llama.cpp); ["none"] = binary
  with working off switch (vLLM models); None = unknown -> bundled behavior.
  build_api_kwargs_extras mirrors that onto the wire.
- Pitfall: user model-provider plugins load DURING a discovery re-entry (early
  bundled plugin -> hermes_cli.auth.list_providers -> _scan_home_layer), BEFORE
  the loader imports the bundled custom profile — `from
  plugins.model_providers.custom import ...` fails at that moment. Fallback:
  load the file by path via providers.__file__'s parent. Discovered live.
- Pitfall (fixed in cogito 7e06e070, 2026-10-12): the plugin's provider reader
  originally accepted only `base_url:`; shipped config.yaml spells litellm
  endpoints `api:` → reader saw 0 providers and every caps lookup silently fell
  back to the bundled widest ladder ("gemma has 7 thinking levels"). Hermes core
  readers accept api/url/base_url aliases — any provider-config reader must too,
  and a caps plugin must assert candidates>0 at startup or its failure is silent.
- Cogito agent-bundle edits (kubernetes/apps/llm/hermes/app/agent-bundle/**) are
  NOT live: bundle.yaml is generated. After editing, run
  `python3 gen-bundle.py` from kubernetes/apps/llm/hermes/app (regenerates
  bundle.yaml + provider-bootstrap.yaml and stamps the bundle-sha256 pod
  annotation in helmrelease.yaml so Flux rolls the deployment), verify with
  `gen-bundle.py --check`, push main via jj, then
  `flux reconcile source git flux-system -n flux-system && flux reconcile
  kustomization llm -n flux-system --with-source`. Verify in-pod with the clean-
  interpreter snippet: load /opt/data/plugins/model-providers/litellm-caps/
  __init__.py via importlib and check _openai_compat_providers() is non-empty and
  _caps_for_model('google/gemma-4-12b-it') → supported_efforts ['none'].
- Upstream picker-display gap tracked in NousResearch/hermes-agent #66543
  (umbrella; PRs #114033/#125810/#95402, issue #129002, all open as of
  2026-10-12). clamp_effort passthrough on ('none',)-only and empty sets means
  naive profile-hook wiring makes the status echo lie — tri-state contract
  needed. Evidence comment drafted at /home/tim/reasoning-caps-issue-66543-
  comment.md (not yet posted as of 2026-10-12; gh auth works as timblakely).
- Pitfall: kustomize-then-apply from /tmp must substitute ALL flux vars
  (${APP}, ${DOMAIN_NAME}, ${NS}) or resources land in `default`.
- Live verdicts (probes in scratch/muse_probe*.py, flashnext_probe.py,
  fleet_probe.py): Muse efforts=() mandatory; flashnext and
  google/gemma-4-12b-it ["none"] (the flashnext verdict was measured on the
  `flashnext-iggy` lane before that node's R9700s moved to Deleuze — the alias
  is now `flashnext-deleuze` on the same runtime family, so re-probe before
  quoting it); Qwen/Qwen3.8-27B-INT8-W8A16 unknown (pod was
  down when probed — correct to leave absent, re-probe then add).

## Verified capability facts (llama.cpp / LiteLLM / Hermes, Oct 2026)

- llama.cpp's OpenAI server does NOT implement a per-request effort ladder: a
  live probe of Muse-Glimmer-30B (server-cuda, `--jinja`, ATEM template) returned
  identical reasoning output for `reasoning_effort` omitted / none / low / medium /
  xhigh / high / bogus, and for per-request `reasoning_budget` 0 / 64 / 1024.
  `chat_template_kwargs.enable_thinking=false` is also ignored (no effect unless
  the chat template itself has a think switch). The only real throttle is the
  server-start flag `--reasoning-budget` (set per InferenceService in llmkube).
  So llama.cpp publishes no effort capability anywhere (/props shows template
  defaults only) and per-request controls are accept-and-ignore — the picker
  ladder for such a route is fiction.
- LiteLLM's `/v1/models` publishes only id/owned_by/max_input_tokens/
  max_output_tokens — no reasoning metadata (verified against cogito litellm);
  `supports_reasoning: true` in the LiteLLMModel CRD `info.extra` never reaches
  it. `/v1/model/info` exists but admin-scoped (401 with the hermes key).
- Hermes DOES have the discovery machinery: `hermes_cli/models_reasoning_caps.py`
  parses OpenRouter-schema `/v1/models` entries (`supported_parameters` contains
  "reasoning" + `reasoning.supported_efforts`/`mandatory`, tri-state contract,
  24h disk mirror at cache/reasoning_caps.json). But
  `hermes_cli/inventory.py::_reasoning_catalog_reader` wires it ONLY for the
  openrouter/nous slugs; custom providers get no catalog, and
  plugins/model-providers/custom declares the widest OPENAI_COMPAT_WIRE_EFFORTS
  on purpose ("a custom endpoint's vocabulary is undiscoverable"). That is why
  custom:litellm-chat models show the full OpenAI ladder regardless of backend.
  Auto-discovery for litellm = publish OpenRouter-shaped reasoning blocks on its
  /v1/models (LiteLLMModel extra→catalog passthrough) + add a caps source for
  the custom provider in Hermes; discovery alone can't create ladder levels the
  backend doesn't implement — for Muse the honest caps are
  supports_reasoning: true, supported_efforts: null, no disable.

## Pitfalls

- Do not add a `supported_efforts` list to a local override unless the consuming code reads it; provider capability metadata and override shape are separate, and decorative keys create false confidence.
- Do not treat every accepted ladder word as a real level; compare behavior at fixed sampling settings because gateways commonly accept-and-ignore unsupported effort names.
- Do not call a model's reasoning support "graded" when the live route only distinguishes enabled from disabled; document the binary behavior and use the explicit off switch when that is the desired default.
- Do not test only the bare model name; provider-qualified ids can select different routes, and a spelling-tolerant resolver can hide a wrong provider selection.
- Do not hand-edit `config.yaml`; use `hermes config set` so YAML structure and profile-specific paths remain safe.
- Do not report a reasoning correction as complete from resolver output alone; verify the provider's request passthrough and live response behavior as well.

## Verification Checklist

- Exact provider/model route is identified.
- Resolver keys and provider adapter behavior are confirmed from source.
- Omitted, off, and candidate effort requests were compared under fixed conditions.
- Passthrough/allowed-parameter behavior is verified.
- CLI-written override resolves for qualified and bare model spellings.
- Global and unrelated per-model reasoning settings are unchanged.
