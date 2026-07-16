from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .odss.briefing import build_briefing_view
from .odss.constants import ENGINE_ORDER, actm_minutes, format_actm
from .odss.engines import analyse
from .odss.parser import extract_pages, parse_lido
from .odss.reporting import render_pdf
from .odss.timing import build_timing_view, timing_finding
from .personal_notes import serialise_personal_note


def infer_metadata(filename: str) -> dict[str, str]:
    stem = Path(filename).stem.upper()
    result = {
        key: ""
        for key in (
            "flight_number", "flight_date", "departure",
            "destination", "aircraft", "registration",
        )
    }
    match = re.search(r"\b(SQ|SIA)[-_ ]?(\d{2,4})\b", stem)
    if match:
        result["flight_number"] = f"SQ{match.group(2)}"
    return result


def run_odss_analysis(
    file_path: Path,
    result_dir: Path,
    report_dir: Path,
    flight_id: int,
    actual_takeoff_utc: str | None = None,
    timing_reference: dict[str, Any] | None = None,
    personal_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pages = extract_pages(file_path)
    flight = parse_lido(pages, file_path.name)
    flight["flight_number"] = flight["flight_number"].replace("SIA", "SQ", 1)
    flight["personal_notes"] = [
        serialise_personal_note(dict(note))
        for note in (personal_notes or [])
    ]
    if actual_takeoff_utc:
        flight["actual_takeoff_utc"] = actual_takeoff_utc
        flight["timing_reference"] = timing_reference or {
            "reference_type": "takeoff",
            "reference_utc": actual_takeoff_utc,
            "reference_waypoint": None,
            "reference_actm_minutes": 0,
            "actual_takeoff_utc": actual_takeoff_utc,
        }

    findings, warnings = analyse(flight)
    timing_view = None
    if actual_takeoff_utc:
        timing_view = build_timing_view(
            flight,
            findings,
            actual_takeoff_utc,
            flight.get("timing_reference"),
        )
        findings.append(timing_finding(timing_view))

    briefing_view = build_briefing_view(
        flight,
        findings,
        warnings,
        timing_view,
    )

    grouped_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped_raw[finding["engine"]].append(finding)
    grouped = {
        engine: grouped_raw[engine]
        for engine in ENGINE_ORDER
        if grouped_raw.get(engine)
    }
    for engine, engine_findings in grouped_raw.items():
        if engine not in grouped:
            grouped[engine] = engine_findings

    result_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    result_path = result_dir / f"flight_{flight_id}_{run_id}_analysis.json"
    level1_path = report_dir / f"flight_{flight_id}_{run_id}_level_1.pdf"
    level2_path = report_dir / f"flight_{flight_id}_{run_id}_level_2.pdf"
    payload = {
        "schema_version": "0.5.0",
        "flight": flight,
        "findings": findings,
        "view": {
            "page_count": len(pages),
            "finding_count": len(findings),
            "notam_finding_count": sum(item["engine"] == "notam" for item in findings),
            "personal_note_count": len(flight["personal_notes"]),
            "grouped": grouped,
            "warnings": warnings,
            "timing": timing_view,
            "briefing": briefing_view,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    result_temp = result_path.with_suffix(".tmp")
    level1_temp = level1_path.with_suffix(".tmp")
    level2_temp = level2_path.with_suffix(".tmp")
    published = False
    try:
        result_temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        render_pdf(flight, findings, warnings, 1, level1_temp)
        render_pdf(flight, findings, warnings, 2, level2_temp)
        result_temp.replace(result_path)
        level1_temp.replace(level1_path)
        level2_temp.replace(level2_path)
        published = True
    finally:
        result_temp.unlink(missing_ok=True)
        level1_temp.unlink(missing_ok=True)
        level2_temp.unlink(missing_ok=True)
        if not published:
            result_path.unlink(missing_ok=True)
            level1_path.unlink(missing_ok=True)
            level2_path.unlink(missing_ok=True)
    return {
        "status": "Completed",
        "analysis_path": str(result_path),
        "level1_report": str(level1_path),
        "level2_report": str(level2_path),
        "flight_number": flight["flight_number"],
        "flight_date": flight["flight_date"],
        "departure": flight["departure"],
        "destination": flight["destination"],
        "aircraft": flight["aircraft_type"],
        "registration": flight["registration"],
        "page_count": len(pages),
        "finding_count": len(findings),
        "weather_records": len(flight["weather"]),
        "notam_records": sum(item["engine"] == "notam" for item in findings),
        "timing_event_count": timing_view["event_count"] if timing_view else 0,
        "personal_note_count": len(flight["personal_notes"]),
        "warnings": warnings,
    }


def load_analysis(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    analysis_path = Path(path)
    if not analysis_path.exists():
        return None
    try:
        return json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# Compatibility with the v0.1 dashboard while files are updated in stages.
def run_placeholder_analysis(file_path: Path) -> dict[str, Any]:
    return {
        "status": "ODSS core installed; update app.main to v0.5.0",
        "file_size_bytes": file_path.stat().st_size,
        "modules": ENGINE_ORDER,
    }


__all__ = [
    "actm_minutes",
    "format_actm",
    "infer_metadata",
    "load_analysis",
    "run_odss_analysis",
    "run_placeholder_analysis",
]
