"""SQLite persistence for the Helpyou discussion test bed.

The test bed stores discussion state, transcript messages and pilot-memory
candidates. It does not publish pilot contributions as operational authority.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid


SCHEMA = """
CREATE TABLE IF NOT EXISTS helpyou_sessions (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    case_id TEXT,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL,
    reasoning_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS helpyou_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('pilot', 'helpyou', 'system')),
    kind TEXT NOT NULL DEFAULT 'message',
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES helpyou_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS helpyou_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    raw_pilot_wording TEXT NOT NULL,
    ai_interpretation TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    privacy_scope TEXT NOT NULL DEFAULT 'private',
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES helpyou_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_helpyou_messages_session
ON helpyou_messages (session_id, id);

CREATE INDEX IF NOT EXISTS idx_helpyou_memories_session
ON helpyou_memories (session_id, id);
"""


class TestbedStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def create_session(self, *, mode: str, case_id: str | None, scenario: str) -> str:
        session_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO helpyou_sessions (id, mode, case_id, scenario, status)
                VALUES (?, ?, ?, ?, 'active')
                """,
                (session_id, mode, case_id, scenario),
            )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM helpyou_sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["reasoning"] = json.loads(item.pop("reasoning_json") or "{}")
        return item

    def list_sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, mode, case_id, scenario, status, created_at, updated_at
                FROM helpyou_sessions
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_reasoning(
        self,
        session_id: str,
        reasoning: Mapping[str, Any],
        *,
        status: str = "active",
    ) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE helpyou_sessions
                SET reasoning_json=?, status=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (json.dumps(reasoning, ensure_ascii=False), status, session_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"Session {session_id} not found")

    def reset_session(self, session_id: str) -> None:
        with self.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM helpyou_sessions WHERE id=?", (session_id,)
            ).fetchone() is None:
                raise LookupError(f"Session {session_id} not found")
            conn.execute(
                "DELETE FROM helpyou_messages WHERE session_id=?", (session_id,)
            )
            conn.execute(
                "DELETE FROM helpyou_memories WHERE session_id=?", (session_id,)
            )
            conn.execute(
                """
                UPDATE helpyou_sessions
                SET reasoning_json='{}', status='active', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (session_id,),
            )

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        kind: str = "message",
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        content = content.strip()
        if not content:
            raise ValueError("Message content cannot be empty")
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO helpyou_messages (
                    session_id, role, kind, content, metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    kind,
                    content,
                    json.dumps(dict(metadata or {}), ensure_ascii=False),
                ),
            )
        return int(cursor.lastrowid)

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, kind, content, metadata_json, created_at
                FROM helpyou_messages
                WHERE session_id=?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            messages.append(item)
        return messages

    def upsert_memory(
        self,
        session_id: str,
        *,
        record_type: str,
        raw_pilot_wording: str,
        ai_interpretation: str,
        evidence_status: str,
        privacy_scope: str = "private",
        context: Mapping[str, Any] | None = None,
    ) -> int:
        if raw_pilot_wording.strip() == ai_interpretation.strip():
            raise ValueError("Pilot wording and AI interpretation must remain separate")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM helpyou_memories WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if existing:
                memory_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE helpyou_memories
                    SET record_type=?, raw_pilot_wording=?, ai_interpretation=?,
                        evidence_status=?, privacy_scope=?, context_json=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        record_type,
                        raw_pilot_wording,
                        ai_interpretation,
                        evidence_status,
                        privacy_scope,
                        json.dumps(dict(context or {}), ensure_ascii=False),
                        memory_id,
                    ),
                )
                return memory_id
            cursor = conn.execute(
                """
                INSERT INTO helpyou_memories (
                    session_id, record_type, raw_pilot_wording,
                    ai_interpretation, evidence_status, privacy_scope, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    record_type,
                    raw_pilot_wording,
                    ai_interpretation,
                    evidence_status,
                    privacy_scope,
                    json.dumps(dict(context or {}), ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def list_memories(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, record_type, raw_pilot_wording, ai_interpretation,
                       evidence_status, privacy_scope, context_json,
                       created_at, updated_at
                FROM helpyou_memories
                WHERE session_id=?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        memories: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["context"] = json.loads(item.pop("context_json") or "{}")
            memories.append(item)
        return memories

    def delete_memory(self, session_id: str, memory_id: int) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM helpyou_memories WHERE id=? AND session_id=?",
                (memory_id, session_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Memory record not found")

    def export_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")
        return {
            "schema": "PilotDriven-Helpyou-Testbed-Session-v0.1",
            "session": session,
            "messages": self.list_messages(session_id),
            "memories": self.list_memories(session_id),
        }
