from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import httpx

from app.odss.opmet import (
    AWC_METAR_PATH,
    AWC_TAF_PATH,
    enrich_official_opmet,
    fetch_awc_product,
)
from app.odss.engines import _official_weather_review_finding


def _flight() -> dict:
    return {
        "departure": "KJFK",
        "destination": "WSSS",
        "scheduled_departure_utc": "2026-07-25T02:15:00+00:00",
        "scheduled_arrival_utc": "2026-07-25T21:30:00+00:00",
        "alternates": [{"airport": "WMKK"}],
        "edto": {"airports": [{"airport": "EINN"}]},
        "weather": [],
    }


def _snapshots() -> dict:
    return {
        "metar": {
            "status": "available",
            "provider": "noaa-awc-data-api",
            "source_url": (
                "https://aviationweather.gov/api/data/metar?"
                "format=json&ids=KJFK%2CWSSS%2CWMKK%2CEINN"
            ),
            "retrieved_at_utc": "2026-07-25T21:35:00+00:00",
            "records": [
                {
                    "icaoId": "WSSS",
                    "reportTime": "2026-07-25T21:30:00Z",
                    "rawOb": "METAR WSSS 252130Z 17006KT 9999 FEW018TCU SCT120 28/24 Q1010 NOSIG",
                }
            ],
        },
        "taf": [
            {
                "status": "available",
                "provider": "noaa-awc-data-api",
                "source_url": (
                    "https://aviationweather.gov/api/data/taf?"
                    "format=json&ids=KJFK%2CWSSS%2CWMKK%2CEINN"
                ),
                "retrieved_at_utc": "2026-07-25T21:35:00+00:00",
                "records": [
                    {
                        "icaoId": "WSSS",
                        "issueTime": "2026-07-25T11:00:00Z",
                        "validTimeFrom": 1784980800,
                        "validTimeTo": 1785088800,
                        "rawTAF": "TAF WSSS 251100Z 2512/2618 18008KT 9999 FEW015 SCT020 TEMPO 2603/2606 3000 TSRA FEW012CB BKN015",
                    }
                ],
            }
        ],
    }


def test_normalizes_official_records_and_fails_closed_for_missing_stations(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    flight = _flight()

    review = enrich_official_opmet(
        flight,
        snapshots=_snapshots(),
        now=datetime(2026, 7, 25, 21, 35, tzinfo=timezone.utc),
    )

    assert review["status"] == "review_required"
    assert "station_product_missing" in review["reason_codes"]
    assert [item["record_type"] for item in flight["weather"]] == ["METAR", "TAF"]
    assert all(item["source"] == "noaa_awc_live" for item in flight["weather"])
    assert flight["weather"][0]["raw_sha256"]


def test_deduplicates_the_same_official_record(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    flight = _flight()
    snapshots = _snapshots()

    now = datetime(2026, 7, 25, 21, 35, tzinfo=timezone.utc)
    enrich_official_opmet(flight, snapshots=snapshots, now=now)
    enrich_official_opmet(flight, snapshots=snapshots, now=now)

    assert len(flight["weather"]) == 2


def test_public_source_receipt_exposes_url_observation_and_forecast_validity(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    flight = _flight()

    review = enrich_official_opmet(
        flight,
        snapshots=_snapshots(),
        now=datetime(2026, 7, 25, 21, 35, tzinfo=timezone.utc),
    )

    metar, taf = flight["weather"]
    assert metar["source_url"] == (
        "https://aviationweather.gov/api/data/metar?"
        "format=json&ids=KJFK%2CWSSS%2CWMKK%2CEINN"
    )
    assert metar["observed_at_utc"] == "2026-07-25T21:30:00+00:00"
    assert taf["source_url"] == (
        "https://aviationweather.gov/api/data/taf?"
        "format=json&ids=KJFK%2CWSSS%2CWMKK%2CEINN"
    )
    assert taf["issue_time_utc"] == "2026-07-25T11:00:00+00:00"
    assert taf["valid_from_utc"] == "2026-07-25T12:00:00+00:00"
    assert taf["valid_to_utc"] == "2026-07-26T18:00:00+00:00"
    assert review["products"]["METAR"]["retrieved_at_utc"] == "2026-07-25T21:35:00+00:00"
    assert review["products"]["TAF"]["effective_end_utc"] == "2026-07-26T18:00:00+00:00"


def test_merged_taf_product_retains_every_request_receipt(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    snapshots = _snapshots()
    first = snapshots["taf"][0]
    first["source_url"] += "&date=2026-07-25T02%3A15%3A00Z&time=valid"
    second = deepcopy(first)
    second["source_url"] = second["source_url"].replace(
        "date=2026-07-25T02%3A15%3A00Z",
        "date=2026-07-25T21%3A30%3A00Z",
    )
    second["records"][0]["validTimeFrom"] = 1785016800
    second["records"][0]["validTimeTo"] = 1785099600
    snapshots["taf"].append(second)

    review = enrich_official_opmet(
        _flight(),
        snapshots=snapshots,
        now=datetime(2026, 7, 25, 21, 35, tzinfo=timezone.utc),
    )

    product = review["products"]["TAF"]
    assert product["source_url"] == first["source_url"], "legacy receipt remains compatible"
    assert [receipt["source_url"] for receipt in product["source_receipts"]] == [
        first["source_url"],
        second["source_url"],
    ]
    assert all(
        {
            "status",
            "source_url",
            "retrieved_at_utc",
            "effective_start_utc",
            "effective_end_utc",
            "refresh_after_utc",
            "expires_at_utc",
            "completeness_status",
        } <= receipt.keys()
        for receipt in product["source_receipts"]
    )


def test_expired_public_source_is_not_used_and_surfaces_review_required(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    flight = _flight()

    review = enrich_official_opmet(
        flight,
        snapshots=_snapshots(),
        now=datetime(2026, 7, 25, 22, 0, 1, tzinfo=timezone.utc),
    )

    assert flight["weather"] == []
    assert review["status"] == "review_required"
    assert "source_stale" in review["reason_codes"]
    assert review["products"]["METAR"]["status"] == "stale"

    # The analysis hook uses this exact deterministic finding, so the source
    # failure cannot remain an invisible audit-only ledger entry.
    gap = _official_weather_review_finding(review)
    assert gap is not None
    assert gap["severity"] == "unknown"
    assert gap["data"]["window_status"] == "review_required"
    assert gap["data"]["source_references"][0]["source_url"].startswith(
        "https://aviationweather.gov/api/data/"
    )


def test_destination_taf_that_does_not_cover_arrival_fails_closed(monkeypatch):
    monkeypatch.setenv("ODSS_OPMET_SOURCE", "awc")
    snapshots = _snapshots()
    snapshots["taf"][0]["records"][0]["validTimeTo"] = 1785009600  # 25 Jul 2000Z
    flight = _flight()

    review = enrich_official_opmet(
        flight,
        snapshots=snapshots,
        now=datetime(2026, 7, 25, 19, 59, tzinfo=timezone.utc),
    )

    assert review["status"] == "review_required"
    assert "essential_forecast_window_not_covered" in review["reason_codes"]
    assert any(
        gap["station"] == "WSSS"
        and gap["window_start_utc"] == "2026-07-25T20:30:00+00:00"
        and gap["window_end_utc"] == "2026-07-25T22:30:00+00:00"
        for gap in review["coverage_gaps"]
    )


def test_204_is_valid_available_no_data():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_product(
            AWC_METAR_PATH,
            {"ids": "WSSS", "hours": "6"},
            client=client,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )

    assert snapshot["status"] == "available"
    assert snapshot["records"] == []
    expected_url = (
        "https://aviationweather.gov/api/data/metar?"
        "format=json&hours=6&ids=WSSS"
    )
    assert requests == [expected_url]
    assert snapshot["source_url"] == expected_url
    assert snapshot["snapshot_scope"] == "requested_noaa_awc_metar_records"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert snapshot["refresh_after_utc"] == "2026-07-26T12:01:00+00:00"
    assert snapshot["expires_at_utc"] == "2026-07-26T12:05:00+00:00"


def test_taf_receipt_retains_the_exact_deterministic_request_url():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_product(
            AWC_TAF_PATH,
            {
                "time": "valid",
                "ids": "WSSS",
                "date": "2026-07-26T12:00:00Z",
            },
            client=client,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )

    expected_url = (
        "https://aviationweather.gov/api/data/taf?"
        "date=2026-07-26T12%3A00%3A00Z&format=json&ids=WSSS&time=valid"
    )
    assert requests == [expected_url]
    assert snapshot["source_url"] == expected_url


def test_malformed_json_fails_closed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not-json")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_product(
            AWC_METAR_PATH,
            {"ids": "WMKK", "hours": "6"},
            client=client,
        )

    assert snapshot["status"] == "unavailable"
    assert snapshot["records"] == []


def test_rejects_an_unapproved_endpoint():
    try:
        fetch_awc_product("/api/data/../../private", {"ids": "WSSS"})
    except ValueError as error:
        assert "Unsupported" in str(error)
    else:
        raise AssertionError("unapproved endpoint was accepted")
