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
