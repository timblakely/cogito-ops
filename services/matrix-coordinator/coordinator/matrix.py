"""Normalized Matrix command boundary used by the encrypted maubot adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from threading import RLock
from typing import Any
import re

from .core import Coordinator
from .deliveries import DeliveryCoordinator
from .models import AgentRun, Approval, PlanVersion, ValidationError, canonical_json
from .planner import PlannerClient
from .runs import RunCoordinator
from .state import StateStore


HASH = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class MatrixEvent:
    event_id: str
    room_id: str
    sender: str
    body: str
    timestamp: str
    thread_root: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MatrixEvent":
        if set(value) - {"event_id", "room_id", "sender", "body", "timestamp", "thread_root"}:
            raise ValidationError("unknown Matrix event field")
        event = cls(**value)
        if not event.event_id.startswith("$") or not event.room_id.startswith("!"):
            raise ValidationError("invalid Matrix event identity")
        if not event.sender.startswith("@") or ":" not in event.sender:
            raise ValidationError("invalid Matrix sender")
        if not event.body.strip() or len(event.body) > 200_000:
            raise ValidationError("invalid Matrix body")
        return event


class MatrixCoordinator:
    def __init__(self, state: StateStore, core: Coordinator, runs: RunCoordinator,
                 deliveries: DeliveryCoordinator, planner: PlannerClient, allowed_senders: set[str],
                 worker_harnesses: tuple[str, ...] = ("pi", "opencode")):
        self.state, self.core, self.runs, self.deliveries, self.planner = (
            state, core, runs, deliveries, planner)
        self.allowed_senders = frozenset(allowed_senders)
        self.worker_harnesses = worker_harnesses
        if not worker_harnesses or set(worker_harnesses) - {"pi", "opencode", "contract"}:
            raise ValidationError("invalid worker harness list")
        self.lock = RLock()

    @staticmethod
    def _message(body: str, root: str) -> dict[str, Any]:
        return {"actions": [{"kind": "message", "body": body, "thread_root": root}]}

    def handle(self, value: dict[str, Any]) -> dict[str, Any]:
        event = MatrixEvent.from_dict(value)
        with self.lock:
            if cached := self.state.matrix_result(event.event_id):
                return cached
            payload_hash = sha256(canonical_json(value).encode()).hexdigest()
            self.state.accept_event("matrix", event.event_id, payload_hash)
            result = self._handle(event)
            self.state.save_matrix_result(event.event_id, result)
            return result

    def _thread_plan(self, event: MatrixEvent):
        root = event.thread_root or event.event_id
        row = self.state.plan_for_thread(event.room_id, root)
        if not row:
            raise ValidationError("this thread has no plan")
        return row

    def _handle(self, event: MatrixEvent) -> dict[str, Any]:
        body = event.body.strip()
        root = event.thread_root or event.event_id
        if event.sender not in self.allowed_senders:
            raise ValidationError("Matrix sender is not allowlisted")
        if not body.startswith("!cogito"):
            if not event.thread_root:
                return {"actions": []}
            plan = self.state.plan_for_thread(event.room_id, event.thread_root)
            if not plan:
                return {"actions": []}
            self.state.add_plan_comment(event.event_id, plan["plan_id"], event.sender, body)
            return self._message("Review comment recorded. Send `!cogito revise` when ready.", root)
        command, _, argument = body.removeprefix("!cogito").strip().partition(" ")
        command = command.lower()
        if command == "plan":
            if not argument.strip():
                raise ValidationError("usage: !cogito plan <objective>")
            plan_id = "plan-" + sha256(event.event_id.encode()).hexdigest()[:16]
            markdown = self.planner.plan(argument)
            plan = PlanVersion(plan_id, 1, markdown, event.room_id, event.event_id,
                               "https://github.com/timblakely/cogito-ops.git")
            self.core.record_plan(plan)
            return self._message(
                f"**Plan `{plan.plan_id}` · version 1**\n\n{plan.markdown}\n"
                f"Plan hash: `{plan.hash}`\n\nReply in this thread with comments, then "
                f"`!cogito revise`, "
                f"or approve the current version with `!cogito approve`.", root)
        if command == "revise":
            row = self._thread_plan(event)
            version = self.state.current_plan_version(row["plan_id"])
            comments = self.state.plan_comments(row["plan_id"])
            if not comments:
                raise ValidationError("no review comments have been recorded")
            markdown = self.planner.plan("Revise the reviewed plan", version["markdown"], comments)
            plan = PlanVersion(row["plan_id"], row["current_version"] + 1, markdown,
                               event.room_id, event.event_id, row["repository"])
            self.core.record_plan(plan)
            return self._message(
                f"**Plan `{plan.plan_id}` · version {plan.version}**\n\n{plan.markdown}\n"
                f"Plan hash: `{plan.hash}`\n\nApprove the current version with "
                f"`!cogito approve`.", root)
        if command == "approve":
            if self.state.control("emergency_stop", "false") == "true":
                raise ValidationError("coordinator emergency stop is active")
            row = self._thread_plan(event)
            digest = argument.strip()
            if digest:
                if not HASH.fullmatch(digest):
                    raise ValidationError("usage: !cogito approve [sha256:<64 hex characters>]")
            else:
                version = self.state.current_plan_version(row["plan_id"])
                try:
                    sent_at = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                    if sent_at.tzinfo is None:
                        raise ValueError
                except ValueError as exc:
                    raise ValidationError("invalid Matrix event timestamp") from exc
                if sent_at.timestamp() < version["created_at"]:
                    raise ValidationError(
                        "the plan changed after this approval was sent; review the latest version"
                    )
                digest = version["content_hash"]
            parent, children = self.core.approve(Approval(
                row["plan_id"], digest, event.event_id, event.sender, event.timestamp))
            dispatched = []
            for index, child in enumerate(children):
                run_id = "delivery-" + sha256(f"{digest}:{child}".encode()).hexdigest()[:20]
                harness = self.worker_harnesses[index % len(self.worker_harnesses)]
                run = AgentRun(
                    run_id=run_id, work_item=child, role="worker", repository=row["repository"],
                    base_ref="main",
                    objective=f"Implement and verify the accepted deliverable tracked by {child}.",
                    acceptance_checks=("Deliverable acceptance checklist is satisfied",
                                       "Relevant repository checks pass"),
                    context={"plan_hash": digest, "matrix_thread": root,
                             "parent_issue": parent,
                             **({"depends_on": children[index - 1]} if index else {})},
                    limits={"attempts": 2, "wall_seconds": 3600, "token_budget": 200000},
                )
                name = self.runs.submit(run, harness)
                self.deliveries.register(run, harness)
                dispatched.append((run_id, name, harness))
            links = "\n".join(f"- {child}" for child in children)
            run_links = "\n".join(
                f"- `{run_id}` via **{harness}** (Argo `{name}`)" for run_id, name, harness in dispatched)
            return self._message(
                f"Plan accepted at `{digest}`.\n\nParent issue: {parent}\n\nDeliverables:\n{links}"
                f"\n\nDispatched runs:\n{run_links}", root)
        if command in {"cancel", "pause", "resume"}:
            run_id = argument.strip()
            getattr(self.runs, command)(run_id)
            return self._message(f"Run `{run_id}` {command} requested.", root)
        if command == "stop":
            self.state.set_control("emergency_stop", "true")
            cancelled = 0
            for row in self.state.active_runs():
                self.runs.cancel(row["run_id"])
                cancelled += 1
            self.state.audit(event.sender, "coordinator.stopped", "global", {"cancelled": cancelled})
            return self._message(f"Emergency stop active; cancellation requested for {cancelled} runs.", root)
        if command == "start":
            self.state.set_control("emergency_stop", "false")
            self.state.audit(event.sender, "coordinator.started", "global", {})
            return self._message("Emergency stop cleared; reconciliation resumed.", root)
        if command == "merge":
            explicit = argument.strip()
            if explicit:
                run_id, separator, head_sha = explicit.partition(" ")
                if not separator:
                    raise ValidationError("usage: !cogito merge")
                head_sha = head_sha.strip()
            else:
                pending = self.state.awaiting_merges_for_thread(event.room_id, root)
                if not pending:
                    raise ValidationError("this thread has no change awaiting merge approval")
                if len(pending) > 1:
                    raise ValidationError(
                        "multiple changes await approval in this thread; use the approval card"
                    )
                run_id = pending[0]["worker_run_id"]
                head_sha = pending[0]["approved_head_sha"]
            self.deliveries.approve_merge(run_id, head_sha.strip())
            return self._message("Merge approved.", root)
        if command == "status":
            run_id = argument.strip()
            row = self.state.run(run_id)
            if not row:
                raise ValidationError("unknown run")
            return self._message(
                f"Run `{run_id}` is **{row['state']}** (Argo `{row['argo_name'] or 'pending'}`).", root)
        if command in {"help", ""}:
            return self._message(
                "Commands: `plan <objective>`, `revise`, `approve [hash]`, "
                "`status <run>`, `cancel|pause|resume <run>`, `merge`, `stop`, `start`. "
                "Ordinary replies in a plan thread are review comments.", root)
        raise ValidationError("unknown !cogito command")
