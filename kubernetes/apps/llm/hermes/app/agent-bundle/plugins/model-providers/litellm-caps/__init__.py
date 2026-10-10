"""litellm-caps — reasoning-effort honesty for the custom:litellm-* routes.

A ``custom`` OpenAI-compatible profile cannot know a backend's reasoning ladder,
so the bundled CustomProfile answers with the widest OpenAI-compat vocabulary and
every level the route publishes. That is fiction for llama.cpp-backed models
(which accept-and-ignore every per-request effort) and over-promises for
binary-thinking vLLM models (where only on/off exists on the wire).

This user plugin overrides the ``custom`` profile (documented last-writer-wins
registration for ``$HERMES_HOME/plugins/model-providers/``) and answers effort
questions from each endpoint's ``/v1/models`` catalog when it carries
OpenRouter-schema reasoning metadata::

    {"id": "...", "supported_parameters": [..., "reasoning"],
     "reasoning": {"supported_efforts": ["none"], "mandatory": false}}

Cogito publishes that shape at https://litellm.timblakely.com/caps/v1/models via
the model-caps-annotator sidecar; without a caps document every model parses as
unknown and behavior is byte-for-byte the bundled CustomProfile's — this plugin
can only make the wire more honest, never different when it has no data.

Config (optional, per entry in ``providers:``)::

    providers:
      litellm-chat:
        caps_url: https://litellm.timblakely.com/caps/v1/models   # defaults to <base_url>/models

Never performs HTTP on the request hot path: caps resolve from memory / a disk
mirror, and misses kick off a background warm.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Optional
from urllib.parse import urlparse

from agent.reasoning_effort import OPENAI_COMPAT_WIRE_EFFORTS, clamp_effort
from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)


def _load_caps_module():
    """Import ``caps.py`` from this plugin's own directory under any loader scheme."""
    here = os.path.dirname(os.path.abspath(__file__))
    modname = f"{__name__}._caps"
    if modname in sys.modules:
        return sys.modules[modname]
    import importlib.util

    spec = importlib.util.spec_from_file_location(modname, os.path.join(here, "caps.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


_caps = _load_caps_module()

# Provider entries are read rarely and change rarely; one parse per minute.
_providers_ttl = 60.0
_providers_cache: tuple[float, list[dict[str, str]]] = (0.0, [])


def _openai_compat_providers() -> list[dict[str, str]]:
    """[{base_url, key_env, caps_url}] from ``providers:`` / ``custom_providers:`` config."""
    global _providers_cache
    now = time.monotonic()
    if now - _providers_cache[0] < _providers_ttl:
        return _providers_cache[1]
    entries: list[dict[str, str]] = []
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly() or {}
    except Exception:
        cfg = {}
    raw: list[dict[str, Any]] = []
    providers = cfg.get("providers")
    if isinstance(providers, dict):
        raw.extend(p if isinstance(p, dict) else {} for p in providers.values())
    custom = cfg.get("custom_providers")
    if isinstance(custom, list):
        raw.extend(p for p in custom if isinstance(p, dict))
    for entry in raw:
        base_url = str(entry.get("base_url") or "").strip()
        if not base_url or not urlparse(base_url).hostname:
            continue
        caps_url = str(entry.get("caps_url") or "").strip()
        entries.append({
            "base_url": base_url,
            "key_env": str(entry.get("key_env") or "").strip(),
            "caps_url": caps_url or f"{base_url.rstrip('/')}/models",
        })
    _providers_cache = (now, entries)
    return entries


def _api_key_for(key_env: str) -> str:
    if not key_env:
        return ""
    try:
        from hermes_cli.config import get_env_value_prefer_dotenv

        value = get_env_value_prefer_dotenv(key_env)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return (os.environ.get(key_env) or "").strip()


def _caps_for_model(model: str, base_url: str = "") -> Optional[dict[str, Any]]:
    """Cache-only caps lookup across configured endpoints (+ background warm on miss)."""
    if not model:
        return None
    candidates = _openai_compat_providers()
    if base_url:
        base = base_url.rstrip("/")
        candidates = sorted(candidates, key=lambda e: 0 if e["base_url"].rstrip("/") == base else 1)
    for entry in candidates:
        caps = _caps.get_caps(entry["caps_url"], model)
        if caps is not None:
            return caps
    for entry in candidates:
        age = _caps.caps_age_seconds(entry["caps_url"])
        if age is None or age >= _caps.DISK_TTL_SECONDS:
            # Missing entirely, or past TTL (get_caps serves stale deliberately) —
            # re-warm in the background; warm_async itself skips fresh entries.
            _caps.warm_async(entry["caps_url"], _api_key_for(entry["key_env"]))
    return None


def _import_bundled_custom():
    """The bundled CustomProfile, or None when internals moved (then we stand down).

    Order-independent: this plugin can be imported during a discovery re-entry
    (an early bundled plugin pulls in ``hermes_cli.auth``, whose ``list_providers()``
    re-enters the home-layer scan) BEFORE the loader has imported the bundled
    ``custom`` profile, so the plain import is not enough — fall back to loading
    the bundled file from the repo's ``plugins/model-providers/custom/`` next to
    the ``providers`` package. The import registers the bundled profile itself
    (module-level ``register_provider``), and our later registration still wins
    last-writer-wins.
    """
    try:
        from plugins.model_providers.custom import CustomProfile

        return CustomProfile
    except Exception:
        pass
    try:
        import importlib.util
        import sys as _sys

        import providers as _providers

        init = (os.path.dirname(os.path.dirname(os.path.abspath(_providers.__file__)))
                + "/plugins/model-providers/custom/__init__.py")
        spec = importlib.util.spec_from_file_location("plugins.model_providers.custom", init)
        module = importlib.util.module_from_spec(spec)
        _sys.modules.setdefault("plugins.model_providers.custom", module)
        spec.loader.exec_module(module)
        return module.CustomProfile
    except Exception as exc:  # pragma: no cover — defensive against upstream renames
        logger.warning("litellm-caps: cannot import bundled custom profile (%s); standing down", exc)
        return None


_Bundled = _import_bundled_custom()


class LiteLLMCapsProfile(_Bundled if _Bundled is not None else ProviderProfile):
    """``custom`` profile whose reasoning vocabulary comes from the route's catalog.

    Everything except the reasoning-wire decision delegates to the bundled
    CustomProfile, so wire quirks (Ollama think, Groq default, num_ctx) keep
    tracking upstream. If the bundled profile can't be imported this class
    subclasses ProviderProfile and stands down from every override (base-class
    defaults are no-ops), leaving discovery-only traces — never a half-wired
    custom provider.
    """

    _stand_down = _Bundled is None

    @staticmethod
    def _looks_disabled(reasoning_config: dict) -> bool:
        effort = (reasoning_config.get("effort") or "").strip().lower()
        return effort == "none" or reasoning_config.get("enabled", True) is False

    def supported_reasoning_efforts(self, model: str | None) -> tuple[str, ...] | None:
        if self._stand_down:
            return None
        caps = _caps_for_model(str(model or ""))
        if caps is None or not caps.get("supports_reasoning"):
            # Unknown -> bundled widest-vocabulary answer; definitive negative ->
            # the transport contract for "omit reasoning fields entirely".
            if caps is not None and caps.get("supports_reasoning") is False:
                return ()
            return super().supported_reasoning_efforts(model) if not self._stand_down else None
        efforts = caps.get("supported_efforts")
        if efforts is None:
            # Binary thinking route (accepts the field, no graded ladder):
            # report unknown so transports keep their default vocabulary.
            return super().supported_reasoning_efforts(model) if not self._stand_down else None
        return tuple(efforts)

    def build_api_kwargs_extras(self, *, reasoning_config: dict | None = None, **ctx: Any):
        extra_body, top_level = super().build_api_kwargs_extras(reasoning_config=reasoning_config, **ctx)
        if self._stand_down or not isinstance(reasoning_config, dict) or not reasoning_config:
            return extra_body, top_level
        caps = _caps_for_model(str(ctx.get("model") or ""), str(ctx.get("base_url") or ""))
        if caps is None:
            return extra_body, top_level  # no data -> bundled wire policy verbatim
        if not caps.get("supports_reasoning"):
            # The route says this model takes no reasoning parameters at all.
            top_level.pop("reasoning_effort", None)
            extra_body.pop("reasoning", None)
            return extra_body, top_level
        efforts = caps.get("supported_efforts")
        if efforts is None:
            return extra_body, top_level  # binary ladder: bundled clamp-and-send is the honest wire
        allowed = [lvl for lvl in (str(e).strip().lower() for e in efforts) if lvl]
        enabled_set = [lvl for lvl in allowed if lvl != "none"]
        if self._looks_disabled(reasoning_config):
            if "none" not in allowed:
                top_level.pop("reasoning_effort", None)
                extra_body.pop("reasoning", None)
            return extra_body, top_level
        requested = (reasoning_config.get("effort") or "").strip().lower()
        if not requested:
            return extra_body, top_level
        if not enabled_set:
            # On/off-only vocabulary: an enabled request rides the server default.
            top_level.pop("reasoning_effort", None)
            extra_body.pop("reasoning", None)
            return extra_body, top_level
        if requested in enabled_set:
            top_level["reasoning_effort"] = requested
        else:
            top_level["reasoning_effort"] = clamp_effort(requested, tuple(enabled_set)) or enabled_set[0]
        return extra_body, top_level


# Stand-down mode (bundled import failed): registering this would REPLACE the
# bundled profile with no-op defaults. Log once and touch nothing.
if _Bundled is not None:
    register_provider(LiteLLMCapsProfile(
        name="custom",
        aliases=("ollama", "local", "vllm", "llamacpp", "llama.cpp", "llama-cpp"),
        env_vars=(),
        base_url="",
    ))
else:  # pragma: no cover
    logger.warning("litellm-caps: bundled custom profile unavailable; plugin registered nothing")
