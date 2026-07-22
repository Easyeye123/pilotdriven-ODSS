from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import pytest
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import analysis
from app.odss.reporting import render_pdf, report_sections


def _notam(
    notam_id: str,
    role: str,
    severity: str = "warning",
    priority_score: int = 1,
    schedule: str | None = None,
) -> dict[str, Any]:
    details = []
    if schedule:
        details.append(f"Schedule: {schedule}.")
    details.extend([
        "Operating window 2026-07-11T09:30:00+00:00 to 2026-07-11T11:30:00+00:00.",
        f"Location WSSS; category {role}.",
        "Validity 2026-07-01T00:00:00+00:00 to 2026-07-31T23:59:00+00:00.",
    ])
    return {
        "engine": "notam",
        "severity": severity,
        "title": f"{role.title()} NOTAM {notam_id}",
        "summary": f"Operational finding for {role}.",
        "details": details,
        "data": {
            "role": role,
            "priority_score": priority_score,
            "schedule": schedule,
        },
    }


def _weather(index: int) -> dict[str, Any]:
    text = (
        "TAF WSSS 161100Z 1612/1718 18010KT 9999 FEW020 SCT040 "
        "TEMPO 1612/1618 4000 TSRA BKN015CB BECMG 1700/1702 22015G25KT "
    ) * 5
    return {
        "engine": "weather",
        "severity": "warning",
        "title": f"Weather record {index:02d}",
        "summary": text,
        "details": ["Record type: TAF."],
        "data": {},
    }


def _flight() -> dict[str, Any]:
    return {
        "flight_number": "SQ304",
        "departure": "WSSS",
        "destination": "EBBR",
        "departure_runway": "20C",
        "destination_runway": "07L",
        "flight_date": "11JUL26",
        "scheduled_departure_utc": "2026-07-11T10:30:00+00:00",
        "scheduled_arrival_utc": "2026-07-11T22:00:00+00:00",
        "aircraft_type": "A350-941",
        "registration": "9V-SMG",
        "ground_distance_nm": 5933,
        "planned_level_profile": "SIN/350/POINT/390/BRU/410",
        "route_waypoints": [
            {"name": "WSSS", "actm_minutes": 0, "latitude": 1.36, "longitude": 103.99, "fir_boundary": None, "airway_in": None, "msa_hundreds_ft": 4, "vws": 1},
            {"name": "-VOMF", "actm_minutes": 120, "latitude": 13.93, "longitude": 92.33, "fir_boundary": "VOMF", "airway_in": "L759", "msa_hundreds_ft": None, "vws": 2},
            {"name": "POINT", "actm_minutes": 360, "latitude": 31.40, "longitude": 69.00, "fir_boundary": None, "airway_in": "L750", "msa_hundreds_ft": 166, "vws": 5},
            {"name": "EBBR", "actm_minutes": 690, "latitude": 50.90, "longitude": 4.48, "fir_boundary": None, "airway_in": "DCT", "msa_hundreds_ft": 5, "vws": 2},
        ],
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_landing_weight_kg": 175802,
            "planned_takeoff_weight_kg": 245529,
        },
        "fuel": {
            "fuel_in_tanks_kg": 79643,
            "trip_fuel_kg": 69727,
            "planned_destination_fuel_kg": 9316,
        },
        "alternates": [{"airport": "EDDL", "runway": "05L", "approach": "CAT1DME"}],
        "edto": {"entry_actm_minutes": 120, "exit_actm_minutes": 150, "etp_actm_minutes": [135], "airports": []},
        "weather": [],
        "notams": [],
        "personal_notes": [],
    }


def test_level1_notams_preserve_critical_roles_schedule_and_omission_count() -> None:
    findings = [
        _notam(f"D{index:02d}/26", "departure", priority_score=30 - index)
        for index in range(12)
    ]
    findings.extend([
        _notam(
            "A1234/26",
            "destination",
            severity="critical",
            priority_score=100,
            schedule="DLY 0200-0400",
        ),
        _notam("A2000/26", "destination alternate", priority_score=20),
        _notam("A3000/26", "EDTO", priority_score=10),
    ])
    findings.extend([
        _notam(f"I{index:02d}/26", "informational", priority_score=index)
        for index in range(10)
    ])

    section = report_sections(findings, 1)[0]
    text = "\n".join(section["lines"])

    assert section["severity"] == "critical"
    assert "Destination NOTAM A1234/26" in text
    assert "- Schedule: DLY 0200-0400." in text
    assert "Departure NOTAM" in text
    assert "Destination Alternate NOTAM A2000/26" in text
    assert "Edto NOTAM A3000/26" in text
    assert "9 lower-priority active or review NOTAM findings omitted; see Level 2." in text


def test_level1_is_two_page_readable_portrait_brief(tmp_path: Path) -> None:
    path = tmp_path / "level_1.pdf"
    findings = [
        _weather(1),
        _notam("A1000/26", "departure"),
        {
            "engine": "depressurisation",
            "severity": "unknown",
            "title": "High terrain detected but no profile matched",
            "summary": "Manual chart-index review is required.",
            "details": [],
            "data": {},
        },
        *[
            {
                "engine": "terrain",
                "severity": "warning",
                "title": f"High-MSA event {index}",
                "summary": "Review terrain escape planning.",
                "details": [],
                "data": {},
            }
            for index in range(1, 9)
        ],
    ]
    render_pdf(_flight(), findings, [], 1, path)

    reader = PdfReader(path)
    assert len(reader.pages) == 2
    first = reader.pages[0].extract_text() or ""
    second = reader.pages[1].extract_text() or ""

    assert "PILOTDRIVEN" in first
    assert float(reader.pages[0].mediabox.width) < float(reader.pages[0].mediabox.height)
    assert "PZFW" in first and "166,486 kg" in first
    assert "PLDW" in first and "175,802 kg" in first
    assert "PTOW" in first and "245,529 kg" in first
    assert "1  MEL / CDL / CDDL" in first
    assert "3  DEPARTURE AIRPORT" in first
    assert "4  DESTINATION AIRPORT / ALTERNATES / NOTAM" in first
    assert "5  FIR / COMMUNICATIONS" in second
    assert "6  TERRAIN / VWS / DEPRESSURISATION" in second
    assert "High terrain detected but no profile matched" in second
    assert "Manual chart-index review is required" in second
    assert "8  ACTM / CALCULATED UTC TIMELINE" in second


def test_level2_begins_with_visual_cover_and_repeats_detail_header(tmp_path: Path) -> None:
    path = tmp_path / "level_2.pdf"
    render_pdf(_flight(), [_weather(index) for index in range(24)], [], 2, path)

    reader = PdfReader(path)
    assert len(reader.pages) > 2
    first = reader.pages[0].extract_text() or ""
    second = reader.pages[1].extract_text() or ""

    assert "PILOTDRIVEN" in first
    assert "PZFW" in first and "166,486 kg" in first
    assert "SQ304 Expanded Operational Analysis" in second
    assert "Decision support only - approved documents" in second
    assert "Page 2" in second


def test_run_analysis_normalizes_identity_before_json_and_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    flight = {
        "flight_number": "SIA304",
        "flight_date": "11JUL26",
        "departure": "WSSS",
        "destination": "EBBR",
        "aircraft_type": "A350-941",
        "registration": "9V-SMG",
        "weather": [],
        "notams": [],
    }
    rendered_identities = []

    monkeypatch.setattr(analysis, "extract_pages", lambda path: ["CFP"])
    monkeypatch.setattr(analysis, "parse_lido", lambda pages, name: dict(flight))
    monkeypatch.setattr(analysis, "analyse", lambda parsed: ([], []))

    def capture_render(
        parsed: dict[str, Any],
        findings: list[dict[str, Any]],
        warnings: list[str],
        level: int,
        path: Path,
    ) -> None:
        rendered_identities.append(parsed["flight_number"])
        path.write_bytes(b"pdf")

    monkeypatch.setattr(analysis, "render_pdf", capture_render)

    result = analysis.run_odss_analysis(
        tmp_path / "source.pdf",
        tmp_path / "results",
        tmp_path / "reports",
        7,
    )
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))

    assert result["flight_number"] == "SQ304"
    assert payload["flight"]["flight_number"] == "SQ304"
    assert payload["view"]["briefing"]["route_label"] == "WSSS → EBBR"
    assert rendered_identities == ["SQ304", "SQ304"]
