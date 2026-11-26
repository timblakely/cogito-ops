"""Paseo's replacement catalogue must retain OpenCode's thinking variants.

Both provider entries are asserted: `opencode` (the lead, which carries Paseo's
own tools) and `opencode-worker` (the worker entry, whose whole point is that it
carries none). `models` is not inherited through `extends`, so a worker that
launched with an incomplete list would silently advertise OpenCode's bundled
free tier -- model names that exist nowhere in this repo -- which is the guard
this file exists to hold.
"""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"

# Every agents.providers entry that can launch a session: the lead entry and
# the worker entry derived from it.
CATALOG_PROVIDERS = ("opencode", "opencode-worker")


def embedded_config(filename, key):
    return json.loads(yaml.safe_load((APP / filename).read_text())["data"][key])


class PaseoCatalogTests(unittest.TestCase):
    def test_managed_genui_and_native_tools_are_enabled_at_fresh_boot(self):
        paseo = embedded_config("paseo-config.yaml", "config.json")
        self.assertTrue(paseo.get("pluginsEnabled", False))
        self.assertTrue(paseo["daemon"]["mcp"]["injectIntoAgents"])
        self.assertEqual(paseo["plugins"]["genui"], {
            "source": "directory",
            "path": "/opt/paseo-genui/node_modules/paseo-plugin-genui",
            "enabled": True,
        })

    def test_replacement_models_preserve_opencode_variants(self):
        opencode = embedded_config("opencode-config.yaml", "opencode.json")
        paseo = embedded_config("paseo-config.yaml", "config.json")
        providers = paseo["agents"]["providers"]
        expected = {
            f"{provider_id}/{model_id}": model
            for provider_id, provider in opencode["providers"].items()
            for model_id, model in provider["models"].items()
        }
        for provider_id in CATALOG_PROVIDERS:
            with self.subTest(provider=provider_id):
                models = providers[provider_id]["models"]
                self.assertEqual(len(models), len(expected))
                self.assertEqual({model["id"] for model in models}, set(expected))
                self.assertEqual(
                    sum(model.get("isDefault", False) for model in models), 1)
                for model in models:
                    with self.subTest(model=model["id"]):
                        # OpenCode v2 generates variants from effort, not toggle
                        # support.
                        efforts = expected[model["id"]]["capabilities"].get(
                            "reasoning", {}).get("effort", [])
                        self.assertIn("thinkingOptions", model)
                        options = model["thinkingOptions"]
                        self.assertEqual([option["id"] for option in options], efforts)
                        self.assertTrue(all(option["label"].strip() for option in options))

    def test_worker_entry_is_the_one_that_drops_the_paseo_catalog(self):
        """paseoTools is read per provider id, so only a provider split works."""
        paseo = embedded_config("paseo-config.yaml", "config.json")
        providers = paseo["agents"]["providers"]
        worker = providers["opencode-worker"]
        self.assertEqual(worker["extends"], "opencode")
        # ProviderOverridesSchema rejects a custom provider without a label.
        self.assertTrue(worker["label"].strip())
        self.assertFalse(worker["paseoTools"]["enabled"])
        # The lead keeps Paseo's tools: absent means enabled, so assert the
        # worker is the only entry that turns them off rather than asserting an
        # explicit `true` the schema never needs.
        for provider_id in CATALOG_PROVIDERS:
            with self.subTest(provider=provider_id):
                enabled = providers[provider_id].get("paseoTools", {}).get("enabled", True)
                self.assertEqual(enabled, provider_id != "opencode-worker")

    def test_agent_profiles_launch_from_declared_providers_and_models(self):
        """Profiles are advisory, so their provider/model must be real strings.

        `daemon.agentProfiles` (not `agents.agentProfiles`) is an array of
        {id, name, provider, model, notes}. The schema is passthrough, so a key
        the daemon ignores -- `extends`, `label` -- would sit here forever
        pretending to do something, and a model the provider does not advertise
        would fail only when someone launches it.
        """
        paseo = embedded_config("paseo-config.yaml", "config.json")
        profiles = paseo["daemon"]["agentProfiles"]
        providers = paseo["agents"]["providers"]
        self.assertEqual([profile["id"] for profile in profiles], ["lead", "worker"])
        for profile in profiles:
            with self.subTest(profile=profile["id"]):
                for key in ("id", "name", "provider", "notes"):
                    self.assertTrue(profile[key].strip(), key)
                self.assertNotIn("extends", profile)
                self.assertIn(profile["provider"], providers)
                self.assertTrue(providers[profile["provider"]]["enabled"])
                advertised = {model["id"] for model in providers[profile["provider"]]["models"]}
                self.assertIn(profile["model"], advertised)
                # Only the worker entry disables Paseo's tools.
                disabled = providers[profile["provider"]].get(
                    "paseoTools", {}).get("enabled", True) is False
                self.assertEqual(disabled, profile["id"] == "worker")

    def test_worker_stays_on_this_host(self):
        """The MCP catalog can only reach this pod while the relay is off.

        list_hosts reports zero destination hosts, so `create_agent` and
        `create_workspace` land here. Enabling the relay (or registering a host)
        would let them run somewhere else.
        """
        paseo = embedded_config("paseo-config.yaml", "config.json")
        self.assertFalse(paseo["daemon"]["relay"]["enabled"])
        self.assertTrue(paseo["daemon"]["mcp"]["enabled"])


if __name__ == "__main__":
    unittest.main()
