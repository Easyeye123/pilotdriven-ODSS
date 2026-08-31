from __future__ import annotations

import httpx

from app.odss.direct_vaac_gts import (
    GTS_CENTRES,
    NOAA_GTS_ORIGIN,
    fetch_gts_vaac_snapshots,
    parse_advisory_psn,
    parse_gts_listing,
    parse_gts_vaac_advisory,
)


# Boss 30 Aug: "Need a way for reliable ... VAA" — every ICAO centre reachable
# from the one GTS mirror, each bulletin identity-checked and DTG-bounded.

LONDON_ACTIVE = """FVXX01 EGRR 301200
VA ADVISORY
DTG: 20260830/1200Z
VAAC: LONDON
VOLCANO: GRIMSVOTN 373010
PSN: N6425 W01720
AREA: ICELAND
SUMMIT ELEV: 1725M
ADVISORY NR: 2026/041
INFO SOURCE: ICELANDIC MET OFFICE
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: INTERMITTENT ASH EMISSIONS
OBS VA DTG: 30/1130Z
OBS VA CLD: SFC/FL200 N6425 W01720 - N6440 W01640 - N6410 W01600 -
N6350 W01700 - N6425 W01720
FCST VA CLD +6 HR: 30/1730Z SFC/FL200 NO VA EXP
RMK: NIL
NXT ADVISORY: 20260830/1800Z
"""

WELLINGTON_ACTIVE = """FVPS01 NZKL 301100
VA ADVISORY
DTG: 20260830/1100Z
VAAC: WELLINGTON
VOLCANO: WHAKAARI 241040
PSN: S3731 E17711
AREA: NEW ZEALAND
ADVISORY NR: 2026/007
INFO SOURCE: GNS SCIENCE
OBS VA DTG: 30/1030Z
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA
NXT ADVISORY: NO FURTHER ADVISORIES
"""

# The mirror keeps the last bulletin per slot forever: this 2013-era bulletin
# is exactly what a freshness gate must refuse to treat as current coverage.
ANCHORAGE_STALE_2013 = """FVAK21 PANC 011014
VAAAK1
VA ADVISORY
DTG: 20131001/1015Z
VAAC: ANCHORAGE
VOLCANO: KATMAI 1101-17
PSN: N5816 W15459
AREA: ALASKA PENINSULA
ADVISORY NR: 2013/016
OBS VA DTG: 01/1015Z
OBS VA CLD: NO VA OBSERVED
NXT ADVISORY: NO FURTHER ADVISORIES
"""

INDEX_HTML = """<html><body><pre>
<a href="fvxx01.egrr..txt">fvxx01.egrr..txt</a>  30-Aug-2026 12:01  1k
<a href="fvxx01.egrr.par.t2.txt">fvxx01.egrr.par.t2.txt</a>  30-Aug-2026 12:01  4k
<a href="fvps01.nzkl..txt">fvps01.nzkl..txt</a>  30-Aug-2026 11:02  1k
<a href="fvak21.panc..txt">fvak21.panc..txt</a>  01-Oct-2013 10:16  1k
<a href="fvcn01.cwao..txt">fvcn01.cwao..txt</a>  30-Aug-2026 09:00  1k
<a href="fvxx20.knes..txt">fvxx20.knes..txt</a>  30-Aug-2026 08:00  1k
<a href="fvag01.sabm..txt">fvag01.sabm..txt</a>  30-Aug-2026 07:00  1k
<a href="fvxx01.lfpw..txt">fvxx01.lfpw..txt</a>  30-Aug-2026 06:00  1k
<a href="fvfe01.rjtd..txt">fvfe01.rjtd..txt</a>  30-Aug-2026 05:00  1k
<a href="fvau01.adrm..txt">fvau01.adrm..txt</a>  30-Aug-2026 04:00  1k
</pre></body></html>"""


def _flight() -> dict[str, object]:
    return {
        "scheduled_departure_utc": "2026-08-30T10:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-30T16:00:00+00:00",
    }


def test_every_icao_centre_has_a_slot_table_row() -> None:
    assert set(GTS_CENTRES) == {
        "ANCHORAGE", "BUENOS AIRES", "DARWIN", "LONDON", "MONTREAL",
        "TOKYO", "TOULOUSE", "WASHINGTON", "WELLINGTON",
    }


def test_listing_slices_per_centre_and_drops_chart_variants() -> None:
    assert [row["file"] for row in parse_gts_listing(INDEX_HTML, "LONDON")] == [
        "fvxx01.egrr..txt",
    ]
    assert [row["file"] for row in parse_gts_listing(INDEX_HTML, "WELLINGTON")] == [
        "fvps01.nzkl..txt",
    ]
    assert [row["file"] for row in parse_gts_listing(INDEX_HTML, "WASHINGTON")] == [
        "fvxx20.knes..txt",
    ]
    assert [row["file"] for row in parse_gts_listing(INDEX_HTML, "BUENOS AIRES")] == [
        "fvag01.sabm..txt",
    ]


def test_advisory_identity_and_position_parse() -> None:
    advisory = parse_gts_vaac_advisory(LONDON_ACTIVE, {"file": "fvxx01.egrr..txt"}, "LONDON")
    assert advisory["vaac"] == "LONDON"
    assert advisory["volcano"].startswith("GRIMSVOTN")
    assert advisory["aviation_colour_code"] == "ORANGE"
    assert advisory["next_advisory"] == "20260830/1800Z"
    position = advisory["volcano_position"]
    assert round(position["latitude"], 2) == 64.42
    assert round(position["longitude"], 2) == -17.33


def test_wrong_centre_signature_is_refused() -> None:
    try:
        parse_gts_vaac_advisory(LONDON_ACTIVE, {"file": "x"}, "TOULOUSE")
    except ValueError as exc:
        assert "TOULOUSE" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("A London bulletin must not enter as Toulouse")


def test_psn_parser_never_invents_positions() -> None:
    assert parse_advisory_psn("S0832 E12246") == {"latitude": -8.5333, "longitude": 122.7667}
    assert parse_advisory_psn("N5816 W15459") == {"latitude": 58.2667, "longitude": -154.9833}
    assert parse_advisory_psn("garbled") is None
    assert parse_advisory_psn("N9999 E99999") is None


def test_one_mirror_pass_yields_fresh_centres_and_drops_stale_bulletins() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/fv/"):
            return httpx.Response(200, text=INDEX_HTML)
        if path.endswith("fvxx01.egrr..txt"):
            return httpx.Response(200, text=LONDON_ACTIVE)
        if path.endswith("fvps01.nzkl..txt"):
            return httpx.Response(200, text=WELLINGTON_ACTIVE)
        if path.endswith("fvak21.panc..txt"):
            return httpx.Response(200, text=ANCHORAGE_STALE_2013)
        return httpx.Response(404, text="missing")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=NOAA_GTS_ORIGIN,
    )
    snapshots = fetch_gts_vaac_snapshots(
        _flight(),
        client=client,
        centres=("LONDON", "WELLINGTON", "ANCHORAGE"),
    )

    london = snapshots["LONDON"]
    assert london["status"] == "available"
    assert london["advisory_count"] == 1
    assert london["advisories"][0]["centre"] == "LONDON"
    assert london["next_advisory_due"] == "20260830/1800Z"

    wellington = snapshots["WELLINGTON"]
    assert wellington["advisory_count"] == 1

    anchorage = snapshots["ANCHORAGE"]
    # The 2013 bulletin was read and identity-verified, then excluded by its
    # own DTG: the slot is reachable, but there is no current advisory and the
    # receipt still names the stale listing time instead of claiming coverage.
    assert anchorage["status"] == "available"
    assert anchorage["advisory_count"] == 0
    assert anchorage["listing_latest_utc"] == "2013-10-01T10:15:00+00:00"


def test_unreachable_mirror_fails_every_requested_centre_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=NOAA_GTS_ORIGIN,
    )
    snapshots = fetch_gts_vaac_snapshots(
        _flight(), client=client, centres=("LONDON", "MONTREAL"),
    )
    assert {snapshot["status"] for snapshot in snapshots.values()} == {"unavailable"}
    assert all(snapshot["advisories"] == [] for snapshot in snapshots.values())
