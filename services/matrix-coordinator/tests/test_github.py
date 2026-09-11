from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coordinator.github import GitHubIssues


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

    def test_close_issue_is_idempotent(self):
        github = GitHubIssues(token="token")
        requests = []

        def request(method, path, body=None):
            requests.append((method, path, body))
            if method == "GET":
                return {"html_url": "https://github.com/o/r/issues/7", "state": "open"}
            return {"html_url": "https://github.com/o/r/issues/7", "state": "closed"}

        github._request = request
        result = github.close_issue("https://github.com/o/r/issues/7")
        self.assertEqual(result["state"], "closed")
        self.assertEqual(requests[-1], (
            "PATCH", "/repos/o/r/issues/7",
            {"state": "closed", "state_reason": "completed"}))
