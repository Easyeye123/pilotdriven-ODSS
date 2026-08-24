from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.direct_vaac_toulouse import (
    TOULOUSE_VAAC_ORIGIN,
    fetch_toulouse_vaac_snapshot,
    parse_toulouse_vaac_advisory,
    parse_toulouse_vaac_listing,
)
from app.odss.vaa import fetch_mounted_vaac_snapshots, mounted_vaac_centres


SLUG = "211060_20260818075433"
PAGE_PATH = f"/advisory/2026/{SLUG}/{SLUG}/"
LISTING = f"""
<html><body>
<a href="{TOULOUSE_VAAC_ORIGIN}{PAGE_PATH}">ETNA.105</a>
<a href="{TOULOUSE_VAAC_ORIGIN}{PAGE_PATH}">duplicate presentation link</a>
<a href="https://attacker.example/advisory/2026/{SLUG}/{SLUG}/">unsafe</a>
</body></html>
""".encode()
ADVISORY = b"""VA ADVISORY
DTG: 20260818/0754Z
VAAC: TOULOUSE
VOLCANO: ETNA 211060
PSN: N3744 E01459
AREA: SICILY VOLCANIC PROVINCE
ADVISORY NR: 2026/105
INFO SOURCE: VONA, SAT IMAGERY
ERUPTION DETAILS: EXPLOSIVE ACTIVITY IS DECREASING
OBS VA DTG: 18/0730Z
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA WIND FL100 290/20KT
FCST VA CLD +6 HR: 18/1330Z NO VA EXP
FCST VA CLD +12 HR: 18/1930Z NO VA EXP
FCST VA CLD +18 HR: 19/0130Z NO VA EXP
NXT ADVISORY: NO FURTHER ADVISORIES=
"""


def _flight() -> dict[str, str]:
    return {
        "scheduled_departure_utc": "2026-08-18T06:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-18T14:00:00+00:00",
    }


def test_toulouse_listing_accepts_only_bounded_official_advisory_links() -> None:
    rows = parse_toulouse_vaac_listing(LISTING)

    assert len(rows) == 1
    assert rows[0]["issued_at_utc"] == "2026-08-18T07:54:33+00:00"
    assert rows[0]["vaa_url"].endswith(f"/{SLUG}_vaa.txt")
    assert rows[0]["vag_url"].endswith(f"/{SLUG}_vag.png")


def test_toulouse_advisory_verifies_centre_identity_and_keeps_vag_receipt() -> None:
    row = parse_toulouse_vaac_listing(LISTING)[0]
    advisory = parse_toulouse_vaac_advisory(ADVISORY, row)

    assert advisory["centre"] == "TOULOUSE"
    assert advisory["advisory_number"] == "2026/105"
    assert advisory["phases"][0]["state"] == "not_identifiable"
    assert advisory["phases"][1]["state"] == "no_ash_expected"
    assert len(advisory["raw_sha256"]) == 64


def test_toulouse_fetch_uses_one_listing_and_only_selected_text_records() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/docs/":
            return httpx.Response(200, content=LISTING)
        if request.url.path.endswith("_vaa.txt"):
            return httpx.Response(200, content=ADVISORY)
        return httpx.Response(404)

    snapshot = fetch_toulouse_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "available"
    assert snapshot["coverage_status"] == "toulouse_vaac_latest_operational_advisories"
    assert snapshot["advisory_count"] == 1
    assert [request.url.path for request in requests] == [
        "/docs/",
        f"/advisory/2026/{SLUG}/{SLUG}_vaa.txt",
    ]


def test_toulouse_mount_is_route_independent_and_reports_its_own_centre(monkeypatch) -> None:
    from app.odss import direct_vaac_toulouse

    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "toulouse")
    monkeypatch.setattr(direct_vaac_toulouse, "live_toulouse_vaac_snapshot", lambda flight: {
        "status": "available",
        "provider": "meteo-france-toulouse-vaac",
        "advisory_count": 0,
        "advisories": [],
    })

    mounted = mounted_vaac_centres()
    snapshots = fetch_mounted_vaac_snapshots(_flight(), mounted)

    assert mounted == [{
        "token": "toulouse",
        "centre": "TOULOUSE",
        "provider": "meteo-france-toulouse-vaac",
    }]
    assert snapshots[0]["centre"] == "TOULOUSE"
