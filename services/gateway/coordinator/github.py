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
ISSUE_URL_PATH = re.compile(r"^/([^/]+)/([^/]+)/issues/([1-9][0-9]*)$")
PLAN_ID_MARKER = re.compile(r"<!--\s*cogito-plan-id:\s*([^\s]+)\s*-->")
DELIVERABLE_HEADING = re.compile(r"^\*\*(.+?)\*\*(?:\s|$)")
MAX_ISSUE_TITLE = 240


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


def deliverable_specs(markdown: str) -> list[tuple[str, int | None]]:
    """Return checklist text and nearest less-indented parent position."""
    result: list[tuple[str, int | None]] = []
    stack: list[tuple[int, int]] = []
    in_section = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().lower() in {
                "deliverables", "implementation checklist"}
            continue
        match = DELIVERABLE.match(line) if in_section else None
        if not match:
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None
        position = len(result)
        result.append((match.group(1), parent))
        stack.append((indent, position))
    if not result:
        result.append(("Implement and verify the approved plan", None))
    if len(result) > 100:
        raise ValidationError("a plan may contain at most 100 deliverables")
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


def deliverable_title(item: str) -> str:
    """Build a bounded GitHub title while keeping the full ask in the body."""
    match = DELIVERABLE_HEADING.match(item.strip())
    title = match.group(1) if match else item
    title = " ".join(title.split()).strip() or "Implement and verify the approved deliverable"
    if len(title) > MAX_ISSUE_TITLE:
        title = title[:MAX_ISSUE_TITLE - 3].rstrip() + "..."
    return title


def plan_issue_body(plan: PlanVersion) -> str:
    permalink = f"https://matrix.to/#/{plan.matrix_room_id}/{plan.matrix_event_id}"
    return (
        f"<!-- cogito-plan-id: {plan.plan_id} -->\n"
        f"<!-- cogito-plan-hash: {plan.hash} -->\n"
        f"Matrix thread: {permalink}\n\n{plan.markdown}"
    )


def plan_markdown_from_issue(body: str) -> tuple[str, str]:
    marker = PLAN_ID_MARKER.search(body or "")
    if not marker:
        raise ValidationError("GitHub issue is missing the Cogito plan marker")
    parts = (body or "").split("\n\n", 1)
    if len(parts) != 2:
        raise ValidationError("GitHub plan issue has no editable plan body")
    return marker.group(1), parts[1]


@dataclass
class GitHubIssues:
    token: str | None = None
    matrix_base_url: str = "https://matrix.to/#"
    api_base: str = "https://api.github.com"
    token_file: str | None = None
    required_checks: tuple[str, ...] = ("Flux Local Success",)

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
                "User-Agent": "cogito-gateway/0.1",
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

    @staticmethod
    def _issue_identity(issue_url: str) -> tuple[str, int]:
        parsed = urlparse(issue_url)
        match = ISSUE_URL_PATH.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or not match:
            raise ValidationError(f"invalid GitHub issue URL: {issue_url}")
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

    def checks_status(self, pr_url: str) -> dict:
        slug, number = self._pull_identity(pr_url)
        pull = self._request("GET", f"/repos/{slug}/pulls/{number}")
        sha = pull.get("head", {}).get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("pull request has no valid head SHA")
        response = self._request("GET", f"/repos/{slug}/commits/{sha}/check-runs?per_page=100")
        runs = {run.get("name"): run for run in response.get("check_runs", [])}
        missing = [name for name in self.required_checks if name not in runs]
        pending = [name for name in self.required_checks
                   if name in runs and runs[name].get("status") != "completed"]
        failed = [name for name in self.required_checks if name in runs
                  and runs[name].get("status") == "completed"
                  and runs[name].get("conclusion") not in {"success", "neutral", "skipped"}]
        return {"sha": sha, "ready": not missing and not pending and not failed,
                "missing": missing, "pending": pending, "failed": failed}

    def merge_result(self, pr_url: str, merge_uuid: str) -> dict:
        slug, number = self._pull_identity(pr_url)
        result = self._request(
            "GET", f"/repos/{slug}/pulls/{number}/merge-async/{quote(merge_uuid, safe='')}")
        if not isinstance(result, dict) or not result.get("status"):
            raise RuntimeError("GitHub returned an invalid asynchronous merge result")
        return result

    def publish_plan(self, plan: PlanVersion) -> str:
        slug = repository_slug(plan.repository)
        title_line = next((l.removeprefix("# ").strip() for l in plan.markdown.splitlines()
                           if l.startswith("# ")), plan.plan_id)
        body = plan_issue_body(plan)
        marker = f"<!-- cogito-plan-id: {plan.plan_id} -->"
        existing = self._request(
            "GET", f"/repos/{slug}/issues?state=all&labels=workflow%2Fplan&per_page=100")
        parent = next((issue for issue in existing if marker in (issue.get("body") or "")), None)
        if parent is None:
            parent = self._request("POST", f"/repos/{slug}/issues", {
                "title": f"[plan] {title_line}", "body": body,
                "labels": ["workflow/plan"],
            })
        elif parent.get("body") != body or parent.get("title") != f"[plan] {title_line}":
            parent = self._request("PATCH", f"/repos/{slug}/issues/{parent['number']}", {
                "title": f"[plan] {title_line}", "body": body,
            })
        return parent["html_url"]

    def apply_label(self, issue_url: str, label: str) -> None:
        slug, number = self._issue_identity(issue_url)
        self._request("POST", f"/repos/{slug}/issues/{number}/labels", {"labels": [label]})

    def remove_label(self, issue_url: str, label: str) -> None:
        slug, number = self._issue_identity(issue_url)
        self._request_with_status(
            "DELETE", f"/repos/{slug}/issues/{number}/labels/{quote(label, safe='')}",
            allowed_errors={404},
        )

    def update_issue_state(self, issue_url: str, state: str) -> None:
        if state not in {"open", "closed"}:
            raise ValidationError("issue state must be open or closed")
        slug, number = self._issue_identity(issue_url)
        self._request("PATCH", f"/repos/{slug}/issues/{number}", {"state": state})

    def comment(self, issue_url: str, body: str, marker: str | None = None) -> str:
        slug, number = self._issue_identity(issue_url)
        if marker:
            tag = f"<!-- cogito-action: {marker} -->"
            existing = self._request(
                "GET", f"/repos/{slug}/issues/{number}/comments?per_page=100")
            found = next((item for item in existing if tag in (item.get("body") or "")), None)
            if found:
                return found["html_url"]
            body = str(body).strip()[:59_000] + "\n\n" + tag
        value = self._request("POST", f"/repos/{slug}/issues/{number}/comments", {
            "body": str(body).strip()[:60_000],
        })
        return value["html_url"]

    def pull_summary(self, pr_url: str) -> dict:
        slug, number = self._pull_identity(pr_url)
        pull = self._request("GET", f"/repos/{slug}/pulls/{number}")
        return {
            "url": pull.get("html_url"), "state": pull.get("state"),
            "draft": bool(pull.get("draft")), "mergeable": pull.get("mergeable"),
            "head_sha": (pull.get("head") or {}).get("sha"),
            "base": (pull.get("base") or {}).get("ref"),
            "title": str(pull.get("title") or "")[:500],
        }

    def post_review_packet(self, pr_url: str, head_sha: str, packet: dict,
                           marker: str | None = None) -> dict:
        """Publish bounded reviewer evidence, falling back when a line is not diff-addressable."""
        slug, number = self._pull_identity(pr_url)
        agent = str(packet.get("agent") or "reviewer")[:100]
        verdict = str(packet.get("verdict") or "UNKNOWN")[:40]
        sections = [f"### {agent} · {verdict}", str(packet.get("conclusion") or "")[:4_000]]
        if packet.get("uncertainty"):
            sections.append("**Uncertainty**\n\n" + str(packet["uncertainty"])[:2_000])
        body = "\n\n".join(filter(None, sections))
        if marker:
            tag = f"<!-- cogito-action: {marker} -->"
            existing = self._request(
                "GET", f"/repos/{slug}/pulls/{number}/reviews?per_page=100")
            found = next((item for item in existing if tag in (item.get("body") or "")), None)
            if found:
                return {"url": found.get("html_url"), "id": found.get("id"),
                        "inline_comments": 0, "existing": True}
            body += "\n\n" + tag
        comments = [{
            "path": item["path"], "line": item["line"], "side": "RIGHT",
            "body": str(item.get("note") or packet.get("conclusion") or "Evidence")[:2_000],
        } for item in packet.get("evidence", [])
            if item.get("path") and isinstance(item.get("line"), int)]
        request = {"commit_id": head_sha, "event": "COMMENT", "body": body,
                   "comments": comments}
        try:
            value = self._request("POST", f"/repos/{slug}/pulls/{number}/reviews", request)
        except HTTPError as exc:
            if exc.code != 422 or not comments:
                raise
            # GitHub only accepts inline coordinates on lines in the PR diff.
            # Preserve the independent review body if a packet cited context.
            request.pop("comments")
            value = self._request("POST", f"/repos/{slug}/pulls/{number}/reviews", request)
        return {"url": value.get("html_url"), "id": value.get("id"),
                "inline_comments": len(comments)}

    def get_issue(self, issue_url: str) -> dict:
        slug, number = self._issue_identity(issue_url)
        value = self._request("GET", f"/repos/{slug}/issues/{number}")
        if not isinstance(value, dict) or value.get("html_url") != issue_url:
            raise RuntimeError("GitHub returned an invalid issue response")
        return value

    def create_deliverables(self, plan: PlanVersion, parent_url: str) -> list[str]:
        slug, parent_number = self._issue_identity(parent_url)
        parent = self._request("GET", f"/repos/{slug}/issues/{parent_number}")
        existing = self._request(
            "GET", f"/repos/{slug}/issues?state=all&labels=workflow%2Fdeliverable&per_page=100")
        children = []
        child_records = []
        specs = deliverable_specs(plan.markdown)
        for index, (item, parent_position) in enumerate(specs, 1):
            title = deliverable_title(item)
            child_marker = f"<!-- cogito-plan-deliverable: {plan.plan_id}:{index} -->"
            child_body = deliverable_body(plan, index, item, parent["html_url"])
            child = next((issue for issue in existing if child_marker in (issue.get("body") or "")), None)
            if child is not None:
                if child.get("title") != title or child.get("body") != child_body:
                    child = self._request(
                        "PATCH", f"/repos/{slug}/issues/{child['number']}",
                        {"title": title, "body": child_body, "state": "open"},
                    )
                children.append(child["html_url"])
                child_records.append(child)
                continue
            child = self._request("POST", f"/repos/{slug}/issues", {
                "title": title,
                "body": child_body,
                "labels": ["workflow/deliverable"],
                "parent_issue_id": (parent["id"] if parent_position is None
                                    else child_records[parent_position]["id"]),
            })
            children.append(child["html_url"])
            child_records.append(child)
            if index < len(specs):
                time.sleep(0.5)
        # A plan checklist is ordered. Represent that order with native issue
        # dependencies so later deliverables cannot be mistaken as runnable
        # before their predecessor is accepted.
        # Preserve author order among siblings. A nested child is blocked by
        # its previous sibling, not by the preceding item in another branch.
        previous_by_parent = {}
        for child, (_, parent_position) in zip(child_records, specs):
            blocker = previous_by_parent.get(parent_position)
            previous_by_parent[parent_position] = child
            if blocker is None:
                continue
            blocked = child
            dependencies = self._request(
                "GET", f"/repos/{slug}/issues/{blocked['number']}/dependencies/blocked_by")
            if not any(issue["id"] == blocker["id"] for issue in dependencies):
                self._request(
                    "POST", f"/repos/{slug}/issues/{blocked['number']}/dependencies/blocked_by",
                    {"issue_id": blocker["id"]})
        return children
