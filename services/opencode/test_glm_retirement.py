"""GLM-5.3-Flash retirement guards for the clients.

The GLM-5.3-Flash route was added in 3cc06b9f (2026-11-27) and retired on
2026-11-28 before live acceptance: the OpenCode/Paseo catalogue entries, the
Hermes shortcut and the LiteLLM route are all gone. These tests pin the
negative state and the preserved state around it, so a later edit cannot
quietly reintroduce a half-retired GLM route alongside the surviving
five-alias catalogue.

Historical material - Maya-M trial artifacts, archive docs and plans/ -
is intentionally out of scope and stays in the tree as history.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"
HERMES = ROOT / "kubernetes/apps/llm/hermes/app"

FIVE_ALIASES = ["flashnext-deleuze", "glimmer-deleuze", "heretic-deleuze",
                "inkling-deleuze", "gemma-4-12b"]
FIVE_SHORTCUTS = ["glimmer", "heretic", "inkling"]


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


class GlmRetirementGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.opencode = embedded("opencode-config.yaml", "opencode.json")
        cls.paseo = embedded("paseo-config.yaml", "config.json")

    def test_opencode_catalogue_carries_exactly_the_five_aliases(self):
        chat = self.opencode["providers"]["cogito"]
        self.assertEqual(list(chat["models"]), FIVE_ALIASES)
        self.assertEqual(self.opencode["model"], "cogito/flashnext-deleuze")
        self.assertEqual(chat["package"], "@opencode/ai/providers/openai-compatible")
        self.assertNotIn("glm", json.dumps(self.opencode).lower())

    def test_paseo_catalogue_carries_no_glm_row(self):
        providers = self.paseo["agents"]["providers"]
        for provider_id in ("opencode", "opencode-worker"):
            with self.subTest(provider=provider_id):
                for model in providers[provider_id]["models"]:
                    self.assertNotIn("glm", model["id"].lower())
                defaults = [m["id"] for m in providers[provider_id]["models"]
                            if m.get("isDefault")]
                self.assertEqual(defaults, ["cogito/flashnext-deleuze"])
        # The worker still derives from the lead, so it inherits the same
        # catalogue minus OpenCode's own tool row.
        self.assertEqual(providers["opencode-worker"]["extends"], "opencode")
        self.assertEqual(providers["opencode-worker"]["paseoTools"],
                         {"enabled": False})

    def test_hermes_shortcut_is_gone_but_preserved_state_survives(self):
        config, mode = configure_hermes()
        self.assertNotIn("glm", config.get("model_aliases", {}))
        self.assertEqual(list(config["model_aliases"]), FIVE_SHORTCUTS)
        self.assertEqual(config["model"]["default"], "flashnext-deleuze")
        chat = config["providers"]["litellm-chat"]
        self.assertEqual(chat["default_model"], "flashnext-deleuze")
        self.assertTrue(chat["discover_models"])
        for slot, selection in config["auxiliary"].items():
            with self.subTest(slot=slot):
                self.assertEqual(selection["provider"], "litellm-chat")
        self.assertEqual(mode, 0o600)

    def test_hermes_existing_home_still_unmanaged(self):
        existing = {
            "model_aliases": {"personal": {"model": "personal-model"}},
            "providers": {"personal": {"api": "https://example.invalid/v1"}},
            "custom_setting": {"keep": True},
        }
        config, _ = configure_hermes(existing)
        self.assertNotIn("glm", config["model_aliases"])
        self.assertEqual(config["model_aliases"]["personal"],
                         existing["model_aliases"]["personal"])
        self.assertEqual(config["custom_setting"], existing["custom_setting"])

    def test_hermes_removes_managed_glm_alias_from_existing_home(self):
        # A config written before the retirement still carries the managed
        # glm record; the reconciler must drop exactly that record. Personal
        # aliases, providers and settings beside it are untouched.
        managed_glm = {
            "model": "glm-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": "http://litellm.llm.svc.cluster.local:4000/v1",
        }
        existing = {
            "model_aliases": {
                "glm": dict(managed_glm),
                "personal": {"model": "personal-model"},
            },
            "providers": {"personal": {"api": "https://example.invalid/v1"}},
            "custom_setting": {"keep": True},
        }
        config, _ = configure_hermes(existing)
        self.assertNotIn("glm", config["model_aliases"])
        self.assertEqual(config["model_aliases"]["personal"],
                         existing["model_aliases"]["personal"])
        self.assertEqual(config["custom_setting"], existing["custom_setting"])
        self.assertEqual(config["providers"]["personal"],
                         existing["providers"]["personal"])

    def test_hermes_keeps_user_modified_glm_alias(self):
        # An alias named glm that the user changed on purpose is personal,
        # not managed, so the retirement must not delete it.
        user_glm = {
            "model": "glimmer-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": "http://example.invalid/v1",
        }
        existing = {
            "model_aliases": {
                "glm": dict(user_glm),
                "personal": {"model": "personal-model"},
            },
        }
        config, _ = configure_hermes(existing)
        self.assertEqual(config["model_aliases"]["glm"], user_glm)
        self.assertEqual(config["model_aliases"]["personal"],
                         existing["model_aliases"]["personal"])

    def test_hermes_removes_only_exact_managed_glm_shape(self):
        # A glm entry with a one-field drift from the managed record is also
        # treated as user-owned, never as managed.
        grown = {
            "model": "glm-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": "http://litellm.llm.svc.cluster.local:4000/v1",
            "extra_flag": True,
        }
        existing = {"model_aliases": {"glm": dict(grown)}}
        config, _ = configure_hermes(existing)
        self.assertEqual(config["model_aliases"]["glm"], grown)

    def test_docs_are_clean_of_the_retired_route(self):
        for rel in ("services/opencode/README.md",
                    "kubernetes/apps/llm/hermes/README.md"):
            self.assertNotIn("glm", (ROOT / rel).read_text().lower(), rel)

    def test_generated_bundle_stays_current(self):
        result = subprocess.run(
            [sys.executable, str(HERMES / "gen-bundle.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bootstrap = yaml.safe_load((HERMES / "provider-bootstrap.yaml").read_text())
        self.assertEqual(bootstrap["data"]["configure.py"],
                         (HERMES / "configure.py").read_text())
        # The retirement must not silently become a registration again. The
        # file legitimately names the retired record as the removal sentinel;
        # an active `"glm": {...}` alias entry would mean we only half-retired.
        source = bootstrap["data"]["configure.py"]
        self.assertNotIn('"glm": {', source)
        self.assertNotIn('"glm":{', source)
        self.assertIn("managed_glm = {", source)


if __name__ == "__main__":
    unittest.main()
