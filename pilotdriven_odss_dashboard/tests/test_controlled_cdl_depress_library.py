from __future__ import annotations

from datetime import timezone

import pytest

from app.odss import engines
from app.odss.controlled_library import (
    aircraft_effectivity_tokens,
    load_depress_profiles,
    select_cdl_variants,
)
from app.odss.engines import analyse, detect_terrain_events, match_profiles
from app.odss.parser import _parse_deferred_items

UTC = timezone.utc


def _flight(route_waypoints: list[dict] | None = None) -> dict:
    return {
        "document_id": "test.pdf",
        "flight_number": "SQ24",
        "flight_date": "22JUL26",
        "aircraft_type": "A350-941",
        "registration": "9V-SGE",
        "departure": "WSSS",
        "destination": "KJFK",
        "departure_runway": "20C",
        "destination_runway": "22L",
        "scheduled_departure_utc": "2026-07-22T04:10:00+00:00",
        "scheduled_arrival_utc": "2026-07-22T22:50:00+00:00",
        "route_text": "",
        "route_waypoints": route_waypoints or [],
        "planned_level_profile": None,
        "cost_index": 70,
        "edto_rvsm": "EDTO/RVSM",
        "bobcat": None,
        "deferred_items": [],
        "alternates": [],
        "performance": {},
        "fuel": {
            "trip_fuel_kg": 106_345,
            "contingency_fuel_kg": 1_031,
            "alternate_fuel_kg": 2_119,
            "alternate_holding_fuel_kg": 2_174,
            "taxi_fuel_kg": 600,
            "flight_plan_required_fuel_kg": 112_269,
            "excess_fuel_kg": 6_100,
            "fuel_in_tanks_kg": 118_369,
            "planned_destination_fuel_kg": 11_424,
        },
        "masses": {
            "planned_zfw_kg": 162_231,
            "planned_takeoff_weight_kg": 280_000,
            "planned_landing_weight_kg": 173_655,
        },
        "edto": {
            "entry_actm_minutes": None,
            "exit_actm_minutes": None,
            "etp_actm_minutes": [],
            "airports": [],
        },
        "notams": [],
        "weather": [],
    }


def _wp(
    name: str,
    actm: int,
    msa: int,
    airway: str | None,
    *,
    star: bool = False,
) -> dict:
    return {
        "name": name,
        "actm_minutes": actm,
        "fir_boundary": None,
        "latitude": None,
        "longitude": None,
        "msa_hundreds_ft": msa,
        "msa_asterisk": star,
        "vws": None,
        "airway_in": airway,
    }


def test_page1_parser_recognises_upper_block_cdl_reference() -> None:
    page1 = "\n".join(
        (
            "SUMMARY EDTO CFP",
            "AA CDL 28-01",
            "FUEL JETTISON TUBES MISSING",
            "BOTH TUBES REMOVED",
            "PLAN 32/0/1",
            "RTE NO 123 A350-941",
        )
    )
    assert _parse_deferred_items(page1) == [
        {
            "reference": "28-01",
            "description": "FUEL JETTISON TUBES MISSING",
            "item_type": "CDL",
            "company_remark": "BOTH TUBES REMOVED",
        }
    ]


def test_aircraft_series_effectivity_tokens() -> None:
    assert aircraft_effectivity_tokens("9V-SGE", "A350-941") == {"A350941", "ULR"}
    assert aircraft_effectivity_tokens("9V-SMA", "A350-941") == {"A350941", "LH"}
    assert aircraft_effectivity_tokens("9V-SHA", "A350-941") == {"A350941", "MH"}


def test_cdl_variant_selection_is_registration_specific() -> None:
    record = {
        "variants": [
            {"applicable_registrations": ["9V-SGE"], "component": "ULR VARIANT"},
            {"applicable_registrations": ["9V-SMA"], "component": "LH VARIANT"},
        ]
    }
    assert [item["component"] for item in select_cdl_variants(record, "9VSGE")] == [
        "ULR VARIANT"
    ]
    assert select_cdl_variants(record, "9V-SHA") == []


def test_controlled_cdl_finding_includes_penalties_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "reference": "28-01",
        "title": "Fuel Jettison Tube",
        "source_pages": [241],
        "variants": [
            {
                "quantity_installed": "2",
                "component": "FUEL JETTISON TUBE",
                "applicable_registrations": ["9V-SGE"],
                "dispatch_conditions": "All may be missing provided that the jettison system is deactivated.",
                "limitations": None,
                "notes": ["May be combined with any other item listed in CDL-28 chapter."],
                "maintenance_references": ["A350-A-28-31-XX-00ZZZ-560Z-A"],
                "mel_references": ["MEL/MI-28-31"],
                "takeoff_approach_penalty_kg_values": [60],
                "enroute_penalty_kg_values": [],
                "fuel_penalty_percent_values": [],
            }
        ],
    }
    monkeypatch.setattr(engines, "CDL_REFERENCES", {"28-01": record})
    monkeypatch.setattr(
        engines,
        "CDL_LIBRARY_METADATA",
        {"title": "SIA A350 Fleet CDL", "issue_date": "2026-05-05", "status": "controlled-index-loaded"},
    )
    flight = _flight()
    flight["deferred_items"] = [
        {
            "item_type": "CDL",
            "reference": "28-01",
            "description": "FUEL JETTISON TUBES MISSING",
            "company_remark": "BOTH TUBES REMOVED",
        }
    ]
    findings, _ = analyse(flight)
    result = next(item for item in findings if item["engine"] == "cdl")
    assert result["data"]["source_pages"] == [241]
    assert result["data"]["takeoff_approach_penalty_kg_values"] == [60]
    assert any("jettison system is deactivated" in detail for detail in result["details"])


def test_asterisk_qualifies_exact_100_as_high_msa() -> None:
    waypoints = [
        _wp("BEFORE", 1, 90, "DCT"),
        _wp("STAR100", 2, 100, "DCT", star=True),
        _wp("DROP", 3, 90, "DCT"),
    ]
    events = detect_terrain_events(waypoints)
    assert len(events) == 1
    assert events[0]["first_high"]["name"] == "STAR100"


def test_sq24_high_msa_uses_minimal_11_4_and_11_37_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("HAMND", 682, 72, "A590"),
        _wp("TED", 698, 129, "DCT", star=True),
        _wp("GKN", 714, 157, "J511", star=True),
        _wp("ORT", 726, 190, "J124", star=True),
        _wp("63N40", 732, 76, "DCT"),
        _wp("63N30", 764, 111, "DCT", star=True),
        _wp("62N20", 797, 111, "DCT", star=True),
        _wp("59N10", 837, 48, "DCT"),
    ]
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", load_depress_profiles())
    events = detect_terrain_events(waypoints)
    matches = match_profiles(
        {
            "aircraft_type": "A350-941",
            "registration": "9V-SGE",
            "route_waypoints": waypoints,
        },
        events,
    )
    assert [item["profile"]["chart"] for item in matches] == ["11-4", "11-37"]
    assert all(item["coverage_complete"] for item in matches)
