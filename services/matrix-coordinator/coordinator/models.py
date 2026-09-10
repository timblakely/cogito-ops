"""Versioned domain objects and strict boundary validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urlparse
import json
import re

API_VERSION = "cogito.dev/v1alpha1"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
ROLES = {
    "planner", "coordinator", "worker", "reviewer",
    "worker-escalated", "reviewer-escalated",
}


class ValidationError(ValueError):
    """Input failed a coordinator trust-boundary check."""


def canonical_markdown(value: str) -> str:
    """Normalize transport differences without changing Markdown meaning."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def content_hash(value: str) -> str:
    return "sha256:" + sha256(canonical_markdown(value).encode()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _nonempty(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _url(name: str, value: Any, schemes: set[str]) -> str:
    value = _nonempty(name, value)
    parsed = urlparse(value)
    if parsed.scheme not in schemes or not parsed.netloc:
        raise ValidationError(f"{name} must use one of {sorted(schemes)}")
    return value


@dataclass(frozen=True)
class PlanVersion:
    plan_id: str
    version: int
    markdown: str
    matrix_room_id: str
    matrix_event_id: str
    repository: str
    hash: str = field(init=False)

    def __post_init__(self) -> None:
        _nonempty("plan_id", self.plan_id)
        if self.version < 1:
            raise ValidationError("version must be positive")
        _nonempty("markdown", self.markdown)
        _nonempty("matrix_room_id", self.matrix_room_id)
        _nonempty("matrix_event_id", self.matrix_event_id)
        _url("repository", self.repository, {"https", "ssh"})
        object.__setattr__(self, "markdown", canonical_markdown(self.markdown))
        object.__setattr__(self, "hash", content_hash(self.markdown))


@dataclass(frozen=True)
class Approval:
    plan_id: str
    plan_hash: str
    matrix_event_id: str
    approver: str
    approved_at: str

    def __post_init__(self) -> None:
        _nonempty("plan_id", self.plan_id)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.plan_hash):
            raise ValidationError("plan_hash must be a SHA-256 digest")
        if not self.approver.startswith("@") or ":" not in self.approver:
            raise ValidationError("approver must be a full Matrix user ID")


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    work_item: str
    role: str
    repository: str
    base_ref: str
    objective: str
    api_version: str = API_VERSION
    constraints: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    acceptance_checks: tuple[str, ...] = ()
    callback: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION:
            raise ValidationError(f"unsupported api_version {self.api_version!r}")
        if not RUN_ID.fullmatch(self.run_id):
            raise ValidationError("run_id contains unsafe characters or has invalid length")
        _url("work_item", self.work_item, {"https"})
        if self.role not in ROLES:
            raise ValidationError(f"unknown role {self.role!r}")
        _url("repository", self.repository, {"https", "ssh"})
        for name in ("base_ref", "objective"):
            _nonempty(name, getattr(self, name))
        if self.base_ref.startswith("-") or any(c.isspace() for c in self.base_ref):
            raise ValidationError("base_ref is not a safe explicit ref")
        for path in self.allowed_paths:
            if path.startswith("/") or ".." in path.split("/"):
                raise ValidationError(f"unsafe allowed path {path!r}")
        allowed_limits = {"attempts", "wall_seconds", "token_budget"}
        if set(self.limits) - allowed_limits:
            raise ValidationError("unknown run limit")
        if any(not isinstance(v, int) or v <= 0 for v in self.limits.values()):
            raise ValidationError("run limits must be positive integers")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRun":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = set(value) - allowed
        if unknown:
            raise ValidationError(f"unknown AgentRun fields: {sorted(unknown)}")
        converted = dict(value)
        for key in ("constraints", "allowed_paths", "acceptance_checks"):
            converted[key] = tuple(converted.get(key, ()))
        return cls(**converted)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("constraints", "allowed_paths", "acceptance_checks"):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: Literal["succeeded", "failed", "cancelled", "needs_input"]
    summary: str
    head_sha: str | None = None
    pull_request: str | None = None
    checks: tuple[dict[str, str], ...] = ()
    artifacts: tuple[dict[str, str], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    api_version: str = API_VERSION

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION or not RUN_ID.fullmatch(self.run_id):
            raise ValidationError("invalid result identity")
        _nonempty("summary", self.summary)
        if self.head_sha is not None and not re.fullmatch(r"[0-9a-f]{7,64}", self.head_sha):
            raise ValidationError("head_sha is invalid")
        if self.pull_request is not None:
            _url("pull_request", self.pull_request, {"https"})
        for check in self.checks:
            if set(check) != {"name", "status"} or check["status"] not in {"passed", "failed", "skipped"}:
                raise ValidationError("invalid check result")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentResult":
        converted = dict(value)
        converted["checks"] = tuple(converted.get("checks", ()))
        converted["artifacts"] = tuple(converted.get("artifacts", ()))
        return cls(**converted)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["checks"] = list(value["checks"])
        value["artifacts"] = list(value["artifacts"])
        return value
