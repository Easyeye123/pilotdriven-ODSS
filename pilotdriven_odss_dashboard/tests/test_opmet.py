from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.opmet import (
    AWC_METAR_PATH,
    enrich_official_opmet,
    fetch_awc_product,
)


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
            "source_url": "https://aviationweather.gov/api/data/metar",
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
                "source_url": "https://aviationweather.gov/api/data/taf",
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

    enrich_official_opmet(flight, snapshots=snapshots)
    enrich_official_opmet(flight, snapshots=snapshots)

    assert len(flight["weather"]) == 2


def test_204_is_valid_available_no_data():
    def handler(_request: httpx.Request) -> httpx.Response:
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
    assert snapshot["snapshot_scope"] == "requested_noaa_awc_metar_records"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert snapshot["refresh_after_utc"] == "2026-07-26T12:01:00+00:00"
    assert snapshot["expires_at_utc"] == "2026-07-26T12:05:00+00:00"


def test_malformed_json_fails_closed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not-json")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_awc_product(
            AWC_METAR_PATH,
            {"ids": "WSSS", "hours": "6", "cache_buster": "malformed"},
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
