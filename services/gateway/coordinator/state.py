"""Minimal durable state for planning, approval, and Foreman correlation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, connect
from threading import RLock
from typing import Any, Iterator
import json
import time

SCHEMA_VERSION = 12

# Matrix sender identities. The MXID encodes the role so the backing agent can
# change without renaming the account Tim already trusts in his client.
SENDERS = ("gateway", "planner", "coordinator")

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
  attempt INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(plan_id, position));
CREATE TABLE IF NOT EXISTS matrix_event_results (
  event_id TEXT PRIMARY KEY, response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matrix_outbox (
  notification_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, thread_root TEXT NOT NULL,
  body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL,
  sent_event_id TEXT, thread_notification_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'message', target_notification_id TEXT NOT NULL DEFAULT '',
  sender TEXT NOT NULL DEFAULT 'gateway', mention INTEGER NOT NULL DEFAULT 0,
  plan_id TEXT);
CREATE INDEX IF NOT EXISTS matrix_outbox_pending
  ON matrix_outbox(state, sender, created_at);
CREATE INDEX IF NOT EXISTS matrix_outbox_sent
  ON matrix_outbox(room_id, sent_event_id);
CREATE TABLE IF NOT EXISTS external_actions (
  action_key TEXT PRIMARY KEY, kind TEXT NOT NULL, request_json TEXT NOT NULL,
  state TEXT NOT NULL, result_json TEXT, last_error TEXT);
CREATE TABLE IF NOT EXISTS plan_notes (
  plan_id TEXT PRIMARY KEY REFERENCES plans(plan_id), markdown TEXT NOT NULL,
  updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS plan_controls (
  plan_id TEXT PRIMARY KEY REFERENCES plans(plan_id), previous_state TEXT,
  updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS coordinator_events (
  event_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  source TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  received_at INTEGER NOT NULL, ready_at INTEGER NOT NULL, batch_id TEXT,
  processed_at INTEGER);
CREATE INDEX IF NOT EXISTS coordinator_events_ready
  ON coordinator_events(processed_at, ready_at, plan_id);
CREATE TABLE IF NOT EXISTS luna_turns (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id TEXT NOT NULL REFERENCES plans(plan_id), batch_id TEXT NOT NULL UNIQUE,
  input_json TEXT NOT NULL, output_json TEXT, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
  created_at INTEGER NOT NULL, completed_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at INTEGER NOT NULL DEFAULT 0, last_error TEXT);
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
        if current < 10:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(matrix_outbox)")}
            if "thread_notification_id" not in columns:
                self.db.execute(
                    "ALTER TABLE matrix_outbox ADD COLUMN "
                    "thread_notification_id TEXT NOT NULL DEFAULT ''"
                )
        if current < 11:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(matrix_outbox)")}
            if "kind" not in columns:
                self.db.execute(
                    "ALTER TABLE matrix_outbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'message'"
                )
            if "target_notification_id" not in columns:
                self.db.execute(
                    "ALTER TABLE matrix_outbox ADD COLUMN target_notification_id TEXT NOT NULL DEFAULT ''"
                )
            columns = {row[1] for row in self.db.execute(
                "PRAGMA table_info(plan_deliverables)")}
            if "attempt" not in columns:
                self.db.execute(
                    "ALTER TABLE plan_deliverables ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1"
                )
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(luna_turns)")}
            for name, declaration in {
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "next_attempt_at": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT",
            }.items():
                if name not in columns:
                    self.db.execute(f"ALTER TABLE luna_turns ADD COLUMN {name} {declaration}")
            # The v11 tables are created by DDL above. Reset an interrupted
            # coordinator batch to pending: tool actions have their own
            # idempotency keys, so replaying the exact input is safe.
            self.db.execute(
                "UPDATE luna_turns SET state='pending' WHERE state='running'"
            )
        if current < 12:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(matrix_outbox)")}
            for name, declaration in {
                "sender": "TEXT NOT NULL DEFAULT 'gateway'",
                "mention": "INTEGER NOT NULL DEFAULT 0",
                "plan_id": "TEXT",
            }.items():
                if name not in columns:
                    self.db.execute(f"ALTER TABLE matrix_outbox ADD COLUMN {name} {declaration}")
            # Conversations are flat from v12 on. Existing rows keep their
            # thread_root as a historical anchor but are never re-sent, so
            # clearing it here would only lose the permalink.
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
            existing = db.execute(
                "SELECT payload_hash FROM inbound_events WHERE source=? AND external_id=?",
                (source, external_id),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ValueError("event identity was replayed with a different payload")
                return False
            db.execute("INSERT INTO inbound_events VALUES (?,?,?,?)",
                       (source, external_id, payload_hash, int(time.time())))
            return True

    def release_event(self, source: str, external_id: str, payload_hash: str) -> bool:
        """Permit redelivery when processing failed after durable admission."""
        with self.transaction() as db:
            return db.execute(
                "DELETE FROM inbound_events WHERE source=? AND external_id=? AND payload_hash=?",
                (source, external_id, payload_hash),
            ).rowcount == 1

    def plan_for_github_url(self, url: str):
        """Resolve a plan, deliverable issue, or known pull request URL."""
        with self.lock:
            return self.db.execute(
                "SELECT p.* FROM plans p LEFT JOIN plan_deliverables d ON d.plan_id=p.plan_id "
                "WHERE p.github_issue_url=? OR d.issue_url=? OR d.pr_url=? "
                "ORDER BY CASE WHEN p.github_issue_url=? THEN 0 ELSE 1 END LIMIT 1",
                (url, url, url, url),
            ).fetchone()

    def active_plans_for_repository(self, repository_url: str):
        target = str(repository_url).rstrip("/").removesuffix(".git").lower()
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM plans WHERE state NOT IN ('completed','cancelled') "
                "ORDER BY plan_id"
            ).fetchall()
        return [row for row in rows
                if str(row["repository"]).rstrip("/").removesuffix(".git").lower() == target]

    def enqueue_coordinator_event(self, event_id: str, plan_id: str, source: str,
                                  event_type: str, payload: dict[str, Any],
                                  delay_seconds: int = 30) -> bool:
        """Durably queue one bounded, untrusted event for Luna."""
        now = int(time.time())
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if len(encoded) > 64_000:
            encoded = json.dumps({
                "truncated": True,
                "summary": encoded[:60_000],
            }, sort_keys=True)
        with self.transaction() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO coordinator_events "
                "(event_id,plan_id,source,event_type,payload_json,received_at,ready_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (event_id, plan_id, source, event_type, encoded, now,
                 now + max(0, delay_seconds)),
            ).rowcount == 1
            if inserted and delay_seconds > 0:
                # A debounce window: every new same-plan event pushes the
                # complete unclaimed batch out, rather than giving each event
                # an independent timer.
                db.execute(
                    "UPDATE coordinator_events SET ready_at=? WHERE plan_id=? "
                    "AND processed_at IS NULL AND batch_id IS NULL",
                    (now + delay_seconds, plan_id),
                )
            return inserted

    def next_luna_batch(self, now: int | None = None, limit: int = 50):
        """Claim one per-plan batch, or replay an interrupted identical turn."""
        now = int(time.time()) if now is None else now
        with self.transaction() as db:
            pending = db.execute(
                "SELECT * FROM luna_turns WHERE state='pending' AND next_attempt_at<=? "
                "ORDER BY sequence LIMIT 1", (now,)
            ).fetchone()
            if pending:
                db.execute("UPDATE luna_turns SET state='running',attempts=attempts+1 "
                           "WHERE sequence=?",
                           (pending["sequence"],))
                return {
                    "sequence": pending["sequence"], "plan_id": pending["plan_id"],
                    "batch_id": pending["batch_id"],
                    "events": json.loads(pending["input_json"]),
                }
            first = db.execute(
                "SELECT plan_id FROM coordinator_events WHERE processed_at IS NULL "
                "AND batch_id IS NULL AND ready_at<=? ORDER BY ready_at,event_id LIMIT 1",
                (now,),
            ).fetchone()
            if not first:
                return None
            rows = db.execute(
                "SELECT event_id,source,event_type,payload_json,received_at "
                "FROM coordinator_events WHERE plan_id=? AND processed_at IS NULL "
                "AND batch_id IS NULL AND ready_at<=? ORDER BY received_at,event_id LIMIT ?",
                (first["plan_id"], now, max(1, min(limit, 100))),
            ).fetchall()
            event_ids = [row["event_id"] for row in rows]
            batch_id = "luna:" + __import__("hashlib").sha256(
                "\n".join(event_ids).encode()).hexdigest()[:24]
            events = [{
                "event_id": row["event_id"], "source": row["source"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "received_at": row["received_at"],
            } for row in rows]
            encoded = json.dumps(events, sort_keys=True, ensure_ascii=False)
            db.executemany(
                "UPDATE coordinator_events SET batch_id=? WHERE event_id=?",
                [(batch_id, event_id) for event_id in event_ids],
            )
            turn = db.execute(
                "INSERT INTO luna_turns(plan_id,batch_id,input_json,state,created_at) "
                "VALUES (?,?,?,'running',?) RETURNING sequence",
                (first["plan_id"], batch_id, encoded, now),
            ).fetchone()
            db.execute("UPDATE luna_turns SET attempts=1 WHERE sequence=?", (turn[0],))
            return {"sequence": turn[0], "plan_id": first["plan_id"],
                    "batch_id": batch_id, "events": events}

    def finish_luna_turn(self, sequence: int, output: dict[str, Any],
                         input_tokens: int, output_tokens: int) -> None:
        now = int(time.time())
        encoded = json.dumps(output, sort_keys=True, ensure_ascii=False)
        with self.transaction() as db:
            row = db.execute(
                "SELECT batch_id FROM luna_turns WHERE sequence=?", (sequence,)
            ).fetchone()
            if not row:
                raise ValueError("unknown Luna turn")
            db.execute(
                "UPDATE luna_turns SET state='complete',output_json=?,input_tokens=?,"
                "output_tokens=?,completed_at=? WHERE sequence=?",
                (encoded[:64_000], max(0, input_tokens), max(0, output_tokens),
                 now, sequence),
            )
            db.execute(
                "UPDATE coordinator_events SET processed_at=? WHERE batch_id=?",
                (now, row["batch_id"]),
            )
            plan_id = db.execute(
                "SELECT plan_id FROM luna_turns WHERE sequence=?", (sequence,)
            ).fetchone()[0]
        self.enqueue_plan_card(plan_id)

    def fail_luna_turn(self, sequence: int, error: str = "") -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT plan_id,attempts FROM luna_turns WHERE sequence=?", (sequence,)
            ).fetchone()
            if not row:
                return
            if row["attempts"] >= 5:
                db.execute(
                    "UPDATE luna_turns SET state='failed',last_error=? WHERE sequence=?",
                    (str(error)[-2_000:], sequence),
                )
                db.execute("UPDATE plans SET state='needs_input' WHERE plan_id=?",
                           (row["plan_id"],))
            else:
                delay = min(300, 15 * (2 ** max(0, row["attempts"] - 1)))
                db.execute(
                    "UPDATE luna_turns SET state='pending',next_attempt_at=?,last_error=? "
                    "WHERE sequence=?",
                    (int(time.time()) + delay, str(error)[-2_000:], sequence),
                )
        self.enqueue_plan_card(row["plan_id"])

    def luna_usage(self, plan_id: str) -> dict[str, int]:
        with self.lock:
            row = self.db.execute(
                "SELECT count(*) turns,COALESCE(sum(input_tokens),0) input_tokens,"
                "COALESCE(sum(output_tokens),0) output_tokens FROM luna_turns "
                "WHERE plan_id=? AND state='complete'", (plan_id,),
            ).fetchone()
        return dict(row)

    def update_plan_notes(self, plan_id: str, markdown: str) -> None:
        markdown = str(markdown).strip()[:32_000]
        with self.transaction() as db:
            db.execute(
                "INSERT INTO plan_notes VALUES (?,?,?) ON CONFLICT(plan_id) DO UPDATE SET "
                "markdown=excluded.markdown,updated_at=excluded.updated_at",
                (plan_id, markdown, int(time.time())),
            )

    def plan_notes(self, plan_id: str) -> str:
        with self.lock:
            row = self.db.execute(
                "SELECT markdown FROM plan_notes WHERE plan_id=?", (plan_id,)
            ).fetchone()
        return row[0] if row else ""

    def audit(self, actor: str, action: str, subject: str, payload: dict[str, Any]) -> int:
        with self.transaction() as db:
            row = db.execute(
                "INSERT INTO audit_events(occurred_at,actor,action,subject,payload_json) "
                "VALUES (?,?,?,?,?) RETURNING sequence",
                (int(time.time()), actor, action, subject, json.dumps(payload, sort_keys=True))).fetchone()
            return int(row[0])

    def audit_count(self, subject: str, action: str) -> int:
        with self.lock:
            return int(self.db.execute(
                "SELECT count(*) FROM audit_events WHERE subject=? AND action=?",
                (subject, action),
            ).fetchone()[0])

    def reserve_astra_turn(self, plan_id: str, kind: str, cap: int = 20) -> bool:
        """Atomically account for a planner call before spending the turn."""
        with self.transaction() as db:
            count = int(db.execute(
                "SELECT count(*) FROM audit_events WHERE subject=? AND action='astra.turn'",
                (plan_id,),
            ).fetchone()[0])
            if count >= cap:
                db.execute("UPDATE plans SET state='needs_input' WHERE plan_id=?", (plan_id,))
                reserved = False
            else:
                db.execute(
                    "INSERT INTO audit_events(occurred_at,actor,action,subject,payload_json) "
                    "VALUES (?,?,?,?,?)",
                    (int(time.time()), "astra", "astra.turn", plan_id,
                     json.dumps({"kind": str(kind)[:100]}, sort_keys=True)),
                )
                reserved = True
        self.enqueue_plan_card(plan_id)
        return reserved

    def astra_turns(self, plan_id: str) -> int:
        return self.audit_count(plan_id, "astra.turn")

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

    def plan_for_anchor(self, room_id: str, anchor_event_id: str):
        """The plan started by a specific owner message."""
        with self.lock:
            return self.db.execute(
                "SELECT * FROM plans WHERE matrix_room_id=? AND root_event_id=?",
                (room_id, anchor_event_id)).fetchone()

    def plan_for_card_event(self, room_id: str, event_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT p.* FROM plans p JOIN matrix_outbox o "
                "ON o.notification_id=('plan:' || p.plan_id || ':card') "
                "WHERE o.room_id=? AND o.sent_event_id=? LIMIT 1",
                (room_id, event_id),
            ).fetchone()

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

    TERMINAL_STATES = frozenset({"complete", "cancelled", "failed"})

    def set_plan_state(self, plan_id: str, state: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE plans SET state=? WHERE plan_id=?", (state, plan_id))
        self.enqueue_plan_card(plan_id)
        if state in self.TERMINAL_STATES:
            self.enqueue_unpin(plan_id)

    def pause_plan(self, plan_id: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT state FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            if not row:
                raise ValueError("unknown plan")
            if row["state"] != "paused":
                db.execute(
                    "INSERT INTO plan_controls VALUES (?,?,?) ON CONFLICT(plan_id) DO UPDATE SET "
                    "previous_state=excluded.previous_state,updated_at=excluded.updated_at",
                    (plan_id, row["state"], int(time.time())),
                )
                db.execute("UPDATE plans SET state='paused' WHERE plan_id=?", (plan_id,))
        self.enqueue_plan_card(plan_id)

    def resume_plan(self, plan_id: str) -> str:
        with self.transaction() as db:
            control = db.execute(
                "SELECT previous_state FROM plan_controls WHERE plan_id=?", (plan_id,)
            ).fetchone()
            state = control[0] if control and control[0] else "review"
            db.execute("UPDATE plans SET state=? WHERE plan_id=?", (state, plan_id))
            db.execute("DELETE FROM plan_controls WHERE plan_id=?", (plan_id,))
        self.enqueue_plan_card(plan_id)
        return state

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
        # Foreman's repo-backed native loop applies the coder no-change gate
        # even to read-only freeform tasks. A successful scout therefore ends
        # as NO-CHANGES/NO-GO, with its useful answer preserved separately.
        # Prefer that model answer over the generic "produced no diff" wrapper.
        extra = result.get("extra") if isinstance(result, dict) else None
        if isinstance(extra, dict):
            summary = extra.get("modelSummary") or summary
            # Job-mode Foreman currently wraps executor errors in a generic
            # image-pull/OOM/deadline summary. Give Astra a bounded, actionable
            # classification without forwarding raw logs or possible secrets.
            if extra.get("outcome") == "JOB-ERROR" and not extra.get("modelSummary"):
                log_tail = str(extra.get("logTail", "")).lower()
                if any(marker in log_tail for marker in (
                        "connection refused", "connect: operation not permitted",
                        "i/o timeout", "context deadline exceeded")):
                    summary = ("Foreman research Job could not reach its inference endpoint; "
                               "the task produced no repository evidence.")
                else:
                    reason = status.get("failureReason") or result.get("failureReason")
                    summary = f"Foreman research Job failed before producing evidence: {reason or 'unknown infrastructure error'}."
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

    def has_active_research(self) -> bool:
        with self.lock:
            return self.db.execute(
                "SELECT 1 FROM plan_research r JOIN plans p ON p.plan_id=r.plan_id "
                "WHERE p.state='researching' AND r.state NOT IN ('Succeeded','Failed') LIMIT 1"
            ).fetchone() is not None

    def research_round_groups(self):
        with self.lock:
            return self.db.execute(
                "SELECT DISTINCT r.plan_id,r.round,p.matrix_room_id,p.root_event_id "
                "FROM plan_research r JOIN plans p ON p.plan_id=r.plan_id "
                "ORDER BY r.plan_id,r.round"
            ).fetchall()

    def research_run_links(self, plan_id: str, round_number: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT r.position,r.task_name,o.sent_event_id FROM plan_research r "
                "LEFT JOIN matrix_outbox o ON o.notification_id="
                "('agent-run:' || r.task_name || ':root') "
                "WHERE r.plan_id=? AND r.round=? ORDER BY r.position",
                (plan_id, round_number),
            ).fetchall()
        if not rows or any(not row["sent_event_id"] for row in rows):
            return []
        return [dict(row) for row in rows]

    def unpublished_terminal_research(self):
        with self.lock:
            return self.db.execute(
                "SELECT r.*,p.repository,p.matrix_room_id,p.root_event_id "
                "FROM plan_research r JOIN plans p ON p.plan_id=r.plan_id "
                "JOIN matrix_outbox root ON root.notification_id="
                "('agent-run:' || r.task_name || ':root') "
                "LEFT JOIN matrix_outbox o ON o.notification_id="
                "('agent-run:' || r.task_name || ':transcript:999-final') "
                "WHERE r.state IN ('Succeeded','Failed') AND o.notification_id IS NULL "
                "ORDER BY r.updated_at,r.task_name"
            ).fetchall()

    def current_plan_version(self, plan_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT v.* FROM plan_versions v JOIN plans p ON p.plan_id=v.plan_id "
                "AND p.current_version=v.version WHERE p.plan_id=?", (plan_id,)).fetchone()

    def approval(self, plan_id: str):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM approvals WHERE plan_id=?", (plan_id,)
            ).fetchone()

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

    def deliverable_urls(self, plan_id: str) -> list[str]:
        with self.lock:
            return [row[0] for row in self.db.execute(
                "SELECT issue_url FROM plan_deliverables WHERE plan_id=? ORDER BY position",
                (plan_id,),
            ).fetchall()]

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

    def prepare_deliverable_retry(self, plan_id: str, issue_url: str):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM plan_deliverables WHERE plan_id=? AND issue_url=?",
                (plan_id, issue_url),
            ).fetchone()
            if not row or row["state"] != "failed":
                raise ValueError("only this plan's failed deliverable can be retried")
            db.execute(
                "UPDATE plan_deliverables SET state='pending',workload_name=NULL,pr_url=NULL,"
                "head_sha=NULL,merge_uuid=NULL,merge_status_json=NULL,attempt=attempt+1,"
                "updated_at=? WHERE plan_id=? AND position=?",
                (int(time.time()), plan_id, row["position"]),
            )
            db.execute("DELETE FROM workloads WHERE name=?", (row["workload_name"],))
            db.execute("UPDATE plans SET state='decomposed' WHERE plan_id=?", (plan_id,))
            result = db.execute(
                "SELECT * FROM plan_deliverables WHERE plan_id=? AND position=?",
                (plan_id, row["position"]),
            ).fetchone()
        self.enqueue_plan_card(plan_id)
        return result

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

    def completed_plans(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM plans WHERE state='completed' AND github_issue_url IS NOT NULL "
                "ORDER BY plan_id"
            ).fetchall()

    def cancelled_plans(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM plans WHERE state='cancelled' AND github_issue_url IS NOT NULL "
                "ORDER BY plan_id"
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
        self.enqueue_plan_card(plan_id)

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
                "WHERE p.state IN ('running','needs_input') AND d.state='running' "
                "ORDER BY w.name").fetchall()

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
        if changed:
            self.enqueue_plan_card(row["plan_id"])
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
                outcome = new_state
            elif not db.execute(
                    "SELECT 1 FROM plan_deliverables WHERE plan_id=? AND state!='merged' LIMIT 1",
                    (plan_id,)).fetchone():
                db.execute("UPDATE plans SET state='completed' WHERE plan_id=?", (plan_id,))
                outcome = "completed"
            else:
                outcome = new_state
        self.enqueue_plan_card(plan_id)
        return outcome

    def fail_deliverable(self, plan_id: str, position: int, status: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE plan_deliverables SET state='failed',merge_status_json=?,updated_at=? "
                "WHERE plan_id=? AND position=?",
                (json.dumps(status, sort_keys=True), int(time.time()), plan_id, position),
            )
            db.execute("UPDATE plans SET state='failed' WHERE plan_id=?", (plan_id,))
        self.enqueue_plan_card(plan_id)

    def plan_progress(self, plan_id: str) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute(
                "SELECT state,count(*) count FROM plan_deliverables WHERE plan_id=? GROUP BY state",
                (plan_id,),
            ).fetchall()
        counts = {row["state"]: row["count"] for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    def enqueue_matrix(self, notification_id: str, room_id: str, thread_root: str,
                       body: str, thread_notification_id: str = "",
                       kind: str = "message", target_notification_id: str = "",
                       sender: str = "gateway", mention: bool = False,
                       plan_id: str | None = None) -> bool:
        if kind not in {"message", "edit", "pin", "unpin"}:
            raise ValueError("unsupported Matrix outbox action")
        if sender not in SENDERS:
            raise ValueError("unknown Matrix sender identity")
        with self.transaction() as db:
            return db.execute(
                "INSERT OR IGNORE INTO matrix_outbox(notification_id,room_id,thread_root,body,"
                "created_at,thread_notification_id,kind,target_notification_id,sender,mention,"
                "plan_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (notification_id, room_id, thread_root, body, int(time.time()),
                 thread_notification_id, kind, target_notification_id, sender,
                 1 if mention else 0, plan_id)).rowcount == 1

    def enqueue_plan_card(self, plan_id: str) -> bool:
        plan = self.plan(plan_id)
        if not plan:
            return False
        progress = self.plan_progress(plan_id)
        research = self.research_progress(plan_id)
        usage = self.luna_usage(plan_id)
        astra_turns = self.astra_turns(plan_id)
        issue = plan["github_issue_url"] or ""
        body = (
            f"**{plan['state'].upper()}** · plan `{plan_id}` · version {plan['current_version']}\n\n"
            + (f"Plan issue: {issue}\n\n" if issue else "")
            + f"Deliverables: {progress.get('merged', 0)}/{progress.get('total', 0)} merged · "
            f"Scouts: {research.get('Succeeded', 0) + research.get('Failed', 0)}/"
            f"{research.get('total', 0)} finished\n\n"
            f"Astra: {astra_turns} turns · "
            f"Luna: {usage['turns']} turns · {usage['input_tokens']} input tokens · "
            f"{usage['output_tokens']} output tokens"
        )
        root_id = f"plan:{plan_id}:card"
        with self.lock:
            existing = self.db.execute(
                "SELECT 1 FROM matrix_outbox WHERE notification_id=?", (root_id,)
            ).fetchone()
        if not existing:
            # The card is the pinned object for the life of the plan: one
            # edited message carrying state and the issue link, so an open plan
            # stays reachable from the room header instead of scrolling away.
            queued = self.enqueue_matrix(
                root_id, plan["matrix_room_id"], "", body, plan_id=plan_id)
            self.enqueue_pin(plan_id, plan["matrix_room_id"], root_id)
            return queued
        digest = __import__("hashlib").sha256(body.encode()).hexdigest()[:20]
        return self.enqueue_matrix(
            f"{root_id}:edit:{digest}", plan["matrix_room_id"], "",
            body, kind="edit", target_notification_id=root_id, plan_id=plan_id,
        )

    def enqueue_pin(self, plan_id: str, room_id: str, target_notification_id: str) -> bool:
        return self.enqueue_matrix(
            f"plan:{plan_id}:pin", room_id, "", "", kind="pin",
            target_notification_id=target_notification_id, plan_id=plan_id)

    def enqueue_unpin(self, plan_id: str) -> bool:
        """Release the room pin once a plan can no longer need attention."""
        with self.lock:
            row = self.db.execute(
                "SELECT room_id,target_notification_id FROM matrix_outbox "
                "WHERE notification_id=?", (f"plan:{plan_id}:pin",)).fetchone()
        if not row:
            return False
        return self.enqueue_matrix(
            f"plan:{plan_id}:unpin", row["room_id"], "", "", kind="unpin",
            target_notification_id=row["target_notification_id"], plan_id=plan_id)

    def pending_matrix(self, limit: int = 20,
                       sender: str | None = None) -> list[dict[str, Any]]:
        if sender is not None and sender not in SENDERS:
            raise ValueError("unknown Matrix sender identity")
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT child.notification_id,child.room_id,"
                "CASE WHEN child.thread_root != '' THEN child.thread_root "
                "ELSE COALESCE(parent.sent_event_id,'') END thread_root,child.body,child.kind,"
                "child.sender,child.mention,"
                "COALESCE(target.sent_event_id,'') target_event_id "
                "FROM matrix_outbox child LEFT JOIN matrix_outbox parent "
                "ON parent.notification_id=child.thread_notification_id "
                "LEFT JOIN matrix_outbox target ON target.notification_id=child.target_notification_id "
                "WHERE child.state='pending' AND (child.thread_notification_id='' "
                "OR parent.sent_event_id IS NOT NULL) AND (child.target_notification_id='' "
                "OR target.sent_event_id IS NOT NULL) "
                "AND (? IS NULL OR child.sender=?) "
                "ORDER BY child.created_at,child.notification_id LIMIT ?",
                (sender, sender, limit)).fetchall()]

    def plan_for_sent_event(self, room_id: str, event_id: str):
        """Resolve the plan a bot message belonged to, for flat rich replies."""
        with self.lock:
            return self.db.execute(
                "SELECT p.* FROM plans p JOIN matrix_outbox o ON o.plan_id=p.plan_id "
                "WHERE o.room_id=? AND o.sent_event_id=?", (room_id, event_id)).fetchone()

    def active_plan_for_room(self, room_id: str):
        """The plan a bare message in a flat room is about.

        Rooms carry one live plan at a time, so an unaddressed message belongs
        to the most recently created plan that has not reached a terminal
        state. A plan counts as present in a room when it either started there
        or has posted there, which is what makes the implementation room
        resolvable without threads. Explicit `!cogito <command> <plan-id>`
        remains the recovery path when that guess is wrong.
        """
        with self.lock:
            return self.db.execute(
                "SELECT p.* FROM plans p WHERE p.state NOT IN ('complete','cancelled','failed') "
                "AND (p.matrix_room_id=? OR EXISTS (SELECT 1 FROM matrix_outbox o "
                "WHERE o.plan_id=p.plan_id AND o.room_id=?)) "
                "ORDER BY p.rowid DESC LIMIT 1", (room_id, room_id)).fetchone()

    def complete_matrix(self, notification_id: str, event_id: str) -> bool:
        with self.transaction() as db:
            return db.execute("UPDATE matrix_outbox SET state='sent',sent_event_id=? "
                              "WHERE notification_id=? AND state='pending'",
                              (event_id, notification_id)).rowcount == 1

    def prometheus_metrics(self) -> str:
        lines = ["# HELP cogito_gateway_up Whether the gateway process is serving.",
                 "# TYPE cogito_gateway_up gauge", "cogito_gateway_up 1",
                 "# HELP cogito_gateway_objects Durable objects by kind and state.",
                 "# TYPE cogito_gateway_objects gauge"]
        with self.lock:
            for kind, table in {"plan": "plans", "workload": "workloads",
                                "matrix_outbox": "matrix_outbox",
                                "external_action": "external_actions"}.items():
                for row in self.db.execute(
                        f"SELECT state,count(*) count FROM {table} GROUP BY state ORDER BY state"):
                    lines.append(f'cogito_gateway_objects{{kind="{kind}",state="{row["state"]}"}} {row["count"]}')
            failed = self.db.execute(
                "SELECT count(*) FROM external_actions action JOIN luna_turns turn "
                "ON substr(action.action_key,1,length(turn.batch_id)+1)=turn.batch_id || ':' "
                "WHERE action.last_error IS NOT NULL "
                "AND turn.state IN ('pending','running')"
            ).fetchone()[0]
            audits = self.db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
            luna = self.db.execute(
                "SELECT plan_id,count(*) turns,COALESCE(sum(input_tokens),0) input_tokens,"
                "COALESCE(sum(output_tokens),0) output_tokens FROM luna_turns "
                "WHERE state='complete' GROUP BY plan_id ORDER BY plan_id"
            ).fetchall()
            astra = self.db.execute(
                "SELECT subject plan_id,count(*) turns FROM audit_events "
                "WHERE action='astra.turn' GROUP BY subject ORDER BY subject"
            ).fetchall()
            batches = self.db.execute(
                "SELECT plan_id,count(DISTINCT batch_id) batches,count(*) events "
                "FROM coordinator_events WHERE processed_at IS NOT NULL "
                "GROUP BY plan_id ORDER BY plan_id"
            ).fetchall()
        lines.extend(["# HELP cogito_gateway_external_action_errors Durable actions awaiting retry.",
                      "# TYPE cogito_gateway_external_action_errors gauge",
                      f"cogito_gateway_external_action_errors {failed}",
                      "# HELP cogito_gateway_audit_events_total Append-only audit records.",
                      "# TYPE cogito_gateway_audit_events_total counter",
                      f"cogito_gateway_audit_events_total {audits}"])
        lines.extend([
            "# HELP cogito_gateway_luna_turns_total Completed Luna turns by plan.",
            "# TYPE cogito_gateway_luna_turns_total counter",
            "# HELP cogito_gateway_astra_turns_total Reserved Astra turns by plan.",
            "# TYPE cogito_gateway_astra_turns_total counter",
            "# HELP cogito_gateway_luna_tokens_total Luna tokens by plan and kind.",
            "# TYPE cogito_gateway_luna_tokens_total counter",
            "# HELP cogito_gateway_webhook_batches_total Coordinator event batches by plan.",
            "# TYPE cogito_gateway_webhook_batches_total counter",
            "# HELP cogito_gateway_coalesced_events_total Events consumed in batches by plan.",
            "# TYPE cogito_gateway_coalesced_events_total counter",
        ])
        for row in astra:
            label = str(row["plan_id"]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'cogito_gateway_astra_turns_total{{plan="{label}"}} {row["turns"]}')
        for row in luna:
            label = str(row["plan_id"]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'cogito_gateway_luna_turns_total{{plan="{label}"}} {row["turns"]}')
            lines.append(
                f'cogito_gateway_luna_tokens_total{{plan="{label}",kind="input"}} '
                f'{row["input_tokens"]}')
            lines.append(
                f'cogito_gateway_luna_tokens_total{{plan="{label}",kind="output"}} '
                f'{row["output_tokens"]}')
        for row in batches:
            label = str(row["plan_id"]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(
                f'cogito_gateway_webhook_batches_total{{plan="{label}"}} {row["batches"]}')
            lines.append(
                f'cogito_gateway_coalesced_events_total{{plan="{label}"}} {row["events"]}')
        return "\n".join(lines) + "\n"

    def close(self) -> None:
        self.db.close()
