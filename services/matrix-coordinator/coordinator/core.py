"""Plan state transitions independent of Matrix, GitHub, and Argo clients."""

from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from .models import Approval, PlanVersion, ValidationError
from .state import StateStore


class IssuePort(Protocol):
    def create_plan(self, plan: PlanVersion) -> tuple[str, list[str]]: ...


class Coordinator:
    def __init__(self, state: StateStore, issues: IssuePort, approvers: set[str]):
        self.state = state
        self.issues = issues
        self.approvers = frozenset(approvers)

    def record_plan(self, plan: PlanVersion) -> bool:
        with self.state.transaction() as db:
            current = db.execute(
                "SELECT current_version, state FROM plans WHERE plan_id=?", (plan.plan_id,)
            ).fetchone()
            if current and plan.version <= current["current_version"]:
                return False
            if current and current["state"] not in {"drafting", "review"}:
                raise ValidationError("accepted plan is immutable")
            db.execute(
                "INSERT INTO plans(plan_id,state,repository,matrix_room_id,root_event_id,current_version) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET state='review', "
                "current_version=excluded.current_version",
                (plan.plan_id, "review", plan.repository, plan.matrix_room_id,
                 plan.matrix_event_id, plan.version),
            )
            db.execute(
                "INSERT INTO plan_versions VALUES (?,?,?,?,?,strftime('%s','now'))",
                (plan.plan_id, plan.version, plan.hash, plan.matrix_event_id, plan.markdown),
            )
        self.state.audit("planner", "plan.versioned", plan.plan_id, asdict(plan))
        return True

    def approve(self, approval: Approval) -> tuple[str, list[str]]:
        if approval.approver not in self.approvers:
            raise ValidationError("Matrix user is not allowed to approve")
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
                    pass
                else:
                    raise ValidationError("plan already approved at another hash")
            else:
                db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,?)",
                (approval.plan_id, approval.plan_hash, approval.matrix_event_id,
                 approval.approver, approval.approved_at),
                )
            db.execute("UPDATE plans SET state='accepted' WHERE plan_id=?", (approval.plan_id,))
            plan = PlanVersion(
                approval.plan_id, plan_row["current_version"], version["markdown"],
                plan_row["matrix_room_id"], version["matrix_event_id"], plan_row["repository"],
            )
        action_key = f"github-plan:{approval.plan_id}:{approval.plan_hash}"
        completed = self.state.begin_action(action_key, "github.create-plan", {"plan_id": approval.plan_id})
        if completed:
            issue_url, children = completed["parent"], completed["children"]
        else:
            try:
                issue_url, children = self.issues.create_plan(plan)
            except Exception as exc:
                self.state.fail_action(action_key, str(exc))
                raise
            self.state.complete_action(action_key, {"parent": issue_url, "children": children})
        with self.state.transaction() as db:
            db.execute(
                "UPDATE plans SET state='decomposed', github_issue_url=? WHERE plan_id=?",
                (issue_url, approval.plan_id),
            )
        self.state.register_work_items(approval.plan_id, issue_url, children)
        self.state.audit(approval.approver, "plan.approved", approval.plan_id,
                         {**asdict(approval), "github_issue": issue_url, "sub_issues": children})
        return issue_url, children

    def github_event(self, delivery: str, event: str, payload: dict) -> bool:
        """Reconcile a relevant GitHub issue/PR event and queue one Matrix update."""
        issue = payload.get("issue") or payload.get("pull_request")
        if not isinstance(issue, dict) or not issue.get("html_url"):
            return False
        url = issue["html_url"]
        context = self.state.work_item_context(url)
        if not context:
            return False
        state = issue.get("state", "open")
        changed = self.state.update_work_item(url, state, {
            "kind": event, "action": payload.get("action"), "url": url,
            "title": issue.get("title", ""), "state": state,
        })
        if changed:
            action = payload.get("action") or "updated"
            body = f"GitHub **{event} {action}**: [{issue.get('title') or url}]({url}) · `{state}`"
            self.state.enqueue_matrix(
                f"github:{delivery}", context["matrix_room_id"], context["root_event_id"], body)
            self.state.audit("github", f"{event}.{action}", url, {"delivery": delivery, "state": state})
        return changed

    def reconcile_github(self) -> int:
        changed = 0
        for row in self.state.work_items():
            issue = self.issues.get_issue(row["external_id"])
            state = issue.get("state", "open")
            payload = {"kind": "issue", "url": row["external_id"],
                       "title": issue.get("title", ""), "state": state}
            if self.state.update_work_item(row["external_id"], state, payload):
                changed += 1
                self.state.enqueue_matrix(
                    "reconcile:" + __import__("hashlib").sha256(
                        (row["external_id"] + ":" + state).encode()).hexdigest(),
                    row["matrix_room_id"], row["root_event_id"],
                    f"GitHub reconciled: [{issue.get('title') or row['external_id']}]"
                    f"({row['external_id']}) · `{state}`",
                )
        return changed
