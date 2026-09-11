"""Autonomous worker-to-PR-to-review delivery reconciliation."""

from __future__ import annotations

from hashlib import sha256
import json

from .github import GitHubIssues
from .models import AgentResult, AgentRun, ValidationError
from .policy import classify
from .runs import RunCoordinator
from .state import StateStore


class DeliveryCoordinator:
    def __init__(self, state: StateStore, runs: RunCoordinator, github: GitHubIssues,
                 review_harnesses: tuple[str, ...] = ("opencode", "pi")):
        self.state, self.runs, self.github = state, runs, github
        self.review_harnesses = review_harnesses
        if not review_harnesses or set(review_harnesses) - {"pi", "opencode", "contract"}:
            raise ValidationError("invalid review harness list")

    def register(self, run: AgentRun, harness: str) -> None:
        self.state.register_delivery(run.work_item, run.run_id, harness)

    def _load_run(self, run_id: str) -> tuple[AgentRun, AgentResult | None, str]:
        row = self.state.run(run_id)
        if not row:
            raise ValidationError("delivery references an unknown run")
        request = json.loads(row["request_json"])
        request.pop("harness", None)
        result = AgentResult.from_dict(json.loads(row["result_json"])) if row["result_json"] else None
        return AgentRun.from_dict(request), result, row["state"]

    def _notify(self, work_item: str, suffix: str, body: str) -> None:
        context = self.state.work_item_context(work_item)
        if context:
            self.state.enqueue_matrix(
                f"delivery:{sha256((work_item + ':' + suffix).encode()).hexdigest()}",
                context["matrix_room_id"], context["root_event_id"], body)

    def _repair(self, delivery, worker: AgentRun, reason: str) -> bool:
        attempt = delivery["repair_attempts"] + 1
        if attempt >= worker.limits.get("attempts", 1):
            return False
        if delivery["pull_request_url"]:
            self.github.close_superseded_pull(delivery["pull_request_url"], reason)
        run_id = "repair-" + sha256(
            f"{delivery['work_item_external_id']}:{attempt}".encode()).hexdigest()[:20]
        repair = AgentRun(
            run_id, worker.work_item, worker.role, worker.repository, worker.base_ref,
            worker.objective + "\n\nRepair feedback:\n" + reason[:4000],
            constraints=worker.constraints, allowed_paths=worker.allowed_paths,
            acceptance_checks=worker.acceptance_checks, callback=worker.callback,
            context={**worker.context, "repair_attempt": attempt}, limits=worker.limits,
        )
        self.runs.submit(repair, delivery["worker_harness"])
        self.state.update_delivery(
            worker.work_item, state="worker_running", worker_run_id=run_id,
            pull_request_url=None, reviewer_run_id=None, review_harness=None,
            approved_head_sha=None, repair_attempts=attempt)
        self._notify(worker.work_item, f"repair-{attempt}",
                     f"Bounded repair `{run_id}` dispatched after failed evidence.")
        return True

    def reconcile_once(self) -> int:
        if self.state.control("emergency_stop", "false") == "true":
            return 0
        changed = 0
        for delivery in self.state.deliveries():
            work_item, state = delivery["work_item_external_id"], delivery["state"]
            worker, worker_result, worker_state = self._load_run(delivery["worker_run_id"])
            if state == "worker_running":
                if worker_state in {"failed", "cancelled", "needs_input"}:
                    summary = worker_result.summary if worker_result else worker_state
                    if not self._repair(delivery, worker, summary):
                        self.state.update_delivery(work_item, state="failed")
                        self._notify(work_item, "worker-failed",
                                     f"Worker `{worker.run_id}` exhausted its repair budget: {summary[:1000]}")
                    changed += 1
                elif worker_state == "succeeded" and worker_result:
                    pull = self.github.create_pull_request(worker, worker_result)
                    paths = worker_result.usage.get("changed_paths", [])
                    if not isinstance(paths, list) or not paths or not all(
                            isinstance(path, str) for path in paths):
                        raise ValidationError("worker result has no changed-path evidence")
                    decision = classify(paths)
                    index = list(sorted(d["work_item_external_id"] for d in self.state.deliveries())).index(work_item)
                    review_harness = self.review_harnesses[index % len(self.review_harnesses)]
                    review_id = "review-" + sha256((worker.run_id + ":" + worker_result.head_sha).encode()).hexdigest()[:20]
                    branch = worker_result.usage["published_ref"].removeprefix("refs/heads/")
                    review = AgentRun(
                        review_id, work_item, "reviewer", worker.repository, branch,
                        f"Independently review {pull} against {work_item}. Do not edit files. "
                        "End the final response with exactly COGITO_REVIEW: APPROVE if all acceptance "
                        "criteria are met, otherwise COGITO_REVIEW: REQUEST_CHANGES and explain why.",
                        constraints=("Do not modify the repository", "Inspect the diff against main"),
                        acceptance_checks=("Diff matches the issue", "No unrelated changes"),
                        context={"pull_request": pull, "worker_run": worker.run_id},
                        limits={"attempts": 1, "wall_seconds": 1800, "token_budget": 100000},
                    )
                    self.runs.submit(review, review_harness)
                    self.state.update_delivery(
                        work_item, state="review_running", pull_request_url=pull,
                        reviewer_run_id=review_id, review_harness=review_harness, risk=decision.risk.value)
                    self._notify(work_item, "pr", f"Opened {pull}; independent review `{review_id}` is running.")
                    changed += 1
            elif state == "review_running":
                _, review_result, review_state = self._load_run(delivery["reviewer_run_id"])
                if review_state in {"failed", "cancelled", "needs_input"}:
                    summary = review_result.summary if review_result else "review workflow failed"
                    if not self._repair(delivery, worker, summary):
                        self.state.update_delivery(work_item, state="failed")
                        self._notify(work_item, "review-failed",
                                     f"Review repair budget exhausted for {delivery['pull_request_url']}: {summary[:1000]}")
                    changed += 1
                elif review_state == "succeeded" and review_result:
                    if review_result.usage.get("review_verdict") != "approve":
                        raise ValidationError("successful review has no approval verdict")
                    self.github.add_review_evidence(
                        delivery["pull_request_url"], delivery["reviewer_run_id"], review_result.summary)
                    worker_head = worker_result.head_sha
                    if delivery["risk"] == "low":
                        self.state.update_delivery(work_item, state="ready_to_merge",
                                                   approved_head_sha=worker_head)
                    else:
                        self.state.update_delivery(work_item, state="awaiting_approval",
                                                   approved_head_sha=worker_head)
                        self._notify(work_item, "merge-approval",
                                     f"{delivery['pull_request_url']} passed independent review. "
                                     f"Approve immutable head `{worker_head}` with "
                                     f"`!cogito merge {worker.run_id} {worker_head}`.")
                    changed += 1
            elif state == "ready_to_merge":
                try:
                    merge_sha = self.github.merge_pull_request(
                        delivery["pull_request_url"], delivery["approved_head_sha"])
                except ValidationError:
                    continue
                self.state.update_delivery(work_item, state="merged", merge_sha=merge_sha)
                self._notify(work_item, "merged", f"Merged {delivery['pull_request_url']} at `{merge_sha}`.")
                changed += 1
        return changed

    def approve_merge(self, worker_run_id: str, head_sha: str) -> None:
        delivery = self.state.delivery_for_run(worker_run_id)
        if not delivery or delivery["worker_run_id"] != worker_run_id:
            raise ValidationError("unknown worker delivery")
        if delivery["state"] != "awaiting_approval":
            raise ValidationError("delivery is not awaiting merge approval")
        if delivery["approved_head_sha"] != head_sha:
            raise ValidationError("approval targets an obsolete pull request head")
        self.state.update_delivery(delivery["work_item_external_id"], state="ready_to_merge")
        self.state.audit("matrix", "merge.approved", worker_run_id, {"head_sha": head_sha})
