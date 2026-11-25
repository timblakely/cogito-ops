#!/usr/bin/env python3
"""Regression tests for managed Paseo startup and GenUI patch validation."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PaseoStartupTests(unittest.TestCase):
    def test_managed_configuration_preserves_only_unmanaged_plugin_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed = {
                "daemon": {"mcp": {"injectIntoAgents": True}},
                "agents": {"providers": {"opencode": {"models": ["managed"]}}},
                "plugins": {"genui": {"enabled": True, "path": "/opt/paseo-genui"}},
            }
            old = {
                "daemon": {"mcp": {"injectIntoAgents": False}},
                "agents": {"providers": {"unwanted": {}}},
                "plugins": {"genui": {"enabled": False, "path": "/old/genui"}, "progress": {"enabled": True, "path": "/home/progress"}},
            }
            template, destination = root / "template.json", root / "config.json"
            template.write_text(json.dumps(managed))
            destination.write_text(json.dumps(old))
            result = subprocess.run([sys.executable, str(HERE / "configure-paseo.py"), str(template), str(destination)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = {**managed, "plugins": {"progress": old["plugins"]["progress"], **managed["plugins"]}}
            self.assertEqual(json.loads(destination.read_text()), expected)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_fresh_home_is_initialized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template, destination = root / "template.json", root / "home/config.json"
            template.write_text('{"plugins": {"genui": {"enabled": true}}}')
            result = subprocess.run([sys.executable, str(HERE / "configure-paseo.py"), str(template), str(destination)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(destination.read_text()), json.loads(template.read_text()))

    def test_malformed_runtime_configuration_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template, destination = root / "template.json", root / "config.json"
            template.write_text('{"plugins": {}}')
            destination.write_text('not JSON')
            result = subprocess.run([sys.executable, str(HERE / "configure-paseo.py"), str(template), str(destination)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_text(), 'not JSON')


class GenuiPatchTests(unittest.TestCase):
    def test_upstream_drift_fails_before_any_file_is_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "server").mkdir()
            (root / "package.json").write_text('{"name": "paseo-plugin-genui", "version": "0.3.3"}')
            for relative in ["index.server.ts", "server/data-source.ts"]:
                (root / relative).write_text('unrecognized upstream source')
            result = subprocess.run([sys.executable, str(HERE / "patch-genui.py"), str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unexpected upstream GenUI source', result.stderr)
            for relative in ["index.server.ts", "server/data-source.ts"]:
                self.assertEqual((root / relative).read_text(), 'unrecognized upstream source')

    @unittest.skipUnless(os.environ.get('GENUI_PACKAGE_ROOT'), 'Requires the installed patched package')
    def test_read_only_check_accepts_exact_patched_artifact(self):
        result = subprocess.run([sys.executable, str(HERE / "patch-genui.py"), '--check', os.environ['GENUI_PACKAGE_ROOT']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
