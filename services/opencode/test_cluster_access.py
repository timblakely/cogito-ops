"""Static RBAC/config regression tests; verify live API and MCP calls separately."""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"
MCP = ROOT / "kubernetes/apps/llm/toolhive/flux-ops"


def documents(path):
    return list(yaml.safe_load_all(path.read_text()))


def role_at(path, name):
    return next(d for d in documents(path)
                if d["kind"] == "ClusterRole" and d["metadata"]["name"] == name)


def permits(role, verb, group, resource, name=None):
    def matches(items, value):
        return value in items or "*" in items

    def names_match(rule):
        names = rule.get("resourceNames") or []
        if not names:
            return True
        return name is not None and name in names

    return any(matches(rule["verbs"], verb)
               and matches(rule["apiGroups"], group)
               and matches(rule["resources"], resource)
               and names_match(rule)
               for rule in role["rules"])


class ClusterAccessTests(unittest.TestCase):
    def setUp(self):
        self.reader = role_at(APP / "cluster-access.yaml", "opencode-investigator")
        self.writer = role_at(MCP / "rbac.yaml", "opencode-flux-operations")

    def test_investigation_includes_tunnels_but_not_exec_or_mutation(self):
        for verb, group, resource in [("list", "", "pods"), ("get", "", "pods/log"),
                                      ("watch", "apps", "deployments"),
                                      ("get", "metrics.k8s.io", "nodes"),
                                      ("create", "", "pods/portforward")]:
            self.assertTrue(permits(self.reader, verb, group, resource))
        for verb, group, resource in [("get", "", "secrets"), ("get", "", "nodes/proxy"),
                                      ("create", "", "pods/exec"), ("delete", "", "pods"),
                                      ("patch", "apps", "deployments"),
                                      ("patch", "kustomize.toolkit.fluxcd.io", "kustomizations")]:
            self.assertFalse(permits(self.reader, verb, group, resource))

    def test_operator_can_operate_but_not_administer_credentials_or_rbac(self):
        for verb, group, resource in [("create", "batch", "jobs"), ("delete", "", "pods"),
                                      ("patch", "apps", "deployments"),
                                      ("patch", "kustomize.toolkit.fluxcd.io", "kustomizations"),
                                      ("patch", "helm.toolkit.fluxcd.io", "helmreleases")]:
            self.assertTrue(permits(self.writer, verb, group, resource))
        for verb, group, resource in [("get", "", "secrets"), ("create", "", "serviceaccounts/token"),
                                      ("create", "rbac.authorization.k8s.io", "clusterrolebindings"),
                                      ("delete", "", "nodes"), ("delete", "", "namespaces")]:
            self.assertFalse(any(permits(role, verb, group, resource)
                                 for role in (self.reader, self.writer)))

    def test_operator_can_manage_home_ops_instances_without_direct_reader_writes(self):
        resources = [
            ("", "serviceaccounts"),
            ("external-secrets.io", "externalsecrets"),
            ("external-secrets.io", "pushsecrets"),
            ("gateway.envoyproxy.io", "securitypolicies"),
            ("pocketid.internal", "pocketidoidcclients"),
            ("pocketid.internal", "pocketidusergroups"),
            ("kopiur.home-operations.com", "repositories"),
            ("kopiur.home-operations.com", "snapshotpolicies"),
            ("kopiur.home-operations.com", "snapshotschedules"),
            ("kopiur.home-operations.com", "snapshots"),
        ]
        for group, resource in resources:
            for verb in ("get", "list", "watch", "create", "update", "patch", "delete"):
                with self.subTest(group=group, resource=resource, verb=verb):
                    self.assertTrue(permits(self.writer, verb, group, resource))
                    if verb in ("create", "update", "patch", "delete"):
                        self.assertFalse(permits(self.reader, verb, group, resource))
        for group, resource in [
                ("external-secrets.io", "clustersecretstores"),
                ("kopiur.home-operations.com", "clusterrepositories"),
                ("apiextensions.k8s.io", "customresourcedefinitions"),
                ("rbac.authorization.k8s.io", "rolebindings"),
                ("", "persistentvolumes"),
                ("", "secrets"),
                ("", "serviceaccounts/token")]:
            for verb in ("create", "update", "patch", "delete"):
                with self.subTest(group=group, resource=resource, denied=verb):
                    self.assertFalse(permits(self.writer, verb, group, resource))

    def test_narrow_pv_patch_grant_is_named_patch_only(self):
        # Approved narrow exception: the Flux MCP writer may `patch` exactly
        # the Deleuze retained claim, and nothing else. General PV writes stay
        # denied; see scripts/test-flux-pv-rbac.py for the rule-text contract.
        PV = "pvc-64dd51b2-5880-48fb-a1b6-1e4b64c08edd"
        self.assertTrue(permits(self.writer, "patch", "", "persistentvolumes", name=PV))
        self.assertFalse(permits(self.writer, "patch", "", "persistentvolumes", name="some-unrelated-pv"))
        for verb in ("create", "update", "delete"):
            with self.subTest(verb=verb):
                self.assertFalse(permits(self.writer, verb, "", "persistentvolumes", name=PV))
        # An unnamed request is not allowed by the named rule.
        self.assertFalse(permits(self.writer, "patch", "", "persistentvolumes"))

    def test_workload_identity_is_separate_and_kubeconfig_uses_token_file(self):
        hr = documents(APP / "helmrelease.yaml")[0]
        controller = hr["spec"]["values"]["controllers"]["opencode"]
        self.assertEqual(controller["serviceAccount"]["name"], "opencode-reader")
        self.assertEqual(controller["containers"]["main"]["env"]["KUBECONFIG"],
                         "/etc/opencode/kube/config")
        kubeconfig = yaml.safe_load(documents(APP / "kubeconfig.yaml")[0]["data"]["config"])
        user = kubeconfig["users"][0]["user"]
        self.assertIn("tokenFile", user)
        self.assertNotIn("token", user)
        server = documents(MCP / "mcpserver.yaml")[0]["spec"]
        self.assertEqual(server["serviceAccount"], "opencode-flux-operator")
        self.assertIn("oidcConfigRef", server)
        self.assertIn("authzConfig", server)

    def test_mcp_identity_is_audience_bound_and_subject_restricted(self):
        server = documents(MCP / "mcpserver.yaml")[0]["spec"]
        self.assertEqual(server["oidcConfigRef"]["audience"], "cogito-flux-mcp")
        policy = server["authzConfig"]["inline"]["policies"]
        self.assertEqual(policy, [
            'permit(principal == Client::"system:serviceaccount:llm:opencode-reader", action, resource);'
        ])
        values = documents(APP / "helmrelease.yaml")[0]["spec"]["values"]
        identity = values["persistence"]["flux-mcp-identity"]
        token = identity["volumeSpec"]["projected"]["sources"][0]["serviceAccountToken"]
        self.assertEqual(token["audience"], "cogito-flux-mcp")
        self.assertEqual(token["expirationSeconds"], 3600)
        self.assertEqual(set(identity["advancedMounts"]["opencode"]), {"main"})
        auth = documents(MCP / "auth.yaml")[0]["spec"]["kubernetesServiceAccount"]
        self.assertEqual(auth["issuer"], "https://k8s.internal:6443")
        self.assertTrue(auth["useClusterAuth"])

    def test_backend_cannot_be_reached_by_open_code_directly(self):
        server = documents(MCP / "mcpserver.yaml")[0]
        name = server["metadata"]["name"]
        self.assertEqual(server["spec"]["transport"], "streamable-http")
        self.assertIn("--transport=http", server["spec"]["args"])
        policies = documents(MCP / "networkpolicy.yaml")
        backend = next(d for d in policies if d["metadata"]["name"] == name + "-backend")
        self.assertEqual(backend["spec"]["podSelector"]["matchLabels"],
                         {"app": name, "toolhive-name": name})
        self.assertEqual(backend["spec"]["ingress"][0]["from"], [
            {"podSelector": {"matchLabels": {"app": "mcpserver", "toolhive-name": name}}}
        ])
        policy, binding = documents(MCP / "tunnel-policy.yaml")
        self.assertEqual(policy["spec"]["paramKind"], {"apiVersion": "v1", "kind": "Pod"})
        self.assertEqual(policy["spec"]["matchConstraints"]["resourceRules"][0]["operations"], ["CONNECT"])
        self.assertIn("opencode-reader", policy["spec"]["matchConditions"][0]["expression"])
        self.assertEqual(binding["spec"]["paramRef"]["selector"]["matchLabels"], {"toolhive": "true"})
        self.assertEqual(binding["spec"]["validationActions"], ["Deny"])
        proxy = next(d for d in policies if d["metadata"]["name"] == name + "-proxy")
        self.assertEqual(proxy["spec"]["podSelector"]["matchLabels"],
                         {"app": "mcpserver", "toolhive-name": name})

    def test_managed_mcp_does_not_embed_cached_credentials(self):
        config = json.loads(documents(APP / "opencode-config.yaml")[0]["data"]["opencode.json"])
        self.assertEqual(config["mcp"]["servers"]["flux"]["command"],
                         ["node", "/etc/opencode/mcp/flux-mcp-bridge.mjs"])
        self.assertNotIn("headers", config["mcp"]["servers"]["flux"])
        rule = next(r for r in config["permissions"]
                    if r.get("resource") == "kubectl *")
        self.assertEqual(rule["effect"], "allow")
        generator = documents(APP / "kustomization.yaml")[0]["configMapGenerator"][0]
        self.assertEqual(generator["options"]["annotations"]
                         ["kustomize.toolkit.fluxcd.io/substitute"], "disabled")


if __name__ == "__main__":
    unittest.main()
