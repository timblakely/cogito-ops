"""Authenticated HTTP boundary for Matrix, GitHub, and workflow clients."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import json
import os
import threading
import time

from .argo import ArgoClient
from .core import Coordinator
from .github import GitHubIssues
from .models import AgentRun, Approval, PlanVersion, ValidationError
from .matrix import MatrixCoordinator
from .planner import PlannerClient
from .state import StateStore
from .runs import RunCoordinator
from .webhooks import verify_github, verify_internal


class App:
    def __init__(self):
        self.internal_secret = os.environ["COORDINATOR_INTERNAL_SECRET"].encode()
        self.github_secret = os.environ["GITHUB_WEBHOOK_SECRET"].encode()
        self.state = StateStore(os.environ.get("COORDINATOR_STATE_PATH", "/data/coordinator.sqlite3"))
        self.argo = ArgoClient(namespace=os.environ.get("ARGO_NAMESPACE", "tools"))
        self.runs = RunCoordinator(self.state, self.argo)
        self.coordinator = Coordinator(
            self.state, GitHubIssues(os.environ["GITHUB_TOKEN"]),
            set(filter(None, os.environ.get("MATRIX_APPROVERS", "").split(","))),
        )
        planner_fallbacks = tuple(filter(None, os.environ.get(
            "PLANNER_FALLBACK_MODELS", "planner-gpt").split(",")))
        self.matrix = MatrixCoordinator(
            self.state, self.coordinator, self.runs,
            PlannerClient(os.environ["LITELLM_PLANNER_API_KEY"],
                          os.environ.get("LITELLM_BASE_URL", "https://litellm.timblakely.com/v1"),
                          os.environ.get("PLANNER_MODEL", "planner"), planner_fallbacks),
            set(filter(None, os.environ.get("MATRIX_APPROVERS", "").split(","))),
        )

    def handle(self, path: str, headers, body: bytes) -> tuple[int, dict]:
        if path == "/events/github":
            if not verify_github(self.github_secret, body, headers.get("X-Hub-Signature-256")):
                return 401, {"error": "invalid signature"}
            delivery = headers.get("X-GitHub-Delivery", "")
            if not delivery:
                return 400, {"error": "missing delivery ID"}
            fresh = self.state.accept_event("github", delivery, hashlib.sha256(body).hexdigest())
            if fresh:
                self.state.audit("github", "webhook.received", delivery,
                                 {"event": headers.get("X-GitHub-Event", "unknown")})
            return 202, {"accepted": fresh}
        if not verify_internal(self.internal_secret, body, headers.get("X-Cogito-Signature-256")):
            return 401, {"error": "invalid signature"}
        value = json.loads(body)
        if path == "/v1/matrix/events":
            return 200, self.matrix.handle(value)
        if path == "/v1/plans":
            plan = PlanVersion(**value)
            return 201, {"created": self.coordinator.record_plan(plan), "hash": plan.hash}
        if path == "/v1/approvals":
            parent, children = self.coordinator.approve(Approval(**value))
            return 201, {"parent": parent, "children": children}
        if path == "/v1/runs":
            harness = value.pop("harness")
            run = AgentRun.from_dict(value)
            name = self.runs.submit(run, harness)
            return 201, {"workflow": name, "run_id": run.run_id}
        if path.startswith("/v1/runs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["v1", "runs"]:
                run_id, operation = parts[2:]
                if operation == "cancel":
                    self.runs.cancel(run_id)
                elif operation == "resume":
                    self.runs.resume(run_id)
                elif operation == "reconcile":
                    self.runs.reconcile_once()
                else:
                    return 404, {"error": "not found"}
                return 202, {"run_id": run_id, "operation": operation}
        return 404, {"error": "not found"}

    def reconcile_forever(self) -> None:
        interval = int(os.environ.get("COORDINATOR_RECONCILE_SECONDS", "15"))
        while True:
            try:
                self.runs.reconcile_once()
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
            payload = b"cogito_coordinator_up 1\n"
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
