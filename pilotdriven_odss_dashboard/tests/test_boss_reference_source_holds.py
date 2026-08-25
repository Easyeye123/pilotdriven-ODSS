from __future__ import annotations

from datetime import datetime, timezone

from app.odss.briefing import (
    _compact_notam_lines,
    _decision_finding_projection,
    _intam_review_queue,
    _performance_reconciliation_projection,
    _release_gate_projection,
    _route_airspace_projection,
    _source_assurance_projection,
)
from app.odss.combined_brief import _fuel_panel_rows
from app.odss.enrichment import _parse_route_airspace_notices
from app.odss.parser import parse_page1_fuel_summary


def test_route_airspace_source_hold_is_bounded_and_does_not_infer_intersection():
    pages = [
        "NOTAM\n",
        (
            "==============================\n"
            "EXTENDED AREA AROUND DEPARTURE\n"
            "==============================\n"
            "D5/EXERCISE AREA\n"
            "----------------\n"
            "1A1000/26 VALID: 01-AUG-26 0000 - 02-AUG-26 2359\n"
            "MIL TRAINING AND EXER WILL TAKE PLACE WITHIN PUBLISHED COORDINATES.\n"
            "ALL AFFECTED TRAFFIC SUBJECT ATC CLEARANCE.\n"
            "F) SFC G) FL400\n"
            "WIIF JAKARTA FIR\n"
            "----------------\n"
            "1A1001/26 VALID: 01-AUG-26 0000 - 02-AUG-26 2359\n"
            "CPDLC OPERATIONAL TRIAL.\n"
        ),
        (
            "================================\n"
            "EXTENDED AREA AROUND DESTINATION\n"
            "================================\n"
            "D6/UNRELATED AREA\n"
            "-----------------\n"
            "1B2000/26 VALID: 01-AUG-26 0000 - 02-AUG-26 2359\n"
            "DANGER AREA TEST ACTIVE.\n"
        ),
        "INTAM\n",
    ]

    records = _parse_route_airspace_notices(
        pages,
        datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert [record["notam_id"] for record in records] == ["1A1000/26"]
    assert records[0]["source_page"] == 2
    assert records[0]["activity_kind"] == "military_training"
    projection = _route_airspace_projection({"route_airspace_notices": records})
    assert projection["record_count"] == 1
    assert projection["source_page_text"] == "OFP p2"
    assert projection["applicability_inferred"] is False
    assert projection["military_source_record"]["notam_id"] == "1A1000/26"
    assert "Military-training record 1A1000/26 is source-held" in projection[
        "card_summary"
    ]
    assert "full held records remain in the dashboard" in projection[
        "card_summary"
    ]
    assert "confirm route/level applicability" in projection["release_detail"]
    assert "No polygon intersection is inferred" in projection["release_detail"]

    gates = _release_gate_projection([], [], [], [], [], projection)
    assert gates[-1]["label"] == "ROUTE"
    assert gates[-1]["status"] == "REVIEW"
    assurance = _source_assurance_projection({}, [], [], projection)
    route_row = next(
        row for row in assurance if row["source"] == "ROUTE AIRSPACE NOTICES"
    )
    assert route_row["status"] == "HELD"
    assert "applicability not inferred" in route_row["detail"]


def test_page1_fuel_chain_and_derived_values_are_shared_and_reproducible():
    page1 = (
        "SINGAPORE AIRLINES - SUMMARY STANDARD CFP\n"
        "GND MILES 1431 CRZ COMP M026 BURNOFF 03.21 019367\n"
        "AIR MILES 1520 STAT CONT 00.10 000975\n"
        "ALTN CRK (RPLC) ALTN FUEL 00.21 001828\n"
        "ALTN HOLD 00.30 002274\n"
        "TOP UP TO 60 MINS DEST HOLD FUEL 00.00 000000\n"
        "TAXI FUEL 000600\n"
        "PZFW 169700 FLT PLAN REQMT 04.23 025044\n"
        "PTOW 212991 EXCESS FUEL 03.16 018847\n"
        "PLWT 193624 FUEL IN TANKS 07.38 043891\n"
    )
    summary = parse_page1_fuel_summary(page1)

    assert summary is not None
    assert summary["derived_fuel_kg"] == {"takeoff": 43291, "landing": 23924}
    panel_text = " | ".join(
        f"{label}: {value}" for label, value in _fuel_panel_rows(summary)
    )
    for expected in (
        "STAT CONT",
        "975 kg",
        "ALTN FUEL / ALTN HOLD",
        "1,828 kg",
        "2,274 kg",
        "TAXI: 600 kg",
        "43,291 kg",
        "23,924 kg",
    ):
        assert expected in panel_text

    rows = _performance_reconciliation_projection(
        {"fuel_summary": summary},
        {
            "selected_rtow_kg": 224367,
            "ptow_kg": 212991,
            "margin_kg": 11376,
            "inputs": {"maximum_fuel_available_kg": 36420},
        },
    )
    arithmetic = rows[0]["detail"]
    for expected in (
        "FPL REQ 25,044 kg",
        "BURNOFF 19,367",
        "STAT CONT 975",
        "ALTN FUEL 1,828",
        "ALTN HOLD 2,274",
        "TAXI 600",
        "T/O FUEL 43,291",
        "LDG FUEL 23,924",
    ):
        assert expected in arithmetic


def test_same_condition_notam_duplicate_does_not_displace_unrelated_notice():
    def notice(
        notam_id: str,
        text: str,
        *,
        kind: str,
        rank: int,
        severity: str = "warning",
    ) -> dict:
        return {
            "notam_id": notam_id,
            "item_e_text": text,
            "summary": text,
            "pertinence_kind": kind,
            "pertinence_rank": rank,
            "severity": severity,
            "source_page": 10,
        }

    rows = _compact_notam_lines(
        [
            notice(
                "1A1000/26",
                "RWY 02R/20L IS NOT AVAILABLE FOR CIVIL USE",
                kind="runway_closure",
                rank=1,
                severity="critical",
            ),
            notice(
                "SX10/26",
                "RWY 02R/20L IS NOT AVBL FOR CIVIL USE",
                kind="runway_closure",
                rank=1,
                severity="critical",
            ),
            notice(
                "SX11/26",
                "TEMPORARY DEACTIVATION OF RAPID EXIT TAXIWAY INDICATOR "
                "LIGHTS (RETIL) AT RUNWAY 02C/20C",
                kind="runway_approach_restriction",
                rank=2,
            ),
            notice(
                "1A1002/26",
                "TWY B CLOSED DUE WORK IN PROGRESS",
                kind="taxiway_closure",
                rank=3,
            ),
        ],
        "departure",
        limit=3,
        planned_runways={"20C"},
        reference_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    ids = [row["notam_id"] for row in rows]
    assert len({"1A1000/26", "SX10/26"} & set(ids)) == 1
    assert "SX11/26" in ids
    assert "1A1002/26" in ids


def test_route_airspace_review_replaces_unrelated_alternate_weather_card():
    route_airspace = _route_airspace_projection({
        "route_airspace_notices": [{
            "notam_id": "1A1000/26",
            "activity_kind": "military_training",
            "source_page": 32,
            "text": "MIL TRAINING; AFFECTED TRAFFIC SUBJECT ATC CLEARANCE.",
        }],
    })
    findings = [
        {
            "engine": "notam",
            "severity": "critical",
            "title": "Destination approach notice",
            "summary": "ILS unavailable.",
            "data": {"role": "destination"},
        },
        {
            "engine": "weather",
            "severity": "warning",
            "title": "Weather coverage",
            "summary": "Current product review required.",
            "data": {},
        },
        {
            "engine": "arrival_ground",
            "severity": "warning",
            "title": "Arrival ground constraints",
            "summary": "Taxiway restriction held.",
            "data": {},
        },
        {
            "engine": "alternate_weather",
            "severity": "warning",
            "title": "Alternate weather",
            "summary": "Source weather held.",
            "data": {},
        },
    ]

    selected = _decision_finding_projection(
        findings,
        performance_rows=[{
            "label": "Fuel reconciliation",
            "status": "OPEN",
            "detail": "Reconcile fuel.",
            "source_reference": "OFP p1",
        }],
        deferred_gates=[{
            "title": "Engine latch",
            "summary": "Check before departure.",
            "category": "in",
        }],
        route_airspace=route_airspace,
    )

    engines = [row["engine"] for row in selected]
    assert len(engines) == 6
    assert "route_airspace" in engines
    assert "alternate_weather" not in engines
    route = next(row for row in selected if row["engine"] == "route_airspace")
    assert route["target"] == "sec_enroute"
    assert "1A1000/26" in route["summary"]
    assert "no polygon intersection is inferred" in route["summary"]


def test_intam_queue_is_generic_source_ordered_category_diverse_and_stable():
    records = [
        {
            "category": category,
            "identity": identity,
            "headline": f"SOURCE HEADLINE {identity}",
            "source_page": page,
        }
        for category, identity, page in (
            ("OPS", "OPS-LATE", 42),
            ("AIRCRAFT", "AIRCRAFT-FIRST", 39),
            ("AIRPORT", "AIRPORT-FIRST", 39),
            ("OPS", "OPS-FIRST", 40),
            ("SAFETY", "SAFETY-FIRST", 44),
            ("SEC", "SEC-FIRST", 45),
        )
    ]

    queue = _intam_review_queue(records)

    assert [record["identity"] for record in queue] == [
        "AIRCRAFT-FIRST",
        "AIRPORT-FIRST",
        "OPS-FIRST",
        "SAFETY-FIRST",
        "SEC-FIRST",
    ]
    assert _intam_review_queue(records) == queue
    with_unrelated_tail = [
        *records,
        {
            "category": "OPS",
            "identity": "UNRELATED-TAIL",
            "headline": "UNRELATED SOURCE RECORD",
            "source_page": 46,
        },
    ]
    assert _intam_review_queue(with_unrelated_tail) == queue
