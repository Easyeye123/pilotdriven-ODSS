from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.odss.direct_vaac_wifs import (
    fetch_wifs_global_vaac_snapshot,
    parse_wifs_vaa_collective,
    wifs_centre_snapshot,
)
from app.odss.vaa import fetch_mounted_vaac_snapshots, mounted_vaac_centres


COLLECTIVE = b"""\
LUXX01 EGRR 160600
VA ADVISORY
DTG: 20260816/0600Z
VAAC: LONDON
VOLCANO: TEST ONE 999001
AREA: TEST AREA
ADVISORY NR: 2026/101
OBS VA DTG: 16/0600Z
OBS VA CLD: SFC/FL200 N6000 W01000 - N6100 W00900 - N6000 W00800
FCST VA CLD +6 HR: 16/1200Z NO VA EXP
NXT ADVISORY: 20260816/1200Z
=
LUXX02 ADRM 160605
VA ADVISORY
DTG: 20260816/0605Z
VAAC: DARWIN
VOLCANO: TEST TWO 999002
AREA: TEST AREA
ADVISORY NR: 2026/202
OBS VA DTG: 16/0605Z
OBS VA CLD: SFC/FL180 S0600 E12500 - S0700 E12600 - S0600 E12700
FCST VA CLD +6 HR: 16/1205Z S0600 E12600 - S0700 E12700 - S0600 E12800
NXT ADVISORY: 20260816/1200Z
=
"""

WASHINGTON_NO_SPACE_FORECAST = """\
FVXX01 KWBC 160600
VA ADVISORY
DTG: 20260816/0600Z
VAAC: WASHINGTON
VOLCANO: TEST THREE 999003
AREA: TEST AREA
ADVISORY NR: 2026/303
OBS VA DTG: 16/0600Z
OBS VA CLD: SFC/FL200 N2000 W10000 - N2100 W09900 - N2000 W09800
FCST VA CLD +6HR: 16/1200Z SFC/FL200 N2100 W09900 - N2200 W09800 - N2100 W09700
NXT ADVISORY: 20260816/1200Z
"""


def _flight() -> dict[str, str]:
    return {
        "scheduled_departure_utc": "2026-08-16T05:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-16T14:00:00+00:00",
    }


def test_wifs_collective_verifies_centre_identity_and_keeps_official_phases() -> None:
    advisories, errors = parse_wifs_vaa_collective(COLLECTIVE.decode())

    assert errors == []
    assert [item["centre"] for item in advisories] == ["DARWIN", "LONDON"]
    assert advisories[0]["advisory_number"] == "2026/202"
    assert advisories[0]["phases"][0]["state"] == "polygon_available"
    assert advisories[1]["phases"][1]["state"] == "no_ash_expected"


def test_washington_no_space_forecast_key_is_canonicalized() -> None:
    advisories, errors = parse_wifs_vaa_collective(
        WASHINGTON_NO_SPACE_FORECAST
    )

    assert errors == []
    assert [item["centre"] for item in advisories] == ["WASHINGTON"]
    assert [phase["phase"] for phase in advisories[0]["phases"]] == [
        "observed",
        "forecast_plus_6_hours",
    ]


def test_wifs_exercise_advisory_is_a_coverage_error_not_nil() -> None:
    exercise = WASHINGTON_NO_SPACE_FORECAST.replace(
        "VA ADVISORY\n",
        "VA ADVISORY\nSTATUS: EXERCISE\n",
    )

    advisories, errors = parse_wifs_vaa_collective(exercise)

    assert advisories == []
    assert errors == [{
        "record": "1",
        "error": "Exercise VAA is not operational evidence",
    }]


def test_wifs_collective_rejects_an_unknown_vaac_instead_of_guessing() -> None:
    unknown = COLLECTIVE.decode().replace("VAAC: LONDON", "VAAC: MADE UP", 1)
    advisories, errors = parse_wifs_vaa_collective(unknown)

    assert [item["centre"] for item in advisories] == ["DARWIN"]
    assert errors == [{"record": "1", "error": "VAA centre or DTG could not be verified"}]


def test_wifs_collective_fails_closed_when_multiple_record_boundaries_are_missing() -> None:
    unbounded = COLLECTIVE.decode().replace("\n=\n", "\n")

    advisories, errors = parse_wifs_vaa_collective(unbounded)

    assert advisories == []
    assert errors == [{
        "record": "collective",
        "error": "Multiple VAA record boundaries could not be verified",
    }]


def test_wifs_collective_marks_a_safety_limit_truncation_as_partial(monkeypatch) -> None:
    from app.odss import direct_vaac_wifs

    monkeypatch.setattr(direct_vaac_wifs, "_MAX_ADVISORIES", 1)

    advisories, errors = parse_wifs_vaa_collective(COLLECTIVE.decode())

    assert len(advisories) == 1
    assert errors == [{
        "record": "collective",
        "error": "WIFS VAA collective exceeded the 1-record safety limit",
    }]


def test_wifs_fetch_is_one_bounded_global_request_and_never_places_key_in_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=COLLECTIVE, headers={"content-type": "text/plain"})

    snapshot = fetch_wifs_global_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 16, 6, 22, tzinfo=timezone.utc),
        api_key="synthetic-secret-key",
    )

    assert snapshot["status"] == "available"
    assert snapshot["coverage_status"] == "global_nine_vaac_tac_advisories"
    assert snapshot["advisory_count"] == 2
    assert len(snapshot["centres"]) == 9
    assert len(requests) == 1
    assert requests[0].headers["X-API-KEY"] == "synthetic-secret-key"
    assert "synthetic-secret-key" not in str(requests[0].url)
    assert requests[0].url.params["datetime"] == "2026-08-16T06:20:00Z/PT36H"
    assert requests[0].url.params["parameter-name"] == "VAA"


def test_missing_wifs_key_fails_closed_without_touching_the_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=COLLECTIVE)

    snapshot = fetch_wifs_global_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime(2026, 8, 16, 6, 22, tzinfo=timezone.utc),
        api_key="",
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["coverage_status"] == "not_configured"
    assert calls == 0


def test_empty_or_all_malformed_wifs_responses_are_never_available() -> None:
    empty = fetch_wifs_global_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"")
        )),
        now=datetime(2026, 8, 16, 6, 22, tzinfo=timezone.utc),
        api_key="synthetic-secret-key",
    )
    malformed = fetch_wifs_global_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=COLLECTIVE.replace(b"VAAC: LONDON", b"VAAC: MADE UP").replace(
                    b"VAAC: DARWIN", b"VAAC: ALSO MADE UP"
                ),
            )
        )),
        now=datetime(2026, 8, 16, 6, 22, tzinfo=timezone.utc),
        api_key="synthetic-secret-key",
    )

    assert empty["status"] == "unavailable"
    assert malformed["status"] == "unavailable"


def test_one_global_snapshot_splits_into_honest_per_centre_receipts() -> None:
    global_snapshot = fetch_wifs_global_vaac_snapshot(
        _flight(),
        client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=COLLECTIVE)
        )),
        now=datetime(2026, 8, 16, 6, 22, tzinfo=timezone.utc),
        api_key="synthetic-secret-key",
    )

    darwin = wifs_centre_snapshot(global_snapshot, "DARWIN")
    montreal = wifs_centre_snapshot(global_snapshot, "MONTREAL")
    assert darwin["status"] == "available"
    assert darwin["advisory_count"] == 1
    assert montreal["status"] == "available"
    assert montreal["advisory_count"] == 0


def test_wifs_global_mount_expands_to_all_nine_centres(monkeypatch) -> None:
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "jma-tokyo,anchorage,wifs-global")

    mounted = mounted_vaac_centres()

    assert len(mounted) == 9
    assert mounted[0]["centre"] == "TOKYO"
    assert mounted[0]["fallback_token"] == "wifs-global:tokyo"
    assert mounted[1]["centre"] == "ANCHORAGE"
    assert mounted[1]["fallback_token"] == "wifs-global:anchorage"
    assert mounted[-1]["centre"] == "WELLINGTON"
    assert all(entry["token"].startswith("wifs-global:") for entry in mounted[2:])


def test_wifs_is_a_single_fetch_fallback_when_a_direct_centre_is_down(monkeypatch) -> None:
    from app.odss import direct_vaac, direct_vaac_anchorage, direct_vaac_wifs

    wifs_calls = 0
    global_snapshot = {
        "status": "available",
        "provider": "noaa-wifs-global-vaa",
        "coverage_status": "global_nine_vaac_tac_advisories",
        "advisories": [{"centre": "TOKYO", "advisory_number": "2026/1"}],
    }

    def wifs(_flight):
        nonlocal wifs_calls
        wifs_calls += 1
        return global_snapshot

    monkeypatch.setattr(direct_vaac, "live_tokyo_vaac_snapshot", lambda _flight: {
        "status": "unavailable", "provider": "jma-tokyo-vaac", "advisories": []
    })
    monkeypatch.setattr(direct_vaac_anchorage, "live_anchorage_vaac_snapshot", lambda _flight: {
        "status": "available", "provider": "nws-anchorage-vaac", "advisories": []
    })
    monkeypatch.setattr(direct_vaac_wifs, "live_wifs_global_vaac_snapshot", wifs)
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "jma-tokyo,anchorage,wifs-global")

    snapshots = fetch_mounted_vaac_snapshots(_flight(), mounted_vaac_centres())

    assert len(snapshots) == 9
    assert snapshots[0]["provider"] == "noaa-wifs-global-vaa"
    assert snapshots[1]["provider"] == "nws-anchorage-vaac"
    assert wifs_calls == 1
