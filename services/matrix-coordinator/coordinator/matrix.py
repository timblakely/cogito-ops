"""Normalized Matrix command boundary used by the encrypted maubot adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from threading import RLock
from typing import Any
import re

from .core import Coordinator
from .foreman import ForemanClient
from .models import Approval, PlanVersion, ValidationError, canonical_json
from .planner import PlannerClient
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
    def __init__(self, state: StateStore, core: Coordinator, foreman: ForemanClient,
                 planner: PlannerClient, allowed_senders: set[str]):
        self.state, self.core, self.foreman, self.planner = state, core, foreman, planner
        self.allowed_senders = frozenset(allowed_senders)
        self.lock = RLock()

    @staticmethod
    def _message(body: str, root: str) -> dict[str, Any]:
        return {"actions": [{"kind": "message", "body": body, "thread_root": root}]}

    def _enqueue_actions(self, event: MatrixEvent, result: dict[str, Any]) -> None:
        for index, action in enumerate(result.get("actions", [])):
            if action.get("kind") != "message":
                continue
            notification_id = "command:" + sha256(
                f"{event.event_id}:{index}".encode()
            ).hexdigest()
            self.state.enqueue_matrix(
                notification_id,
                event.room_id,
                action.get("thread_root") or event.thread_root or event.event_id,
                action["body"],
            )

    def handle(self, value: dict[str, Any]) -> dict[str, Any]:
        event = MatrixEvent.from_dict(value)
        with self.lock:
            if cached := self.state.matrix_result(event.event_id):
                self._enqueue_actions(event, cached)
                return cached
            payload_hash = sha256(canonical_json(value).encode()).hexdigest()
            self.state.accept_event("matrix", event.event_id, payload_hash)
            result = self._handle(event)
            self.state.save_matrix_result(event.event_id, result)
            self._enqueue_actions(event, result)
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
            version = self.state.current_plan_version(row["plan_id"])
            workload = self.foreman.ensure_workload(
                plan_id=row["plan_id"], plan_hash=digest, intent=version["markdown"],
                repository=row["repository"], issue_urls=children,
                room_id=event.room_id, thread_root=root,
            )
            name = workload["metadata"]["name"]
            status = self.foreman.summary(workload)
            self.state.register_workload(name, row["plan_id"], status)
            links = "\n".join(f"- {child}" for child in children)
            return self._message(
                f"Plan accepted at `{digest}`.\n\nParent issue: {parent}\n\nDeliverables:\n{links}"
                f"\n\nForeman Workload: `{name}` · **{status['phase']}**", root)
        if command == "status":
            name = argument.strip()
            if not name:
                row = self._thread_plan(event)
                saved = self.state.workload_for_plan(row["plan_id"])
                if not saved:
                    raise ValidationError("this plan has no Foreman Workload")
                name = saved["name"]
            workload = self.foreman.get(name)
            status = self.foreman.summary(workload)
            self.state.update_workload(name, status)
            return self._message(
                f"Workload `{name}` is **{status['phase']}**: "
                f"{status['succeeded']} succeeded, {status['failed']} failed, "
                f"{status['incomplete']} incomplete.", root)
        if command in {"help", ""}:
            return self._message(
                "Commands: `plan <objective>`, `revise`, `approve [hash]`, `status [workload]`. "
                "Ordinary replies in a plan thread are review comments.", root)
        raise ValidationError("unknown !cogito command")
