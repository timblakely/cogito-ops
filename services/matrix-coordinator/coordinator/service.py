"""Authenticated HTTP boundary for Matrix planning and Foreman correlation."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json
import os
import threading
import time

from .core import Coordinator
from .foreman import ForemanClient
from .github import GitHubIssues
from .models import Approval, PlanVersion, ValidationError
from .matrix import MatrixCoordinator
from .planner import PlannerClient
from .state import StateStore
from .webhooks import verify_internal


class App:
    def __init__(self):
        self.internal_secret = os.environ["COORDINATOR_INTERNAL_SECRET"].encode()
        self.state = StateStore(os.environ.get("COORDINATOR_STATE_PATH", "/data/coordinator.sqlite3"))
        self.foreman = ForemanClient(namespace=os.environ.get("FOREMAN_NAMESPACE", "llm"))
        self.github = GitHubIssues(
            token=os.environ.get("GITHUB_TOKEN"),
            token_file=os.environ.get("GITHUB_TOKEN_FILE"),
        )
        self.coordinator = Coordinator(
            self.state, self.github,
            set(filter(None, os.environ.get("MATRIX_APPROVERS", "").split(","))),
        )
        planner_fallbacks = tuple(filter(None, os.environ.get(
            "PLANNER_FALLBACK_MODELS", "planner-gpt,planner-gpt-pro,planner-local").split(",")))
        self.matrix = MatrixCoordinator(
            self.state, self.coordinator, self.foreman,
            PlannerClient(os.environ["LITELLM_PLANNER_API_KEY"],
                          os.environ.get("LITELLM_BASE_URL", "https://litellm.timblakely.com/v1"),
                          os.environ.get("PLANNER_MODEL", "planner"), planner_fallbacks),
            set(filter(None, os.environ.get("MATRIX_APPROVERS", "").split(","))),
            os.environ.get("MATRIX_ACTIVITY_ROOM_ID", ""),
        )

    def handle(self, path: str, headers, body: bytes) -> tuple[int, dict]:
        if not verify_internal(self.internal_secret, body, headers.get("X-Cogito-Signature-256")):
            return 401, {"error": "invalid signature"}
        value = json.loads(body)
        if path == "/v1/matrix/events":
            return 200, self.matrix.handle(value)
        if path == "/v1/matrix/outbox":
            operation = value.get("operation")
            if operation == "poll":
                return 200, {"notifications": self.state.pending_matrix(
                    min(max(int(value.get("limit", 20)), 1), 100))}
            if operation == "ack":
                return 200, {"completed": self.state.complete_matrix(
                    value["notification_id"], value["event_id"])}
            raise ValidationError("unknown outbox operation")
        if path == "/v1/plans":
            plan = PlanVersion(**value)
            return 201, {"created": self.coordinator.record_plan(plan), "hash": plan.hash}
        if path == "/v1/approvals":
            parent, children = self.coordinator.approve(Approval(**value))
            return 201, {"parent": parent, "children": children}
        return 404, {"error": "not found"}

    def reconcile_forever(self) -> None:
        interval = int(os.environ.get("COORDINATOR_RECONCILE_SECONDS", "15"))
        while True:
            try:
                self.matrix.reconcile_once()
            except Exception as exc:
                print(json.dumps({"component": "reconciler", "error": type(exc).__name__,
                                  "message": str(exc)[:500]}))
            time.sleep(interval)


APP: App


class Handler(BaseHTTPRequestHandler):
    server_version = "cogito-coordinator/0.1"

    def do_GET(self):
        if self.path == "/healthz":
            self.reply(200, {"status": "ok"})
        elif self.path == "/metrics":
            payload = APP.state.prometheus_metrics().encode()
            self.send_response(200); self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValidationError("invalid body length")
            status, value = APP.handle(urlparse(self.path).path, self.headers, self.rfile.read(length))
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
            status, value = 400, {"error": str(exc)}
        except Exception as exc:
            status, value = 502, {"error": type(exc).__name__}
        self.reply(status, value)

    def log_message(self, format, *args):
        print(json.dumps({"remote": self.client_address[0], "message": format % args}))

    def reply(self, status: int, value: dict):
        payload = json.dumps(value, sort_keys=True).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


def main() -> None:
    global APP
    APP = App()
    threading.Thread(target=APP.reconcile_forever, daemon=True, name="reconciler").start()
    address = os.environ.get("COORDINATOR_LISTEN", "0.0.0.0:8080")
    host, port = address.rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()


if __name__ == "__main__":
    main()
