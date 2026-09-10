"""Deterministic risk and execution-budget policy."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class Risk(StrEnum):
    LOW = "low"
    WORKLOAD = "workload"
    HIGH = "high"


@dataclass(frozen=True)
class PolicyDecision:
    risk: Risk
    merge_requires_approval: bool
    reason: str


HIGH_RISK_PREFIXES = (
    "kubernetes/talos/", "kubernetes/bootstrap/", "bootstrap/",
    "kubernetes/apps/cluster-infra/onepassword/",
)
WORKLOAD_PREFIXES = ("kubernetes/",)
SECRET_WORDS = ("secret", "credential", "password", "private-key", "access")


def classify(paths: list[str]) -> PolicyDecision:
    normalized = [str(PurePosixPath(p)) for p in paths]
    if any(p.startswith(HIGH_RISK_PREFIXES) for p in normalized) or any(
        word in PurePosixPath(p).name.lower() for p in normalized for word in SECRET_WORDS
    ):
        return PolicyDecision(Risk.HIGH, True, "access, secret, Talos, or bootstrap boundary")
    if any(p.startswith(WORKLOAD_PREFIXES) for p in normalized):
        return PolicyDecision(Risk.WORKLOAD, True, "workload GitOps change")
    return PolicyDecision(Risk.LOW, False, "documentation or low-risk maintenance")


def within_budget(attempt: int, elapsed_seconds: int, tokens: int, limits: dict[str, int]) -> bool:
    checks = {
        "attempts": attempt,
        "wall_seconds": elapsed_seconds,
        "token_budget": tokens,
    }
    return all(checks[key] <= value for key, value in limits.items())
