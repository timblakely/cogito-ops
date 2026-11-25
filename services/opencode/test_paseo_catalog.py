"""Paseo's replacement catalogue must retain OpenCode's thinking variants."""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"


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
        models = paseo["agents"]["providers"]["opencode"]["models"]
        expected = {
            f"{provider_id}/{model_id}": model
            for provider_id, provider in opencode["providers"].items()
            for model_id, model in provider["models"].items()
        }
        self.assertEqual(len(models), len(expected))
        self.assertEqual({model["id"] for model in models}, set(expected))
        self.assertEqual(sum(model.get("isDefault", False) for model in models), 1)
        for model in models:
            with self.subTest(model=model["id"]):
                # OpenCode v2 generates variants from effort, not toggle support.
                efforts = expected[model["id"]]["capabilities"].get(
                    "reasoning", {}).get("effort", [])
                self.assertIn("thinkingOptions", model)
                options = model["thinkingOptions"]
                self.assertEqual([option["id"] for option in options], efforts)
                self.assertTrue(all(option["label"].strip() for option in options))


if __name__ == "__main__":
    unittest.main()
