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

    def test_v6_migration_drops_retired_executor_tables(self):
        path = self.tmp.name
        self.state.close()
        db = sqlite3.connect(path)
        db.executescript("""
            DELETE FROM migrations;
            INSERT INTO migrations VALUES (5, 0);
            CREATE TABLE runs (run_id TEXT);
            CREATE TABLE deliveries (run_id TEXT);
            CREATE TABLE work_items (external_id TEXT);
            CREATE TABLE controls (key TEXT);
        """)
        db.close()
        self.state = StateStore(path)
        names = {row[0] for row in self.state.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"runs", "deliveries", "work_items", "controls"}.isdisjoint(names))

    def test_workload_status_is_correlated_to_plan(self):
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?)",
                ("plan-workload", "decomposed", "https://github.com/o/r.git", "!r:x", "$root", 1),
            )
        self.state.register_workload("workload-1", "plan-workload", {"phase": "Planning"})
        self.assertEqual(self.state.workload_for_plan("plan-workload")["name"], "workload-1")
        self.assertTrue(self.state.update_workload("workload-1", {"phase": "Completed", "succeeded": 3}))
        self.assertEqual(self.state.plan_for_thread("!r:x", "$root")["state"], "completed")

    def test_prometheus_metrics_report_state_usage_and_artifacts(self):
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?)", ("metrics-plan", "complete", "https://github.com/o/r.git",
                "!room:x", "$root", 1),
            )
        metrics = self.state.prometheus_metrics()
        self.assertIn('cogito_coordinator_objects{kind="plan",state="complete"} 1', metrics)
        self.assertNotIn("run_usage", metrics)


if __name__ == "__main__":
    unittest.main()
