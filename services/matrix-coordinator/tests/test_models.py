import unittest

from coordinator.models import AgentResult, AgentRun, PlanVersion, ValidationError, content_hash


class ModelTests(unittest.TestCase):
    def run_request(self, **updates):
        value = {
            "run_id": "run-00000001",
            "work_item": "https://github.com/timblakely/cogito/issues/1",
            "role": "worker",
            "repository": "https://github.com/timblakely/cogito.git",
            "base_ref": "main",
            "objective": "Do the work",
            "allowed_paths": ["services/**"],
            "limits": {"attempts": 2},
        }
        value.update(updates)
        return AgentRun.from_dict(value)

    def test_plan_hash_normalizes_transport_whitespace(self):
        self.assertEqual(content_hash("# Plan\r\n\r\nText  \r\n"), content_hash("# Plan\n\nText\n"))

    def test_run_round_trip(self):
        run = self.run_request()
        self.assertEqual(AgentRun.from_dict(run.as_dict()), run)

    def test_unknown_fields_fail_closed(self):
        with self.assertRaises(ValidationError):
            self.run_request(shell="rm -rf /")

    def test_paths_cannot_escape_workspace(self):
        with self.assertRaises(ValidationError):
            self.run_request(allowed_paths=["../secrets"])

    def test_result_requires_known_check_status(self):
        with self.assertRaises(ValidationError):
            AgentResult("run-00000001", "succeeded", "done", checks=({"name": "x", "status": "maybe"},))


if __name__ == "__main__":
    unittest.main()
