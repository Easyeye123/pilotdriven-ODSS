from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from pypdf import PdfReader
import pytest

from app.odss.briefing import build_briefing_view, build_route_map, render_route_svg
from app.odss.reporting import render_pdf
from app.odss.parser import _parse_waypoints
from app.odss.vaa import (
    assess_volcanic_ash,
    build_direct_vaa_source_review,
    evaluate_vaa,
    extract_embedded_vaa,
    fetch_awc_snapshot,
)
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

    waypoints = _parse_waypoints(
        [route_page],
        "DCT 63N140W 63N130W",
        start_page_number=7,
    )

    assert [item["name"] for item in waypoints] == ["63N40", "63N30"]
    assert waypoints[0]["latitude"] == 63.0
    assert waypoints[0]["longitude"] == -140.0
    assert [item["source_page"] for item in waypoints] == [7, 7]


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
    assert snapshot["snapshot_scope"] == "noaa_awc_current_active_international_sigmet_feed"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert snapshot["effective_start_utc"] == snapshot["coverage_start_utc"]
    assert snapshot["effective_end_utc"] == snapshot["coverage_end_utc"]


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
    assert "EDTO" in (reader.pages[1].extract_text() or "")


@pytest.mark.parametrize("status", ["review_required", "affected"])
def test_level1_integrates_conditional_vaa_on_route_page(
    status: str,
    tmp_path: Path,
) -> None:
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
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    page2 = reader.pages[1].extract_text() or ""
    page3 = reader.pages[2].extract_text() or ""

    assert len(reader.pages) == 3
    assert "DATA COVERAGE" in page2
    assert "DATA COVERAGE" not in page3
    assert (
        "VAA: route impact identified - review Level 2."
        if status == "affected"
        else "VAA: review required."
    ) in page2
    assert "VOLCANIC ASH ADVISORY REVIEW" not in text
    assert "SOURCE / PROVENANCE" not in text
    assert "MANUAL REVIEW REQUIRED" not in text


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


def test_map_prefers_explicit_va_sigmet_review_over_legacy_combined_review() -> None:
    flight = _flight()
    flight["va_sigmet_review"] = evaluate_vaa(
        flight,
        _snapshot([_advisory()]),
    )
    flight["vaa_review"] = evaluate_vaa(flight, _snapshot([]))

    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    route_map = build_route_map(flight)

    assert len(contract.hazards_geojson["features"]) == 1
    assert contract.metadata["va_sigmet_status"] == "affected"
    assert contract.metadata["vaa_status"] == "affected"
    assert route_map["va_sigmet_status"] == "affected"
    assert route_map["vaa_status"] == "affected"

    # A stale legacy combined review cannot put VA SIGMET geometry back after
    # the explicit VA SIGMET evaluator has cleared it.
    flight["vaa_review"] = flight["va_sigmet_review"]
    flight["va_sigmet_review"] = evaluate_vaa(flight, _snapshot([]))
    cleared = build_map_contract(flight, [], MapSettings(provider="schematic"))
    assert cleared.hazards_geojson["features"] == []
    assert cleared.metadata["va_sigmet_status"] == "not_applicable"


def test_awc_sigmet_only_does_not_claim_complete_vaac_coverage(monkeypatch) -> None:
    monkeypatch.delenv("ODSS_VAAC_ADVISORY_SOURCE", raising=False)
    snapshot = _snapshot([])
    snapshot["provider"] = "noaa-awc-international-sigmet"
    flight = _flight()

    review = assess_volcanic_ash(flight, [], snapshot=snapshot)

    assert review["status"] == "review_required"
    assert "direct_vaac_advisory_source_not_mounted" in review["reason_codes"]
    assert (
        review["coverage_ledger"]["responsible_vaac_advisory_and_vag"]["available"]
        is False
    )


def test_va_sigmet_and_direct_vaa_source_reviews_are_distinct(monkeypatch) -> None:
    """A VA SIGMET hit must not turn an unmounted VAA source into "found"."""
    monkeypatch.delenv("ODSS_VAAC_ADVISORY_SOURCE", raising=False)
    flight = _flight()

    legacy = assess_volcanic_ash(
        flight,
        [],
        snapshot=_snapshot([_advisory()]),
    )

    assert flight["va_sigmet_review"]["product"] == "VA_SIGMET"
    assert flight["va_sigmet_review"]["status"] == "affected"
    assert len(flight["va_sigmet_review"]["hazard_features"]) == 1
    direct = flight["direct_vaa_source_review"]
    assert direct["product"] == "VAA"
    assert direct["status"] == "review_required"
    assert direct["source_status"] == "unavailable"
    assert direct["applicability_status"] == "not_assessed"
    assert direct["official_advisory_count"] == 0
    assert "direct_vaa_applicability_not_assessed" in direct["reason_codes"]
    # Existing callers still receive and can read the legacy combined review.
    assert legacy is flight["vaa_review"]


def test_direct_vaa_source_review_counts_only_route_responsible_centres() -> None:
    flight = _flight()  # The route resolves to DARWIN.
    tokyo_advisory = {
        "centre": "TOKYO",
        "vaac": "TOKYO",
        "advisory_number": "2026/101",
        "issued_at_utc": "2026-07-22T03:00:00+00:00",
        "phases": [],
    }

    review = build_direct_vaa_source_review(
        flight,
        snapshots=[{
            "centre": "TOKYO",
            "provider": "jma-tokyo-vaac",
            "status": "available",
            "coverage_status": "tokyo_vaac_area_direct_advisories",
            "advisory_count": 1,
            "advisories": [tokyo_advisory],
        }],
        mounted=[{
            "token": "jma-tokyo",
            "centre": "TOKYO",
            "provider": "jma-tokyo-vaac",
        }],
    )

    assert review["responsible_centres"] == ["DARWIN"]
    assert review["reached_responsible_centres"] == []
    assert review["source_status"] == "unavailable"
    assert review["official_advisory_count"] == 0
    assert review["official_advisories"] == []


def test_direct_vaa_source_review_is_partial_until_every_responsible_centre_is_reached() -> None:
    flight = _flight()
    flight["route_waypoints"][-1].update(latitude=14.5, longitude=121.0)
    mounted = [
        {"token": "darwin-gts", "centre": "DARWIN", "provider": "noaa-gts-darwin-vaa"},
        {"token": "jma-tokyo", "centre": "TOKYO", "provider": "jma-tokyo-vaac"},
    ]
    darwin = {
        "centre": "DARWIN",
        "provider": "noaa-gts-darwin-vaa",
        "status": "available",
        "coverage_status": "darwin_vaac_area_direct_advisories",
        "advisory_count": 0,
        "advisories": [],
    }

    partial = build_direct_vaa_source_review(
        flight,
        snapshots=[darwin],
        mounted=mounted,
    )
    assert partial["responsible_centres"] == ["DARWIN", "TOKYO"]
    assert partial["reached_responsible_centres"] == ["DARWIN"]
    assert partial["source_status"] == "partial"
    assert partial["applicability_status"] == "not_assessed"

    complete_sources = build_direct_vaa_source_review(
        flight,
        snapshots=[darwin, {
            "centre": "TOKYO",
            "provider": "jma-tokyo-vaac",
            "status": "available",
            "coverage_status": "tokyo_vaac_area_direct_advisories",
            "advisory_count": 0,
            "advisories": [],
        }],
        mounted=mounted,
    )
    assert complete_sources["source_status"] == "available"
    assert complete_sources["applicability_status"] == "not_assessed"
    assert complete_sources["status"] == "review_required"
    assert "verified_no_intersection" not in complete_sources["reason_codes"]


def test_direct_vaa_source_review_never_resurrects_the_all_centre_ledger_as_responsibility() -> None:
    review = build_direct_vaa_source_review(
        {"route_waypoints": []},
        snapshots=[{
            "centre": centre,
            "provider": "fixture",
            "status": "available",
            "coverage_status": "fixture",
            "advisory_count": 0,
            "advisories": [],
        } for centre in ("ANCHORAGE", "DARWIN", "TOKYO")],
        mounted=[],
    )

    assert review["responsible_centres"] == []
    assert review["responsible_centre_receipts"] == []
    assert review["source_status"] == "unavailable"
    assert review["responsibility_review_required"] is True
    assert "responsible_vaac_unresolved" in review["reason_codes"]


def test_briefing_projects_va_sigmet_and_direct_vaa_without_counting_cfp_notice_as_official() -> None:
    flight = _flight()
    va_sigmet_review = evaluate_vaa(flight, _snapshot([_advisory()]))
    va_sigmet_review["product"] = "VA_SIGMET"
    direct_review = build_direct_vaa_source_review(
        flight,
        snapshots=[],
        mounted=[],
    )
    flight["va_sigmet_review"] = va_sigmet_review
    flight["direct_vaa_source_review"] = direct_review
    flight["vaa_review"] = {**va_sigmet_review, "status": "affected"}
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 220400/220700 VA ERUPTION "
            "MT KRAKATAU WI S0200 E10400 - S0200 E10600 - N0200 E10600 "
            "SFC/FL400"
        ),
        "source_page": 13,
    }]

    view = build_briefing_view(flight, [], [])

    assert view["va_sigmet"]["status"] == "affected"
    assert view["va_sigmet"]["review"] is va_sigmet_review
    assert len(view["vaa"]["cfp_notices"]) == 1
    assert view["vaa"]["cfp_advisories"] == view["vaa"]["cfp_notices"]
    assert view["vaa"]["direct_source_review"] is direct_review
    assert view["vaa"]["official_advisory_count"] == 0
    assert view["vaa"]["official_advisories"] == []
    assert view["vaa"]["applicability_status"] == "not_assessed"
    assert view["vaa"]["status"] == "review_required"


def test_briefing_adapts_legacy_direct_snapshot_without_losing_source_truth() -> None:
    flight = _flight()  # The route resolves to DARWIN.
    flight["vaa_review"] = {
        "status": "affected",
        "direct_vaac_snapshot": {
            "centre": "DARWIN",
            "provider": "noaa-gts-darwin-vaa",
            "status": "available",
            "coverage_status": "darwin_vaac_area_direct_advisories",
            "advisory_count": 1,
            "advisories": [{
                "vaac": "DARWIN",
                "advisory_number": "2026/017",
                "volcano": "KRAKATAU",
                "issued_at_utc": "2026-08-25T18:00:00+00:00",
            }],
        },
        "vaac_centre_ledger": [{
            "centre": "DARWIN",
            "provider": "noaa-gts-darwin-vaa",
            "status": "available",
            "coverage_status": "darwin_vaac_area_direct_advisories",
            "advisory_count": 1,
        }],
    }

    view = build_briefing_view(flight, [], [])

    direct = view["vaa"]["direct_source_review"]
    assert direct["compatibility_source"] == (
        "vaa_review.direct_vaac_snapshot"
    )
    assert view["vaa"]["status"] == "review_required"
    assert view["vaa"]["source_status"] == "available"
    assert view["vaa"]["applicability_status"] == "not_assessed"
    assert view["vaa"]["official_advisory_count"] == 1
    assert view["vaa"]["official_advisories"][0]["centre"] == "DARWIN"
    assert view["va_sigmet"]["status"] == "affected"


def test_vaac_reach_uses_explicit_responsible_receipts_not_all_centre_ledger() -> None:
    from app.odss.briefing import _vaac_reach_summary

    flight = _flight()
    flight["vaa_review"] = {
        "vaac_centre_ledger": [
            {"centre": centre, "status": "available"}
            for centre in ("ANCHORAGE", "DARWIN", "TOKYO")
        ]
    }
    flight["direct_vaa_source_review"] = {
        "responsible_centres": ["DARWIN"],
        "responsible_centre_receipts": [{
            "centre": "DARWIN",
            "status": "not_mounted",
            "reached": False,
        }],
        "responsible_line": (
            "Responsible for this route: DARWIN - NOT reached: DARWIN "
            "(review gap)"
        ),
        "responsibility_review_required": False,
        "responsibility_source": {"document": "ICAO Doc 9766 fixture"},
    }

    summary = _vaac_reach_summary(flight)

    assert summary["summary"] == "3/3 reached"  # all-nine audit tally only
    assert summary["responsible"] == [{"centre": "DARWIN", "reached": False}]
    assert "NOT reached: DARWIN" in summary["responsible_line"]



def test_vaac_reach_summary_names_the_responsible_centres() -> None:
    # Boss, 21 Aug: "there's a VAAC ... in Manila? ... don't see any
    # [checking]" — the reach summary leads with the centres Doc 9766 makes
    # responsible for this route, and says whether each was reached.
    from app.odss.briefing import _vaac_reach_summary

    flight = {
        "route_waypoints": [
            {"name": "WSSS", "latitude": 1.3, "longitude": 103.9, "fir_boundary": None},
            {"name": "-RPHI", "latitude": 12.0, "longitude": 118.0, "fir_boundary": "RPHI"},
            {"name": "RPLL", "latitude": 14.5, "longitude": 121.0, "fir_boundary": None},
        ],
        "vaa_review": {
            "vaac_centre_ledger": [
                {"centre": "TOKYO", "status": "available", "advisory_count": 1},
                {"centre": "DARWIN", "status": "available", "advisory_count": 0},
                {"centre": "ANCHORAGE", "status": "available", "advisory_count": 0},
                {"centre": "LONDON", "status": "not_mounted", "advisory_count": 0},
            ]
        },
    }
    summary = _vaac_reach_summary(flight)
    assert summary["responsible"] == [
        {"centre": "DARWIN", "reached": True},
        {"centre": "TOKYO", "reached": True},
    ]
    assert summary["responsible_source"]["document"].startswith("ICAO Doc 9766")
    assert "Responsible for this route: DARWIN, TOKYO" in summary["responsible_line"]
    assert summary["responsible_review_required"] is False
