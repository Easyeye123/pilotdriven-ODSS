from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.direct_vaac import (
    fetch_tokyo_vaac_snapshot,
    parse_tokyo_vaac_advisory,
    parse_tokyo_vaac_listing,
)


LISTING = b"""
<table>
<tr class="mtx"><td style="DISPLAY: none">2026/07/25 12:00:00</td>
<td>12:00 UTC, 25 Jul. 2026</td><td>SHEVELUCH</td><td>RUSSIA</td>
<td><font size=2 color="black">2026/294</font></td>
<td><a href="TextData/2026/20260725_30027000_0294_Text.html">Text</a></td>
<td><a href="javascript:void(0)" onClick="opennewwide('VAG/2026/html/20260725_30027000_0294_PF15.html')">VAG</a></td>
</tr>
<tr class="mtx"><td style="DISPLAY: none">2026/07/20 12:00:00</td>
<td>12:00 UTC, 20 Jul. 2026</td><td>OLD</td><td>RUSSIA</td>
<td><font size=2 color="black">2026/1</font></td>
<td><a href="TextData/2026/old_Text.html">Text</a></td></tr>
</table>
"""

ADVISORY = b"""
<html><body><!-- VAA Text Start -->FVFE01 RJTD 251200<BR>
VA ADVISORY<BR>DTG: 20260725/1200Z<BR>VAAC: TOKYO<BR>
VOLCANO: SHEVELUCH 300270<BR>AREA: RUSSIA<BR>ADVISORY NR: 2026/294<BR>
INFO SOURCE: HIMAWARI-9<BR>OBS VA DTG: 25/1120Z<BR>
OBS VA CLD: SFC/FL280 N5442 E15201 - N5854 E16246 - N5837 E16305 -<BR>
N5521 E15534<BR>
FCST VA CLD +6 HR: 25/1720Z SFC/FL280 N5945 E16452 - N5502 E15352 - N5012 E14657<BR>
FCST VA CLD +12 HR: 25/2320Z SFC/FL280 N6041 E16706 - N5731 E15755 - N5059 E14710<BR>
FCST VA CLD +18 HR: NO VA EXP<BR>NXT ADVISORY: 20260725/1800Z=<BR>
<!-- VAA Text End --></body></html>
"""


def _flight() -> dict:
    return {
        "scheduled_departure_utc": "2026-07-25T02:15:00+00:00",
        "scheduled_arrival_utc": "2026-07-25T21:30:00+00:00",
        "route_waypoints": [],
    }


def test_listing_keeps_only_fixed_official_urls():
    rows = parse_tokyo_vaac_listing(LISTING)

    assert rows[0]["volcano"] == "SHEVELUCH"
    assert rows[0]["vaa_url"].startswith(
        "https://www.data.jma.go.jp/vaac/data/TextData/"
    )
    assert rows[0]["vag_url"].startswith(
        "https://www.data.jma.go.jp/vaac/data/VAG/"
    )


def test_advisory_keeps_official_snapshots_without_interpolating():
    metadata = parse_tokyo_vaac_listing(LISTING)[0]
    advisory = parse_tokyo_vaac_advisory(ADVISORY, metadata)

    assert advisory["provider"] == "jma-tokyo-vaac"
    assert advisory["advisory_number"] == "2026/294"
    assert advisory["phases"][0]["state"] == "polygon_available"
    assert len(advisory["phases"][0]["polygon"]) == 4
    assert advisory["phases"][-1]["state"] == "no_ash_expected"
    assert "valid_from_utc" not in advisory["phases"][0]


def test_fetch_is_bounded_to_flight_window_and_official_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("vaac_list.html"):
            return httpx.Response(200, content=LISTING)
        return httpx.Response(200, content=ADVISORY)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = fetch_tokyo_vaac_snapshot(
            _flight(),
            client=client,
            now=datetime(2026, 7, 26, 13, tzinfo=timezone.utc),
        )

    assert snapshot["status"] == "available"
    assert snapshot["advisory_count"] == 1
    assert snapshot["snapshot_scope"] == "jma_tokyo_vaac_direct_advisories_for_requested_issue_window"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert snapshot["effective_start_utc"] == snapshot["requested_issue_window_start_utc"]
    assert snapshot["effective_end_utc"] == snapshot["requested_issue_window_end_utc"]
    assert seen == [
        "https://www.data.jma.go.jp/vaac/data/vaac_list.html",
        "https://www.data.jma.go.jp/vaac/data/TextData/2026/20260725_30027000_0294_Text.html",
    ]
