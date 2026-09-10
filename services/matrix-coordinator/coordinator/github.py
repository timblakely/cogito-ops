"""Narrow GitHub Issues client for accepted plans and native sub-issues."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import json
import re
import time

from .models import PlanVersion, ValidationError

API_VERSION = "2026-03-10"
DELIVERABLE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$")


def repository_slug(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.removesuffix(".git").strip("/")
    if parsed.netloc != "github.com" or path.count("/") != 1:
        raise ValidationError("coordinator currently accepts github.com owner/repository URLs")
    return path


def deliverables(markdown: str) -> list[str]:
    """Extract top-level unchecked/checklist deliverables from the accepted plan."""
    result = []
    in_section = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().lower() in {"deliverables", "implementation checklist"}
            continue
        if in_section and (match := DELIVERABLE.match(line)):
            result.append(match.group(1))
    if not result:
        result.append("Implement and verify the accepted plan")
    if len(result) > 100:
        raise ValidationError("GitHub supports at most 100 direct sub-issues")
    return result


@dataclass
class GitHubIssues:
    token: str
    matrix_base_url: str = "https://matrix.to/#"
    api_base: str = "https://api.github.com"

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        request = Request(
            self.api_base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "Content-Type": "application/json",
                "User-Agent": "cogito-matrix-coordinator/0.1",
            },
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def create_plan(self, plan: PlanVersion) -> tuple[str, list[str]]:
        slug = repository_slug(plan.repository)
        title_line = next((l.removeprefix("# ").strip() for l in plan.markdown.splitlines()
                           if l.startswith("# ")), plan.plan_id)
        permalink = f"{self.matrix_base_url}/{plan.matrix_room_id}/{plan.matrix_event_id}"
        body = (
            f"<!-- cogito-plan-id: {plan.plan_id} -->\n"
            f"<!-- cogito-plan-hash: {plan.hash} -->\n"
            f"Matrix review: {permalink}\n\n{plan.markdown}"
        )
        parent = self._request("POST", f"/repos/{slug}/issues", {
            "title": f"[plan] {title_line}", "body": body,
            "labels": ["workflow/plan", "workflow/accepted"],
        })
        children = []
        for index, item in enumerate(deliverables(plan.markdown), 1):
            child = self._request("POST", f"/repos/{slug}/issues", {
                "title": item,
                "body": (f"Parent plan: {parent['html_url']}\n\n"
                         f"Accepted plan hash: `{plan.hash}`\n\n"
                         "## Acceptance criteria\n\n- [ ] Deliverable implemented\n- [ ] Checks recorded\n"),
                "labels": ["workflow/deliverable"],
                "parent_issue_id": parent["id"],
            })
            children.append(child["html_url"])
            if index < len(deliverables(plan.markdown)):
                time.sleep(0.5)
        return parent["html_url"], children
