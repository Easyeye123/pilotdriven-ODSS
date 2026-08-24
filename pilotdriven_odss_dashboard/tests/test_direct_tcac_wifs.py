from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.direct_tcac_wifs import (
    fetch_wifs_global_tca_snapshot,
    parse_wifs_tca_collective,
)


COLLECTIVE = b"""LKNT21 KNHC 180900
TC ADVISORY
DTG: 20260818/0900Z
TCAC: MIAMI
TC: TESTONE
ADVISORY NR: 2026/01
OBS PSN: 18/0900Z N1800 W06000
MOV: W 10KT
INTST CHANGE: INTSF
C: 980HPA
MAX WIND: 80KT
FCST PSN +6 HR: 18/1500Z N1812 W06100
FCST MAX WIND +6 HR: 85KT
NXT MSG: 20260818/1500Z
=
LKPQ30 RJTD 180905
TC ADVISORY
DTG: 20260818/0905Z
TCAC: TOKYO
TC: TESTTWO
ADVISORY NR: 2026/02
OBS PSN: 18/0900Z N2200 E14000
MOV: NW 08KT
INTST CHANGE: NC
C: 970HPA
MAX WIND: 90KT
FCST PSN +6 HR: 18/1500Z N2240 E13920
FCST MAX WIND +6 HR: 90KT
NXT MSG: 20260818/1500Z
=
"""


def _flight() -> dict[str, str]:
    return {
        "scheduled_departure_utc": "2026-08-18T08:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-18T16:00:00+00:00",
    }


def test_wifs_tca_collective_verifies_tcac_identity_and_forecast_fields() -> None:
    advisories, errors = parse_wifs_tca_collective(COLLECTIVE.decode())

    assert errors == []
    assert [item["centre"] for item in advisories] == ["TOKYO", "MIAMI"]
    assert advisories[0]["cyclone"] == "TESTTWO"
    assert advisories[0]["forecasts"] == [{
        "hours": 6,
        "position": "18/1500Z N2240 E13920",
        "maximum_wind": "90KT",
    }]


def test_wifs_tca_collective_rejects_unverified_centres() -> None:
    malformed = COLLECTIVE.decode().replace("TCAC: MIAMI", "TCAC: MADE UP", 1)
    advisories, errors = parse_wifs_tca_collective(malformed)

    assert [item["centre"] for item in advisories] == ["TOKYO"]
    assert errors == [{"record": "1", "error": "TCA centre or DTG could not be verified"}]


def test_wifs_tca_fetch_is_bounded_keyed_and_never_places_key_in_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=COLLECTIVE)

    snapshot = fetch_wifs_global_tca_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 18, 9, 12, tzinfo=timezone.utc),
        api_key="synthetic-secret-key",
    )

    assert snapshot["status"] == "available"
    assert snapshot["coverage_status"] == "global_seven_tcac_tac_advisories"
    assert snapshot["advisory_count"] == 2
    assert len(snapshot["centres"]) == 7
    assert len(requests) == 1
    assert requests[0].headers["X-API-KEY"] == "synthetic-secret-key"
    assert "synthetic-secret-key" not in str(requests[0].url)
    assert requests[0].url.params["parameter-name"] == "TCA"
    assert requests[0].url.params["datetime"] == "2026-08-18T09:10:00Z/PT36H"


def test_missing_wifs_key_keeps_direct_tca_unavailable_without_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=COLLECTIVE)

    snapshot = fetch_wifs_global_tca_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 18, 9, 12, tzinfo=timezone.utc),
        api_key="",
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["coverage_status"] == "not_configured"
    assert calls == 0
