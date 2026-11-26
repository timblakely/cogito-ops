#!/usr/bin/env python3
"""Consumer-side checks for the inkling-deleuze alias: the files that advertise it.

The catalogue validator renders litellm/app and llmkube/resources; these consumers
are parsed here because their kustomizations cannot build standalone. Each check
mirrors a rule that file states for itself, so a PASS means "this file agrees with
its own documented rule", not "a linter is happy":

  1. hermes/app/configure.py compiles, the alias it registers names a real
     LiteLLMModel, and provider-bootstrap.yaml is configure.py embedded verbatim
     (gen-bundle.py's own render), with helmrelease.yaml's bundle-sha256 second
     half equal to sha256(configure.py) -- the pod-roll contract.
  2. opencode/app/opencode-config.yaml: the cogito block's modelID values are real
     aliases, every `limit` mirrors that alias's maxInputTokens/maxOutputTokens,
     every `capabilities.input` image claim matches supportsVision, and every
     effort level listed is one that alias's caps ladder publishes.
  3. opencode/app/paseo-config.yaml: every cogito model row resolves to an alias in
     the `opencode` key's scope, and the two provider lists (opencode and
     opencode-worker, which extends it) carry the same model set.
  4. Both files stay valid: the JSON-ish ConfigMap data parses as JSON.

Usage: python3 check_consumers.py
"""
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Repo root from this file's location (plans/llm/artifacts/<dir>/), so the copy
# in the repository is runnable; RENDERED is this directory's rendered/ copy,
# refreshed with the two kustomize builds named in the docstring.
ROOT = Path(__file__).resolve().parents[4]
HERMES = ROOT / "kubernetes/apps/llm/hermes/app"
OPENCODE = ROOT / "kubernetes/apps/llm/opencode/app"
RENDERED = Path(__file__).resolve().parent / "rendered"
fails = []


def ok(m):
    print("PASS:", m)


def bad(m):
    fails.append(m)
    print("FAIL:", m)


litellm = [d for d in yaml.safe_load_all((RENDERED / "litellm-app.yaml").read_text()) if d]
models = {m["metadata"]["name"]: m for m in litellm if m["kind"] == "LiteLLMModel"}
# LiteLLM routes on spec.modelName; the CR's metadata.name is only the file's short name
# (gemma-4-12b.yaml publishes google/gemma-4-12b-it). Key scopes name the modelName.
by_alias = {m["spec"]["modelName"]: m for m in models.values()}
keys = {k["metadata"]["name"]: (k["spec"].get("models") or [])
        for k in litellm if k["kind"] == "LiteLLMVirtualKey"}
caps_cm = next(c for c in litellm if c["kind"] == "ConfigMap" and c["metadata"]["name"] == "model-caps")
caps = json.loads(caps_cm["data"]["caps.json"])
ok("%d LiteLLMModel aliases, %d virtual keys, %d curated caps entries"
   % (len(models), len(keys), len(caps)))

# ---- 1. Hermes ----------------------------------------------------------------
cfg = (HERMES / "configure.py").read_text()
try:
    compile(cfg, "configure.py", "exec")
    ok("hermes configure.py compiles (%d B)" % len(cfg))
except SyntaxError as e:
    bad("hermes configure.py does not compile: %s" % e)

boot = (HERMES / "provider-bootstrap.yaml").read_text()
spec = importlib.util.spec_from_file_location("gb", HERMES / "gen-bundle.py")
gb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gb)
if gb.render_configure_configmap() == boot:
    ok("provider-bootstrap.yaml is gen-bundle.py's render of configure.py, byte for byte")
else:
    bad("provider-bootstrap.yaml is NOT the current render of configure.py - run gen-bundle.py")

hr = (HERMES / "helmrelease.yaml").read_text()
annot = re.search(re.escape(gb.ANNOT) + r': "([0-9a-f]+)"', hr).group(1)
want_tail = hashlib.sha256((HERMES / "configure.py").read_bytes()).hexdigest()
if annot.endswith(want_tail):
    ok("helmrelease %s second half == sha256(configure.py): %s...%s"
       % (gb.ANNOT, annot[:12], annot[-12:]))
else:
    bad("helmrelease bundle-sha256 tail %s != sha256(configure.py) %s - the pod would not roll "
        "for this configure.py change" % (annot[-16:], want_tail[-16:]))

# Every alias configure.py registers must exist, and be scoped on the hermes key.
pairs = re.findall(r'"([a-z0-9-]+)": \{\n\s+"model": "([^"]+)",\n\s+"provider": "custom:litellm-chat"', cfg)
for alias, model in pairs:
    if model not in models:
        bad("hermes alias %r -> %r, which is not a LiteLLMModel" % (alias, model))
    elif model not in keys.get("hermes", []):
        bad("hermes alias %r -> %r is not on the `hermes` key scope" % (alias, model))
if pairs:
    ok("hermes aliases %s all resolve to scoped LiteLLMModel aliases"
       % ", ".join("%s->%s" % p for p in pairs))
overrides = re.search(r'"reasoning_overrides":\s*\{(.*?)\}', cfg, re.S)
over_models = set(re.findall(r'"([a-z0-9/@.-]+)":\s*(?:\{|")', overrides.group(1))) if overrides else set()
deleuze = {m for _, m in pairs if m.endswith("-deleuze")} - {"flashnext-deleuze"}
if over_models & deleuze:
    bad("reasoning_overrides names %s, which publish no named effort level" % sorted(over_models & deleuze))
else:
    ok("no reasoning_override for the always-thinking radiance entries %s (they publish no level)"
       % sorted(deleuze))
vision = re.search(r'aux\["vision"\]\s*=\s*\{[^}]*"model":\s*"([^"]+)"', cfg)
if vision and vision.group(1) in models:
    v = models[vision.group(1)]["spec"].get("info", {}).get("supportsVision")
    (ok if v else bad)("auxiliary.vision pins %s, whose supportsVision is %s"
                       % (vision.group(1), v))

# ---- 2/3. OpenCode consumer files ---------------------------------------------
def configmap_json(path, key):
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    for d in docs:
        if d.get("kind") == "ConfigMap" and key in (d.get("data") or {}):
            raw = d["data"][key]
            try:
                return json.loads(raw), d
            except json.JSONDecodeError as e:
                bad("%s: %s is not valid JSON (%s)" % (path.name, key, e))
                return None, d
    bad("%s has no ConfigMap key %s" % (path.name, key))
    return None, d


oc, _ = configmap_json(OPENCODE / "opencode-config.yaml", "opencode.json")
pc, _ = configmap_json(OPENCODE / "paseo-config.yaml", "config.json")

if oc:
    provs = (oc.get("providers") or {})
    cogito = (provs.get("cogito") or {}).get("models") or {}
    scope = set(keys.get("opencode", []))
    for name, m in cogito.items():
        mid = m.get("modelID")
        if mid not in by_alias:
            bad("opencode-config %s.modelID %r is not a LiteLLMModel" % (name, mid))
            continue
        info = by_alias[mid]["spec"].get("info", {})
        lim = m.get("limit", {})
        for field, want in (("context", info.get("maxInputTokens")),
                            ("output", info.get("maxOutputTokens"))):
            if lim.get(field) != want:
                bad("opencode-config %s limit.%s=%s but %s advertises %s"
                    % (name, field, lim.get(field), mid, want))
        imgs = "image" in (m.get("capabilities", {}).get("input") or [])
        if imgs != bool(info.get("supportsVision")):
            bad("opencode-config %s advertises image input=%s while %s sets supportsVision=%s"
                % (name, imgs, mid, info.get("supportsVision")))
        effort = (m.get("capabilities", {}).get("reasoning") or {}).get("effort") or []
        ladder = (caps.get(mid) or {}).get("supported_efforts")
        if ladder is not None and set(effort) - set(ladder):
            bad("opencode-config %s offers efforts %s, outside %s's caps ladder %s"
                % (name, sorted(set(effort) - set(ladder)), mid, ladder))
        if effort and ladder is None:
            bad("opencode-config %s offers an effort ladder for %s, which has no curated caps entry"
                % (name, mid))
    ok("opencode-config cogito models %s: modelIDs resolve, limits mirror maxInput/OutputTokens, "
       "image matches supportsVision, efforts stay inside curated caps"
       % sorted(cogito))
    missing = scope - {v.get("modelID") for v in cogito.values()}
    if missing:
        bad("the `opencode` key scope offers %s which opencode-config does not declare"
            % sorted(missing))
    else:
        ok("the `opencode` key scope and opencode-config's cogito block offer the same %d models"
           % len(scope))

if pc:
    lists = {}
    for pname, p in ((pc.get("agents") or {}).get("providers", {}).items()):
        if isinstance(p, dict) and p.get("models"):
            lists[pname] = [m["id"] for m in p["models"]]
    for pname, ids in lists.items():
        for i in ids:
            if not i.startswith("cogito/"):
                continue
            alias = i.split("/", 1)[1]
            target = (alias if alias in by_alias else
                      (models[alias]["spec"]["modelName"] if alias in models else None))
            if target is None:
                bad("paseo-config %s lists %s, which is not a LiteLLMModel" % (pname, i))
            elif target not in keys.get("opencode", []):
                bad("paseo-config %s lists %s, not on the `opencode` key scope" % (pname, i))
    ok("paseo-config provider model rows %s all resolve to aliases on the `opencode` key"
       % {k: len(v) for k, v in lists.items()})
    if len({tuple(v) for v in lists.values()}) == 1:
        ok("the opencode and opencode-worker model lists are identical (worker extends opencode)")
    else:
        bad("the two paseo provider model lists disagree: %s" % lists)
    for pname, p in ((pc.get("agents") or {}).get("providers", {}) or {}).items():
        for prof in (p or {}).get("profiles", []) if isinstance(p, dict) else []:
            if prof.get("model", "").startswith("cogito/") and \
               prof["model"].split("/", 1)[1] not in set(by_alias) | set(models):
                bad("paseo profile %r uses %s, not a LiteLLMModel" % (prof.get("id"), prof["model"]))

print("\nRESULT:", "FAILURES: %d" % len(fails) if fails else "consumer files agree with the catalogue")
sys.exit(1 if fails else 0)
