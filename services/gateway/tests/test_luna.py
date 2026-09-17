import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.luna import LunaClient, LunaCoordinator
from coordinator.models import Approval, PlanVersion
from coordinator.state import StateStore


class FakeIssues:
    def __init__(self):
        self.parent = "https://github.com/t/c/issues/1"
        self.children = ["https://github.com/t/c/issues/2", "https://github.com/t/c/issues/3"]
        self.comments = []

    def publish_plan(self, plan): return self.parent
    def create_deliverables(self, plan, parent_url): return self.children
    def update_issue_state(self, issue_url, state): pass
    def remove_label(self, issue_url, label): pass
    def comment(self, issue_url, body, marker=None):
        self.comments.append((issue_url, body, marker))
        return issue_url + "#comment"


class FakeForeman:
    def __init__(self):
        self.created = []
        self.task_items = []

    def ensure_workload(self, **values):
        self.created.append(values)
        position = values["deliverable_position"]
        return {"metadata": {"name": f"workload-{position}"},
                "status": {"phase": "Planning"}}

    @staticmethod
    def summary(value):
        return {"phase": value.get("status", {}).get("phase", "Pending"),
                "succeeded": 0, "failed": 0, "incomplete": 1,
                "contradicted": 0, "review_iterations": 0, "conditions": []}

    def tasks(self, workload_name):
        return self.task_items


class DispatchingLuna:
    def run(self, context, execute):
        pending = next((item for item in context["deliverables"]
                        if item["state"] == "pending"), None)
        actions = []
        if pending:
            result = execute("create_workload", {"issue": pending["issue_url"]}, "dispatch")
            actions.append({"tool": "create_workload", "result": result})
        return {"summary": "Coordination complete.", "actions": actions,
                "input_tokens": 120, "output_tokens": 30}


class ScriptedLunaClient(LunaClient):
    def __init__(self):
        super().__init__("test")
        self.responses = iter([
            {"usage": {"input_tokens": 10, "output_tokens": 3}, "output": [{
                "type": "function_call", "name": "post_thread", "call_id": "call-1",
                "arguments": '{"text":"Working"}',
            }]},
            {"usage": {"input_tokens": 12, "output_tokens": 4},
             "output_text": "Done", "output": []},
        ])

    def _response(self, input_items):
        return next(self.responses)


class LunaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.issues, self.foreman = FakeIssues(), FakeForeman()
        self.core = Coordinator(self.state, self.issues, {"@tim:x"})
        plan = PlanVersion(
            "plan-luna", 1,
            "# Plan\n\n## Deliverables\n- [ ] First\n- [ ] Second\n",
            "!project:x", "$root", "https://github.com/t/c.git",
        )
        self.core.record_plan(plan)
        self.core.approve(Approval(
            plan.plan_id, plan.hash, "$approve", "@tim:x", "2026-09-13T00:00:00Z"))
        self.luna = LunaCoordinator(
            self.state, self.core, self.foreman, self.issues, object(),
            DispatchingLuna(), "!implementation:x",
        )

    def tearDown(self): self.state.close(); self.tmp.close()

    def test_approved_deliverables_are_dispatched_by_durable_luna_turns(self):
        self.assertTrue(self.luna.reconcile_once())
        self.assertEqual([item["deliverable_position"] for item in self.foreman.created], [1])
        self.assertIn("First", self.foreman.created[0]["intent"])
        self.assertNotIn("Second", self.foreman.created[0]["intent"])
        usage = self.state.luna_usage("plan-luna")
        self.assertEqual(usage, {"turns": 1, "input_tokens": 120, "output_tokens": 30})
        pending = self.state.pending_matrix(100)
        root = next(item for item in pending if item["notification_id"].endswith(":root"))
        self.assertEqual(root["room_id"], "!implementation:x")
        self.assertIn("Implementing plan", root["body"])

        self.state.begin_merge(
            "plan-luna", 1, "https://github.com/t/c/pull/4", "a" * 40, None,
            {"status": "merged"})
        self.state.finish_merge("plan-luna", 1, {"status": "merged"})
        self.state.enqueue_coordinator_event(
            "merge:first", "plan-luna", "gateway", "deliverable.merged",
            {"position": 1}, delay_seconds=0)
        self.assertTrue(self.luna.reconcile_once())
        self.assertEqual([item["deliverable_position"] for item in self.foreman.created], [1, 2])

    def test_responses_tool_loop_accumulates_usage(self):
        calls = []
        result = ScriptedLunaClient().run(
            {"plan": {"id": "p"}},
            lambda name, args, call_id: calls.append((name, args, call_id)) or {"queued": True},
        )
        self.assertEqual(calls, [("post_thread", {"text": "Working"}, "call-1")])
        self.assertEqual(result["summary"], "Done")
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (22, 7))

    def test_turn_cap_stops_before_calling_model(self):
        self.luna.turn_cap = 0
        # Constructor normally clamps this; force the boundary for the test.
        self.assertTrue(self.luna.reconcile_once())
        self.assertEqual(self.foreman.created, [])
        self.assertEqual(self.state.plan("plan-luna")["state"], "needs_input")

    def test_failed_deliverable_retry_gets_a_new_workload_attempt(self):
        self.assertTrue(self.luna.reconcile_once())
        self.state.fail_deliverable("plan-luna", 1, {"status": "failed"})
        result = self.luna._execute_once(
            self.state.plan("plan-luna"), "retry-batch", "retry_workload", {
                "issue": self.issues.children[0], "diagnosis": "Gate image lacked a tool.",
            })
        self.assertTrue(result["created"])
        self.assertEqual(result["name"], "workload-1")
        self.assertEqual(self.foreman.created[-1]["attempt"], 2)
        self.assertIn("Gate image", self.issues.comments[0][1])

    def test_validation_rejection_is_a_durable_tool_result(self):
        self.state.set_plan_state("plan-luna", "review")
        plan = self.state.plan("plan-luna")
        result = self.luna._execute(
            plan, "invalid-batch", "create_workload",
            {"issue": self.issues.children[0]}, "invalid-call",
        )
        self.assertEqual(result, {
            "ok": False, "error": "plan state does not allow Workload creation",
        })
        row = self.state.db.execute(
            "SELECT state,last_error FROM external_actions WHERE action_key=?",
            ("invalid-batch:invalid-call:create_workload",),
        ).fetchone()
        self.assertEqual((row["state"], row["last_error"]), ("complete", None))
        self.assertEqual(
            self.luna._execute(
                plan, "invalid-batch", "create_workload",
                {"issue": self.issues.children[0]}, "invalid-call",
            ),
            result,
        )

    def test_luna_replan_immediately_unfreezes_the_plan(self):
        result = self.luna._execute_once(
            self.state.plan("plan-luna"), "replan-batch", "request_replan",
            {"reason": "The approach conflicts with the repository architecture."},
        )
        self.assertTrue(result["queued"])
        self.assertIsNone(self.state.approval("plan-luna"))
        self.assertEqual(self.state.plan("plan-luna")["state"], "review")
        # GitHub's eventual unlabeled echo must not enqueue a second transition.
        before = self.state.audit_count("plan-luna", "plan.approval-removed")
        self.core.reopen_review(self.issues.parent, "owner", "echo")
        self.assertEqual(
            self.state.audit_count("plan-luna", "plan.approval-removed"), before)

    def test_task_packet_is_structured_and_bounded(self):
        self.foreman.get_task = lambda name: {
            "metadata": {"labels": {"cogito.dev/plan-id": "plan-luna"}},
            "spec": {"agentRef": {"name": "scout"}},
            "status": {"phase": "Succeeded", "verdict": "GO", "result": {
                "summary": '{"conclusion":"Found it","confidence":"high",'
                           '"evidence":[{"path":"x.py","line":4,"note":"proof"}],'
                           '"uncertainty":"","suggested_followups":[],"artifacts":[]}'
            }},
        }
        result = self.luna._execute_once(
            self.state.plan("plan-luna"), "packet", "task_packet", {"name": "scout-1"})
        self.assertEqual(result["packet"]["conclusion"], "Found it")
        self.assertEqual(result["packet"]["evidence"][0]["line"], 4)

    def test_task_packet_accepts_workload_name_and_lists_children(self):
        self.assertTrue(self.luna.reconcile_once())
        self.foreman.task_items = [{
            "metadata": {"name": "workload-1-verify-2", "labels": {
                "cogito.dev/plan-id": "plan-luna"}},
            "spec": {"kind": "gate", "agentRef": {"name": "cogito-gate"}},
            "status": {"phase": "Succeeded", "verdict": "INCOMPLETE",
                       "failureReason": "AuthUnavailable"},
        }, {
            "metadata": {"name": "workload-1-coder-2", "labels": {
                "cogito.dev/plan-id": "plan-luna"}},
            "spec": {"kind": "issue-fix", "agentRef": {"name": "cogito-coder"}},
            "status": {"phase": "Succeeded", "verdict": "GO"},
        }]
        result = self.luna._execute_once(
            self.state.plan("plan-luna"), "packet-index", "task_packet",
            {"name": "workload-1"})
        self.assertEqual([item["name"] for item in result["tasks"]],
                         ["workload-1-coder-2", "workload-1-verify-2"])
        self.assertEqual(result["tasks"][1]["failure_reason"], "AuthUnavailable")
        self.assertFalse(result["truncated"])


class PhaseGuardTests(unittest.TestCase):
    """Luna must only act on plans that are actually under execution."""

    def test_batch_for_an_unapproved_plan_is_retired_without_a_turn(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            state.begin_intake(
                "plan-drafting", "!room:x", "$root", "https://github.com/t/c.git")
            state.set_plan_state("plan-drafting", "researching")
            state.enqueue_coordinator_event(
                "gh:1", "plan-drafting", "github", "github.push.event", {}, 0)

            luna = LunaCoordinator(
                state, None, None, None, None, _ExplodingClient(),
                implementation_room_id="!impl:x")
            self.assertTrue(luna.reconcile_once())

            # No turn spent, no implementation thread opened, state untouched.
            self.assertEqual(state.luna_usage("plan-drafting")["turns"], 0)
            self.assertEqual(state.luna_usage("plan-drafting")["input_tokens"], 0)
            self.assertEqual(state.plan("plan-drafting")["state"], "researching")
            self.assertEqual(
                [row for row in state.pending_matrix(50)
                 if row["room_id"] == "!impl:x"], [])
            state.close()

    def test_a_failing_turn_cannot_resurrect_a_cancelled_plan(self):
        """A terminal plan must stay terminal.

        needs_input is an attributable state, so resurrecting a cancelled plan
        re-opened it to repository events; the next push queued another turn,
        which failed and resurrected it again.
        """
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            state.begin_intake(
                "plan-gone", "!room:x", "$root", "https://github.com/t/c.git")
            state.enqueue_coordinator_event(
                "gh:1", "plan-gone", "github", "github.push.event", {}, 0)
            batch = state.next_luna_batch(now=2**31)
            state.set_plan_state("plan-gone", "cancelled")

            for _ in range(6):
                state.fail_luna_turn(batch["sequence"], "boom")

            self.assertEqual(state.plan("plan-gone")["state"], "cancelled")
            self.assertEqual(
                [row["plan_id"] for row
                 in state.active_plans_for_repository("https://github.com/t/c")],
                [])
            state.close()

    def test_needs_input_card_edit_carries_a_mention(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            state.begin_intake(
                "plan-x", "!room:x", "$root", "https://github.com/t/c.git")
            state.set_plan_state("plan-x", "researching")
            state.complete_matrix("plan:plan-x:card", "$card")
            state.set_plan_state("plan-x", "needs_input")
            edits = [row for row in state.pending_matrix(50) if row["kind"] == "edit"]
            self.assertTrue(edits)
            self.assertIn("NEEDS_INPUT", edits[-1]["body"])
            self.assertEqual(edits[-1]["mention"], 1)
            state.close()


class _ExplodingClient:
    """Any call here means the guard failed to stop the turn."""

    def run(self, *args, **kwargs):
        raise AssertionError("Luna ran a turn for a plan not under execution")



if __name__ == "__main__": unittest.main()
