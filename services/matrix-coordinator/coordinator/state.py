"""SQLite state store with replay protection and append-only audit."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 1

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
        self.db = connect(self.path, isolation_level=None)
        self.db.row_factory = __import__("sqlite3").Row
        self.db.executescript(DDL)
        self.db.execute(
            "INSERT OR IGNORE INTO migrations(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, int(time.time())),
        )

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
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

    def close(self) -> None:
        self.db.close()
