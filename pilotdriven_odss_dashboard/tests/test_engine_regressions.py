from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss import engines
from app.odss.engines import (
    _notam_role_window,
    _schedule_overlaps,
    _weather_role_window,
    analyse,
    detect_terrain_events,
    match_profiles,
)
from app.odss.enrichment import (
    _notice_score,
    _parse_airport_notams,
    _parse_cfp_volcano_advisories,
    _parse_notam_datetime,
    _record_source_page,
)
from app.odss.briefing import _weather_summary
from app.odss.parser import (
    _parse_deferred_items,
    _parse_edto_airports,
    _parse_edto_sectors,
    _parse_named_procedure,
    parse_lido,
)
from app.odss.pilot_briefing import concise_weather_finding, select_pertinent_notams


UTC = timezone.utc


def test_sq338_page_one_mel_continuations_are_preserved() -> None:
    page_one = "\n".join(
        (
            "SINGAPORE AIRLINES - SUMMARY EDTO CFP",
            "ATTN ALL CONCERN FR MAINTROL",
            "AA MEL 21-60-08A",
            "ECAM COND BULK CARGO HEATER FAULT X PERFORMANCE [P]",
            "CARRIAGE OF TEMP SENSITIVE CARGO IN BULK CGO COMPT",
            "IS NOT ALLOWED",
            "PLAN 89/0/1",
            "RTE NO SINCDG60YL A350-941",
        )
    )

    assert _parse_deferred_items(page_one) == [
        {
            "reference": "21-60-08A",
            "description": "ECAM COND BULK CARGO HEATER FAULT X PERFORMANCE [P]",
            "item_type": "MEL",
            "source_declaration": "AA MEL 21-60-08A",
            "company_remark": (
                "CARRIAGE OF TEMP SENSITIVE CARGO IN BULK CGO COMPT "
                "IS NOT ALLOWED"
            ),
        }
    ]


def test_sia722_aa_ifeddl_is_preserved_without_mel_cdl_or_cddl_classification() -> None:
    page_one = "\n".join(
        (
            "SINGAPORE AIRLINES - SUMMARY STANDARD CFP",
            "REMARKS:",
            "AA IFEDDL",
            "CONNECTIVITY, WIFI INTERNET",
            "NO WIFI SIGNAL / KRISWORLD WIFI NETWORK",
            "WHOLE AIRCRAFT",
            "PLAN 2",
            "RTE NO SINBKK03 A350-941",
        )
    )

    # 21 Aug 2026 (SQ910 round): the CFP's own IFEDDL word is the type —
    # the internal "UNCLASSIFIED" label never reaches a pilot surface.
    assert _parse_deferred_items(page_one) == [
        {
            "reference": None,
            "description": "CONNECTIVITY, WIFI INTERNET",
            "item_type": "IFEDDL",
            "source_declaration": "AA IFEDDL",
            "company_remark": (
                "NO WIFI SIGNAL / KRISWORLD WIFI NETWORK WHOLE AIRCRAFT"
            ),
        }
    ]


def test_sia722_aa_ifeddl_never_enters_the_mel_cdl_or_cddl_engines() -> None:
    flight = _flight()
    flight["deferred_items"] = [
        {
            "reference": None,
            "description": "CONNECTIVITY, WIFI INTERNET",
            "item_type": "UNCLASSIFIED",
            "source_declaration": "AA IFEDDL",
            "company_remark": (
                "NO WIFI SIGNAL / KRISWORLD WIFI NETWORK WHOLE AIRCRAFT"
            ),
        }
    ]

    findings, _ = analyse(flight)
    declaration = next(
        item for item in findings if item["engine"] == "deferred_declaration"
    )
    assert declaration["title"] == "AA IFEDDL"
    assert declaration["summary"] == (
        "OFP deferred declaration requires review; acronym meaning is not "
        "inferred and no MEL, CDL or CDDL classification is asserted."
    )
    assert declaration["details"] == [
        "CONNECTIVITY, WIFI INTERNET",
        "NO WIFI SIGNAL / KRISWORLD WIFI NETWORK WHOLE AIRCRAFT",
    ]
    assert not any(
        item["engine"] in {"mel", "cdl", "cddl"} for item in findings
    )


def test_internal_only_deferred_declaration_is_not_published_by_analysis() -> None:
    flight = _flight()
    raw_item = {
        "item_type": "UNCLASSIFIED",
        "reference": "UNSPECIFIED",
        "source_declaration": "UNCLASSIFIED UNSPECIFIED",
        "description": "SOURCE TEXT REQUIRES REVIEW",
    }
    flight["deferred_items"] = [raw_item]

    findings, _ = analyse(flight)
    declaration = next(
        item for item in findings if item["engine"] == "deferred_declaration"
    )
    pilot_projection = " ".join(
        [declaration["title"], declaration["summary"], *declaration["details"]]
    ).upper()
    assert "UNCLASSIFIED" not in pilot_projection
    assert "UNSPECIFIED" not in pilot_projection
    assert raw_item["source_declaration"] == "UNCLASSIFIED UNSPECIFIED"


def test_normalized_source_locator_finds_record_page_without_flight_specific_rules() -> None:
    pages = [
        "SUMMARY PAGE",
        "SA   250051Z   15007KT   10SM FEW250",
        "1A6475/26 VALID: 25-JUL-26 0300 - 25-JUL-26 1000",
    ]

    assert _record_source_page(pages, "SA 250051Z 15007KT 10SM FEW250") == 2
    assert _record_source_page(pages, "1A6475/26") == 3
    assert _record_source_page(pages, "NOT PRESENT") is None


def _record(
    notam_id: str,
    location: str,
    valid_from: str,
    valid_to: str | None,
    schedule: str | None = None,
    *,
    text: str = "RWY CLSD",
    category: str = "RWY",
    priority_score: int = 10,
) -> dict:
    return {
        "notam_id": notam_id,
        "location": location,
        "category": category,
        "text": text,
        "valid_from_utc": valid_from,
        "valid_to_utc": valid_to,
        "schedule": schedule,
        "schedule_review": False,
        "validity_review": False,
        "priority_score": priority_score,
    }


def _flight(
    notams: list[dict] | None = None,
    route_waypoints: list[dict] | None = None,
    weather: list[dict] | None = None,
) -> dict:
    return {
        "document_id": "test.pdf",
        "flight_number": "SQ123",
        "flight_date": "16JUL26",
        "aircraft_type": "A350-941",
        "registration": "9VAAA",
        "departure": "WSSS",
        "destination": "RJBB",
        "departure_runway": "20C",
        "destination_runway": "24L",
        "scheduled_departure_utc": "2026-07-16T10:00:00+00:00",
        "scheduled_arrival_utc": "2026-07-16T12:00:00+00:00",
        "route_text": "",
        "route_waypoints": route_waypoints or [],
        "planned_level_profile": None,
        "cost_index": None,
        "edto_rvsm": None,
        "bobcat": None,
        "deferred_items": [],
        "alternates": [{"airport": "WIII"}],
        "performance": {},
        "fuel": {
            "trip_fuel_kg": 5_000,
            "contingency_fuel_kg": 500,
            "alternate_fuel_kg": 800,
            "alternate_holding_fuel_kg": 0,
            "taxi_fuel_kg": 100,
            "flight_plan_required_fuel_kg": 9_000,
            "excess_fuel_kg": 0,
            "fuel_in_tanks_kg": 10_000,
            "planned_destination_fuel_kg": 4_900,
        },
        "masses": {
            "planned_zfw_kg": 100_000,
            "planned_takeoff_weight_kg": 109_900,
            "planned_landing_weight_kg": 104_900,
        },
        "edto": {
            "entry_actm_minutes": None,
            "exit_actm_minutes": None,
            "etp_actm_minutes": [],
            "airports": [],
        },
        "notams": notams or [],
        "weather": weather or [],
    }


@pytest.mark.parametrize(
    "text",
    (
        "ALLOCATION OF STANDS",
        "DETAILS ONLY",
        "BLOCK PAVEMENT",
        "LOCAL TIME",
    ),
)
def test_notam_scoring_requires_token_boundaries(text: str) -> None:
    assert _notice_score(text, "AIRPORT") == 0


def test_notam_scoring_retains_operational_tokens() -> None:
    assert _notice_score("RWY CLSD", "AIRPORT") == 10
    assert _notice_score("TWY S2 CLSD", "AIRPORT") == 7


def test_airport_notam_parser_does_not_cap_records() -> None:
    block = "\n".join(
        f"A{index:02d}/26 VALID: 01-JUL-26 0000 - 31-JUL-26 2359\nRWY {index:02d} CLSD"
        for index in range(24)
    )
    records = _parse_airport_notams("WSSS", block, datetime(2026, 7, 1, tzinfo=UTC))
    assert len(records) == 24
    assert {record["notam_id"] for record in records} == {f"A{index:02d}/26" for index in range(24)}


@pytest.mark.parametrize(
    "value",
    (
        "32-JUL-26 1200",
        "01-ABC-26 1200",
        "01-JUL-26 2460",
    ),
)
def test_malformed_notam_datetimes_return_none(value: str) -> None:
    assert _parse_notam_datetime(value) is None


def test_malformed_notam_validity_is_retained_for_review() -> None:
    fallback = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
    block = "A1/26 VALID: 32-JUL-26 1200 - 01-ABC-26 1200\nRWY CLSD"
    records = _parse_airport_notams("WSSS", block, fallback)
    assert len(records) == 1
    assert records[0]["valid_from_utc"] == fallback.isoformat()
    assert records[0]["valid_to_utc"] is None
    assert records[0]["validity_review"] is True


@pytest.mark.parametrize(
    ("schedule", "window_start", "window_end", "expected"),
    (
        (
            "DAILY 1500-0700",
            datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 6, 0, tzinfo=UTC),
            True,
        ),
        (
            "DAILY 1500-0700",
            datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 11, 0, tzinfo=UTC),
            False,
        ),
        (
            "MON-FRI 0500-1500",
            datetime(2026, 7, 13, 6, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 7, 0, tzinfo=UTC),
            True,
        ),
        (
            "MON-FRI 0500-1500",
            datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
            datetime(2026, 7, 12, 7, 0, tzinfo=UTC),
            False,
        ),
        (
            "JUL 06-12 0400-0559",
            datetime(2026, 7, 12, 5, 0, tzinfo=UTC),
            datetime(2026, 7, 12, 5, 30, tzinfo=UTC),
            True,
        ),
        (
            "JUL 06-12 0400-0559",
            datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 5, 30, tzinfo=UTC),
            False,
        ),
        (
            "JUL 08 12 15 19 22 26 29 1730-2130",
            datetime(2026, 7, 12, 18, 0, tzinfo=UTC),
            datetime(2026, 7, 12, 19, 0, tzinfo=UTC),
            True,
        ),
        (
            "JUL 08 12 15 19 22 26 29 1730-2130",
            datetime(2026, 7, 13, 18, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 19, 0, tzinfo=UTC),
            False,
        ),
    ),
)
def test_item_d_schedule_overlap(
    schedule: str,
    window_start: datetime,
    window_end: datetime,
    expected: bool,
) -> None:
    assert _schedule_overlaps(schedule, window_start, window_end) is expected


@pytest.mark.parametrize(
    "schedule",
    (
        "DAILY 1500-0700",
        "MON-FRI 0500-1500",
        "JUL 06-12 0400-0559",
        "JUL 08 12 15 19 22 26 29 1730-2130",
    ),
)
def test_item_d_schedule_lines_are_preserved(schedule: str) -> None:
    block = f"A1/26 VALID: 01-JUL-26 0000 - 31-JUL-26 2359\n{schedule}\nRWY CLSD"
    records = _parse_airport_notams("WSSS", block, datetime(2026, 7, 1, tzinfo=UTC))
    assert records[0]["schedule"] == schedule


@pytest.mark.parametrize(
    "schedule",
    (
        "MON-FRI EXC HOL 0500-1500",
        "JUL 01-31 EXC 04 1100-2300",
        "DAILY 0100-0200 EXC SAT",
        "MON 0100-0200 TUE 0300-0400",
    ),
)
def test_item_d_schedule_exceptions_require_manual_review(schedule: str) -> None:
    assert _schedule_overlaps(
        schedule,
        datetime(2026, 7, 13, 6, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 7, 0, tzinfo=UTC),
    ) is None


def test_destination_and_alternate_notams_use_two_hour_arrival_window() -> None:
    notams = [
        _record("DESTTOOOLD/26", "RJBB", "2026-07-16T09:00:00+00:00", "2026-07-16T09:59:00+00:00"),
        _record("DESTOLD/26", "RJBB", "2026-07-16T09:30:00+00:00", "2026-07-16T10:30:00+00:00"),
        _record("DESTNOW/26", "RJBB", "2026-07-16T11:30:00+00:00", "2026-07-16T12:30:00+00:00"),
        _record("ALTNTOOOLD/26", "WIII", "2026-07-16T09:00:00+00:00", "2026-07-16T09:59:00+00:00"),
        _record("ALTNOLD/26", "WIII", "2026-07-16T09:30:00+00:00", "2026-07-16T10:30:00+00:00"),
        _record("ALTNNOW/26", "WIII", "2026-07-16T11:30:00+00:00", "2026-07-16T12:30:00+00:00"),
    ]
    flight = _flight(notams=notams)
    findings, _ = analyse(flight)
    notam_findings = [item for item in findings if item["engine"] == "notam"]
    ids = {item["data"]["notam_id"] for item in notam_findings}
    roles = {item["data"]["notam_id"]: item["data"]["role"] for item in notam_findings}
    assert ids == {"DESTOLD/26", "DESTNOW/26", "ALTNOLD/26", "ALTNNOW/26"}
    assert roles == {
        "DESTOLD/26": "destination",
        "DESTNOW/26": "destination",
        "ALTNOLD/26": "destination alternate",
        "ALTNNOW/26": "destination alternate",
    }
    assert all(
        item["data"]["window_start_utc"] == "2026-07-16T10:00:00+00:00"
        and item["data"]["window_end_utc"] == "2026-07-16T14:00:00+00:00"
        for item in notam_findings
    )


def test_departure_notam_preserves_reference_state_and_actual_validity() -> None:
    flight = _flight(notams=[
        _record(
            "1A6475/26",
            "KJFK",
            "2026-07-25T03:00:00+00:00",
            "2026-07-25T10:00:00+00:00",
            text="RWY 04L/22R CLSD",
            category="RUNWAY",
        ),
        _record(
            "OUTSIDE/26",
            "KJFK",
            "2026-07-25T03:16:00+00:00",
            "2026-07-25T10:00:00+00:00",
            text="RWY 13L/31R CLSD",
            category="RUNWAY",
        ),
    ])
    flight.update({
        "departure": "KJFK",
        "destination": "WSSS",
        "flight_date": "25JUL26",
        "scheduled_departure_utc": "2026-07-25T02:15:00+00:00",
        "scheduled_arrival_utc": "2026-07-25T21:30:00+00:00",
    })

    findings, _ = analyse(flight)
    item = next(
        row
        for row in findings
        if row.get("engine") == "notam"
        and (row.get("data") or {}).get("notam_id") == "1A6475/26"
    )

    assert item["data"]["stateAtReference"] == "begins_after_reference"
    assert item["data"]["referenceAt"] == "2026-07-25T02:15:00+00:00"
    assert item["data"]["minutesDelta"] == 45
    assert item["data"]["valid_from_utc"] == "2026-07-25T03:00:00+00:00"
    assert item["data"]["valid_to_utc"] == "2026-07-25T10:00:00+00:00"
    assert {
        record["notam_id"]
        for record in flight["audit_evidence"]["notam"]["records"]
        if record["pilot_status"] == "outside_time_window"
    } == {"OUTSIDE/26"}


def test_arrival_notam_window_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_NOTAM_ARRIVAL_WINDOW_MINUTES", "30")
    notams = [
        _record("OUTSIDE/26", "RJBB", "2026-07-16T11:00:00+00:00", "2026-07-16T11:29:00+00:00"),
        _record("INSIDE/26", "RJBB", "2026-07-16T11:30:00+00:00", "2026-07-16T12:15:00+00:00"),
    ]

    findings, _ = analyse(_flight(notams=notams))

    assert {
        item["data"]["notam_id"]
        for item in findings
        if item["engine"] == "notam"
    } == {"INSIDE/26"}


def test_notams_are_semantically_deduplicated_and_ranked_after_sta_filter() -> None:
    valid_from = "2026-07-16T10:00:00+00:00"
    valid_to = "2026-07-16T14:00:00+00:00"
    notams = [
        _record(
            "CRANE1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="CRANE ERECTED 2NM SOUTH OF AD",
            category="OBST",
            priority_score=99,
        ),
        _record(
            "TWY1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="TWY A CLSD DUE WIP",
            category="TWY",
            priority_score=7,
        ),
        _record(
            "ILS1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="ILS RWY 24L U/S",
            category="AIRPORT",
            priority_score=10,
        ),
        _record(
            "RWY1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="RWY 24L CLSD",
            category="RWY",
            priority_score=10,
        ),
        _record(
            "RWY-DUP/26",
            "RJBB",
            valid_from,
            valid_to,
            text="RUNWAY 24L CLOSED",
            category="RWY",
            priority_score=10,
        ),
        _record(
            "AD1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="AD CLSD",
            category="AIRPORT",
            priority_score=10,
        ),
    ]

    findings, _ = analyse(_flight(notams=notams))

    selected = [item for item in findings if item["engine"] == "notam"]
    assert [item["data"]["pertinence_kind"] for item in selected] == [
        "airport_closure",
        "runway_closure",
        "approach_navaid_closure",
        "taxiway_closure",
        "obstacle",
    ]
    assert "RWY 24L CLSD" not in "\n".join(item["summary"] for item in selected)
    # The raw source and duplicate decision remain outside the pilot-facing findings.
    flight = _flight(notams=notams)
    analyse(flight)
    notam_audit = flight["audit_evidence"]["notam"]
    assert notam_audit["source_record_count"] == 6
    assert notam_audit["pilot_facing_count"] == 5
    assert notam_audit["semantic_duplicate_count"] == 1
    duplicate = next(
        item for item in notam_audit["records"]
        if item["pilot_status"] == "semantic_duplicate"
    )
    assert duplicate["pilot_status"] == "semantic_duplicate"
    assert duplicate["raw_text"] in {"RWY 24L CLSD", "RUNWAY 24L CLOSED"}


def test_exact_approach_outages_are_critical_for_every_applicable_airport_role() -> None:
    valid_from = "2026-07-16T09:00:00+00:00"
    valid_to = "2026-07-16T15:00:00+00:00"
    notams = [
        _record(
            "ALT-ILS/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-COMMA/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 24, U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-TWO-RUNWAYS/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 24 AND RWY 25 U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-CAT-AFTER-RWY/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 CAT II NOT AVBL",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-CAT-LIST/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 CAT I/II U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-WITHDRAWN/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 WITHDRAWN",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "EDTO-RNP/26",
            "WADD",
            valid_from,
            valid_to,
            text="RNP APCH RWY 27 NOT AVBL",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "FUEL-LOC/26",
            "WIMM",
            valid_from,
            valid_to,
            text="THE UNSERVICEABILITY OF ILS AND GP RWY 23",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-LOC-OSC/26",
            "WIII",
            valid_from,
            valid_to,
            text="LOC 'LAA' RWY 25 MAY INTERRUPT OR OSCILLATE DUE CRANE",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "EDTO-RNAV/26",
            "WADD",
            valid_from,
            valid_to,
            text="RNAV RWY 27 NOT AVBL",
            category="NAVIGATION",
        ),
        _record(
            "FUEL-DME-IAP/26",
            "WIMM",
            valid_from,
            valid_to,
            text="DME MIM U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-TWY/26",
            "WIII",
            valid_from,
            valid_to,
            text="TWY A CLSD",
            category="TWY",
        ),
    ]
    flight = _flight(notams=notams)
    flight["edto"]["airports"] = [{
        "airport": "WADD",
        "period_start_utc": "2026-07-16T10:30:00+00:00",
        "period_end_utc": "2026-07-16T11:30:00+00:00",
    }]
    flight["fuel_enroute_airports"] = [{
        "airport": "WIMM",
        "role": "fuel_enroute_airport",
    }]

    findings, _ = analyse(flight)
    by_id = {
        item["data"]["notam_id"]: item
        for item in findings
        if item.get("engine") == "notam"
    }

    for notam_id, role in (
        ("ALT-ILS/26", "destination alternate"),
        ("ALT-ILS-COMMA/26", "destination alternate"),
        ("ALT-ILS-TWO-RUNWAYS/26", "destination alternate"),
        ("ALT-ILS-CAT-AFTER-RWY/26", "destination alternate"),
        ("ALT-ILS-CAT-LIST/26", "destination alternate"),
        ("ALT-ILS-WITHDRAWN/26", "destination alternate"),
        ("EDTO-RNP/26", "EDTO"),
        ("FUEL-LOC/26", "fuel enroute airport"),
    ):
        assert by_id[notam_id]["severity"] == "critical"
        assert by_id[notam_id]["data"]["role"] == role
        assert by_id[notam_id]["data"]["pertinence_kind"] == (
            "approach_navaid_closure"
        )
        assert by_id[notam_id]["data"]["approach_affected"] is True

    for notam_id, role in (
        ("ALT-LOC-OSC/26", "destination alternate"),
        ("EDTO-RNAV/26", "EDTO"),
        ("FUEL-DME-IAP/26", "fuel enroute airport"),
    ):
        assert by_id[notam_id]["severity"] == "critical"
        assert by_id[notam_id]["data"]["role"] == role
        assert by_id[notam_id]["data"]["approach_affected"] is True

    assert by_id["ALT-TWY/26"]["severity"] == "warning"
    assert by_id["ALT-TWY/26"]["data"]["approach_affected"] is False


def test_sequence_flashing_light_outage_does_not_close_available_approach_lights() -> None:
    valid_from = "2026-07-16T09:00:00+00:00"
    valid_to = "2026-07-16T15:00:00+00:00"
    flight = _flight(notams=[
        _record(
            "SX55/25",
            "WMKK",
            valid_from,
            valid_to,
            text=(
                "SX0055/25 AIP SUPPLEMENT WMKK/KUALA LUMPUR/SEPANG INTL "
                "SEQUENCE FLASHING LIGHT (SFL) RWY 14R VALIDITY: 27NOV25 - "
                "UFN THIS AIRAC AIP SUP IS TO INFORM ALL CONCERNED OF THE "
                "UNSERVICEABILITY OF THE SEQUENCE FLG LGT (SFL) FOR RWY 14R. "
                "APCH LGT FOR RWY 14R AVBL FOR OPR USE."
            ),
            category="RUNWAY",
        )
    ])
    flight["alternates"] = [{"airport": "WMKK"}]

    findings, _ = analyse(flight)
    item = next(
        row
        for row in findings
        if row.get("engine") == "notam" and row["data"]["notam_id"] == "SX55/25"
    )

    assert item["severity"] == "warning"
    assert item["data"]["pertinence_kind"] == "runway_lighting_restriction"
    assert item["data"]["approach_affected"] is False
    assert "approach/navaid" not in item["summary"].lower()
    assert "approach lights are reported available" in item["summary"].lower()
    assert engines._approach_lights_reported_available(
        "RWY 27 HIGH INTENSITY APCH LGT FOR RWY 27 AVBL FOR OPR USE"
    )

    negated_availability = engines._notam_operational_summary(
        (
            "SEQUENCE FLASHING LIGHT (SFL) RWY 14R U/S. "
            "APCH LGT FOR RWY 14R NOT CURRENTLY AVBL."
        ),
        "runway_lighting_restriction",
        "destination alternate",
    )
    assert "reported available" not in negated_availability.lower()

    competing_subject = engines._notam_operational_summary(
        (
            "SEQUENCE FLASHING LIGHT (SFL) RWY 14R U/S. "
            "APCH LGT FOR RWY 14R STATUS UNKNOWN. PAPI AVBL FOR OPR USE."
        ),
        "runway_lighting_restriction",
        "destination alternate",
    )
    assert "reported available" not in competing_subject.lower()


@pytest.mark.parametrize(
    ("notam_id", "text"),
    (
        (
            "SX23/26",
            "SX0023/26 AIP SUPPLEMENT LGRP/RODOS/DIAGORAS VALIDITY: "
            "09JUL26 - 23DEC26 FIRST 180M (20PCT) OF APCH LGT RWY 24 U/S.",
        ),
        (
            "SX40/24",
            "SX0040/24 AIP SUPPLEMENT VTSS/SONGKHLA/HAT YAI VALIDITY: "
            "15SEP24 1001UTC - UFN UNSERVICEABILITY OF APCH LGT AND "
            "SEQUENCED FLG LGT 2.1 SALS AND SEQUENCED FLG LGT OF RWY 08 "
            "WILL BE U/S. 2.2 SALS AND SEQUENCE FLG LGT OF RWY 26 WILL BE U/S.",
        ),
        (
            "1C3691/26",
            "THREE SEQUENCE FLASHING LGT 32L U/S. APPLY PROC FOR HIGH "
            "INTST APCH LGT INOPERATIVE (AIP AD 2.22.4)",
        ),
        (
            "1A2927/26",
            "APPROACH LIGHTING SYSTEM PALS CAT I RWY 11 U/S DUE TO MAINT",
        ),
        (
            "1A76/26",
            "APPROACH LIGHTING SYSTEM RWY23 CROSS BAR U/S.",
        ),
    ),
)
def test_approach_lighting_outages_remain_lighting_warnings(
    notam_id: str,
    text: str,
) -> None:
    flight = _flight(notams=[
        _record(
            notam_id,
            "WIII",
            "2026-07-16T09:00:00+00:00",
            "2026-07-16T15:00:00+00:00",
            text=text,
            category="RUNWAY",
        )
    ])

    findings, _ = analyse(flight)
    item = next(row for row in findings if row.get("engine") == "notam")

    assert item["severity"] == "warning"
    assert item["data"]["approach_affected"] is False
    assert item["data"]["pertinence_kind"] == "runway_lighting_restriction"
    assert "lighting" in item["summary"].lower()
    assert "approach/navaid" not in item["summary"].lower()


def test_approach_critical_gate_rejects_standalone_navaids_and_papi() -> None:
    valid_from = "2026-07-16T09:00:00+00:00"
    valid_to = "2026-07-16T15:00:00+00:00"
    flight = _flight(notams=[
        _record(
            "DEP-ILS-NOT-US/26",
            "WSSS",
            valid_from,
            valid_to,
            text="ILS RWY 20C NOT U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "DEST-ILS-NOT-WITHDRAWN/26",
            "RJBB",
            valid_from,
            valid_to,
            text="ILS RWY 24L NOT WITHDRAWN",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-PAPI/26",
            "WIII",
            valid_from,
            valid_to,
            text="PAPI RWY 25 U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-PAPI-DIRECTIONAL/26",
            "WIII",
            valid_from,
            valid_to,
            text="PAPI RIGHT SIDE RWY 03 U/S",
            category="RUNWAY",
        ),
        _record(
            "ALT-PAPI-RWY-FIRST/26",
            "WIII",
            valid_from,
            valid_to,
            text="RWY 01L PAPI U/S",
            category="RUNWAY",
        ),
        _record(
            "ALT-VOR/26",
            "WIII",
            valid_from,
            valid_to,
            text="VOR ABC U/S",
            category="NAVAID",
        ),
        _record(
            "ALT-DVOR-DME/26",
            "WIII",
            valid_from,
            valid_to,
            text="DVOR/DME PEL U/S",
            category="NAVAID",
        ),
        _record(
            "ALT-NDB-FREQ/26",
            "WIII",
            valid_from,
            valid_to,
            text="NDB GEL/GERALDTON 359KHZ U/S",
            category="NAVAID",
        ),
        _record(
            "ALT-PAPI-CONTEXT/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 AVBL. PAPI RWY 25 U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-VOR-PAPI-CONTEXT/26",
            "WIII",
            valid_from,
            valid_to,
            text="VOR ABC AVBL. PAPI RWY 25 U/S",
            category="NAVAID",
        ),
        _record(
            "ALT-APCH-LGT/26",
            "WIII",
            valid_from,
            valid_to,
            text="APCH LGT FOR RWY 25 NOT AVBL",
            category="RUNWAY",
        ),
        _record(
            "ALT-ILS-AVAILABLE/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY 25 AVBL WHILE RWY 25 CLSD",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-CHECK/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY25 FLIGHT CHECK IN PROGRESS, RWY26 CLSD",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-CHECK-NOCOMMA/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS FLIGHT CHECK IN PROGRESS RWY 26 CLSD",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-CALIBRATION/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS CALIBRATION IN PROGRESS RWY 26 CLSD",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "ALT-ILS-MONITORED/26",
            "WIII",
            valid_from,
            valid_to,
            text="ILS RWY25 SIGNAL MONITORED, TWY A CLSD",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "EDTO-NDB/26",
            "WADD",
            valid_from,
            valid_to,
            text="NDB DEF U/S",
            category="NAVAID",
        ),
        _record(
            "EDTO-RNP10/26",
            "WADD",
            valid_from,
            valid_to,
            text="RNP 10 NOT AVBL",
            category="NAVIGATION",
        ),
        _record(
            "EDTO-ILS-NO-OSC/26",
            "WADD",
            valid_from,
            valid_to,
            text="ILS RWY25 NOT EXPECTED TO OSCILLATE",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "FUEL-DME/26",
            "WIMM",
            valid_from,
            valid_to,
            text="DME GHI U/S",
            category="NAVAID",
        ),
        _record(
            "FUEL-ILS-NOT-US/26",
            "WIMM",
            valid_from,
            valid_to,
            text="ILS RWY25 NOT U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "FUEL-ILS-NOT-CURRENTLY-US/26",
            "WIMM",
            valid_from,
            valid_to,
            text="ILS RWY 25 NOT CURRENTLY U/S",
            category="APPROACH PROCEDURE",
        ),
    ])
    flight["edto"]["airports"] = [{
        "airport": "WADD",
        "period_start_utc": "2026-07-16T10:30:00+00:00",
        "period_end_utc": "2026-07-16T11:30:00+00:00",
    }]
    flight["fuel_enroute_airports"] = [{
        "airport": "WIMM",
        "role": "fuel_enroute_airport",
    }]

    findings, _ = analyse(flight)
    by_id = {
        item["data"]["notam_id"]: item
        for item in findings
        if item.get("engine") == "notam"
    }

    for notam_id in (
        "DEP-ILS-NOT-US/26",
        "DEST-ILS-NOT-WITHDRAWN/26",
        "ALT-PAPI/26",
        "ALT-PAPI-DIRECTIONAL/26",
        "ALT-PAPI-RWY-FIRST/26",
        "ALT-PAPI-CONTEXT/26",
        "ALT-VOR-PAPI-CONTEXT/26",
        "ALT-APCH-LGT/26",
        "ALT-ILS-AVAILABLE/26",
        "ALT-ILS-CHECK/26",
        "ALT-ILS-CHECK-NOCOMMA/26",
        "ALT-ILS-CALIBRATION/26",
        "ALT-ILS-MONITORED/26",
        "ALT-VOR/26",
        "ALT-DVOR-DME/26",
        "ALT-NDB-FREQ/26",
        "EDTO-NDB/26",
        "EDTO-RNP10/26",
        "EDTO-ILS-NO-OSC/26",
        "FUEL-DME/26",
        "FUEL-ILS-NOT-US/26",
        "FUEL-ILS-NOT-CURRENTLY-US/26",
    ):
        assert by_id[notam_id]["severity"] == "warning"
        assert by_id[notam_id]["data"]["approach_affected"] is False

    for notam_id, subject in (
        ("ALT-PAPI/26", "PAPI"),
        ("ALT-PAPI-DIRECTIONAL/26", "PAPI RIGHT SIDE RWY 03"),
        ("ALT-PAPI-RWY-FIRST/26", "PAPI RWY 01L"),
        ("ALT-VOR/26", "VOR"),
        ("ALT-DVOR-DME/26", "DME"),
        ("ALT-NDB-FREQ/26", "NDB"),
    ):
        assert by_id[notam_id]["data"]["pertinence_kind"] == (
            "approach_navaid_closure"
        )
        assert subject.lower() in by_id[notam_id]["summary"].lower()
        assert "unavailable" in by_id[notam_id]["summary"].lower()

    for notam_id, available_subject in (
        ("ALT-PAPI-CONTEXT/26", "ILS"),
        ("ALT-VOR-PAPI-CONTEXT/26", "VOR"),
    ):
        summary = by_id[notam_id]["summary"]
        assert "PAPI RWY 25 unavailable" in summary
        assert f"{available_subject} RWY 25 unavailable" not in summary
        assert f"{available_subject} unavailable" not in summary

    assert by_id["ALT-APCH-LGT/26"]["data"]["pertinence_kind"] == (
        "runway_lighting_restriction"
    )
    assert "closed" not in by_id["ALT-APCH-LGT/26"]["summary"].lower()

    for notam_id in (
        "DEP-ILS-NOT-US/26",
        "DEST-ILS-NOT-WITHDRAWN/26",
    ):
        assert by_id[notam_id]["data"]["pertinence_kind"] == (
            "runway_approach_restriction"
        )
        assert "unavailable" not in by_id[notam_id]["summary"].lower()


@pytest.mark.parametrize(
    "text",
    (
        "ILS Z RWY 25 U/S",
        "ILS Y RWY 25 U/S",
        "RNP Z RWY 25 NOT AVBL",
        "RNAV (GNSS) Z RWY 25 NOT AVBL",
        "ILS 'IPH' 109.9 RWY 24 U/S",
        "ILS RWY 25 FREQ 109.9MHZ U/S",
        "ILS RWY 25 109.9MHZ U/S",
        "LOC RWY 25 109.9 MHZ NOT AVBL",
        "LLZ RWY 25 U/S",
        "GP 332.6 MHZ RWY 25 U/S",
        "GLIDE PATH 332.6 MHZ RWY 25 U/S",
        "GBAS RWY 25 U/S",
        "ILS RWY 35 GP UNUSABLE SFC-2900FT",
        "LOC RWY 16 BC UNUSABLE BEYOND 6DEG RIGHT OF COURSE",
        "ILS RWY 35L UNREL",
        "ILS RWY25 UNRELIABLE",
        "ILS RWY25 FREQ 109.9MHZ U/S",
        "GLIDE PATH RWY25 U/S",
        "ILS RWY25 UNAVAILABLE FOR TESTING",
        "NO APCH OR DEPARTURES TO OR FM RWY 09R/27L WILL TAKE PLACE "
        "WHEN CRANE IS OPR AT FULL HEIGHT",
        "LPV MINIMA SHALL BE RAISED TO THE RESPECTIVE LNAV/VNAV MINIMA. "
        "RNP Z RWY 16, REF AIP AUSTRIA, LOWW AD 2 MAP 13-2-3",
        "NO APCH TO RWY 25 WILL TAKE PLACE WHEN CRANE IS AT FULL HEIGHT "
        "AND PAPI NOW AVAILABLE",
        "NO APCH TO RWY 25 WILL TAKE PLACE WHEN CRANE IS AT FULL HEIGHT "
        "AND TWY A NOW AVAILABLE",
        "NO APCH TO RWY 25 WILL TAKE PLACE WHEN CRANE IS AT FULL HEIGHT "
        "AND ILS RWY 07 NOW AVAILABLE",
        "LPV MINIMA SHALL BE RAISED TO LNAV/VNAV MINIMA AND PAPI NOW AVAILABLE",
        "ILS RWY 25 U/S AND VOR ABC NOW AVAILABLE",
        "ILS RWY 25 U/S AND LOC RWY 07 NOW AVAILABLE",
        "ILS RWY 25 U/S AND GP NOW AVAILABLE",
        "ILS RWY 25 U/S AND GBAS NOW AVAILABLE",
        "ILS RWY 25 U/S AND PAPI NOW AVAILABLE",
        "ILS RWY 25 U/S AND APPROACH LIGHTING NOW AVAILABLE",
        "ILS RWY 25 U/S AND TAXIWAY LIGHTS NOW AVAILABLE",
        "ILS RWY 25 U/S AND RUNWAY LIGHTS NOW AVAILABLE",
        "ILS RWY 25 U/S NOT CANCELLED",
        "ILS RWY 25 U/S NOT CANCELED",
        "ILS RWY 25 U/S NOT REVOKED",
        "ILS RWY 25 U/S NOT RESTORED",
        "AUTO-COUPLED APCH SHOULD NOT BE FLOWN",
        "IAC ILS/VOR/RNAV PROCEDURES SUSPENDED",
        "IAC ILS/VOR/RNAV PROCEDURES WITHDRAWN",
        "RWY 22L CAT II/III OPS NOT AVBL",
        "VOR RWY 07 PROC WITHDRAWN",
        "ILS RWY 04 ON TEST. DO NOT USE.",
        "ILS/LOC RWY 13 U/S",
        "ILS/GP RWY 13 U/S",
        "ILS GP RWY 32L OUT OF SVC",
        "ILS RWY 25 PROCEDURE NA",
        "ILS RWY 25 CAT II/III NA",
        "ILS RWY 25 AVBL, CAT III OPS NOT AVBL",
        "ILS RWY 25 LOC AVAILABLE GP U/S",
        "ILS RWY 25 LOCALIZER AVBL, GLIDE PATH U/S",
        "ILS RWY 25 AVBL EXCEPT CAT II/III OPS NOT AVBL",
        "CAT III OPS RWY 25 NOT AVBL",
        "ILS RWY 25 AVAILABLE. CAT III OPS NOT AVAILABLE",
    ),
)
def test_named_instrument_approach_procedure_outages_are_critical(
    text: str,
) -> None:
    assert engines._instrument_approach_affected(
        text,
        "APPROACH PROCEDURE",
    ) is True


@pytest.mark.parametrize(
    "text",
    (
        (
            "IAC ILS-01 ILS Z RWY 03L DATED 10 JAN 2013 SUSPENDED. "
            "IAC VOR-01 VOR Z RWY 21R DATED 04 APR 2013 SUSPENDED. "
            "IAC RNAV-01 RNAV (GNSS) RWY 03R DATED 31 DEC 2020 SUSPENDED."
        ),
        (
            "IAC VOR-02 VOR Y RWY 21R DATED 10 JAN 2013 WITHDRAWN. "
            "IAC ILS-02 ILS Y RWY 03L DATED 18 AUG 2016 WITHDRAWN."
        ),
    ),
)
def test_numbered_iac_corpus_outages_are_critical(text: str) -> None:
    valid_from = "2026-07-16T09:00:00+00:00"
    valid_to = "2026-07-16T15:00:00+00:00"
    findings, _ = analyse(_flight(notams=[
        _record(
            "1A2888/26",
            "RJBB",
            valid_from,
            valid_to,
            text=text,
            category="APPROACH PROCEDURE",
        )
    ]))
    item = next(row for row in findings if row.get("engine") == "notam")

    assert item["severity"] == "critical"
    assert item["data"]["approach_affected"] is True
    assert item["data"]["pertinence_kind"] == "approach_navaid_closure"
    assert "unavailable" in item["summary"].lower()


@pytest.mark.parametrize(
    "text",
    (
        (
            "IAP SEATTLE-TACOMA INTL, SEATTLE, WA. ILS RWY 34L "
            "(SA CAT I AND II), AMDT 1F ... PROCEDURE NA. TEMPORARY CRANE."
        ),
        (
            "IAP ILS RWY 02/20 (CAT A,B,C,D) SUSPENDED DUE ILS CAT I "
            "RWY 02/20 ON TEST. REF AIP RPLC AD CHART 2-35 TO 2-36."
        ),
        "ILS/LOC RWY 13 IUPG FREQ 111.3MHZ U/S DUE TO INTERFERENCE FREQUENCY",
        "LOC RWY 13R IVP 110.300MHZ U/S.",
        (
            "CAT (ROMAN)III ILS RWY 11R IDENT IDMR (LOC 111.300MHZ, "
            "GP 332.300MHZ,DME IDMR CH50X) NOT AVBL DUE EQUIPMENT REPLACEMENT."
        ),
        "INSTRUMENT LANDING SYSTEM (ILS) RWY35R ON TEST, DO NOT USE.",
        (
            "ILS RWY23 LLZ MA FREQ 110.3MHZ AND GP FREQ 335.0 MHZ "
            "ON TEST, DO NOT USE."
        ),
        (
            "DAILY 2200-0630 ILS 'IBS' 110.1 RWY19L ON TEST, DO NOT USE "
            "FALSE INDICATIONS POSSIBLE."
        ),
        "NDB GEL/GERALDTON 359KHZ U/S",
        "DME 'CGN' CH100Y U/S.",
        "RWY 14 'SD' 110.3MHZ ILS LOC UNUSABLE SOUTH OF THE 17NM ARC",
        "RWY 14 CH40X ILS DME UNUSABLE SOUTH OF THE 17NM ARC",
        "ILS UNREL",
        "LOC NA",
        "GP DO NOT USE",
        "VOR UNSERVICEABILITY",
        "NDB INOPERATIVE",
        "DME INTERRUPTED",
        "VOR INTERRUPTION",
        "NDB OSCILLATION",
        "DME DEGRADED",
        "VOR DEGRADATION",
        "NDB DOWNGRADED",
        "DME UNRELIABLE",
        "VOR UNREL",
        "NDB NA",
        "DME DO NOT USE",
        "VOR SHOULD NOT BE FLOWN",
        (
            "LOC IGD 109.5 RWY21 SUBJECT TO INTERRUPTION / POSSIBLE SIGNAL "
            "OSCILLATION DUE CRANE OPERATIONS."
        ),
        "ILS/MM RWY 17 FREQ 75MHZ U/S",
        "OM (ILS 'FSS') RWY34R COMPLETELY WITHDRAWN",
        "RWY 24 ILS OM 75MHZ OUT OF SERVICE",
        "I-PHL INNER MARKER OUT OF SERVICE",
        "ILS RWY09R INNER MARKER OUT OF SERVICE",
        "INNER MARKER (ILS I-PHL) OUT OF SERVICE",
        "MIDDLE MARKER RWY25 U/S",
        "OUTER MARKER RWY25 U/S",
        "INNER MARKER U/S",
        "MIDDLE MARKER U/S",
        "OUTER MARKER U/S",
        "IAP ILS RWY34L PROCEDURE NA. SID CANCELLED.",
        "IAP ILS RWY34L PROCEDURE NA, SID CANCELLED.",
        "IAP ILS RWY25 SUSPENDED, SID CANCELLED.",
        "IAC ILS/VOR/RNAV PROCEDURES SUSPENDED, SID CANCELLED",
        "ILS RWY25 ON TEST DO NOT USE, SID CANCELLED",
        "ILS RWY25 ON TEST DO NOT USE, ATIS CANCELLED",
        "LPV APCH Z RWY 07L SUSPENDED",
        "LPV APCH RNP Y RWY 34 IS SUSPENDED",
        "ILS AND LOC APCH TEMPO SUSPENDED",
        "DME READINGS ON ILS/LOC RWY 15 FINAL NOT AVBL",
        "PROC ILS OR LOC RWY 19R TEMPO WITHDRAWN",
        "IAP ILS RWY25 CAT I AVAILABLE. ILS RWY25 CAT II PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE, S-ILS 25 CAT II NA.",
        "IAP ILS RWY25 CAT I AVAILABLE, CAT II PROCEDURE NA.",
        "IAC ILS-01 ILS Z RWY 06 CAT II DATED 08 DEC 2016 WITHDRAWN",
        "IAC-23 ILS Z CAT I OR LOC Z RWY 21L PROCEDURES ARE SUSPENDED",
        "ILS RWY 11R CAT II AND III PROCEDURE WITHDRAWN",
        "PROC ILS RWY 29L CAT II AND III WITHDRAWN",
        "ILS RWY 27R SPECIAL AUTH CAT II NA",
        "IAP ILS CAT I RWY 27 THE G.P INOPERATIVE",
        "LOC IGD 109.5 RWY 21 SUBJ TO INTRP",
        "ILS FOR RWY 31L OUT OF SERVICE DUE TO MAINT",
        "LOC FOR RWY 31R OUT OF SERVICE DUE TO MAINT",
        (
            "IAP JOHN F KENNEDY INTL, NEW YORK, NY. ILS OR LOC RWY 22R, "
            "AMDT 3. PROCEDURE NA EXCEPT FOR ACFT EQUIPPED WITH SUITABLE "
            "RNAV SYSTEM WITH GPS. JFK VOR/DME OUT OF SERVICE."
        ),
    ),
)
def test_authentic_published_approach_outage_syntaxes_are_critical(
    text: str,
) -> None:
    assert engines._instrument_approach_affected(
        text,
        "APPROACH PROCEDURE",
    ) is True


@pytest.mark.parametrize(
    "text",
    (
        (
            "LAS IAP HARRY REID INTL, LAS VEGAS, NV. VOR/DME-A, ORIG-E... "
            "PROCEDURE NA."
        ),
        (
            "PHL IAP PHILADELPHIA INTL, PHILADELPHIA, PA. ILS Z RWY 9R, "
            "AMDT 1. S-ILS 9R CAT II NA EXCEPT FOR AIRCRAFT EQUIPPED "
            "WITH RADIO ALTIMETER."
        ),
    ),
)
def test_exact_faa_iap_unavailability_is_text_authoritative_across_categories(
    text: str,
) -> None:
    assert engines._instrument_approach_affected(text, "RUNWAY") is True


def test_conditional_crane_runway_state_is_not_promoted_to_a_closure() -> None:
    text = (
        "2130-0330 LIT CRANE OPR WI HOUNSLOW. MAX HGT 246FT AGL. "
        "CRANE WILL ONLY OPERATE WHEN RWY 09L/27R IS CLSD. "
        "NO CRANE OPR IN LVP."
    )

    rank, kind = engines.notam_pertinence(text, "AIRPORT")

    assert (rank, kind) == (8, "obstacle")
    assert "runway is not reported closed" in engines._notam_operational_summary(
        text,
        kind,
        "destination",
    ).lower()


def test_conditional_crane_approach_prohibition_stays_critical_review() -> None:
    text = (
        "LIT CRANE OPR AT HEATHROW. NO APCH OR DEPARTURES TO OR FM "
        "RWY 09R/27L WILL TAKE PLACE WHEN CRANE IS OPR AT FULL HEIGHT."
    )

    assert engines._instrument_approach_affected(text, "AIRPORT") is True
    assert engines._conditional_instrument_approach_impact(text) is True


def test_parser_number_prefix_does_not_duplicate_one_notam_identity() -> None:
    def finding(notam_id: str, raw_text: str) -> dict[str, object]:
        return {
            "engine": "notam",
            "severity": "warning",
            "title": f"NOTAM {notam_id}",
            "summary": "Taxiway restriction requires review.",
            "data": {
                "role": "destination",
                "location": "WSSS",
                "pertinence_kind": "taxiway_restriction",
                "notam_id": notam_id,
                "raw_text": raw_text,
                "valid_from_utc": "2026-08-29T00:00:00Z",
                "valid_to_utc": "2026-09-01T00:00:00Z",
                "window_start_utc": "2026-08-29T04:00:00Z",
                "window_end_utc": "2026-08-29T06:00:00Z",
                "applicability": "active",
            },
        }

    selected = select_pertinent_notams([
        finding("A2876/26", "A2876/26 TWY A CLSD"),
        finding("1A2876/26", "1A2876/26 TWY A CLOSED - SOURCE COPY"),
    ], limit=10)

    assert len(selected) == 1
    assert selected[0]["data"]["notam_id"] == "A2876/26"


@pytest.mark.parametrize(
    "text",
    (
        "RNP 10 NOT AVBL",
        "ILS Z FLIGHT CHECK IN PROGRESS RWY 26 CLSD",
        "ILS RWY 34R U/S CANCELLED",
        "ILS RWY 25 U/S CONDITION CANCELLED, NOW OPERATIONAL",
        "ILS RWY 25 WAS U/S NOW AVAILABLE",
        "ILS RWY 25 U/S UNTIL 1200Z THEN AVAILABLE",
        "ILS RWY 25 U/S REVOKED",
        "ILS RWY 25 U/S RESTORED",
        "NO APCH TO RWY 25 WILL TAKE PLACE CONDITION CANCELLED",
        "LPV MINIMA SHALL BE RAISED TO LNAV/VNAV MINIMA CONDITION CANCELLED",
        "ILS RWY 25 PROCEDURE NOT NA",
        "ILS RWY 25 ON TEST. DO NOT USE CONDITION CANCELLED.",
        "AUTO-COUPLED APCH SHOULD NOT BE FLOWN CONDITION CANCELLED",
        "SID PROCEDURE SUSPENDED",
        "STAR PROCEDURE WITHDRAWN",
        "IAP ILS RWY 25 PROCEDURE AVAILABLE. SID PROCEDURE SUSPENDED.",
        "IAP ILS RWY 25 PROCEDURE AVAILABLE. STAR PROCEDURE WITHDRAWN.",
        "IAP ILS RWY 25 PROCEDURE AVAILABLE. RUNWAY 25 SUSPENDED.",
        "IAP ILS RWY34L PROCEDURE NA CONDITION CANCELLED.",
        "IAP ILS RWY34L PROCEDURE NA. NOTICE CANCELLED.",
        "IAC ILS RWY25 AVAILABLE, SID PROCEDURE SUSPENDED",
        "IAC ILS RWY25 AVAILABLE, STAR PROCEDURE WITHDRAWN",
        "IAC ILS RWY25 NOT SUSPENDED",
        "IAC ILS RWY25 SUSPENDED CONDITION CANCELLED",
        "IAC ILS RWY25 SUSPENDED, NOW AVAILABLE",
        "ILS RWY 25 STATUS UNKNOWN, PAPI ON TEST DO NOT USE",
        "ILS RWY 25 STATUS UNKNOWN, RWY EDGE LIGHTS ON TEST DO NOT USE",
        "ILS RWY 25 (PAPI U/S) AVAILABLE",
        "ILS RWY 25 (RWY EDGE LIGHTS U/S) AVAILABLE",
        "ILS RWY 25 (TEMPORARY CRANE U/S) AVAILABLE",
        "ILS RWY25 (PAPI) U/S",
        "ILS RWY 25 LIGHTS FREQ 100 U/S",
        "ILS RWY 25 CRANE 123 U/S",
        "TWY IM U/S",
        "TWY MM U/S",
        "TWY OM U/S",
        "TAXIWAY IM CLOSED",
        "STAND IM U/S",
        "APRON IM U/S",
        "TWY A MIDDLE MARKER RWY25 U/S",
        "STAND INNER MARKER (ILS I-PHL) OUT OF SERVICE",
        "ILS RWY25 STATUS UNKNOWN, TAXIWAY A STOP BAR ON TEST DO NOT USE",
        "ILS RWY25 STATUS UNKNOWN, ATIS ON TEST DO NOT USE",
        "ILS RWY25 STATUS UNKNOWN, RVR EQUIPMENT ON TEST DO NOT USE",
        "IAP ILS RWY25 AVAILABLE. DEPARTURE PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. DP KENNEDY FIVE DEPARTURE PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. TAXI PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. RUNWAY PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. PAPI PROCEDURE NA.",
        "IAP ILS RWY25 STATUS UNKNOWN, DEPARTURE PROCEDURE SUSPENDED",
        "IAP ILS RWY25 STATUS UNKNOWN, NOISE ABATEMENT PROCEDURE WITHDRAWN",
        "ILS RWY25 SFL U/S",
        "ILS RWY25 SALS U/S",
        "ILS RWY25 MALSR U/S",
        "ILS RWY25 PALS U/S",
        "ILS RWY25 SSALR U/S",
        "ILS RWY25 REIL U/S",
        "ILS RWY25 TDZL U/S",
        "ILS RWY25 RCLL U/S",
        "ILS RWY25 RTIL U/S",
        "ILS RWY25 TWR 118.1 U/S",
        "ILS RWY25 ATIS 126.0 U/S",
        "ILS RWY25 RVR 100 U/S",
        "ILS SFL RWY25 U/S",
        "ILS MALSR RWY25 U/S",
        "ILS PALS RWY25 U/S",
        "ILS ATIS ON TEST DO NOT USE",
        "ILS RVR ON TEST DO NOT USE",
        "ILS TWR ON TEST DO NOT USE",
        "IAP ILS RWY25 AVAILABLE. DEPARTURE: PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. DEPARTURE CHART PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. ATIS PROCEDURE NA.",
        "IAP ILS RWY25 AVAILABLE. RVR PROCEDURE NA.",
    ),
)
def test_named_procedure_support_preserves_non_approach_boundaries(
    text: str,
) -> None:
    assert engines._instrument_approach_affected(
        text,
        "APPROACH PROCEDURE",
    ) is False


def test_authentic_corpus_approach_wording_reaches_machine_contract() -> None:
    valid_from = "2026-07-16T09:00:00+00:00"
    valid_to = "2026-07-16T15:00:00+00:00"
    flight = _flight(notams=[
        _record(
            "1F2548/26",
            "NZCH",
            valid_from,
            valid_to,
            text="AUTO-COUPLED APCH SHOULD NOT BE FLOWN",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1A2888/26",
            "RJBB",
            valid_from,
            valid_to,
            text="IAC ILS/VOR/RNAV PROCEDURES SUSPENDED",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1A1312/26",
            "EKCH",
            valid_from,
            valid_to,
            text="RWY 22L CAT II/III OPS NOT AVBL",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1G681/26",
            "VOMM",
            valid_from,
            valid_to,
            text="VOR RWY 07 PROC WITHDRAWN",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1A399/26",
            "VCBI",
            valid_from,
            valid_to,
            text="ILS RWY 04 ON TEST. DO NOT USE.",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "CAT-PARTIAL/26",
            "VOMM",
            valid_from,
            valid_to,
            text="ILS RWY 25 AVBL, CAT III OPS NOT AVBL",
            category="APPROACH PROCEDURE",
        ),
    ])
    flight["destination"] = "NZCH"
    flight["alternates"] = [
        {"airport": "EKCH"},
        {"airport": "VOMM"},
        {"airport": "VCBI"},
    ]

    findings, _ = analyse(flight)
    by_id = {
        item["data"]["notam_id"]: item
        for item in findings
        if item.get("engine") == "notam"
    }

    for notam_id in (
        "1F2548/26",
        "1A2888/26",
        "1A1312/26",
        "1G681/26",
        "1A399/26",
        "CAT-PARTIAL/26",
    ):
        assert by_id[notam_id]["severity"] == "critical"
        assert by_id[notam_id]["data"]["approach_affected"] is True


def test_authentic_sq322_approach_impacts_are_critical_without_losing_condition() -> None:
    valid_from = "2026-06-01T00:00:00+00:00"
    valid_to = "2026-11-03T23:59:00+00:00"
    flight = _flight(notams=[
        _record(
            "1A2085/26",
            "EGLL",
            valid_from,
            valid_to,
            text=(
                "LIT CRANE OPR AT PSN 512741N 0002747W (HEATHROW). "
                "MAX HGT 125FT AGL, 203FT AMSL. NO CRANE OPR IN LVP. "
                "NO APCH OR DEPARTURES TO OR FM RWY 09R/27L WILL TAKE "
                "PLACE WHEN CRANE IS OPR AT FULL HEIGHT."
            ),
            category="OBSTACLE",
        ),
        _record(
            "1A2954/26",
            "EGCC",
            valid_from,
            valid_to,
            text="ILS RWY 05L U/S",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1A2951/26",
            "EGCC",
            valid_from,
            valid_to,
            text="ILS RWY 05L OUT OF SERVICE.",
            category="APPROACH PROCEDURE",
        ),
        _record(
            "1A1998/26",
            "LOWW",
            valid_from,
            valid_to,
            text=(
                "LPV MINIMA SHALL BE RAISED TO THE RESPECTIVE LNAV/VNAV "
                "MINIMA. RNP RWY 11. RNP RWY 29. RNP Z RWY 16. RNP RWY 34."
            ),
            category="APPROACH PROCEDURE",
        ),
    ])
    flight["destination"] = "EGLL"
    flight["alternates"] = [{"airport": "EGCC"}]
    flight["fuel_enroute_airports"] = [{
        "airport": "LOWW",
        "role": "fuel_enroute_airport",
    }]

    findings, _ = analyse(flight)
    by_id = {
        item["data"]["notam_id"]: item
        for item in findings
        if item.get("engine") == "notam"
    }

    for notam_id in ("1A2085/26", "1A2954/26", "1A2951/26", "1A1998/26"):
        assert by_id[notam_id]["severity"] == "critical"
        assert by_id[notam_id]["data"]["approach_affected"] is True
    assert "only under the exact condition stated in item E" in by_id[
        "1A2085/26"
    ]["summary"]
    assert "manual review required" in by_id["1A2085/26"]["summary"]
    assert "closed" not in by_id["1A2085/26"]["summary"].lower()
    assert "LPV minima are raised" in by_id["1A1998/26"]["summary"]


def test_notam_subject_outages_are_not_promoted_to_full_surface_closures() -> None:
    valid_from = "2026-07-16T10:00:00+00:00"
    valid_to = "2026-07-16T14:00:00+00:00"
    notams = [
        _record(
            "AD1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="AD AP CLSD",
            category="AIRPORT",
        ),
        _record(
            "STAND1/26",
            "RJBB",
            valid_from,
            valid_to,
            text=(
                "CLOSURE OF ACFT STAND E5 AT CARGO APRON. "
                "ACFT STAND E5 AT THE AIRPORT WILL BE CLOSED."
            ),
            category="AIRPORT",
        ),
        _record(
            "RWYLGT1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="RWY 24L LEAD OFF LGT AT TWY K U/S",
            category="RUNWAY",
        ),
        _record(
            "TWY1/26",
            "RJBB",
            valid_from,
            valid_to,
            text="TWY Z BTN RWY 06L/24R AND TWY Y CLSD",
            category="TAXIWAY",
        ),
    ]

    findings, _ = analyse(_flight(notams=notams))
    by_id = {
        item["data"]["notam_id"]: item
        for item in findings
        if item["engine"] == "notam"
    }

    assert by_id["AD1/26"]["data"]["pertinence_kind"] == "airport_closure"
    assert by_id["STAND1/26"]["data"]["pertinence_kind"] == "apron_stand_closure"
    assert "Entire airport" not in by_id["STAND1/26"]["summary"]
    assert by_id["RWYLGT1/26"]["data"]["pertinence_kind"] == "runway_lighting_restriction"
    assert "closed" not in by_id["RWYLGT1/26"]["summary"].lower()
    assert by_id["TWY1/26"]["data"]["pertinence_kind"] == "taxiway_closure"
    assert [item["data"]["notam_id"] for item in findings if item["engine"] == "notam"] == [
        "AD1/26",
        "RWYLGT1/26",
        "TWY1/26",
        "STAND1/26",
    ]


def test_unresolved_notam_schedule_is_review_required_not_declared_active() -> None:
    record = _record(
        "SCHED1/26",
        "RJBB",
        "2026-07-01T00:00:00+00:00",
        "2026-07-31T23:59:00+00:00",
        text="RWY 24L WILL BE CLSD BTN 1800-2200 DLY",
        category="RUNWAY",
    )
    record["schedule_review"] = True

    findings, _ = analyse(_flight(notams=[record]))
    item = next(row for row in findings if row["engine"] == "notam")

    assert item["data"]["applicability"] == "review"
    assert "could not be resolved" in item["summary"]
    assert "review required" in item["summary"]
    assert "closed or unavailable during" not in item["summary"]


def test_exact_approach_outage_survives_unresolved_schedule_as_critical_review() -> None:
    record = _record(
        "SCHED-ILS/26",
        "RJBB",
        "2026-07-01T00:00:00+00:00",
        "2026-07-31T23:59:00+00:00",
        text="ILS RWY 24L U/S",
        category="APPROACH PROCEDURE",
    )
    record["schedule"] = "ON REQUEST EXC PUBLISHED PERIODS"
    record["schedule_review"] = True

    findings, _ = analyse(_flight(notams=[record]))
    item = next(row for row in findings if row["engine"] == "notam")

    assert item["severity"] == "critical"
    assert item["data"]["approach_affected"] is True
    assert item["data"]["applicability"] == "review"
    assert item["data"]["schedule_status"] == "review_required"
    assert "could not be resolved" in item["summary"]
    assert "closed or unavailable during" not in item["summary"]


def test_notam_priority_view_is_bounded_but_level2_retains_every_applicable_record() -> None:
    notams = [
        _record(
            f"OBS{index:02d}/26",
            "RJBB",
            "2026-07-16T10:00:00+00:00",
            "2026-07-16T14:00:00+00:00",
            text=f"CRANE {index} ERECTED NEAR AD",
            category="OBST",
            priority_score=index,
        )
        for index in range(30)
    ]
    notams.append(
        _record(
            "RWYTOP/26",
            "RJBB",
            "2026-07-16T10:00:00+00:00",
            "2026-07-16T14:00:00+00:00",
            text="RWY 24L CLSD",
            category="RWY",
            priority_score=1,
        )
    )
    flight = _flight(notams=notams)

    findings, _ = analyse(flight)

    applicable = [item for item in findings if item["engine"] == "notam"]
    assert len(applicable) == 31
    assert applicable[0]["data"]["notam_id"] == "RWYTOP/26"
    audit = flight["audit_evidence"]["notam"]
    assert audit["source_record_count"] == 31
    assert audit["time_applicable_count"] == 31
    assert audit["pilot_facing_count"] == 31
    assert audit["priority_view_count"] == 24
    assert audit["level2_only_count"] == 7
    assert audit["audit_only_count"] == 0


def test_departure_surface_closures_survive_saturated_alternate_notam_list() -> None:
    notams = [
        _record(
            f"ALT{index:02d}/26",
            "WIII",
            "2026-07-16T10:00:00+00:00",
            "2026-07-16T14:00:00+00:00",
            text=f"RWY {index:02d} CLSD",
            category="RWY",
            priority_score=100 - index,
        )
        for index in range(24)
    ]
    notams.extend(
        [
            _record(
                "SX68/26",
                "WSSS",
                "2026-05-14T14:30:00+00:00",
                "2026-10-01T21:30:00+00:00",
                text="TWY W9 AND JUNCTION OF TWY W9 TWY W AND TWY R CLSD",
                category="TWY",
            ),
            _record(
                "SX174/24",
                "WSSS",
                "2024-11-28T00:00:00+00:00",
                "2027-12-22T23:59:00+00:00",
                text="TWY ASSOCIATED WITH RWY 02R/20L CLSD",
                category="TWY",
            ),
        ]
    )

    flight = _flight(notams=notams)
    findings, _ = analyse(flight)

    selected_ids = {
        item["data"]["notam_id"]
        for item in findings
        if item["engine"] == "notam"
    }
    assert {"SX68/26", "SX174/24"} <= selected_ids
    audit_status = {
        item["notam_id"]: item["pilot_status"]
        for item in flight["audit_evidence"]["notam"]["records"]
    }
    # All unique applicable records remain in analysis truth; the separate
    # priority-view count remains bounded for Level 1.
    assert len([item for item in findings if item["engine"] == "notam"]) == 26
    assert audit_status["SX68/26"] == "selected"
    assert audit_status["SX174/24"] == "selected"
    assert flight["audit_evidence"]["notam"]["source_record_count"] == 26
    assert flight["audit_evidence"]["notam"]["priority_view_count"] == 24
    assert flight["audit_evidence"]["notam"]["level2_only_count"] == 2


def test_compound_and_tabulated_taxiway_closures_keep_the_operational_extent() -> None:
    sx68 = (
        "SINGAPORE CHANGI AIRPORT - TEMPORARY CLOSURE AT TAXIWAY W9 AND "
        "JUNCTION OF TAXIWAY W9, TAXIWAY W AND TAXIWAY R. TAXIWAY W9 AND "
        "THE JUNCTION OF TAXIWAY W9, TAXIWAY W AND TAXIWAY R WILL BE CLOSED."
    )
    sx174 = (
        "CLOSURE OF TWY ASSOCIATED WITH RWY02R/20L. TWY CLOSURE PERIOD: "
        "28 NOV 2024, 0000UTC TO 22 DEC 2027, 2359UTC "
        "TWY A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11, A12 "
        "TWY A TWY B1, B2, B3, B4, B5, B6, F, E, B7, B8, B9, B10, B11, B12, B13, B14 "
        "TWY B TWY G TWY G2, G3 TWY H TWY J8, J9, J10, J12 "
        "TWY L BTN TWY U13 C14 ALL MARKINGS LEADING INTO THE CLSD TWY WILL BE REMOVED."
    )
    flight = _flight(notams=[
        _record(
            "SX68/26",
            "WSSS",
            "2026-05-14T14:30:00+00:00",
            "2026-10-01T21:30:00+00:00",
            text=sx68,
            category="TWY",
        ),
        _record(
            "SX174/24",
            "WSSS",
            "2024-11-28T00:00:00+00:00",
            "2027-12-22T23:59:00+00:00",
            text=sx174,
            category="TWY",
        ),
    ])

    findings, _ = analyse(flight)
    summaries = {
        item["data"]["notam_id"]: item["summary"]
        for item in findings
        if item["engine"] == "notam"
    }

    assert summaries["SX68/26"] == (
        "TWY W9 AND W9/W/R JUNCTION closed during the applicable departure window."
    )
    assert "TWY ASSOCIATED" not in summaries["SX174/24"]
    assert "A1-A12" in summaries["SX174/24"]
    assert "B1-B14" in summaries["SX174/24"]
    assert "J8-J10" in summaries["SX174/24"]
    assert "L BETWEEN U13 AND C14" in summaries["SX174/24"]


def test_analyse_structures_caas_174_operational_details_and_review_metadata() -> None:
    raw_text = (
        "CLOSURE OF TWY ASSOCIATED WITH RWY02R/20L. "
        "ALL MARKINGS LEADING INTO THE CLSD TWY WILL BE REMOVED. "
        "UNSERVICEABILITY MARKERS (MARKERBOARD) AND CLSD MARKINGS "
        "(YELLOW CROSS) WILL BE IN PLACE TO DEMARCATE THE CLSD TWY. "
        "THE UNSERVICEABILITY MARKERS ON CLSD TWY WILL HAVE "
        "OMNI-DIRECTIONAL FIXED RED LGT THAT WILL BE LGTD AT NGT AND IN "
        "LOW VIS COND. TWY CL LGT LEADING INTO AND WI THE CLSD TWY WILL "
        "NOT BE IN USE."
    )
    flight = _flight(notams=[
        _record(
            "SX174/24",
            "WSSS",
            "2024-11-28T00:00:00+00:00",
            "2027-12-22T23:59:00+00:00",
            text=raw_text,
            category="TWY",
        )
    ])

    findings, _ = analyse(flight)

    item = next(item for item in findings if item["engine"] == "notam")
    assert item["data"]["operational_details"] == [
        "lead_in_markings_removed",
        "markerboards_yellow_cross",
        "marker_red_lights",
        "centreline_lights_out",
    ]
    publication = item["data"]["reviewed_publication"]
    assert publication["authority"] == "CAAS"
    assert publication["publication_id"] == "AIRAC AIP SUP 174/2024"
    assert publication["reviewed_sections"] == ("2.2", "2.3", "2.4")
    assert publication["source_url"].startswith("https://aim-sg.caas.gov.sg/")


def test_taxiway_operational_detail_extraction_is_bounded_and_non_inferential() -> None:
    complete = (
        "All markings leading into the closed taxiway will be removed. "
        "Unserviceability markerboards and closed markings (yellow crosses) "
        "will demarcate the closed taxiway. Fixed red lights on "
        "unserviceability markers on the closed taxiway will be lit at night "
        "and in low visibility. "
        "Taxiway centreline lights leading into and within the closed taxiway "
        "will not be in use."
    )
    expected = engines.taxiway_operational_details(
        complete,
        "taxiway_restriction",
    )
    assert len(expected) == 4
    assert engines.taxiway_operational_details(
        complete + " " + complete,
        "taxiway_restriction",
    ) == expected
    assert engines.taxiway_operational_details(
        "TWY Z CLSD DUE WORKS.",
        "taxiway_restriction",
    ) == []
    assert not any(
        "markerboard" in detail.lower()
        for detail in engines.taxiway_operational_details(
            "Markerboards demarcate the closed taxiway.",
            "taxiway_restriction",
        )
    )
    assert not any(
        "fixed red" in detail.lower()
        for detail in engines.taxiway_operational_details(
            "Fixed red lights on unserviceability markers will be lit at night "
            "on the closed taxiway.",
            "taxiway_restriction",
        )
    )
    assert not any(
        "not in use" in detail.lower()
        for detail in engines.taxiway_operational_details(
            "Taxiway centreline lights leading into and within the closed "
            "taxiway remain in use.",
            "taxiway_restriction",
        )
    )
    assert engines.taxiway_operational_details(
        complete,
        "runway_closure",
    ) == []
    sentinel = "SENTINEL-RAW-NOT-FOR-REPORT " * 2_000
    assert engines.taxiway_operational_details(
        f"TWY Z CLSD DUE WORKS. {sentinel}",
        "taxiway_restriction",
    ) == []


def test_taxiway_summaries_never_promote_grammar_or_pavement_words_as_ids() -> None:
    flight = _flight(notams=[
        _record(
            "SX124/26",
            "WSSS",
            "2026-07-09T00:00:00+00:00",
            "2026-08-26T23:59:00+00:00",
            text=(
                "REHABILITATION WORKS OF PART OF THE TANGO TWY WITH CLOSURE OF A PART OF "
                "THE TWY AND W4 AND W5 HIGH-SPEED TURN-OFFS. CLOSURE OF HIGH-SPEED "
                "TURN-OFFS W4 AND W5. RAPID EXIT TWY INDICATOR LIGHTS ARE OFF."
            ),
            category="TWY",
        ),
        _record(
            "A4644/26",
            "WSSS",
            "2026-07-09T00:00:00+00:00",
            "2026-08-04T23:59:00+00:00",
            text=(
                "PART OF MIKE TWY CLSD TO ACFT WITH ENGINE ON. ACFT WITH ENGINES ON "
                "PROHIBITED FROM TAXIING ON TWY M BTN TWY BM3 AND BM5 EXCLUDED."
            ),
            category="TWY",
        ),
        _record(
            "SX176/24",
            "WSSS",
            "2024-10-28T05:00:00+00:00",
            "2026-10-05T15:59:00+00:00",
            text=(
                "CONSTRUCTION SURVEY LASERS WILL BE USED TO MEASURE TAXIWAY PAVEMENT "
                "ELEVATION ON TAXILANE R1, R2 AND R3."
            ),
            category="TWY",
        ),
    ])

    findings, _ = analyse(flight)
    summaries = {
        item["data"]["notam_id"]: item["summary"]
        for item in findings
        if item["engine"] == "notam"
    }

    assert "TANGO TWY SEGMENT" in summaries["SX124/26"]
    assert "W4/W5 HIGH-SPEED TURN-OFFS" in summaries["SX124/26"]
    assert "TWY M BETWEEN BM3 AND BM5" in summaries["A4644/26"]
    assert "taxilanes R1/R2/R3" in summaries["SX176/24"]
    assert all(
        bad not in " ".join(summaries.values())
        for bad in ("TWY WITH", "TWY CLSD", "TWY PAVEMENT")
    )


def test_weather_is_grouped_into_phase_window_mechanism_and_effect_with_raw_audit() -> None:
    raw_metar = "SA RJBB 161130Z 22018G32KT 4000 TSRA BKN008CB"
    raw_taf = (
        "FT RJBB 160900Z 1610/1718 22008KT 9999 FEW020 "
        "TEMPO 1612/1616 2000 TSRA BKN006CB"
    )
    flight = _flight(weather=[
        {"location": "RJBB", "record_type": "METAR", "text": raw_metar},
        {"location": "RJBB", "record_type": "TAF", "text": raw_taf},
    ])

    findings, _ = analyse(flight)

    weather = [item for item in findings if item["engine"] == "weather"]
    assert len(weather) == 1
    item = weather[0]
    assert item["data"]["phase"] == "Destination"
    assert item["data"]["utc_window"] == "16 JUL 1100Z-1300Z"
    assert "convection / thunderstorms" in item["data"]["mechanism"]
    assert item["data"]["flight_effect"] == (
        "Flight-specific operational effect is not stated by the source; "
        "review required."
    )
    assert not any(
        rejected in item["data"]["flight_effect"]
        for rejected in ("routing", "runway", "delay", "holding", "windshear")
    )
    assert raw_metar not in item["summary"]
    assert raw_taf not in item["summary"]
    assert {detail.split(":", 1)[0] for detail in item["details"]} == {
        "Phase",
        "UTC window",
        "Applicable conditions",
        "Timing",
        "Nearby observation",
        "Operational mechanism",
        "Flight effect",
        "Window status",
    }
    audit = flight["audit_evidence"]["weather"]
    assert audit["source_record_count"] == 2
    assert audit["pilot_facing_group_count"] == 1
    assert [record["raw_text"] for record in audit["records"]] == [
        raw_metar,
        raw_taf,
    ]
    assert [record["selected_for_pilot"] for record in audit["records"]] == [
        False,
        True,
    ]


def test_official_weather_source_gap_is_pilot_facing_and_fails_closed() -> None:
    flight = _flight()
    flight["official_weather_review"] = {
        "status": "review_required",
        "provider": "noaa-awc-data-api",
        "reason_codes": ["source_stale"],
        "products": {
            "TAF": {
                "source_url": (
                    "https://aviationweather.gov/api/data/taf?"
                    "format=json&ids=WSSS%2CRJBB%2CWIII"
                ),
                "retrieved_at_utc": "2026-07-16T09:00:00+00:00",
                "effective_start_utc": "2026-07-16T06:00:00+00:00",
                "effective_end_utc": "2026-07-17T06:00:00+00:00",
            },
        },
    }

    findings, warnings = analyse(flight)

    weather = [item for item in findings if item["engine"] == "weather"]
    assert len(weather) == 1
    assert weather[0]["title"] == "Official weather source review required"
    assert weather[0]["severity"] == "unknown"
    assert weather[0]["data"]["window_status"] == "review_required"
    assert weather[0]["data"]["source_references"][0]["source_url"] == (
        "https://aviationweather.gov/api/data/taf?"
        "format=json&ids=WSSS%2CRJBB%2CWIII"
    )
    assert any("Official public METAR/TAF coverage is incomplete" in warning for warning in warnings)


def test_tcu_alone_does_not_create_a_bad_weather_warning() -> None:
    flight = _flight(weather=[{
        "location": "RJBB",
        "record_type": "METAR",
        "text": "METAR RJBB 161130Z 22008KT 9999 FEW018TCU SCT120 28/24 Q1010 NOSIG",
    }])

    findings, _ = analyse(flight)

    item = next(row for row in findings if row["engine"] == "weather")
    assert item["severity"] == "information"
    assert item["data"]["window_status"] == "no_significant_observation"
    assert "thunderstorm" not in item["data"]["mechanism"].lower()


def test_weather_group_suppresses_benign_jargon_and_duplicate_mechanisms() -> None:
    flight = _flight(weather=[
        {"location": "RJBB", "record_type": "METAR", "text": "SA RJBB 161130Z 22008KT CAVOK"},
        {"location": "RJBB", "record_type": "TAF", "text": "FT RJBB 161100Z TEMPO 1612/1616 4000 TSRA BKN008CB"},
        {"location": "RJBB", "record_type": "TAF", "text": "FT RJBB 161130Z TEMPO 1612/1616 3000 TSRA"},
    ])

    findings, _ = analyse(flight)
    item = next(row for row in findings if row["engine"] == "weather")

    assert "convection / thunderstorms" in item["data"]["mechanism"]
    assert "trigger" not in item["summary"].lower()
    assert item["details"].count("Operational mechanism: convection / thunderstorms.") == 1


def test_destination_taf_excludes_significant_group_outside_arrival_window() -> None:
    flight = _flight(weather=[{
        "location": "RJBB",
        "record_type": "TAF",
        "text": (
            "FT 241700 2418/2600 16009KT 9999 FEW015 SCT020 "
            "TEMPO 2502/2505 3000 TSRA FEW012CB BKN015="
        ),
    }])
    flight["scheduled_departure_utc"] = "2026-07-25T02:15:00+00:00"
    flight["scheduled_arrival_utc"] = "2026-07-25T21:30:00+00:00"

    findings, _ = analyse(flight)

    item = next(row for row in findings if row["engine"] == "weather")
    assert item["severity"] == "information"
    assert item["data"]["window_status"] == "no_significant_overlap"
    assert item["data"]["mechanism"] == "None in time-overlapping forecast groups"
    assert "02:00Z-05:00Z" in item["data"]["timing"]
    assert "outside this window" in item["data"]["timing"]
    assert "No significant weather group overlaps this window" in item["summary"]
    assert "Arrival routing" not in item["summary"]
    assert flight["audit_evidence"]["weather"]["records"][0]["raw_text"].endswith("BKN015=")
    panel_weather = _weather_summary(findings, "RJBB", "destination")
    assert "No significant weather group overlaps this window" in panel_weather["primary"]
    assert "02:00Z-05:00Z" in panel_weather["primary"]
    assert "Arrival routing" not in panel_weather["primary"]


def test_weather_uses_sixty_minutes_without_changing_notam_arrival_window() -> None:
    flight = _flight(weather=[{
        "location": "RJBB",
        "record_type": "TAF",
        "text": (
            "FT 160900 1610/1615 16009KT 9999 FEW015 "
            "TEMPO 1613/1614 3000 TSRA BKN015CB="
        ),
    }])

    findings, _ = analyse(flight)

    item = next(row for row in findings if row["engine"] == "weather")
    assert item["data"]["utc_window"] == "16 JUL 1100Z-1300Z"
    assert item["data"]["window_status"] == "no_significant_overlap"
    assert "13:00Z-14:00Z" in item["data"]["timing"]
    assert flight["weather_window_preference"] == {
        "before_minutes": 60,
        "after_minutes": 60,
        "basis": "scheduled_phase_reference",
    }

    _, weather_start, weather_end = _weather_role_window(
        flight,
        "RJBB",
        {"WIII"},
        {},
    )
    _, notam_start, notam_end = _notam_role_window(
        flight,
        "RJBB",
        {"WIII"},
        {},
    )
    assert weather_start.isoformat() == "2026-07-16T11:00:00+00:00"
    assert weather_end.isoformat() == "2026-07-16T13:00:00+00:00"
    assert notam_start.isoformat() == "2026-07-16T10:00:00+00:00"
    assert notam_end.isoformat() == "2026-07-16T14:00:00+00:00"

    flight["weather_window_preference"] = {
        "before_minutes": 45,
        "after_minutes": 75,
    }
    _, custom_start, custom_end = _weather_role_window(
        flight,
        "RJBB",
        {"WIII"},
        {},
    )
    _, unchanged_notam_start, unchanged_notam_end = _notam_role_window(
        flight,
        "RJBB",
        {"WIII"},
        {},
    )
    assert custom_start.isoformat() == "2026-07-16T11:15:00+00:00"
    assert custom_end.isoformat() == "2026-07-16T13:15:00+00:00"
    assert unchanged_notam_start == notam_start
    assert unchanged_notam_end == notam_end


def test_destination_taf_keeps_significant_group_overlapping_arrival_window() -> None:
    flight = _flight(weather=[{
        "location": "RJBB",
        "record_type": "TAF",
        "text": (
            "FT 241700 2418/2600 16009KT 9999 FEW015 SCT020 "
            "TEMPO 2520/2523 3000 TSRA FEW012CB BKN015="
        ),
    }])
    flight["scheduled_departure_utc"] = "2026-07-25T02:15:00+00:00"
    flight["scheduled_arrival_utc"] = "2026-07-25T21:30:00+00:00"

    findings, _ = analyse(flight)

    item = next(row for row in findings if row["engine"] == "weather")
    assert item["severity"] == "warning"
    assert item["data"]["window_status"] == "pertinent"
    assert "convection / thunderstorms" in item["data"]["mechanism"]
    assert "20:30Z-22:30Z" in item["data"]["timing"]
    assert item["data"]["flight_effect"] == (
        "Flight-specific operational effect is not stated by the source; "
        "review required."
    )


@pytest.mark.parametrize(
    "phase",
    ("Departure", "Destination", "Destination alternate", "EDTO", "Enroute"),
)
def test_weather_fallback_never_invents_phase_specific_operational_effects(
    phase: str,
) -> None:
    item = concise_weather_finding({
        "engine": "weather",
        "severity": "warning",
        "title": f"{phase} weather",
        "summary": "",
        "details": [],
        "data": {
            "phase": phase,
            "utc_window": "16 JUL 1000Z-1400Z",
            "mechanism": "convection / thunderstorms",
        },
    })

    effect = item["data"]["flight_effect"]
    assert effect == (
        "Flight-specific operational effect is not stated by the source; "
        "review required."
    )
    assert not any(
        rejected in effect
        for rejected in (
            "routing",
            "runway",
            "delay",
            "holding",
            "windshear",
            "approach minima",
            "alternate use",
            "flight-level strategy",
        )
    )


def test_destination_taf_incomplete_coverage_fails_closed() -> None:
    flight = _flight(weather=[{
        "location": "RJBB",
        "record_type": "TAF",
        "text": "FT 241700 2418/2518 16009KT 9999 FEW015 SCT020=",
    }])
    flight["scheduled_departure_utc"] = "2026-07-25T02:15:00+00:00"
    flight["scheduled_arrival_utc"] = "2026-07-25T21:30:00+00:00"

    findings, _ = analyse(flight)

    item = next(row for row in findings if row["engine"] == "weather")
    assert item["severity"] == "warning"
    assert item["data"]["window_status"] == "review_required"
    assert "does not fully cover" in item["data"]["timing"]
    assert "review required" in item["summary"].lower()


def test_incomplete_lido_pages_fail_before_zero_value_analysis() -> None:
    page = "\n".join(
        (
            "9VAAA SQ123 SIN/KIX ETD 1000 16JUL26",
            "SCHED DEP 1000 UTC SCHED ARR 1800 UTC",
        )
    )
    with pytest.raises(ValueError, match="Incomplete or unsupported Lido OFP"):
        parse_lido([page], "partial.pdf")


def test_lido_parser_keeps_sid_and_star_names_instead_of_airport_tokens() -> None:
    pages = [
        """SUMMARY STANDARD CFP
9VAAA SQ722 SIN/BKK ETD 0250 01AUG26
SCHED DEP 0250 UTC SCHED ARR 0520 UTC
RTE NO 001 A350-941
WSSS/20C VMR B469 VPK
VTBS/20R
GND  MILES    900
AIR  MILES    930
BURNOFF 02.00 010000
TAXI FUEL 001000
FLT PLAN REQMT 03.00 015000
FUEL IN TANKS 04.00 020000
PZFW 180000
PTOW 200000
PLWT 190000
""",
        "",
        "SID: WSSS/20C VMR9B",
        "",
        "STAR: VTBS/20R TUMGA1C",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]

    flight = parse_lido(pages, "procedures.pdf")

    assert flight["sid"] == "VMR9B"
    assert flight["sid_source_page"] == 3
    assert flight["star"] == "TUMGA1C"
    assert flight["star_source_page"] == 5


@pytest.mark.parametrize(
    ("label", "declaration"),
    (
        ("SID", "SID: NIL"),
        ("SID", "SID: NONE"),
        ("SID", "SID: N/A"),
        ("SID", "SID: WSSS/20C"),
        ("SID", "SID: NOT AVAILABLE"),
        ("STAR", "STAR: NOT STATED"),
        ("SID", "SID: WSSS/20C NOT AVAILABLE"),
        ("STAR", "STAR: VTBS/20R NOT STATED - USE ATC ASSIGNMENT"),
    ),
)
def test_named_procedure_rejects_non_procedure_declarations(
    label: str,
    declaration: str,
) -> None:
    assert _parse_named_procedure([declaration], label) == (None, None)


def test_named_procedure_stays_on_its_label_line_and_accepts_trailing_context() -> None:
    page = "\n".join(
        (
            "SID: WSSS/20C",
            "STAR: VTBS/20R TUMGA1C",
            "SID: WSSS/20C VMR9B TRANSITION",
        )
    )

    assert _parse_named_procedure([page], "SID") == ("VMR9B", 1)
    assert _parse_named_procedure([page], "STAR") == ("TUMGA1C", 1)
    assert _parse_named_procedure(["SID: WSSS/20C NOTUS1A"], "SID") == (
        "NOTUS1A",
        1,
    )


def test_edto_periods_follow_overnight_flight_dates() -> None:
    pages = [
        """SUMMARY EDTO CFP
9VAAA SQ123 SIN/KIX ETD 2200 16JUL26
SCHED DEP 2200 UTC SCHED ARR 0400 UTC
RTE NO 001 A350-941
WSSS/20C
DCT BOBI1 DCT BOBI2
RJBB/24L
GND  MILES    5984
AIR  MILES    6197
BURNOFF 11.30 050000
TAXI FUEL 001000
FLT PLAN REQMT 13.00 060000
FUEL IN TANKS 14.00 065000
PZFW 180000
PTOW 245000
PLWT 195000
""",
        """EDTO INFORMATION
RJAA 0100-0300 16L ILS 200FT
RPLL 2300-0100 06 ILS 200FT
""",
        "",
        "",
        "",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]

    flight = parse_lido(pages, "overnight.pdf")
    periods = {item["airport"]: item for item in flight["edto"]["airports"]}

    assert periods["RJAA"]["period_start_utc"] == "2026-07-17T01:00:00+00:00"
    assert periods["RJAA"]["period_end_utc"] == "2026-07-17T03:00:00+00:00"
    assert periods["RPLL"]["period_start_utc"] == "2026-07-16T23:00:00+00:00"
    assert periods["RPLL"]["period_end_utc"] == "2026-07-17T01:00:00+00:00"
    assert flight["ground_distance_nm"] == 5984
    assert flight["air_distance_nm"] == 6197


def test_edto_parser_preserves_every_numbered_sector_and_explicit_point() -> None:
    sectors = _parse_edto_sectors(
        """EDTO INFORMATION:
       2.39 N5405.3 CYQX
ENTRY1      W04650.1
       3.17 N5623.3 CYQX 36 180 777
 1E    ..... W03701.3 EINN 39 180 996
       4.17 N5600.4 EINN
EXIT1       W01937.0
      15.13 N1551.2 VECC
ENTRY2      E09020.3
      15.13 N1551.2 VTSP 44 260 661
 1E    ..... E09020.3 VTSP 44 260 661
      15.42 N1302.8 VTSP
EXIT2       E09313.0
"""
    )

    assert [sector["number"] for sector in sectors] == [1, 2]
    assert [
        (sector["entry_actm_minutes"], sector["exit_actm_minutes"])
        for sector in sectors
    ] == [(159, 257), (913, 942)]
    assert sectors[0]["entry"]["name"] == "ENTRY1"
    assert sectors[1]["exit"]["name"] == "EXIT2"
    assert sectors[0]["etps"][0]["label"] == "1E"
    assert sectors[0]["etps"][0]["airports"] == ["CYQX", "EINN"]
    assert sectors[1]["etp_actm_minutes"] == [913]


def test_edto_airport_parser_does_not_consume_row_after_blank_approach() -> None:
    airports = _parse_edto_airports(
        """EDTO ENROUTE ALTN AIRPORTS:
APT      PERIOD CHKD       RWY           APCH             MINIMA
PGUM     1737-2046         24R     CIRC VORDME@06L     1035FT/4316M
RJTT     1830-2300         34R           CAT2           300FT/1350M
RJCC     2037-0020         01R       CAT1+VORDME        452FT/1550M
PASY     2155-0140          28                          400FT/2409M
PACD     2311-0509          15    RNAV GPS LNAV/VNAV    700FT/2250M
KSFO     0220-0509         28R          CAT3A           250FT/1000M
""",
        datetime(2026, 8, 15, 11, 55, tzinfo=UTC),
        datetime(2026, 8, 16, 3, 35, tzinfo=UTC),
    )

    assert [item["airport"] for item in airports] == [
        "PGUM", "RJTT", "RJCC", "PASY", "PACD", "KSFO"
    ]
    pasy = next(item for item in airports if item["airport"] == "PASY")
    pacd = next(item for item in airports if item["airport"] == "PACD")
    assert pasy["approach"] == ""
    assert pasy["minima"] == "400FT/2409M"
    assert pacd["approach"] == "RNAV GPS LNAV/VNAV"
    assert pacd["minima"] == "700FT/2250M"


def test_edto_parser_pairs_unnumbered_southern_hemisphere_boundaries() -> None:
    sectors = _parse_edto_sectors(
        """EDTO INFORMATION:
       2.06 S1335.5 WARR
ENTRY.....  E10926.3
       2.06 S1335.5 WIII 124 230 479
 1E    ..... E10926.3 WIII 124 230 479
       2.26 S1609.4 YPLM
EXIT .....  E11020.9
"""
    )

    assert len(sectors) == 1
    assert sectors[0]["number"] == 1
    assert sectors[0]["entry_actm_minutes"] == 126
    assert sectors[0]["exit_actm_minutes"] == 146
    assert sectors[0]["entry"]["name"] == "ENTRY1"
    assert sectors[0]["exit"]["name"] == "EXIT1"
    assert sectors[0]["entry"]["latitude"] < 0
    assert sectors[0]["exit"]["latitude"] < 0
    assert sectors[0]["entry"]["longitude"] > 0


def test_bobcat_allocation_accepts_lido_commas_and_suffix() -> None:
    pages = [
        """SUMMARY EDTO CFP
BOBCAT ALLOCATION:
WPT BOBI1, FL360, CTO 2215, CTOT 2205(10MIN)DLY
9VAAA SQ123 SIN/KIX ETD 2200 16JUL26
SCHED DEP 2200 UTC SCHED ARR 0400 UTC
RTE NO 001 A350-941
WSSS/20C
DCT BOBI1 DCT BOBI2
RJBB/24L
BURNOFF 11.30 050000
TAXI FUEL 001000
FLT PLAN REQMT 13.00 060000
FUEL IN TANKS 14.00 065000
PZFW 180000
PTOW 245000
PLWT 195000
""",
        "",
        "",
        "",
        "",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]

    flight = parse_lido(pages, "bobcat.pdf")

    assert flight["bobcat"] == {
        "waypoint": "BOBI1",
        "flight_level": 360,
        "cto_utc": "2026-07-16T22:15:00+00:00",
        "ctot_utc": "2026-07-16T22:05:00+00:00",
    }


def test_depressurisation_profiles_require_aircraft_effectivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "10-4",
                "from": "RANAH",
                "to": "HILAL",
                "from_aliases": ["RANAH"],
                "to_aliases": ["HILAL"],
                "airways": ["L750", "G202"],
                "critical": "DUDEG",
                "critical_aliases": ["DUDEG"],
                "effectivity": ["A350-941"],
            }
        ],
    )
    waypoints = [
        {"name": "RANAH", "actm_minutes": 1, "msa_hundreds_ft": 90, "airway_in": "L750"},
        {"name": "DUDEG", "actm_minutes": 2, "msa_hundreds_ft": 146, "airway_in": "L750"},
        {"name": "HILAL", "actm_minutes": 3, "msa_hundreds_ft": 90, "airway_in": "G202"},
    ]
    events = detect_terrain_events(waypoints)
    supported = match_profiles({"aircraft_type": "A350-941", "route_waypoints": waypoints}, events)
    unsupported = match_profiles({"aircraft_type": "C172", "route_waypoints": waypoints}, events)
    assert [item["profile"]["chart"] for item in supported] == ["10-4"]
    assert unsupported == []


def test_bobcat_midnight_rollover_reconciles_without_false_difference() -> None:
    waypoint = {
        "name": "BOB",
        "actm_minutes": 60,
        "fir_boundary": None,
        "msa_hundreds_ft": None,
        "vws": None,
        "airway_in": None,
    }
    flight = _flight(route_waypoints=[waypoint])
    flight["bobcat"] = {
        "waypoint": "BOB",
        "flight_level": 300,
        "ctot_utc": "2026-07-16T23:30:00+00:00",
        "cto_utc": "2026-07-16T00:30:00+00:00",
    }
    findings, _ = analyse(flight)
    bobcat = next(item for item in findings if item["engine"] == "bobcat")
    timeline = next(item for item in findings if item["engine"] == "timeline")
    assert bobcat["data"]["difference_minutes"] == 0
    assert bobcat["severity"] == "information"
    assert any("BOBCAT BOB" in detail for detail in timeline["details"])


def test_unapproved_communication_samples_fail_closed() -> None:
    waypoint = {
        "name": "-VOMF",
        "actm_minutes": 10,
        "fir_boundary": "VOMF",
        "msa_hundreds_ft": None,
        "vws": None,
        "airway_in": None,
    }
    findings, _ = analyse(_flight(route_waypoints=[waypoint]))
    communication = next(
        item
        for item in findings
        if item["engine"] == "communications"
    )
    assert communication["severity"] == "unknown"
    assert communication["title"] == "FIR communication review required"
    assert "approved communication procedures are unavailable" in communication["summary"]
    assert all("ACTM 00.00" not in item["summary"] for item in findings)
    assert all("Chennai ATS/FIS" not in str(item) for item in findings)


def test_unapproved_mel_sample_does_not_publish_sample_conditions() -> None:
    flight = _flight()
    flight["deferred_items"] = [{
        "item_type": "MEL",
        "reference": "30-81-01A",
        "description": "Ice detection system inoperative",
        "company_remark": None,
    }]

    findings, _ = analyse(flight)

    mel = next(item for item in findings if item["engine"] == "mel")
    assert mel["severity"] == "unknown"
    assert mel["summary"] == "Current approved MEL evidence is unavailable."
    assert "Repair interval" not in str(mel)
    assert "anti-ice operational procedure" not in str(mel)


def test_bobcat_summary_states_the_allocation_not_only_the_delta() -> None:
    """
    The printed reports render a finding's summary line and not its evidence
    list, so a summary carrying only "predicted CTO difference -1 min" left the
    crossing level, the CTOT and the allocated CTO out of the brief the boss
    opens offline. The allocation is held in the CFP and belongs on that line.
    """
    pages = [
        """SUMMARY EDTO CFP
BOBCAT ALLOCATION: WPT BOBI1 FL 380 CTO 2215 CTOT 2205
9VAAA SQ123 SIN/KIX ETD 2200 16JUL26
SCHED DEP 2200 UTC SCHED ARR 0400 UTC
RTE NO 001 A350-941
WSSS/20C
DCT BOBI1 DCT BOBI2
RJBB/24L
BURNOFF 11.30 050000
TAXI FUEL 001000
FLT PLAN REQMT 13.00 060000
FUEL IN TANKS 14.00 065000
PZFW 180000
PTOW 245000
PLWT 195000
""",
        "",
        "",
        "",
        "",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]

    flight = parse_lido(pages, "bobcat.pdf")
    findings, _ = engines.analyse(flight)
    bobcat = next(item for item in findings if item["engine"] == "bobcat")

    summary = bobcat["summary"]
    assert "BOBI1" in summary
    assert "FL380" in summary
    assert "2205Z" in summary, "the allocated CTOT must be printed"
    assert "2215Z" in summary, "the allocated CTO must be printed"
    # ACTM 00.15 after CTOT 2205Z is 2220Z, five minutes after the allocated CTO.
    assert "2220Z" in summary, "the computed crossing time must be printed"
    assert "+5 min" in summary


def test_cfp_volcano_advisories_stop_at_page_separators_and_next_fir() -> None:
    page = """
            VAA TAAL
--------------------
1B4233/26                 VALID: 20-AUG-26 0115 - 21-AUG-26 0100 EST
  TAAL VOLCANO ON ALERT LVL 1.
  FLT OPS ARE ADZ TO AVOID FLY CLOSE TO THE VOLCANO.
  F) SFC G) FL110
===================================================
AREA ENROUTE DESTINATION - DESTINATION ALTERNATE(S)
===================================================
            VAA KANLAON
-----------------------
1B4236/26                 VALID: 20-AUG-26 0140 - 20-AUG-26 2124 EST
  ERUPTION OF VOLCANO KANLAON.
  SOURCE OF INFO: PHIVOLCS VONA
  F) SFC G) FL110
RCAA        TAIPEI FIR
----------------------
1A600/26                  VALID: 16-MAR-26 0000 - 31-MAR-27 2359 EST
  UNRELATED AIR TRAFFIC FLOW MANAGEMENT NOTICE.
"""

    advisories = _parse_cfp_volcano_advisories(
        [page],
        datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert [item["volcano"] for item in advisories] == ["TAAL", "KANLAON"]
    assert "FLT OPS ARE ADZ" in advisories[0]["text"]
    assert "=" not in advisories[0]["text"]
    assert "RCAA" not in advisories[1]["text"]
    assert "AIR TRAFFIC FLOW" not in advisories[1]["text"]
