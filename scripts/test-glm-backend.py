#!/usr/bin/env python3
"""Offline GLM fleet/catalogue contracts and tiny, mocked staging transfers."""
import ast
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "kubernetes/apps/llm/llmkube/resources"
LITELLM = ROOT / "kubernetes/apps/llm/litellm/app"


def documents(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def resource(path, kind):
    return next(d for d in documents(path) if d["kind"] == kind)


class BackendContracts(unittest.TestCase):
    def test_model_storage_stays_local_and_outside_backup_resources(self):
        pvc = resource(RESOURCES / "radiance-deleuze.yaml", "PersistentVolumeClaim")
        self.assertEqual(pvc["spec"]["storageClassName"], "openebs-hostpath-retain")
        backup_kinds = {"ReplicationSource", "ReplicationDestination", "SnapshotPolicy",
                        "SnapshotSchedule", "Snapshot", "VolumeSnapshot"}
        for path in (ROOT / "kubernetes").rglob("*.yaml"):
            if "radiance-deleuze" not in path.read_text():
                continue
            for doc in documents(path):
                if isinstance(doc, dict) and doc.get("kind") in backup_kinds:
                    with self.subTest(path=path):
                        self.assertNotIn("radiance-deleuze", json.dumps(doc))

    def test_fleet_is_bounded_and_exclusive(self):
        path = RESOURCES / "radiance-deleuze.yaml"
        fleet = yaml.safe_load(resource(path, "ConfigMap")["data"]["radiance.yaml"])
        entry = fleet["models"]["glm-5.3-flash"]
        self.assertEqual(list(fleet["models"])[-1], "glm-5.3-flash")
        self.assertEqual(entry["tp"], 2)
        self.assertNotIn("weights-disk-tier", entry)
        self.assertEqual(entry["host-pool-mib"], 104448)
        self.assertEqual(entry["embedding-placement"], "ram")
        self.assertEqual(entry["max-num-batched-tokens"], 1024)
        self.assertEqual(entry["max-num-seqs"], 1)
        self.assertEqual(entry["max-model-len"], 262144)
        self.assertEqual(entry["kv-cache-dtype"], "i8")
        self.assertEqual(entry["num-speculative-tokens"], 0)
        self.assertEqual(entry["mm-max-patches"], 0)
        self.assertNotIn("vision-tower-placement", entry)
        self.assertEqual(entry["prefix-cache-mib"], 0)
        self.assertEqual(entry["checkpoint-slots"], 0)
        self.assertEqual(fleet["server"]["kernels"], "glm,libr4d,libavx,libref")
        self.assertEqual(set(fleet["groups"]["one-at-a-time"]["exclusive"]),
                         set(fleet["models"]))
        self.assertEqual(resource(path, "InferenceService")["spec"]["resources"]["memory"], "116Gi")
        self.assertEqual(resource(path, "PersistentVolumeClaim")["spec"]["resources"]["requests"]["storage"], "800Gi")

    def test_alias_does_not_invent_capabilities(self):
        spec = resource(LITELLM / "models/glm-deleuze.yaml", "LiteLLMModel")["spec"]
        self.assertEqual(spec["params"]["model"], "openai/glm-5.3-flash")
        self.assertFalse(spec["info"]["supportsVision"])
        self.assertNotIn("maxOutputTokens", spec["info"])
        self.assertNotIn("thinking_levels", spec["info"]["extra"])
        self.assertNotIn("reasoning_effort", spec["params"].get("additional", {}))
        for name in ("hermes", "opencode"):
            spec = resource(LITELLM / f"virtualkeys/{name}.yaml", "LiteLLMVirtualKey")["spec"]
            self.assertIn("glm-deleuze", spec["models"])

    def test_upstream_inkling_reserve_and_global_headroom_survive(self):
        fleet = yaml.safe_load(resource(RESOURCES / "radiance-deleuze.yaml", "ConfigMap")["data"]["radiance.yaml"])
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

    def test_preflight_matches_artifact_and_fleet(self):
        path = RESOURCES / "manual/radiance-glm-preflight.yaml"
        wanted = resource(RESOURCES / "radiance-deleuze.yaml", "ConfigMap")["data"]
        self.assertEqual(resource(path, "ConfigMap")["data"], wanted)
        job = resource(path, "Job")["spec"]["template"]["spec"]
        self.assertEqual(job["containers"][0]["resources"]["limits"]["memory"], "116Gi")
        self.assertNotIn("amd.com/gpu", job["containers"][0]["resources"]["limits"])
        probe = job["initContainers"][0]["args"][0]
        self.assertIn("170662334464", probe)
        self.assertIn("1e20c4bc2f7ea7022f7bae9dd1ffa9873c2031b242d41e85d1ac0a5016342687", probe)
        compile(probe, "weight-probe", "exec")
        kustomization = documents(RESOURCES / "kustomization.yaml")[0]
        self.assertFalse(any("stage-glm" in x or "glm-preflight" in x
                             for x in kustomization["resources"]))

    def test_ram_first_profile_has_no_hidden_host_retention_or_engine_override(self):
        lane = resource(RESOURCES / "radiance-deleuze.yaml", "InferenceService")
        fleet_data = resource(RESOURCES / "radiance-deleuze.yaml", "ConfigMap")["data"]
        fleet = yaml.safe_load(fleet_data["radiance.yaml"])
        entry = fleet["models"]["glm-5.3-flash"]
        self.assertEqual(set(entry), {
            "model", "aliases", "tp", "tp-wire", "placement", "host-pool-mib",
            "embedding-placement", "max-num-seqs", "max-model-len",
            "max-num-batched-tokens", "kv-cache-dtype", "num-speculative-tokens",
            "mm-max-patches", "prefix-cache-mib", "checkpoint-slots", "ttl",
        })
        self.assertEqual(entry["placement"], "expert_tiered")
        self.assertEqual(entry["tp-wire"], "exact")
        self.assertEqual(lane["spec"]["image"],
                         "docker.io/stilldeadcode/radiance:2.3.0@sha256:"
                         "1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12")
        # Explicit RAM is required for the fail-closed late arena reservation.
        self.assertIn("explicit RAM embedding", fleet_data["radiance.yaml"])
        # Include the 1210 MiB embedding pin and 1 GiB staging allowance; actual
        # arenas and baseline memory must fit the remainder, checked at runtime.
        cap_mib = int(lane["spec"]["resources"]["memory"].removesuffix("Gi")) * 1024
        self.assertEqual(cap_mib - entry["host-pool-mib"] - 1024 - 1210 - 8 * 1024,
                         3910)
        for name in ("radiance-23-preflight", "radiance-glm-preflight"):
            path = RESOURCES / "manual" / f"{name}.yaml"
            self.assertEqual(resource(path, "ConfigMap")["data"], fleet_data)
            container = resource(path, "Job")["spec"]["template"]["spec"]["containers"][0]
            self.assertEqual(container["image"], lane["spec"]["image"])
            self.assertEqual(container["resources"]["limits"]["memory"], "116Gi")
            self.assertNotIn("amd.com/gpu", container["resources"]["limits"])


class StagerTests(unittest.TestCase):
    def setUp(self):
        script = resource(RESOURCES / "manual/radiance-deleuze-stage-glm.yaml", "Job")["spec"]["template"]["spec"]["containers"][0]["args"][0]
        tree = ast.parse(script)
        # Load definitions/constants, not the two module-level filesystem actions.
        tree.body = tree.body[:-2]
        self.ns = {}
        exec(compile(tree, "stager", "exec"), self.ns)
        self.temp = tempfile.TemporaryDirectory(prefix="glm-stage-test-", dir="/tmp/opencode")
        self.addCleanup(self.temp.cleanup)
        self.ns["DEST_DIR"] = self.temp.name
        self.ns["SEG"] = 64
        self.data = b"tiny artifact for offline transfer tests" * 9
        self.spec = dict(url="https://example.invalid/artifact", name="test.rad",
                         sha256=hashlib.sha256(self.data).hexdigest(), size=len(self.data))
        self.dst = Path(self.temp.name) / "test.rad"
        # Simulate the space reserve without requiring 8GiB on a test machine.
        self.free = patch("os.statvfs", return_value=type("Space", (), {
            "f_bavail": 16 << 30, "f_frsize": 1})())
        self.free.start()
        self.addCleanup(self.free.stop)

    def response(self, request, timeout):
        lo, hi = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
        response = io.BytesIO(self.data[lo:hi + 1])
        response.status = 206
        response.headers = {"Content-Range": f"bytes {lo}-{hi}/{len(self.data)}"}
        return response

    def test_transfer_and_verified_idempotence(self):
        with patch("urllib.request.urlopen", side_effect=self.response) as network:
            self.ns["fetch"](self.spec)
            self.assertEqual(self.dst.read_bytes(), self.data)
            count = network.call_count
            self.ns["fetch"](self.spec)
            self.assertEqual(network.call_count, count)
        self.assertFalse(Path(str(self.dst) + ".partial").exists())
        self.assertFalse(Path(str(self.dst) + ".pieces").exists())

    def test_existing_wrong_final_is_never_deleted(self):
        self.dst.write_bytes(b"unrelated existing data")
        with patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(RuntimeError, "preserving"):
                self.ns["fetch"](self.spec)
            network.assert_not_called()
        self.assertEqual(self.dst.read_bytes(), b"unrelated existing data")

    def test_resumes_completed_segments(self):
        part = Path(str(self.dst) + ".partial")
        part.write_bytes(self.data[:64] + bytes(len(self.data) - 64))
        Path(str(self.dst) + ".pieces").write_text(json.dumps(dict(
            sha256=self.spec["sha256"], size=self.spec["size"], segment=64, done=[0])))
        with patch("urllib.request.urlopen", side_effect=self.response) as network:
            self.ns["fetch"](self.spec)
            self.assertFalse(any(c.args[0].headers["Range"].startswith("bytes=0-")
                                 for c in network.call_args_list))
        self.assertEqual(self.dst.read_bytes(), self.data)

    def test_bad_range_cannot_publish(self):
        def wrong(request, timeout):
            response = self.response(request, timeout)
            response.status = 200
            return response
        with patch("urllib.request.urlopen", side_effect=wrong):
            with self.assertRaisesRegex(RuntimeError, "unexpected byte range"):
                self.ns["fetch"](self.spec)
        self.assertFalse(self.dst.exists())

    def test_checksum_mismatch_preserves_evidence_without_publishing(self):
        def corrupt(request, timeout):
            response = self.response(request, timeout)
            original = response.getvalue()
            response = io.BytesIO(b"x" * len(original))
            response.status = 206
            lo, hi = map(int, request.headers["Range"].removeprefix("bytes=").split("-"))
            response.headers = {"Content-Range": f"bytes {lo}-{hi}/{len(self.data)}"}
            return response
        with patch("urllib.request.urlopen", side_effect=corrupt):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                self.ns["fetch"](self.spec)
        self.assertFalse(self.dst.exists())
        self.assertTrue(Path(str(self.dst) + ".partial").exists())
        self.assertTrue(Path(str(self.dst) + ".pieces").exists())

    def test_low_space_refuses_before_download(self):
        with patch("os.statvfs", return_value=type("Space", (), {
                "f_bavail": 1, "f_frsize": 1})()), patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(RuntimeError, "filesystem space"):
                self.ns["fetch"](self.spec)
            network.assert_not_called()
        self.assertFalse(self.dst.exists())


if __name__ == "__main__":
    unittest.main()
