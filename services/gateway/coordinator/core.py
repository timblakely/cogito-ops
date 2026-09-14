"""Plan state transitions independent of Matrix and GitHub clients."""

from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from .models import Approval, PlanVersion, ValidationError
from .state import StateStore


class IssuePort(Protocol):
    def publish_plan(self, plan: PlanVersion) -> str: ...
    def create_deliverables(self, plan: PlanVersion, parent_url: str) -> list[str]: ...
    def request_merge(self, pr_url: str, expected_head_sha: str,
                      expected_branch: str) -> dict: ...
    def merge_result(self, pr_url: str, merge_uuid: str) -> dict: ...
    def checks_status(self, pr_url: str) -> dict: ...


class Coordinator:
    def __init__(self, state: StateStore, issues: IssuePort, approvers: set[str],
                 github_approvers: set[str] | None = None):
        self.state = state
        self.issues = issues
        self.approvers = frozenset(approvers)
        self.github_approvers = frozenset(github_approvers or set())

    def record_plan(self, plan: PlanVersion) -> bool:
        current = self.state.plan(plan.plan_id)
        if current and plan.version <= current["current_version"]:
            return False
        if current and current["state"] not in {
                "intake", "researching", "synthesizing", "research_failed",
                "drafting", "review"}:
            raise ValidationError("approved plan is immutable")
        # GitHub is the review object from the first draft. Publishing first is
        # safe because the plan-id marker makes retries idempotent.
        issue_url = self.issues.publish_plan(plan)
        with self.state.transaction() as db:
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,"
                "current_version,github_issue_url) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(plan_id) DO UPDATE SET state='review', "
                "current_version=excluded.current_version,"
                "github_issue_url=excluded.github_issue_url",
                (plan.plan_id, "review", plan.repository, plan.matrix_room_id,
                 plan.matrix_event_id, plan.version, issue_url),
            )
            db.execute(
                "INSERT INTO plan_versions VALUES (?,?,?,?,?,strftime('%s','now'))",
                (plan.plan_id, plan.version, plan.hash, plan.matrix_event_id, plan.markdown),
            )
        self.state.audit("planner", "plan.versioned", plan.plan_id, asdict(plan))
        self.state.enqueue_plan_card(plan.plan_id)
        return True

    def record_github_edit(self, issue_url: str, body: str, delivery_id: str,
                           actor: str) -> tuple[str, str]:
        from .github import plan_markdown_from_issue
        plan_id, markdown = plan_markdown_from_issue(body)
        row = self.state.plan(plan_id)
        if not row:
            raise ValidationError("GitHub event references an unknown plan")
        if row["github_issue_url"] != issue_url:
            raise ValidationError("GitHub event does not match the plan review issue")
        current = self.state.current_plan_version(plan_id)
        candidate = PlanVersion(
            plan_id, row["current_version"] + 1, markdown, row["matrix_room_id"],
            f"github:{delivery_id}", row["repository"],
        )
        if candidate.hash == current["content_hash"]:
            return plan_id, candidate.hash
        if self.state.approval(plan_id):
            raise ValidationError(
                "approved plan body is frozen; remove workflow/approved before editing")
        normalized_url = self.issues.publish_plan(candidate)
        if normalized_url != issue_url:
            raise ValidationError("GitHub normalized a plan edit onto another issue")
        with self.state.transaction() as db:
            db.execute("UPDATE plans SET state='review',current_version=? WHERE plan_id=?",
                       (candidate.version, plan_id))
            db.execute(
                "INSERT INTO plan_versions VALUES (?,?,?,?,?,strftime('%s','now'))",
                (plan_id, candidate.version, candidate.hash, candidate.matrix_event_id,
                 candidate.markdown),
            )
        self.state.audit(f"github:{actor}", "plan.body-edited", plan_id,
                         {"hash": candidate.hash, "delivery": delivery_id})
        self.state.enqueue_plan_card(plan_id)
        return plan_id, candidate.hash

    def approve(self, approval: Approval, source: str = "matrix") -> tuple[str, list[str]]:
        allowed = self.approvers if source == "matrix" else self.github_approvers
        if approval.approver not in allowed:
            raise ValidationError(f"{source.title()} user is not allowed to approve")
        already_advanced = False
        with self.state.transaction() as db:
            plan_row = db.execute(
                "SELECT * FROM plans WHERE plan_id=?", (approval.plan_id,)
            ).fetchone()
            if not plan_row:
                raise ValidationError("unknown plan")
            version = db.execute(
                "SELECT * FROM plan_versions WHERE plan_id=? AND version=?",
                (approval.plan_id, plan_row["current_version"]),
            ).fetchone()
            if version["content_hash"] != approval.plan_hash:
                raise ValidationError("approval targets an obsolete plan version")
            existing = db.execute(
                "SELECT content_hash FROM approvals WHERE plan_id=?", (approval.plan_id,)
            ).fetchone()
            if existing:
                if existing["content_hash"] == approval.plan_hash:
                    already_advanced = plan_row["state"] in {
                        "decomposed", "running", "completed", "paused", "needs_input",
                        "failed", "cancelled",
                    }
                else:
                    raise ValidationError("plan already approved at another hash")
            else:
                db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,?)",
                (approval.plan_id, approval.plan_hash, approval.matrix_event_id,
                 approval.approver, approval.approved_at),
                )
            if not already_advanced:
                db.execute("UPDATE plans SET state='accepted' WHERE plan_id=?", (approval.plan_id,))
            plan = PlanVersion(
                approval.plan_id, plan_row["current_version"], version["markdown"],
                plan_row["matrix_room_id"], version["matrix_event_id"], plan_row["repository"],
            )
        issue_url = plan_row["github_issue_url"]
        if not issue_url:
            raise ValidationError("plan has no GitHub review issue")
        if already_advanced:
            return issue_url, self.state.deliverable_urls(approval.plan_id)
        action_key = f"github-deliverables:{approval.plan_id}:{approval.plan_hash}"
        completed = self.state.begin_action(
            action_key, "github.create-deliverables", {"plan_id": approval.plan_id})
        if completed:
            children = completed["children"]
        else:
            try:
                children = self.issues.create_deliverables(plan, issue_url)
            except Exception as exc:
                self.state.fail_action(action_key, str(exc))
                raise
            self.state.complete_action(action_key, {"children": children})
        with self.state.transaction() as db:
            db.execute(
                "UPDATE plans SET state='decomposed', github_issue_url=? WHERE plan_id=?",
                (issue_url, approval.plan_id),
            )
        self.state.register_deliverables(approval.plan_id, children)
        self.state.enqueue_coordinator_event(
            f"approval:{approval.matrix_event_id}", approval.plan_id, source,
            "plan.approved", {
                "actor": approval.approver,
                "plan_hash": approval.plan_hash,
                "plan_issue_url": issue_url,
                "deliverables": children,
            }, delay_seconds=0,
        )
        self.state.audit(approval.approver, "plan.approved", approval.plan_id,
                         {**asdict(approval), "github_issue": issue_url, "sub_issues": children})
        self.state.enqueue_plan_card(approval.plan_id)
        return issue_url, children

    def approve_github(self, issue_url: str, body: str, delivery_id: str, actor: str,
                       timestamp: str) -> tuple[str, list[str]]:
        plan_id, digest = self.record_github_edit(
            issue_url, body, delivery_id + ":body", actor)
        return self.approve(Approval(
            plan_id, digest, f"github:{delivery_id}", actor, timestamp), source="github")

    def reopen_review(self, issue_url: str, actor: str, delivery_id: str) -> str:
        row = self.state.plan_for_github_url(issue_url)
        if not row or row["github_issue_url"] != issue_url:
            raise ValidationError("approval label was removed from an unknown plan issue")
        with self.state.transaction() as db:
            removed = db.execute(
                "DELETE FROM approvals WHERE plan_id=?", (row["plan_id"],)
            ).rowcount
            changed = bool(removed or row["state"] != "review")
            db.execute("UPDATE plans SET state='review' WHERE plan_id=?", (row["plan_id"],))
        if not changed:
            return row["plan_id"]
        self.state.enqueue_coordinator_event(
            f"github:{delivery_id}:approval-removed", row["plan_id"], "github",
            "plan.approval_removed", {"actor": actor, "issue": issue_url},
            delay_seconds=0,
        )
        self.state.audit(f"github:{actor}", "plan.approval-removed", row["plan_id"],
                         {"delivery": delivery_id})
        self.state.enqueue_plan_card(row["plan_id"])
        return row["plan_id"]
