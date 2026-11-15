"""Regression tests for the capability publisher embedded in model-caps.yaml."""
import ast
import json
import os
import tempfile
from pathlib import Path
import types
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

import yaml


def load_server():
    manifest = Path(__file__).resolve().parents[1] / "model-caps.yaml"
    config = next(d for d in yaml.safe_load_all(manifest.read_text()) if d["kind"] == "ConfigMap")
    tree = ast.parse(config["data"]["server.py"])
    # Do not start the HTTP server or refresh thread while importing its functions.
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Expr, ast.If))]
    module = types.ModuleType("model_caps_test")
    exec(compile(tree, str(manifest), "exec"), module.__dict__)
    return module


class CatalogueTests(unittest.TestCase):
    def test_openai_fetch_is_get_only_with_tested_client_headers_and_no_token_writes(self):
        server = load_server()
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            auth = Path(directory) / "auth.json"
            before = json.dumps({"access_token": "test-token", "account_id": "test-account"})
            auth.write_text(before)
            def respond(request, timeout):
                self.assertEqual(request.get_method(), "GET")
                self.assertIn("client_version=0.169.0", request.full_url)
                headers = {k.lower(): v for k, v in request.header_items()}
                self.assertEqual(headers.get("originator"), "codex_cli_rs")
                self.assertEqual(headers["authorization"], "Bearer test-token")
                return StringIO('{"models": []}')
            with patch.object(server, "TOKEN_FILE", str(auth)), patch.object(server.urllib.request, "urlopen", side_effect=respond):
                self.assertEqual(server._fetch_openai(), {"models": []})
            self.assertEqual(auth.read_text(), before)

    def test_refresh_joins_only_registered_routes_and_reports_new_visible_models(self):
        server = load_server()
        catalogue = {"fetched_at": "now", "models": [
            {"slug": name, "visibility": visibility, "supported_in_api": True,
             "supported_reasoning_levels": [{"effort": "low"}]} for name, visibility in
            [("served", "list"), ("new", "list"), ("internal", "hide")]
        ]}
        with patch.object(server, "_fetch_upstream", return_value={"data": [{"id": "alias"}, {"id": "local"}]}), \
             patch.object(server, "_fetch_routes", create=True, return_value={"alias": "chatgpt/served", "local": "openai/local"}), \
             patch.object(server, "_load_caps", return_value={}), \
             patch.object(server, "_refresh_openai", return_value=catalogue):
            server._refresh_once()
        self.assertEqual([m["id"] for m in server._snapshot["data"]], ["alias", "local"])
        self.assertEqual(server._snapshot["data"][0]["reasoning"]["supported_efforts"], ["low"])
        self.assertNotIn("reasoning", server._snapshot["data"][1])
        self.assertEqual(server._snapshot["openai_catalogue"]["unregistered_models"], ["new"])

    def test_live_refresh_is_rate_limited_and_failure_retains_good_metadata_without_logging_body(self):
        server = load_server()
        source = {"models": [{"slug": "example", "supported_reasoning_levels": [{"effort": "low"}]}]}
        with patch.object(server, "_fetch_openai", create=True, side_effect=[source, RuntimeError("private response body")]) as fetch:
            with patch.object(server, "_load_fallback", create=True, return_value=None):
                first = server._refresh_openai(now=1000)
                self.assertEqual(first["models"][0]["slug"], "example")
                self.assertEqual(server._refresh_openai(now=1001), first)
                self.assertEqual(fetch.call_count, 1)
                output = StringIO()
                with redirect_stdout(output):
                    stale = server._refresh_openai(now=1000 + server.OPENAI_REFRESH_SECONDS + 1)
                self.assertEqual(stale, first)
                self.assertNotIn("private response body", output.getvalue())
                self.assertEqual(fetch.call_count, 2)

    def test_sanitization_drops_nonmetadata_and_rejects_empty_catalogues(self):
        server = load_server()
        payload = {"models": [{
            "slug": "example", "visibility": "list", "supported_in_api": True,
            "supported_reasoning_levels": [{"effort": "low", "description": "quick"}],
            "default_reasoning_level": "low", "access_token": "test-only-sensitive-value",
            "system_prompt": "not capability metadata",
        }]}
        clean = server._sanitize_catalogue(payload, "2026-11-15T16:28:16Z")
        self.assertEqual(clean["models"][0]["slug"], "example")
        self.assertNotIn("access_token", json.dumps(clean))
        self.assertNotIn("system_prompt", json.dumps(clean))
        with self.assertRaises(ValueError):
            server._sanitize_catalogue({"models": []}, "now")

    def test_openai_levels_override_stale_curated_tiers_without_sending_ultra(self):
        server = load_server()
        source = {"fetched_at": "2026-11-15T16:28:16Z", "models": [{
            "slug": "example-model", "visibility": "list", "supported_in_api": True,
            "supported_reasoning_levels": [{"effort": e} for e in ["low", "high", "max", "ultra"]],
            "default_reasoning_level": "low", "multi_agent_reasoning_effort": "high",
        }]}
        caps = {"alias": {"supported_efforts": ["none", "minimal", "low"], "mandatory": False}}
        result = server._annotate([{"id": "alias"}], caps, source, {"alias": "chatgpt/example-model"})[0]
        self.assertEqual(result["reasoning"]["supported_efforts"], ["none", "low", "high", "max"])
        self.assertFalse(result["reasoning"]["mandatory"])
        self.assertEqual(result["reasoning"]["product_efforts"], ["low", "high", "max", "ultra"])
        self.assertEqual(result["reasoning"]["default_effort"], "low")
        self.assertEqual(result["reasoning"]["source"], "openai-codex")


if __name__ == "__main__":
    unittest.main()
