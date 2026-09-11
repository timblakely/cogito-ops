"""SQLite state store with replay protection and append-only audit."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 5

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
CREATE TABLE IF NOT EXISTS matrix_outbox (
  notification_id TEXT PRIMARY KEY,
  room_id TEXT NOT NULL,
  thread_root TEXT NOT NULL,
  body TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL,
  sent_event_id TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  work_item_external_id TEXT NOT NULL,
  argo_name TEXT UNIQUE,
  state TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
  work_item_external_id TEXT PRIMARY KEY,
  worker_run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
  worker_harness TEXT NOT NULL,
  state TEXT NOT NULL,
  pull_request_url TEXT,
  reviewer_run_id TEXT UNIQUE,
  review_harness TEXT,
  risk TEXT,
  approved_head_sha TEXT,
  merge_sha TEXT,
  repair_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS controls (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
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
        self._backfill_work_items()

    def _backfill_work_items(self) -> None:
        """Recover issue hierarchy created before work-item persistence existed."""
        rows = self.db.execute(
            "SELECT request_json,result_json FROM external_actions "
            "WHERE kind='github.create-plan' AND state='complete' AND result_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
            plan_id = request.get("plan_id")
            if plan_id and result.get("parent"):
                self.register_work_items(plan_id, result["parent"], result.get("children", []))

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

    def queued_runs(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM runs WHERE state='queued' ORDER BY run_id"
            ).fetchall()

    def active_run_count(self) -> int:
        with self.lock:
            return int(self.db.execute(
                "SELECT count(*) FROM runs WHERE state IN ('submitting','submitted','running','cancelling')"
            ).fetchone()[0])

    def total_usage_tokens(self) -> int:
        total = 0
        with self.lock:
            rows = self.db.execute("SELECT result_json FROM runs WHERE result_json IS NOT NULL").fetchall()
        for row in rows:
            usage = json.loads(row[0]).get("usage", {})
            total += sum(usage.get(key, 0) for key in ("input_tokens", "output_tokens")
                         if isinstance(usage.get(key, 0), int))
        return total

    def update_run(self, run_id: str, state: str, result: dict[str, Any] | None = None) -> None:
        encoded = None if result is None else json.dumps(result, sort_keys=True)
        with self.transaction() as db:
            db.execute(
                "UPDATE runs SET state=?,result_json=COALESCE(?,result_json) WHERE run_id=?",
                (state, encoded, run_id),
            )

    def register_delivery(self, work_item: str, run_id: str, harness: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO deliveries(work_item_external_id,worker_run_id,worker_harness,state) "
                "VALUES (?,?,?,'worker_running')", (work_item, run_id, harness),
            )
            return result.rowcount == 1

    def deliveries(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM deliveries WHERE state NOT IN ('merged','cancelled','failed') "
                "ORDER BY work_item_external_id"
            ).fetchall()

    def delivery_for_run(self, run_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM deliveries WHERE worker_run_id=? OR reviewer_run_id=?",
                (run_id, run_id),
            ).fetchone()

    def update_delivery(self, work_item: str, **values: Any) -> None:
        allowed = {"state", "worker_run_id", "worker_harness", "pull_request_url",
                   "reviewer_run_id", "review_harness",
                   "risk", "approved_head_sha", "merge_sha", "repair_attempts"}
        if not values or set(values) - allowed:
            raise ValueError("invalid delivery update")
        assignments = ",".join(f"{key}=?" for key in values)
        with self.transaction() as db:
            db.execute(f"UPDATE deliveries SET {assignments} WHERE work_item_external_id=?",
                       (*values.values(), work_item))

    def set_control(self, key: str, value: str) -> None:
        if key not in {"emergency_stop"}:
            raise ValueError("unknown control")
        with self.transaction() as db:
            db.execute("INSERT INTO controls VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))

    def control(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.db.execute("SELECT value FROM controls WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def register_work_items(self, plan_id: str, parent: str, children: list[str]) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO work_items VALUES (?,?,NULL,'open',?) "
                "ON CONFLICT(external_id) DO NOTHING",
                (parent, plan_id, json.dumps({"kind": "plan"}, sort_keys=True)),
            )
            for child in children:
                db.execute(
                    "INSERT INTO work_items VALUES (?,?,?,'open',?) "
                    "ON CONFLICT(external_id) DO NOTHING",
                    (child, plan_id, parent, json.dumps({"kind": "deliverable"}, sort_keys=True)),
                )

    def update_work_item(self, external_id: str, state: str, payload: dict[str, Any]) -> bool:
        with self.transaction() as db:
            row = db.execute(
                "SELECT state,payload_json FROM work_items WHERE external_id=?", (external_id,)
            ).fetchone()
            if not row:
                return False
            encoded = json.dumps(payload, sort_keys=True)
            changed = row["state"] != state or row["payload_json"] != encoded
            db.execute(
                "UPDATE work_items SET state=?,payload_json=? WHERE external_id=?",
                (state, encoded, external_id),
            )
            return changed

    def work_item_context(self, external_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT w.*,p.matrix_room_id,p.root_event_id FROM work_items w "
                "JOIN plans p ON p.plan_id=w.plan_id WHERE w.external_id=?", (external_id,)
            ).fetchone()

    def work_items(self):
        with self.lock:
            return self.db.execute(
                "SELECT w.*,p.repository,p.matrix_room_id,p.root_event_id FROM work_items w "
                "JOIN plans p ON p.plan_id=w.plan_id ORDER BY w.external_id"
            ).fetchall()

    def enqueue_matrix(self, notification_id: str, room_id: str, thread_root: str, body: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO matrix_outbox(notification_id,room_id,thread_root,body,created_at) "
                "VALUES (?,?,?,?,?)", (notification_id, room_id, thread_root, body, int(time.time())),
            )
            return result.rowcount == 1

    def pending_matrix(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT notification_id,room_id,thread_root,body FROM matrix_outbox "
                "WHERE state='pending' ORDER BY created_at,notification_id LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def complete_matrix(self, notification_id: str, event_id: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                "UPDATE matrix_outbox SET state='sent',sent_event_id=? "
                "WHERE notification_id=? AND state='pending'", (event_id, notification_id),
            )
            return result.rowcount == 1

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
