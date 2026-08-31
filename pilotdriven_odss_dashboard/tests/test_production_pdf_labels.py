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
    folded = " ".join(first.split())
    assert "STD 0945Z -> STA 2240Z" in first
    assert "SCHED ARR" in first and "2240Z" in first
    assert "TARGET ARRIVAL NOT CALCULATED" in folded
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
    assert "TARGET ARRIVAL" in first and "2159Z" in first
    assert "TIME BASIS" in first
    assert "TARGET CROSS-OVER TIME = ATOT" in first
    assert "SCHED ARR" in first and "2240Z" in first
    assert "TARGET ARRIVAL 2240Z" not in first


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
        for panel in view["airport_operational_panels"]:
            roles = set(panel.get("role_keys") or [])
            if "departure" in roles:
                panel["selected_notams"].append({
                    "notam_id": "A1001/26",
                    "severity": "critical",
                    "approach_affected": True,
                    "applicability": "active",
                    "stateAtReference": "active_at_reference",
                    "item_e_text": (
                        "ILS RWY 07R UNAVAILABLE FOR A RETURN AFTER DEPARTURE"
                    ),
                    "valid_from_utc": "2026-07-16T08:00:00Z",
                    "valid_to_utc": "2026-07-16T12:00:00Z",
                    "source_page": 21,
                })
            if "destination" in roles:
                panel["selected_notams"].append({
                    "notam_id": "B3881/26",
                    "severity": "critical",
                    "approach_affected": True,
                    "applicability": "active",
                    "stateAtReference": "active_at_reference",
                    "item_e_text": (
                        "ILS RWY 24 UNAVAILABLE DURING THE DESTINATION WINDOW"
                    ),
                    "valid_from_utc": "2026-07-16T20:00:00Z",
                    "valid_to_utc": "2026-07-17T02:00:00Z",
                    "source_page": 22,
                })
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        with_destination_ils,
    )
    flight, findings = _production_case()
    output = tmp_path / "arrival-approach-label.pdf"

    render_combined_briefing(flight, findings, [], output)

    with fitz.open(output) as document:
        first = document[0].get_text()
        all_text = "\n".join(page.get_text() for page in document)
    assert "ILS RWY 24 UNAVAILABLE" in first
    assert "REVIEW ARRIVAL PLAN" in first
    assert "CRITICAL INSTRUMENT APPROACH IMPACTS" in all_text
    assert "EBBR A1001/26" in all_text
    assert "WSSS B3881/26" in all_text


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

        outline_pages = {
            title: page_number - 1
            for _level, title, page_number in document.get_toc()
        }
        expected_pages = {
            "RELEASE": outline_pages["Performance / Fuel / Status"],
            "BEFORE PUSH": outline_pages["MEL/CDL Evidence"],
            "ROUTE": outline_pages["Enroute / Assurance"],
            "ARRIVAL": outline_pages["Airports / Alternates"],
            "WEATHER": outline_pages["Weather / Route Hazards"],
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
