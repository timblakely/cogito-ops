import json
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
