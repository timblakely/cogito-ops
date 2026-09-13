"""Normalized Matrix command boundary used by the encrypted maubot adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from threading import RLock
from typing import Any
import json
import re

from .core import Coordinator
from .foreman import ForemanClient
from .models import Approval, PlanVersion, ValidationError, canonical_json
from .planner import PlannerClient
from .state import StateStore


HASH = re.compile(r"sha256:[0-9a-f]{64}")
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s'\"]+"),
    re.compile(
        r"(?i)((?:\"|')?(?:token|password|secret|api[_-]?key)(?:\"|')?"
        r"\s*[:=]\s*(?:\"|')?)[^\s,'\"}]+"
    ),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)
MAX_TRACE_EVENTS = 80


def _sanitize(value: Any, limit: int = 6000) -> str:
    text = str(value or "").replace("\x00", "")
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    text = text.replace("```", "` ` `")
    if len(text) > limit:
        return text[:limit] + f"\n… [truncated {len(text) - limit} characters]"
    return text


def _code(value: Any, language: str = "text", limit: int = 6000) -> str:
    return f"```{language}\n{_sanitize(value, limit)}\n```"


def _tool_output(message: dict[str, Any] | None) -> str:
    if not message:
        return "No tool output was recorded."
    content = message.get("content", "")
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
    except (TypeError, json.JSONDecodeError):
        parsed = content
    if not isinstance(parsed, dict):
        return _sanitize(parsed)
    sections = []
    if "exit_code" in parsed:
        sections.append(f"exit `{parsed['exit_code']}`")
    if parsed.get("timed_out"):
        sections.append("timed out")
    header = " · ".join(sections)
    streams = []
    if parsed.get("stdout"):
        streams.append(_code(parsed["stdout"]))
    if parsed.get("stderr"):
        streams.append("stderr:\n" + _code(parsed["stderr"]))
    if not streams:
        residual = {key: value for key, value in parsed.items()
                    if key not in {"command", "exit_code", "timed_out", "stdout", "stderr"}}
        if residual:
            streams.append(_code(json.dumps(residual, indent=2, sort_keys=True)))
    return "\n\n".join(filter(None, [header, *streams])) or "No output."


def _transcript_events(configmap: dict[str, Any]) -> list[str]:
    raw = configmap.get("data", {}).get("transcript.json", "")
    try:
        transcript = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ["⚠️ Foreman stored a transcript that could not be decoded."]
    if not isinstance(transcript, dict) or not isinstance(transcript.get("messages"), list):
        return ["⚠️ Foreman stored a transcript with an unsupported structure."]
    messages = transcript.get("messages", [])
    outputs = {message.get("tool_call_id"): message for message in messages
               if isinstance(message, dict) and message.get("role") == "tool"
               and message.get("tool_call_id")}
    events = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        note = str(message.get("content") or "").strip()
        if note:
            events.append(f"**Agent note**\n\n{_sanitize(note)}")
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function", {})
            if not isinstance(function, dict):
                continue
            name = str(function.get("name", "unknown"))
            arguments = function.get("arguments", "")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (TypeError, json.JSONDecodeError):
                parsed = arguments
            if name == "bash" and isinstance(parsed, dict):
                invocation = _code(parsed.get("command", ""), "sh", 4000)
                heading = "**Command · `bash`**"
            else:
                invocation = _code(
                    json.dumps(parsed, indent=2, sort_keys=True)
                    if isinstance(parsed, (dict, list)) else parsed,
                    "json" if isinstance(parsed, (dict, list)) else "text", 4000,
                )
                heading = f"**Tool · `{_sanitize(name, 80)}`**"
            events.append(
                f"{heading}\n\n{invocation}\n\n**Output**\n\n"
                f"{_tool_output(outputs.get(call.get('id')))}"
            )
    if len(events) > MAX_TRACE_EVENTS:
        omitted = len(events) - MAX_TRACE_EVENTS
        events = events[:MAX_TRACE_EVENTS]
        events.append(f"⚠️ Trace display capped; {omitted} additional event(s) omitted.")
    return events


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
                 planner: PlannerClient, allowed_senders: set[str],
                 activity_room_id: str = ""):
        self.state, self.core, self.foreman, self.planner = state, core, foreman, planner
        self.allowed_senders = frozenset(allowed_senders)
        self.activity_room_id = activity_room_id
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

    def _activity(self, notification_id: str, body: str) -> None:
        if self.activity_room_id:
            self.state.enqueue_matrix(notification_id, self.activity_room_id, "", body)

    def typing_rooms(self) -> list[str]:
        rooms = set(self.state.planning_typing_rooms())
        if self.activity_room_id and self.state.has_active_research():
            rooms.add(self.activity_room_id)
        return sorted(rooms)

    @staticmethod
    def _agent_root_notification(task_name: str) -> str:
        return f"agent-run:{task_name}:root"

    def _enqueue_research_threads(self, row, round_number: int, names: list[str],
                                  prompts: list[str]) -> None:
        if not self.activity_room_id:
            return
        for position, (task_name, prompt) in enumerate(zip(names, prompts), 1):
            root = self._agent_root_notification(task_name)
            body = (
                f"**Planning scout `{task_name}`**\n\n"
                f"Plan `{row['plan_id']}` · research round {round_number} · scout {position}\n\n"
                "Agent: `cogito-planning-scout` · model: `muse-glimmer-30b`\n\n"
                f"Repository: `{row['repository']}`\n\n"
                f"**Prompt**\n\n{_code(prompt, 'text', 8000)}\n\n"
                "Raw private chain-of-thought is not published. This thread shows "
                "model-authored notes, tool calls, commands, bounded outputs, and the final summary."
            )
            self.state.enqueue_matrix(root, self.activity_room_id, "", body)
            self.state.enqueue_matrix(
                f"agent-run:{task_name}:status:queued", self.activity_room_id, "",
                "**Queued** — waiting for Foreman scheduling.", root,
            )

    def _announce_research_links(self) -> None:
        if not self.activity_room_id:
            return
        for group in self.state.research_round_groups():
            links = self.state.research_run_links(group["plan_id"], group["round"])
            if not links:
                continue
            lines = [
                f"[Scout r{group['round']}-{item['position']}]"
                f"(https://matrix.to/#/{self.activity_room_id}/{item['sent_event_id']})"
                for item in links
            ]
            self.state.enqueue_matrix(
                f"plan:{group['plan_id']}:research:{group['round']}:agent-links",
                group["matrix_room_id"], group["root_event_id"],
                f"Agent Runs for research round {group['round']}: " + " · ".join(lines),
            )

    def _enqueue_research_status(self, row, task: dict[str, Any]) -> None:
        if not self.activity_room_id:
            return
        status = task.get("status", {})
        phase = status.get("phase", "Pending")
        details = []
        if status.get("assignedNode"):
            details.append(f"Fleet node `{_sanitize(status['assignedNode'], 200)}`")
        if status.get("jobName"):
            details.append(f"Job `{_sanitize(status['jobName'], 200)}`")
        suffix = " — " + " · ".join(details) if details else ""
        self.state.enqueue_matrix(
            "agent-run:" + row["task_name"] + ":status:" + sha256(
                canonical_json(status).encode()).hexdigest(),
            self.activity_room_id, "", f"**{_sanitize(phase, 80)}**{suffix}",
            self._agent_root_notification(row["task_name"]),
        )

    def _publish_terminal_research(self) -> None:
        if not self.activity_room_id:
            return
        for row in self.state.unpublished_terminal_research():
            try:
                task = self.foreman.get_task(row["task_name"])
                transcript = self.foreman.get_transcript(task)
            except Exception:
                # Transcript ConfigMaps can land just after the terminal status.
                # Leave this run unpublished so the next reconciliation retries.
                continue
            root = self._agent_root_notification(row["task_name"])
            for index, body in enumerate(_transcript_events(transcript or {})):
                self.state.enqueue_matrix(
                    f"agent-run:{row['task_name']}:transcript:{index:03d}",
                    self.activity_room_id, "", body, root,
                )
            status = task.get("status", {})
            result = status.get("result", {})
            extra = result.get("extra", {}) if isinstance(result, dict) else {}
            metrics = []
            if extra.get("turnCount") is not None:
                metrics.append(f"{extra['turnCount']} turn(s)")
            if result.get("elapsedSec") is not None:
                try:
                    metrics.append(f"{float(result['elapsedSec']):.1f}s")
                except (TypeError, ValueError):
                    pass
            metrics_text = " · " + " · ".join(metrics) if metrics else ""
            summary = row["summary"] or status.get("failureReason") or "No summary returned."
            self.state.enqueue_matrix(
                f"agent-run:{row['task_name']}:transcript:999-final",
                self.activity_room_id, "",
                f"**Finished · {_sanitize(row['state'], 80)}**{metrics_text}\n\n"
                f"**Evidence summary**\n\n{_sanitize(summary, 8000)}",
                root,
            )

    @staticmethod
    def _plan_message(plan: PlanVersion) -> str:
        return (
            f"**Plan `{plan.plan_id}` · version {plan.version}**\n\n{plan.markdown}\n"
            f"Plan hash: `{plan.hash}`\n\nReply in this thread with review comments, then "
            f"`!cogito revise`, or approve the current version with `!cogito approve`."
        )

    def _apply_intake_decision(self, event_id: str, row,
                               decision: dict[str, Any]) -> dict[str, Any]:
        if decision["status"] == "delegate":
            self.state.add_intake_message(
                event_id + ":assistant", row["plan_id"], "planner",
                "assistant", "delegate", decision["message"],
            )
            round_number, names = self.state.register_research(
                row["plan_id"], decision["tasks"])
            self._enqueue_research_threads(row, round_number, names, decision["tasks"])
            return self._message(
                decision["message"].strip() +
                f"\n\nDelegated {len(names)} focused read-only task(s) to local planning "
                "scouts. Their Agent Runs threads will be linked here after Matrix acknowledges "
                "them. I’ll post the draft or a substantive question here when they finish.",
                row["root_event_id"],
            )
        if decision["status"] == "ready":
            version = row["current_version"] + 1
            plan = PlanVersion(
                row["plan_id"], version, decision["plan_markdown"], row["matrix_room_id"],
                event_id, row["repository"],
            )
            self.core.record_plan(plan)
            transition = decision["message"].strip()
            return self._message(f"{transition}\n\n{self._plan_message(plan)}", row["root_event_id"])
        self.state.add_intake_message(
            event_id + ":assistant", row["plan_id"], "planner",
            "assistant", decision["status"], decision["message"],
        )
        self.state.set_plan_state(row["plan_id"], "intake")
        suffix = "\n\nReply here, or send `!cogito draft` to proceed with stated assumptions."
        return self._message(decision["message"].strip() + suffix, row["root_event_id"])

    def _planner_messages(self, row) -> list[dict[str, str]]:
        messages = self.state.intake_messages(row["plan_id"])
        if row["current_version"]:
            version = self.state.current_plan_version(row["plan_id"])
            messages.append({"role": "assistant", "kind": "prior_plan",
                             "body": version["markdown"]})
            messages.extend({"role": "user", "kind": "review_comment", "body": comment}
                            for comment in self.state.plan_comments(row["plan_id"]))
        return messages

    def _continue_intake(self, event: MatrixEvent, row, force: bool = False) -> dict[str, Any]:
        # Two conversational rounds are enough for an experiment. Beyond that,
        # draft with explicit assumptions so intake cannot become an endless gate.
        force = (force or self.state.intake_rounds(row["plan_id"]) >= 2
                 or self.state.research_rounds(row["plan_id"]) >= 2)
        decision = self.planner.intake(
            self._planner_messages(row), force=force,
            research=self.state.research_briefing(row["plan_id"]),
        )
        return self._apply_intake_decision(event.event_id, row, decision)

    def _dispatch_next(self, plan_id: str) -> dict[str, Any] | None:
        deliverable = self.state.next_deliverable(plan_id)
        if not deliverable:
            return None
        plan = self.state.plan(plan_id)
        version = self.state.current_plan_version(plan_id)
        workload = self.foreman.ensure_workload(
            plan_id=plan_id,
            plan_hash=version["content_hash"],
            intent=version["markdown"],
            repository=plan["repository"],
            issue_urls=[deliverable["issue_url"]],
            room_id=plan["matrix_room_id"],
            thread_root=plan["root_event_id"],
            deliverable_position=deliverable["position"],
        )
        status = self.foreman.summary(workload)
        self.state.register_workload(
            workload["metadata"]["name"], plan_id, status, deliverable["position"])
        self._activity(
            f"activity:{plan_id}:{deliverable['position']}:dispatched",
            f"Plan `{plan_id}` · deliverable {deliverable['position']} dispatched as Foreman "
            f"Workload `{workload['metadata']['name']}` · **{status['phase']}**.",
        )
        return {"workload": workload, "status": status, "deliverable": deliverable}

    def _merged(self, row, result: dict[str, Any]) -> None:
        outcome = self.state.finish_merge(row["plan_id"], row["position"], result)
        self._activity(
            f"merge:{row['plan_id']}:{row['position']}:merged",
            f"Plan `{row['plan_id']}` · deliverable {row['position']} merged: {row['pr_url']}",
        )
        if outcome == "completed":
            self.state.enqueue_matrix(
                f"plan:{row['plan_id']}:completed",
                row["matrix_room_id"], row["root_event_id"],
                f"Plan `{row['plan_id']}` is **Completed**; every approved deliverable merged.",
            )

    def _synthesize_research(self, ready) -> None:
        # Matrix commands use this same lock, preventing a manual draft and the
        # background synthesis from creating competing plan versions.
        with self.lock:
            row = self.state.plan(ready["plan_id"])
            if row["state"] != "researching":
                return
            self.state.set_plan_state(row["plan_id"], "synthesizing")
            try:
                decision = self.planner.intake(
                    self._planner_messages(row),
                    force=ready["round"] >= 2,
                    research=self.state.research_briefing(row["plan_id"]),
                )
                result = self._apply_intake_decision(
                    f"$research-{row['plan_id']}-{ready['round']}", row, decision)
            except Exception as exc:
                self.state.set_plan_state(row["plan_id"], "research_failed")
                self.state.enqueue_matrix(
                    f"plan:{row['plan_id']}:research:{ready['round']}:failed",
                    row["matrix_room_id"], row["root_event_id"],
                    f"Planning synthesis is **Blocked**: {type(exc).__name__}. "
                    "Send `!cogito draft` to retry with the completed scout summaries.",
                )
                return
            for index, action in enumerate(result.get("actions", [])):
                if action.get("kind") == "message":
                    self.state.enqueue_matrix(
                        f"plan:{row['plan_id']}:research:{ready['round']}:result:{index}",
                        row["matrix_room_id"], row["root_event_id"], action["body"],
                    )

    def reconcile_once(self) -> None:
        """Advance Workload -> reviewed SHA -> GitHub merge -> next deliverable."""
        for row in self.state.active_research():
            if row["state"] == "Pending":
                task = self.foreman.ensure_research_task(
                    task_name=row["task_name"], plan_id=row["plan_id"],
                    prompt=row["prompt"], repository=row["repository"],
                )
            else:
                task = self.foreman.get_task(row["task_name"])
            task_status = task.get("status", {})
            changed = self.state.update_research(row["task_name"], task_status)
            if changed:
                self._enqueue_research_status(row, task)

        self._publish_terminal_research()
        self._announce_research_links()

        for ready in self.state.research_ready():
            self._synthesize_research(ready)

        for row in self.state.active_workloads():
            status = self.foreman.summary(self.foreman.get(row["name"]))
            changed = self.state.update_workload(row["name"], status)
            if changed:
                self._activity(
                    "activity:" + sha256(
                        f"{row['name']}:{canonical_json(status)}".encode()).hexdigest(),
                    f"Plan `{row['plan_id']}` · deliverable {row['deliverable_position']} · "
                    f"Workload `{row['name']}` is **{status['phase']}**: "
                    f"{status['succeeded']} succeeded, {status['failed']} failed, "
                    f"{status['incomplete']} incomplete.",
                )
            if status["phase"] == "Failed":
                self.state.fail_deliverable(row["plan_id"], row["deliverable_position"], status)
                self.state.enqueue_matrix(
                    f"deliverable:{row['plan_id']}:{row['deliverable_position']}:failed",
                    row["matrix_room_id"], row["root_event_id"],
                    f"Deliverable {row['deliverable_position']} is **Blocked**: Foreman Workload "
                    f"`{row['name']}` failed. Use `!cogito status` for task counts.",
                )
            elif status["phase"] == "Completed":
                try:
                    candidate = self.foreman.merge_candidate(row["name"], quorum=2)
                    result = self.core.issues.request_merge(
                        candidate["pr_url"], candidate["head_sha"], candidate["branch"])
                except RuntimeError as exc:
                    blocked = {"status": "failed", "details": {"message": str(exc)}}
                    self.state.fail_deliverable(
                        row["plan_id"], row["deliverable_position"], blocked)
                    self.state.enqueue_matrix(
                        f"deliverable:{row['plan_id']}:{row['deliverable_position']}:quorum-failed",
                        row["matrix_room_id"], row["root_event_id"],
                        f"Deliverable {row['deliverable_position']} is **Blocked**: {exc}.",
                    )
                    continue
                self.state.begin_merge(
                    row["plan_id"], row["deliverable_position"], candidate["pr_url"],
                    candidate["head_sha"], result.get("uuid"), result)
                self._activity(
                    f"activity:{row['plan_id']}:{row['deliverable_position']}:merge-requested",
                    f"Plan `{row['plan_id']}` · deliverable {row['deliverable_position']} reached "
                    f"review quorum; squash merge requested for `{candidate['head_sha'][:12]}`: "
                    f"{candidate['pr_url']}",
                )
                if result.get("status") == "merged":
                    pending = next(item for item in self.state.pending_merges()
                                   if item["plan_id"] == row["plan_id"]
                                   and item["position"] == row["deliverable_position"])
                    self._merged(pending, result)

        for row in self.state.pending_merges():
            if not row["merge_uuid"]:
                continue
            result = self.core.issues.merge_result(row["pr_url"], row["merge_uuid"])
            if result.get("status") in {"pending", "queued", "in_progress"}:
                continue
            if result.get("status") == "merged":
                self._merged(row, result)
            else:
                self.state.finish_merge(row["plan_id"], row["position"], result)
                detail = result.get("details", {}).get("message", "GitHub rejected the merge")
                self.state.enqueue_matrix(
                    f"merge:{row['plan_id']}:{row['position']}:failed",
                    row["matrix_room_id"], row["root_event_id"],
                    f"Deliverable {row['position']} is **Blocked**: {detail}",
                )

        # This is also crash recovery for a merge committed immediately before
        # the next Workload could be created.
        for plan in self.state.plans_ready_to_dispatch():
            self._dispatch_next(plan["plan_id"])

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
            if plan["state"] in {"intake", "research_failed"}:
                self.state.add_intake_message(
                    event.event_id, plan["plan_id"], event.sender, "user", "answer", body)
                return self._continue_intake(event, plan)
            if plan["state"] in {"researching", "synthesizing"}:
                return self._message(
                    "Planning scouts are still working. Send `!cogito status` for progress or "
                    "`!cogito draft` to draft now from completed results.", root)
            self.state.add_plan_comment(event.event_id, plan["plan_id"], event.sender, body)
            return self._message("Review comment recorded. Send `!cogito revise` when ready.", root)
        command, _, argument = body.removeprefix("!cogito").strip().partition(" ")
        command = command.lower()
        if command == "plan":
            if not argument.strip():
                raise ValidationError("usage: !cogito plan <objective>")
            plan_id = "plan-" + sha256(event.event_id.encode()).hexdigest()[:16]
            self.state.begin_intake(
                plan_id, event.room_id, event.event_id,
                "https://github.com/timblakely/cogito-ops.git")
            self.state.add_intake_message(
                event.event_id, plan_id, event.sender, "user", "objective", argument.strip())
            return self._continue_intake(event, self.state.plan(plan_id))
        if command == "draft":
            row = self._thread_plan(event)
            if row["state"] not in {"intake", "researching", "synthesizing", "research_failed"}:
                raise ValidationError("this plan already has a draft")
            return self._continue_intake(event, row, force=True)
        if command == "revise":
            row = self._thread_plan(event)
            comments = self.state.plan_comments(row["plan_id"])
            if not comments:
                raise ValidationError("no review comments have been recorded")
            return self._continue_intake(event, row)
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
            self.state.register_deliverables(row["plan_id"], children)
            dispatched = self._dispatch_next(row["plan_id"])
            name = dispatched["workload"]["metadata"]["name"]
            status = dispatched["status"]
            links = "\n".join(f"- {child}" for child in children)
            return self._message(
                f"Plan accepted at `{digest}`.\n\nParent issue: {parent}\n\nDeliverables:\n{links}"
                f"\n\nExecution started with Foreman Workload `{name}` · **{status['phase']}**. "
                "Approval authorizes serial delivery and automatic merge after two independent "
                "reviewer approvals.", root)
        if command == "status":
            name = argument.strip()
            if not name:
                row = self._thread_plan(event)
                if row["state"] in {"researching", "synthesizing", "research_failed"}:
                    progress = self.state.research_progress(row["plan_id"])
                    complete = progress.get("Succeeded", 0) + progress.get("Failed", 0)
                    return self._message(
                        f"Planning research is **{row['state']}**: {complete}/"
                        f"{progress['total']} scout tasks finished "
                        f"({progress.get('Failed', 0)} failed).", root)
                saved = self.state.workload_for_plan(row["plan_id"])
                if not saved:
                    raise ValidationError("this plan has no Foreman Workload")
                name = saved["name"]
            workload = self.foreman.get(name)
            status = self.foreman.summary(workload)
            self.state.update_workload(name, status)
            progress = self.state.plan_progress(row["plan_id"]) if not argument.strip() else {}
            progress_text = (f" Plan progress: {progress.get('merged', 0)}/"
                             f"{progress.get('total', 0)} deliverables merged.") if progress else ""
            return self._message(
                f"Workload `{name}` is **{status['phase']}**: "
                f"{status['succeeded']} succeeded, {status['failed']} failed, "
                f"{status['incomplete']} incomplete.{progress_text}", root)
        if command in {"help", ""}:
            return self._message(
                "Commands: `plan <objective>`, `draft`, `revise`, `approve [hash]`, "
                "`status [workload]`. During intake, ordinary thread replies continue the "
                "planner conversation; after a draft, they become review comments.", root)
        raise ValidationError("unknown !cogito command")
