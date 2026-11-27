"""Keep Inkling's shared KV floor and advertised context limits in agreement."""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "kubernetes/apps/llm"


class InklingKVConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = LLM / "llmkube/resources"
        docs = list(yaml.safe_load_all((resources / "radiance-deleuze.yaml").read_text()))
        cls.fleet_bytes = next(
            doc["data"]["radiance.yaml"] for doc in docs
            if doc and doc["kind"] == "ConfigMap"
            and doc["metadata"]["name"] == "radiance-fleet-config")
        cls.entry = yaml.safe_load(cls.fleet_bytes)["models"]["inkling-2-mini"]
        cls.preflight = list(yaml.safe_load_all(
            (resources / "manual/radiance-23-preflight.yaml").read_text()))

    def test_all_eight_full_contexts_have_an_explicit_floor(self):
        self.assertEqual(self.entry["max-num-seqs"], 8)
        self.assertEqual(self.entry["max-model-len"], 262144)
        self.assertEqual(self.entry["flex"]["kv"]["min-tokens"],
                         self.entry["max-num-seqs"] * self.entry["max-model-len"])

    def test_int8_cache_and_speculative_decoder_are_preserved(self):
        self.assertEqual(self.entry["tp"], 2)
        self.assertEqual(self.entry["kv-cache-dtype"], "i8")
        self.assertEqual(self.entry["num-speculative-tokens"], 7)
        self.assertEqual(self.entry["draft-window"], "adaptive")

    def test_litellm_advertises_the_backend_context(self):
        model = yaml.safe_load((LLM / "litellm/app/models/inkling-deleuze.yaml").read_text())
        self.assertEqual(model["spec"]["info"]["maxInputTokens"],
                         self.entry["max-model-len"])

    def test_opencode_advertises_the_backend_context(self):
        cm = yaml.safe_load((LLM / "opencode/app/opencode-config.yaml").read_text())
        config = json.loads(cm["data"]["opencode.json"])
        model = config["providers"]["cogito"]["models"]["inkling-deleuze"]
        self.assertEqual(model["limit"]["context"], self.entry["max-model-len"])
        self.assertEqual(model["limit"]["output"], 16384)

    def test_preflight_checks_exactly_the_deployable_fleet(self):
        config = next(doc for doc in self.preflight if doc and doc["kind"] == "ConfigMap")
        self.assertEqual(config["data"]["radiance.yaml"], self.fleet_bytes)


if __name__ == "__main__":
    unittest.main()
