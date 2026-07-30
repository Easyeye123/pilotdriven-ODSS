"""Corridor (single-endpoint) depressurisation profile matching.

These tests encode the approved PilotDriven v1.3 depressurisation answer key
for SQ352 WSSS-EKCH and the SQ23 KJFK-WSSS regression:

- A chart whose from/to endpoints are BOTH filed waypoints matches exactly as
  before (class 1).
- A chart with exactly ONE endpoint on the filed route matches a subsegment
  (class 2) only when the filed airway legs, walked outward from that
  endpoint, follow the chart's published airway sequence contiguously from
  the same endpoint. This is the published rejection rule for chart 8-7 on
  SQ352: its leg adjacent to TEMEL is N199, not the filed UM11/M11 legs, so
  it must not be promoted, while chart 8-5 (TEMEL - UM11 - M11 - MATAL) is a
  full subsegment match.
- Strict MSA >100*: an exact 100* waypoint is a boundary that terminates an
  active exposure and never starts one.
- Windows with no class 1/2 candidate stay fail-closed (no nearby or generic
  chart substituted).

Profile rows mirror the controlled LOEP format already used by
``test_depress_profile_index_builder``; no controlled chart content is
reproduced here.
"""

from __future__ import annotations

import pytest

from app.odss import engines
from app.odss.engines import detect_terrain_events, match_profiles


def _wp(
    name: str,
    actm: int,
    msa: int | None,
    airway: str | None,
    *,
    star: bool = False,
    fir: str | None = None,
) -> dict:
    return {
        "name": name,
        "actm_minutes": actm,
        "fir_boundary": fir,
        "latitude": None,
        "longitude": None,
        "msa_hundreds_ft": msa,
        "msa_asterisk": star,
        "vws": None,
        "airway_in": airway,
    }


PROFILE_8_5 = {
    "chart": "8-5",
    "chart_page": 235,
    "from": "TEMEL",
    "from_aliases": ["TEMEL"],
    "to": "LEKBA",
    "to_aliases": ["LEKBA"],
    "critical": "MATAL",
    "critical_aliases": ["MATAL"],
    "airways": ["UM11", "M11", "T916", "N161"],
    "effective_date": "12 JUN 2026",
    "effectivity": ["LH", "ULR"],
}

PROFILE_8_7 = {
    "chart": "8-7",
    "chart_page": 237,
    "from": "TEMEL",
    "from_aliases": ["TEMEL"],
    "to": "RASAM",
    "to_aliases": ["RASAM"],
    "critical": "REBLO",
    "critical_aliases": ["REBLO"],
    "airways": ["N199", "M11", "UM11/UR317", "UW71"],
    "effective_date": "24 NOV 2022",
    "effectivity": ["LH", "ULR"],
}


def _sq352_flight() -> dict:
    """Synthetic westbound Caucasus segment mirroring the filed SQ352 legs."""
    waypoints = [
        _wp("AMOKU", 465, 21, "M11"),
        _wp("ABROD", 470, 69, "M11"),
        _wp("ERLEV", 476, 86, "M11"),
        _wp("ALUVO", 471 + 12, 130, "M11", star=True),
        _wp("LUSAL", 489, 100, "M11", star=True),
        _wp("EDATA", 492, 96, "M11"),
        _wp(None, 493, None, None, fir="UDDD"),
        _wp("MATAL", 487 + 13, 136, "M11", star=True),
        _wp("TABAS", 497 + 12, 159, "M11", star=True),
        _wp(None, 510, None, None, fir="LTAA"),
        _wp("REBLO", 511, 129, "M11", star=True),
        _wp("DELEL", 514, 154, "UM11", star=True),
        _wp("EKTES", 516, 154, "UM11", star=True),
        _wp("TBN", 520, 119, "UM11", star=True),
        _wp("TEMEL", 523, 117, "UM11", star=True),
        _wp("ARLAT", 529, 95, "UM11"),
        _wp("IPSAT", 533, 76, "UM11"),
    ]
    return {
        "registration": "9V-SMQ",
        "aircraft_type": "A350-941",
        "route_waypoints": waypoints,
    }


def _match_charts(flight: dict, profiles: list[dict]) -> list[dict]:
    events = detect_terrain_events(flight["route_waypoints"])
    original = engines.DEPRESS_PROFILES
    engines.DEPRESS_PROFILES = profiles
    try:
        return match_profiles(flight, events)
    finally:
        engines.DEPRESS_PROFILES = original


def test_exact_100_star_is_a_boundary_not_an_exposure() -> None:
    """v1.3 segmentation: exact 100* terminates the ALUVO event (drop LUSAL)."""
    events = detect_terrain_events(_sq352_flight()["route_waypoints"])
    names = [
        (event["first_high"]["name"], event["last_high"]["name"], (event.get("drop") or {}).get("name"))
        for event in events
    ]
    assert ("ALUVO", "ALUVO", "LUSAL") in names, names
    # LUSAL at exactly 100* must never begin or extend an exposure.
    assert all(event["first_high"]["name"] != "LUSAL" for event in events)


def test_fir_boundary_rows_do_not_terminate_an_event() -> None:
    events = detect_terrain_events(_sq352_flight()["route_waypoints"])
    matal = next(event for event in events if event["first_high"]["name"] == "MATAL")
    assert matal["last_high"]["name"] == "TEMEL"
    assert (matal.get("drop") or {}).get("name") == "ARLAT"
    assert matal["maximum"]["name"] == "TABAS"


def test_single_endpoint_corridor_promotes_8_5_and_rejects_8_7() -> None:
    """SQ352 TERR-03: 8-5 is a full MATAL-TEMEL subsegment match; 8-7's leg
    adjacent to TEMEL is N199, not the filed UM11 leg, so it is rejected."""
    matches = _match_charts(_sq352_flight(), [PROFILE_8_7, PROFILE_8_5])
    matal_matches = [
        match
        for match in matches
        if match["event"]["first_high"]["name"] == "MATAL"
    ]
    assert [match["profile"]["chart"] for match in matal_matches] == ["8-5"]
    match = matal_matches[0]
    assert match["route_start"] == "MATAL"
    assert match["route_end"] == "TEMEL"
    assert match["coverage_complete"] is True
    assert match["match_class"] == "corridor-subsegment"


def test_corridor_match_respects_aircraft_effectivity() -> None:
    flight = _sq352_flight()
    flight["registration"] = "9V-SHA"  # MH: not in LH/ULR effectivity
    matches = _match_charts(flight, [PROFILE_8_5])
    assert [
        match
        for match in matches
        if match["event"]["first_high"]["name"] == "MATAL"
    ] == []


def test_both_endpoint_match_still_wins_over_corridor_candidates() -> None:
    """SQ23 regression: eastbound route filing TEMEL..RASAM keeps chart 8-7
    (class 1) for the window even though 8-5 offers a corridor candidate."""
    waypoints = [
        _wp("SOKRU", 460, 96, "UM11"),
        _wp("TEMEL", 465, 117, "UM11", star=True),
        _wp("TBN", 469, 119, "N199", star=True),
        _wp("DELEL", 473, 154, "M11", star=True),
        _wp("REBLO", 476, 154, "UM11", star=True),
        _wp("LUSAL", 480, 96, "UW71"),
        _wp("MATAL", 484, 159, "UW71", star=True),
        _wp("RASAM", 488, 114, "UW71", star=True),
        _wp("GIVMO", 492, 81, "N199"),
    ]
    flight = {
        "registration": "9V-SGE",
        "aircraft_type": "A350-941",
        "route_waypoints": waypoints,
    }
    matches = _match_charts(flight, [PROFILE_8_5, PROFILE_8_7])
    first_window = [
        match
        for match in matches
        if match["event"]["first_high"]["name"] == "TEMEL"
    ]
    assert [match["profile"]["chart"] for match in first_window] == ["8-7"]
    assert first_window[0]["match_class"] == "published-route"


def test_dct_window_with_no_corridor_stays_unmatched() -> None:
    """SQ352 TERR-04: DCT Central Europe sector has no endpoint/airway match;
    nothing may be substituted."""
    waypoints = [
        _wp("TEMEL", 400, 40, "UM11"),
        _wp("LUGEB", 465, 35, "DCT"),
        _wp("NARKA", 471, 111, "DCT", star=True),
        _wp(None, 474, None, None, fir="LHCC"),
        _wp("KELEL", 480, 112, "DCT", star=True),
        _wp("BAREX", 483, 112, "DCT", star=True),
        _wp("AGODU", 489, 63, "DCT"),
    ]
    flight = {
        "registration": "9V-SMQ",
        "aircraft_type": "A350-941",
        "route_waypoints": waypoints,
    }
    matches = _match_charts(flight, [PROFILE_8_5, PROFILE_8_7])
    assert [
        match
        for match in matches
        if match["event"]["first_high"]["name"] == "NARKA"
    ] == []


def test_corridor_anchor_must_touch_the_exposure_window() -> None:
    """An on-route chart endpoint far from the window must not create a
    corridor candidate for it (no geographic teleporting along airway names)."""
    waypoints = [
        _wp("TEMEL", 100, 40, "UM11"),
        _wp("GAP1", 140, 20, "W702"),
        _wp("GAP2", 180, 20, "W702"),
        _wp("FARHI", 220, 130, "M11", star=True),
        _wp("FARLO", 226, 90, "M11"),
    ]
    flight = {
        "registration": "9V-SMQ",
        "aircraft_type": "A350-941",
        "route_waypoints": waypoints,
    }
    matches = _match_charts(flight, [PROFILE_8_5])
    assert [
        match
        for match in matches
        if match["event"]["first_high"]["name"] == "FARHI"
    ] == []
