from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}

REFERENCE_LIBRARY_METADATA = {
    "version": "sample-2026-07",
    "status": "manual-review",
    "notice": (
        "Candidate MEL and communications mappings are regression samples only. "
        "Verify every match against the current approved operator source."
    ),
}

OPERATIONAL_KEYWORDS: dict[str, int] = {
    "RWY": 5, "RUNWAY": 5, "ILS": 5, "LOC": 4, "RNP": 4, "VOR": 3,
    "NDB": 2, "CLSD": 5, "CLOSED": 5, "U/S": 5, "NOT AVBL": 5,
    "SUSPENDED": 5, "MINIMA": 4, "OCA": 4, "OCH": 4, "RVR": 3,
    "TWY": 2, "TAXIWAY": 2, "FUEL": 3, "RFFS": 4, "FIRE FIGHTING": 4,
    "BOBCAT": 5, "TIBA": 5, "GNSS": 4, "AIRSPACE": 3, "TSA": 3,
    "TRA": 3, "DANGER": 3, "RESTRICTED": 3, "MILITARY": 3, "OBST": 2,
    "CRANE": 2, "STOP BAR": 3,
}

MEL_REFERENCES: dict[str, dict[str, Any]] = {
    "30-81-01A": {
        "description": "Ice detection system inoperative",
        "repair_interval": "D", "installed": 1, "required": 0,
        "placard_required": False, "operational_procedure_required": True,
        "terms": [
            "If icing conditions are expected in flight, use the approved engine and wing anti-ice operational procedure.",
            "Confirm interaction with take-off performance assumptions when anti-ice is required.",
        ],
    },
    "21-26-08A": {
        "description": "Ventilation avionics filter clogged",
        "repair_interval": "A - 30 consecutive calendar days", "installed": 2,
        "required": 0, "placard_required": False,
        "terms": ["Confirm DDL opening date and exact expiry."],
    },
    "25-20-50A": {
        "description": "Non-essential equipment / VCRU 1 inoperative",
        "repair_interval": "D", "installed": None, "required": 0,
        "placard_required": True,
        "terms": ["Company dry-ice mitigation is separate from the generic MEL/NEF entry."],
    },
    "46-30-01A": {
        "description": "OIS maintenance application access unavailable",
        "repair_interval": "D", "installed": None, "required": 0,
        "placard_required": False, "operational_procedure_required": True,
        "terms": ["Alternate procedures must be established and used."],
    },
}

COMMUNICATION_RULES = [
    {"boundary": "VOMF", "lead": 10, "agency": "Chennai ATS/FIS", "action": "Forward FIR-boundary estimate"},
    {"boundary": "OPKR", "lead": 15, "agency": "Karachi ACC", "action": "Establish two-way contact"},
    {"boundary": "OPLR", "lead": 15, "agency": "Lahore ACC", "action": "Ensure contact/coordination"},
    {"boundary": "OAKX", "lead": 10, "agency": "Kabul TIBA", "action": "Initial TIBA broadcast", "frequency": "125.2", "notes": "Repeat every five minutes within Kabul FIR."},
    {"boundary": "UTAV", "lead": 10, "agency": "Turkmenabat Control", "action": "Establish next-FIR contact", "frequency": "134.5", "backup": "128.5"},
]

ENGINE_ORDER = [
    "page1", "bobcat", "mel", "cdl", "cddl", "performance", "weather", "vaa", "notam",
    "communications", "actual_timing", "terrain", "vws", "depressurisation",
    "edto", "timeline", "qa",
]


def actm_minutes(value: str | int) -> int:
    if isinstance(value, int):
        return value
    hours, minutes = value.replace(":", ".").split(".", 1)
    return int(hours) * 60 + int(minutes)


def format_actm(minutes: int | None) -> str:
    if minutes is None:
        return "--.--"
    return f"{minutes // 60:02d}.{minutes % 60:02d}"


def format_kg(value: int | None) -> str:
    return "not available" if value is None else f"{value:,} kg"


def date_ddmmmyy(value: str) -> datetime:
    import re
    match = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2})", value.upper())
    if not match:
        raise ValueError(f"Unsupported Lido date: {value}")
    return datetime(2000 + int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)), tzinfo=timezone.utc)


def utc_on_date(day: datetime, hhmm: str) -> datetime:
    return day.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0, microsecond=0)
