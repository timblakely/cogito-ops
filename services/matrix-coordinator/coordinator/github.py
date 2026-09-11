"""Narrow GitHub Issues client for accepted plans and native sub-issues."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import json
import re
import time

from .models import AgentResult, AgentRun, PlanVersion, ValidationError

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

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
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
            child_body = (f"{child_marker}\nParent plan: {parent['html_url']}\n\n"
                          f"Accepted plan hash: `{plan.hash}`\n\n"
                          "## Acceptance criteria\n\n- [ ] Deliverable implemented\n- [ ] Checks recorded\n")
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

    def get_issue(self, url: str) -> dict:
        slug = repository_slug("https://github.com/" + "/".join(urlparse(url).path.strip("/").split("/")[:2]))
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) != 4 or parts[2] != "issues" or not parts[3].isdigit():
            raise ValidationError("work item is not a GitHub issue URL")
        return self._request("GET", f"/repos/{slug}/issues/{parts[3]}")

    def close_issue(self, url: str) -> dict:
        slug, number = self._issue_parts(url)
        issue = self._request("GET", f"/repos/{slug}/issues/{number}")
        if issue.get("state") == "closed":
            return issue
        return self._request(
            "PATCH", f"/repos/{slug}/issues/{number}",
            {"state": "closed", "state_reason": "completed"},
        )

    @staticmethod
    def _issue_parts(url: str) -> tuple[str, int]:
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) != 4 or parts[2] != "issues" or not parts[3].isdigit():
            raise ValidationError("work item is not a GitHub issue URL")
        return "/".join(parts[:2]), int(parts[3])

    @staticmethod
    def _pull_parts(url: str) -> tuple[str, int]:
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) != 4 or parts[2] != "pull" or not parts[3].isdigit():
            raise ValidationError("value is not a GitHub pull request URL")
        return "/".join(parts[:2]), int(parts[3])

    def create_pull_request(self, run: AgentRun, result: AgentResult) -> str:
        slug, issue_number = self._issue_parts(run.work_item)
        ref = result.usage.get("published_ref")
        if not isinstance(ref, str) or not ref.startswith("refs/heads/agent/"):
            raise ValidationError("agent result has no safe published ref")
        branch = ref.removeprefix("refs/heads/")
        owner = slug.split("/", 1)[0]
        existing = self._request(
            "GET", f"/repos/{slug}/pulls?state=all&head={owner}%3A{branch}&per_page=10")
        if existing:
            return existing[0]["html_url"]
        issue = self._request("GET", f"/repos/{slug}/issues/{issue_number}")
        body = (f"<!-- cogito-run-id: {run.run_id} -->\n"
                f"Closes #{issue_number}\n\n"
                f"Automated delivery for {run.work_item}.\n\n"
                f"Agent result: {result.summary[:2000]}")
        pull = self._request("POST", f"/repos/{slug}/pulls", {
            "title": issue.get("title") or f"Complete #{issue_number}",
            "head": branch, "base": run.base_ref, "body": body,
        })
        return pull["html_url"]

    def add_review_evidence(self, pull_url: str, run_id: str, summary: str) -> None:
        slug, number = self._pull_parts(pull_url)
        marker = f"<!-- cogito-review-run: {run_id} -->"
        comments = self._request("GET", f"/repos/{slug}/issues/{number}/comments?per_page=100")
        if any(marker in (comment.get("body") or "") for comment in comments):
            return
        self._request("POST", f"/repos/{slug}/issues/{number}/comments", {
            "body": f"{marker}\nIndependent agent review: **approved**\n\n{summary[:4000]}"
        })

    def close_superseded_pull(self, pull_url: str, reason: str) -> None:
        slug, number = self._pull_parts(pull_url)
        self._request("POST", f"/repos/{slug}/issues/{number}/comments", {
            "body": "Superseded by a bounded automated repair.\n\n" + reason[:2000]
        })
        self._request("PATCH", f"/repos/{slug}/pulls/{number}", {"state": "closed"})

    def pull_status(self, pull_url: str) -> dict:
        slug, number = self._pull_parts(pull_url)
        pull = self._request("GET", f"/repos/{slug}/pulls/{number}")
        checks = self._request("GET", f"/repos/{slug}/commits/{pull['head']['sha']}/check-runs?per_page=100")
        runs = checks.get("check_runs", [])
        blocked = [run for run in runs if run.get("status") != "completed" or
                   run.get("conclusion") not in {"success", "neutral", "skipped"}]
        return {"head_sha": pull["head"]["sha"], "merged": pull.get("merged", False),
                "mergeable": pull.get("mergeable"), "checks": len(runs), "blocked_checks": len(blocked)}

    def merge_pull_request(self, pull_url: str, expected_head: str) -> str:
        slug, number = self._pull_parts(pull_url)
        status = self.pull_status(pull_url)
        if status["merged"]:
            pull = self._request("GET", f"/repos/{slug}/pulls/{number}")
            return pull["merge_commit_sha"]
        if status["head_sha"] != expected_head:
            raise ValidationError("pull request head changed after review")
        if status["mergeable"] is not True or status["blocked_checks"]:
            raise ValidationError("pull request is not ready to merge")
        merged = self._request("PUT", f"/repos/{slug}/pulls/{number}/merge", {
            "sha": expected_head, "merge_method": "squash",
        })
        if not merged.get("merged"):
            raise ValidationError(merged.get("message") or "GitHub refused merge")
        return merged["sha"]
