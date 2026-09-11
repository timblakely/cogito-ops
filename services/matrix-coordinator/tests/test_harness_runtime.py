import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from coordinator.harness_runtime import Workspace
from coordinator.models import AgentRun


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        seed = root / "seed"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.email", "fixture@example.invalid"], check=True)
        (seed / "README.md").write_text("fixture\n")
        subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-m", "fixture"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(self.remote)], check=True)
        subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)
        self.run = AgentRun(
            "workspace-run-0001", "https://github.com/o/r/issues/1", "worker",
            "https://github.com/o/r.git", "main", "write health", allowed_paths=("health.txt",),
        )
        object.__setattr__(self.run, "repository", str(self.remote))
        self.env = patch.dict(os.environ, {"COGITO_WORK_ROOT": str(root / "work"),
                                           "COGITO_PUBLISH": "1", "PATH": "/usr/bin:/bin"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_explicit_ref_workspace_and_idempotent_publication(self):
        workspace = Workspace(self.run)
        workspace.prepare()
        (workspace.repo / "health.txt").write_text("ok\n")
        head, branch = workspace.publish()
        self.assertEqual(branch, "agent/workspace-run-0001")
        remote = subprocess.run(
            ["git", "--git-dir", str(self.remote), "rev-parse", "refs/heads/" + branch],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(head, remote)

    def test_path_escape_fails_closed(self):
        workspace = Workspace(self.run)
        workspace.prepare()
        (workspace.repo / "outside.txt").write_text("no\n")
        with self.assertRaisesRegex(RuntimeError, "outside allowlist"):
            workspace.publish()


if __name__ == "__main__":
    unittest.main()
