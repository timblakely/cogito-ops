import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.matrix import MatrixCoordinator
from coordinator.models import ValidationError
from coordinator.state import StateStore


class FakePlanner:
    def __init__(self):
        self.calls = 0
        self.decisions = []
        self.research = []
    def intake(self, messages, force=False, research=None):
        self.calls += 1
        self.research.append(research or [])
        if self.decisions:
            decision = self.decisions.pop(0)
            if force and decision["status"] != "ready":
                return {"status": "ready", "message": "Drafting with assumptions.",
                        "plan_markdown": "# Forced\n\n## Deliverables\n- [ ] Ship it\n"}
            return decision
        if any(message.get("kind") == "prior_plan" for message in messages):
            return {"status": "ready", "message": "Revision ready.",
                    "plan_markdown": "# Test revised\n\n## Deliverables\n- [ ] Ship it\n"}
        return {"status": "ready", "message": "This is ready to plan.",
                "plan_markdown": "# Test\n\n## Deliverables\n- [ ] Ship it\n"}
    def plan(self, objective, prior="", comments=None):
        self.calls += 1
        suffix = " revised" if prior else ""
        return f"# Test{suffix}\n\n## Deliverables\n- [ ] Ship it\n"


class FakeIssues:
    def __init__(self):
        self.calls = 0
        self.children = ["https://github.com/t/c/issues/2"]
        self.merge_requests = []
    def create_plan(self, plan):
        self.calls += 1
        return "https://github.com/t/c/issues/1", self.children
    def request_merge(self, pr_url, head_sha, branch):
        self.merge_requests.append((pr_url, head_sha, branch))
        return {"status": "pending", "uuid": f"merge-{len(self.merge_requests)}"}
    def merge_result(self, pr_url, merge_uuid):
        return {"status": "merged", "details": {"sha": "f" * 40}}


class FakeForeman:
    def __init__(self):
        self.created = []
        self.research_created = []
        self.research_phase = "Succeeded"
        self.phase = "Dispatched"
    def ensure_workload(self, **values):
        self.created.append(values)
        position = values.get("deliverable_position", 1)
        return {"metadata": {"name": f"plan-test-d{position}"},
                "status": {"phase": "Planning"}}
    def get(self, name):
        return {"metadata": {"name": name}, "status": {
            "phase": self.phase, "succeededTasks": 4 if self.phase == "Completed" else 1,
        }}
    def ensure_research_task(self, **values):
        self.research_created.append(values)
        return {"metadata": {"name": values["task_name"]}, "status": {
            "phase": self.research_phase,
            "result": {"summary": "The relevant implementation is in coordinator/matrix.py."},
        }}
    def get_task(self, name):
        return {"metadata": {"name": name}, "status": {
            "phase": self.research_phase,
            "result": {"summary": "The relevant implementation is in coordinator/matrix.py."},
        }}
    def merge_candidate(self, name, quorum=2):
        position = name.rsplit("d", 1)[-1]
        return {"pr_url": f"https://github.com/t/c/pull/{position}",
                "head_sha": position * 40,
                "branch": f"foreman/plan/issue-{position}",
                "reviewers": ["reviewer", "falsifier"]}
    @staticmethod
    def summary(value):
        status = value.get("status", {})
        return {"phase": status.get("phase", "Pending"),
                "succeeded": status.get("succeededTasks", 0),
                "failed": status.get("failedTasks", 0),
                "incomplete": status.get("incompleteTasks", 0),
                "contradicted": 0, "review_iterations": 0, "conditions": []}


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.planner, self.issues, self.foreman = FakePlanner(), FakeIssues(), FakeForeman()
        core = Coordinator(self.state, self.issues, {"@tim:matrix.example"})
        self.matrix = MatrixCoordinator(
            self.state, core, self.foreman, self.planner, {"@tim:matrix.example"},
            "!activity:matrix.example",
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
        self.matrix.handle(self.event("$comment", "Add rollback", "$root"))
        plan = self.state.plan_for_thread("!room:matrix.example", "$root")
        self.assertEqual(self.state.plan_comments(plan["plan_id"]), ["Add rollback"])
        revised = self.matrix.handle(self.event("$revise", "!cogito revise", "$root"))
        revised_hash = revised["actions"][0]["body"].split("Plan hash: `", 1)[1].split("`", 1)[0]
        with self.assertRaises(ValidationError):
            self.matrix.handle(self.event("$old", f"!cogito approve {digest}", "$root"))
        accepted = self.matrix.handle(
            self.event("$accepted", f"!cogito approve {revised_hash}", "$root"))
        self.assertIn("Parent issue", accepted["actions"][0]["body"])
        self.assertIn("Foreman Workload", accepted["actions"][0]["body"])
        self.assertEqual(len(self.foreman.created), 1)
        self.assertEqual(self.planner.calls, 2)
        self.assertEqual(self.issues.calls, 1)

    def test_intake_clarification_reply_then_plan(self):
        self.planner.decisions = [
            {"status": "clarify", "message": "Which namespace should own it?"},
            {"status": "ready", "message": "That resolves the boundary.",
             "plan_markdown": "# Namespaced\n\n## Deliverables\n- [ ] Ship it\n"},
        ]
        first = self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        self.assertIn("Which namespace", first["actions"][0]["body"])
        row = self.state.plan_for_thread("!room:matrix.example", "$root")
        self.assertEqual(row["state"], "intake")
        second = self.matrix.handle(self.event("$answer", "Use home-infra", "$root"))
        self.assertIn("# Namespaced", second["actions"][0]["body"])
        self.assertEqual(self.state.plan(row["plan_id"])["state"], "review")

    def test_draft_command_forces_plan_during_intake(self):
        self.planner.decisions = [
            {"status": "clarify", "message": "Which namespace should own it?"},
            {"status": "clarify", "message": "Still need a namespace."},
        ]
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        result = self.matrix.handle(self.event("$draft", "!cogito draft", "$root"))
        self.assertIn("# Forced", result["actions"][0]["body"])

    def test_intake_automatically_drafts_after_two_rounds(self):
        self.planner.decisions = [
            {"status": "clarify", "message": "Question one?"},
            {"status": "pushback", "message": "Concern two."},
            {"status": "clarify", "message": "Would otherwise ask again."},
        ]
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        self.matrix.handle(self.event("$answer1", "Answer one", "$root"))
        result = self.matrix.handle(self.event("$answer2", "Proceed", "$root"))
        self.assertIn("# Forced", result["actions"][0]["body"])

    def test_research_is_delegated_to_foreman_then_synthesized(self):
        self.planner.decisions = [
            {"status": "delegate", "message": "I need the current boundaries.",
             "tasks": ["Inspect the coordinator planning boundary."]},
            {"status": "ready", "message": "Research resolved it.",
             "plan_markdown": "# Researched\n\n## Deliverables\n- [ ] Ship it\n"},
        ]
        first = self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        self.assertIn("local planning scouts", first["actions"][0]["body"])
        plan = self.state.plan_for_thread("!room:matrix.example", "$root")
        self.assertEqual(plan["state"], "researching")
        self.matrix.reconcile_once()
        self.assertEqual(len(self.foreman.research_created), 1)
        self.assertIn("coordinator/matrix.py", self.planner.research[-1][0]["summary"])
        self.assertEqual(self.state.plan(plan["plan_id"])["state"], "review")
        messages = [item["body"] for item in self.state.pending_matrix()]
        self.assertTrue(any("# Researched" in body for body in messages))

    def test_revision_can_delegate_before_creating_version_two(self):
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        self.matrix.handle(self.event("$comment", "Confirm current boundaries", "$root"))
        self.planner.decisions = [
            {"status": "delegate", "message": "Checking the revision.",
             "tasks": ["Inspect the current boundary."]},
            {"status": "ready", "message": "Revision ready.",
             "plan_markdown": "# Version two\n\n## Deliverables\n- [ ] Ship it\n"},
        ]
        result = self.matrix.handle(self.event("$revise", "!cogito revise", "$root"))
        self.assertIn("local planning scouts", result["actions"][0]["body"])
        self.matrix.reconcile_once()
        plan = self.state.plan_for_thread("!room:matrix.example", "$root")
        self.assertEqual(plan["current_version"], 2)
        self.assertEqual(self.state.current_plan_version(plan["plan_id"])["markdown"],
                         "# Version two\n\n## Deliverables\n- [ ] Ship it\n")

    def test_status_and_draft_work_while_scouts_are_running(self):
        self.planner.decisions = [{
            "status": "delegate", "message": "Checking.", "tasks": ["Inspect it."]}]
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        status = self.matrix.handle(self.event("$status", "!cogito status", "$root"))
        self.assertIn("0/1 scout tasks", status["actions"][0]["body"])
        drafted = self.matrix.handle(self.event("$draft", "!cogito draft", "$root"))
        self.assertIn("# Test", drafted["actions"][0]["body"])

    def test_event_replay_returns_same_actions(self):
        value = self.event("$root", "!cogito plan Build it")
        first = self.matrix.handle(value)
        self.assertEqual(first, self.matrix.handle(value))
        self.assertEqual(self.planner.calls, 1)
        pending = self.state.pending_matrix()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["room_id"], "!room:matrix.example")
        self.assertEqual(pending[0]["thread_root"], "$root")
        self.assertEqual(pending[0]["body"], first["actions"][0]["body"])

    def test_command_response_is_durable_before_transport_delivery(self):
        result = self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        pending = self.state.pending_matrix()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["body"], result["actions"][0]["body"])

    def test_thread_approval_resolves_current_version(self):
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        value = self.event("$approve", "!cogito approve", "$root")
        value["timestamp"] = "2099-01-01T00:00:00Z"
        accepted = self.matrix.handle(value)
        self.assertIn("Plan accepted", accepted["actions"][0]["body"])

    def test_delayed_thread_approval_cannot_accept_newer_version(self):
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        with self.assertRaisesRegex(ValidationError, "plan changed"):
            self.matrix.handle(self.event("$approve", "!cogito approve", "$root"))

    def test_status_reads_foreman_workload(self):
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        approval = self.event("$approve", "!cogito approve", "$root")
        approval["timestamp"] = "2099-01-01T00:00:00Z"
        self.matrix.handle(approval)
        result = self.matrix.handle(self.event("$status", "!cogito status", "$root"))
        self.assertIn("**Dispatched**", result["actions"][0]["body"])
        self.assertIn("1 succeeded", result["actions"][0]["body"])

    def test_multi_deliverable_plan_merges_serially_after_quorum(self):
        self.issues.children = [
            "https://github.com/t/c/issues/2", "https://github.com/t/c/issues/3",
        ]
        self.matrix.handle(self.event("$root", "!cogito plan Build it"))
        approval = self.event("$approve", "!cogito approve", "$root")
        approval["timestamp"] = "2099-01-01T00:00:00Z"
        self.matrix.handle(approval)
        self.assertEqual([call["deliverable_position"] for call in self.foreman.created], [1])

        self.foreman.phase = "Completed"
        self.matrix.reconcile_once()
        self.assertEqual([call["deliverable_position"] for call in self.foreman.created], [1, 2])
        self.assertEqual(self.state.plan_progress("plan-" + __import__(
            "hashlib").sha256(b"$root").hexdigest()[:16])["merged"], 1)

        self.matrix.reconcile_once()
        plan = self.state.plan_for_thread("!room:matrix.example", "$root")
        self.assertEqual(plan["state"], "completed")
        messages = [item["body"] for item in self.state.pending_matrix()]
        self.assertTrue(any("every approved deliverable merged" in body for body in messages))
        activity = [item for item in self.state.pending_matrix()
                    if item["room_id"] == "!activity:matrix.example"]
        self.assertTrue(any("review quorum" in item["body"] for item in activity))
        self.assertTrue(all(item["thread_root"] == "" for item in activity))

    def test_non_command_outside_plan_thread_is_ignored(self):
        self.assertEqual(self.matrix.handle(self.event("$chat", "ordinary chat")), {"actions": []})
        self.assertEqual(
            self.matrix.handle(self.event("$other", "thread chat", "$unrelated")),
            {"actions": []},
        )

    def test_untrusted_sender_is_rejected(self):
        value = self.event("$root", "!cogito help")
        value["sender"] = "@mallory:matrix.example"
        with self.assertRaises(ValidationError): self.matrix.handle(value)

if __name__ == "__main__": unittest.main()
