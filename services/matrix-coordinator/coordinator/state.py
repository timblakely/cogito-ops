"""SQLite state store with replay protection and append-only audit."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 2

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS migrations (
  version INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS inbound_events (
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY (source, external_id)
);
CREATE TABLE IF NOT EXISTS matrix_event_results (
  event_id TEXT PRIMARY KEY,
  response_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_comments (
  matrix_event_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  sender TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
  plan_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  repository TEXT NOT NULL,
  matrix_room_id TEXT NOT NULL,
  root_event_id TEXT NOT NULL,
  current_version INTEGER NOT NULL,
  github_issue_url TEXT
);
CREATE TABLE IF NOT EXISTS plan_versions (
  plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  version INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  matrix_event_id TEXT NOT NULL UNIQUE,
  markdown TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (plan_id, version)
);
CREATE TABLE IF NOT EXISTS approvals (
  plan_id TEXT PRIMARY KEY REFERENCES plans(plan_id),
  content_hash TEXT NOT NULL,
  matrix_event_id TEXT NOT NULL UNIQUE,
  approver TEXT NOT NULL,
  approved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_items (
  external_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  parent_external_id TEXT,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  work_item_external_id TEXT NOT NULL,
  argo_name TEXT UNIQUE,
  state TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS external_actions (
  action_key TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  request_json TEXT NOT NULL,
  state TEXT NOT NULL,
  result_json TEXT,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  subject TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
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
        self.db.execute(
            "INSERT OR IGNORE INTO migrations(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, int(time.time())),
        )

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
            result = db.execute(
                "INSERT OR IGNORE INTO inbound_events VALUES (?, ?, ?, ?)",
                (source, external_id, payload_hash, int(time.time())),
            )
            return result.rowcount == 1

    def audit(self, actor: str, action: str, subject: str, payload: dict[str, Any]) -> int:
        with self.transaction() as db:
            row = db.execute(
                "INSERT INTO audit_events(occurred_at, actor, action, subject, payload_json) "
                "VALUES (?, ?, ?, ?, ?) RETURNING sequence",
                (int(time.time()), actor, action, subject, json.dumps(payload, sort_keys=True)),
            ).fetchone()
            return int(row[0])

    def begin_action(self, key: str, kind: str, request: dict[str, Any]) -> dict[str, Any] | None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT state,result_json FROM external_actions WHERE action_key=?", (key,)
            ).fetchone()
            if row and row["state"] == "complete":
                return json.loads(row["result_json"])
            db.execute(
                "INSERT INTO external_actions VALUES (?, ?, ?, 'pending', NULL, NULL) "
                "ON CONFLICT(action_key) DO UPDATE SET last_error=NULL",
                (key, kind, json.dumps(request, sort_keys=True)),
            )
            return None

    def complete_action(self, key: str, result: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE external_actions SET state='complete',result_json=?,last_error=NULL WHERE action_key=?",
                (json.dumps(result, sort_keys=True), key),
            )

    def fail_action(self, key: str, error: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE external_actions SET state='pending',last_error=? WHERE action_key=?",
                (error[-2000:], key),
            )

    def register_run(self, run_id: str, work_item: str, request: dict[str, Any]) -> bool:
        """Persist a run before its external submission; identical retries are harmless."""
        encoded = json.dumps(request, sort_keys=True)
        with self.transaction() as db:
            row = db.execute(
                "SELECT request_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row:
                if row["request_json"] != encoded:
                    raise ValueError("run_id already exists with another request")
                return False
            db.execute(
                "INSERT INTO runs(run_id,work_item_external_id,state,request_json) "
                "VALUES (?,?,'submitting',?)", (run_id, work_item, encoded),
            )
            return True

    def attach_workflow(self, run_id: str, name: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE runs SET argo_name=?,state='submitted' WHERE run_id=?",
                (name, run_id),
            )

    def run(self, run_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()

    def active_runs(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM runs WHERE state IN ('submitting','submitted','running','cancelling') "
                "ORDER BY run_id"
            ).fetchall()

    def update_run(self, run_id: str, state: str, result: dict[str, Any] | None = None) -> None:
        encoded = None if result is None else json.dumps(result, sort_keys=True)
        with self.transaction() as db:
            db.execute(
                "UPDATE runs SET state=?,result_json=COALESCE(?,result_json) WHERE run_id=?",
                (state, encoded, run_id),
            )

    def matrix_result(self, event_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute(
                "SELECT response_json FROM matrix_event_results WHERE event_id=?", (event_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_matrix_result(self, event_id: str, result: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO matrix_event_results VALUES (?,?)",
                (event_id, json.dumps(result, sort_keys=True)),
            )

    def plan_for_thread(self, room_id: str, root_event_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM plans WHERE matrix_room_id=? AND root_event_id=?",
                (room_id, root_event_id),
            ).fetchone()

    def current_plan_version(self, plan_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT v.* FROM plan_versions v JOIN plans p ON p.plan_id=v.plan_id "
                "AND p.current_version=v.version WHERE p.plan_id=?", (plan_id,)
            ).fetchone()

    def add_plan_comment(self, event_id: str, plan_id: str, sender: str, body: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO plan_comments VALUES (?,?,?,?,?)",
                (event_id, plan_id, sender, body, int(time.time())),
            )
            return result.rowcount == 1

    def plan_comments(self, plan_id: str) -> list[str]:
        with self.lock:
            rows = self.db.execute(
                "SELECT body FROM plan_comments WHERE plan_id=? ORDER BY created_at,matrix_event_id",
                (plan_id,),
            ).fetchall()
            return [row[0] for row in rows]

    def close(self) -> None:
        self.db.close()
