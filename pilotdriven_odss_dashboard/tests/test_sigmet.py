from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss import vaa
from app.odss.constants import ENGINE_ORDER
from app.odss.engines import analyse
from app.odss.sigmet import assess_significant_weather
from app.odss.vaa import fetch_awc_snapshot, filter_awc_snapshot
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def _flight() -> dict:
    return {
        "flight_number": "TEST1",
        "departure": "AAAA",
        "destination": "BBBB",
        "scheduled_departure_utc": "2026-07-22T04:00:00+00:00",
        "scheduled_arrival_utc": "2026-07-22T06:00:00+00:00",
        "planned_level_profile": "START/350",
        "route_waypoints": [
            {
                "name": "START",
                "actm_minutes": 0,
                "latitude": 0.0,
                "longitude": 100.0,
                "msa_hundreds_ft": 4,
                "vws": 1,
            },
            {
                "name": "END",
                "actm_minutes": 120,
                "latitude": 0.0,
                "longitude": 110.0,
                "msa_hundreds_ft": 4,
                "vws": 1,
            },
        ],
        "weather": [],
        "notams": [],
        "deferred_items": [],
        "performance": {},
        "masses": {
            "planned_zfw_kg": 100_000,
            "planned_takeoff_weight_kg": 110_000,
            "planned_landing_weight_kg": 105_000,
        },
        "fuel": {
            "trip_fuel_kg": 5_000,
            "contingency_fuel_kg": 500,
            "alternate_fuel_kg": 800,
            "alternate_holding_fuel_kg": 0,
            "taxi_fuel_kg": 100,
            "flight_plan_required_fuel_kg": 9_000,
            "excess_fuel_kg": 0,
            "fuel_in_tanks_kg": 10_000,
            "planned_destination_fuel_kg": 5_000,
        },
        "alternates": [],
        "edto": {
            "entry_actm_minutes": None,
            "exit_actm_minutes": None,
            "etp_actm_minutes": [],
            "airports": [],
        },
        "personal_notes": [],
    }


def _record(hazard: str, *, base: int | None = 30000, top: int | None = 40000) -> dict:
    return {
        "hazard": hazard,
        "firId": "TEST",
        "seriesId": f"{hazard}-1",
        "validTimeFrom": "2026-07-22T04:30:00Z",
        "validTimeTo": "2026-07-22T05:30:00Z",
        "base": base,
        "top": top,
        "coords": [
            {"lon": 104.0, "lat": -2.0},
            {"lon": 106.0, "lat": -2.0},
            {"lon": 106.0, "lat": 2.0},
            {"lon": 104.0, "lat": 2.0},
        ],
        "rawSigmet": f"TEST {hazard} SIGMET",
    }


def _snapshot(advisories: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "provider": "noaa-awc-international-sigmet",
        "source_url": "https://aviationweather.gov/api/data/isigmet?format=json",
        "status": "available",
        "retrieved_at_utc": "2026-07-22T03:55:00+00:00",
        "coverage_status": "global_current_active_sigmet",
        "coverage_start_utc": "2026-07-22T03:00:00+00:00",
        "coverage_end_utc": "2026-07-22T07:00:00+00:00",
        "freshness_status": "fresh",
        "advisories": advisories,
        "parse_warnings": [],
        "raw_record_count": len(advisories),
        "raw_sha256": "snapshot-sha",
    }


def test_one_awc_snapshot_normalises_all_supported_sigmet_hazards() -> None:
    payload = [
        _record("TS", base=None),
        _record("TURB"),
        _record("VA", base=0),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
            headers={"Date": "Wed, 22 Jul 2026 03:55:00 GMT"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(
            client=client,
            now=datetime(2026, 7, 22, 3, 55, tzinfo=timezone.utc),
            hazard_code="ALL",
        )

    assert snapshot["hazard_code"] == "ALL"
    assert snapshot["advisory_count"] == 3
    assert {item["hazard"] for item in snapshot["advisories"]} == {"TS", "TURB", "VA"}
    thunderstorm = next(item for item in snapshot["advisories"] if item["hazard"] == "TS")
    assert thunderstorm["lower_flight_level"] == 0


def test_live_hazard_views_reuse_one_governed_awc_receipt(monkeypatch) -> None:
    calls: list[str] = []
    all_snapshot = _snapshot([])

    def fake_fetch(*, hazard_code: str = "VA", **_kwargs):
        calls.append(hazard_code)
        return all_snapshot

    monkeypatch.setattr(vaa, "fetch_awc_snapshot", fake_fetch)
    vaa._CACHE_BY_HAZARD.clear()

    vaa.live_awc_snapshot()
    vaa.live_vaa_snapshot("VA")
    vaa.live_vaa_snapshot("TC")

    assert calls == ["ALL"]


def test_general_sigmet_review_excludes_dedicated_va_and_tc_paths() -> None:
    all_snapshot = _snapshot([
        {
            **_record("TS", base=None),
            "advisory_id": "TS-1",
            "valid_from_utc": "2026-07-22T04:30:00+00:00",
            "valid_to_utc": "2026-07-22T05:30:00+00:00",
            "lower_flight_level": 0,
            "upper_flight_level": 400,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[104.0, -2.0], [106.0, -2.0], [106.0, 2.0], [104.0, 2.0], [104.0, -2.0]]],
            },
        },
        {
            **_record("VA", base=0),
            "advisory_id": "VA-1",
            "valid_from_utc": "2026-07-22T04:30:00+00:00",
            "valid_to_utc": "2026-07-22T05:30:00+00:00",
            "lower_flight_level": 0,
            "upper_flight_level": 400,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[104.0, -2.0], [106.0, -2.0], [106.0, 2.0], [104.0, 2.0], [104.0, -2.0]]],
            },
        },
    ])
    flight = _flight()

    review = assess_significant_weather(flight, snapshot=all_snapshot)

    assert review["status"] == "affected"
    assert [match["hazard_code"] for match in review["matches"]] == ["TS"]
    assert review["hazard_features"][0]["properties"]["hazard_code"] == "TS"
    assert flight["sigmet_review"] is review

    filtered = filter_awc_snapshot(all_snapshot, {"VA", "TC"})
    assert [item["hazard"] for item in filtered["advisories"]] == ["VA"]


def test_route_map_and_findings_include_route_matched_general_sigmet() -> None:
    flight = _flight()
    snapshot = _snapshot([
        {
            "advisory_id": "TURB-1",
            "hazard": "TURB",
            "valid_from_utc": "2026-07-22T04:30:00+00:00",
            "valid_to_utc": "2026-07-22T05:30:00+00:00",
            "lower_flight_level": 300,
            "upper_flight_level": 400,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[104.0, -2.0], [106.0, -2.0], [106.0, 2.0], [104.0, 2.0], [104.0, -2.0]]],
            },
        },
    ])
    assess_significant_weather(flight, snapshot=snapshot)

    findings, _warnings = analyse(flight)
    sigmet_findings = [item for item in findings if item["engine"] == "sigmet"]
    contract = build_map_contract(flight, findings, MapSettings(provider="schematic"))

    assert "sigmet" in ENGINE_ORDER
    assert sigmet_findings[0]["severity"] == "critical"
    assert sigmet_findings[0]["data"]["match_count"] == 1
    assert contract.hazards_geojson["features"][0]["properties"]["hazard_code"] == "TURB"
    assert contract.metadata["sigmet_status"] == "affected"
