#!/usr/bin/env python3
"""Keep the Flux MCP PV write exception confined to the approved object."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PV = "pvc-64dd51b2-5880-48fb-a1b6-1e4b64c08edd"


class PvPatchGrantTests(unittest.TestCase):
    def test_only_named_pv_patch_is_granted(self):
        path = ROOT / "kubernetes/apps/llm/toolhive/flux-ops/rbac.yaml"
        documents = list(yaml.safe_load_all(path.read_text()))
        role = next(doc for doc in documents if doc.get("kind") == "ClusterRole"
                    and doc["metadata"]["name"] == "opencode-flux-operations")
        rules = [rule for rule in role["rules"]
                 if any(group in ("", "*") for group in rule["apiGroups"])
                 and any(resource in ("persistentvolumes", "*")
                         for resource in rule["resources"])]
        self.assertEqual(rules, [{"apiGroups": [""],
                                 "resources": ["persistentvolumes"],
                                 "resourceNames": [PV], "verbs": ["patch"]}])
        binding = next(doc for doc in documents
                       if doc.get("kind") == "ClusterRoleBinding"
                       and doc["metadata"]["name"] == "opencode-flux-operations")
        self.assertEqual(binding["roleRef"]["name"], role["metadata"]["name"])
        self.assertEqual(binding["subjects"], [{"kind": "ServiceAccount",
                                               "name": "opencode-flux-operator",
                                               "namespace": "llm"}])


if __name__ == "__main__":
    unittest.main()
