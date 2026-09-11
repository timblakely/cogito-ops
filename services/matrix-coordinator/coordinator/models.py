"""Versioned domain objects and strict boundary validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse
import json
import re


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
