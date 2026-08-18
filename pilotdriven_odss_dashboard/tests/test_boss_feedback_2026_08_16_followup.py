from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.briefing import _notice_kind
from app.odss.combined_brief import (
    _airport_table_required_height,
    _crop_panel_required_height,
    _kv_card_required_height,
    _terrain_profile_width,
    _terrain_table_height,
    _time_gate_card_layout,
    render_combined_briefing,
)
from app.odss.engines import _notam_operational_summary
from app.odss.pilot_briefing import notam_pertinence
from app.odss.report_quality import validate_combined_briefing_pdf


def _window_weather_finding() -> dict:
    return {
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
    }


def test_overview_prefers_raw_bulletins_on_airport_cards(tmp_path):
    """18 Aug instruction: the dep/dest cards print the actual METAR and TAF
    from the CFP; synthesised window prose only appears when no bulletin is
    held."""
    flight = sample_flight()
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    findings.append(_window_weather_finding())
    output = tmp_path / "weather-overview.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        first_page = document[0].get_text()
    assert "METAR SA 160630 17007KT" in first_page.replace("\n", " ")
    assert "Forecast overlaps ETA plus or minus one hour." not in first_page


def test_overview_falls_back_to_operating_window_weather_primary(tmp_path):
    flight = sample_flight()
    flight["weather"] = []
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    findings.append(_window_weather_finding())
    output = tmp_path / "weather-overview-fallback.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        first_page = document[0].get_text()
    assert "Forecast overlaps ETA plus or minus one hour." in first_page
    assert "Weather review on the hazard assessment page." not in first_page


def test_combined_briefing_uses_the_combined_publication_contract(tmp_path):
    flight = sample_flight()
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "combined-contract.pdf"

    render_combined_briefing(flight, findings, [], output)

    result = validate_combined_briefing_pdf(output)
    assert result["valid"] is True
    assert result["page_count"] == 9
    assert result["violations"] == []


def test_sparse_gate_cards_use_content_height_instead_of_stretching_to_footer():
    rows = [
        ("MEL/CDL", "MEL 25-20-50A"),
        ("DEP", "20C"),
        ("DEST", "03"),
    ]

    height = _kv_card_required_height(rows, 240)

    assert 90 <= height < 180


def test_authoritative_source_card_height_tracks_crop_content_with_hard_bounds():
    short_wide_crop = {"width": 1672, "height": 417}
    tall_crop = {"width": 800, "height": 2400}

    short_height = _crop_panel_required_height(short_wide_crop, 789.89, 364)
    tall_height = _crop_panel_required_height(tall_crop, 789.89, 240)

    assert 195 <= short_height <= 210
    assert tall_height == 240
    assert _crop_panel_required_height(None, 789.89, 364) == 72


def test_short_authoritative_source_crop_does_not_stretch_card_to_footer(tmp_path):
    source = tmp_path / "short-deferred-source.pdf"
    with fitz.open() as source_document:
        page = source_document.new_page(width=595, height=842)
        page.insert_text((50, 80), "ATTN ALL CONCERN", fontsize=10, fontname="cour")
        page.insert_text((50, 96), "MEL 25-20-50A NON-ESSENTIAL EQUIPMENT", fontsize=10, fontname="cour")
        page.insert_text((50, 112), "COMPANY REMARK REVIEW GOVERNED SOURCE", fontsize=10, fontname="cour")
        page.insert_text((50, 138), "RTE NO WSSS YPPH", fontsize=10, fontname="cour")
        source_document.save(source)

    flight = sample_flight()
    flight["deferred_items"] = [{
        "item_type": "MEL",
        "reference": "25-20-50A",
        "description": "Non-essential equipment and furnishings",
        "company_remark": "Review the current governed item.",
    }]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "responsive-source-card.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        output,
        source_pdf_path=str(source),
    )

    with fitz.open(output) as document:
        mel_page = document[4]
        title_box = mel_page.search_for("CROPPED CFP DECLARATION - NOT THE APPROVED REMEDY")[0]
        enclosing_panels = [
            drawing["rect"]
            for drawing in mel_page.get_drawings()
            if drawing["type"] == "fs"
            and drawing["rect"].width > 700
            and abs(drawing["rect"].x0 - 26) < 0.1
            and drawing["rect"].y0 <= title_box.y0
            and drawing["rect"].y1 >= title_box.y1
        ]

        assert len(enclosing_panels) == 1
        assert 90 <= enclosing_panels[0].height < 180
        assert mel_page.get_images(full=True)
        assert abs(mel_page.rect.width - 841.89) < 0.1
        assert abs(mel_page.rect.height - 595.28) < 0.1
        assert "CFP REMARK - NOT THE APPROVED MEL REMEDY" in mel_page.get_text()
        assert "OPEN EXACT MEL ITEM / REMEDY >" in mel_page.get_text()


def test_time_gate_cards_use_a_content_filling_mosaic_without_three_empty_columns():
    layout = _time_gate_card_layout(full_width=780, cards_top=270)

    edto_x, edto_y, edto_w, edto_h = layout["edto"]
    comms_x, comms_y, comms_w, comms_h = layout["communications"]
    gates_x, gates_y, gates_w, gates_h = layout["operating"]

    assert edto_x == 0
    assert edto_y == 30
    assert edto_w > comms_w
    assert edto_h == 240
    assert comms_x == gates_x
    assert comms_w == gates_w
    assert comms_y > gates_y
    assert comms_h == gates_h
    assert gates_y == 30


def test_single_terrain_profile_uses_the_full_content_width():
    assert _terrain_profile_width(780, image_count=1) == 780
    assert _terrain_profile_width(780, image_count=2) == 385


def test_matched_terrain_page_drops_redundant_zero_unresolved_table():
    assert _terrain_table_height(has_charts=True, unmatched_count=0) == 0
    assert _terrain_table_height(has_charts=True, unmatched_count=1) == 74
    assert _terrain_table_height(has_charts=False, unmatched_count=2) >= 96


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
