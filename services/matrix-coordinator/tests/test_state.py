import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from coordinator.state import StateStore


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)

    def tearDown(self):
        self.state.close()
        self.tmp.close()

    def test_event_replay_is_ignored(self):
        self.assertTrue(self.state.accept_event("matrix", "$event", "sha256:a"))
        self.assertFalse(self.state.accept_event("matrix", "$event", "sha256:a"))

    def test_concurrent_replay_is_recorded_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(
                lambda _: self.state.accept_event("github", "delivery-1", "sha256:b"),
                range(32),
            ))
        self.assertEqual(accepted.count(True), 1)

    def test_audit_is_append_only(self):
        sequence = self.state.audit("test", "created", "plan-1", {"safe": True})
        with self.assertRaises(sqlite3.IntegrityError):
            self.state.db.execute("DELETE FROM audit_events WHERE sequence=?", (sequence,))


if __name__ == "__main__":
    unittest.main()
