from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss.engines import _schedule_overlaps, analyse, detect_terrain_events, match_profiles
from app.odss.enrichment import _notice_score, _parse_airport_notams, _parse_notam_datetime
from app.odss.parser import parse_lido


UTC = timezone.utc


def _record(
    notam_id: str,
    location: str,
    valid_from: str,
    valid_to: str | None,
    schedule: str | None = None,
) -> dict:
    return {
        "notam_id": notam_id,
        "location": location,
        "category": "RWY",
        "text": "RWY CLSD",
        "valid_from_utc": valid_from,
        "valid_to_utc": valid_to,
        "schedule": schedule,
        "schedule_review": False,
        "validity_review": False,
        "priority_score": 10,
    }


def _flight(
    notams: list[dict] | None = None,
    route_waypoints: list[dict] | None = None,
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
        "weather": [],
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


def test_destination_and_alternate_notams_use_arrival_phase() -> None:
    notams = [
        _record("DESTOLD/26", "RJBB", "2026-07-16T09:30:00+00:00", "2026-07-16T10:30:00+00:00"),
        _record("DESTNOW/26", "RJBB", "2026-07-16T11:30:00+00:00", "2026-07-16T12:30:00+00:00"),
        _record("ALTNOLD/26", "WIII", "2026-07-16T09:30:00+00:00", "2026-07-16T10:30:00+00:00"),
        _record("ALTNNOW/26", "WIII", "2026-07-16T11:30:00+00:00", "2026-07-16T12:30:00+00:00"),
    ]
    findings, _ = analyse(_flight(notams=notams))
    notam_findings = [item for item in findings if item["engine"] == "notam"]
    ids = {item["data"]["notam_id"] for item in notam_findings}
    roles = {item["data"]["notam_id"]: item["data"]["role"] for item in notam_findings}
    assert ids == {"DESTNOW/26", "ALTNNOW/26"}
    assert roles == {"DESTNOW/26": "destination", "ALTNNOW/26": "destination alternate"}


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


def test_zero_actm_action_is_kept_in_timeline() -> None:
    waypoint = {
        "name": "-VOMF",
        "actm_minutes": 10,
        "fir_boundary": "VOMF",
        "msa_hundreds_ft": None,
        "vws": None,
        "airway_in": None,
    }
    findings, _ = analyse(_flight(route_waypoints=[waypoint]))
    timeline = next(item for item in findings if item["engine"] == "timeline")
    assert any("ACTM 00.00 - Early ATC/FIR action before VOMF" in detail for detail in timeline["details"])
