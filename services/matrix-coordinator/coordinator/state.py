"""Minimal durable state for planning, approval, and Foreman correlation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 9

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS inbound_events (
  source TEXT NOT NULL, external_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
  received_at INTEGER NOT NULL, PRIMARY KEY (source, external_id));
CREATE TABLE IF NOT EXISTS plans (
  plan_id TEXT PRIMARY KEY, state TEXT NOT NULL, repository TEXT NOT NULL,
  matrix_room_id TEXT NOT NULL, root_event_id TEXT NOT NULL,
  current_version INTEGER NOT NULL, github_issue_url TEXT);
CREATE TABLE IF NOT EXISTS plan_versions (
  plan_id TEXT NOT NULL REFERENCES plans(plan_id), version INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE, matrix_event_id TEXT NOT NULL UNIQUE,
  markdown TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY (plan_id, version));
CREATE TABLE IF NOT EXISTS plan_comments (
  matrix_event_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  sender TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS plan_intake (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, matrix_event_id TEXT NOT NULL UNIQUE,
  plan_id TEXT NOT NULL REFERENCES plans(plan_id), sender TEXT NOT NULL,
  role TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS plan_research (
  task_name TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  round INTEGER NOT NULL, position INTEGER NOT NULL, prompt TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'Pending', summary TEXT, status_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(plan_id, round, position));
CREATE TABLE IF NOT EXISTS approvals (
  plan_id TEXT PRIMARY KEY REFERENCES plans(plan_id), content_hash TEXT NOT NULL,
  matrix_event_id TEXT NOT NULL UNIQUE, approver TEXT NOT NULL, approved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workloads (
  name TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  deliverable_position INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL, status_json TEXT NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(plan_id, deliverable_position));
CREATE TABLE IF NOT EXISTS plan_deliverables (
  plan_id TEXT NOT NULL REFERENCES plans(plan_id), position INTEGER NOT NULL,
  issue_url TEXT NOT NULL UNIQUE, state TEXT NOT NULL DEFAULT 'pending',
  workload_name TEXT REFERENCES workloads(name), pr_url TEXT, head_sha TEXT,
  merge_uuid TEXT, merge_status_json TEXT, updated_at INTEGER NOT NULL,
  PRIMARY KEY(plan_id, position));
CREATE TABLE IF NOT EXISTS matrix_event_results (
  event_id TEXT PRIMARY KEY, response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matrix_outbox (
  notification_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, thread_root TEXT NOT NULL,
  body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL,
  sent_event_id TEXT);
CREATE TABLE IF NOT EXISTS external_actions (
  action_key TEXT PRIMARY KEY, kind TEXT NOT NULL, request_json TEXT NOT NULL,
  state TEXT NOT NULL, result_json TEXT, last_error TEXT);
CREATE TABLE IF NOT EXISTS audit_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
  actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


class StateStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.lock = RLock()
        self.db = connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = __import__("sqlite3").Row
        self.db.executescript(DDL)
        current = int(self.db.execute("SELECT COALESCE(max(version),0) FROM migrations").fetchone()[0])
        if current < SCHEMA_VERSION:
            # Foreman replaces this experimental executor state; no compatibility
            # bridge or historical import is useful here.
            self.db.executescript("""
                DROP TABLE IF EXISTS deliveries;
                DROP TABLE IF EXISTS runs;
                DROP TABLE IF EXISTS work_items;
                DROP TABLE IF EXISTS controls;
            """)
        if current < 7:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(workloads)")}
            if "deliverable_position" not in columns:
                self.db.executescript("""
                    DROP TABLE plan_deliverables;
                    ALTER TABLE workloads RENAME TO workloads_v6;
                    CREATE TABLE workloads (
                      name TEXT PRIMARY KEY,
                      plan_id TEXT NOT NULL REFERENCES plans(plan_id),
                      deliverable_position INTEGER NOT NULL DEFAULT 1,
                      state TEXT NOT NULL,
                      status_json TEXT NOT NULL,
                      updated_at INTEGER NOT NULL,
                      UNIQUE(plan_id, deliverable_position));
                    INSERT INTO workloads
                      (name,plan_id,deliverable_position,state,status_json,updated_at)
                    SELECT name,plan_id,1,state,status_json,updated_at FROM workloads_v6;
                    DROP TABLE workloads_v6;
                    CREATE TABLE plan_deliverables (
                      plan_id TEXT NOT NULL REFERENCES plans(plan_id),
                      position INTEGER NOT NULL,
                      issue_url TEXT NOT NULL UNIQUE,
                      state TEXT NOT NULL DEFAULT 'pending',
                      workload_name TEXT REFERENCES workloads(name),
                      pr_url TEXT,
                      head_sha TEXT,
                      merge_uuid TEXT,
                      merge_status_json TEXT,
                      updated_at INTEGER NOT NULL,
                      PRIMARY KEY(plan_id, position));
                """)
        # A process can disappear while Astra is synthesizing completed scout
        # results. Re-entering research is safe: Foreman task names and Matrix
        # notifications are deterministic, while a stuck plan is not useful.
        self.db.execute("UPDATE plans SET state='researching' WHERE state='synthesizing'")
        self.db.execute("INSERT OR IGNORE INTO migrations VALUES (?,?)",
                        (SCHEMA_VERSION, int(time.time())))

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except Exception:
                self.db.rollback()
                raise
            else:
                self.db.commit()

    def accept_event(self, source: str, external_id: str, payload_hash: str) -> bool:
        with self.transaction() as db:
            return db.execute("INSERT OR IGNORE INTO inbound_events VALUES (?,?,?,?)",
                              (source, external_id, payload_hash, int(time.time()))).rowcount == 1

    def audit(self, actor: str, action: str, subject: str, payload: dict[str, Any]) -> int:
        with self.transaction() as db:
            row = db.execute(
                "INSERT INTO audit_events(occurred_at,actor,action,subject,payload_json) "
                "VALUES (?,?,?,?,?) RETURNING sequence",
                (int(time.time()), actor, action, subject, json.dumps(payload, sort_keys=True))).fetchone()
            return int(row[0])

    def begin_action(self, key: str, kind: str, request: dict[str, Any]) -> dict[str, Any] | None:
        with self.transaction() as db:
            row = db.execute("SELECT state,result_json FROM external_actions WHERE action_key=?",
                             (key,)).fetchone()
            if row and row["state"] == "complete":
                return json.loads(row["result_json"])
            db.execute(
                "INSERT INTO external_actions VALUES (?, ?, ?, 'pending', NULL, NULL) "
                "ON CONFLICT(action_key) DO UPDATE SET last_error=NULL",
                (key, kind, json.dumps(request, sort_keys=True)))
            return None

    def complete_action(self, key: str, result: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute("UPDATE external_actions SET state='complete',result_json=?,last_error=NULL "
                       "WHERE action_key=?", (json.dumps(result, sort_keys=True), key))

    def fail_action(self, key: str, error: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE external_actions SET state='pending',last_error=? WHERE action_key=?",
                       (error[-2000:], key))

    def matrix_result(self, event_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT response_json FROM matrix_event_results WHERE event_id=?",
                                  (event_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_matrix_result(self, event_id: str, result: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO matrix_event_results VALUES (?,?)",
                       (event_id, json.dumps(result, sort_keys=True)))

    def plan_for_thread(self, room_id: str, root_event_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM plans WHERE matrix_room_id=? AND root_event_id=?",
                                   (room_id, root_event_id)).fetchone()

    def planning_typing_rooms(self) -> list[str]:
        """Rooms where asynchronous planning scouts or synthesis are active."""
        with self.lock:
            return [row[0] for row in self.db.execute(
                "SELECT DISTINCT matrix_room_id FROM plans "
                "WHERE state IN ('researching','synthesizing') ORDER BY matrix_room_id"
            ).fetchall()]

    def plan(self, plan_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()

    def begin_intake(self, plan_id: str, room_id: str, root_event_id: str,
                     repository: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO plans(plan_id,state,repository,matrix_room_id,"
                "root_event_id,current_version) VALUES (?, 'intake', ?, ?, ?, 0)",
                (plan_id, repository, room_id, root_event_id),
            )

    def add_intake_message(self, event_id: str, plan_id: str, sender: str,
                           role: str, kind: str, body: str) -> bool:
        with self.transaction() as db:
            return db.execute(
                "INSERT OR IGNORE INTO plan_intake(matrix_event_id,plan_id,sender,role,kind,body,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (event_id, plan_id, sender, role, kind, body, int(time.time())),
            ).rowcount == 1

    def intake_messages(self, plan_id: str) -> list[dict[str, str]]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT role,kind,body FROM plan_intake WHERE plan_id=? ORDER BY sequence",
                (plan_id,),
            ).fetchall()]

    def intake_rounds(self, plan_id: str) -> int:
        with self.lock:
            return int(self.db.execute(
                "SELECT count(*) FROM plan_intake WHERE plan_id=? AND role='assistant' "
                "AND kind IN ('clarify','pushback')", (plan_id,),
            ).fetchone()[0])

    def set_plan_state(self, plan_id: str, state: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE plans SET state=? WHERE plan_id=?", (state, plan_id))

    def register_research(self, plan_id: str, prompts: list[str]) -> tuple[int, list[str]]:
        if not prompts or len(prompts) > 4:
            raise ValueError("research delegation requires one to four tasks")
        with self.transaction() as db:
            round_number = int(db.execute(
                "SELECT COALESCE(max(round),0)+1 FROM plan_research WHERE plan_id=?",
                (plan_id,),
            ).fetchone()[0])
            now = int(time.time())
            names = []
            for position, prompt in enumerate(prompts, 1):
                task_name = f"{plan_id}-research-r{round_number}-{position}"[:63].rstrip("-")
                db.execute(
                    "INSERT INTO plan_research(task_name,plan_id,round,position,prompt,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (task_name, plan_id, round_number, position, prompt, now, now),
                )
                names.append(task_name)
            db.execute("UPDATE plans SET state='researching' WHERE plan_id=?", (plan_id,))
        return round_number, names

    def active_research(self):
        with self.lock:
            return self.db.execute(
                "SELECT r.*,p.repository,p.matrix_room_id,p.root_event_id FROM plan_research r "
                "JOIN plans p ON p.plan_id=r.plan_id WHERE p.state='researching' "
                "AND r.state NOT IN ('Succeeded','Failed') ORDER BY r.plan_id,r.round,r.position"
            ).fetchall()

    def update_research(self, task_name: str, status: dict[str, Any]) -> bool:
        phase = status.get("phase", "Pending")
        result = status.get("result") or {}
        summary = result.get("summary") if isinstance(result, dict) else None
        if not summary and phase == "Failed":
            summary = status.get("failureReason") or "Foreman research task failed"
        if summary:
            summary = str(summary).strip()[:4000]
        encoded = json.dumps(status, sort_keys=True)
        with self.transaction() as db:
            row = db.execute(
                "SELECT state,status_json FROM plan_research WHERE task_name=?", (task_name,)
            ).fetchone()
            if not row:
                return False
            changed = row["state"] != phase or row["status_json"] != encoded
            db.execute(
                "UPDATE plan_research SET state=?,summary=?,status_json=?,updated_at=? "
                "WHERE task_name=?", (phase, summary, encoded, int(time.time()), task_name),
            )
            return changed

    def research_ready(self):
        with self.lock:
            return self.db.execute(
                "SELECT r.plan_id,r.round FROM plan_research r JOIN plans p ON p.plan_id=r.plan_id "
                "WHERE p.state='researching' AND r.round=(SELECT max(r2.round) "
                "FROM plan_research r2 WHERE r2.plan_id=r.plan_id) GROUP BY r.plan_id,r.round "
                "HAVING count(*)=sum(CASE WHEN r.state IN "
                "('Succeeded','Failed') THEN 1 ELSE 0 END) ORDER BY r.plan_id"
            ).fetchall()

    def research_briefing(self, plan_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT round,position,prompt,state,COALESCE(summary,'No summary returned') summary "
                "FROM plan_research WHERE plan_id=? ORDER BY round,position", (plan_id,),
            ).fetchall()]

    def research_rounds(self, plan_id: str) -> int:
        with self.lock:
            return int(self.db.execute(
                "SELECT COALESCE(max(round),0) FROM plan_research WHERE plan_id=?", (plan_id,),
            ).fetchone()[0])

    def research_progress(self, plan_id: str) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute(
                "SELECT state,count(*) count FROM plan_research WHERE plan_id=? GROUP BY state",
                (plan_id,),
            ).fetchall()
        counts = {row["state"]: row["count"] for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    def current_plan_version(self, plan_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT v.* FROM plan_versions v JOIN plans p ON p.plan_id=v.plan_id "
                "AND p.current_version=v.version WHERE p.plan_id=?", (plan_id,)).fetchone()

    def add_plan_comment(self, event_id: str, plan_id: str, sender: str, body: str) -> bool:
        with self.transaction() as db:
            return db.execute("INSERT OR IGNORE INTO plan_comments VALUES (?,?,?,?,?)",
                              (event_id, plan_id, sender, body, int(time.time()))).rowcount == 1

    def plan_comments(self, plan_id: str) -> list[str]:
        with self.lock:
            return [row[0] for row in self.db.execute(
                "SELECT body FROM plan_comments WHERE plan_id=? ORDER BY created_at,matrix_event_id",
                (plan_id,)).fetchall()]

    def register_deliverables(self, plan_id: str, issue_urls: list[str]) -> None:
        with self.transaction() as db:
            existing = db.execute(
                "SELECT issue_url FROM plan_deliverables WHERE plan_id=? ORDER BY position",
                (plan_id,),
            ).fetchall()
            if existing:
                if [row[0] for row in existing] != issue_urls:
                    raise ValueError("approved plan deliverables changed after dispatch")
                return
            now = int(time.time())
            db.executemany(
                "INSERT INTO plan_deliverables(plan_id,position,issue_url,updated_at) "
                "VALUES (?,?,?,?)",
                [(plan_id, position, url, now)
                 for position, url in enumerate(issue_urls, 1)],
            )

    def next_deliverable(self, plan_id: str):
        """Return the first pending item only when every predecessor merged."""
        with self.lock:
            return self.db.execute(
                "SELECT d.* FROM plan_deliverables d "
                "WHERE d.plan_id=? AND d.state='pending' "
                "AND NOT EXISTS (SELECT 1 FROM plan_deliverables prior "
                "WHERE prior.plan_id=d.plan_id AND prior.position<d.position "
                "AND prior.state!='merged') ORDER BY d.position LIMIT 1",
                (plan_id,),
            ).fetchone()

    def plans_ready_to_dispatch(self):
        with self.lock:
            return self.db.execute(
                "SELECT DISTINCT p.plan_id FROM plans p JOIN plan_deliverables d "
                "ON d.plan_id=p.plan_id WHERE p.state IN ('decomposed','running') "
                "AND d.state='pending' AND NOT EXISTS (SELECT 1 FROM plan_deliverables prior "
                "WHERE prior.plan_id=d.plan_id AND prior.position<d.position "
                "AND prior.state!='merged') AND NOT EXISTS (SELECT 1 FROM plan_deliverables active "
                "WHERE active.plan_id=d.plan_id AND active.state IN ('running','merge_pending')) "
                "ORDER BY p.plan_id"
            ).fetchall()

    def register_workload(self, name: str, plan_id: str, status: dict[str, Any],
                          deliverable_position: int = 1) -> None:
        encoded = json.dumps(status, sort_keys=True)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO workloads(name,plan_id,deliverable_position,state,status_json,updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET state=excluded.state,"
                "status_json=excluded.status_json,updated_at=excluded.updated_at",
                (name, plan_id, deliverable_position, status.get("phase", "Pending"),
                 encoded, int(time.time())))
            db.execute(
                "UPDATE plan_deliverables SET state='running',workload_name=?,updated_at=? "
                "WHERE plan_id=? AND position=?",
                (name, int(time.time()), plan_id, deliverable_position),
            )
            db.execute("UPDATE plans SET state='running' WHERE plan_id=?", (plan_id,))

    def workload_for_plan(self, plan_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM workloads WHERE plan_id=? ORDER BY deliverable_position DESC LIMIT 1",
                (plan_id,),
            ).fetchone()

    def active_workloads(self):
        with self.lock:
            return self.db.execute(
                "SELECT w.*,p.matrix_room_id,p.root_event_id FROM workloads w "
                "JOIN plans p ON p.plan_id=w.plan_id "
                "JOIN plan_deliverables d ON d.plan_id=w.plan_id "
                "AND d.position=w.deliverable_position "
                "WHERE d.state='running' ORDER BY w.name").fetchall()

    def update_workload(self, name: str, status: dict[str, Any]) -> bool:
        encoded = json.dumps(status, sort_keys=True)
        with self.transaction() as db:
            row = db.execute("SELECT state,status_json,plan_id FROM workloads WHERE name=?",
                             (name,)).fetchone()
            if not row:
                return False
            state = status.get("phase", "Pending")
            changed = row["state"] != state or row["status_json"] != encoded
            db.execute("UPDATE workloads SET state=?,status_json=?,updated_at=? WHERE name=?",
                       (state, encoded, int(time.time()), name))
            return changed

    def begin_merge(self, plan_id: str, position: int, pr_url: str, head_sha: str,
                    merge_uuid: str | None, status: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE plan_deliverables SET state=?,pr_url=?,head_sha=?,merge_uuid=?,"
                "merge_status_json=?,updated_at=? WHERE plan_id=? AND position=?",
                ("merge_pending", pr_url, head_sha, merge_uuid, json.dumps(status, sort_keys=True),
                 int(time.time()), plan_id, position),
            )

    def pending_merges(self):
        with self.lock:
            return self.db.execute(
                "SELECT d.*,p.matrix_room_id,p.root_event_id FROM plan_deliverables d "
                "JOIN plans p ON p.plan_id=d.plan_id WHERE d.state='merge_pending' "
                "ORDER BY d.plan_id,d.position"
            ).fetchall()

    def finish_merge(self, plan_id: str, position: int, status: dict[str, Any]) -> str:
        merged = status.get("status") == "merged"
        new_state = "merged" if merged else "failed"
        with self.transaction() as db:
            db.execute(
                "UPDATE plan_deliverables SET state=?,merge_status_json=?,updated_at=? "
                "WHERE plan_id=? AND position=?",
                (new_state, json.dumps(status, sort_keys=True), int(time.time()),
                 plan_id, position),
            )
            if not merged:
                db.execute("UPDATE plans SET state='failed' WHERE plan_id=?", (plan_id,))
            elif not db.execute(
                    "SELECT 1 FROM plan_deliverables WHERE plan_id=? AND state!='merged' LIMIT 1",
                    (plan_id,)).fetchone():
                db.execute("UPDATE plans SET state='completed' WHERE plan_id=?", (plan_id,))
                return "completed"
        return new_state

    def fail_deliverable(self, plan_id: str, position: int, status: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE plan_deliverables SET state='failed',merge_status_json=?,updated_at=? "
                "WHERE plan_id=? AND position=?",
                (json.dumps(status, sort_keys=True), int(time.time()), plan_id, position),
            )
            db.execute("UPDATE plans SET state='failed' WHERE plan_id=?", (plan_id,))

    def plan_progress(self, plan_id: str) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute(
                "SELECT state,count(*) count FROM plan_deliverables WHERE plan_id=? GROUP BY state",
                (plan_id,),
            ).fetchall()
        counts = {row["state"]: row["count"] for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    def enqueue_matrix(self, notification_id: str, room_id: str, thread_root: str, body: str) -> bool:
        with self.transaction() as db:
            return db.execute(
                "INSERT OR IGNORE INTO matrix_outbox(notification_id,room_id,thread_root,body,created_at) "
                "VALUES (?,?,?,?,?)", (notification_id, room_id, thread_root, body,
                                        int(time.time()))).rowcount == 1

    def pending_matrix(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT notification_id,room_id,thread_root,body FROM matrix_outbox "
                "WHERE state='pending' ORDER BY created_at,notification_id LIMIT ?", (limit,)).fetchall()]

    def complete_matrix(self, notification_id: str, event_id: str) -> bool:
        with self.transaction() as db:
            return db.execute("UPDATE matrix_outbox SET state='sent',sent_event_id=? "
                              "WHERE notification_id=? AND state='pending'",
                              (event_id, notification_id)).rowcount == 1

    def prometheus_metrics(self) -> str:
        lines = ["# HELP cogito_coordinator_up Whether the coordinator process is serving.",
                 "# TYPE cogito_coordinator_up gauge", "cogito_coordinator_up 1",
                 "# HELP cogito_coordinator_objects Durable objects by kind and state.",
                 "# TYPE cogito_coordinator_objects gauge"]
        with self.lock:
            for kind, table in {"plan": "plans", "workload": "workloads",
                                "matrix_outbox": "matrix_outbox",
                                "external_action": "external_actions"}.items():
                for row in self.db.execute(
                        f"SELECT state,count(*) count FROM {table} GROUP BY state ORDER BY state"):
                    lines.append(f'cogito_coordinator_objects{{kind="{kind}",state="{row["state"]}"}} {row["count"]}')
            failed = self.db.execute(
                "SELECT count(*) FROM external_actions WHERE last_error IS NOT NULL").fetchone()[0]
            audits = self.db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
        lines.extend(["# HELP cogito_coordinator_external_action_errors Durable actions awaiting retry.",
                      "# TYPE cogito_coordinator_external_action_errors gauge",
                      f"cogito_coordinator_external_action_errors {failed}",
                      "# HELP cogito_coordinator_audit_events_total Append-only audit records.",
                      "# TYPE cogito_coordinator_audit_events_total counter",
                      f"cogito_coordinator_audit_events_total {audits}"])
        return "\n".join(lines) + "\n"

    def close(self) -> None:
        self.db.close()
