#!/usr/bin/env python3
"""GLM-5.3-Flash retirement guards.

The GLM-5.3-Flash lane was added in 3cc06b9f (2026-11-27) and retired on
2026-11-28 before live acceptance: its registration, serving profile, staged
artifact, staging/preflight Jobs, LiteLLM route, and OpenCode/Paseo/Hermes
entries are all gone. These tests pin the negative state (no registration
anywhere) AND the preserved state beside it (Inkling's eight-seat reserve,
the five-entry exclusive group, the 80 Gi cgroup, the 800 Gi retained claim),
so a later edit cannot quietly reintroduce a half-retired GLM route.

Historical material - the Maya-M trial, its archive docs and the plans/
artifacts - is intentionally outside scope and stays in the tree as history.
"""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "kubernetes/apps/llm/llmkube/resources"
LITELLM = ROOT / "kubernetes/apps/llm/litellm/app"


def documents(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def documented_fleet():
    docs = documents(RESOURCES / "radiance-deleuze.yaml")
    return (
        yaml.safe_load(next(d for d in docs if d["kind"] == "ConfigMap")["data"]["radiance.yaml"]),
        next(d for d in docs if d["kind"] == "InferenceService"),
        next(d for d in docs if d["kind"] == "PersistentVolumeClaim"),
        next(d for d in docs if d["kind"] == "ConfigMap")["data"]["radiance.yaml"],
    )


class GlmRetirementGuards(unittest.TestCase):
    def test_five_entry_fleet_without_glm(self):
        fleet, _, _, _ = documented_fleet()
        self.assertEqual(
            list(fleet["models"]),
            ["qwen3.8-flash-next", "muse-glimmer", "flux-3-klein", "gemma4-heretic", "inkling-2-mini"],
        )
        self.assertNotIn("kernels", fleet["server"])
        self.assertEqual(
            set(fleet["groups"]["one-at-a-time"]["exclusive"]),
            set(fleet["models"]),
        )
        self.assertNotIn("glm-5.3-flash", fleet["groups"]["one-at-a-time"]["exclusive"])

    def test_no_glm_anywhere_in_fleet_files(self):
        for path in (RESOURCES / "radiance-deleuze.yaml",
                     RESOURCES / "manual" / "radiance-23-preflight.yaml"):
            text = path.read_text()
            self.assertNotIn("glm-deleuze", text)
            self.assertNotIn("glm-5.3-flash", text)
            self.assertNotIn("glm53", text)

    def test_inkling_reserve_survives_unchanged(self):
        fleet, _, _, _ = documented_fleet()
        self.assertEqual(fleet["models"]["inkling-2-mini"], {
            "model": "/models/radiance/inkling-2-mini-iq4r-v4.rad",
            "aliases": ["inkling"], "tp": 2, "max-model-len": 262144,
            "max-num-seqs": 8, "flex": {"kv": {"min-tokens": 2097152}},
            "kv-cache-dtype": "i8", "num-speculative-tokens": 7,
            "draft-window": "adaptive", "vision-tower-placement": "vram",
            "prefix-cache-mib": 4096, "ttl": "15m",
        })
        self.assertEqual(fleet["memory"], {"gpu-headroom-mib": 160})
        self.assertEqual(fleet["scheduler"], {"stuck-exit": "60s", "load-timeout": "600s"})

    def test_capacity_allocation_is_the_pre_glm_state(self):
        _, lane, pvc, _ = documented_fleet()
        # GLM raised the serving cap 80 Gi -> 116 Gi; retirement returns it.
        self.assertEqual(lane["spec"]["resources"]["memory"], "80Gi")
        # The 800 Gi retained claim is live (storage owner read it back);
        # it must stay.
        self.assertEqual(pvc["spec"]["resources"]["requests"]["storage"], "800Gi")
        self.assertEqual(pvc["spec"]["storageClassName"], "openebs-hostpath-retain")

    def test_staging_jobs_are_deleted_and_unregistered(self):
        manual = RESOURCES / "manual"
        self.assertFalse((manual / "radiance-deleuze-stage-glm.yaml").exists())
        self.assertFalse((manual / "radiance-glm-preflight.yaml").exists())
        kustomization = documents(RESOURCES / "kustomization.yaml")[0]
        self.assertFalse(any("glm" in x for x in kustomization["resources"]))

    def test_preflight_copy_matches_lane_bytes(self):
        # The 2.3.0 one-shot preflight carries its own copy of the fleet bytes;
        # it must gate the same file the lane mounts.
        fleet = documented_fleet()[3]
        pdocs = documents(RESOURCES / "manual" / "radiance-23-preflight.yaml")
        self.assertEqual(next(d for d in pdocs if d["kind"] == "ConfigMap")["data"]["radiance.yaml"], fleet)

    def test_route_is_gone_from_every_catalogue_layer(self):
        kustomization = yaml.safe_load((LITELLM / "models" / "kustomization.yaml").read_text())
        self.assertFalse(any("glm" in str(x) for x in kustomization["resources"]))
        self.assertFalse((LITELLM / "models" / "glm-deleuze.yaml").exists())
        for name in ("hermes", "opencode"):
            keys = [d for d in documents(LITELLM / "virtualkeys" / f"{name}.yaml") if d["kind"] == "LiteLLMVirtualKey"]
            self.assertTrue(keys)
            scope = keys[0]["spec"]["models"]
            self.assertFalse(any("glm" in m for m in scope))
            self.assertIn("inkling-deleuze", scope)

    def test_no_glm_in_repo_active_files(self):
        # Known-active files must not carry the retired route; the Maya-M
        # trial, its archive docs and plans/artifacts are out of scope. The
        # retirement note in the fleet file may mention the retired lane by
        # name; nothing registration-shaped may remain.
        # Configure.py legitimately names the retired record as the removal
        # sentinel used by the deletion logic, so it is asserted by shape
        # (no live registration) rather than by token.
        for path in [
            RESOURCES / "radiance-deleuze.yaml",
            LITELLM / "models" / "kustomization.yaml",
            LITELLM / "virtualkeys" / "hermes.yaml",
            LITELLM / "virtualkeys" / "opencode.yaml",
            ROOT / "kubernetes/apps/llm/opencode/app/opencode-config.yaml",
            ROOT / "kubernetes/apps/llm/opencode/app/paseo-config.yaml",
            ROOT / "services/opencode/README.md",
            ROOT / "kubernetes/apps/llm/hermes/README.md",
        ]:
            lowered = path.read_text().lower()
            for token in ("glm-deleuze", "glm-5.3-flash", "glm53", "glm_5.3",
                          "stage-glm", "glm-preflight", "glm-deleuze.yaml",
                          '"glm": {', '"glm":{'):
                self.assertNotIn(token, lowered, f"{path}: {token!r}")
        configure = (ROOT / "kubernetes/apps/llm/hermes/app/configure.py").read_text()
        self.assertIn("managed_glm = {", configure)
        self.assertNotIn('"glm": {', configure)
        self.assertNotIn('"glm":{', configure)
        # The generated provider bootstrap is the same payload: no live
        # registration, ever.
        bootstrap = (ROOT / "kubernetes/apps/llm/hermes/app/provider-bootstrap.yaml").read_text()
        self.assertIn("managed_glm = {", bootstrap)
        self.assertNotIn('"glm": {', bootstrap)
        self.assertNotIn('"glm":{', bootstrap)


if __name__ == "__main__":
    unittest.main()
