"""caps.py — reasoning-capability cache shared by the litellm-caps plugin and its CLI.

Reads a LiteLLM-style ``/v1/models`` document whose entries carry OpenRouter-schema
reasoning metadata (published by the model-caps-annotator sidecar)::

    {"id": "Muse-Glimmer-30B", ..., "supported_parameters": [..., "reasoning"],
     "reasoning": {"supported_efforts": ["low", "medium"], "mandatory": false}}

Tri-state per model (mirrors hermes_cli/models_reasoning_caps.py, kept local so the
plugin survives internal refactors of that module):
  {"supports_reasoning": True,  "supported_efforts": [...] | None, "mandatory": bool}
  {"supports_reasoning": False}                                   -- definitive negative
  None                                                             -- unknown

Cache policy: memory for the process lifetime; a disk mirror under the active Hermes
home survives cold starts and short-lived CLI processes; HTTP never runs on the
request hot path (callers get cache-only answers, warming is background).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DISK_TTL_SECONDS = 24 * 3600
_FETCH_FAILURE_SUPPRESS_SECONDS = 60
_USER_AGENT = "hermes-litellm-caps-plugin/1"

# base_url -> {"ts": float, "caps": {model_id: caps-dict}}
_memory: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_warm_started: set[str] = set()


def _disk_path() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "cache" / "litellm_caps.json"
    except Exception:
        return Path.home() / ".hermes" / "cache" / "litellm_caps.json"


def parse_reasoning_caps(item: Any) -> Optional[dict[str, Any]]:
    """Normalize one catalog entry's reasoning metadata (OpenRouter schema)."""
    if not isinstance(item, dict):
        return None
    params = item.get("supported_parameters")
    if not isinstance(params, list):
        return None  # catalog doesn't speak the schema for this entry: unknown
    if "reasoning" not in params:
        return {"supports_reasoning": False}
    reasoning = item.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {}
    raw = reasoning.get("supported_efforts")
    efforts: Optional[list[str]] = None
    if isinstance(raw, list):
        efforts = list(dict.fromkeys(
            str(e).strip().lower() for e in raw if str(e).strip()))
    return {"supports_reasoning": True, "supported_efforts": efforts,
            "mandatory": reasoning.get("mandatory") is True}


def parse_catalog(items: Any) -> Optional[dict[str, dict[str, Any]]]:
    """Parse a ``/v1/models`` ``data`` array into ``{model_id: caps}``; None if unusable."""
    if not isinstance(items, list):
        return None
    caps_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        mid = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if mid:
            caps_by_id[mid] = parse_reasoning_caps(item)
    return caps_by_id or None


def _read_disk() -> dict[str, Any]:
    try:
        return json.loads(_disk_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_disk(base_url: str, caps: dict[str, dict[str, Any]]) -> None:
    path = _disk_path()
    try:
        data = _read_disk()
        data[base_url] = {"ts": time.time(), "caps": caps}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("litellm-caps: disk mirror write failed: %s", exc)


def _load_disk(base_url: str) -> tuple[Optional[dict[str, Any]], float]:
    entry = _read_disk().get(base_url)
    caps = entry.get("caps") if isinstance(entry, dict) else None
    if not isinstance(caps, dict) or not caps:
        return None, 0.0
    try:
        age = max(0.0, time.time() - float(entry.get("ts") or 0))
    except (TypeError, ValueError):
        age = DISK_TTL_SECONDS
    return caps, age


def fetch(base_url: str, api_key: str = "", timeout: float = 6.0) -> Optional[dict[str, Any]]:
    """One HTTP round-trip to ``<base_url>/models`` -> caps map (None on any failure)."""
    url = base_url.rstrip("/")
    url = url if url.endswith("/models") else url + "/models"
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug("litellm-caps: fetch of %s failed: %s", url, exc)
        return None
    caps = parse_catalog(payload.get("data"))
    if caps is not None:
        with _lock:
            _memory[base_url] = {"ts": time.time(), "caps": caps}
        _write_disk(base_url, caps)
    return caps


def get_caps(base_url: str, model: str) -> Optional[dict[str, Any]]:
    """Cache-only caps for one model: memory, else disk mirror. Never HTTP."""
    if not base_url or not model:
        return None
    with _lock:
        entry = _memory.get(base_url)
    if entry is None:
        caps, age = _load_disk(base_url)
        if caps is None:
            return None
        # Keep the DISK age in the memory entry: stamping load-time here would make
        # an stale mirror look fresh to the TTL-based re-warm forever.
        entry = {"ts": time.time() - age, "caps": caps}
        with _lock:
            _memory[base_url] = entry
    model_caps = entry["caps"].get(model)
    if model_caps is None:
        # LiteLLM serves whatever casing the alias uses; Hermes may spell it differently.
        lowered = {k.lower(): v for k, v in entry["caps"].items()}
        model_caps = lowered.get(model.lower())
    return model_caps


def warm_async(base_url: str, api_key: str = "") -> None:
    """Background-fetch the catalog unless it is fresh in memory or already warming."""
    if not base_url or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _lock:
        if base_url in _warm_started:
            return
        entry = _memory.get(base_url)
        if entry is not None and time.time() - entry["ts"] < DISK_TTL_SECONDS:
            return
        _warm_started.add(base_url)

    def _run():
        try:
            if fetch(base_url, api_key) is None:
                # Remember the failure briefly so a dead endpoint doesn't re-storm,
                # but allow a retry in a long-lived process instead of giving up forever.
                with _lock:
                    _warm_started.discard(base_url)
        except Exception:
            with _lock:
                _warm_started.discard(base_url)

    threading.Thread(target=contextvars.copy_context().run, args=(_run,),
                     name="litellm-caps-warm", daemon=True).start()


def caps_age_seconds(base_url: str) -> Optional[float]:
    with _lock:
        entry = _memory.get(base_url)
    if entry is None:
        _caps, age = _load_disk(base_url)
        return age if _caps is not None else None
    return time.time() - entry["ts"]
