import json
import unittest

from coordinator.planner import PlannerClient


class FakePlannerClient(PlannerClient):
    def __init__(self, response):
        super().__init__("test")
        self.response = response
        self.request = None

    def _response(self, system, content, tools=None, tool_choice=None):
        self.request = (system, content, tools, tool_choice)
        return self.response


class PlannerTests(unittest.TestCase):
    def test_streamed_responses_are_reassembled_from_completed_event(self):
        item = {"type": "message", "content": [{"type": "output_text", "text": "OK"}]}
        completed = {"status": "completed", "output": []}
        raw = (b'data: {"type":"response.created"}\n\n' +
               b'data: ' + json.dumps({"type": "response.output_item.done",
                                       "output_index": 0, "item": item}).encode() + b'\n\n' +
               b'data: ' + json.dumps({"type": "response.completed",
                                       "response": completed}).encode() + b'\n\n' +
               b'data: [DONE]\n\n')
        decoded = PlannerClient._decode_response(raw, "text/event-stream; charset=utf-8")
        self.assertEqual(decoded["output"], [item])
        self.assertEqual(PlannerClient._output_text(decoded), "OK")

    def test_incomplete_response_stream_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "did not complete"):
            PlannerClient._decode_response(
                b'data: {"type":"response.in_progress"}\n\n', "text/event-stream")

    def test_intake_reads_responses_api_function_call(self):
        client = FakePlannerClient({"output": [{
            "type": "function_call", "name": "delegate_research",
            "arguments": json.dumps({"message": "Checking facts.", "tasks": ["Inspect it."]}),
        }]})
        decision = client.intake([{"role": "user", "kind": "objective", "body": "Build it"}])
        self.assertEqual(decision["status"], "delegate")
        self.assertEqual(decision["tasks"], ["Inspect it."])
        self.assertEqual(client.request[3], "auto")

    def test_forced_intake_disables_delegation_and_reads_output_text(self):
        value = {"status": "ready", "message": "Ready.",
                 "plan_markdown": "# Plan\n\n## Deliverables\n- [ ] Ship\n"}
        client = FakePlannerClient({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(value)},
        ]}]})
        self.assertEqual(client.intake([], force=True)["status"], "ready")
        self.assertEqual(client.request[2], [])
        self.assertEqual(client.request[3], "none")


if __name__ == "__main__": unittest.main()
