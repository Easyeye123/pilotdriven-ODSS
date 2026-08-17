from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.briefing import _notice_kind
from app.odss.combined_brief import (
    _airport_table_required_height,
    _kv_card_required_height,
    render_combined_briefing,
)
from app.odss.engines import _notam_operational_summary
from app.odss.pilot_briefing import notam_pertinence


def test_overview_uses_operating_window_weather_primary(tmp_path):
    flight = sample_flight()
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    findings.append({
        "engine": "weather",
        "severity": "warning",
        "title": "Destination weather - WSSS",
        "summary": "This fallback summary must not win.",
        "details": [],
        "data": {
            "location": "WSSS",
            "window_status_text": "Forecast overlaps ETA plus or minus one hour.",
            "timing": "Arrival window 2140Z to 2340Z.",
        },
    })
    output = tmp_path / "weather-overview.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        first_page = document[0].get_text()
    assert "Forecast overlaps ETA plus or minus one hour." in first_page
    assert "Weather review on the hazard assessment page." not in first_page


def test_sparse_gate_cards_use_content_height_instead_of_stretching_to_footer():
    rows = [
        ("MEL/CDL", "MEL 25-20-50A"),
        ("DEP", "20C"),
        ("DEST", "03"),
    ]

    height = _kv_card_required_height(rows, 240)

    assert 90 <= height < 180


def test_obstacle_surface_notice_does_not_become_a_runway_restriction():
    text = (
        "AD OBSTACLES AMD. UNMARKED FLOODLIGHT POLES INFRINGING "
        "RWY 06/24 TRANSITIONAL SFC."
    )

    _, kind = notam_pertinence(text)
    summary = _notam_operational_summary(text, kind, "destination")

    assert kind == "obstacle"
    assert _notice_kind(text) == "Obstacle"
    assert "not reported closed by this notice" in summary.lower()
    assert "restriction applies" not in summary.lower()


def test_sparse_airport_tables_use_content_height_instead_of_stretching_to_footer():
    rows = [
        ("RWY 03", "PLANNED", "Planned CFP basis."),
        ("Runway / approach", "CRITICAL", "ILS RWY 24 unavailable."),
        ("Obstacle", "ACTIVE", "Floodlight poles affect the airport environment."),
    ]

    height = _airport_table_required_height(rows, 620)

    assert 120 <= height < 240
