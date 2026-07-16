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


@pytest.mark.parametrize(
    ("level", "title"),
    [
        (1, "SQ304 WSSS-EBBR"),
        (2, "SQ304 Expanded Operational Analysis"),
    ],
)
def test_multipage_reports_repeat_title_footer_and_physical_page_number(
    tmp_path: Path,
    level: int,
    title: str,
) -> None:
    flight = {
        "flight_number": "SQ304",
        "departure": "WSSS",
        "destination": "EBBR",
        "flight_date": "11JUL26",
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_landing_weight_kg": 175802,
            "planned_takeoff_weight_kg": 245529,
        },
    }
    path = tmp_path / f"level_{level}.pdf"

    render_pdf(flight, [_weather(index) for index in range(24)], [], level, path)

    reader = PdfReader(path)
    assert len(reader.pages) > 1
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        assert title in text
        assert "Decision support only - approved documents" in text
        assert f"Page {page_number}" in text

    first_page_text = reader.pages[0].extract_text() or ""
    assert "PZFW" in first_page_text
    assert "166,486 kg" in first_page_text
    assert "PLDW" in first_page_text
    assert "175,802 kg" in first_page_text
    assert "PTOW" in first_page_text
    assert "245,529 kg" in first_page_text


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
    assert rendered_identities == ["SQ304", "SQ304"]
