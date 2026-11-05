from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.odss.direct_vaac import (
    advisory_next_receipt,
    advisory_phase,
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

# Exact field grammar from Tokyo VAAC advisory 2026/172, issued for
# Sakurajima during the authentic SQ38 flight window.  The source URL is
# https://www.data.jma.go.jp/vaac/data/TextData/2026/
# 20260830_28208001_0172_Text.html; only the advisory's own PSN is evidence
# for the position below.
SAKURAJIMA_ADVISORY = b"""
<html><body><!-- VAA Text Start -->FVFE01 RJTD 300503<BR>
VA ADVISORY<BR>DTG: 20260830/0503Z<BR>VAAC: TOKYO<BR>
VOLCANO: SAKURAJIMA (AIRA CALDERA) 282080<BR>
PSN: N3136 E13039<BR>AREA: JAPAN<BR>SOURCE ELEV: 1117M AMSL<BR>
ADVISORY NR: 2026/172<BR>INFO SOURCE: JMA HIMAWARI-9<BR>
ERUPTION DETAILS: ERUPTED AT 20260830/0449Z OVER FL080 STNR<BR>
OBS VA DTG: 30/0450Z<BR>
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA WIND FL180 240/6KT<BR>
FCST VA CLD +6 HR: NOT AVBL<BR>FCST VA CLD +12 HR: NOT AVBL<BR>
FCST VA CLD +18 HR: NOT AVBL<BR>
RMK: WE WILL ISSUE FURTHER ADVISORY IF VA IS DETECTED IN SATELLITE IMAGERY.<BR>
NXT ADVISORY: NO FURTHER ADVISORIES=<BR>
<!-- VAA Text End --></body></html>
"""

SAKURAJIMA_METADATA = {
    "issued_at_utc": "2026-08-30T05:03:00+00:00",
    "volcano": "SAKURAJIMA (AIRA CALDERA)",
    "area": "JAPAN",
    "advisory_number": "2026/172",
    "vaa_url": (
        "https://www.data.jma.go.jp/vaac/data/TextData/2026/"
        "20260830_28208001_0172_Text.html"
    ),
}


def test_next_advisory_receipt_separates_future_due_from_exact_notes() -> None:
    valid_due, notes = advisory_next_receipt([
        {
            "issued_at_utc": "2026-08-30T12:00:00+00:00",
            "next_advisory": "20260830/1800Z",
            "advisory_number": "2026/041",
            "volcano": "ALPHA 000001",
        },
        {
            "issued_at_utc": "2026-08-30T12:00:00+00:00",
            "next_advisory": "20260830/1100Z",
            "advisory_number": "2026/040",
            "volcano": "BRAVO 000002",
        },
        {
            "issued_at_utc": "2026-08-30T12:00:00+00:00",
            "next_advisory": "20261330/1900Z",
            "advisory_number": "2026/039",
            "volcano": "CHARLIE 000003",
        },
        {
            "issued_at_utc": "2026-08-30T12:00:00+00:00",
            "next_advisory": "NO FURTHER ADVISORIES",
            "advisory_number": "2026/038",
            "volcano": "DELTA 000004",
        },
        {
            "issued_at_utc": None,
            "next_advisory": "20260830/1900Z",
            "advisory_number": "2026/037",
            "volcano": "ECHO 000005",
        },
    ])
    assert valid_due == "20260830/1800Z"
    assert notes == [
        "ADVISORY 2026/040 / BRAVO 000002: 20260830/1100Z",
        "ADVISORY 2026/039 / CHARLIE 000003: 20261330/1900Z",
        "ADVISORY 2026/038 / DELTA 000004: NO FURTHER ADVISORIES",
        "ADVISORY 2026/037 / ECHO 000005: 20260830/1900Z",
    ]

    note_only_due, note_only = advisory_next_receipt([
        {
            "issued_at_utc": "2026-08-30T12:00:00+00:00",
            "next_advisory": "NO FURTHER ADVISORIES",
            "advisory_number": "2026/172",
            "volcano": "SAKURAJIMA 282080",
        }
    ])
    assert note_only_due is None
    assert note_only == [
        "ADVISORY 2026/172 / SAKURAJIMA 282080: NO FURTHER ADVISORIES"
    ]


@pytest.mark.parametrize(
    "invalid_vertex",
    (
        "N9100 E10000",
        "N3160 E10000",
        "N3100 E18100",
    ),
)
def test_advisory_phase_withholds_whole_polygon_for_any_invalid_vertex(
    invalid_vertex: str,
) -> None:
    phase = advisory_phase(
        "observed",
        (
            "30/1200Z SFC/FL100 N3000 E10000 - N3100 E10100 - "
            f"{invalid_vertex} - N3000 E10200"
        ),
        datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert phase["state"] == "text_only"
    assert phase["polygon"] is None


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


def test_tokyo_exercise_advisory_is_rejected() -> None:
    exercise = ADVISORY.replace(
        b"VA ADVISORY<BR>",
        b"VA ADVISORY<BR>STATUS: EXER<BR>",
    )

    with pytest.raises(ValueError, match="exercise advisory"):
        parse_tokyo_vaac_advisory(
            exercise,
            parse_tokyo_vaac_listing(LISTING)[0],
        )


def test_tokyo_advisory_psn_drives_the_authentic_sq38_volcano_proximity() -> None:
    from app.odss.vaa import volcano_proximity_from_snapshots

    advisory = parse_tokyo_vaac_advisory(
        SAKURAJIMA_ADVISORY,
        SAKURAJIMA_METADATA,
    )

    assert advisory["centre"] == "TOKYO"
    assert advisory["volcano_position"] == {
        "latitude": 31.6,
        "longitude": 130.65,
    }

    # Exact adjacent coordinate rows from the supplied SQ38 LIDO OFP route
    # (SHIBK to the following RJJJ boundary) which establish its closest
    # approach to the advisory PSN without inventing a catalogue position.
    flight = {
        "route_waypoints": [
            {"name": "SHIBK", "latitude": 29.6533333333333, "longitude": 132.08},
            {"name": "-RJJJ", "latitude": 30.485, "longitude": 133.261666666667},
        ],
    }
    review = volcano_proximity_from_snapshots(
        flight,
        [{"advisories": [advisory]}],
    )

    assert review["status"] == "held"
    assert review["entries"] == [{
        "volcano": "SAKURAJIMA (AIRA CALDERA) 282080",
        "centre": "TOKYO",
        "advisory_number": "2026/172",
        "aviation_colour_code": None,
        "position": {"latitude": 31.6, "longitude": 130.65},
        "distance_nm": 137.1,
        "within_corridor": True,
        "issued_at_utc": "2026-08-30T05:03:00+00:00",
        "next_advisory": "NO FURTHER ADVISORIES=",
    }]


def test_tokyo_advisory_without_an_explicit_psn_never_invents_a_position() -> None:
    metadata = parse_tokyo_vaac_listing(LISTING)[0]
    advisory = parse_tokyo_vaac_advisory(ADVISORY, metadata)

    assert advisory["volcano_position"] is None

    for malformed_psn in (
        b"N3160 E13039",
        b"N3136 E13060",
        b"N9100 E13039",
        b"N9160 E13039",
        b"N3136 E18100",
    ):
        malformed = SAKURAJIMA_ADVISORY.replace(b"N3136 E13039", malformed_psn)
        advisory = parse_tokyo_vaac_advisory(malformed, SAKURAJIMA_METADATA)
        assert advisory["volcano_position"] is None


def test_tokyo_advisory_body_must_match_the_selected_listing_identity() -> None:
    mismatched_bodies = (
        SAKURAJIMA_ADVISORY.replace(b"20260830/0503Z", b"20260830/0504Z"),
        SAKURAJIMA_ADVISORY.replace(b"2026/172", b"2026/171"),
        SAKURAJIMA_ADVISORY.replace(
            b"SAKURAJIMA (AIRA CALDERA) 282080",
            b"MAYON 273030",
        ),
    )

    for body in mismatched_bodies:
        with pytest.raises(ValueError, match="identity"):
            parse_tokyo_vaac_advisory(body, SAKURAJIMA_METADATA)


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
    assert snapshot["next_advisory_due"] == "20260725/1800Z="
    assert snapshot["next_advisory_notes"] == []
    assert seen == [
        "https://www.data.jma.go.jp/vaac/data/vaac_list.html",
        "https://www.data.jma.go.jp/vaac/data/TextData/2026/20260725_30027000_0294_Text.html",
    ]
