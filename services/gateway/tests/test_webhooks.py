from hashlib import sha256
from hmac import new
import json
import tempfile
import unittest

from coordinator.core import Coordinator
from coordinator.github import plan_issue_body
from coordinator.models import PlanVersion
from coordinator.state import StateStore
from coordinator.webhooks import GitHubWebhook, verify_internal


class FakeIssues:
    def __init__(self):
        self.parent = "https://github.com/t/c/issues/1"
        self.labels = []

    def publish_plan(self, plan):
        return self.parent

    def create_deliverables(self, plan, parent_url):
        return ["https://github.com/t/c/issues/2"]

    def apply_label(self, issue_url, label):
        self.labels.append((issue_url, label))

    def get_issue(self, issue_url):
        return {"html_url": issue_url, "body": self.body}


class WebhookTests(unittest.TestCase):
    @staticmethod
    def headers(delivery, event, body):
        return {
            "X-GitHub-Delivery": delivery, "X-GitHub-Event": event,
            "X-Hub-Signature-256": "sha256=" + new(b"secret", body, sha256).hexdigest(),
        }
    def test_signature(self):
        signature = "sha256=dc46983557fea127b43af721467eb9b3fde2338fe3e14f51952aa8478c13d355"
        self.assertTrue(verify_internal(b"secret", b"body", signature))
        self.assertFalse(verify_internal(b"secret", b"tampered", signature))

    def test_label_approval_versions_body_freezes_hash_and_deduplicates(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            plan = PlanVersion(
                "plan-1", 1, "# Plan\n\n## Deliverables\n- [ ] First\n",
                "!room:example", "$root", "https://github.com/t/c.git",
            )
            core.record_plan(plan)
            edited = PlanVersion(
                "plan-1", 2, "# Plan revised\n\n## Deliverables\n- [ ] First\n",
                "!room:example", "$root", "https://github.com/t/c.git",
            )
            payload = {
                "action": "labeled",
                "label": {"name": "workflow/approved"},
                "sender": {"login": "tim"},
                "issue": {
                    "html_url": issues.parent,
                    "body": plan_issue_body(edited),
                    "updated_at": "2026-09-13T20:00:00Z",
                },
            }
            issues.body = payload["issue"]["body"]
            body = json.dumps(payload).encode()
            headers = {
                "X-GitHub-Delivery": "delivery-1",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=" + new(b"secret", body, sha256).hexdigest(),
            }
            webhook = GitHubWebhook(b"secret", state, core, issues)
            status, result = webhook.handle(headers, body)
            self.assertEqual(status, 202)
            self.assertEqual(len(result["children"]), 1)
            self.assertEqual(state.plan("plan-1")["state"], "decomposed")
            self.assertEqual(state.current_plan_version("plan-1")["content_hash"], edited.hash)
            self.assertEqual(webhook.handle(headers, body)[1]["duplicate"], True)
            state.close()

    def test_owner_comment_is_bounded_and_coalesced_for_luna(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            plan = PlanVersion(
                "plan-1", 1, "# Plan\n", "!room:example", "$root",
                "https://github.com/t/c.git")
            core.record_plan(plan)
            payload = {
                "action": "created", "sender": {"login": "tim"},
                "comment": {"body": "Please revise the rollback section."},
                "issue": {"html_url": issues.parent, "body": plan_issue_body(plan)},
            }
            body = json.dumps(payload).encode()
            status, result = GitHubWebhook(b"secret", state, core, issues).handle(
                self.headers("comment-1", "issue_comment", body), body)
            self.assertEqual(status, 202)
            self.assertTrue(result["queued"])
            self.assertEqual(state.plan_comments("plan-1"),
                             ["Please revise the rollback section."])
            batch = state.next_luna_batch(now=2**31)
            self.assertEqual(batch["events"][0]["event_type"],
                             "github.issue_comment.created")
            state.close()

    def test_repository_event_wakes_each_plan_under_execution(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            for index in (1, 2):
                core.record_plan(PlanVersion(
                    f"plan-{index}", 1, f"# Plan {index}\n", "!room:example",
                    f"$root-{index}", "https://github.com/t/c.git"))
                state.set_plan_state(f"plan-{index}", "running")
            payload = {
                "ref": "refs/heads/main", "after": "a" * 40,
                "sender": {"login": "tim"},
                "repository": {"html_url": "https://github.com/t/c"},
            }
            body = json.dumps(payload).encode()
            status, result = GitHubWebhook(b"secret", state, core, issues).handle(
                self.headers("push-1", "push", body), body)
            self.assertEqual(status, 202)
            self.assertEqual(result["plan_ids"], ["plan-1", "plan-2"])
            count = state.db.execute(
                "SELECT count(*) FROM coordinator_events WHERE event_type='github.push.event'"
            ).fetchone()[0]
            self.assertEqual(count, 2)
            self.assertEqual(state.plan_comments("plan-1"), [])
            state.close()

    def test_repository_event_leaves_a_plan_still_being_drafted_alone(self):
        """Unattributed repo traffic must not derail a plan before approval.

        A plan in research has no frozen version, so handing it to Luna
        crashed the reconciler and forced the plan into needs_input while
        Astra was still waiting on its scouts.
        """
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            state.begin_intake(
                "plan-drafting", "!room:example", "$root", "https://github.com/t/c.git")
            state.set_plan_state("plan-drafting", "researching")
            core.record_plan(PlanVersion(
                "plan-running", 1, "# Running\n", "!room:example",
                "$root-r", "https://github.com/t/c.git"))
            state.set_plan_state("plan-running", "running")
            payload = {
                "ref": "refs/heads/main", "after": "b" * 40,
                "sender": {"login": "tim"},
                "repository": {"html_url": "https://github.com/t/c"},
            }
            body = json.dumps(payload).encode()
            status, result = GitHubWebhook(b"secret", state, core, issues).handle(
                self.headers("push-2", "push", body), body)
            self.assertEqual(status, 202)
            self.assertEqual(result["plan_ids"], ["plan-running"])
            self.assertEqual(state.plan("plan-drafting")["state"], "researching")
            state.close()

    def test_gateway_comment_wakes_luna_without_feedback_loop(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            plan = PlanVersion(
                "plan-1", 1, "# Plan\n", "!room:example", "$root",
                "https://github.com/t/c.git")
            core.record_plan(plan)
            payload = {
                "action": "created", "sender": {"login": "cogito-app[bot]"},
                "comment": {"body": "● Luna status\n\n<!-- cogito-action: batch:1 -->"},
                "issue": {"html_url": issues.parent, "body": plan_issue_body(plan)},
            }
            body = json.dumps(payload).encode()
            result = GitHubWebhook(b"secret", state, core, issues).handle(
                self.headers("own-comment", "issue_comment", body), body)[1]
            self.assertTrue(result["queued"])
            self.assertEqual(state.plan_comments("plan-1"), [])
            batch = state.next_luna_batch(now=2**31)
            self.assertTrue(batch["events"][0]["payload"]["gateway_action"])
            self.assertEqual(batch["events"][0]["payload"]["comment"], "")
            state.close()

    def test_approve_comment_applies_label(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            plan = PlanVersion(
                "plan-1", 1, "# Plan\n\n## Deliverables\n- [ ] First\n",
                "!room:example", "$root", "https://github.com/t/c.git",
            )
            core.record_plan(plan)
            payload = {
                "action": "created", "sender": {"login": "tim"},
                "comment": {"body": "/approve", "updated_at": "2026-09-13T20:00:00Z"},
                "issue": {"html_url": issues.parent, "body": plan_issue_body(plan)},
            }
            issues.body = payload["issue"]["body"]
            body = json.dumps(payload).encode()
            headers = {
                "X-GitHub-Delivery": "delivery-2",
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": "sha256=" + new(b"secret", body, sha256).hexdigest(),
            }
            status, _ = GitHubWebhook(b"secret", state, core, issues).handle(headers, body)
            self.assertEqual(status, 202)
            self.assertEqual(issues.labels, [(issues.parent, "workflow/approved")])
            labeled = {
                "action": "labeled", "label": {"name": "workflow/approved"},
                "sender": {"login": "tim"},
                "issue": {"html_url": issues.parent, "body": plan_issue_body(plan),
                          "updated_at": "2026-09-13T20:00:01Z"},
            }
            labeled_body = json.dumps(labeled).encode()
            status, _ = GitHubWebhook(b"secret", state, core, issues).handle(
                self.headers("delivery-3", "issues", labeled_body), labeled_body)
            self.assertEqual(status, 202)
            self.assertEqual(state.plan("plan-1")["state"], "decomposed")
            self.assertEqual(state.db.execute(
                "SELECT count(*) FROM coordinator_events WHERE plan_id='plan-1'"
            ).fetchone()[0], 1)
            state.close()

    def test_failed_delivery_can_be_retried(self):
        with tempfile.NamedTemporaryFile() as tmp:
            state = StateStore(tmp.name)
            issues = FakeIssues()
            core = Coordinator(state, issues, set(), {"tim"})
            plan = PlanVersion(
                "plan-1", 1, "# Plan\n\n## Deliverables\n- [ ] First\n",
                "!room:example", "$root", "https://github.com/t/c.git",
            )
            core.record_plan(plan)
            payload = {
                "action": "labeled", "label": {"name": "workflow/approved"},
                "sender": {"login": "tim"},
                "issue": {"html_url": issues.parent, "body": plan_issue_body(plan),
                          "updated_at": "2026-09-13T20:00:00Z"},
            }
            issues.body = payload["issue"]["body"]
            body = json.dumps(payload).encode()
            headers = self.headers("retryable", "issues", body)
            original = issues.get_issue
            issues.get_issue = lambda _: (_ for _ in ()).throw(RuntimeError("transient"))
            webhook = GitHubWebhook(b"secret", state, core, issues)
            with self.assertRaisesRegex(RuntimeError, "transient"):
                webhook.handle(headers, body)
            issues.get_issue = original
            self.assertEqual(webhook.handle(headers, body)[0], 202)
            state.close()


if __name__ == "__main__":
    unittest.main()
