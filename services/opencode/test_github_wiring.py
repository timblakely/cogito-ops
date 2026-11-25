"""GitHub credential manifests must preserve scope and rotation semantics."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"


class GithubWiringTests(unittest.TestCase):
    def test_dedicated_generator_has_only_repository_contents_write(self):
        path = APP / "github-app.yaml"
        self.assertTrue(path.exists(), "OpenCode needs its own token generator")
        docs = list(yaml.safe_load_all(path.read_text()))
        generator = next(d for d in docs if d["kind"] == "GithubAccessToken")
        foreman = next(d for d in yaml.safe_load_all(
            (APP.parents[1] / "foreman/app/github-app.yaml").read_text())
                       if d["kind"] == "GithubAccessToken")
        self.assertEqual(generator["metadata"]["name"], "opencode")
        spec = generator["spec"]
        self.assertEqual(spec["appID"], foreman["spec"]["appID"])
        self.assertEqual(spec["installID"], foreman["spec"]["installID"])
        self.assertEqual(spec["repositories"], ["cogito-ops"])
        self.assertEqual(spec["permissions"], {"contents": "write"})
        self.assertEqual(spec["auth"]["privateKey"]["secretRef"],
                         {"name": "opencode-github-app-auth", "key": "private-key.pem"})

    def test_only_main_mounts_rotating_token_as_readonly_directory(self):
        values = yaml.safe_load((APP / "helmrelease.yaml").read_text())["spec"]["values"]
        persistence = values["persistence"]
        self.assertIn("github-token", persistence)
        token = persistence["github-token"]
        self.assertEqual(token["type"], "secret")
        self.assertEqual(token["name"], "opencode-github-token")
        self.assertEqual(token["defaultMode"], 0o440)
        self.assertEqual(token["advancedMounts"], {
            "opencode": {"main": [{"path": "/var/run/secrets/github", "readOnly": True}]}
        })
        self.assertEqual(values["controllers"]["opencode"]["pod"]["securityContext"]["fsGroup"], 1000)
        self.assertNotIn("opencode-github-app-auth", yaml.safe_dump(persistence))
        for container in values["controllers"]["opencode"]["containers"].values():
            self.assertNotIn("opencode-github-token", yaml.safe_dump(container.get("env", {})))

    def test_registered_system_helper_config_is_only_mounted_in_main(self):
        kustomization = yaml.safe_load((APP / "kustomization.yaml").read_text())
        self.assertIn("./github-app.yaml", kustomization["resources"])
        generator = next(g for g in kustomization["configMapGenerator"]
                         if g["name"] == "opencode-github")
        self.assertEqual(set(generator["files"]),
                         {"github.gitconfig", "github-credential-helper.py"})
        self.assertTrue(generator["options"]["disableNameSuffixHash"])
        self.assertEqual(generator["options"]["annotations"]
                         ["kustomize.toolkit.fluxcd.io/substitute"], "disabled")
        values = yaml.safe_load((APP / "helmrelease.yaml").read_text())["spec"]["values"]
        config = values["persistence"]["github-config"]
        self.assertEqual(config["type"], "configMap")
        self.assertEqual(config["name"], "opencode-github")
        self.assertEqual(config["advancedMounts"], {
            "opencode": {"main": [
                {"path": "/etc/opencode/github", "readOnly": True},
                {"path": "/etc/gitconfig", "subPath": "github.gitconfig", "readOnly": True},
            ]}
        })

    def test_rotation_updates_only_token_and_does_not_roll_sessions(self):
        docs = list(yaml.safe_load_all((APP / "github-app.yaml").read_text()))
        auth = next(d for d in docs if d["metadata"]["name"] == "opencode-github-app-auth")
        self.assertEqual(auth["spec"]["secretStoreRef"],
                         {"kind": "ClusterSecretStore", "name": "onepassword"})
        self.assertEqual(auth["spec"]["data"], [{
            "secretKey": "private-key.pem",
            "remoteRef": {"key": "matrix-github-app", "property": "private-key"},
        }])
        token = next(d for d in docs if d["metadata"]["name"] == "opencode-github-token")
        self.assertEqual(token["spec"]["refreshInterval"], "30m")
        self.assertEqual(token["spec"]["dataFrom"], [{"sourceRef": {"generatorRef": {
            "apiVersion": "generators.external-secrets.io/v1alpha1",
            "kind": "GithubAccessToken", "name": "opencode",
        }}}])
        target = token["spec"]["target"]
        self.assertEqual(target["template"]["data"], {"token": "{{ .token }}"})
        self.assertEqual(target["template"]["metadata"]["annotations"]
                         ["reloader.stakater.com/ignore"], "true")
        values = yaml.safe_load((APP / "helmrelease.yaml").read_text())["spec"]["values"]
        self.assertEqual(values["controllers"]["opencode"]["annotations"]
                         ["reloader.stakater.com/auto"], "true")


if __name__ == "__main__":
    unittest.main()
