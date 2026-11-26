"""Paseo's replacement catalogue must retain OpenCode's thinking variants.

Both provider entries are asserted: `opencode` (the lead, which carries Paseo's
own tools) and `opencode-worker` (the worker entry, whose whole point is that it
carries none). `models` is not inherited through `extends`, so a worker that
launched with an incomplete list would silently advertise OpenCode's bundled
free tier -- model names that exist nowhere in this repo -- which is the guard
this file exists to hold. The catalog is withheld from the worker by naming every
tool in `paseoTools.disabledTools` rather than switching `enabled` off, for the
reason recorded on the test below.
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

# The part of Paseo's catalog a worker must never hold directly: fleet control
# (launching agents, workspaces and scheduled work elsewhere on this host) and
# the shell (terminals and approving another agent's permissions). The config
# blocks the full catalog; this list pins the names whose absence matters most.
WITHHELD_FROM_WORKERS = (
    "create_agent",
    "send_agent_prompt",
    "cancel_agent",
    "kill_agent",
    "archive_agent",
    "create_workspace",
    "create_terminal",
    "send_terminal_keys",
    "kill_terminal",
    "respond_to_permission",
    "create_schedule",
    "create_heartbeat",
)


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
        """paseoTools is read per provider id, so only a provider split works.

        The switch has to be ``disabledTools``, never ``enabled: false``. Paseo
        strips its internal ``paseo`` MCP server from a launch only while native
        tools are in use, and ``isPaseoToolPolicyEnabled`` is
        ``policy?.enabled !== false``, so a disabled policy leaves the launch
        asking for a dedicated OpenCode server. Measured on this host, where the
        OpenCode service is shared, create_agent then fails before a session
        starts: "Custom OpenCode MCP servers or process environment require an
        isolated server and cannot be used with a shared OpenCode service."
        """
        paseo = embedded_config("paseo-config.yaml", "config.json")
        providers = paseo["agents"]["providers"]
        worker = providers["opencode-worker"]
        self.assertEqual(worker["extends"], "opencode")
        # ProviderOverridesSchema rejects a custom provider without a label.
        self.assertTrue(worker["label"].strip())
        policy = worker["paseoTools"]
        self.assertIsNot(policy.get("enabled", True), False)
        blocked = policy["disabledTools"]
        self.assertEqual(len(blocked), len(set(blocked)))
        self.assertTrue(all(isinstance(name, str) and name.strip() for name in blocked))
        # A name is only blocked because it is named, so the list has to cover
        # the live catalog; pin the parts that must never reach a worker and a
        # floor so a careless trim fails here. Paseo upgrades add tools, so
        # re-check this against the daemon's tools/list when bumping the image.
        self.assertGreaterEqual(len(blocked), 40)
        for name in WITHHELD_FROM_WORKERS:
            self.assertIn(name, blocked)
        # The lead keeps Paseo's tools: absent means enabled, so the worker must
        # be the only entry that names a blocked tool.
        for provider_id in CATALOG_PROVIDERS:
            with self.subTest(provider=provider_id):
                tools = providers[provider_id].get("paseoTools", {})
                self.assertEqual(
                    bool(tools.get("disabledTools")), provider_id == "opencode-worker"
                )

    def test_worker_profile_launches_the_provider_that_blocks_the_catalog(self):
        """A profile pointing at the wrong provider would silently re-inject."""
        paseo = embedded_config("paseo-config.yaml", "config.json")
        providers = paseo["agents"]["providers"]
        profiles = {p["id"]: p for p in paseo["daemon"]["agentProfiles"]}
        blocked = [
            pid
            for pid, provider in providers.items()
            if provider.get("paseoTools", {}).get("disabledTools")
        ]
        self.assertEqual(profiles["worker"]["provider"], "opencode-worker")
        self.assertEqual(blocked, [profiles["worker"]["provider"]])
        self.assertFalse(
            providers[profiles["lead"]["provider"]].get("paseoTools", {}).get(
                "disabledTools"
            )
        )

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
                # Only the worker entry blocks Paseo's tools -- and it blocks
                # them by name, because `enabled: false` moves the launch off
                # the native-tools path onto a dedicated OpenCode server this
                # shared service refuses to start.
                policy = providers[profile["provider"]].get("paseoTools", {})
                self.assertIsNot(policy.get("enabled", True), False)
                self.assertEqual(
                    bool(policy.get("disabledTools")), profile["id"] == "worker"
                )

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
