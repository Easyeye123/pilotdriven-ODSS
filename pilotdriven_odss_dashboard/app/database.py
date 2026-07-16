from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "odss.db"

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
    notes TEXT,
    last_error TEXT,
    actual_takeoff_utc TEXT,
    timing_reference_type TEXT,
    timing_reference_waypoint TEXT,
    timing_reference_utc TEXT
);
'''


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(flights)")}
    additions = {
        "analysis_path": "TEXT",
        "last_error": "TEXT",
        "actual_takeoff_utc": "TEXT",
        "timing_reference_type": "TEXT",
        "timing_reference_waypoint": "TEXT",
        "timing_reference_utc": "TEXT",
    }
    for column, sql_type in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE flights ADD COLUMN {column} {sql_type}")


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
                analysis_path=NULL,
                level1_report=NULL,
                level2_report=NULL,
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
                status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        return int(cur.lastrowid)


def list_flights() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM flights ORDER BY id DESC"))


def get_flight(flight_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()


def update_status(
    flight_id: int,
    status: str,
    notes: str | None = None,
    last_error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            '''
            UPDATE flights
            SET status=?, notes=COALESCE(?, notes), last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            ''',
            (status, notes, last_error, flight_id),
        )


def save_timing_reference(
    flight_id: int,
    actual_takeoff_utc: str,
    reference_type: str,
    reference_utc: str,
    reference_waypoint: str | None = None,
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
            WHERE id=?
            ''',
            (
                actual_takeoff_utc,
                reference_type,
                reference_waypoint,
                reference_utc,
                flight_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")


def begin_analysis(flight_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            '''
            UPDATE flights SET
                status='Processing',
                notes='Parsing Lido CFP and running ODSS engines.',
                last_error=NULL,
                analysis_path=NULL,
                level1_report=NULL,
                level2_report=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status != 'Processing'
            ''',
            (flight_id,),
        )
        if cursor.rowcount == 1:
            return True
        if conn.execute("SELECT 1 FROM flights WHERE id=?", (flight_id,)).fetchone() is None:
            raise LookupError(f"Flight {flight_id} not found")
        return False


def complete_analysis(flight_id: int, result: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            '''
            UPDATE flights SET
                flight_number=COALESCE(NULLIF(?, ''), flight_number),
                flight_date=COALESCE(NULLIF(?, ''), flight_date),
                departure=COALESCE(NULLIF(?, ''), departure),
                destination=COALESCE(NULLIF(?, ''), destination),
                aircraft=COALESCE(NULLIF(?, ''), aircraft),
                registration=COALESCE(NULLIF(?, ''), registration),
                analysis_path=?, level1_report=?, level2_report=?,
                status='Completed', notes=?, last_error=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
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
                ),
                flight_id,
            ),
        )


def attach_report(flight_id: int, level: int, report_path: str) -> None:
    column = "level1_report" if level == 1 else "level2_report"
    with connect() as conn:
        cursor = conn.execute(
            f"UPDATE flights SET {column}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (report_path, flight_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Flight {flight_id} not found")
