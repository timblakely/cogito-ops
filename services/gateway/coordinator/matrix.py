"""Normalized Matrix command boundary used by the encrypted maubot adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from threading import RLock
from typing import Any
import base64
import binascii
import json
import re

from .core import Coordinator
from .foreman import ForemanClient
from .github import deliverable_execution_intent, deliverable_specs
from .image import ImageClient
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
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


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
    image: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MatrixEvent":
        if set(value) - {
                "event_id", "room_id", "sender", "body", "timestamp", "thread_root", "image"}:
            raise ValidationError("unknown Matrix event field")
        event = cls(**value)
        if not event.event_id.startswith("$") or not event.room_id.startswith("!"):
            raise ValidationError("invalid Matrix event identity")
        if not event.sender.startswith("@") or ":" not in event.sender:
            raise ValidationError("invalid Matrix sender")
        if not event.body.strip() or len(event.body) > 200_000:
            raise ValidationError("invalid Matrix body")
        if event.image is not None:
            if (not isinstance(event.image, dict)
                    or set(event.image) - {"mime_type", "data", "name"}):
                raise ValidationError("invalid Matrix image")
            mime_type = event.image.get("mime_type")
            encoded = event.image.get("data")
            name = event.image.get("name", "")
            if mime_type not in IMAGE_TYPES or not isinstance(encoded, str):
                raise ValidationError("unsupported Matrix image")
            if not isinstance(name, str) or len(name) > 512:
                raise ValidationError("invalid Matrix image name")
            try:
                image = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationError("invalid Matrix image data") from exc
            if not image or len(image) > MAX_IMAGE_BYTES:
                raise ValidationError("invalid Matrix image size")
        return event

    def image_bytes(self) -> bytes:
        return base64.b64decode(self.image["data"], validate=True) if self.image else b""


class MatrixCoordinator:
    def __init__(self, state: StateStore, core: Coordinator, foreman: ForemanClient,
                 planner: PlannerClient, allowed_senders: set[str],
                 activity_room_id: str = "", astra_turn_cap: int = 20,
                 images: ImageClient | None = None,
                 project_rooms: dict[str, str] | None = None):
        self.state, self.core, self.foreman, self.planner = state, core, foreman, planner
        self.allowed_senders = frozenset(allowed_senders)
        self.activity_room_id = activity_room_id
        self.astra_turn_cap = max(1, astra_turn_cap)
        self.images = images
        self.project_rooms = dict(project_rooms or {})
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
        row = (self.state.plan_for_thread(event.room_id, root)
               or self.state.plan_for_implementation_thread(event.room_id, root))
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
            agent = ("cogito-planning-scout" if position % 2
                     else "cogito-planning-scout-qwen")
            model = "scout" if position % 2 else "scout-qwen"
            body = (
                f"**Planning scout `{task_name}`**\n\n"
                f"Plan `{row['plan_id']}` · research round {round_number} · scout {position}\n\n"
                f"Agent: `{agent}` · model alias: `{model}`\n\n"
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
            result = status.get("result") or {}
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
    def _plan_message(plan: PlanVersion, issue_url: str) -> str:
        return (
            f"◆ Astra: **Plan drafted** → {issue_url}\n\n"
            f"Plan `{plan.plan_id}` · version {plan.version} · Plan hash: `{plan.hash}`\n\n"
            "Review or edit the issue body on GitHub. Approve the exact current body by "
            "applying `workflow/approved` or commenting `/approve` on the issue."
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
            issue_url = self.state.plan(plan.plan_id)["github_issue_url"]
            return self._message(
                f"{transition}\n\n{self._plan_message(plan, issue_url)}", row["root_event_id"])
        self.state.add_intake_message(
            event_id + ":assistant", row["plan_id"], "planner",
            "assistant", decision["status"], decision["message"],
        )
        self.state.set_plan_state(row["plan_id"], "intake")
        suffix = "\n\nReply here, or send `!cogito draft` to proceed with stated assumptions."
        return self._message(decision["message"].strip() + suffix, row["root_event_id"])

    def _planner_messages(self, row) -> list[dict[str, str]]:
        messages = self.state.intake_messages(row["plan_id"])
        if notes := self.state.plan_notes(row["plan_id"]):
            messages.append({"role": "assistant", "kind": "working_notes", "body": notes})
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
        if not self.state.reserve_astra_turn(
                row["plan_id"], "intake", self.astra_turn_cap):
            return self._message(
                f"◆ Astra: **Needs input:** this plan reached the "
                f"{self.astra_turn_cap}-turn planning cap. "
                "Raise the configured cap or cancel the plan before continuing.",
                row["root_event_id"],
            )
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
        item = deliverable_specs(
            version["markdown"])[deliverable["position"] - 1][0]
        workload = self.foreman.ensure_workload(
            plan_id=plan_id,
            plan_hash=version["content_hash"],
            intent=deliverable_execution_intent(deliverable["position"], item),
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
        self.state.enqueue_coordinator_event(
            f"merge:{row['plan_id']}:{row['position']}:merged",
            row["plan_id"], "gateway", "deliverable.merged", {
                "position": row["position"], "pull_request": row["pr_url"],
                "merge": result,
            }, delay_seconds=0,
        )
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
                if not self.state.reserve_astra_turn(
                        row["plan_id"], "synthesis", self.astra_turn_cap):
                    self.state.enqueue_matrix(
                        f"plan:{row['plan_id']}:astra-cap",
                        row["matrix_room_id"], row["root_event_id"],
                        f"◆ Astra: **Needs input:** this plan reached the "
                        f"{self.astra_turn_cap}-turn planning cap.",
                    )
                    return
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
                self.state.enqueue_coordinator_event(
                    f"workload:{row['name']}:failed", row["plan_id"], "foreman",
                    "workload.failed", {"name": row["name"], "status": status},
                    delay_seconds=0,
                )
                self.state.enqueue_matrix(
                    f"deliverable:{row['plan_id']}:{row['deliverable_position']}:failed",
                    row["matrix_room_id"], row["root_event_id"],
                    f"Deliverable {row['deliverable_position']} is **Blocked**: Foreman Workload "
                    f"`{row['name']}` failed. Use `!cogito status` for task counts.",
                )
            elif status["phase"] == "Completed":
                try:
                    candidate = self.foreman.merge_candidate(row["name"], quorum=2)
                    for packet in candidate.get("review_packets", []):
                        agent = packet.get("agent") or "reviewer"
                        action_key = (
                            f"github-review:{row['plan_id']}:{row['deliverable_position']}:"
                            f"{candidate['head_sha']}:{agent}"
                        )
                        cached = self.state.begin_action(
                            action_key, "github.post-review", packet)
                        if cached is None:
                            try:
                                review = self.core.issues.post_review_packet(
                                    candidate["pr_url"], candidate["head_sha"], packet,
                                    action_key)
                            except Exception as exc:
                                self.state.fail_action(action_key, str(exc))
                                raise
                            self.state.complete_action(action_key, review)
                    checks = self.core.issues.checks_status(candidate["pr_url"])
                    if checks["failed"]:
                        raise RuntimeError(
                            "required checks failed: " + ", ".join(checks["failed"]))
                    if not checks["ready"]:
                        waiting = checks["missing"] + checks["pending"]
                        self._activity(
                            f"activity:{row['plan_id']}:{row['deliverable_position']}:checks",
                            f"Plan `{row['plan_id']}` · deliverable "
                            f"{row['deliverable_position']} is waiting for required checks: "
                            + ", ".join(waiting),
                        )
                        continue
                    result = self.core.issues.request_merge(
                        candidate["pr_url"], candidate["head_sha"], candidate["branch"])
                except RuntimeError as exc:
                    blocked = {"status": "failed", "details": {"message": str(exc)}}
                    self.state.fail_deliverable(
                        row["plan_id"], row["deliverable_position"], blocked)
                    self.state.enqueue_coordinator_event(
                        f"workload:{row['name']}:verification-failed", row["plan_id"],
                        "gateway", "workload.verification_failed",
                        {"name": row["name"], "reason": str(exc)[:2_000]},
                        delay_seconds=0,
                    )
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
                self.state.enqueue_coordinator_event(
                    f"merge:{row['plan_id']}:{row['position']}:failed",
                    row["plan_id"], "github", "merge.failed",
                    {"position": row["position"], "pull_request": row["pr_url"],
                     "reason": str(detail)[:2_000]}, delay_seconds=0,
                )
                self.state.enqueue_matrix(
                    f"merge:{row['plan_id']}:{row['position']}:failed",
                    row["matrix_room_id"], row["root_event_id"],
                    f"Deliverable {row['position']} is **Blocked**: {detail}",
                )

        # Crash recovery never bypasses Luna: reconstruct only the durable
        # coordination wake-up when a runnable deliverable has no active turn.
        for plan in self.state.plans_ready_to_dispatch():
            pending = self.state.next_deliverable(plan["plan_id"])
            if pending:
                self.state.enqueue_coordinator_event(
                    f"recovery:{plan['plan_id']}:{pending['position']}:{pending['attempt']}",
                    plan["plan_id"], "gateway", "coordination.recover", {
                        "position": pending["position"], "issue": pending["issue_url"],
                        "attempt": pending["attempt"],
                    }, delay_seconds=0,
                )

        for plan in self.state.completed_plans():
            key = f"github-close-plan:{plan['plan_id']}"
            if self.state.begin_action(
                    key, "github.close-plan", {"issue": plan["github_issue_url"]}) is not None:
                continue
            try:
                self.core.issues.update_issue_state(plan["github_issue_url"], "closed")
            except Exception as exc:
                self.state.fail_action(key, str(exc))
                continue
            self.state.complete_action(key, {"closed": True})

        for plan in self.state.cancelled_plans():
            urls = [plan["github_issue_url"], *self.state.deliverable_urls(plan["plan_id"])]
            for issue_url in urls:
                key = "github-close-cancelled:" + sha256(issue_url.encode()).hexdigest()
                if self.state.begin_action(
                        key, "github.close-cancelled", {"issue": issue_url}) is not None:
                    continue
                try:
                    self.core.issues.update_issue_state(issue_url, "closed")
                except Exception as exc:
                    self.state.fail_action(key, str(exc))
                    continue
                self.state.complete_action(key, {"closed": True})

    def _handle(self, event: MatrixEvent) -> dict[str, Any]:
        body = event.body.strip()
        root = event.thread_root or event.event_id
        if event.sender not in self.allowed_senders:
            raise ValidationError("Matrix sender is not allowlisted")
        # Root-level images belong to the configured project room or require a
        # command caption elsewhere. Thread images are contextual input. In all
        # cases a local model reduces raw media to bounded text before Astra or
        # Luna sees it.
        if event.image and (event.thread_root or body.startswith("!cogito")
                            or event.room_id in self.project_rooms):
            if not self.images:
                raise ValidationError("image description is not configured")
            description = self.images.describe(
                event.image["mime_type"], event.image_bytes(),
                event.image.get("name", ""), body,
            )
            body += "\n\n[Local Muse image description]\n" + description
        if event.thread_root and body.lower() in {"status", "stop"}:
            body = "!cogito " + body.lower()
        if (not event.thread_root and not body.startswith("!cogito")
                and event.room_id in self.project_rooms):
            body = "!cogito plan " + body
        if not body.startswith("!cogito"):
            if not event.thread_root:
                return {"actions": []}
            plan = self.state.plan_for_thread(event.room_id, event.thread_root)
            implementation = False
            if not plan:
                plan = self.state.plan_for_implementation_thread(
                    event.room_id, event.thread_root)
                implementation = bool(plan)
            if not plan:
                return {"actions": []}
            if implementation:
                self.state.enqueue_coordinator_event(
                    f"matrix:{event.event_id}", plan["plan_id"], "matrix",
                    "owner.instruction", {"actor": event.sender, "body": body[:8_000]},
                    delay_seconds=0,
                )
                return self._message("● Luna: instruction queued.", root)
            if plan["state"] in {"intake", "research_failed"}:
                self.state.add_intake_message(
                    event.event_id, plan["plan_id"], event.sender, "user", "answer", body)
                return self._continue_intake(event, plan)
            if plan["state"] in {"researching", "synthesizing"}:
                if event.image:
                    self.state.add_intake_message(
                        event.event_id, plan["plan_id"], event.sender,
                        "user", "owner_image", body)
                    return self._message(
                        "Image described locally and recorded for the pending synthesis. "
                        "Send `!cogito status` for scout progress or `!cogito draft` to "
                        "draft now from completed results.", root)
                return self._message(
                    "Planning scouts are still working. Send `!cogito status` for progress or "
                    "`!cogito draft` to draft now from completed results.", root)
            self.state.add_plan_comment(event.event_id, plan["plan_id"], event.sender, body)
            return self._message("Review comment recorded. Send `!cogito revise` when ready.", root)
        command, _, argument = body.removeprefix("!cogito").strip().partition(" ")
        command = command.lower()
        if command == "react":
            reaction, _, target = argument.strip().partition(" ")
            row = self.state.plan_for_card_event(event.room_id, target.strip())
            if not row:
                raise ValidationError("reaction does not target a Cogito plan card")
            if reaction == "⏹":
                self.state.set_plan_state(row["plan_id"], "cancelled")
                self.state.enqueue_coordinator_event(
                    f"matrix:{event.event_id}:cancel", row["plan_id"], "matrix",
                    "owner.cancelled", {"actor": event.sender}, delay_seconds=0)
                return self._message("▣ gateway: plan cancelled.", row["root_event_id"])
            if reaction == "⏸":
                self.state.pause_plan(row["plan_id"])
                return self._message("▣ gateway: plan paused.", row["root_event_id"])
            if reaction == "🔄":
                if row["state"] == "paused":
                    state = self.state.resume_plan(row["plan_id"])
                    text = f"Plan resumed in **{state}**."
                else:
                    text = "Owner requested a retry."
                self.state.enqueue_coordinator_event(
                    f"matrix:{event.event_id}:retry", row["plan_id"], "matrix",
                    "owner.retry", {"actor": event.sender}, delay_seconds=0)
                return self._message("▣ gateway: " + text, row["root_event_id"])
            if reaction == "🔍":
                self.state.enqueue_coordinator_event(
                    f"matrix:{event.event_id}:investigate", row["plan_id"], "matrix",
                    "owner.investigate", {"actor": event.sender}, delay_seconds=0)
                return self._message("● Luna: investigation queued.", row["root_event_id"])
            raise ValidationError("unsupported plan-card reaction")
        if command == "plan":
            if not argument.strip():
                raise ValidationError("usage: !cogito plan <objective>")
            plan_id = "plan-" + sha256(event.event_id.encode()).hexdigest()[:16]
            self.state.begin_intake(
                plan_id, event.room_id, event.event_id,
                self.project_rooms.get(
                    event.room_id, "https://github.com/timblakely/cogito-ops.git"))
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
            links = "\n".join(f"- {child}" for child in children)
            return self._message(
                f"Plan accepted at `{digest}`.\n\nParent issue: {parent}\n\nDeliverables:\n{links}"
                "\n\n● Luna queued the approved plan for serial execution. The gateway will "
                "merge only after two independent reviewer approvals and required checks.", root)
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
                    if row["state"] in {"accepted", "decomposed"}:
                        usage = self.state.luna_usage(row["plan_id"])
                        return self._message(
                            f"Plan is **{row['state']}** and queued for Luna coordination. "
                            f"Luna turns: {usage['turns']}.", root)
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
        if command == "stop":
            row = self._thread_plan(event)
            self.state.set_plan_state(row["plan_id"], "cancelled")
            self.state.enqueue_coordinator_event(
                f"matrix:{event.event_id}:cancel", row["plan_id"], "matrix",
                "owner.cancelled", {"actor": event.sender}, delay_seconds=0)
            return self._message("▣ gateway: plan cancelled.", root)
        if command in {"help", ""}:
            return self._message(
                "Commands: `plan <objective>`, `draft`, `revise`, `approve [hash]`, "
                "`status [workload]`, `stop`. During intake, ordinary thread replies continue the "
                "planner conversation; after a draft, they become review comments.", root)
        raise ValidationError("unknown !cogito command")
