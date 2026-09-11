"""Durable, idempotent orchestration of Argo-backed AgentRuns."""

from __future__ import annotations

import json
from typing import Protocol

from .models import AgentResult, AgentRun, ValidationError
from .state import StateStore


class ArgoPort(Protocol):
    def submit(self, run: AgentRun, harness: str) -> str: ...
    def find_run(self, run_id: str) -> str | None: ...
    def status(self, name: str) -> dict: ...
    def cancel(self, name: str) -> dict: ...
    def pause(self, name: str) -> dict: ...
    def resume(self, name: str) -> dict: ...


class RunCoordinator:
    def __init__(self, state: StateStore, argo: ArgoPort, max_active: int = 4,
                 max_aggregate_tokens: int = 1_000_000):
        self.state = state
        self.argo = argo
        if max_active < 1 or max_aggregate_tokens < 1:
            raise ValueError("run limits must be positive")
        self.max_active = max_active
        self.max_aggregate_tokens = max_aggregate_tokens

    def submit(self, run: AgentRun, harness: str) -> str:
        request = {**run.as_dict(), "harness": harness}
        created = self.state.register_run(run.run_id, run.work_item, request)
        row = self.state.run(run.run_id)
        if row["argo_name"]:
            return row["argo_name"]
        if self.state.control("emergency_stop", "false") == "true":
            self.state.update_run(run.run_id, "queued")
            return "queued"
        if (self.state.active_run_count() > self.max_active or
                self.state.total_usage_tokens() >= self.max_aggregate_tokens):
            self.state.update_run(run.run_id, "queued")
            return "queued"
        # Recover a submission that reached Kubernetes before a process crash.
        name = self.argo.find_run(run.run_id)
        if name is None:
            name = self.argo.submit(run, harness)
        self.state.attach_workflow(run.run_id, name)
        if created:
            self.state.audit("coordinator", "run.submitted", run.run_id,
                             {"workflow": name, "harness": harness})
        return name

    @staticmethod
    def _result(workflow: dict, run_id: str) -> AgentResult:
        status = workflow.get("status", {})
        outputs = status.get("outputs")
        if not outputs:
            # Argo stores WorkflowTemplate entrypoint outputs on the root node.
            # Depending on controller/version, it may not copy them to
            # status.outputs on the Workflow object.
            name = workflow.get("metadata", {}).get("name")
            root = status.get("nodes", {}).get(name, {})
            outputs = root.get("outputs", {})
        parameters = (outputs or {}).get("parameters", [])
        value = next((p.get("value") for p in parameters if p.get("name") == "result-json"), None)
        if value is None:
            raise ValidationError("successful workflow has no result-json output")
        result = AgentResult.from_dict(json.loads(value))
        if result.run_id != run_id:
            raise ValidationError("workflow result run_id mismatch")
        return result

    def reconcile_once(self) -> int:
        changed = 0
        for row in self.state.queued_runs():
            if self.state.control("emergency_stop", "false") == "true":
                break
            if self.state.active_run_count() >= self.max_active:
                break
            if self.state.total_usage_tokens() >= self.max_aggregate_tokens:
                break
            request = json.loads(row["request_json"])
            harness = request.pop("harness")
            run = AgentRun.from_dict(request)
            name = self.argo.find_run(run.run_id) or self.argo.submit(run, harness)
            self.state.attach_workflow(run.run_id, name)
            self.state.audit("coordinator", "run.dequeued", run.run_id,
                             {"workflow": name, "harness": harness})
            changed += 1
        for row in self.state.active_runs():
            if not row["argo_name"]:
                request = json.loads(row["request_json"])
                harness = request.pop("harness")
                self.submit(AgentRun.from_dict(request), harness)
                changed += 1
                continue
            workflow = self.argo.status(row["argo_name"])
            phase = workflow.get("status", {}).get("phase", "Pending")
            if phase == "Succeeded":
                result = self._result(workflow, row["run_id"])
                state = result.status
                self.state.update_run(row["run_id"], state, result.as_dict())
                self.state.audit("argo", "run.completed", row["run_id"], result.as_dict())
            elif phase in {"Failed", "Error"}:
                state = "cancelled" if row["state"] == "cancelling" else "failed"
                result = AgentResult(row["run_id"], state, workflow.get("status", {}).get("message") or phase)
                self.state.update_run(row["run_id"], state, result.as_dict())
                self.state.audit("argo", "run.completed", row["run_id"], result.as_dict())
            else:
                state = "running" if phase == "Running" else row["state"]
                if state != row["state"]:
                    self.state.update_run(row["run_id"], state)
            if state in {"succeeded", "failed", "cancelled", "needs_input"} and state != row["state"]:
                context = self.state.work_item_context(row["work_item_external_id"])
                if context:
                    self.state.enqueue_matrix(
                        f"run:{row['run_id']}:{state}", context["matrix_room_id"],
                        context["root_event_id"],
                        f"Run `{row['run_id']}` is **{state}** · Argo `{row['argo_name']}`",
                    )
            changed += state != row["state"]
        return changed

    def cancel(self, run_id: str) -> None:
        row = self.state.run(run_id)
        if not row or not row["argo_name"]:
            raise ValidationError("unknown run")
        if row["state"] in {"succeeded", "failed", "cancelled"}:
            return
        self.argo.cancel(row["argo_name"])
        self.state.update_run(run_id, "cancelling")

    def resume(self, run_id: str) -> None:
        row = self.state.run(run_id)
        if not row or not row["argo_name"]:
            raise ValidationError("unknown run")
        self.argo.resume(row["argo_name"])
        self.state.update_run(run_id, "submitted")

    def pause(self, run_id: str) -> None:
        row = self.state.run(run_id)
        if not row or not row["argo_name"]:
            raise ValidationError("unknown run")
        if row["state"] in {"succeeded", "failed", "cancelled", "needs_input"}:
            raise ValidationError("completed run cannot be paused")
        self.argo.pause(row["argo_name"])
        self.state.update_run(run_id, "paused")
