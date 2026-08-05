from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
import pytest

from app.odss.direct_vaac_anchorage import (
    fetch_anchorage_vaac_snapshot,
    parse_anchorage_vaac_advisory,
    parse_anchorage_vaac_listing,
)
from app.odss.vaa import (
    merge_vaac_snapshots,
    mounted_vaac_centres,
)


# Shapes transcribed from the live National Weather Service API on 2026-08-05.
# The advisory body is the ICAO VA ADVISORY text as Anchorage issues it; the
# volcano and clock here are whatever that record happened to carry and are
# never matched on by the connector.
LISTING = {
    "@graph": [
        {
            "id": "8c6cf528-48f3-4898-970c-664a9e850514",
            "issuingOffice": "PAWU",
            "issuanceTime": "2026-08-05T00:12:00+00:00",
            "wmoCollectiveId": "FVAK22",
        },
        {
            "id": "outside-window",
            "issuingOffice": "PAWU",
            "issuanceTime": "2026-07-01T00:00:00+00:00",
            "wmoCollectiveId": "FVAK22",
        },
        {
            "id": "another-office",
            "issuingOffice": "KKCI",
            "issuanceTime": "2026-08-05T00:12:00+00:00",
            "wmoCollectiveId": "FVXX01",
        },
    ]
}

ADVISORY = {
    "issuingOffice": "PAWU",
    "issuanceTime": "2026-08-05T00:12:00+00:00",
    "productText": (
        "\n000\nFVAK22 PAWU 050012\nVAAAK2\nVA ADVISORY\n\n"
        "DTG: 20260805/0008Z\n\nVAAC: ANCHORAGE\n\n"
        "VOLCANO: TESTVOLCANO 300270\n\nPSN: N5639 E16122\n\n"
        "AREA: TEST AREA\n\nSOURCE ELEV: 10771 FT AMSL\n\n"
        "ADVISORY NR: 2026/252\n\n"
        "OBS VA DTG: 05/0008Z\n\n"
        "OBS VA CLD: SFC/FL200 N5639 E16122 - N5700 E16200 - N5639 E16300\n\n"
        "FCST VA CLD +6 HR: 05/0600Z SFC/FL200 N5639 E16122 - N5700 E16200\n\n"
        "RMK: PLEASE SEE FVFE01 RJTD ISSUED BY VAAC TOKYO WHICH DESCRIBES\n"
        "CONDITIONS NEAR THE VAAC ANCHORAGE AREA OF RESPONSIBILITY...SC\n\n"
        "NXT ADVISORY: NO LATER THAN 20260805/0600Z\n"
    ),
}


def _flight() -> dict[str, object]:
    return {
        "scheduled_departure_utc": "2026-08-04T20:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-05T06:00:00+00:00",
    }


def test_listing_keeps_only_advisories_anchorage_issued() -> None:
    rows = parse_anchorage_vaac_listing(LISTING)

    assert [row["product_id"] for row in rows] == [
        "8c6cf528-48f3-4898-970c-664a9e850514",
        "outside-window",
    ]
    assert all("api.weather.gov/products/" in row["vaa_url"] for row in rows)


def test_advisory_identity_is_verified_from_the_advisory_itself() -> None:
    parsed = parse_anchorage_vaac_advisory(
        ADVISORY,
        {"issued_at_utc": "2026-08-05T00:12:00+00:00"},
    )

    assert parsed["provider"] == "nws-anchorage-vaac"
    assert parsed["vaac"] == "ANCHORAGE"
    assert parsed["advisory_number"] == "2026/252"
    assert [item["phase"] for item in parsed["phases"]] == [
        "observed",
        "forecast_plus_6_hours",
    ]
    # The observed layer is read from the advisory's own polygon, not inferred.
    observed = parsed["phases"][0]
    assert observed["state"] == "polygon_available"
    assert (observed["lower_limit"], observed["upper_limit"]) == ("SFC", "FL200")
    # The deferral to the neighbouring centre is retained rather than dropped,
    # so a reader is not left thinking the area was assessed as clear.
    assert "VAAC TOKYO" in parsed["remarks"]


def test_an_advisory_from_another_centre_is_rejected() -> None:
    relayed = {
        **ADVISORY,
        "productText": ADVISORY["productText"].replace(
            "VAAC: ANCHORAGE", "VAAC: TOKYO"
        ),
    }

    with pytest.raises(ValueError):
        parse_anchorage_vaac_advisory(
            relayed, {"issued_at_utc": "2026-08-05T00:12:00+00:00"}
        )


def test_snapshot_retrieves_only_advisories_inside_the_flight_window() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/products/types/VAA":
            return httpx.Response(200, json=LISTING)
        return httpx.Response(200, json=ADVISORY)

    snapshot = fetch_anchorage_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "available"
    assert snapshot["provider"] == "nws-anchorage-vaac"
    assert snapshot["advisory_count"] == 1
    assert snapshot["coverage_status"] == "anchorage_vaac_area_direct_advisories"
    assert not any("outside-window" in url for url in requested)


def test_an_unreachable_centre_fails_closed_rather_than_reporting_no_ash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    snapshot = fetch_anchorage_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["advisories"] == []
    assert snapshot["errors"]


def test_a_non_json_body_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not the product</html>")

    snapshot = fetch_anchorage_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "unavailable"


def test_centres_are_mounted_by_token(monkeypatch) -> None:
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "jma-tokyo,anchorage")
    assert [entry["centre"] for entry in mounted_vaac_centres()] == ["TOKYO", "ANCHORAGE"]

    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "anchorage")
    assert [entry["centre"] for entry in mounted_vaac_centres()] == ["ANCHORAGE"]

    # The single legacy spellings a deployment may already be set to keep working.
    for legacy in ("jma", "tokyo", "jma-tokyo"):
        monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", legacy)
        assert [entry["centre"] for entry in mounted_vaac_centres()] == ["TOKYO"]

    for disabled in ("", "disabled", "off", "none"):
        monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", disabled)
        assert mounted_vaac_centres() == []


def test_an_unknown_token_mounts_nothing_rather_than_guessing(monkeypatch) -> None:
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "darwin,washington")
    assert mounted_vaac_centres() == []


def test_merged_coverage_is_the_weakest_of_the_mounted_centres() -> None:
    tokyo = {
        "status": "available",
        "provider": "jma-tokyo-vaac",
        "centre": "TOKYO",
        "advisories": [{"advisory_number": "2026/294"}],
        "retrieved_at_utc": "2026-08-05T01:00:00+00:00",
    }
    anchorage_down = {
        "status": "unavailable",
        "provider": "nws-anchorage-vaac",
        "centre": "ANCHORAGE",
        "advisories": [],
        "errors": [{"error": "HTTPStatusError"}],
        "retrieved_at_utc": "2026-08-05T01:00:00+00:00",
    }

    merged = merge_vaac_snapshots([tokyo, anchorage_down])

    assert merged["status"] == "partial", "a centre that did not answer is a gap, not an all-clear"
    assert merged["centres"] == ["TOKYO", "ANCHORAGE"]
    assert merged["advisory_count"] == 1
    assert merged["advisories"][0]["centre"] == "TOKYO"
    assert merged["errors"][0]["centre"] == "ANCHORAGE"


def test_every_merged_advisory_names_the_centre_that_issued_it() -> None:
    merged = merge_vaac_snapshots([
        {"status": "available", "provider": "jma-tokyo-vaac", "centre": "TOKYO",
         "advisories": [{"advisory_number": "1"}]},
        {"status": "available", "provider": "nws-anchorage-vaac", "centre": "ANCHORAGE",
         "advisories": [{"advisory_number": "2"}]},
    ])

    assert merged["status"] == "available"
    assert sorted(item["centre"] for item in merged["advisories"]) == ["ANCHORAGE", "TOKYO"]
    assert merged["coverage_status"] == "multi_vaac_area_direct_advisories"


def test_a_single_mounted_centre_is_passed_through_unchanged() -> None:
    only = {"status": "available", "provider": "jma-tokyo-vaac", "centre": "TOKYO", "advisories": []}

    assert merge_vaac_snapshots([only]) is only
    assert merge_vaac_snapshots([]) is None


def test_no_flight_timing_yields_no_invented_coverage() -> None:
    snapshot = fetch_anchorage_vaac_snapshot(
        {},
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=LISTING))),
        now=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["advisories"] == []
