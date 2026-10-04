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
    monkeypatch.delenv("ODSS_ADWX_HK_URL", raising=False)
    monkeypatch.delenv("ODSS_ADWX_MAX_BULLETIN_AGE_HOURS", raising=False)


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


def test_real_cfp_parser_airport_shape_drives_every_warning_product():
    """The production parser uses departure/destination and alternate.airport."""
    flight = {
        "departure": "WSSS",
        "destination": "LIRF",
        "alternates": [
            {"airport": "LIRA"},
            {"airport": "LIMC"},
            {"airport": "EDDM"},
        ],
    }
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])

    review = adwx.enrich_aerodrome_warnings(flight, client=client, now=RETRIEVED_AT)

    assert review["stations_requested"] == ["WSSS", "LIRF", "LIRA", "LIMC", "EDDM"]
    assert list(review["products"]) == ["WSSS", "LIRF", "LIRA", "LIMC", "EDDM"]


def test_country_bulletin_without_affected_airport_requires_review():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    tokyo = review["products"]["RJTT"]
    assert tokyo["status"] == "review_required"
    assert tokyo["warnings"] == []
    assert "airport_scope_unresolved" in tokyo["reason_codes"]
    assert tokyo["source_receipts"][0]["source_url"].startswith(adwx.GTS_MIRROR_ORIGIN)
    assert tokyo["source_receipts"][0]["retrieved_at_utc"] == "2026-08-10T01:00:00Z"


def test_unscoped_nil_is_not_cleared_by_quiet_regional_api():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)
    singapore = review["products"]["WSSS"]
    assert singapore["status"] == "review_required"
    assert singapore["warnings"] == []
    assert "airport_scope_unresolved" in singapore["reason_codes"]


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
    warning = next(
        warning for warning in singapore["warnings"]
        if warning["provider"] == "mss-singapore-via-data-gov-sg"
    )
    assert warning["raw_text"] == SG_ACTIVE["data"]["records"][0]["warning"]
    assert warning["issued_utc_estimate"] == "2026-08-09T23:15:00Z"
    assert warning["source_url"] == adwx.AUTHORITY_API_ROWS["WS"]["url"]
    assert warning["scope"] == "authority_area"


def test_stale_structured_warning_is_never_shown():
    stale_payload = {
        "code": 0,
        "data": {"records": [{
            "warning": "Persisted warning that is no longer current",
            "issued": "2026-07-10T07:15:00+08:00",
        }]},
    }
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(200, json=stale_payload)),
    ])

    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)

    singapore = review["products"]["WSSS"]
    assert singapore["warnings"] == []


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


def test_dead_authority_api_is_not_masked_by_a_nil_mirror_bulletin():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text=INDEX_HTML)),
        ("/data/raw/wo/", httpx.Response(404, text="")),
        ("wwjp25.rjtd..txt", httpx.Response(200, text=JMA_BULLETIN)),
        ("wwsr20.wsss..txt", httpx.Response(200, text=NIL_BULLETIN)),
        ("api-open.data.gov.sg", httpx.Response(503, text="down")),
    ])

    review = adwx.enrich_aerodrome_warnings(_flight(), client=client, now=RETRIEVED_AT)

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
    assert tokyo["status"] == "review_required"
    assert tokyo["warnings"] == []
    assert "bulletin_issue_not_current" in tokyo["reason_codes"]


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
    warning = hong_kong["warnings"][0]
    assert warning["raw_text"] == hko_active["WHOT"]["name"]
    assert warning["issued_utc_estimate"] == "2026-08-09T22:45:00Z"
    assert warning["provider"] == "hko-via-official-open-data"
    assert warning["source_url"] == adwx.AUTHORITY_API_ROWS["VH"]["url"]
    assert warning["scope"] == "authority_area"


def test_an_unexpected_internal_error_never_fails_the_analysis(monkeypatch):
    # The enrichment rides the CFP analysis chain. Whatever breaks inside it,
    # the flight must still get an honest review — never an exception that
    # takes the whole briefing down with it.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic internal defect")

    monkeypatch.setattr(adwx, "_warning_index", _boom)
    flight = _flight()
    review = adwx.enrich_aerodrome_warnings(flight, now=RETRIEVED_AT)
    assert review["status"] == "review_required"
    assert "internal_error" in review["reason_codes"]
    assert review["products"] == {}
    assert flight["aerodrome_warning_review"] is review


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


WARNING_CHECK_AT = datetime(2026, 9, 8, 0, 30, tzinfo=timezone.utc)
MALAYSIA_INDEX = '<a href="woms31.wmkk..txt">woms31.wmkk..txt</a>'
EXACT_WMKP_WARNING = (
    "WOMS31 WMKK 072334\n"
    "WMKP AD WRNG 4 VALID 072350/080120 MOD RA VIS LESS THAN 4000M FCST\nWKN="
)


def _malaysia_warning_review(body: str):
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text="")),
        ("/data/raw/wo/", httpx.Response(200, text=MALAYSIA_INDEX)),
        ("woms31.wmkk..txt", httpx.Response(200, text=body)),
    ])
    return adwx.enrich_aerodrome_warnings(
        _flight("WMKK", "WMKJ", ("WMKP",)), client=client, now=WARNING_CHECK_AT,
    )


def test_exact_live_wmkp_warning_never_becomes_wmkk_or_wmkj_warning():
    products = _malaysia_warning_review(EXACT_WMKP_WARNING)["products"]
    for station in ("WMKK", "WMKJ"):
        assert products[station]["warnings"] == []
        assert products[station]["status"] == "review_required"
        assert "other_airport_messages_only" in products[station]["reason_codes"]
        assert products[station]["source_receipts"][0]["affected_airports"] == ["WMKP"]
    penang = products["WMKP"]
    assert penang["status"] == "warnings_held"
    assert len(penang["warnings"]) == 1
    warning = penang["warnings"][0]
    assert warning["affected_airport"] == "WMKP"
    assert warning["header"] == "WOMS31 WMKK"
    assert warning["issued_utc_estimate"] == "2026-09-07T23:34:00Z"
    assert warning["validity_period_raw"] == "072350/080120"
    assert warning["validity_assessment"] == "not_assessed"
    assert warning["raw_text"] == EXACT_WMKP_WARNING


def test_mixed_airport_messages_keep_only_their_own_body_and_validity():
    bulletin = (
        "WOMS31 WMKK 080015\n"
        "WMKP AD WRNG 4 VALID 072350/080120 MOD RA FCST WKN=\n"
        "WMKK AD WRNG 2 VALID 080020/080200 SFC WSPD 35KT=\n"
        "WMKJ WS WRNG 1 080010 VALID TL 080130 MOD WS APCH RWY 16="
    )
    products = _malaysia_warning_review(bulletin)["products"]
    expected = {"WMKP": "072350/080120", "WMKK": "080020/080200", "WMKJ": "TL 080130"}
    for station, validity in expected.items():
        warnings = products[station]["warnings"]
        assert len(warnings) == 1
        assert warnings[0]["affected_airport"] == station
        assert warnings[0]["validity_period_raw"] == validity
        body = warnings[0]["raw_text"].split("\n", 1)[1]
        assert body.startswith(station)
        assert body.count("WRNG") == 1


def test_adjacent_messages_without_equals_do_not_leak_next_airport():
    products = _malaysia_warning_review(
        "WOMS31 WMKK 080015\n"
        "WMKP AD WRNG 4 VALID 072350/080120 MOD RA FCST WKN\n"
        "WMKK AD WRNG 2 VALID 080020/080200 SFC WSPD 35KT\n"
    )["products"]
    assert "SFC WSPD" not in products["WMKP"]["warnings"][0]["raw_text"]
    assert "MOD RA" not in products["WMKK"]["warnings"][0]["raw_text"]


def test_concatenated_wmo_envelopes_use_each_own_issue_time():
    products = _malaysia_warning_review(
        "WOMS31 WMKK 070020\nWMKP AD WRNG 4 VALID 070030/070230 MOD RA=\n"
        "WOMS31 WMKK 080015\nWMKK AD WRNG 2 VALID 080020/080200 SFC WSPD 35KT="
    )["products"]
    assert products["WMKP"]["warnings"][0]["issued_utc_estimate"] == "2026-09-07T00:20:00Z"
    assert products["WMKK"]["warnings"][0]["issued_utc_estimate"] == "2026-09-08T00:15:00Z"
    assert "WMKP AD WRNG" not in products["WMKK"]["warnings"][0]["raw_text"]


def test_cancellation_stays_with_its_airport_and_does_not_claim_all_clear():
    products = _malaysia_warning_review(
        "WOMS31 WMKK 080015\n"
        "WMKP AD WRNG 5 VALID 080020/080120\nCNL AD WRNG 4 072350/080120=\n"
        "WMKK AD WRNG 2 VALID 080020/080200 SFC WSPD 35KT="
    )["products"]
    assert products["WMKP"]["status"] == "warnings_held"
    warning = products["WMKP"]["warnings"][0]
    assert warning["message_status"] == "cancellation"
    assert "CNL AD WRNG 4" in warning["raw_text"]
    assert warning["validity_period_raw"] == "080020/080120"
    assert products["WMKK"]["warnings"][0]["message_status"] == "warning"


@pytest.mark.parametrize("body,reason", [
    ("WOMS31 WMKK 080015\nNIL=", "airport_scope_unresolved"),
    ("WOMS31 WMKK 080015\nWARNING FOR PENANG AREA MOD RA=", "airport_scope_unresolved"),
    ("WOMS31 WMKK 060015\nWMKK AD WRNG 2 VALID 060020/060200 MOD RA=", "bulletin_issue_not_current"),
    ("WMKK AD WRNG 2 VALID 080020/080200 MOD RA=", "bulletin_issue_not_current"),
    ("WOMS31 WMKK 080015\nWMKK WMKP AD WRNG 2 VALID 080020/080200 MOD RA=", "airport_scope_unresolved"),
])
def test_unresolved_scope_or_issue_never_becomes_clear(body, reason):
    products = _malaysia_warning_review(body)["products"]
    for product in products.values():
        assert product["warnings"] == []
        assert product["status"] == "review_required"
        assert reason in product["reason_codes"]
        assert product["source_receipts"]


def test_missing_validity_is_held_as_unassessed_without_inventing_a_period():
    products = _malaysia_warning_review(
        "WOMS31 WMKK 080015\nWMKP AD WRNG 5 MOD RA FCST="
    )["products"]
    warning = products["WMKP"]["warnings"][0]
    assert warning["validity_period_raw"] is None
    assert warning["validity_assessment"] == "not_assessed"
    assert "warning_validity_unresolved" in products["WMKP"]["reason_codes"]


def test_quiet_authority_api_retains_its_own_absence_receipt():
    client = _client([
        ("/data/raw/ww/", httpx.Response(200, text="")),
        ("/data/raw/wo/", httpx.Response(200, text="")),
        ("api-open.data.gov.sg", httpx.Response(200, json=SG_QUIET)),
    ])
    singapore = adwx.enrich_aerodrome_warnings(
        _flight("WSSS", "WSSS"), client=client, now=RETRIEVED_AT,
    )["products"]["WSSS"]
    assert singapore["status"] == "no_active_warning"
    assert singapore["source_receipts"][0]["scope"] == "authority_area"
    assert singapore["source_receipts"][0]["status"] == "no_active_warning"


def test_message_terminator_is_not_invented_from_later_message():
    penang = _malaysia_warning_review(
        "WOMS31 WMKK 080015\nWMKP AD WRNG 4 VALID 072350/080120 MOD RA\n"
        "WMKK AD WRNG 2 VALID 080020/080200 SFC WSPD 35KT="
    )["products"]["WMKP"]["warnings"][0]
    assert penang["raw_text"].endswith("MOD RA")


def test_unscoped_cancellation_does_not_attach_to_issuing_airport():
    products = _malaysia_warning_review(
        "WOMS31 WMKK 080015\nCNL AD WRNG 4 072350/080120="
    )["products"]
    assert all(product["warnings"] == [] for product in products.values())
    assert all(product["status"] == "review_required" for product in products.values())
