import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.models import Approval, PlanVersion, ValidationError
from coordinator.state import StateStore


class FakeIssues:
    def __init__(self):
        self.calls = 0
        self.closed = []

    def create_plan(self, plan):
        self.calls += 1
        return "https://github.com/timblakely/cogito/issues/10", ["https://github.com/timblakely/cogito/issues/11"]

    def get_issue(self, url):
        return {"html_url": url, "title": "One", "state": "closed"}

    def close_issue(self, url):
        self.closed.append(url)
        return {"html_url": url, "title": "One", "state": "closed"}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.issues = FakeIssues()
        self.core = Coordinator(self.state, self.issues, {"@tim:matrix.timblakely.com"})
        self.plan = PlanVersion(
            "plan-1", 1, "# Test\n\n## Deliverables\n- [ ] One\n",
            "!room:matrix.timblakely.com", "$plan", "https://github.com/timblakely/cogito.git")
        self.core.record_plan(self.plan)

    def tearDown(self):
        self.state.close()
        self.tmp.close()

    def approval(self, **values):
        args = dict(plan_id="plan-1", plan_hash=self.plan.hash, matrix_event_id="$approval",
                    approver="@tim:matrix.timblakely.com", approved_at="2026-09-10T00:00:00Z")
        args.update(values)
        return Approval(**args)

    def test_exact_current_version_creates_issue_hierarchy(self):
        parent, children = self.core.approve(self.approval())
        self.assertEqual(parent.rsplit("/", 1)[-1], "10")
        self.assertEqual(len(children), 1)
        self.assertEqual(self.issues.calls, 1)
        self.assertIsNotNone(self.state.work_item_context(parent))
        self.assertIsNotNone(self.state.work_item_context(children[0]))
        replay_parent, replay_children = self.core.approve(self.approval())
        self.assertEqual((replay_parent, replay_children), (parent, children))
        self.assertEqual(self.issues.calls, 1)

    def test_wrong_hash_and_wrong_actor_fail(self):
        with self.assertRaises(ValidationError):
            self.core.approve(self.approval(plan_hash="sha256:" + "0" * 64))
        with self.assertRaises(ValidationError):
            self.core.approve(self.approval(approver="@mallory:example.com"))

    def test_obsolete_version_cannot_be_approved(self):
        old_hash = self.plan.hash
        self.core.record_plan(PlanVersion(
            "plan-1", 2, "# Revised\n", "!room:matrix.timblakely.com", "$plan2",
            "https://github.com/timblakely/cogito.git"))
        with self.assertRaises(ValidationError):
            self.core.approve(self.approval(plan_hash=old_hash))

    def test_github_event_reconciles_once_and_queues_matrix(self):
        parent, children = self.core.approve(self.approval())
        payload = {"action": "closed", "issue": {
            "html_url": children[0], "title": "One", "state": "closed"}}
        self.assertTrue(self.core.github_event("delivery-1", "issues", payload))
        self.assertFalse(self.core.github_event("delivery-1", "issues", payload))
        outbox = self.state.pending_matrix()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["notification_id"], "github:delivery-1")
        self.assertTrue(self.state.complete_matrix("github:delivery-1", "$sent"))
        self.assertFalse(self.state.complete_matrix("github:delivery-1", "$sent-again"))

    def test_periodic_github_reconciliation(self):
        self.core.approve(self.approval())
        self.assertEqual(self.core.reconcile_github(), 2)
        self.assertEqual(self.core.reconcile_github(), 0)

    def test_completed_deliveries_close_parent_and_plan_once(self):
        parent, children = self.core.approve(self.approval())
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO runs(run_id,work_item_external_id,state,request_json) VALUES (?,?,?,?)",
                ("run-1", children[0], "succeeded", "{}"),
            )
            db.execute(
                "INSERT INTO deliveries(work_item_external_id,worker_run_id,worker_harness,state) "
                "VALUES (?,?,?,'merged')", (children[0], "run-1", "pi"),
            )
        self.assertEqual(self.core.reconcile_github(), 3)
        self.assertEqual(self.issues.closed, [parent])
        self.assertEqual(self.state.plan_for_thread(
            self.plan.matrix_room_id, self.plan.matrix_event_id)["state"], "complete")
        self.assertEqual(self.core.reconcile_github(), 0)
        self.assertEqual(self.issues.closed, [parent])
        self.assertEqual(len([
            row for row in self.state.pending_matrix()
            if row["notification_id"] == "plan-complete:plan-1"]), 1)


if __name__ == "__main__":
    unittest.main()
