import sqlite3
import tempfile
import unittest
import json
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

    def test_restart_backfills_legacy_issue_hierarchy(self):
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?)",
                ("legacy-plan", "review", "https://github.com/o/r.git", "!r:x", "$root", 1),
            )
        self.state.begin_action("legacy", "github.create-plan", {"plan_id": "legacy-plan"})
        self.state.complete_action("legacy", {
            "parent": "https://github.com/o/r/issues/1",
            "children": ["https://github.com/o/r/issues/2"],
        })
        path = self.tmp.name
        self.state.close()
        self.state = StateStore(path)
        self.assertIsNotNone(self.state.work_item_context("https://github.com/o/r/issues/1"))
        self.assertIsNotNone(self.state.work_item_context("https://github.com/o/r/issues/2"))

    def test_prometheus_metrics_report_state_usage_and_artifacts(self):
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?)", ("metrics-plan", "complete", "https://github.com/o/r.git",
                "!room:x", "$root", 1),
            )
            db.execute(
                "INSERT INTO runs(run_id,work_item_external_id,state,request_json,result_json) "
                "VALUES (?,?,?,?,?)", ("metrics-run-0001", "https://github.com/o/r/issues/1",
                "succeeded", json.dumps({"role": "reviewer", "harness": "opencode"}),
                json.dumps({"usage": {"input_tokens": 12, "output_tokens": 3},
                            "artifacts": [{"name": "log", "digest": "sha256:a"}]})),
            )
        metrics = self.state.prometheus_metrics()
        self.assertIn('cogito_coordinator_objects{kind="plan",state="complete"} 1', metrics)
        self.assertIn(
            'cogito_coordinator_run_usage_tokens_total{role="reviewer",harness="opencode",'
            'direction="input"} 12', metrics)
        self.assertIn("cogito_coordinator_artifacts_total 1", metrics)


if __name__ == "__main__":
    unittest.main()
