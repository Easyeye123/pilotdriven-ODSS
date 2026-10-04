from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.odss.direct_vaac_darwin import (
    NOAA_GTS_ORIGIN,
    PROVIDER,
    fetch_darwin_vaac_snapshot,
    parse_darwin_gts_listing,
    parse_darwin_vaac_advisory,
)
from app.odss.vaa import mounted_vaac_centres, vaac_centre_ledger


# The issued Krakatau termination bulletin from the mirror, 18 Aug 2026 - the
# exact update class a printed CFP cannot carry.
KRAKATAU_TERMINATED = """FVAU05 ADRM 180800
VA ADVISORY
DTG: 20260818/0800Z
VAAC: DARWIN
VOLCANO: KRAKATAU 262000
PSN: S0606 E10525
AREA: INDONESIA
SUMMIT ELEV: 155M
ADVISORY NR: 2026/116
INFO SOURCE: HIMAWARI-9
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: VA EMISSIONS HAVE CEASED
OBS VA DTG: 18/0750Z
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA
FCST VA CLD +6 HR: 18/1350Z NO VA EXP
FCST VA CLD +12 HR: 18/1950Z NO VA EXP
FCST VA CLD +18 HR: 19/0150Z NO VA EXP
RMK: CURRENT SATELLITE IMAGERY INDICATES VA HAS NOW DISSIPATED. NO REPORTS
OF NEW OR ONGOING ERUPTION. ADVISORY TERMINATED.
NXT ADVISORY: NO FURTHER ADVISORIES
"""

LEWOTOBI_ACTIVE = """FVAU04 ADRM 180730
VA ADVISORY
DTG: 20260818/0730Z
VAAC: DARWIN
VOLCANO: LEWOTOBI 264180
PSN: S0832 E12246
AREA: INDONESIA
ADVISORY NR: 2026/392
INFO SOURCE: HIMAWARI-9, GROUND REPORT
OBS VA DTG: 18/0540Z
OBS VA CLD: VA TO FL080 LAST OBS AT 18/0540Z MOV NW
FCST VA CLD +6 HR: 18/1330Z SFC/FL080 S0835 E12248 - S0834 E12219 -
S0822 E12219 - S0813 E12227 - S0831 E12249
RMK: VA NOT VISIBLE IN LATEST SATELLITE IMAGERY HOWEVER GROUND REPORTS
CONFIRM INTERMITTENT ERUPTIONS CONTINUE.
NXT ADVISORY: 20260818/1330Z
"""

INDEX_HTML = """<html><body><pre>
<a href="fvak20.pawu..txt">fvak20.pawu..txt</a>  18-Aug-2026 06:10  1k
<a href="fvau04.adrm..txt">fvau04.adrm..txt</a>  18-Aug-2026 07:30  1k
<a href="fvau05.adrm..txt">fvau05.adrm..txt</a>  18-Aug-2026 07:58  1k
<a href="fvau01.ammc..txt">fvau01.ammc..txt</a>  16-Nov-2018 20:06  1k
<a href="fvfe01.rjtd..txt">fvfe01.rjtd..txt</a>  18-Aug-2026 07:44  1k
</pre></body></html>"""


def _flight() -> dict[str, object]:
    # Window is issue-time based: departure-18h to arrival+1h, so the 0800Z
    # termination bulletin sits inside it for this arrival.
    return {
        "scheduled_departure_utc": "2026-08-18T02:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-18T07:30:00+00:00",
    }


def test_listing_keeps_only_darwin_adrm_bulletins() -> None:
    rows = parse_darwin_gts_listing(INDEX_HTML)
    assert [row["file"] for row in rows] == ["fvau04.adrm..txt", "fvau05.adrm..txt"]
    assert rows[0]["vaa_url"].startswith(f"{NOAA_GTS_ORIGIN}/data/raw/fv/")


def test_advisory_identity_is_verified_from_the_bulletin_itself() -> None:
    advisory = parse_darwin_vaac_advisory(KRAKATAU_TERMINATED, {"file": "fvau05.adrm..txt"})
    assert advisory["provider"] == PROVIDER
    assert advisory["vaac"] == "DARWIN"
    assert advisory["centre"] == "DARWIN"
    assert advisory["volcano"] == "KRAKATAU 262000"
    assert advisory["advisory_number"] == "2026/116"
    assert advisory["issued_at_utc"] == "2026-08-18T08:00:00+00:00"
    assert advisory["volcano_position"] == {
        "latitude": -6.1,
        "longitude": 105.41667,
    }
    assert advisory["aviation_colour_code"] == "ORANGE"
    assert "ADVISORY TERMINATED" in advisory["remarks"]
    assert advisory["phases"] and advisory["phases"][0]["phase"] == "observed"
    assert advisory["phases"][0]["state"] == "not_identifiable"


def test_darwin_wmo_header_time_must_match_body_dtg() -> None:
    mismatched = KRAKATAU_TERMINATED.replace(
        "FVAU05 ADRM 180800",
        "FVAU05 ADRM 180801",
    )

    with pytest.raises(ValueError, match="WMO issue time"):
        parse_darwin_vaac_advisory(
            mismatched,
            {"file": "fvau05.adrm..txt"},
        )

    malformed = KRAKATAU_TERMINATED.replace("S0606 E10525", "S0660 E10525")
    assert parse_darwin_vaac_advisory(
        malformed,
        {"file": "fvau05.adrm..txt"},
    )["volcano_position"] is None


def test_darwin_wmo_header_must_match_fetched_mirror_slot() -> None:
    swapped = KRAKATAU_TERMINATED.replace("FVAU05 ADRM", "FVAU04 ADRM")

    with pytest.raises(ValueError, match="mirror slot"):
        parse_darwin_vaac_advisory(
            swapped,
            {"file": "fvau05.adrm..txt"},
        )


def test_darwin_body_dtg_must_be_an_exact_field_value() -> None:
    malformed = KRAKATAU_TERMINATED.replace(
        "DTG: 20260818/0800Z",
        "DTG: INVALID 20260818/0800Z TRAILER",
    )

    with pytest.raises(ValueError, match="readable DTG"):
        parse_darwin_vaac_advisory(
            malformed,
            {"file": "fvau05.adrm..txt"},
        )


def test_a_bulletin_from_another_centre_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_darwin_vaac_advisory(
            KRAKATAU_TERMINATED.replace("VAAC: DARWIN", "VAAC: TOKYO"),
            {"file": "fvau05.adrm..txt"},
        )
    with pytest.raises(ValueError):
        parse_darwin_vaac_advisory(
            KRAKATAU_TERMINATED.replace("FVAU05 ADRM", "FVFE01 RJTD"),
            {"file": "fvau05.adrm..txt"},
        )


def test_snapshot_retains_only_advisories_inside_the_flight_window() -> None:
    stale = KRAKATAU_TERMINATED.replace(
        "FVAU05 ADRM 180800",
        "FVAU04 ADRM 100800",
    ).replace("DTG: 20260818/0800Z", "DTG: 20260610/0800Z")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/fv/"):
            return httpx.Response(200, text=INDEX_HTML)
        if path.endswith("fvau04.adrm..txt"):
            return httpx.Response(200, text=stale)
        if path.endswith("fvau05.adrm..txt"):
            return httpx.Response(200, text=KRAKATAU_TERMINATED)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_darwin_vaac_snapshot(
            _flight(), client=client, now=datetime(2026, 8, 18, 8, 30, tzinfo=timezone.utc)
        )
    assert snapshot["status"] == "available", snapshot.get("errors")
    assert snapshot["advisory_count"] == 1
    assert snapshot["advisories"][0]["advisory_number"] == "2026/116"
    assert snapshot["next_advisory_due"] is None
    assert snapshot["next_advisory_notes"] == [
        "ADVISORY 2026/116 / KRAKATAU 262000: NO FURTHER ADVISORIES"
    ]


@pytest.mark.parametrize("index_body", ("", "<html>maintenance</html>"))
def test_zero_recognized_darwin_slots_fail_coverage_closed(index_body) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=index_body)

    snapshot = fetch_darwin_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 18, 8, 30, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["coverage_status"] == "unavailable"
    assert snapshot["advisories"] == []
    assert "recognized fixed Darwin GTS mirror slot" in snapshot["errors"][0]["error"]


def test_darwin_position_identity_and_colour_reach_the_route_ring() -> None:
    from app.odss.vaa import volcano_proximity_from_snapshots

    advisory = parse_darwin_vaac_advisory(
        KRAKATAU_TERMINATED,
        {"file": "fvau05.adrm..txt"},
    )
    review = volcano_proximity_from_snapshots(
        {
            "route_waypoints": [
                {"latitude": -6.1, "longitude": 104.0},
                {"latitude": -6.1, "longitude": 106.0},
            ],
        },
        [{"centre": "DARWIN", "advisories": [advisory]}],
    )

    assert review["entries"][0]["centre"] == "DARWIN"
    assert review["entries"][0]["aviation_colour_code"] == "ORANGE"


def test_an_unreachable_mirror_fails_closed_rather_than_reporting_no_ash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_darwin_vaac_snapshot(_flight(), client=client)
    assert snapshot["status"] == "unavailable"
    assert snapshot["advisories"] == []
    assert snapshot["errors"]


def test_an_unreadable_bulletin_degrades_to_partial_not_silence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/fv/"):
            return httpx.Response(200, text=INDEX_HTML)
        if path.endswith("fvau04.adrm..txt"):
            return httpx.Response(200, text=LEWOTOBI_ACTIVE)
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_darwin_vaac_snapshot(
            _flight(), client=client, now=datetime(2026, 8, 18, 8, 30, tzinfo=timezone.utc)
        )
    assert snapshot["status"] == "partial"
    assert snapshot["advisory_count"] == 1
    assert snapshot["errors"] and "fvau05" in snapshot["errors"][0]["source_url"]


def test_darwin_is_mounted_by_token_and_named_in_the_ledger(monkeypatch) -> None:
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "jma-tokyo,anchorage,darwin")
    mounted = mounted_vaac_centres()
    assert [entry["centre"] for entry in mounted] == ["TOKYO", "ANCHORAGE", "DARWIN"]
    assert mounted[2]["provider"] == "noaa-gts-darwin-vaa"
    ledger = vaac_centre_ledger(
        [{"centre": "DARWIN", "provider": PROVIDER, "status": "available",
          "coverage_status": "darwin_vaac_area_direct_advisories",
          "advisory_count": 1, "source_url": "https://tgftp.nws.noaa.gov/data/raw/fv/"}],
        mounted,
    )
    darwin_row = next(row for row in ledger if row["centre"] == "DARWIN")
    assert darwin_row["status"] == "available"
