#!/usr/bin/env python3
"""Validate the LLM catalogue: every name that must resolve, resolves.

Renders the llm namespace's kustomizations and asserts the cross-references
that fail silently at runtime (plans/llm/plan.md T0.2):

  1. every LiteLLMVirtualKey scope entry names a published modelName
     (a bad scope blocks the key SILENTLY rather than erroring)
  2. every routerSettings fallback / context_window_fallback name resolves
  3. every in-cluster apiBase has a matching backend in the rendered output
  4. maxInputTokens on a LiteLLM entry matches its backend's maxModelLen /
     contextSize (the advertised-context mirror)
  5. the `coordinator` alias carries NO fallback (cache-locality rule)
  6. every alias annotated cogito.dev/preemptible="true" HAS a fallback
  7. fallback targets are the SAME underlying model as their primary, and
     every key's scope contains the fallback closure of its aliases
     (LiteLLM does not re-check key scope on the fallback path)
  8. consumer env vars naming models resolve

Run from the repo root: scripts/validate-llm-catalogue.py
Exits non-zero on any failure. --self-test additionally verifies the checks
fire on a deliberately broken copy.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

import yaml

# core paths: must render cleanly; catalogue and backends live here
RENDER_PATHS = [
    "kubernetes/apps/llm/litellm/app",
    "kubernetes/apps/llm/llmkube/resources",
]
# consumer paths: parsed file-by-file (their kustomizations patch resources
# injected by shared Flux components and cannot build standalone); they only
# feed the env-reference check
RAW_PATHS = [
    "kubernetes/apps/llm/open-webui/app",
    "kubernetes/apps/llm/hermes/app",
]

# env keys whose values are model names (comma-separated allowed)
MODEL_ENV_KEYS = {"DEFAULT_MODELS", "MODEL", "MODELS", "TASK_MODEL",
                  "WIKI_MODEL", "RAG_EMBEDDING_MODEL", "RAG_RERANKING_MODEL"}


def render(paths):
    """kustomize build each path, pre-substituting Flux's ${APP} var the way
    postBuild.substitute would (plain kustomize chokes on it in patch targets).
    Other ${...} vars are left as literal placeholder strings."""
    docs = []
    for p in paths:
        app = Path(p).parent.name  # .../apps/llm/<app>/app -> <app>
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "build"
            shutil.copytree(p, dst)
            for f in dst.rglob("*.yaml"):
                f.write_text(f.read_text().replace("${APP}", app))
            out = subprocess.run(
                ["kustomize", "build", str(dst)], capture_output=True, text=True)
        if out.returncode != 0:
            print(f"FATAL: kustomize build {p}: {out.stderr.strip()}")
            sys.exit(2)
        docs += [d for d in yaml.safe_load_all(out.stdout) if d]
    return docs


def parse_raw(paths):
    docs = []
    for p in paths:
        for f in Path(p).rglob("*.yaml"):
            try:
                docs += [d for d in yaml.safe_load_all(f.read_text()) if d]
            except yaml.YAMLError:
                pass  # templated files; env refs live in parseable manifests
    return docs


def collect(docs):
    state = {"models": {}, "keys": {}, "backends": {}, "proxies": [],
             "routers": set(), "env_refs": []}
    for d in docs:
        kind = d.get("kind")
        spec = d.get("spec", {}) or {}
        meta = d.get("metadata", {}) or {}
        if kind == "LiteLLMModel":
            entry = {
                "cr": meta.get("name"),
                "apiBase": (spec.get("params") or {}).get("apiBase"),
                "underlying": (spec.get("params") or {}).get("model"),
                "maxInputTokens": (spec.get("info") or {}).get("maxInputTokens"),
                "preemptible": (meta.get("annotations") or {}).get(
                    "cogito.dev/preemptible") == "true",
            }
            state["models"].setdefault(spec.get("modelName"), []).append(entry)
        elif kind == "LiteLLMVirtualKey":
            state["keys"][meta.get("name")] = spec.get("models")
        elif kind == "InferenceService":
            vc = spec.get("vllmConfig") or {}
            state["backends"][meta.get("name")] = (
                vc.get("maxModelLen") or spec.get("contextSize"))
        elif kind == "ModelRouter":
            state["routers"].add(f"{meta.get('name')}-router-proxy")
        elif kind == "LiteLLMProxy":
            state["proxies"].append(spec)
        # env-style model references anywhere in the doc
        def walk(node):
            if isinstance(node, dict):
                if set(node) >= {"name", "value"} and node["name"] in MODEL_ENV_KEYS:
                    state["env_refs"].append((node["name"], str(node["value"])))
                for k, v in node.items():
                    if k in MODEL_ENV_KEYS and isinstance(v, str):
                        state["env_refs"].append((k, v))
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(d)
    return state


def fallback_map(proxies):
    fb = {}
    for spec in proxies:
        rs = spec.get("routerSettings") or {}
        for kind in ("fallbacks", "context_window_fallbacks"):
            for item in rs.get(kind) or []:
                for primary, targets in (item or {}).items():
                    fb.setdefault(primary, []).extend(targets or [])
    return fb


def service_of(api_base):
    if not api_base or "svc" not in api_base and ".llm" not in api_base:
        return None
    host = api_base.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host.split(".")[0]


def check(state):
    errors, warnings = [], []
    names = set(state["models"])
    fb = fallback_map(state["proxies"])

    # 1. key scopes resolve
    for key, scope in state["keys"].items():
        for m in scope or []:
            if m not in names:
                errors.append(f"key '{key}' scope names unknown model '{m}'")

    # 2. fallback names resolve
    for primary, targets in fb.items():
        if primary not in names:
            errors.append(f"fallback primary '{primary}' is not a modelName")
        for t in targets:
            if t not in names:
                errors.append(f"fallback target '{t}' (of '{primary}') is not a modelName")

    # 3 + 4. backends exist; context mirror
    known_svcs = set(state["backends"]) | state["routers"] | {"litellm"}
    for name, entries in state["models"].items():
        for e in entries:
            svc = service_of(e["apiBase"])
            if svc is None:
                continue
            if svc not in known_svcs:
                errors.append(
                    f"model '{name}' apiBase names service '{svc}' with no "
                    f"backend in the rendered output")
                continue
            if svc in state["backends"] and e["maxInputTokens"] is not None:
                backend_len = state["backends"][svc]
                if backend_len is not None and e["maxInputTokens"] != backend_len:
                    errors.append(
                        f"model '{name}': maxInputTokens {e['maxInputTokens']} "
                        f"!= backend '{svc}' maxModelLen/contextSize {backend_len}")
            elif svc in state["routers"] and e["maxInputTokens"] is not None:
                warnings.append(
                    f"model '{name}' routes via ModelRouter '{svc}' - context "
                    f"mirror not verifiable against a single backend")

    # 5. coordinator has no fallback
    if "coordinator" in fb:
        errors.append("'coordinator' must not have a fallback entry "
                      "(cache-locality rule)")

    # 6. preemptible-backed aliases need a fallback
    for name, entries in state["models"].items():
        if any(e["preemptible"] for e in entries) and name not in fb:
            errors.append(f"preemptible-backed model '{name}' has no fallback")

    # 7. same-model fallbacks + scope closure
    def underlying(n):
        return {e["underlying"] for e in state["models"].get(n, [])}
    for primary, targets in fb.items():
        for t in targets:
            if t in names and primary in names and not (underlying(primary) & underlying(t)):
                errors.append(
                    f"fallback '{primary}' -> '{t}' crosses models "
                    f"({underlying(primary)} vs {underlying(t)}); fallbacks "
                    f"must be same model, different host")
    for key, scope in state["keys"].items():
        if scope is None:
            continue
        for m in scope:
            for t in fb.get(m, []):
                if t not in scope:
                    errors.append(
                        f"key '{key}' scope holds '{m}' but not its fallback "
                        f"target '{t}' - the fallback path bypasses scope checks")

    # 8. consumer env model refs resolve
    for env_key, value in state["env_refs"]:
        for m in [v.strip() for v in value.split(",") if v.strip()]:
            if m not in names:
                errors.append(f"consumer env {env_key} names unknown model '{m}'")

    return errors, warnings


def main():
    root = Path(__file__).resolve().parent.parent
    docs = render([str(root / p) for p in RENDER_PATHS])
    docs += parse_raw([str(root / p) for p in RAW_PATHS])
    state = collect(docs)
    errors, warnings = check(state)

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"FAIL: {e}")

    if "--self-test" in sys.argv:
        broken = deepcopy(state)
        first_key = next(iter(broken["keys"]))
        broken["keys"][first_key] = (broken["keys"][first_key] or []) + ["no-such-model"]
        st_errors, _ = check(broken)
        if not any("no-such-model" in e for e in st_errors):
            print("FAIL: self-test - broken scope not detected")
            errors.append("self-test")
        else:
            print("self-test: broken scope correctly detected")

    print(f"{len(state['models'])} modelNames, {len(state['keys'])} keys, "
          f"{len(state['backends'])} backends, "
          f"{sum(len(v) for v in fallback_map(state['proxies']).values())} fallback edges")
    if errors:
        print(f"RESULT: {len(errors)} failure(s)")
        sys.exit(1)
    print("RESULT: catalogue valid")


if __name__ == "__main__":
    main()
