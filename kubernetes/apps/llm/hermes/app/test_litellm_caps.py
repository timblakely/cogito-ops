#!/usr/bin/env python3
"""Focused wire-form tests for the litellm-caps plugin's reasoning handling.

Loads the in-repo plugin file by path (not via the Hermes loader) with its
Hermes internals stubbed: ``agent.reasoning_effort``, ``providers``, and the
bundled ``plugins.model_providers.custom`` profile. The stub bundled profile
implements a minimal documented-style wire policy - echo the requested effort
on the wire unless the config is explicitly disabled - so the assertions cover
the plugin's own decisions (preserve / pop / clamp / set), which is what this
task needs. It does NOT test upstream Hermes' real bundled profile.

Run from the repository root:

    python3 kubernetes/apps/llm/hermes/app/test_litellm_caps.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import importlib.util

PLUGIN_DIR = (
    Path(__file__).resolve().parent
    / "agent-bundle"
    / "plugins"
    / "model-providers"
    / "litellm-caps"
)

EXPECTED_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
INKLING_CAPS = {
    "supports_reasoning": True,
    "supported_efforts": list(EXPECTED_LEVELS),
    "mandatory": True,
}
# A binary-ish ladder, to prove the "none is not always a minimum effort" rule.
NO_NONE_CAPS = {
    "supports_reasoning": True,
    "supported_efforts": ["low", "medium", "high", "xhigh", "max"],
    "mandatory": False,
}

# ---------------------------------------------------------------------------
# Hermes internals stub.


def _install_stubs():
    agent = types.ModuleType("agent")
    agent.__path__ = []
    reasoning_effort = types.ModuleType("agent.reasoning_effort")

    def clamp_effort(requested, allowed):
        # Honest stand-in: no nearest-effort guessing - the plugin falls back
        # to its own enabled_set[0] when this returns None.
        return None

    reasoning_effort.OPENAI_COMPAT_WIRE_EFFORTS = tuple(EXPECTED_LEVELS)
    reasoning_effort.clamp_effort = clamp_effort
    agent.reasoning_effort = reasoning_effort

    providers = types.ModuleType("providers")
    providers.__path__ = []

    def register_provider(*_args, **_kwargs):
        return None

    providers.register_provider = register_provider
    providers_base = types.ModuleType("providers.base")

    class ProviderProfile:
        def __init__(self, *args, **kwargs):
            pass

    providers_base.ProviderProfile = ProviderProfile
    providers.base = providers_base

    plugins = types.ModuleType("plugins")
    plugins.__path__ = []
    model_providers = types.ModuleType("plugins.model_providers")
    model_providers.__path__ = []

    custom = types.ModuleType("plugins.model_providers.custom")

    class CustomProfile(ProviderProfile):
        """Minimal bundled-style policy: echo the requested effort."""

        def supported_reasoning_efforts(self, model):
            return tuple(EXPECTED_LEVELS)

        def build_api_kwargs_extras(self, *, reasoning_config=None, **ctx):
            top = {}
            config = reasoning_config or {}
            enabled = config.get("enabled", True)
            effort = (config.get("effort") or "").strip().lower()
            if enabled is False:
                return ({}, top)
            if effort:
                top["reasoning_effort"] = effort
            return ({}, top)

    custom.CustomProfile = CustomProfile
    plugins.model_providers = model_providers
    model_providers.custom = custom

    for name, module in {
        "agent": agent,
        "agent.reasoning_effort": reasoning_effort,
        "providers": providers,
        "providers.base": providers_base,
        "plugins": plugins,
        "plugins.model_providers": model_providers,
        "plugins.model_providers.custom": custom,
    }.items():
        sys.modules[name] = module


def _load_plugin():
    with patch.dict(sys.modules):
        _install_stubs()
        init = PLUGIN_DIR / "__init__.py"
        spec = importlib.util.spec_from_file_location("litellm_caps_test", init)
        module = importlib.util.module_from_spec(spec)
        sys.modules["litellm_caps_test"] = module
        spec.loader.exec_module(module)
    return module


_MODULE = _load_plugin()


def _profile(caps, providers=None):
    """A LiteLLMCapsProfile with the caps source stubbed out."""
    cls = _MODULE.LiteLLMCapsProfile
    _MODULE._caps_for_model = lambda model, base_url="": caps
    _MODULE._openai_compat_providers = lambda: providers or []
    return cls(name="custom", aliases=(), env_vars=(), base_url="")


def wire(profile, reasoning_config, model="inkling-deleuze"):
    extra_body, top_level = profile.build_api_kwargs_extras(
        reasoning_config=reasoning_config, model=model, base_url="http://stub/v1"
    )
    return top_level.get("reasoning_effort")


class WireFormTests(unittest.TestCase):
    def test_deployed_bundle_matches_plugin_source(self):
        subprocess.run(
            [sys.executable, str(PLUGIN_DIR.parents[3] / "gen-bundle.py"), "--check"],
            check=True, capture_output=True, text=True,
        )

    def test_supported_efforts_is_the_full_ladder(self):
        profile = _profile(INKLING_CAPS)
        self.assertEqual(
            profile.supported_reasoning_efforts("inkling-deleuze"),
            tuple(EXPECTED_LEVELS),
        )
        self.assertEqual(
            profile.supported_reasoning_efforts("Inkling-Deleuze"),
            tuple(EXPECTED_LEVELS),  # plugin resolves case-insensitively
        )

    def test_every_level_is_forwarded_verbatim(self):
        profile = _profile(INKLING_CAPS)
        for level in EXPECTED_LEVELS:
            with self.subTest(level=level):
                got = wire(profile, {"effort": level})
                self.assertEqual(got, level)

    def test_none_is_preserved_not_omitted(self):
        # The ladder contains "none" as a minimum effort: an explicit disable
        # must not be the reason a level is dropped, and an explicit "none"
        # must ride the wire.
        profile = _profile(INKLING_CAPS)
        self.assertEqual(wire(profile, {"effort": "none"}), "none")
        self.assertEqual(wire(profile, {"effort": "None"}), "none")
        self.assertEqual(
            wire(profile, {"enabled": False, "effort": "high"}), "none"
        )

    def test_max_is_forwarded_as_max_not_xhigh(self):
        # Max is an alias of xhigh at the template level, but the wire form
        # must carry the requested name and nothing should collapse it.
        profile = _profile(INKLING_CAPS)
        self.assertEqual(wire(profile, {"effort": "max"}), "max")
        self.assertEqual(wire(profile, {"effort": "xhigh"}), "xhigh")

    def test_disabled_request_without_none_is_dropped(self):
        profile = _profile(NO_NONE_CAPS)
        self.assertIsNone(wire(profile, {"effort": "none"}))
        self.assertIsNone(wire(profile, {"enabled": False, "effort": "high"}))

    def test_unlisted_effort_is_clamped_inside_the_ladder(self):
        profile = _profile(INKLING_CAPS)
        got = wire(profile, {"effort": "quantum-loop"})
        self.assertIn(got, EXPECTED_LEVELS[1:])  # never "none" via clamp
        self.assertNotEqual(got, "quantum-loop")

    def test_no_request_leaves_bundled_wire_policy_intact(self):
        profile = _profile(INKLING_CAPS)
        self.assertEqual(wire(profile, {"enabled": True}), None)
        self.assertEqual(wire(profile, {"effort": ""}), None)

    def test_caps_unsupported_drops_effort(self):
        caps = {"supports_reasoning": False}
        profile = _profile(caps)
        self.assertIsNone(wire(profile, {"effort": "high"}))
        self.assertEqual(profile.supported_reasoning_efforts("inkling-deleuze"), ())

    def test_unknown_ladder_stays_unknown(self):
        caps = {"supports_reasoning": True, "supported_efforts": None}
        profile = _profile(caps)
        self.assertIsNone(profile.supported_reasoning_efforts("inkling-deleuze"))
        # build_api_kwargs_extras: binary ladder passes the bundled wire through
        # because nothing can honestly be said about the level set.
        self.assertEqual(wire(profile, {"effort": "high"}), "high")

    def test_unknown_model_reports_unknown_not_widest(self):
        provider_entry = {
            "base_url": "http://stub/v1",
            "models": ("inkling-deleuze",),
            "caps_url": "http://stub/caps",
            "caps_managed": True,
        }
        profile = _profile(None, providers=[provider_entry])
        self.assertIsNone(profile.supported_reasoning_efforts("inkling-deleuze"))

    def test_unattributed_model_falls_back_to_bundled(self):
        profile = _profile(None, providers=[])
        self.assertEqual(
            profile.supported_reasoning_efforts("unrelated-custom"),
            tuple(EXPECTED_LEVELS),  # the stub bundled profile's wide vocabulary
        )

    def test_response_shape_only_reasoning_effort_rides_top_level(self):
        # The wire contract: reasoning_effort is top-level; nothing else leaks.
        profile = _profile(INKLING_CAPS)
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config={"effort": "medium"},
            model="inkling-deleuze",
            base_url="http://stub/v1",
        )
        self.assertEqual(top_level, {"reasoning_effort": "medium"})
        self.assertEqual(extra_body, {})


if __name__ == "__main__":
    unittest.main()
