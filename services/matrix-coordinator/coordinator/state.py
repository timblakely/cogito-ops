"""Minimal durable state for planning, approval, and Foreman correlation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 6

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
CREATE TABLE IF NOT EXISTS approvals (
  plan_id TEXT PRIMARY KEY REFERENCES plans(plan_id), content_hash TEXT NOT NULL,
  matrix_event_id TEXT NOT NULL UNIQUE, approver TEXT NOT NULL, approved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workloads (
  name TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES plans(plan_id),
  state TEXT NOT NULL, status_json TEXT NOT NULL, updated_at INTEGER NOT NULL);
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

    def register_workload(self, name: str, plan_id: str, status: dict[str, Any]) -> None:
        encoded = json.dumps(status, sort_keys=True)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO workloads(name,plan_id,state,status_json,updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET state=excluded.state,"
                "status_json=excluded.status_json,updated_at=excluded.updated_at",
                (name, plan_id, status.get("phase", "Pending"), encoded, int(time.time())))
            db.execute("UPDATE plans SET state='running' WHERE plan_id=?", (plan_id,))

    def workload_for_plan(self, plan_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM workloads WHERE plan_id=?", (plan_id,)).fetchone()

    def active_workloads(self):
        with self.lock:
            return self.db.execute(
                "SELECT w.*,p.matrix_room_id,p.root_event_id FROM workloads w "
                "JOIN plans p ON p.plan_id=w.plan_id "
                "WHERE w.state NOT IN ('Completed','Failed') ORDER BY w.name").fetchall()

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
            if state in {"Completed", "Failed"}:
                db.execute("UPDATE plans SET state=? WHERE plan_id=?",
                           (state.lower(), row["plan_id"]))
            return changed

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
