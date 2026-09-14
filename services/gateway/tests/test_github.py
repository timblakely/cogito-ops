from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coordinator.github import (
    GitHubIssues, deliverable_body, deliverable_execution_intent,
    deliverable_specs, deliverable_title,
)
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
        item = "Update `services/gateway/RUNBOOK.md` with the approved section."
        body = deliverable_body(plan, 1, item, "https://github.com/example/repo/issues/1")

        self.assertTrue(body.startswith(f"## Deliverable\n\n{item}\n\n"))
        self.assertIn("<!-- cogito-plan-deliverable: plan-1:1 -->", body)
        self.assertIn(f"Accepted plan hash: `{plan.hash}`", body)

    def test_deliverable_title_prefers_bounded_bold_heading(self):
        item = "**Deliverable 1 — Add evidence.** " + "Verify the path. " * 100
        self.assertEqual(deliverable_title(item), "Deliverable 1 — Add evidence.")
        self.assertLessEqual(len(deliverable_title("x" * 1000)), 240)

    def test_execution_intent_contains_only_the_current_deliverable(self):
        intent = deliverable_execution_intent(1, "Create the evidence document.")

        self.assertIn("only approved deliverable 1", intent)
        self.assertIn("Create the evidence document.", intent)
        self.assertIn("do not begin any later deliverable", intent)
        with self.assertRaises(ValidationError):
            deliverable_execution_intent(0, "Invalid")

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

    def test_nested_deliverables_keep_nearest_parent(self):
        specs = deliverable_specs(
            "# Plan\n\n## Deliverables\n- [ ] Parent\n  - [ ] Child one\n"
            "  - [ ] Child two\n- [ ] Sibling\n")
        self.assertEqual(specs, [
            ("Parent", None), ("Child one", 0), ("Child two", 0), ("Sibling", None),
        ])

    def test_review_packet_becomes_inline_review(self):
        github = GitHubIssues(token="test")
        calls = []
        github._request = lambda method, path, body=None: (
            calls.append((method, path, body)) or {"id": 7, "html_url": "review-url"})
        result = github.post_review_packet(
            "https://github.com/o/r/pull/2", "a" * 40, {
                "agent": "falsifier", "verdict": "NO-GO", "conclusion": "Broken",
                "uncertainty": "", "evidence": [
                    {"path": "x.py", "line": 8, "note": "Bad branch"}],
            })
        self.assertEqual(result["inline_comments"], 1)
        self.assertEqual(calls[0][2]["commit_id"], "a" * 40)
        self.assertEqual(calls[0][2]["comments"][0]["line"], 8)
