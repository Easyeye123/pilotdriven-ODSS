from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .odss.briefing import build_briefing_view
from .odss.constants import (
    ENGINE_ORDER,
    REFERENCE_LIBRARY_METADATA,
    actm_minutes,
    format_actm,
)
from .odss.engines import analyse
from .odss.finding_ids import assign_finding_ids
from .odss.parser import extract_pages, parse_lido
from .odss.opmet import enrich_official_opmet
from .odss.reporting import render_pdf
from .odss.sigmet import assess_significant_weather
from .odss.tropical_cyclone import assess_tropical_cyclone
from .odss.tc_track import assess_tropical_cyclone_track
from .odss.vaa import assess_volcanic_ash
from .odss_map_v06.config import MapSettings
from .odss_map_v06.geojson import build_map_contract
from .odss.timing import build_timing_view, timing_finding
from .personal_notes import serialise_personal_note


REPORT_REFRESH_WARNING = (
    "The timing update is active, but the Level 1 and Level 2 reports could "
    "not be refreshed. Retry report generation before use."
)


class CfpParseRejectedError(ValueError):
    """The uploaded PDF is readable but not a supported, complete Lido CFP."""


class ReportRenderingFailure(RuntimeError):
    """A completed deterministic analysis whose PDF publication failed.

    The typed boundary lets timing mutations remain durable without treating a
    parser, engine, grounding, or JSON-publication failure as a recoverable PDF
    problem. Partial PDFs are never exposed.
    """

    def __init__(self, result: dict[str, Any], error_type: str):
        self.result = result
        self.error_type = error_type
        super().__init__(REPORT_REFRESH_WARNING)


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
    surface_overlays: list[dict[str, Any]] | None = None,
    weather_window_preference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        pages = extract_pages(file_path)
        flight = parse_lido(pages, file_path.name)
    except ValueError as exc:
        # Keep parser rejection distinct from rendering, storage and governed
        # source failures so an idempotent retry is never permanently poisoned
        # by a transient infrastructure problem.
        raise CfpParseRejectedError(str(exc)) from exc
    flight["flight_number"] = flight["flight_number"].replace("SIA", "SQ", 1)
    flight["personal_notes"] = [
        serialise_personal_note(dict(note))
        for note in (personal_notes or [])
    ]
    flight["surface_overlays"] = [
        dict(overlay)
        for overlay in (surface_overlays or [])
    ]
    if weather_window_preference is not None:
        flight["weather_window_preference"] = dict(weather_window_preference)
    if actual_takeoff_utc:
        flight["actual_takeoff_utc"] = actual_takeoff_utc
        flight["timing_reference"] = timing_reference or {
            "reference_type": "takeoff",
            "reference_utc": actual_takeoff_utc,
            "reference_waypoint": None,
            "reference_actm_minutes": 0,
            "actual_takeoff_utc": actual_takeoff_utc,
        }

    enrich_official_opmet(flight)
    assess_significant_weather(flight)
    assess_volcanic_ash(flight, pages)
    tropical_cyclone_review = assess_tropical_cyclone(flight, pages)
    tropical_cyclone_review["track_context"] = assess_tropical_cyclone_track(flight)
    findings, warnings = analyse(flight)
    timing_view = None
    if actual_takeoff_utc:
        timing_view = build_timing_view(
            flight,
            findings,
            actual_takeoff_utc,
            flight.get("timing_reference"),
        )
        flight["timing_view"] = timing_view
        findings.append(timing_finding(timing_view))
    assign_finding_ids(findings)

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
    map_contract = None
    try:
        map_contract = build_map_contract(flight, findings, MapSettings.from_env())
    except ValueError as exc:
        warnings.append(f"Map contract unavailable: {exc}")

    payload = {
        "schema_version": "0.6.1",
        "flight": flight,
        "findings": findings,
        "reference_library": REFERENCE_LIBRARY_METADATA,
        "map_contract": map_contract.public_dict() if map_contract else None,
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
    result = {
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
        "sigmet_status": (flight.get("sigmet_review") or {}).get("status"),
        "vaa_status": (flight.get("vaa_review") or {}).get("status"),
        "tropical_cyclone_status": (flight.get("tropical_cyclone_review") or {}).get("status"),
        "warnings": warnings,
        "analysis_version": "0.6.1",
        "report_refresh_state": "current",
        "report_refresh_error_type": None,
    }
    result_temp = result_path.with_suffix(".tmp")
    level1_temp = level1_path.with_suffix(".tmp")
    level2_temp = level2_path.with_suffix(".tmp")
    analysis_published = False
    reports_published = False
    try:
        try:
            render_pdf(flight, findings, warnings, 1, level1_temp)
            render_pdf(flight, findings, warnings, 2, level2_temp)
        except Exception as exc:
            # A renderer may have registered report-only page targets on the
            # in-memory flight. They are not valid unless both PDFs publish.
            flight.pop("depressurisation_profile_charts", None)
            if REPORT_REFRESH_WARNING not in warnings:
                warnings.append(REPORT_REFRESH_WARNING)
            error_type = type(exc).__name__
            payload["view"]["report_refresh"] = {
                "state": "failed",
                "reports_current": False,
                "warning": REPORT_REFRESH_WARNING,
            }
            result["report_refresh_state"] = "failed"
            result["report_refresh_error_type"] = error_type
            result_temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            result_temp.replace(result_path)
            analysis_published = True
            raise ReportRenderingFailure(result, error_type) from exc

        payload["view"]["report_refresh"] = {
            "state": "current",
            "reports_current": True,
            "warning": None,
        }
        # Level 2 rendering registers the exact governed source-chart page on
        # the flight artifact contract. Serialise only after both reports
        # complete so the API never loses that target and the client never has
        # to reconstruct page numbers.
        result_temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result_temp.replace(result_path)
        analysis_published = True
        level1_temp.replace(level1_path)
        level2_temp.replace(level2_path)
        reports_published = True
    finally:
        result_temp.unlink(missing_ok=True)
        level1_temp.unlink(missing_ok=True)
        level2_temp.unlink(missing_ok=True)
        if not analysis_published:
            result_path.unlink(missing_ok=True)
        if not reports_published:
            level1_path.unlink(missing_ok=True)
            level2_path.unlink(missing_ok=True)
    return result


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
        "status": "ODSS core installed; update app.main to v0.6.1",
        "file_size_bytes": file_path.stat().st_size,
        "modules": ENGINE_ORDER,
    }


__all__ = [
    "CfpParseRejectedError",
    "REPORT_REFRESH_WARNING",
    "ReportRenderingFailure",
    "actm_minutes",
    "format_actm",
    "infer_metadata",
    "load_analysis",
    "run_odss_analysis",
    "run_placeholder_analysis",
]
