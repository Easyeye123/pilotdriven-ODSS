from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.engines import _HAZARD_REVIEWS, _hazard_review_findings
from app.odss.tropical_cyclone import (
    assess_tropical_cyclone,
    extract_embedded_tc,
)
from app.odss.vaa import fetch_awc_snapshot

from tests.test_vaa import _flight

_TC_HAZARD = next(
    hazard for hazard in _HAZARD_REVIEWS if hazard["review_key"] == "tropical_cyclone_review"
)


def _tc_advisory(
    *,
    valid_from: str = "2026-07-22T04:30:00+00:00",
    valid_to: str = "2026-07-22T05:30:00+00:00",
    lower: int = 300,
    upper: int = 400,
    ring: list[list[float]] | None = None,
) -> dict:
    return {
        "advisory_id": "TEST-TC-1",
        "hazard": "TC",
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
        "raw_text": "TEST TC SIGMET",
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
        "hazard_code": "TC",
        "source_url": "https://authority.example/tc",
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


def test_reports_affected_when_route_time_and_level_intersect():
    flight = _flight()
    review = assess_tropical_cyclone(flight, [], snapshot=_snapshot([_tc_advisory()]))

    assert review["status"] == "affected"
    assert review["reason_codes"] == ["verified_intersection"]
    assert len(review["matches"]) == 1
    assert review["matches"][0]["planned_flight_level"] == 350
    assert flight["tropical_cyclone_review"] is review


def test_tags_map_features_as_tropical_cyclone():
    flight = _flight()
    review = assess_tropical_cyclone(flight, [], snapshot=_snapshot([_tc_advisory()]))

    feature = review["hazard_features"][0]
    assert feature["properties"]["hazard"] == "tropical_cyclone"
    assert feature["properties"]["not_for_navigation"] is True


def test_does_not_report_affected_when_flight_level_is_below_the_band():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot=_snapshot([_tc_advisory(lower=380, upper=420)]),
    )

    assert review["status"] == "not_applicable"
    assert review["matches"] == []


def test_does_not_report_affected_when_validity_does_not_overlap():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot=_snapshot([
            _tc_advisory(
                valid_from="2026-07-23T04:30:00+00:00",
                valid_to="2026-07-23T05:30:00+00:00",
            )
        ]),
    )

    assert review["status"] == "not_applicable"
    assert review["matches"] == []


def test_does_not_report_affected_when_polygon_misses_the_route():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot=_snapshot([
            _tc_advisory(
                ring=[[140.0, 30.0], [142.0, 30.0], [142.0, 32.0], [140.0, 30.0]]
            )
        ]),
    )

    assert review["status"] == "not_applicable"
    assert review["matches"] == []


def test_fails_closed_when_the_source_is_unavailable():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot=_snapshot(status="unavailable"),
    )

    assert review["status"] == "review_required"
    assert "source_unavailable" in review["reason_codes"]


def test_fails_closed_when_the_source_is_disabled():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot={
            "schema_version": "1.0",
            "provider": None,
            "status": "disabled",
            "coverage_status": "disabled",
            "freshness_status": "unknown",
            "advisories": [],
        },
    )

    assert review["status"] == "not_assessed"
    assert review["reason_codes"] == ["source_disabled"]


def test_extracts_the_embedded_cfp_tropical_cyclone_statement():
    embedded = extract_embedded_tc([
        "TROPICAL CYCLONE SIGMETS:\nWTPQ31 RJTD TC TYPHOON NEAR 20N130E\nDESTINATION WEATHER",
    ])

    assert embedded["status"] == "present"
    assert embedded["source_page"] == 1
    assert "TYPHOON" in embedded["raw_excerpt"]
    assert "DESTINATION" not in embedded["raw_excerpt"]
    assert len(embedded["raw_sha256"]) == 64


def test_marks_the_embedded_statement_unavailable_when_the_cfp_says_so():
    embedded = extract_embedded_tc([
        "TROPICAL CYCLONE SIGMETS:\nNO WX DATA AVAILABLE",
    ])

    assert embedded["status"] == "unavailable"


def test_reports_not_present_when_the_cfp_has_no_section():
    embedded = extract_embedded_tc(["ROUTE LOG ONLY"])

    assert embedded["status"] == "not_present"
    assert embedded["source_page"] is None


def test_fetch_selects_only_tropical_cyclone_records():
    response_payload = [
        {
            "hazard": "TC",
            "firId": "RJJJ",
            "seriesId": "A",
            "validTimeFrom": "2026-07-22T04:00:00Z",
            "validTimeTo": "2026-07-22T08:00:00Z",
            "base": 0,
            "top": 45000,
            "coords": [
                {"lon": 104.0, "lat": -2.0},
                {"lon": 106.0, "lat": -2.0},
                {"lon": 106.0, "lat": 2.0},
                {"lon": 104.0, "lat": 2.0},
            ],
            "rawSigmet": "TEST TC SIGMET",
        },
        {"hazard": "VA", "rawSigmet": "NOT A TROPICAL CYCLONE"},
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
            hazard_code="TC",
        )

    assert snapshot["status"] == "available"
    assert snapshot["hazard_code"] == "TC"
    assert snapshot["raw_record_count"] == 2
    assert snapshot["advisory_count"] == 1
    assert snapshot["advisories"][0]["hazard"] == "TC"
    assert snapshot["advisories"][0]["upper_flight_level"] == 450


def test_absent_base_is_read_as_surface_for_a_tropical_cyclone():
    """Live TC SIGMETs publish only a top; an absent base means surface."""
    response_payload = [
        {
            "hazard": "TC",
            "firId": "RPHI",
            "seriesId": "4",
            "validTimeFrom": "2026-07-22T04:00:00Z",
            "validTimeTo": "2026-07-22T08:00:00Z",
            "base": None,
            "top": 54000,
            "coords": [
                {"lon": 120.65, "lat": 18.633},
                {"lon": 117.8, "lat": 18.217},
                {"lon": 115.8, "lat": 18.9},
            ],
            "rawSigmet": "RPHI TC SIGMET",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(client=client, hazard_code="TC")

    assert snapshot["advisory_count"] == 1
    assert snapshot["parse_warnings"] == []
    assert snapshot["advisories"][0]["lower_flight_level"] == 0
    assert snapshot["advisories"][0]["upper_flight_level"] == 540


def test_absent_base_is_still_refused_for_volcanic_ash():
    """The surface-base reading is specific to tropical cyclones."""
    response_payload = [
        {
            "hazard": "VA",
            "firId": "WAAF",
            "validTimeFrom": "2026-07-22T04:00:00Z",
            "validTimeTo": "2026-07-22T08:00:00Z",
            "base": None,
            "top": 20000,
            "coords": [
                {"lon": 120.0, "lat": 18.0},
                {"lon": 117.0, "lat": 18.0},
                {"lon": 115.0, "lat": 19.0},
            ],
            "rawSigmet": "VA SIGMET WITHOUT BASE",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(client=client, hazard_code="VA")

    assert snapshot["advisory_count"] == 0
    assert snapshot["parse_warnings"] == ["record_0:missing_vertical_limits"]


def test_absent_top_is_refused_even_for_a_tropical_cyclone():
    """An unknown vertical extent is never invented."""
    response_payload = [
        {
            "hazard": "TC",
            "firId": "MHTG",
            "validTimeFrom": "2026-07-22T04:00:00Z",
            "validTimeTo": "2026-07-22T08:00:00Z",
            "base": None,
            "top": None,
            "coords": [
                {"lon": -101.15, "lat": 9.87},
                {"lon": -101.0, "lat": 9.85},
                {"lon": -100.86, "lat": 9.82},
            ],
            "rawSigmet": "TC SIGMET WITHOUT TOP",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(client=client, hazard_code="TC")

    assert snapshot["advisory_count"] == 0
    assert snapshot["parse_warnings"] == ["record_0:missing_vertical_limits"]


def test_incomplete_records_force_review_rather_than_a_clear_result():
    """A TC SIGMET without vertical limits must never read as 'no cyclone'."""
    response_payload = [
        {
            "hazard": "TC",
            "firId": "RJJJ",
            "validTimeFrom": "2026-07-22T04:00:00Z",
            "validTimeTo": "2026-07-22T08:00:00Z",
            "coords": [
                {"lon": 104.0, "lat": -2.0},
                {"lon": 106.0, "lat": -2.0},
                {"lon": 106.0, "lat": 2.0},
            ],
            "rawSigmet": "TC SIGMET WITHOUT LEVELS",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_snapshot(
            client=client,
            now=datetime(2026, 7, 22, 3, 55, tzinfo=timezone.utc),
            hazard_code="TC",
        )

    assert snapshot["advisory_count"] == 0
    assert snapshot["parse_warnings"]

    review = assess_tropical_cyclone(_flight(), [], snapshot=snapshot)
    assert review["status"] == "review_required"
    assert "source_records_incomplete" in review["reason_codes"]


def test_emits_a_critical_tropical_cyclone_finding_when_affected():
    flight = _flight()
    review = assess_tropical_cyclone(flight, [], snapshot=_snapshot([_tc_advisory()]))
    findings, warnings = _hazard_review_findings(review, _TC_HAZARD)

    assert len(findings) == 1
    assert findings[0]["engine"] == "tropical_cyclone"
    assert findings[0]["rule_id"] == "TROPICAL_CYCLONE-AUTO"
    assert findings[0]["severity"] == "critical"
    assert findings[0]["title"] == "Tropical cyclone affects the planned route"
    assert warnings == []


def test_warns_when_the_cyclone_review_is_unresolved():
    flight = _flight()
    review = assess_tropical_cyclone(flight, [], snapshot=_snapshot(status="unavailable"))
    findings, warnings = _hazard_review_findings(review, _TC_HAZARD)

    assert findings[0]["severity"] == "unknown"
    assert findings[0]["title"] == "Tropical cyclone review required"
    assert any("Tropical cyclone applicability remains unresolved" in item for item in warnings)
    # The refusal must never be phrased as a clear result.
    assert any("no tropical cyclone" in detail for detail in findings[0]["details"])


def test_emits_no_finding_when_the_cyclone_review_is_clear():
    flight = _flight()
    review = assess_tropical_cyclone(
        flight,
        [],
        snapshot=_snapshot([_tc_advisory(lower=380, upper=420)]),
    )
    findings, warnings = _hazard_review_findings(review, _TC_HAZARD)

    assert findings == []
    assert warnings == []


def test_volcanic_ash_and_cyclone_reviews_are_independent():
    flight = _flight()
    assess_tropical_cyclone(flight, [], snapshot=_snapshot([_tc_advisory()]))

    assert flight["tropical_cyclone_review"]["status"] == "affected"
    assert "vaa_review" not in flight
