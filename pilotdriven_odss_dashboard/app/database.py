from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any
import uuid

from .config import DATA_DIR

DB_PATH = DATA_DIR / "odss.db"

SCHEMA = '''
CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_number TEXT,
    flight_date TEXT,
    departure TEXT,
    destination TEXT,
    aircraft TEXT,
    registration TEXT,
    source_filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Uploaded',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    analysis_path TEXT,
    level1_report TEXT,
    level2_report TEXT,
    level3_json TEXT,
    level3_report TEXT,
    notes TEXT,
    last_error TEXT,
    actual_takeoff_utc TEXT,
    timing_reference_type TEXT,
    timing_reference_waypoint TEXT,
    timing_reference_utc TEXT,
    analysis_id TEXT UNIQUE,
    tenant_id TEXT,
    user_id TEXT,
    workspace_id TEXT,
    external_flight_id TEXT,
    analysis_version TEXT,
    service_request_id TEXT,
    report_refresh_state TEXT NOT NULL DEFAULT 'pending',
    report_refresh_error_type TEXT,
    report_refresh_updated_at TEXT,
    analysis_failure_category TEXT
);

CREATE TABLE IF NOT EXISTS personal_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id INTEGER NOT NULL,
    placement TEXT NOT NULL CHECK (
        placement IN ('separate', 'departure', 'destination', 'communications')
    ),
    note_text TEXT NOT NULL,
    include_level1 INTEGER NOT NULL DEFAULT 1 CHECK (include_level1 IN (0, 1)),
    include_level2 INTEGER NOT NULL DEFAULT 1 CHECK (include_level2 IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (flight_id) REFERENCES flights(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_personal_notes_flight
ON personal_notes (flight_id, id);

CREATE TABLE IF NOT EXISTS policy_snapshots (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, analysis_id)
);

CREATE TABLE IF NOT EXISTS level3_answers (
    tenant_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer_text TEXT,
    answer_state TEXT NOT NULL CHECK (answer_state IN ('answered', 'declined')),
    answered_by TEXT NOT NULL,
    answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, analysis_id, question_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS policy_snapshots_no_update
BEFORE UPDATE ON policy_snapshots
BEGIN
    SELECT RAISE(ABORT, 'policy snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS policy_snapshots_no_delete
BEFORE DELETE ON policy_snapshots
BEGIN
    SELECT RAISE(ABORT, 'policy snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;
'''


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(flights)")}
    adding_report_refresh_state = "report_refresh_state" not in existing
    additions = {
        "analysis_path": "TEXT",
        "last_error": "TEXT",
        "actual_takeoff_utc": "TEXT",
        "timing_reference_type": "TEXT",
        "timing_reference_waypoint": "TEXT",
        "timing_reference_utc": "TEXT",
        "analysis_id": "TEXT",
        "tenant_id": "TEXT",
        "user_id": "TEXT",
        "workspace_id": "TEXT",
        "external_flight_id": "TEXT",
        "analysis_version": "TEXT",
        "service_request_id": "TEXT",
        "level3_json": "TEXT",
        "level3_report": "TEXT",
        "report_refresh_state": "TEXT NOT NULL DEFAULT 'pending'",
        "report_refresh_error_type": "TEXT",
        "report_refresh_updated_at": "TEXT",
        "analysis_failure_category": "TEXT",
    }
    for column, sql_type in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE flights ADD COLUMN {column} {sql_type}")
    if adding_report_refresh_state:
        # Existing completed report pairs pre-date explicit freshness state.
        # Backfill only during the one-time column migration so a later failed
        # refresh can never be silently promoted on application restart.
        conn.execute(
            """
            UPDATE flights SET
                report_refresh_state=CASE
                    WHEN level1_report IS NOT NULL AND level2_report IS NOT NULL
                    THEN 'current'
                    ELSE 'pending'
                END,
                report_refresh_updated_at=CURRENT_TIMESTAMP
            """
        )
    conn.execute(
        "UPDATE flights SET analysis_id = COALESCE(analysis_id, 'legacy-' || id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_analysis_id ON flights (analysis_id)"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_flights_tenant_analysis
        ON flights (tenant_id, analysis_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_tenant_request
        ON flights (tenant_id, service_request_id)
        WHERE service_request_id IS NOT NULL
        """
    )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        conn.execute(
            '''
            UPDATE flights SET
                status='Failed',
                notes='Previous analysis was interrupted. Run the analysis again.',
                last_error='Analysis interrupted by application shutdown or restart.',
                analysis_failure_category='infrastructure',
                report_refresh_state=CASE
                    WHEN level1_report IS NOT NULL OR level2_report IS NOT NULL
                    THEN 'failed'
                    ELSE report_refresh_state
                END,
                report_refresh_error_type='InterruptedAnalysis',
                report_refresh_updated_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE status='Processing'
            ''',
        )


def create_flight(data: dict[str, Any]) -> int:
    with connect() as conn:
        cur = conn.execute(
            '''
            INSERT INTO flights (
                flight_number, flight_date, departure, destination,
                aircraft, registration, source_filename, source_path,
                status, notes, analysis_id, tenant_id, user_id,
                workspace_id, external_flight_id, analysis_version,
                service_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                data.get("flight_number"),
                data.get("flight_date"),
                data.get("departure"),
                data.get("destination"),
                data.get("aircraft"),
                data.get("registration"),
                data["source_filename"],
                data["source_path"],
                data.get("status", "Uploaded"),
                data.get("notes"),
                data.get("analysis_id") or uuid.uuid4().hex,
                data.get("tenant_id"),
                data.get("user_id"),
                data.get("workspace_id"),
                data.get("external_flight_id"),
                data.get("analysis_version") or "0.6.0",
                data.get("service_request_id"),
            ),
        )
        return int(cur.lastrowid)


def list_flights(tenant_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM flights WHERE tenant_id = ? ORDER BY id DESC",
                (tenant_id,),
            )
        )


def get_flight(flight_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()


def get_flight_for_tenant(flight_id: int, tenant_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM flights WHERE id = ? AND tenant_id = ?",
            (flight_id, tenant_id),
        ).fetchone()




def get_flight_by_analysis_id(
    analysis_id: str,
    tenant_id: str,
) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM flights
            WHERE analysis_id = ? AND tenant_id = ?
            """,
            (analysis_id, tenant_id),
        ).fetchone()


def get_flight_by_service_request(
    tenant_id: str,
    service_request_id: str,
) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM flights
            WHERE tenant_id = ? AND service_request_id = ?
            """,
            (tenant_id, service_request_id),
        ).fetchone()


def create_personal_note(
    flight_id: int,
    placement: str,
    note_text: str,
    include_level1: bool,
    include_level2: bool,
) -> int:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM flights WHERE id=?", (flight_id,)).fetchone() is None:
            raise LookupError(f"Flight {flight_id} not found")
        cursor = conn.execute(
            '''
            INSERT INTO personal_notes (
                flight_id, placement, note_text, include_level1, include_level2
            ) VALUES (?, ?, ?, ?, ?)
            ''',
            (
                flight_id,
                placement,
                note_text,
                int(include_level1),
                int(include_level2),
            ),
        )
        return int(cursor.lastrowid)


def restore_personal_note(flight_id: int, note: dict[str, Any]) -> None:
    """Restore an exact note row after a failed report regeneration.

    Service note deletion is only complete when the matching analysis and PDFs
    regenerate successfully.  Keeping the original id and timestamps lets the
    API roll back a rejected deletion without leaving an already-open client
    with a stale note identifier.
    """
    with connect() as conn:
        if conn.execute("SELECT 1 FROM flights WHERE id=?", (flight_id,)).fetchone() is None:
            raise LookupError(f"Flight {flight_id} not found")
        conn.execute(
            '''
            INSERT INTO personal_notes (
                id, flight_id, placement, note_text,
                include_level1, include_level2, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                int(note["id"]),
                flight_id,
                str(note["placement"]),
                str(note["note_text"]),
                int(bool(note["include_level1"])),
                int(bool(note["include_level2"])),
                str(note["created_at"]),
                str(note["updated_at"]),
            ),
        )


def list_personal_notes(flight_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                '''
                SELECT * FROM personal_notes
                WHERE flight_id=?
                ORDER BY id
                ''',
                (flight_id,),
            )
        )


def get_personal_note(flight_id: int, note_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM personal_notes WHERE id=? AND flight_id=?",
            (note_id, flight_id),
        ).fetchone()


def update_personal_note(
    flight_id: int,
    note_id: int,
    placement: str,
    note_text: str,
    include_level1: bool,
    include_level2: bool,
) -> None:
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE personal_notes SET
                placement=?,
                note_text=?,
                include_level1=?,
                include_level2=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND flight_id=?
            ''',
            (
                placement,
                note_text,
                int(include_level1),
                int(include_level2),
                note_id,
                flight_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Personal note {note_id} not found for flight {flight_id}")


def delete_personal_note(flight_id: int, note_id: int) -> None:
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM personal_notes WHERE id=? AND flight_id=?",
            (note_id, flight_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Personal note {note_id} not found for flight {flight_id}")


def update_status(
    flight_id: int,
    status: str,
    notes: str | None = None,
    last_error: str | None = None,
    tenant_id: str | None = None,
    analysis_failure_category: str | None = None,
) -> None:
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights
            SET status=?, notes=COALESCE(?, notes), last_error=?,
                analysis_failure_category=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (
                status,
                notes,
                last_error,
                analysis_failure_category,
                flight_id,
                tenant_id,
                tenant_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def restore_analysis_state(
    flight_id: int,
    status: str,
    notes: str | None,
    last_error: str | None,
    tenant_id: str | None = None,
    analysis_failure_category: str | None = None,
) -> None:
    """Release an analysis claim back to an exact prior observable state."""
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights SET
                status=?, notes=?, last_error=?, analysis_failure_category=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (
                status,
                notes,
                last_error,
                analysis_failure_category,
                flight_id,
                tenant_id,
                tenant_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


_ANALYSIS_SNAPSHOT_COLUMNS = (
    "flight_number",
    "flight_date",
    "departure",
    "destination",
    "aircraft",
    "registration",
    "status",
    "analysis_path",
    "level1_report",
    "level2_report",
    "level3_json",
    "level3_report",
    "notes",
    "last_error",
    "actual_takeoff_utc",
    "timing_reference_type",
    "timing_reference_waypoint",
    "timing_reference_utc",
    "analysis_version",
    "report_refresh_state",
    "report_refresh_error_type",
    "report_refresh_updated_at",
    "analysis_failure_category",
)


def restore_analysis_snapshot(
    flight_id: int,
    snapshot: sqlite3.Row | dict[str, Any],
    tenant_id: str | None = None,
) -> None:
    """Restore every flight field mutated by an analysis publication.

    This is the compensating transaction for a failure after
    :func:`complete_analysis` has installed new artifact pointers but before
    the Processing claim is finalized.
    """
    assignments = ", ".join(f"{column}=?" for column in _ANALYSIS_SNAPSHOT_COLUMNS)
    values = [snapshot[column] for column in _ANALYSIS_SNAPSHOT_COLUMNS]
    with connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE flights SET {assignments}, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            """,
            (*values, flight_id, tenant_id, tenant_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def save_timing_reference(
    flight_id: int,
    actual_takeoff_utc: str | None,
    reference_type: str | None,
    reference_utc: str | None,
    reference_waypoint: str | None = None,
    tenant_id: str | None = None,
) -> None:
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights SET
                actual_takeoff_utc=?,
                timing_reference_type=?,
                timing_reference_waypoint=?,
                timing_reference_utc=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (
                actual_takeoff_utc,
                reference_type,
                reference_waypoint,
                reference_utc,
                flight_id,
                tenant_id,
                tenant_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def claim_analysis(
    flight_id: int,
    tenant_id: str | None = None,
    *,
    expected_status: str | None = None,
) -> sqlite3.Row | None:
    """Atomically claim a flight and return its authoritative prior row.

    ``BEGIN IMMEDIATE`` makes the read-and-transition one ownership decision.
    A caller that acquired a stale HTTP snapshot therefore still receives the
    latest completed row before applying any timing or personal-note mutation.
    When ``expected_status`` is supplied, the same write transaction also acts
    as a compare-and-set guard for callers holding a potentially stale row.
    """
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        flight = conn.execute(
            '''
            SELECT * FROM flights
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (flight_id, tenant_id, tenant_id),
        ).fetchone()
        if flight is None:
            raise LookupError(f"Flight {flight_id} not found")
        if flight["status"] == "Processing":
            return None
        if expected_status is not None and flight["status"] != expected_status:
            return None
        conn.execute(
            '''
            UPDATE flights SET
                status='Processing',
                notes='Parsing Lido CFP and running ODSS engines.',
                last_error=NULL,
                analysis_failure_category=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (flight_id, tenant_id, tenant_id),
        )
        return flight


def begin_analysis(flight_id: int, tenant_id: str | None = None) -> bool:
    """Backward-compatible boolean wrapper around :func:`claim_analysis`."""
    return claim_analysis(flight_id, tenant_id) is not None


def complete_analysis(
    flight_id: int,
    result: dict[str, Any],
    tenant_id: str | None = None,
    *,
    release_claim: bool = True,
) -> None:
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights SET
                flight_number=COALESCE(NULLIF(?, ''), flight_number),
                flight_date=COALESCE(NULLIF(?, ''), flight_date),
                departure=COALESCE(NULLIF(?, ''), departure),
                destination=COALESCE(NULLIF(?, ''), destination),
                aircraft=COALESCE(NULLIF(?, ''), aircraft),
                registration=COALESCE(NULLIF(?, ''), registration),
                analysis_path=?, level1_report=?, level2_report=?,
                level3_json=?, level3_report=?,
                analysis_version=COALESCE(NULLIF(?, ''), analysis_version),
                report_refresh_state=?,
                report_refresh_error_type=?,
                report_refresh_updated_at=CURRENT_TIMESTAMP,
                status=CASE WHEN ? THEN 'Completed' ELSE 'Processing' END,
                notes=?, last_error=NULL, analysis_failure_category=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (
                result.get("flight_number", ""),
                result.get("flight_date", ""),
                result.get("departure", ""),
                result.get("destination", ""),
                result.get("aircraft", ""),
                result.get("registration", ""),
                result.get("analysis_path"),
                result.get("level1_report"),
                result.get("level2_report"),
                result.get("level3_json"),
                result.get("level3_report"),
                result.get("analysis_version", "0.6.0"),
                result.get("report_refresh_state", "current"),
                result.get("report_refresh_error_type"),
                int(release_claim),
                (
                    f"Analysed {result.get('page_count', 0)} pages; "
                    f"{result.get('finding_count', 0)} findings; "
                    f"{result.get('weather_records', 0)} weather records; "
                    f"{result.get('notam_records', 0)} pertinent NOTAM records."
                    + (
                        f" Calculated {result.get('timing_event_count', 0)} actual UTC events."
                        if result.get("timing_event_count")
                        else ""
                    )
                    + (
                        f" Included {result.get('personal_note_count', 0)} personal notes."
                        if result.get("personal_note_count")
                        else ""
                    )
                ),
                flight_id,
                tenant_id,
                tenant_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def set_report_refresh_state(
    flight_id: int,
    state: str,
    error_type: str | None = None,
    tenant_id: str | None = None,
) -> None:
    if state not in {"pending", "current", "failed"}:
        raise ValueError(f"Unsupported report refresh state: {state}")
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights SET
                report_refresh_state=?,
                report_refresh_error_type=?,
                report_refresh_updated_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            ''',
            (state, error_type, flight_id, tenant_id, tenant_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def attach_report(
    flight_id: int,
    level: int,
    report_path: str,
    tenant_id: str | None = None,
) -> None:
    column = "level1_report" if level == 1 else "level2_report"
    with connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE flights SET {column}=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND (? IS NULL OR tenant_id=?)
            """,
            (report_path, flight_id, tenant_id, tenant_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def get_or_create_policy_snapshot(
    *,
    tenant_id: str,
    analysis_id: str,
    snapshot: dict[str, Any],
) -> sqlite3.Row:
    snapshot_json = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
    with connect() as conn:
        owner = conn.execute(
            "SELECT 1 FROM flights WHERE analysis_id=? AND tenant_id=?",
            (analysis_id, tenant_id),
        ).fetchone()
        if owner is None:
            raise LookupError(f"Analysis {analysis_id} not found")
        existing = conn.execute(
            """
            SELECT * FROM policy_snapshots
            WHERE tenant_id=? AND analysis_id=?
            """,
            (tenant_id, analysis_id),
        ).fetchone()
        if existing:
            return existing
        conn.execute(
            """
            INSERT INTO policy_snapshots (
                id, tenant_id, analysis_id, snapshot_json, snapshot_sha256
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, tenant_id, analysis_id, snapshot_json, digest),
        )
        return conn.execute(
            """
            SELECT * FROM policy_snapshots
            WHERE tenant_id=? AND analysis_id=?
            """,
            (tenant_id, analysis_id),
        ).fetchone()


def get_policy_snapshot(tenant_id: str, analysis_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM policy_snapshots
            WHERE tenant_id=? AND analysis_id=?
            """,
            (tenant_id, analysis_id),
        ).fetchone()


def list_level3_answers(tenant_id: str, analysis_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT * FROM level3_answers
                WHERE tenant_id=? AND analysis_id=?
                ORDER BY question_id
                """,
                (tenant_id, analysis_id),
            )
        )


def save_level3_answer(
    *,
    tenant_id: str,
    analysis_id: str,
    question_id: str,
    answer_text: str | None,
    answer_state: str,
    answered_by: str,
) -> None:
    with connect() as conn:
        owner = conn.execute(
            "SELECT 1 FROM flights WHERE analysis_id=? AND tenant_id=?",
            (analysis_id, tenant_id),
        ).fetchone()
        if owner is None:
            raise LookupError(f"Analysis {analysis_id} not found")
        conn.execute(
            """
            INSERT INTO level3_answers (
                tenant_id, analysis_id, question_id, answer_text,
                answer_state, answered_by, answered_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id, analysis_id, question_id) DO UPDATE SET
                answer_text=excluded.answer_text,
                answer_state=excluded.answer_state,
                answered_by=excluded.answered_by,
                answered_at=CURRENT_TIMESTAMP
            """,
            (
                tenant_id,
                analysis_id,
                question_id,
                answer_text,
                answer_state,
                answered_by,
            ),
        )


def record_audit_event(
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> str:
    event_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (
                id, tenant_id, actor_id, action,
                resource_type, resource_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                tenant_id,
                actor_id,
                action,
                resource_type,
                resource_id,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
            ),
        )
    return event_id
