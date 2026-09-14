"""Authenticated internal and GitHub webhook boundaries."""

from hashlib import sha256
from hmac import compare_digest, new
import json

from .models import ValidationError, canonical_json


def verify_internal(secret: bytes, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + new(secret, body, sha256).hexdigest()
    return compare_digest(expected, signature)


def verify_github(secret: bytes, body: bytes, signature: str | None) -> bool:
    return verify_internal(secret, body, signature)


class GitHubWebhook:
    """Verify, deduplicate, and apply plan-lifecycle repository events."""

    def __init__(self, secret: bytes, state, core, issues):
        self.secret, self.state, self.core, self.issues = secret, state, core, issues

    def _plan_id(self, payload: dict, issue_url: str) -> str | None:
        if issue_url and (row := self.state.plan_for_github_url(issue_url)):
            return row["plan_id"]
        pull_url = (payload.get("pull_request") or {}).get("html_url") or ""
        if pull_url and (row := self.state.plan_for_github_url(pull_url)):
            return row["plan_id"]
        # A newly opened PR is not yet recorded on its deliverable row. Foreman
        # includes the deliverable URL in the PR body, so resolve only exact
        # URLs already owned by this state store.
        pull_body = str((payload.get("pull_request") or {}).get("body") or "")
        for candidate in pull_body.replace("(", " ").replace(")", " ").split():
            candidate = candidate.rstrip(".,:;]")
            if candidate.startswith("https://github.com/"):
                row = self.state.plan_for_github_url(candidate)
                if row:
                    return row["plan_id"]
        return None

    @staticmethod
    def _packet(event: str, payload: dict) -> dict:
        issue = payload.get("issue") or {}
        pull = payload.get("pull_request") or {}
        comment = payload.get("comment") or {}
        review = payload.get("review") or {}
        checks = payload.get("check_suite") or {}
        comment_body = str(comment.get("body") or review.get("body") or "")
        gateway_action = "<!-- cogito-action:" in comment_body
        return {
            "event": event, "action": payload.get("action"),
            "actor": (payload.get("sender") or {}).get("login"),
            "issue": issue.get("html_url"), "pull_request": pull.get("html_url"),
            "title": str(issue.get("title") or pull.get("title") or "")[:500],
            # Gateway-authored writes still wake Luna as state transitions,
            # but their marker prevents an output→input feedback loop.
            "comment": "" if gateway_action else comment_body[:8_000],
            "gateway_action": gateway_action,
            "comment_url": comment.get("html_url"),
            "review_state": review.get("state"),
            "check_conclusion": checks.get("conclusion"),
            "head_sha": checks.get("head_sha") or (pull.get("head") or {}).get("sha"),
        }

    def _queue(self, delivery: str, event: str, payload: dict,
               issue_url: str, delay: int = 30) -> list[str]:
        plan_id = self._plan_id(payload, issue_url)
        if plan_id:
            plan_ids = [plan_id]
        else:
            repository = (payload.get("repository") or {}).get("html_url") or ""
            plan_ids = [row["plan_id"]
                        for row in self.state.active_plans_for_repository(repository)]
        for plan_id in plan_ids:
            self.state.enqueue_coordinator_event(
                f"github:{delivery}:{plan_id}", plan_id, "github",
                f"github.{event}.{payload.get('action') or 'event'}",
                self._packet(event, payload), delay_seconds=delay,
            )
        return plan_ids

    def handle(self, headers, body: bytes) -> tuple[int, dict]:
        if not verify_github(self.secret, body, headers.get("X-Hub-Signature-256")):
            return 401, {"error": "invalid GitHub signature"}
        delivery = headers.get("X-GitHub-Delivery", "").strip()
        event = headers.get("X-GitHub-Event", "").strip()
        if not delivery or not event:
            raise ValidationError("GitHub delivery headers are required")
        payload = json.loads(body)
        payload_hash = sha256(canonical_json(payload).encode()).hexdigest()
        if not self.state.accept_event("github", delivery, payload_hash):
            return 200, {"accepted": False, "duplicate": True}

        try:
            return self._handle_accepted(delivery, event, payload)
        except Exception:
            # GitHub retries non-2xx deliveries. Admission is not completion:
            # release this identity so a transient API failure is recoverable.
            # Outbound mutations use their own markers/action keys.
            self.state.release_event("github", delivery, payload_hash)
            raise

    def _handle_accepted(self, delivery: str, event: str,
                         payload: dict) -> tuple[int, dict]:

        action = payload.get("action")
        issue = payload.get("issue") or {}
        sender = (payload.get("sender") or {}).get("login", "")
        issue_body = issue.get("body") or ""
        issue_url = issue.get("html_url") or ""
        timestamp = issue.get("updated_at") or payload.get("comment", {}).get("updated_at") or ""

        if event == "issues" and action == "edited":
            plan_id, digest = self.core.record_github_edit(
                issue_url, issue_body, delivery, sender)
            self._queue(delivery, event, payload, issue_url)
            return 202, {"accepted": True, "plan_id": plan_id, "hash": digest}
        if (event == "issues" and action == "labeled"
                and (payload.get("label") or {}).get("name") == "workflow/approved"):
            current_body = self.issues.get_issue(issue_url).get("body") or ""
            if current_body != issue_body:
                raise ValidationError(
                    "plan body changed after the approving label event; review and approve again")
            parent, children = self.core.approve_github(
                issue_url, current_body, delivery, sender, timestamp)
            return 202, {"accepted": True, "parent": parent, "children": children}
        if (event == "issues" and action == "unlabeled"
                and (payload.get("label") or {}).get("name") == "workflow/approved"):
            plan_id = self.core.reopen_review(issue_url, sender, delivery)
            return 202, {"accepted": True, "plan_id": plan_id, "state": "review"}
        comment = (payload.get("comment") or {}).get("body", "").strip()
        gateway_action = "<!-- cogito-action:" in comment
        if event == "issue_comment" and action == "created" and comment == "/approve":
            if sender not in self.core.github_approvers:
                raise ValidationError("GitHub user is not allowed to approve")
            current_body = self.issues.get_issue(issue_url).get("body") or ""
            if current_body != issue_body:
                raise ValidationError(
                    "plan body changed after /approve; review and approve again")
            self.issues.apply_label(issue_url, "workflow/approved")
            parent, children = self.core.approve_github(
                issue_url, current_body, delivery, sender, timestamp)
            return 202, {"accepted": True, "parent": parent, "children": children}
        exact_plan_id = self._plan_id(payload, issue_url)
        plan_ids = self._queue(delivery, event, payload, issue_url)
        if (event == "issue_comment" and action in {"created", "edited"}
                and exact_plan_id and comment and not gateway_action):
            self.state.add_plan_comment(
                f"github:{delivery}:comment", exact_plan_id, f"github:{sender}", comment)
        return 202, {"accepted": True, "queued": bool(plan_ids),
                     "plan_id": exact_plan_id, "plan_ids": plan_ids}
