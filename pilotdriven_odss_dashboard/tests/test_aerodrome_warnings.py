"""Aerodrome-warning engine: dynamic country coverage with honest absence.

Boss instruction, 10.08.26 — dep/dest met-authority warnings in Flight
Brief (Singapore localised thunderstorms / Sumatran squall line, Hong Kong
typhoon). The engine is deliberately generic: country coverage comes from
the ICAO prefix against the public GTS mirror index plus data-only
authority rows — never per-country code, never invented warnings.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.odss import aerodrome_warnings as adwx


RETRIEVED_AT = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)

INDEX_HTML = (
    '<html><body>'
    '<a href="wwjp25.rjtd..txt">wwjp25.rjtd..txt</a>'
    '<a href="wwsr20.wsss..txt">wwsr20.wsss..txt</a>'
    '<a href="wwus30.kwns..txt">wwus30.kwns..txt</a>'
    '</body></html>'
)
JMA_BULLETIN = (
    "WWJP25 RJTD 100030\n"
    "WARNING FOR TOKYO AREA VALID 100030/100630\n"
    "LOCALISED HEAVY THUNDERSTORMS EXPECTED.\n"
)
NIL_BULLETIN = "WWSR20 WSSS 100000\nNIL=\n"
SG_ACTIVE = {
    "code": 0,
    "data": {"records": [{
        "warning": "Heavy rain with Sumatran squall line expected 0730-0930",
        "issued": "2026-08-10T07:15:00+08:00",
    }]},
}
SG_QUIET = {"code": 17, "name": "REAL_TIME_API_DATA_NOT_FOUND", "data": None, "errorMsg": "Data not found"}


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(adwx, "_CACHE", {})
    monkeypatch.delenv("ODSS_ADWX_SOURCE", raising=False)
    monkeypatch.delenv("ODSS_ADWX_SG_URL", raising=False)


def _client(routes):
    def _serve(request: httpx.Request) -> httpx.Response:
        for match, response in routes:
            if request.url.path.endswith(match) or match in request.url.host:
                if isinstance(response, Exception):
                    raise response
                return response
        return httpx.Response(404, text="")

    return httpx.Client(transport=httpx.MockTransport(_serve))


def _flight(departure="RJTT", destination="WSSS", alternates=()):
    return {
        "departure_icao": departure,
        "destination_icao": destination,
        "alternates": [{"icao": code} for code in alternates],
    }


def test_prefix_match_serves_the_authoritys_own_bulletin_verbatim():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    tokyo = review["products"]["RJTT"]
    assert tokyo["status"] == "warnings_held"
    assert tokyo["warnings"][0]["header"] == "WWJP25 RJTD"
    assert "LOCALISED HEAVY THUNDERSTORMS" in tokyo["warnings"][0]["raw_text"]
    assert tokyo["warnings"][0]["source_url"].startswith(adwx.GTS_MIRROR_ORIGIN)
    assert tokyo["source_receipts"][0]["retrieved_at_utc"] == "2026-08-10T01:00:00Z"


def test_nil_bulletin_and_quiet_api_are_a_normal_no_warning_state():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    singapore = review["products"]["WSSS"]
    assert singapore["status"] == "no_active_warning"
    assert singapore["warnings"] == []


def test_singapore_active_warning_arrives_from_the_official_api():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_ACTIVE)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    singapore = review["products"]["WSSS"]
    assert singapore["status"] == "warnings_held"
    texts = " ".join(warning["raw_text"] for warning in singapore["warnings"])
    assert "Sumatran squall line" in texts
    assert any(
        warning["provider"] == "mss-singapore-via-data-gov-sg"
        for warning in singapore["warnings"]
    )


def test_fetch_failure_never_reads_as_no_active_warning():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(500, text="")),
        ("wwsr20.wsss..txt", httpx.Response(500, text="")),
        ("api-open.data.gov.sg", httpx.Response(503, text="down")),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    assert review["products"]["RJTT"]["status"] == "unavailable"
    assert review["products"]["WSSS"]["status"] == "unavailable"


def test_a_country_publishing_nothing_is_reported_as_exactly_that():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
    ])
    review = adwx.enrich_aerodrome_warnings(
        _flight(departure="LFPG", destination="EHAM"), client=client, now=RETRIEVED_AT
    )
    assert review["products"]["LFPG"]["status"] == "no_public_feed"
    assert review["products"]["EHAM"]["status"] == "no_public_feed"
    assert review["products"]["LFPG"]["warnings"] == []


def test_mirror_outage_is_unavailable_and_never_blocks_the_briefing():
    client = _client([
        ("/data/raw/ww/", httpx.ConnectError("refused")),
        ("/data/raw/wo/", httpx.ConnectError("refused")),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    flight = _flight(departure="RJTT", destination="RJAA")
    review = adwx.enrich_aerodrome_warnings(flight, client=client, now=RETRIEVED_AT)
    assert review["status"] == "covered"
    assert "gts_mirror_unavailable" in review["reason_codes"]
    assert review["products"]["RJTT"]["status"] == "unavailable"
    assert flight["aerodrome_warning_review"] is review


def test_disabled_source_and_missing_stations_stay_honest():
    disabled_flight = _flight()
    import os

    os.environ["ODSS_ADWX_SOURCE"] = "disabled"
    try:
        review = adwx.enrich_aerodrome_warnings(disabled_flight, now=RETRIEVED_AT)
    finally:
        del os.environ["ODSS_ADWX_SOURCE"]
    assert review["status"] == "not_assessed"
    assert review["reason_codes"] == ["source_disabled"]

    empty = adwx.enrich_aerodrome_warnings({}, now=RETRIEVED_AT)
    assert empty["status"] == "review_required"
    assert empty["reason_codes"] == ["airport_identifiers_unavailable"]


def test_a_stale_persisted_bulletin_is_not_a_live_warning():
    # The mirror keeps a centre's last file forever. A July heading read in
    # August must not surface as a held warning.
    stale = "WWJP25 RJTD 150000\nWARNING FOR TOKYO AREA\nTHUNDERSTORMS.\n"
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=stale)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    tokyo = review["products"]["RJTT"]
    assert tokyo["status"] == "no_active_warning"
    assert tokyo["warnings"] == []


def test_hong_kong_active_warning_arrives_from_the_official_hko_api():
    hko_active = {
        "WHOT": {
            "name": "Very Hot Weather Warning",
            "code": "WHOT",
            "actionCode": "REISSUE",
            "issueTime": "2026-08-05T06:45:00+08:00",
            "updateTime": "2026-08-10T06:45:00+08:00",
        },
        "WCANCELLED": {"name": "Old Signal", "code": "TC1", "actionCode": "CANCEL"},
    }
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("data.weather.gov.hk", httpx.Response(200, json=hko_active)),
    ])
    review = adwx.enrich_aerodrome_warnings(
        _flight(departure="RJTT", destination="VHHH"), client=client, now=RETRIEVED_AT
    )
    hong_kong = review["products"]["VHHH"]
    assert hong_kong["status"] == "warnings_held"
    assert len(hong_kong["warnings"]) == 1
    assert "Very Hot Weather Warning" in hong_kong["warnings"][0]["raw_text"]
    assert hong_kong["warnings"][0]["provider"] == "hko-via-official-open-data"


def test_engine_stays_generic_no_phenomenon_or_country_branches():
    import inspect

    source = inspect.getsource(adwx)
    # Everything from the first function onward is engine logic; the module
    # docstring (which quotes the boss) and the data-only authority rows may
    # name phenomena, the logic never may.
    logic = source.split("def _cache_seconds", 1)[1]
    for term in ("Sumatran", "typhoon", "squall", "WSSS", "VHHH", "RJTT", "RJTD"):
        assert term not in logic, f"engine logic must not branch on {term}"
    assert "".join(sorted(adwx._SINGLE_LETTER_PREFIXES)) == "CKUY"
