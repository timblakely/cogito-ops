import json
import tempfile
import unittest

from coordinator.deliveries import DeliveryCoordinator
from coordinator.models import AgentRun
from coordinator.runs import RunCoordinator
from coordinator.state import StateStore


class FakeArgo:
    def __init__(self): self.count = 0
    def find_run(self, run_id): return None
    def submit(self, run, harness):
        self.count += 1
        return f"workflow-{self.count}"
    def status(self, name): return {"status": {"phase": "Pending"}}
    def cancel(self, name): return {}
    def resume(self, name): return {}
    def pause(self, name): return {}


class FakeGitHub:
    def __init__(self): self.reviews = []; self.merges = []; self.closed = []
    def create_pull_request(self, run, result): return "https://github.com/o/r/pull/3"
    def add_review_evidence(self, url, run_id, summary): self.reviews.append((url, run_id))
    def merge_pull_request(self, url, head):
        self.merges.append((url, head)); return "f" * 40
    def close_superseded_pull(self, url, reason): self.closed.append(url)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.argo, self.github = FakeArgo(), FakeGitHub()
        self.runs = RunCoordinator(self.state, self.argo)
        self.delivery = DeliveryCoordinator(self.state, self.runs, self.github)
        self.run = AgentRun("worker-run-0001", "https://github.com/o/r/issues/2", "worker",
                            "https://github.com/o/r.git", "main", "implement")
        self.runs.submit(self.run, "pi")
        self.delivery.register(self.run, "pi")

    def tearDown(self): self.state.close(); self.tmp.close()

    def finish(self, run_id, result):
        self.state.update_run(run_id, result["status"], result)

    def test_low_risk_delivery_opens_reviews_and_merges(self):
        self.finish(self.run.run_id, {
            "run_id": self.run.run_id, "status": "succeeded", "summary": "done",
            "head_sha": "a" * 40, "usage": {
                "published_ref": "refs/heads/agent/worker-run-0001",
                "changed_paths": ["docs/example.md"]},
        })
        self.assertEqual(self.delivery.reconcile_once(), 1)
        row = self.state.delivery_for_run(self.run.run_id)
        self.assertEqual(row["state"], "review_running")
        review_id = row["reviewer_run_id"]
        self.finish(review_id, {
            "run_id": review_id, "status": "succeeded",
            "summary": "Looks good. COGITO_REVIEW: APPROVE",
            "head_sha": "a" * 40, "usage": {"review_verdict": "approve"},
        })
        self.assertEqual(self.delivery.reconcile_once(), 1)
        self.assertEqual(self.state.delivery_for_run(self.run.run_id)["state"], "ready_to_merge")
        self.assertEqual(self.delivery.reconcile_once(), 1)
        self.assertEqual(self.state.delivery_for_run(self.run.run_id)["state"], "merged")
        self.assertEqual(len(self.github.reviews), 1)
        self.assertEqual(len(self.github.merges), 1)

    def test_failed_worker_gets_one_bounded_repair(self):
        original = AgentRun(**{**self.run.__dict__, "limits": {"attempts": 2}})
        # Persist the limits in the already-registered run for this fixture.
        with self.state.transaction() as db:
            db.execute("UPDATE runs SET request_json=? WHERE run_id=?", (
                json.dumps({**original.as_dict(), "harness": "pi"}, sort_keys=True), self.run.run_id))
        self.finish(self.run.run_id, {
            "run_id": self.run.run_id, "status": "failed", "summary": "temporary failure"})
        self.assertEqual(self.delivery.reconcile_once(), 1)
        repaired = self.state.delivery_for_run(self.run.run_id)
        self.assertIsNone(repaired)
        rows = self.state.deliveries()
        self.assertEqual(rows[0]["repair_attempts"], 1)
        self.assertTrue(rows[0]["worker_run_id"].startswith("repair-"))

    def test_missing_review_verdict_gets_bounded_repair(self):
        original = AgentRun(**{**self.run.__dict__, "limits": {"attempts": 2}})
        with self.state.transaction() as db:
            db.execute("UPDATE runs SET request_json=? WHERE run_id=?", (
                json.dumps({**original.as_dict(), "harness": "pi"}, sort_keys=True), self.run.run_id))
        self.finish(self.run.run_id, {
            "run_id": self.run.run_id, "status": "succeeded", "summary": "done",
            "head_sha": "a" * 40, "usage": {
                "published_ref": "refs/heads/agent/worker-run-0001",
                "changed_paths": ["docs/example.md"]},
        })
        self.delivery.reconcile_once()
        row = self.state.delivery_for_run(self.run.run_id)
        self.finish(row["reviewer_run_id"], {
            "run_id": row["reviewer_run_id"], "status": "succeeded",
            "summary": "review omitted its verdict", "head_sha": "a" * 40,
            "usage": {},
        })
        self.assertEqual(self.delivery.reconcile_once(), 1)
        repaired = self.state.deliveries()[0]
        self.assertEqual(repaired["state"], "worker_running")
        self.assertEqual(repaired["repair_attempts"], 1)
        self.assertTrue(repaired["worker_run_id"].startswith("repair-"))
        self.assertEqual(self.github.closed, ["https://github.com/o/r/pull/3"])


if __name__ == "__main__": unittest.main()
