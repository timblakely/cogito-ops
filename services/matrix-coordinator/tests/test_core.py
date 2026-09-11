import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.models import Approval, PlanVersion, ValidationError
from coordinator.state import StateStore


class FakeIssues:
    def __init__(self):
        self.calls = 0

    def create_plan(self, plan):
        self.calls += 1
        return "https://github.com/timblakely/cogito/issues/10", ["https://github.com/timblakely/cogito/issues/11"]

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

if __name__ == "__main__":
    unittest.main()
