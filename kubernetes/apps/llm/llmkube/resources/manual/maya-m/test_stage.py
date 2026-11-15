import hashlib
import http.server
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import stage


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hot = self.root / "hot"
        self.cold = self.root / "cold"
        self.hot.mkdir()
        self.cold.mkdir()
        self.data = b"maya pinned artifact fixture\n" * 100
        self.want = hashlib.sha256(self.data).hexdigest()
        self.name = "fixture.gguf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_cold_avoids_isp(self):
        (self.cold / self.name).write_bytes(self.data)
        with mock.patch.object(stage, "download", side_effect=AssertionError("ISP must not be used")):
            stage.stage_file(self.hot, self.cold, self.name, len(self.data), self.want, "http://unused")
        self.assertEqual((self.hot / self.name).read_bytes(), self.data)

    def test_hot_is_archived_and_copy_resumes(self):
        (self.hot / self.name).write_bytes(self.data)
        (self.cold / (self.name + ".partial")).write_bytes(self.data[:200])
        with mock.patch.object(stage, "download", side_effect=AssertionError("ISP must not be used")):
            stage.stage_file(self.hot, self.cold, self.name, len(self.data), self.want, "http://unused")
        self.assertEqual((self.cold / self.name).read_bytes(), self.data)

    def test_bad_complete_file_is_preserved(self):
        wrong = b"x" * len(self.data)
        p = self.hot / self.name
        p.write_bytes(wrong)
        with self.assertRaises(ValueError):
            stage.stage_file(self.hot, self.cold, self.name, len(self.data), self.want, "http://unused")
        self.assertEqual(p.read_bytes(), wrong)

    def test_wrong_size_final_files_are_preserved_on_both_tiers(self):
        for tier in ("hot", "cold"):
            for wrong in (b"short", self.data + b"oversized"):
                with self.subTest(tier=tier, size=len(wrong)):
                    for root in (self.hot, self.cold):
                        for path in root.iterdir():
                            path.unlink()
                    source = self.cold if tier == "hot" else self.hot
                    target = self.hot if tier == "hot" else self.cold
                    (source / self.name).write_bytes(self.data)
                    original = target / self.name
                    original.write_bytes(wrong)
                    with self.assertRaises(ValueError):
                        stage.stage_file(self.hot, self.cold, self.name, len(self.data), self.want, "http://unused")
                    self.assertEqual(original.read_bytes(), wrong)

    def test_http_download_resumes_without_prefix_transfer(self):
        data = self.data
        received = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                start = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
                received.append(start)
                self.send_response(206 if start else 200)
                self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
                self.end_headers()
                self.wfile.write(data[start:])

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            target = self.hot / self.name
            target.with_name(target.name + ".partial").write_bytes(data[:200])
            stage.download(f"http://127.0.0.1:{server.server_port}/fixture", target, len(data), self.want)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(received, [200])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_wrong_copy_prefix_is_never_promoted(self):
        source = self.hot / self.name
        source.write_bytes(self.data)
        target = self.cold / self.name
        target.with_name(target.name + ".partial").write_bytes(b"bad")
        with self.assertRaises(ValueError):
            stage.copy_verified(source, target, len(self.data), self.want)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
