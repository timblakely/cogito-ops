"""Offline client-contract guards for the prepared GLM-5.3-Flash route.

Tool support reflects the publisher/backend declaration, not a successful local
tool round trip. These tests do not load the model or verify streaming/context
admission. Unknown output limits and reasoning controls must remain undeclared.
"""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"
HERMES = ROOT / "kubernetes/apps/llm/hermes/app"
ALIAS = "glm-deleuze"
MODEL_REF = f"cogito/{ALIAS}"


def embedded(filename, key):
    return json.loads(yaml.safe_load((APP / filename).read_text())["data"][key])


def configure_hermes(existing=None):
    """Run the real reconciler against scratch paths, never the persistent home."""
    source = (HERMES / "configure.py").read_text()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        destination = root / "config.yaml"
        if existing is not None:
            destination.write_text(yaml.safe_dump(existing))
        for old, new in (
            ('Path("/opt/data/config.yaml")', f"Path({str(destination)!r})"),
            ('Path("/bundle")', f"Path({str(root / 'absent-bundle')!r})"),
        ):
            if source.count(old) != 1:
                raise AssertionError(f"Hermes scratch-path substitution drift: {old}")
            source = source.replace(old, new)
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, str(HERMES / "configure.py"), "exec"), {})
        result = yaml.safe_load(destination.read_text())
        mode = destination.stat().st_mode & 0o777
    return result, mode


class GlmClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.opencode = embedded("opencode-config.yaml", "opencode.json")
        cls.paseo = embedded("paseo-config.yaml", "config.json")
        cls.glm = cls.opencode["providers"]["cogito"]["models"][ALIAS]

    def test_exact_chat_alias_and_known_capabilities_only(self):
        self.assertEqual(self.glm["modelID"], ALIAS)
        self.assertEqual(self.glm["capabilities"], {
            "tools": True, "input": ["text"], "output": ["text"],
        })
        self.assertEqual(self.glm["limit"], {"context": 262144})
        # No settings/body/variants can silently send an unverified effort or
        # budget. No reasoning object asserts an unverified control.
        self.assertEqual(set(self.glm), {"modelID", "name", "capabilities", "limit"})
        chat = self.opencode["providers"]["cogito"]
        self.assertEqual(chat["package"], "@opencode/ai/providers/openai-compatible")
        self.assertNotIn(ALIAS, self.opencode["providers"]["cogito-sub"]["models"])

    def test_backend_declarations_match_without_claiming_runtime_verification(self):
        backend = yaml.safe_load((ROOT / (
            "kubernetes/apps/llm/litellm/app/models/glm-deleuze.yaml"
        )).read_text())["spec"]
        self.assertEqual(backend["modelName"], self.glm["modelID"])
        self.assertEqual(backend["params"]["model"], "openai/glm-5.3-flash")
        info = backend["info"]
        self.assertEqual(info["maxInputTokens"], self.glm["limit"]["context"])
        self.assertEqual(info["supportsFunctionCalling"], self.glm["capabilities"]["tools"])
        self.assertFalse(info["supportsVision"])
        self.assertNotIn("maxOutputTokens", info)

    def test_both_paseo_catalogs_add_one_nondefault_row_without_thinking_options(self):
        providers = self.paseo["agents"]["providers"]
        for provider_id in ("opencode", "opencode-worker"):
            with self.subTest(provider=provider_id):
                rows = [m for m in providers[provider_id]["models"] if m["id"] == MODEL_REF]
                self.assertEqual(rows, [{
                    "id": MODEL_REF, "label": ALIAS,
                    "isDefault": False, "thinkingOptions": [],
                }])
                defaults = [m["id"] for m in providers[provider_id]["models"]
                            if m.get("isDefault")]
                self.assertEqual(defaults, ["cogito/flashnext-deleuze"])

    def test_defaults_profiles_and_worker_isolation_stay_pinned(self):
        self.assertEqual(self.opencode["model"], "cogito/flashnext-deleuze")
        providers = self.paseo["agents"]["providers"]
        self.assertEqual(providers["opencode"]["env"], {
            "PASEO_OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
        })
        worker = providers["opencode-worker"]
        self.assertEqual(worker["extends"], "opencode")
        self.assertEqual(worker["paseoTools"], {"enabled": False})
        # Preserve runtime inheritance: do not introduce custom environment or
        # MCP servers that would force a dedicated service for this catalog row.
        for key in ("env", "mcpServers", "disallowedTools"):
            self.assertNotIn(key, worker)
        self.assertEqual(
            [(p["id"], p["provider"], p["model"])
             for p in self.paseo["daemon"]["agentProfiles"]],
            [("lead", "opencode", "cogito/flashnext-deleuze"),
             ("worker", "opencode-worker", "cogito/flashnext-deleuze")],
        )

    def test_hermes_shortcut_on_fresh_home(self):
        config, mode = configure_hermes()
        self.assertEqual(config["model_aliases"]["glm"], {
            "model": ALIAS, "provider": "custom:litellm-chat",
            "base_url": "http://litellm.llm.svc.cluster.local:4000/v1",
        })
        self.assertNotIn(ALIAS, config["agent"]["reasoning_overrides"])
        self.assertEqual(config["providers"]["litellm-chat"]["default_model"], "flashnext-deleuze")
        self.assertTrue(config["providers"]["litellm-chat"]["discover_models"])
        self.assertEqual(config["model"]["default"], "flashnext-deleuze")
        for slot, selection in config["auxiliary"].items():
            with self.subTest(slot=slot):
                self.assertEqual(selection["model"],
                                 "heretic-deleuze" if slot == "vision" else "flashnext-deleuze")
                self.assertEqual(selection["provider"], "litellm-chat")
        self.assertEqual(mode, 0o600)

    def test_hermes_existing_home_preserves_unmanaged_aliases_and_providers(self):
        existing = {
            "model_aliases": {"personal": {"model": "personal-model"}},
            "providers": {"personal": {"api": "https://example.invalid/v1"}},
            "custom_setting": {"keep": True},
        }
        config, _ = configure_hermes(existing)
        fresh, _ = configure_hermes()
        self.assertEqual(config["model_aliases"]["glm"], fresh["model_aliases"]["glm"])
        self.assertEqual(config["model_aliases"]["personal"], existing["model_aliases"]["personal"])
        self.assertEqual(config["providers"]["personal"], existing["providers"]["personal"])
        self.assertEqual(config["custom_setting"], existing["custom_setting"])

    def test_hermes_generated_bootstrap_and_rollout_digest_are_current(self):
        result = subprocess.run(
            [sys.executable, str(HERMES / "gen-bundle.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bootstrap = yaml.safe_load((HERMES / "provider-bootstrap.yaml").read_text())
        self.assertEqual(bootstrap["data"]["configure.py"], (HERMES / "configure.py").read_text())


if __name__ == "__main__":
    unittest.main()
