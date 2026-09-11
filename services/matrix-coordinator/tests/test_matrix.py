import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.deliveries import DeliveryCoordinator
from coordinator.matrix import MatrixCoordinator
from coordinator.models import ValidationError
from coordinator.runs import RunCoordinator
from coordinator.state import StateStore


class FakePlanner:
    def __init__(self): self.calls = 0
    def plan(self, objective, prior="", comments=None):
        self.calls += 1
        suffix = " revised" if prior else ""
        return f"# Test{suffix}\n\n## Deliverables\n- [ ] Ship it\n"


class FakeIssues:
    def __init__(self): self.calls = 0
    def create_plan(self, plan):
        self.calls += 1
        return "https://github.com/t/c/issues/1", ["https://github.com/t/c/issues/2"]


class FakeArgo:
    def find_run(self, run_id): return None
    def submit(self, run, harness): return "agent-run-1"
    def status(self, name): return {"status": {"phase": "Pending"}}
    def cancel(self, name): return {}
    def resume(self, name): return {}
    def pause(self, name): return {}


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.planner, self.issues, self.argo = FakePlanner(), FakeIssues(), FakeArgo()
        core = Coordinator(self.state, self.issues, {"@tim:matrix.example"})
        runs = RunCoordinator(self.state, self.argo)
        self.matrix = MatrixCoordinator(
            self.state, core, runs, DeliveryCoordinator(self.state, runs, self.issues), self.planner,
            {"@tim:matrix.example"},
        )
        self.base = {
            "room_id": "!room:matrix.example", "sender": "@tim:matrix.example",
            "timestamp": "2026-09-10T00:00:00Z",
        }

    def tearDown(self): self.state.close(); self.tmp.close()

    def event(self, event_id, body, thread_root=None):
        value = {**self.base, "event_id": event_id, "body": body}
        if thread_root: value["thread_root"] = thread_root
        return value

    def test_plan_comment_revision_and_exact_approval(self):
        first = self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        digest = first["actions"][0]["body"].split("Plan hash: `", 1)[1].split("`", 1)[0]
        self.matrix.handle(self.event("$comment", ">> Add rollback", "$root"))
        revised = self.matrix.handle(self.event("$revise", "!cogito revise", "$root"))
        revised_hash = revised["actions"][0]["body"].split("Plan hash: `", 1)[1].split("`", 1)[0]
        with self.assertRaises(ValidationError):
            self.matrix.handle(self.event("$old", f"!cogito approve {digest}", "$root"))
        accepted = self.matrix.handle(
            self.event("$accepted", f"!cogito approve {revised_hash}", "$root"))
        self.assertIn("Parent issue", accepted["actions"][0]["body"])
        self.assertIn("Dispatched runs", accepted["actions"][0]["body"])
        self.assertEqual(len(self.state.active_runs()), 1)
        self.assertEqual(self.state.active_runs()[0]["request_json"].count('"harness": "pi"'), 1)
        self.assertEqual(self.planner.calls, 2)
        self.assertEqual(self.issues.calls, 1)

    def test_event_replay_returns_same_actions(self):
        value = self.event("$root", "!cogito plan Build it")
        self.assertEqual(self.matrix.handle(value), self.matrix.handle(value))
        self.assertEqual(self.planner.calls, 1)

    def test_untrusted_sender_is_rejected(self):
        value = self.event("$root", "!cogito help")
        value["sender"] = "@mallory:matrix.example"
        with self.assertRaises(ValidationError): self.matrix.handle(value)

    def test_emergency_stop_is_durable(self):
        result = self.matrix.handle(self.event("$stop", "!cogito stop"))
        self.assertIn("Emergency stop active", result["actions"][0]["body"])
        self.assertEqual(self.state.control("emergency_stop"), "true")
        self.matrix.handle(self.event("$start", "!cogito start"))
        self.assertEqual(self.state.control("emergency_stop"), "false")


if __name__ == "__main__": unittest.main()
