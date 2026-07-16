from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .odss.constants import ENGINE_ORDER, actm_minutes, format_actm
from .odss.engines import analyse
from .odss.parser import extract_pages, parse_lido
from .odss.reporting import render_pdf


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
) -> dict[str, Any]:
    pages = extract_pages(file_path)
    flight = parse_lido(pages, file_path.name)
    flight["flight_number"] = flight["flight_number"].replace("SIA", "SQ", 1)
    findings, warnings = analyse(flight)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[finding["engine"]].append(finding)

    result_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    result_path = result_dir / f"flight_{flight_id}_{run_id}_analysis.json"
    level1_path = report_dir / f"flight_{flight_id}_{run_id}_level_1.pdf"
    level2_path = report_dir / f"flight_{flight_id}_{run_id}_level_2.pdf"
    payload = {
        "schema_version": "0.2.1",
        "flight": flight,
        "findings": findings,
        "view": {
            "page_count": len(pages),
            "finding_count": len(findings),
            "notam_finding_count": sum(item["engine"] == "notam" for item in findings),
            "grouped": dict(grouped),
            "warnings": warnings,
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
        "status": "ODSS core installed; update app.main to v0.2.0",
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
