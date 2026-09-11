import json
import tempfile
import unittest
from unittest.mock import patch

from coordinator.models import AgentRun, ValidationError
from coordinator.runs import RunCoordinator
from coordinator.state import StateStore


class FakeArgo:
    def __init__(self):
        self.submits = 0
        self.workflows = {}

    def find_run(self, run_id):
        return next((name for name, value in self.workflows.items()
                     if value["metadata"]["labels"]["cogito.dev/run-id"] == run_id), None)

    def submit(self, run, harness):
        self.submits += 1
        name = f"agent-run-{self.submits}"
        self.workflows[name] = {
            "metadata": {"labels": {"cogito.dev/run-id": run.run_id}},
            "status": {"phase": "Pending"},
        }
        return name

    def status(self, name):
        return self.workflows[name]

    def cancel(self, name):
        self.workflows[name]["status"] = {"phase": "Failed", "message": "terminated"}

    def resume(self, name):
        self.workflows[name]["status"] = {"phase": "Running"}

    def pause(self, name):
        self.workflows[name]["status"] = {"phase": "Pending", "message": "suspended"}


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()
        self.state = StateStore(self.tmp.name)
        self.argo = FakeArgo()
        self.runs = RunCoordinator(self.state, self.argo)
        self.run = AgentRun(
            "fixture-run-0001", "https://github.com/timblakely/cogito/issues/1", "worker",
            "https://github.com/timblakely/cogito.git", "main", "Run the fixture",
        )

    def tearDown(self):
        self.state.close(); self.tmp.close()

    def test_submission_and_replay_create_one_workflow(self):
        first = self.runs.submit(self.run, "contract")
        second = self.runs.submit(self.run, "contract")
        self.assertEqual(first, second)
        self.assertEqual(self.argo.submits, 1)

    def test_reconcile_persists_normalized_result(self):
        name = self.runs.submit(self.run, "contract")
        result = {"run_id": self.run.run_id, "status": "succeeded", "summary": "done"}
        self.argo.workflows[name]["status"] = {
            "phase": "Succeeded", "outputs": {"parameters": [
                {"name": "result-json", "value": json.dumps(result)}
            ]},
        }
        self.runs.reconcile_once()
        row = self.state.run(self.run.run_id)
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(json.loads(row["result_json"])["summary"], "done")

    def test_reconcile_reads_workflow_template_root_node_output(self):
        name = self.runs.submit(self.run, "contract")
        self.argo.workflows[name]["metadata"]["name"] = name
        result = {"run_id": self.run.run_id, "status": "succeeded", "summary": "root done"}
        self.argo.workflows[name]["status"] = {
            "phase": "Succeeded", "nodes": {name: {"outputs": {"parameters": [
                {"name": "result-json", "value": json.dumps(result)}
            ]}}},
        }
        self.runs.reconcile_once()
        row = self.state.run(self.run.run_id)
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(json.loads(row["result_json"])["summary"], "root done")

    def test_successful_workflow_preserves_failed_agent_result(self):
        name = self.runs.submit(self.run, "contract")
        result = {"run_id": self.run.run_id, "status": "failed", "summary": "model rejected request"}
        self.argo.workflows[name]["status"] = {
            "phase": "Succeeded", "outputs": {"parameters": [
                {"name": "result-json", "value": json.dumps(result)}
            ]},
        }
        self.runs.reconcile_once()
        self.assertEqual(self.state.run(self.run.run_id)["state"], "failed")

    def test_restart_recovers_unattached_submission(self):
        self.state.register_run(self.run.run_id, self.run.work_item,
                                {**self.run.as_dict(), "harness": "contract"})
        self.argo.submit(self.run, "contract")
        self.runs.reconcile_once()
        self.assertIsNotNone(self.state.run(self.run.run_id)["argo_name"])
        self.assertEqual(self.argo.submits, 1)

    def test_cancel_is_idempotent(self):
        self.runs.submit(self.run, "contract")
        self.runs.cancel(self.run.run_id)
        self.runs.reconcile_once()
        self.assertEqual(self.state.run(self.run.run_id)["state"], "cancelled")
        self.runs.cancel(self.run.run_id)

    def test_cancellation_intent_survives_running_phase(self):
        name = self.runs.submit(self.run, "contract")
        self.state.update_run(self.run.run_id, "cancelling")
        self.argo.workflows[name]["status"] = {"phase": "Running"}
        self.runs.reconcile_once()
        self.assertEqual(self.state.run(self.run.run_id)["state"], "cancelling")
        self.argo.workflows[name]["status"] = {"phase": "Failed", "message": "terminated"}
        self.runs.reconcile_once()
        self.assertEqual(self.state.run(self.run.run_id)["state"], "cancelled")

    def test_pause_and_resume(self):
        self.runs.submit(self.run, "contract")
        self.runs.pause(self.run.run_id)
        self.assertEqual(self.state.run(self.run.run_id)["state"], "paused")
        self.runs.resume(self.run.run_id)
        self.assertEqual(self.state.run(self.run.run_id)["state"], "submitted")

    def test_reusing_run_id_with_changed_request_fails(self):
        self.runs.submit(self.run, "contract")
        changed = AgentRun(**{**self.run.__dict__, "objective": "different"})
        with self.assertRaises(ValueError):
            self.runs.submit(changed, "contract")

    def test_unknown_harness_fails_closed(self):
        # The real Argo boundary validates before creating a Workflow; keep the
        # run coordinator's fake port contract explicit here.
        from coordinator.argo import ArgoClient
        client = ArgoClient()
        with self.assertRaises(ValidationError):
            client.submit(self.run, "shell; id")

    def test_concurrency_queues_and_later_dispatches(self):
        limited = RunCoordinator(self.state, self.argo, max_active=1)
        first = limited.submit(self.run, "contract")
        second_run = AgentRun(**{**self.run.__dict__, "run_id": "fixture-run-0002"})
        self.assertEqual(limited.submit(second_run, "contract"), "queued")
        self.assertEqual(self.state.run(second_run.run_id)["state"], "queued")
        result = {"run_id": self.run.run_id, "status": "succeeded", "summary": "done"}
        self.argo.workflows[first]["metadata"]["name"] = first
        self.argo.workflows[first]["status"] = {"phase": "Succeeded", "outputs": {
            "parameters": [{"name": "result-json", "value": json.dumps(result)}]}}
        limited.reconcile_once()
        limited.reconcile_once()
        self.assertEqual(self.state.run(second_run.run_id)["state"], "submitted")

    def test_dependency_queues_until_predecessor_closes(self):
        dependent = AgentRun(**{**self.run.__dict__,
            "run_id": "dependent-run-0001", "context": {"depends_on": "https://github.com/o/r/issues/1"}})
        with patch.object(self.state, "work_item_state", return_value="open"):
            self.assertEqual(self.runs.submit(dependent, "contract"), "queued")
            self.runs.reconcile_once()
            self.assertEqual(self.state.run(dependent.run_id)["state"], "queued")
        with patch.object(self.state, "work_item_state", return_value="closed"):
            self.runs.reconcile_once()
        self.assertEqual(self.state.run(dependent.run_id)["state"], "submitted")

    def test_exhausted_budget_queues_once_and_alerts(self):
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?)",
                ("plan-budget", "decomposed", self.run.repository, "!room:x", "$root", 1),
            )
        self.state.register_work_items("plan-budget", self.run.work_item, [])
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO runs(run_id,work_item_external_id,state,request_json,result_json) "
                "VALUES (?,?,?,?,?)", ("spent-run-0001", self.run.work_item, "succeeded", "{}",
                json.dumps({"usage": {"input_tokens": 2, "output_tokens": 0}})),
            )
        limited = RunCoordinator(self.state, self.argo, max_aggregate_tokens=1)
        self.assertEqual(limited.submit(self.run, "contract"), "queued")
        self.assertEqual(limited.submit(self.run, "contract"), "queued")
        alerts = [row for row in self.state.pending_matrix()
                  if "aggregate token budget" in row["body"]]
        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
