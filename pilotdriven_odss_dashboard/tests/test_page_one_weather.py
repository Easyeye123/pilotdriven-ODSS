"""The page-1 METAR / TAF rule, pinned to the dashboard's copy of it.

B4 fix round 1 (reviewer, 17 Sep 2026): the page-1 METAR/TAF fields printed
the full held record with the OFP record headers and terminators (``SA 201900
11004KT 9999 FEW018 BKN300 28/23 Q1011 NOSIG=``) while David's reference page
1 prints the trimmed groups (``11004KT 9999 FEW018``, ``16008KT 9999
FEW015/SCT020``) and adds local time under SCHEDULE. One trim rule, applied to
both surfaces in the same change.

``tests/fixtures/page1-weather-vectors.json`` is minted by the app repo
(``scripts/mint-page1-weather-vectors.mjs``) from every held record in the
real corpora and carries the groups the dashboard prints. This suite asserts
the Python implementation reproduces every vector, so the two surfaces cannot
drift apart without one of the suites going red.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.odss.brief_theme import local_clock_label
from app.odss.page_one_weather import (
    PAGE1_WEATHER_RULE,
    forecast_source_line,
    page_one_metar_field,
    page_one_taf_field,
    page_one_weather_groups,
)

VECTORS = Path(__file__).resolve().parent / "fixtures" / "page1-weather-vectors.json"

WSSS_METAR = "SA  201900 11004KT 9999 FEW018 BKN300 28/23 Q1011 NOSIG="
WSSS_TAF = "FT  201700 2018/2200 16008KT 9999 FEW015 SCT020="
RPLL_METAR = "SA  201900 VRB02KT 9999 FEW025 28/26 Q1010 NOSIG RMK A2983="
RPLL_TAF = "FT  201700 2018/2124 25007KT 9999 FEW025 TX32/2106Z TN26/2021Z TEMPO 2103/2109 27015KT FEW025 BKN090="


def test_the_page_one_metar_prints_every_held_group():
    # David, 21 Sep 2026 21:22 with the KUL destination card photographed: the
    # METAR is shortened too much. v1 stopped at the temperature group.
    assert page_one_metar_field(WSSS_METAR, "WEATHER page") == "11004KT 9999 FEW018/BKN300 28/23 Q1011 NOSIG"
    assert page_one_metar_field(RPLL_METAR, "WEATHER page") == "VRB02KT 9999 FEW025 28/26 Q1010 NOSIG RMK A2983"
    assert page_one_metar_field(
        "METAR WSSS 201900Z AUTO 11004KT 9999 FEW018 BKN300 28/23 Q1011 NOSIG=", "WEATHER page"
    ) == "11004KT 9999 FEW018/BKN300 28/23 Q1011 NOSIG"
    assert page_one_metar_field(
        "SA 161350 AUTO 28015KT 260V320 9999 FEW041 BKN056 20/10 Q1013 NOSIG=", "WEATHER page"
    ) == "28015KT 260V320 9999 FEW041/BKN056 20/10 Q1013 NOSIG"
    assert page_one_metar_field(
        "SA 201900 11004KT 0800 R20C/P2000 FG SCT008 BKN015 OVC030 24/24 Q1011=", "WEATHER page"
    ) == "11004KT 0800 R20C/P2000 FG SCT008/BKN015/OVC030 24/24 Q1011"
    assert page_one_metar_field(
        "SA 281353 29005KT 10SM FEW170 FEW230 25/18 A2987 RMK AO2 SLP111 T02500183=", "WEATHER page"
    ) == "29005KT 10SM FEW170/FEW230 25/18 A2987 RMK AO2 SLP111 T02500183"
    assert page_one_metar_field("SA 251400 24009KT CAVOK 24/M04 Q1026 NOSIG=", "WEATHER page") == "24009KT CAVOK 24/M04 Q1026 NOSIG"


def test_a_trend_or_wind_shear_group_is_printed_never_replaced_by_a_pointer():
    for record, expected in (
        ("SA 201900 11004KT 9999 FEW018 28/23 Q1011 NOSIG=", "11004KT 9999 FEW018 28/23 Q1011 NOSIG"),
        ("SA 201900 11004KT 9999 FEW018 28/23 Q1011 TEMPO 3000 TSRA=", "11004KT 9999 FEW018 28/23 Q1011 TEMPO 3000 TSRA"),
        ("SA 201900 11004KT 9999 FEW018 28/23 Q1011 WS ALL RWY NOSIG=", "11004KT 9999 FEW018 28/23 Q1011 WS ALL RWY NOSIG"),
    ):
        assert page_one_metar_field(record, "WEATHER page") == expected
        assert "trend:" not in page_one_metar_field(record, "WEATHER page")


def test_the_page_one_taf_prints_the_base_period_and_every_change_group():
    # David, 22 Sep 2026 13:38: "TAF Tempo is truncated why????".
    assert page_one_taf_field(WSSS_TAF, "WEATHER page") == "16008KT 9999 FEW015/SCT020"
    assert page_one_taf_field(RPLL_TAF, "WEATHER page") == (
        "25007KT 9999 FEW025 TX32/2106Z TN26/2021Z TEMPO 2103/2109 27015KT FEW025/BKN090"
    )
    assert page_one_taf_field(
        "FT 160227 1603/1703 29008KT CAVOK TEMPO 1620/1622 SCT020TCU TEMPO 1700/1703 4000 SHRA SCT020TCU=",
        "WEATHER page",
    ) == "29008KT CAVOK TEMPO 1620/1622 SCT020TCU TEMPO 1700/1703 4000 SHRA SCT020TCU"
    assert page_one_taf_field(
        "FC 152000 1521/1606 27010KT 5000 HZ SCT020 BKN100 BECMG 1603/1604 6000=", "WEATHER page"
    ) == "27010KT 5000 HZ SCT020/BKN100 BECMG 1603/1604 6000"
    assert page_one_taf_field(
        "TAF AMD WSSS 110900Z 1109/1212 27015G25KT 3000 TSRA BKN012CB BECMG 1112/1114 25010KT PROB30 TEMPO 1118/1122 4000 SHRA=",
        "WEATHER page",
    ) == "27015G25KT 3000 TSRA BKN012CB BECMG 1112/1114 25010KT PROB30 TEMPO 1118/1122 4000 SHRA"


def test_an_empty_or_missing_record_is_stated_not_invented():
    assert page_one_taf_field("FT WX NOT AVAILABLE", "WEATHER page") == "WX NOT AVAILABLE"
    assert page_one_taf_field("TAF WSSS 201700Z NIL=", "WEATHER page") == "NIL"
    assert page_one_metar_field("", "WEATHER page") == "Not held"
    assert page_one_metar_field(None, "WEATHER page") == "Not held"
    assert page_one_metar_field({"text": WSSS_METAR}, "WEATHER page") == "11004KT 9999 FEW018/BKN300 28/23 Q1011 NOSIG"
    assert page_one_metar_field("SA 201900=", "WEATHER page") == "SA 201900"


def test_no_held_cloud_layer_or_weather_group_is_dropped():
    result = page_one_weather_groups("SA 201900 11004KT 9999 -SHRA SCT008 BKN015CB OVC030 28/23 Q1011=", "metar")
    assert result["groups"] == "11004KT 9999 -SHRA SCT008/BKN015CB/OVC030 28/23 Q1011"
    assert result["envelope"] == ["SA", "201900"]
    assert result["tail"] == []
    assert result["more"] is False


def test_every_corpus_record_reproduces_the_vector_the_dashboard_is_pinned_to():
    if not VECTORS.is_file():
        pytest.skip("page1-weather-vectors.json is not present")
    fixture = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert fixture["rule"] == PAGE1_WEATHER_RULE
    vectors = fixture["vectors"]
    assert len(vectors) >= 100
    for vector in vectors:
        actual = page_one_weather_groups(vector["record"], vector["kind"])
        assert actual["groups"] == vector["groups"], (
            f"{vector['flight']} {vector['station']} {vector['kind']}: {vector['record']}"
        )
        assert actual["more"] is False, f"{vector['flight']} {vector['station']} {vector['kind']} more-flag"
    stations = {vector["record"] for vector in vectors if vector["role"] in {"departure", "destination"}}
    assert len(stations) >= 90
    for record in (WSSS_METAR, WSSS_TAF, RPLL_METAR, RPLL_TAF):
        assert " ".join(record.split()) in stations


def test_the_local_clock_is_the_registry_zone_for_the_flight_instant_or_nothing():
    assert local_clock_label("WSSS", "2026-08-21T00:50:00+00:00") == "0850 LT"
    assert local_clock_label("RPLL", "2026-08-21T04:45:00+00:00") == "1245 LT"
    # Daylight saving is resolved for the flight's own date, not today's.
    assert local_clock_label("KJFK", "2026-08-21T04:45:00+00:00") == "0045 LT"
    assert local_clock_label("KJFK", "2026-01-21T04:45:00+00:00") == "2345 LT"
    assert local_clock_label("ZZZZ", "2026-08-21T00:50:00+00:00") is None
    assert local_clock_label("WSSS", None) is None
    assert local_clock_label(None, "2026-08-21T00:50:00+00:00") is None


def test_the_weather_page_source_line_names_the_shape_it_holds():
    taf = {"display_title": "NOAA Aviation Weather Center", "issued_at_utc": "2026-08-16T08:00:00+00:00",
           "valid_from_utc": "2026-08-16T08:00:00+00:00", "valid_to_utc": "2026-08-17T12:00:00+00:00"}
    assert forecast_source_line(taf) == "NOAA Aviation Weather Center; issued 16AUG 0800Z; valid 16AUG 0800Z-17AUG 1200Z."
    metar = {"source_type": "uploaded_cfp", "display_title": "Uploaded company OFP", "record_type": "METAR",
             "observed_at_utc": "2026-08-20T19:00:00+00:00"}
    assert forecast_source_line(metar) == "Basis: METAR observation 20AUG 1900Z; Uploaded company OFP."
    assert forecast_source_line({"provider": "noaa-awc-data-api"}) == "noaa-awc-data-api; issue and validity times not held."
    for shape in (taf, metar, {"provider": "noaa-awc-data-api"}):
        assert "details unavailable" not in forecast_source_line(shape)
