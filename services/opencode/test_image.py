"""Cheap recipe checks; actual executables are exercised by smoke.sh in-cluster."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent


class ImageRecipeTests(unittest.TestCase):
    def test_requested_tools_and_native_dependencies(self):
        packages = (ROOT / "packages.txt").read_text().splitlines()
        self.assertEqual(len(packages), len(set(packages)))
        required = {"git", "jujutsu", "bash", "ripgrep", "curl", "jq", "yq-go",
                    "yamlfmt", "yamllint", "coreutils", "build-base", "sops", "age"}
        self.assertFalse(required - set(packages))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9+-]+", p) for p in packages))

    def test_pinned_bases_and_nonroot_smoke(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("KUBECTL_VERSION=1.34.2", dockerfile)
        self.assertIn("kubectl.sha256", dockerfile)
        self.assertIn("USER 1000", dockerfile)
        self.assertGreater(dockerfile.index("RUN opencode-image-check"),
                           dockerfile.index("USER 1000"))
        self.assertRegex(dockerfile, r"FROM ghcr.io/jdx/mise@sha256:[0-9a-f]{64}")
        self.assertNotRegex(dockerfile, r"(?m)^(?:ARG|ENV) .*?(?:TOKEN|PASSWORD)=")

    def test_lan_only_bounded_builder(self):
        script = (ROOT / "build/build.sh").read_text()
        self.assertIn("registry.timblakely.com/timblakely/opencode-cogito:homeops-", script)
        self.assertNotIn("ghcr.io", script)
        self.assertIn("defaultCgroupParent", script)
        self.assertIn('"$quota" != max', script)
        self.assertIn('"$memory" != max', script)
        self.assertIn('"/proc/$daemon/cgroup"', script)
        self.assertIn("--metadata-file /scratch/image-metadata.json", script)
        job = (ROOT / "build/job.yaml").read_text()
        for required in ("activeDeadlineSeconds: 3600", "automountServiceAccountToken: false",
                         "preemptionPolicy: Never", "registry-build-auth", "kristeva"):
            self.assertIn(required, job)
        self.assertNotIn("nvidia.com/gpu", job)
        self.assertNotIn("hostPath:", job)

    def test_hosted_ci_does_not_publish_images(self):
        workflow = (ROOT.parents[1] / ".github/workflows/opencode-image.yaml").read_text()
        for forbidden in ("docker push", "docker build", "packages: write", "docker login",
                          "ghcr.io/", "skopeo copy", "buildah push", "kaniko"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
