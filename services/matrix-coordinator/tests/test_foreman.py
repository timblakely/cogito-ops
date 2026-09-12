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
        self.assertEqual(manifest["spec"]["maxTasks"], 8)
        self.assertEqual(manifest["spec"]["maxReviewIterations"], 1)
        self.assertEqual(
            [ref["name"] for ref in manifest["spec"]["reviewerAgentRefs"]],
            ["cogito-reviewer", "cogito-reviewer-falsifier"],
        )
        self.assertEqual(manifest["spec"]["gateProfile"]["language"], "generic")
        self.assertIn("@sha256:", manifest["spec"]["gateProfile"]["image"])
        self.assertEqual(
            manifest["spec"]["gateProfile"]["commands"]["lint"],
            "git fetch --deepen=1 origin && git diff --check HEAD^ HEAD -- .",
        )

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

    def test_research_manifest_is_a_local_read_only_freeform_task(self):
        manifest = ForemanClient().research_manifest(
            "plan-a-research-r1-1", "plan-a", "Inspect planning.",
            "https://github.com/timblakely/cogito-ops.git",
        )
        self.assertEqual(manifest["spec"]["kind"], "freeform")
        self.assertEqual(manifest["spec"]["agentRef"]["name"], "cogito-planning-scout")
        self.assertEqual(manifest["spec"]["modelRef"], "muse-glimmer-30b")
        self.assertEqual(manifest["spec"]["payload"]["repo"], "timblakely/cogito-ops")
        self.assertEqual(manifest["spec"]["payload"]["baseBranch"], "main")
        self.assertIn("Work read-only", manifest["spec"]["payload"]["prompt"])

    def test_merge_candidate_requires_two_distinct_reviews_after_final_coder(self):
        client = ForemanClient()
        tasks = [
            {"spec": {"kind": "issue-fix"}, "status": {
                "phase": "Succeeded", "verdict": "GO", "finishedAt": "2026-01-01T00:00:01Z",
                "branch": "foreman/plan/issue-1", "commitSHA": "a" * 40,
            }},
            *[{"spec": {"kind": "review", "agentRef": {"name": agent},
                        "payload": {"branch": "foreman/plan/issue-1"}},
               "status": {"phase": "Succeeded", "verdict": "GO",
                          "startedAt": "2026-01-01T00:00:02Z",
                          "result": {"extra": {"pullRequestURL":
                              "https://github.com/o/r/pull/2"}}}}
              for agent in ("reviewer", "falsifier")],
        ]
        client.tasks = lambda _: tasks
        candidate = client.merge_candidate("workload")
        self.assertEqual(candidate["head_sha"], "a" * 40)
        self.assertEqual(candidate["reviewers"], ["falsifier", "reviewer"])

        client.tasks = lambda _: tasks[:-1]
        with self.assertRaises(RuntimeError):
            client.merge_candidate("workload")


if __name__ == "__main__":
    unittest.main()
