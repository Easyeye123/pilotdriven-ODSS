from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss.engines import _schedule_overlaps, analyse, detect_terrain_events, match_profiles
from app.odss.enrichment import (
    _notice_score,
    _parse_airport_notams,
    _parse_notam_datetime,
    _record_source_page,
)
from app.odss.briefing import _weather_summary
from app.odss.parser import _parse_edto_sectors, parse_lido


UTC = timezone.utc


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
    findings, _ = analyse(_flight(notams=notams))
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


def test_notam_pilot_view_is_bounded_but_audit_retains_every_applicable_record() -> None:
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

    selected = [item for item in findings if item["engine"] == "notam"]
    assert len(selected) == 24
    assert selected[0]["data"]["notam_id"] == "RWYTOP/26"
    audit = flight["audit_evidence"]["notam"]
    assert audit["source_record_count"] == 31
    assert audit["time_applicable_count"] == 31
    assert audit["pilot_facing_count"] == 24
    assert audit["audit_only_count"] == 7


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
    assert item["data"]["utc_window"] == "16 JUL 1000Z-1400Z"
    assert "convection / thunderstorms" in item["data"]["mechanism"]
    assert "Arrival routing" in item["data"]["flight_effect"]
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
    assert "20:00Z-23:00Z" in item["data"]["timing"]
    assert "Arrival routing" in item["data"]["flight_effect"]


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
    with pytest.raises(ValueError, match="Incomplete or unsupported Lido CFP"):
        parse_lido([page], "partial.pdf")


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


def test_depressurisation_profiles_require_aircraft_effectivity() -> None:
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
