from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coordinator.github import GitHubIssues, deliverable_body
from coordinator.models import ValidationError
from coordinator.models import PlanVersion


class GitHubCredentialTests(unittest.TestCase):
    def test_projected_github_token_is_reloaded(self):
        with TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("first\n")
            github = GitHubIssues(token="fallback", token_file=str(token_file))

            self.assertEqual(github._authorization_token(), "first")

            token_file.write_text("second\n")
            self.assertEqual(github._authorization_token(), "second")

    def test_static_github_token_remains_a_migration_fallback(self):
        self.assertEqual(GitHubIssues(token="fallback")._authorization_token(), "fallback")

    def test_deliverable_body_starts_with_foreman_verifiable_ask(self):
        plan = PlanVersion(
            "plan-1", 1, "# Plan\n", "!room:example", "$event",
            "https://github.com/timblakely/cogito-ops.git",
        )
        item = "Update `services/matrix-coordinator/RUNBOOK.md` with the accepted section."
        body = deliverable_body(plan, 1, item, "https://github.com/example/repo/issues/1")

        self.assertTrue(body.startswith(f"## Deliverable\n\n{item}\n\n"))
        self.assertIn("<!-- cogito-plan-deliverable: plan-1:1 -->", body)
        self.assertIn(f"Accepted plan hash: `{plan.hash}`", body)

    def test_merge_is_pinned_to_reviewed_head_sha(self):
        github = GitHubIssues(token="test")
        pull = {
            "state": "open", "draft": False, "merged": False,
            "base": {"ref": "main"},
            "head": {"ref": "foreman/plan/issue-1", "sha": "a" * 40,
                     "repo": {"full_name": "o/r"}},
        }
        github._request = lambda method, path, body=None: pull
        github._request_with_status = lambda method, path, body=None, allowed_errors=None: (
            202, {"status": "pending", "details": {"uuid": "merge-1"}})
        result = github.request_merge(
            "https://github.com/o/r/pull/2", "a" * 40, "foreman/plan/issue-1")
        self.assertEqual(result["uuid"], "merge-1")

        with self.assertRaisesRegex(RuntimeError, "changed after reviewer quorum"):
            github.request_merge(
                "https://github.com/o/r/pull/2", "b" * 40, "foreman/plan/issue-1")

    def test_pull_request_identity_rejects_other_hosts(self):
        with self.assertRaises(ValidationError):
            GitHubIssues._pull_identity("https://example.com/o/r/pull/2")
