"""Regression tests for the Inkling 2 Mini reasoning-effort rows.

The upstream chat template for the radiance 2.3.0 `inkling-2-mini` entry maps
the named reasoning_effort levels to internal values (none=0.0, minimal=0.1,
low=0.2, medium=0.7, high=0.9, xhigh=0.99, max=0.99 - an alias of xhigh - and
emits a "Thinking effort level" prompt prefix). Those levels are declared
client-side here as explicit `variants` carrying `settings.reasoningEffort`,
The explicit settings preserve each named effort on the client wire.

This file is the guard for wire form: it checks that
  - the seven levels are declared (none/minimal/low/medium/high/xhigh/max),
  - `none` is carried as a minimum effort, not a hard off (no toggle, no
    enable_thinking, no enable/off wording anywhere),
  - each variant sets str-identical reasoningEffort == its variant id,
  - Paseo mirrors the same seven variants in BOTH provider blocks, and
  - the other rows (subscription aliases, flashnext, glimmer, heretic,
    gemma) are unchanged in shape.

It cannot verify what the radiance runtime does with the field - that is the
separate radiance/runtime worker. It proves only the client-side contract.
"""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"

EXPECTED_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def embedded(filename, key):
    return json.loads(yaml.safe_load((APP / filename).read_text())["data"][key])


class InklingReasoningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.opencode = embedded("opencode-config.yaml", "opencode.json")
        cls.paseo = embedded("paseo-config.yaml", "config.json")
        cls.models = cls.opencode["providers"]["cogito"]["models"]
        cls.inkling = cls.models["inkling-deleuze"]

    def test_supported_levels_are_none_first(self):
        self.assertEqual(
            [v["id"] for v in self.inkling["variants"]], EXPECTED_LEVELS)

    def test_every_variant_sends_named_level_string(self):
        for variant in self.inkling["variants"]:
            with self.subTest(variant=variant["id"]):
                self.assertEqual(
                    variant["settings"]["reasoningEffort"], variant["id"])
                # Only id + settings.reasoningEffort: headers/body/extras would
                # carry meaning we cannot honestly describe.
                self.assertEqual(
                    set(variant), {"id", "settings"})

    def test_no_toggle_and_no_enable_thinking_false(self):
        self.assertFalse(
            self.inkling["capabilities"].get("reasoning", {}).get("toggle", False))
        self.assertFalse(
            self.inkling["capabilities"].get("reasoning", {}).get("effort", []))
        for variant in self.inkling["variants"]:
            body = variant.get("settings", {})
            for forbidden in ("enable_thinking", "enabled", "thinking"):
                self.assertNotIn(forbidden, body)
        self.assertNotIn("toggle", self.inkling["capabilities"]["reasoning"])
        self.assertNotIn("effort", self.inkling["capabilities"]["reasoning"])

    def test_none_is_a_minimum_effort_not_a_hard_off(self):
        # The none variant carries the level, never the word "off" as a
        # separate mechanism.
        forbidden = {"enable_thinking", "thinking", "enabled", "effort"}
        for variant in self.inkling["variants"]:
            for key in variant.get("settings", {}):
                self.assertNotIn(key, forbidden)
        self.assertEqual(self.inkling["variants"][0]["settings"]["reasoningEffort"], "none")

    def test_no_effort_capability_is_advertised_in_capabilities(self):
        # Keep a single explicit declaration of the selectable variants.
        self.assertNotIn("effort", self.inkling["capabilities"]["reasoning"])
        self.assertTrue(self.inkling["capabilities"]["reasoning"]["supported"])

    def test_paseo_mirrors_the_seven_variants_in_both_blocks(self):
        providers = self.paseo["agents"]["providers"]
        for provider_id in ("opencode", "opencode-worker"):
            with self.subTest(provider=provider_id):
                inkling = [m for m in providers[provider_id]["models"]
                           if m["id"] == "cogito/inkling-deleuze"][0]
                options = inkling["thinkingOptions"]
                self.assertEqual(
                    [o["id"] for o in options], EXPECTED_LEVELS)
                self.assertTrue(all(o["label"].strip() for o in options))
                none = [o for o in options if o["id"] == "none"][0]
                # The minimum-effort label must not read as an Off switch.
                self.assertIn("minimum", none["label"].lower())

    def test_unrelated_rows_are_untouched(self):
        cogito = self.models
        self.assertEqual(
            cogito["flashnext-deleuze"]["capabilities"]["reasoning"]["effort"],
            ["minimal", "low", "medium", "xhigh"])
        gpt = self.opencode["providers"]["cogito-sub"]["models"]["gpt-6.1-terra"]
        self.assertEqual(
            gpt["capabilities"]["reasoning"]["effort"],
            ["low", "medium", "high", "xhigh", "max"])
        self.assertFalse(cogito["glimmer-deleuze"]["capabilities"]["reasoning"].get("effort", []))
        self.assertIn("toggle", cogito["gemma-4-12b"]["capabilities"]["reasoning"])


if __name__ == "__main__":
    unittest.main()
