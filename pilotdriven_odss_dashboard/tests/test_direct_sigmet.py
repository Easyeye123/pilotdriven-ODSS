"""Direct BOM SIGMET adapter: parse, merge, gating, and fail-closed rules.

The HTML fixture is a captured excerpt of the real page at
https://www.bom.gov.au/aviation/warnings/sigmet/ retrieved 06.08.26 23:11 UTC,
so the parser is exercised against the authority's actual markup, not an
idealised one.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.direct_sigmet import (
    BOM_PROVIDER,
    fetch_bom_sigmet_snapshot,
    merge_direct_sigmet_snapshot,
    parse_bom_sigmet_page,
    route_intersects_australian_firs,
)
from app.odss.sigmet import GENERAL_SIGMET_HAZARDS, assess_significant_weather


BOM_PAGE_EXCERPT = """
<div class="middle-column-round">
<p class="product">IDQ60075<br />AUSTRALIAN SIGMETS              23:11 UTC, 06/08/2026<br />--------------------------------------------------------------------</p><p class="product">YMMM SIGMET U11 VALID 062111/070111 YMMC-<br />YMMM MELBOURNE FIR SEV TURB FCST WI S5000 E12600 - S4040 E12700 -<br />S4140 E12900 - S4954 E13049 FL140/260 MOV E 35KT NC<br />RMK: MM=</p><p class="product">YMMM SIGMET C04 VALID 062051/070051 YMMC-<br />YMMM MELBOURNE FIR SEV ICE FCST WI S2130 E10530 - S2236 E11533 -<br />S2420 E11900 - S2510 E11830 - S2730 E11320 - S2522 E10534 - S2300<br />E09830 - S2120 E09940 FL120/260 MOV E 30KT NC<br />RMK: MW=</p><p class="product">YBBB SIGMET A02 VALID 062039/070039 YMMC-<br />YBBB BRISBANE FIR SEV TURB FCST WI S2550 E08953 - S2910 E11320 -<br />S2945 E13427 - S2340 E14400 FL250/370 MOV E 10KT NC<br />RMK: MM=</p><p class="product">YBBB SIGMET B01 VALID 062039/070039 YMMC-<br />YBBB BRISBANE FIR EMBD TS FCST N OF S20 AND E OF E145 TOP FL450 MOV SE 15KT NC<br />RMK: MM=</p>
</div>
"""

RETRIEVED_AT = datetime(2026, 8, 6, 23, 30, tzinfo=timezone.utc)


def _parsed():
    return parse_bom_sigmet_page(BOM_PAGE_EXCERPT, RETRIEVED_AT)


def test_parses_polygon_sigmets_from_the_real_page_markup():
    parsed = _parsed()
    assert parsed["issued_at_utc"] == "2026-08-06T23:11:00+00:00"
    advisories = parsed["advisories"]
    assert [item["series_id"] for item in advisories] == ["U11", "C04", "A02"]

    turb = advisories[0]
    assert turb["fir_id"] == "YMMM"
    assert turb["hazard"] == "TURB"
    assert turb["valid_from_utc"] == "2026-08-06T21:11:00+00:00"
    assert turb["valid_to_utc"] == "2026-08-07T01:11:00+00:00"
    assert turb["lower_flight_level"] == 140
    assert turb["upper_flight_level"] == 260
    ring = turb["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert ring[0] == [126.0, -50.0]
    assert turb["advisory_id"].startswith("YMMM-U11-")
    assert turb["source_provider"] == BOM_PROVIDER

    ice = advisories[1]
    assert ice["hazard"] == "ICE"
    # S2236 E11533 is degrees + minutes, not a decimal reading.
    assert [round(value, 4) for value in ice["geometry"]["coordinates"][0][1]] == [115.55, -22.6]


def test_non_polygon_scope_is_a_warning_not_an_invented_polygon():
    parsed = _parsed()
    assert any(warning.endswith("unsupported_geometry") for warning in parsed["parse_warnings"])
    assert all(item["series_id"] != "B01" for item in parsed["advisories"])


def test_fetch_failure_is_governed_and_fail_closed():
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(_refuse))
    snapshot = fetch_bom_sigmet_snapshot(client=client, now=RETRIEVED_AT)
    assert snapshot["status"] == "unavailable"
    assert snapshot["provider"] == BOM_PROVIDER
    assert snapshot["advisories"] == []
    assert "ConnectError" in snapshot["error"]


def test_fetch_parses_live_shaped_response():
    def _serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=BOM_PAGE_EXCERPT)

    client = httpx.Client(transport=httpx.MockTransport(_serve))
    snapshot = fetch_bom_sigmet_snapshot(client=client, now=RETRIEVED_AT)
    assert snapshot["status"] == "available"
    assert snapshot["freshness_status"] == "fresh"
    assert snapshot["advisory_count"] == 3
    assert snapshot["coverage_status"] == "australian_firs_only"


def test_merge_unions_without_duplicates_and_never_pollutes_the_aggregate():
    parsed = _parsed()
    base = {
        "provider": "noaa-awc-international-sigmet",
        "status": "available",
        "freshness_status": "fresh",
        "parse_warnings": [],
        # AWC already carries YMMM U11 under the identical identity.
        "advisories": [dict(parsed["advisories"][0], source_provider=None)],
    }
    direct = {
        "provider": BOM_PROVIDER,
        "status": "available",
        "retrieved_at_utc": "2026-08-06T23:30:00+00:00",
        "freshness_status": "fresh",
        "declared_fir_ids": ["YBBB", "YMMM"],
        "parse_warnings": ["record_4:unsupported_geometry"],
        "advisories": parsed["advisories"],
    }
    merged, report = merge_direct_sigmet_snapshot(base, direct, GENERAL_SIGMET_HAZARDS)
    assert report["advisories_offered"] == 3
    assert report["advisories_duplicate"] == 1
    assert report["advisories_merged"] == 2
    assert len(merged["advisories"]) == 3
    # The direct source's parse warnings stay in the report for the ledger and
    # must never amber the aggregate review through the merged snapshot.
    assert merged["parse_warnings"] == []
    assert merged["merged_direct_sources"] == [BOM_PROVIDER]


def test_unavailable_direct_source_changes_nothing():
    base = {"status": "available", "parse_warnings": [], "advisories": []}
    merged, report = merge_direct_sigmet_snapshot(
        base,
        {"provider": BOM_PROVIDER, "status": "unavailable", "error": "x"},
        GENERAL_SIGMET_HAZARDS,
    )
    assert merged is base
    assert report["available"] is False


def test_route_relevance_gate_uses_route_waypoints():
    australian = {"route_waypoints": [{"latitude": -33.9, "longitude": 151.2}]}
    european = {"route_waypoints": [
        {"latitude": 1.35, "longitude": 103.99},
        {"latitude": 41.8, "longitude": 12.2},
    ]}
    assert route_intersects_australian_firs(australian) is True
    assert route_intersects_australian_firs(european) is False
    assert route_intersects_australian_firs({}) is False


def _australian_flight() -> dict:
    return {
        "flight_number": "TEST2",
        "scheduled_departure_utc": "2026-08-06T21:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-07T01:00:00+00:00",
        "planned_level_profile": "START/200",
        "route_waypoints": [
            {"name": "START", "actm_minutes": 0, "latitude": -44.0, "longitude": 125.0},
            {"name": "END", "actm_minutes": 240, "latitude": -46.0, "longitude": 131.0},
        ],
    }


def test_assessment_merges_direct_records_and_writes_the_ledger(monkeypatch):
    parsed = _parsed()
    monkeypatch.setenv("ODSS_DIRECT_SIGMET_SOURCES", "bom")
    monkeypatch.setattr(
        "app.odss.sigmet.live_bom_sigmet_snapshot",
        lambda: {
            "provider": BOM_PROVIDER,
            "status": "available",
            "retrieved_at_utc": "2026-08-06T23:30:00+00:00",
            "freshness_status": "fresh",
            "declared_fir_ids": ["YBBB", "YMMM"],
            "parse_warnings": [],
            "advisories": parsed["advisories"],
        },
    )
    flight = _australian_flight()
    awc_only = {
        "schema_version": "1.0",
        "provider": "noaa-awc-international-sigmet",
        "source_url": "https://aviationweather.gov/api/data/isigmet?format=json",
        "status": "available",
        "retrieved_at_utc": "2026-08-06T23:30:00+00:00",
        "coverage_status": "current_active_only",
        "freshness_status": "fresh",
        "advisories": [],
        "parse_warnings": [],
    }
    review = assess_significant_weather(flight, snapshot=awc_only)
    ledger = review["coverage_ledger"]

    assert ledger["direct_bom_australia_sigmet"]["available"] is True
    assert ledger["direct_bom_australia_sigmet"]["advisories_merged"] == 3
    assert ledger["direct_bom_australia_sigmet"]["review_required_when_missing"] is False
    assert ledger["direct_jma_fukuoka_sigmet"]["configuration_status"] == (
        "no_public_machine_readable_product"
    )
    assert ledger["direct_hko_hong_kong_sigmet"]["aggregate_carries_fir"] == "VHHK"
    # The route crosses the merged U11 polygon inside its validity, so the
    # direct record is the evidence that flips this review to affected.
    assert review["status"] == "affected"
    assert any(
        str(match.get("advisory_id", "")).startswith("YMMM-U11-")
        for match in review["matches"]
    )


def test_non_australian_route_never_consults_the_direct_source(monkeypatch):
    calls = {"count": 0}

    def _would_fetch():
        calls["count"] += 1
        return {"status": "available", "advisories": [], "parse_warnings": []}

    monkeypatch.setenv("ODSS_DIRECT_SIGMET_SOURCES", "bom")
    monkeypatch.setattr("app.odss.sigmet.live_bom_sigmet_snapshot", _would_fetch)
    flight = {
        "flight_number": "TEST3",
        "scheduled_departure_utc": "2026-08-06T21:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-07T01:00:00+00:00",
        "route_waypoints": [
            {"name": "A", "actm_minutes": 0, "latitude": 1.35, "longitude": 103.99},
            {"name": "B", "actm_minutes": 120, "latitude": 41.8, "longitude": 12.2},
        ],
    }
    review = assess_significant_weather(flight, snapshot={
        "provider": "noaa-awc-international-sigmet",
        "status": "available",
        "retrieved_at_utc": "2026-08-06T23:30:00+00:00",
        "freshness_status": "fresh",
        "advisories": [],
        "parse_warnings": [],
    })
    assert calls["count"] == 0
    assert review["coverage_ledger"]["direct_bom_australia_sigmet"]["configuration_status"] == (
        "not_route_relevant"
    )
