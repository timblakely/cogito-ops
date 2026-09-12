"""Narrow GitHub Issues client for accepted plans and native sub-issues."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import json
import re
import time

from .models import PlanVersion, ValidationError

API_VERSION = "2026-03-10"
DELIVERABLE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$")
PULL_PATH = re.compile(r"^/([^/]+)/([^/]+)/pull/([1-9][0-9]*)$")


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


def deliverable_body(plan: PlanVersion, index: int, item: str, parent_url: str) -> str:
    """Keep the issue's executable ask in the body where Foreman verifies it."""
    return (
        f"## Deliverable\n\n{item}\n\n"
        f"<!-- cogito-plan-deliverable: {plan.plan_id}:{index} -->\n"
        f"Parent plan: {parent_url}\n\n"
        f"Accepted plan hash: `{plan.hash}`\n\n"
        "## Acceptance criteria\n\n- [ ] Deliverable implemented\n- [ ] Checks recorded\n"
    )


@dataclass
class GitHubIssues:
    token: str | None = None
    matrix_base_url: str = "https://matrix.to/#"
    api_base: str = "https://api.github.com"
    token_file: str | None = None

    def _authorization_token(self) -> str:
        """Read projected App tokens for every request so rotation is immediate."""
        if self.token_file:
            token = Path(self.token_file).read_text().strip()
            if token:
                return token
        if self.token:
            return self.token
        raise RuntimeError("GitHub credential is empty")

    def _request_with_status(self, method: str, path: str, body: dict | None = None,
                             allowed_errors: set[int] | None = None) -> tuple[int, object]:
        request = Request(
            self.api_base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._authorization_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "Content-Type": "application/json",
                "User-Agent": "cogito-matrix-coordinator/0.1",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            if not allowed_errors or exc.code not in allowed_errors:
                raise
            return exc.code, json.load(exc)

    def _request(self, method: str, path: str, body: dict | None = None):
        return self._request_with_status(method, path, body)[1]

    @staticmethod
    def _pull_identity(pr_url: str) -> tuple[str, int]:
        parsed = urlparse(pr_url)
        match = PULL_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or not match:
            raise ValidationError(f"invalid GitHub pull request URL: {pr_url}")
        return f"{match.group(1)}/{match.group(2)}", int(match.group(3))

    def request_merge(self, pr_url: str, expected_head_sha: str, expected_branch: str) -> dict:
        """Queue a squash merge, pinned to the exact branch revision reviewed."""
        slug, number = self._pull_identity(pr_url)
        pull = self._request("GET", f"/repos/{slug}/pulls/{number}")
        if pull.get("merged"):
            return {"status": "merged", "details": {"sha": pull.get("merge_commit_sha")}}
        if pull.get("state") != "open" or pull.get("draft"):
            raise RuntimeError("reviewed pull request is not open and ready for merge")
        if pull.get("base", {}).get("ref") != "main":
            raise RuntimeError("reviewed pull request does not target main")
        if pull.get("head", {}).get("repo", {}).get("full_name", "").lower() != slug.lower():
            raise RuntimeError("reviewed pull request head belongs to another repository")
        if pull.get("head", {}).get("ref") != expected_branch:
            raise RuntimeError("reviewed pull request branch does not match Foreman")
        if pull.get("head", {}).get("sha") != expected_head_sha:
            raise RuntimeError("pull request changed after reviewer quorum")
        _, result = self._request_with_status(
            "PUT", f"/repos/{slug}/pulls/{number}/merge-async",
            {"sha": expected_head_sha, "merge_method": "squash", "merge_action": "default"},
            allowed_errors={409},
        )
        if not isinstance(result, dict):
            raise RuntimeError("GitHub returned an invalid asynchronous merge response")
        merge_uuid = result.get("uuid") or result.get("details", {}).get("uuid")
        if result.get("status") != "merged" and not merge_uuid:
            raise RuntimeError("GitHub did not return an asynchronous merge UUID")
        return {**result, "uuid": merge_uuid}

    def merge_result(self, pr_url: str, merge_uuid: str) -> dict:
        slug, number = self._pull_identity(pr_url)
        result = self._request(
            "GET", f"/repos/{slug}/pulls/{number}/merge-async/{quote(merge_uuid, safe='')}")
        if not isinstance(result, dict) or not result.get("status"):
            raise RuntimeError("GitHub returned an invalid asynchronous merge result")
        return result

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
        marker = f"<!-- cogito-plan-id: {plan.plan_id} -->"
        existing = self._request(
            "GET", f"/repos/{slug}/issues?state=all&labels=workflow%2Fplan&per_page=100")
        parent = next((issue for issue in existing if marker in (issue.get("body") or "")), None)
        if parent is None:
            parent = self._request("POST", f"/repos/{slug}/issues", {
                "title": f"[plan] {title_line}", "body": body,
                "labels": ["workflow/plan", "workflow/accepted"],
            })
        children = []
        child_records = []
        for index, item in enumerate(deliverables(plan.markdown), 1):
            child_marker = f"<!-- cogito-plan-deliverable: {plan.plan_id}:{index} -->"
            child_body = deliverable_body(plan, index, item, parent["html_url"])
            child = next((issue for issue in existing if child_marker in (issue.get("body") or "")), None)
            if child is not None:
                children.append(child["html_url"])
                child_records.append(child)
                continue
            child = self._request("POST", f"/repos/{slug}/issues", {
                "title": item,
                "body": child_body,
                "labels": ["workflow/deliverable"],
                "parent_issue_id": parent["id"],
            })
            children.append(child["html_url"])
            child_records.append(child)
            if index < len(deliverables(plan.markdown)):
                time.sleep(0.5)
        # A plan checklist is ordered. Represent that order with native issue
        # dependencies so later deliverables cannot be mistaken as runnable
        # before their predecessor is accepted.
        for blocker, blocked in zip(child_records, child_records[1:]):
            dependencies = self._request(
                "GET", f"/repos/{slug}/issues/{blocked['number']}/dependencies/blocked_by")
            if not any(issue["id"] == blocker["id"] for issue in dependencies):
                self._request(
                    "POST", f"/repos/{slug}/issues/{blocked['number']}/dependencies/blocked_by",
                    {"issue_id": blocker["id"]})
        return parent["html_url"], children
