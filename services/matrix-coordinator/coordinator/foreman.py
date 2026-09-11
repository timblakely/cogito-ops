"""Small Kubernetes API gateway for Foreman Workloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import json
import re
import ssl

from .models import ValidationError


ISSUE_PATH = re.compile(r"^/([^/]+)/([^/]+)/issues/([1-9][0-9]*)$")
DNS_SAFE = re.compile(r"[^a-z0-9-]+")


def _repo_slug(repository: str) -> str:
    parsed = urlparse(repository)
    path = parsed.path.removesuffix(".git").strip("/")
    parts = path.split("/")
    if parsed.hostname != "github.com" or len(parts) != 2 or not all(parts):
        raise ValidationError("Foreman currently requires a github.com owner/repository URL")
    return "/".join(parts)


def _issue_numbers(repo: str, issue_urls: list[str]) -> list[int]:
    numbers = []
    for url in issue_urls:
        parsed = urlparse(url)
        match = ISSUE_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or not match:
            raise ValidationError(f"invalid GitHub issue URL: {url}")
        if f"{match.group(1)}/{match.group(2)}".lower() != repo.lower():
            raise ValidationError("all deliverable issues must belong to the plan repository")
        numbers.append(int(match.group(3)))
    if not numbers:
        raise ValidationError("approved plan has no deliverable issues")
    return numbers


def workload_name(plan_id: str, plan_hash: str) -> str:
    stem = DNS_SAFE.sub("-", plan_id.lower()).strip("-")[:42] or "plan"
    return f"{stem}-{plan_hash.removeprefix('sha256:')[:12]}"[:63].rstrip("-")


@dataclass
class ForemanClient:
    namespace: str = "llm"
    api_server: str = "https://kubernetes.default.svc"
    token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    # Foreman's gate template clones to /work. Its upstream Debian Go image
    # runs as root and can create that directory; the non-root coder image
    # cannot. The tag is retained for readability and the digest is authority.
    gate_image: str = (
        "docker.io/library/golang:1.26@"
        "sha256:3c3e25a4da13fd0478eed2df1eb35a0e667094a7124d3993a6a1d30f71c17e79"
    )

    @property
    def collection_path(self) -> str:
        return f"/apis/foreman.llmkube.dev/v1alpha1/namespaces/{self.namespace}/workloads"

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        token = Path(self.token_path).read_text().strip()
        request = Request(
            self.api_server + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        context = ssl.create_default_context(cafile=self.ca_path)
        with urlopen(request, timeout=30, context=context) as response:
            return json.load(response)

    def manifest(self, plan_id: str, plan_hash: str, intent: str, repository: str,
                 issue_urls: list[str], room_id: str, thread_root: str) -> dict:
        repo = _repo_slug(repository)
        issues = _issue_numbers(repo, issue_urls)
        name = workload_name(plan_id, plan_hash)
        return {
            "apiVersion": "foreman.llmkube.dev/v1alpha1",
            "kind": "Workload",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/part-of": "foreman",
                    "cogito.dev/plan-id": plan_id,
                },
                "annotations": {
                    "cogito.dev/plan-hash": plan_hash,
                    "cogito.dev/matrix-room": room_id,
                    "cogito.dev/matrix-thread": thread_root,
                },
            },
            "spec": {
                "intent": intent,
                "repo": repo,
                "issues": issues,
                # Base coder/gate/reviewer plus one bounded reviewer repair round.
                "maxTasks": len(issues) * 6,
                "maxReviewIterations": 1,
                "coderAgentRef": {"name": "cogito-coder"},
                "verifierAgentRef": {"name": "cogito-gate"},
                "reviewerAgentRefs": [{"name": "cogito-reviewer"}],
                "allowCloudReviewers": False,
                "openPullRequest": True,
                "gateProfile": {
                    "language": "generic",
                    "image": self.gate_image,
                    "sourceExtensions": [".py", ".yaml", ".yml", ".json", ".md"],
                    "commands": {
                        "lint": "git diff --check origin/main...HEAD -- ."
                    },
                },
            },
        }

    def ensure_workload(self, **values) -> dict:
        desired = self.manifest(**values)
        try:
            return self._call("POST", self.collection_path, desired)
        except HTTPError as exc:
            if exc.code != 409:
                raise
            current = self.get(desired["metadata"]["name"])
            if current.get("metadata", {}).get("annotations", {}).get(
                    "cogito.dev/plan-hash") != values["plan_hash"]:
                raise RuntimeError("existing Foreman Workload has another plan hash")
            return current

    def get(self, name: str) -> dict:
        return self._call("GET", f"{self.collection_path}/{quote(name)}")

    @staticmethod
    def summary(workload: dict) -> dict:
        status = workload.get("status", {})
        return {
            "phase": status.get("phase", "Pending"),
            "succeeded": int(status.get("succeededTasks", 0)),
            "failed": int(status.get("failedTasks", 0)),
            "incomplete": int(status.get("incompleteTasks", 0)),
            "contradicted": int(status.get("contradictedTasks", 0)),
            "review_iterations": int(status.get("reviewIterations", 0)),
            "conditions": status.get("conditions", []),
        }
