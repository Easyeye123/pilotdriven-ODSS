"""Focused regressions for pilot-facing labels on the production PDF."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.combined_brief import render_combined_briefing
from app.odss.timing import build_timing_view


def _production_case():
    flight = sample_flight()
    flight["fuel_summary"] = {
        "state": "verified",
        "rows": {
            "fuel_in_tanks": {"fuel_kg": 79_643},
            "flt_plan_reqmt": {"fuel_kg": 79_643},
        },
    }
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    return flight, findings


def _page_one_text(path: Path) -> str:
    with fitz.open(path) as document:
        return document[0].get_text()


def test_page_one_labels_scheduled_arrival_sta_without_atot(tmp_path):
    flight, findings = _production_case()
    output = tmp_path / "scheduled-arrival-label.pdf"

    render_combined_briefing(flight, findings, [], output)

    first = _page_one_text(output)
    assert first.count("STA 2240Z") >= 2
    assert "ETA 2240Z" not in first


def test_page_one_preserves_eta_for_atot_derived_arrival(tmp_path):
    flight, findings = _production_case()
    flight["actual_takeoff_utc"] = "2026-07-16T09:52:00+00:00"
    flight["timing_view"] = build_timing_view(
        flight,
        findings,
        flight["actual_takeoff_utc"],
    )
    output = tmp_path / "derived-arrival-label.pdf"

    render_combined_briefing(flight, findings, [], output)

    first = _page_one_text(output)
    assert "ETA 2159Z" in first
    assert "STA 2159Z" not in first


def test_approach_highlights_distinguish_return_from_arrival(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def with_destination_ils(
        flight,
        findings,
        warnings,
        timing_view=None,
        weather_charts=None,
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["overview"]["destination"]["primary_operational_highlight"] = {
            "text": "ILS RWY 24 unavailable during the destination window.",
            "signal_family": "approach_navaid",
            "notam_id": "1B3881/26",
            "source_page": 22,
        }
        view["overview"]["departure"]["primary_operational_highlight"] = {
            "text": "ILS RWY 07R unavailable for a return after departure.",
            "signal_family": "approach_navaid",
            "notam_id": "A1001/26",
            "source_page": 21,
        }
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        with_destination_ils,
    )
    flight, findings = _production_case()
    output = tmp_path / "arrival-approach-label.pdf"

    render_combined_briefing(flight, findings, [], output)

    first = _page_one_text(output)
    assert "ARRIVAL APPROACH" in first
    assert "RETURN APPROACH" in first


def test_page_one_phase_strip_has_actions_and_clickable_phase_targets(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def with_phase_evidence(
        flight,
        findings,
        warnings,
        timing_view=None,
        weather_charts=None,
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["performance_reconciliation"].append({
            "label": "PERFORMANCE MAX FUEL / TANKS",
            "status": "OPEN",
        })
        view["deferred_dispatch_gates"] = [{
            "overview_summary": "ENG 2 LATCH · CHECK EACH DEPARTURE",
        }]
        view["route_airspace"] = {
            "record_count": 1,
            "military_source_record": {
                "text": "MIL TRAINING; AFFECTED TRAFFIC SUBJECT TO ATC CLR",
            },
            "applicability_inferred": False,
        }
        view["overview"]["destination"]["primary_operational_highlight"] = {
            "text": "ILS RWY 24 unavailable during the destination window.",
            "notam_id": "1B3881/26",
        }
        view["hazards"]["coverage_ledger"] = [
            {"label": "AIRMET", "status": "unavailable"},
            {"label": "TC SIGMET", "status": "unavailable"},
            {"label": "VA SIGMET", "status": "unavailable"},
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        with_phase_evidence,
    )
    flight, findings = _production_case()
    flight["deferred_items"] = [{"item_type": "IN"}]
    output = tmp_path / "phase-action-strip.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        page = document[0]
        text = " ".join(page.get_text().split())
        for expected in (
            "RELEASE",
            "BEFORE PUSH",
            "ROUTE",
            "ARRIVAL",
            "WEATHER",
            "FUEL-LINE RECONCILE",
            "ENG 2 LATCH - CHECK EACH DEPARTURE",
            "ATC / MIL ACTIVITY HELD - REVIEW APPLICABILITY",
            "ILS RWY 24 UNAVAILABLE - REVIEW ARRIVAL PLAN",
            "AIRMET / TC / VA: NO DATA - COVERAGE GAP",
        ):
            assert expected in text
        assert "PHASE ACTION STRIP PERFORMANCE OPEN STATUS OPEN" not in text

        expected_pages = {
            "RELEASE": 2,
            "BEFORE PUSH": 3,
            "ROUTE": 6,
            "ARRIVAL": 4,
            "WEATHER": 5,
        }
        for phase, expected_page in expected_pages.items():
            phase_box = page.search_for(phase)[-1]
            links = [
                link
                for link in page.get_links()
                if not (fitz.Rect(link["from"]) & phase_box).is_empty
            ]
            assert len(links) == 1, phase
            link = links[0]
            target_page = (
                link.get("page")
                if link.get("kind") == fitz.LINK_GOTO
                else int(str(link.get("page"))) - 1
            )
            assert target_page == expected_page, phase


def test_page_one_receipts_additional_flight_planning_etps_in_dashboard(
    tmp_path,
):
    flight, findings = _production_case()
    flight["flight_planning_etps"] = [
        {
            "label": "ETP A",
            "from": "SIN",
            "to": "MNL",
            "distance_nm": 721,
            "eet_token": "01.40",
            "eet_minutes": 100,
            "source_page": 10,
        },
        {
            "label": "ETP B",
            "from": "MNL",
            "to": "TPE",
            "distance_nm": 322,
            "eet_token": "00.45",
            "eet_minutes": 45,
            "source_page": 10,
        },
    ]
    output = tmp_path / "additional-etp-receipt.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        text = " ".join(
            " ".join(page.get_text().split())
            for page in document
        )
    assert "ETP A SIN/MNL · 721 NM / EET 01:40" in text
    assert "+1 FLIGHT-PLANNING ETPS · IN DASHBOARD" in text
