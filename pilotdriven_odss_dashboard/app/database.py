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
    level1_report TEXT,
    level2_report TEXT,
    notes TEXT
);
'''

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)

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

def update_status(flight_id: int, status: str, notes: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE flights SET status=?, notes=COALESCE(?, notes), updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, notes, flight_id),
        )

def attach_report(flight_id: int, level: int, report_path: str) -> None:
    column = "level1_report" if level == 1 else "level2_report"
    with connect() as conn:
        conn.execute(
            f"UPDATE flights SET {column}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (report_path, flight_id),
        )
