import unittest

from coordinator.foreman import ForemanClient, _issue_numbers, _repo_slug, workload_name
from coordinator.models import ValidationError


class ForemanTests(unittest.TestCase):
    def test_manifest_is_deterministic_and_uses_issue_shortcut(self):
        client = ForemanClient()
        values = dict(
            plan_id="plan-abc", plan_hash="sha256:" + "a" * 64,
            intent="# Do it\n", repository="https://github.com/timblakely/cogito-ops.git",
            issue_urls=["https://github.com/timblakely/cogito-ops/issues/12"],
            room_id="!room:example", thread_root="$root",
        )
        manifest = client.manifest(**values)
        self.assertEqual(manifest["metadata"]["name"], workload_name(values["plan_id"], values["plan_hash"]))
        self.assertEqual(manifest["spec"]["repo"], "timblakely/cogito-ops")
        self.assertEqual(manifest["spec"]["issues"], [12])
        self.assertEqual(manifest["spec"]["maxTasks"], 6)
        self.assertEqual(manifest["spec"]["maxReviewIterations"], 1)
        self.assertEqual(manifest["spec"]["gateProfile"]["language"], "generic")
        self.assertIn("@sha256:", manifest["spec"]["gateProfile"]["image"])

    def test_repository_and_issue_must_match(self):
        self.assertEqual(_repo_slug("https://github.com/O/R.git"), "O/R")
        with self.assertRaises(ValidationError):
            _repo_slug("https://gitlab.example/O/R.git")
        with self.assertRaises(ValidationError):
            _issue_numbers("O/R", ["https://github.com/O/else/issues/1"])

    def test_summary_is_bounded_status(self):
        self.assertEqual(ForemanClient.summary({"status": {
            "phase": "Completed", "succeededTasks": 3, "failedTasks": 0,
        }})["succeeded"], 3)


if __name__ == "__main__":
    unittest.main()
