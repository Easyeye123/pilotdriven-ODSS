from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.tc_track import (
    assess_tropical_cyclone_track,
    fetch_hko_track_snapshot,
    parse_hko_track,
)


TRACK_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<TropicalCycloneTrack tcid="2617">
  <BulletinHeader>
    <BulletinProvider>Hong Kong Observatory</BulletinProvider>
    <BulletinTime>2026-07-26T19:00:22+08:00</BulletinTime>
  </BulletinHeader>
  <WeatherReport>
    <TropicalCycloneName>NOUL</TropicalCycloneName>
    <PastInformation>
      <Time>2026-07-26T06:00:00+00:00</Time>
      <Latitude>23.50N</Latitude><Longitude>114.10E</Longitude>
      <Intensity>Tropical Storm</Intensity><MaximumWind>85km/h</MaximumWind>
    </PastInformation>
    <AnalysisInformation>
      <Time>2026-07-26T09:00:00+00:00</Time>
      <Latitude>24.00N</Latitude><Longitude>114.00E</Longitude>
      <Intensity>Tropical Storm</Intensity><MaximumWind>65km/h</MaximumWind>
    </AnalysisInformation>
    <ForecastInformation>
      <Index>1</Index><Latitude>24.20N</Latitude><Longitude>113.90E</Longitude>
    </ForecastInformation>
    <ForecastInformation>
      <Time>2026-07-27T09:00:00+00:00</Time>
      <Latitude>27.40N</Latitude><Longitude>112.70E</Longitude>
      <Intensity>Low Pressure Area</Intensity><MaximumWind>40km/h</MaximumWind>
    </ForecastInformation>
  </WeatherReport>
</TropicalCycloneTrack>"""


def _snapshot() -> dict:
    return {
        "status": "available",
        "provider": "hong-kong-observatory-public-tc-track",
        "source_url": "https://www.weather.gov.hk/wxinfo/currwx/tc_list.xml",
        "retrieved_at_utc": "2026-07-26T11:00:00+00:00",
        "attribution": "Source: Hong Kong Observatory via DATA.GOV.HK",
        "tracks": [parse_hko_track(TRACK_XML, cyclone_id="2617")],
        "errors": [],
    }


def _flight() -> dict:
    return {
        "scheduled_departure_utc": "2026-07-26T06:00:00+00:00",
        "route_waypoints": [
            {
                "name": "A",
                "latitude": 23.5,
                "longitude": 114.5,
                "actm_minutes": 0,
            },
            {
                "name": "B",
                "latitude": 27.5,
                "longitude": 113.0,
                "actm_minutes": 27 * 60,
            },
        ],
    }


def test_keeps_only_official_timed_positions():
    track = parse_hko_track(TRACK_XML, cyclone_id="2617")

    assert [item["kind"] for item in track["positions"]] == [
        "past",
        "analysis",
        "forecast",
    ]
    assert track["positions"][-1]["time_utc"] == "2026-07-27T09:00:00+00:00"


def test_rejects_doctype_and_entities():
    for raw in (
        b"<!DOCTYPE foo><TropicalCycloneTrack/>",
        b"<!ENTITY x 'bad'><TropicalCycloneTrack/>",
    ):
        try:
            parse_hko_track(raw, cyclone_id="2617")
        except ValueError as error:
            assert "prohibited" in str(error)
        else:
            raise AssertionError("unsafe XML declaration accepted")


def test_compares_timed_track_with_timed_route_without_claiming_impact(monkeypatch):
    monkeypatch.setenv("ODSS_TC_TRACK_SOURCE", "hko")
    review = assess_tropical_cyclone_track(_flight(), snapshot=_snapshot())

    assert review["status"] == "context_available"
    cyclone = review["cyclones"][0]
    assert cyclone["movement"]["speed_knots"] > 0
    assert cyclone["closest_route_screening"]["distance_nm"] < 500
    assert cyclone["screening_status"] == "near_route_centreline_review_required"
    assert "not a wind field" in review["source_note"]
    assert "screening estimate" in cyclone["closest_route_screening"]["position_basis"]


def test_source_failure_is_review_required(monkeypatch):
    monkeypatch.setenv("ODSS_TC_TRACK_SOURCE", "hko")
    review = assess_tropical_cyclone_track(
        _flight(),
        snapshot={"status": "unavailable", "provider": "hko", "tracks": []},
    )

    assert review["status"] == "review_required"
    assert review["reason_codes"] == ["source_unavailable"]


def test_fetches_only_fixed_hko_paths():
    list_xml = b"""<TropicalCycloneList><TropicalCyclone>
      <TropicalCycloneID>2617</TropicalCycloneID>
      <TropicalCycloneEnglishName>NOUL</TropicalCycloneEnglishName>
      <TropicalCycloneURL>http://evil.example/steal.xml</TropicalCycloneURL>
    </TropicalCyclone></TropicalCycloneList>"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("tc_list.xml"):
            return httpx.Response(200, content=list_xml)
        return httpx.Response(200, content=TRACK_XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_hko_track_snapshot(
            client=client,
            now=datetime(2026, 7, 26, 11, tzinfo=timezone.utc),
        )

    assert snapshot["status"] == "available"
    assert snapshot["snapshot_scope"] == "hko_published_tropical_cyclone_track_files"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert snapshot["effective_start_utc"] is not None
    assert snapshot["effective_end_utc"] is not None
    assert seen == [
        "https://www.weather.gov.hk/wxinfo/currwx/tc_list.xml",
        "https://www.weather.gov.hk/wxinfo/currwx/hko_tctrack_2617.xml",
    ]
