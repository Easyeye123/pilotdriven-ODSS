from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from pypdf import PdfReader
import pytest

from app.odss.briefing import build_route_map, render_route_svg
from app.odss.reporting import render_pdf
from app.odss.parser import _parse_waypoints
from app.odss.vaa import evaluate_vaa, extract_embedded_vaa, fetch_awc_snapshot
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def _flight() -> dict:
    return {
        "flight_number": "SQ24",
        "departure": "WSSS",
        "destination": "KJFK",
        "departure_runway": "20C",
        "destination_runway": "22L",
        "flight_date": "22JUL26",
        "scheduled_departure_utc": "2026-07-22T04:00:00+00:00",
        "scheduled_arrival_utc": "2026-07-22T06:00:00+00:00",
        "aircraft_type": "A350-900",
        "registration": "9V-SXX",
        "ground_distance_nm": 9000,
        "planned_level_profile": "START/350",
        "route_waypoints": [
            {
                "name": "START",
                "actm_minutes": 0,
                "latitude": 0.0,
                "longitude": 100.0,
                "fir_boundary": None,
                "airway_in": "DCT",
                "msa_hundreds_ft": 4,
                "vws": 1,
            },
            {
                "name": "END",
                "actm_minutes": 120,
                "latitude": 0.0,
                "longitude": 110.0,
                "fir_boundary": None,
                "airway_in": "DCT",
                "msa_hundreds_ft": 4,
                "vws": 1,
            },
        ],
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_landing_weight_kg": 175802,
            "planned_takeoff_weight_kg": 245529,
        },
        "fuel": {
            "fuel_in_tanks_kg": 79643,
            "trip_fuel_kg": 69727,
            "planned_destination_fuel_kg": 9316,
        },
        "alternates": [],
        "edto": {
            "entry_actm_minutes": 20,
            "exit_actm_minutes": 100,
            "etp_actm_minutes": [60],
            "airports": [],
        },
        "weather": [],
        "notams": [],
        "personal_notes": [],
        "bobcat": None,
    }


def _advisory(
    *,
    valid_from: str = "2026-07-22T04:30:00+00:00",
    valid_to: str = "2026-07-22T05:30:00+00:00",
    lower: int = 300,
    upper: int = 400,
    ring: list[list[float]] | None = None,
) -> dict:
    return {
        "advisory_id": "TEST-VA-1",
        "hazard": "VA",
        "fir_id": "TEST",
        "valid_from_utc": valid_from,
        "valid_to_utc": valid_to,
        "lower_flight_level": lower,
        "upper_flight_level": upper,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                ring
                or [[104.0, -2.0], [106.0, -2.0], [106.0, 2.0], [104.0, 2.0], [104.0, -2.0]]
            ],
        },
        "raw_text": "TEST VA SIGMET",
        "raw_sha256": "abc",
    }


def _snapshot(
    advisories: list[dict] | None = None,
    *,
    coverage_status: str = "complete",
    status: str = "available",
    freshness_status: str = "fresh",
) -> dict:
    return {
        "schema_version": "1.0",
        "provider": "fixture-approved-provider",
        "source_url": "https://authority.example/vaa",
        "status": status,
        "retrieved_at_utc": "2026-07-22T03:55:00+00:00",
        "coverage_status": coverage_status,
        "coverage_start_utc": "2026-07-22T03:00:00+00:00",
        "coverage_end_utc": "2026-07-22T07:00:00+00:00",
        "freshness_status": freshness_status,
        "advisories": advisories or [],
        "parse_warnings": [],
        "raw_sha256": "snapshot-sha",
    }


def _vaa_finding(status: str) -> dict:
    return {
        "engine": "vaa",
        "severity": "critical" if status == "affected" else "unknown",
        "title": (
            "Volcanic ash affects the planned route"
            if status == "affected"
            else "Volcanic ash review required"
        ),
        "summary": "Route/time/flight-level review result.",
        "details": ["Official source evidence retained."],
        "data": {"status": status},
    }


def test_no_wx_data_is_source_unavailable_not_no_ash() -> None:
    embedded = extract_embedded_vaa([
        "FLIGHT WEATHER\nVolcanic Ash SIGMETs:\nNo Wx data available\nDestination weather"
    ])
    review = evaluate_vaa(
        _flight(),
        _snapshot(status="unavailable", coverage_status="unavailable", freshness_status="unknown"),
        embedded,
    )

    assert embedded["status"] == "unavailable"
    assert review["status"] == "review_required"
    assert "source_unavailable" in review["reason_codes"]
    assert "cfp_weather_data_unavailable" in review["reason_codes"]


def test_route_time_level_and_geometry_intersection_is_affected() -> None:
    review = evaluate_vaa(_flight(), _snapshot([_advisory()]))

    assert review["status"] == "affected"
    assert review["matches"][0]["route_from"] == "START"
    assert review["matches"][0]["planned_flight_level"] == 350
    assert review["hazard_features"][0]["properties"]["hazard"] == "volcanic_ash"


@pytest.mark.parametrize(
    "advisory",
    [
        _advisory(valid_from="2026-07-22T07:00:00+00:00", valid_to="2026-07-22T08:00:00+00:00"),
        _advisory(lower=400, upper=450),
        _advisory(ring=[[120.0, -2.0], [122.0, -2.0], [122.0, 2.0], [120.0, 2.0], [120.0, -2.0]]),
    ],
    ids=["time", "flight-level", "geometry"],
)
def test_complete_verified_nonintersection_is_not_applicable(advisory: dict) -> None:
    review = evaluate_vaa(_flight(), _snapshot([advisory]))

    assert review["status"] == "not_applicable"
    assert review["reason_codes"] == ["verified_no_intersection"]
    assert review["hazard_features"] == []


def test_current_active_feed_without_match_fails_closed() -> None:
    review = evaluate_vaa(
        _flight(),
        _snapshot([], coverage_status="global_current_active_sigmet"),
    )

    assert review["status"] == "review_required"
    assert "coverage_not_complete_for_flight" in review["reason_codes"]


def test_boundary_contact_across_antimeridian_counts_as_intersection() -> None:
    flight = _flight()
    flight["route_waypoints"][0].update(longitude=170.0, latitude=50.0)
    flight["route_waypoints"][1].update(longitude=-170.0, latitude=50.0)
    advisory = _advisory(
        ring=[[178.0, 50.0], [-178.0, 50.0], [-178.0, 54.0], [178.0, 54.0], [178.0, 50.0]]
    )

    review = evaluate_vaa(flight, _snapshot([advisory]))

    assert review["status"] == "affected"
    assert review["matches"][0]["boundary_contact_counts"] is True
    map_geometry = review["hazard_features"][0]["geometry"]
    assert map_geometry["type"] == "MultiPolygon"
    for polygon in map_geometry["coordinates"]:
        longitudes = [point[0] for point in polygon[0]]
        assert max(longitudes) - min(longitudes) <= 180


def test_actual_takeoff_time_is_used_for_vaa_timing() -> None:
    flight = _flight()
    flight["actual_takeoff_utc"] = "2026-07-22T10:00:00+00:00"
    advisory = _advisory(
        valid_from="2026-07-22T10:30:00+00:00",
        valid_to="2026-07-22T11:30:00+00:00",
    )
    snapshot = _snapshot([advisory])
    snapshot["coverage_end_utc"] = "2026-07-22T13:00:00+00:00"

    review = evaluate_vaa(flight, snapshot)

    assert review["status"] == "affected"
    assert review["matches"][0]["segment_start_utc"] == "2026-07-22T10:00:00+00:00"


def test_coordinate_level_anchor_matches_lido_abbreviated_waypoint_name() -> None:
    flight = _flight()
    flight["planned_level_profile"] = "START/350/63N140W/410"
    flight["route_waypoints"] = [
        {**flight["route_waypoints"][0], "longitude": -145.0, "latitude": 63.0},
        {
            **flight["route_waypoints"][0],
            "name": "63N40",
            "actm_minutes": 60,
            "longitude": -140.0,
            "latitude": 63.0,
        },
        {**flight["route_waypoints"][1], "longitude": -130.0, "latitude": 63.0},
    ]
    advisory = _advisory(
        lower=400,
        upper=420,
        ring=[[-141.0, 62.0], [-135.0, 62.0], [-135.0, 64.0], [-141.0, 64.0], [-141.0, 62.0]],
    )

    review = evaluate_vaa(flight, _snapshot([advisory]))

    assert review["status"] == "affected"
    assert review.get("unresolved_level_anchors") is None
    assert review["matches"][0]["planned_flight_level"] == 410


def test_parser_keeps_lido_abbreviated_coordinate_waypoints() -> None:
    route_page = """63N40        12.12 0.03 498 004 00.3
N63 00.0 W140 00.0 076 0027 390
63N30        12.44 0.08 498 001 00.7
N63 00.0 W130 00.0 111 0062 410
"""

    waypoints = _parse_waypoints([route_page], "DCT 63N140W 63N130W")

    assert [item["name"] for item in waypoints] == ["63N40", "63N30"]
    assert waypoints[0]["latitude"] == 63.0
    assert waypoints[0]["longitude"] == -140.0


def test_awc_snapshot_retains_auditable_source_evidence() -> None:
    response_payload = [
        {
            "hazard": "VA",
            "firId": "TEST",
            "firName": "TEST FIR",
            "seriesId": "1",
            "validTimeFrom": 1784692800,
            "validTimeTo": 1784714400,
            "receiptTime": "2026-07-22T03:50:00Z",
            "base": 0,
            "top": 35000,
            "coords": [
                {"lon": 104.0, "lat": -2.0},
                {"lon": 106.0, "lat": -2.0},
                {"lon": 106.0, "lat": 2.0},
                {"lon": 104.0, "lat": 2.0},
            ],
            "rawSigmet": "TEST VA SIGMET",
        },
        {"hazard": "TS", "rawSigmet": "NOT VOLCANIC ASH"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("PilotDriven-ODSS")
        return httpx.Response(
            200,
            json=response_payload,
            headers={"Date": "Wed, 22 Jul 2026 03:55:00 GMT"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(
            client=client,
            now=datetime(2026, 7, 22, 3, 55, tzinfo=timezone.utc),
        )

    assert snapshot["status"] == "available"
    assert snapshot["raw_record_count"] == 2
    assert snapshot["advisory_count"] == 1
    assert len(snapshot["raw_sha256"]) == 64
    assert snapshot["advisories"][0]["upper_flight_level"] == 350


def test_awc_vertical_limits_are_conservative_when_not_exact_hundreds() -> None:
    response_payload = [
        {
            "hazard": "VA",
            "firId": "TEST",
            "seriesId": "2",
            "validTimeFrom": 1784692800,
            "validTimeTo": 1784714400,
            "base": 12501,
            "top": 34901,
            "coords": [
                {"lon": 104.0, "lat": -2.0},
                {"lon": 106.0, "lat": -2.0},
                {"lon": 106.0, "lat": 2.0},
                {"lon": 104.0, "lat": 2.0},
            ],
            "rawSigmet": "TEST VA SIGMET",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=response_payload,
            headers={"Date": "Wed, 22 Jul 2026 03:55:00 GMT"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(
            client=client,
            now=datetime(2026, 7, 22, 3, 55, tzinfo=timezone.utc),
        )

    advisory = snapshot["advisories"][0]
    assert advisory["lower_flight_level"] == 125
    assert advisory["upper_flight_level"] == 350


def test_awc_source_rejects_unapproved_host_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_VA_SIGMET_URL", "https://internal.example/secret")

    snapshot = fetch_awc_snapshot(
        now=datetime(2026, 7, 22, 3, 55, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["source_url"] is None
    assert "approved aviationweather.gov" in snapshot["error"]


def test_level1_omits_vaa_and_bobcat_when_verified_not_applicable(tmp_path: Path) -> None:
    flight = _flight()
    flight["vaa_review"] = evaluate_vaa(flight, _snapshot([]))
    path = tmp_path / "no-vaa.pdf"

    render_pdf(flight, [], [], 1, path)
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert len(reader.pages) == 3
    assert "VOLCANIC ASH ADVISORY REVIEW" not in text
    assert "BOBCAT" not in text
    assert "EDTO" in (reader.pages[2].extract_text() or "")


@pytest.mark.parametrize("status", ["review_required", "affected"])
def test_level1_adds_conditional_vaa_page(status: str, tmp_path: Path) -> None:
    flight = _flight()
    review = evaluate_vaa(
        flight,
        _snapshot([_advisory()])
        if status == "affected"
        else _snapshot([], coverage_status="global_current_active_sigmet"),
    )
    assert review["status"] == status
    flight["vaa_review"] = review
    path = tmp_path / f"{status}.pdf"

    render_pdf(flight, [_vaa_finding(status)], [], 1, path)
    reader = PdfReader(path)
    page4 = reader.pages[3].extract_text() or ""

    assert len(reader.pages) == 4
    assert "VOLCANIC ASH ADVISORY REVIEW" in page4
    assert ("ROUTE AFFECTED" if status == "affected" else "MANUAL REVIEW REQUIRED") in page4
    assert "authority.example" in page4
    if status == "affected":
        assert "22 JUL 0400Z-22 JUL 0600Z" in page4


def test_map_contract_and_schematic_include_only_verified_hazards() -> None:
    flight = _flight()
    flight["vaa_review"] = evaluate_vaa(flight, _snapshot([_advisory()]))

    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    route_map = build_route_map(flight)
    svg = render_route_svg(route_map)

    assert contract.schema_version == "1.1"
    assert len(contract.hazards_geojson["features"]) == 1
    assert contract.metadata["vaa_status"] == "affected"
    assert 'fill="#ff6b6b"' in svg

    flight["vaa_review"] = evaluate_vaa(flight, _snapshot([]))
    cleared = build_map_contract(flight, [], MapSettings(provider="schematic"))
    assert cleared.hazards_geojson["features"] == []
