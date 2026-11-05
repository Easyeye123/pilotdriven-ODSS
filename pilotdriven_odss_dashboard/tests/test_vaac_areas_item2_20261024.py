"""ITEM2-VOLCANIC: is every route point assigned to the VAAC ICAO Doc 9766 makes responsible?

The 21 Aug transcription left every Pacific crossing with route points in the Kuril/Kamchatka band (N43-N60,
E150-E165) and the NE Pacific (N43-N60, W150-W128) unassigned (volcanic_check.py's own docstring, release 436). Cause:
the table was incomplete, not wrong-bounded - the Tokyo, Anchorage and Washington rows are bounded by the Oakland
Oceanic, Anchorage Oceanic and Anchorage Continental FIR boundaries, which were never encoded. They now come from the
FAA's published boundary points (app/odss/vaac_fir_boundaries.json). Where the readings of the source differ, every
centre a reading names is responsible; a point no row assigns stays unsettled.

Synthetic points and routes are LABELLED SYNTHETIC; the genuine corpus is read offline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.odss.vaac_areas import (
    VAAC_AREA_SOURCE,
    centres_for_point,
    responsible_vaac_centres,
    waypoint_firs,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"


@pytest.mark.parametrize("point,expected", [
    # Kuril/Kamchatka band, west of Anchorage Oceanic's edge (N4542 E16255 - N5004 E15900): Tokyo's, "to Oakland
    # Oceanic and Anchorage Oceanic and Continental FIR boundaries".
    ((44.17, 155.10), {"TOKYO"}),     # genuine SQ34/SQ38 AGEDI
    ((47.00, 160.00), {"TOKYO"}),
    ((52.00, 158.00), {"TOKYO"}),     # Petropavlovsk-Kamchatsky
    # Inside Anchorage Oceanic: Anchorage's.
    ((49.00, 164.62), {"ANCHORAGE"}),  # genuine SQ34 EXIT1
    ((50.50, 179.00), {"ANCHORAGE"}),
    # Oakland Oceanic north of the N4300 E16500 - N4812 W15000 - N4812 W12800 line: Anchorage's.
    ((52.00, -160.00), {"ANCHORAGE"}),
    # Oakland Oceanic south of the line: Washington's.
    ((40.00, -150.00), {"WASHINGTON"}),
    ((45.51, -132.66), {"WASHINGTON"}),  # genuine SQ38 EXIT3
    ((15.00, 145.00), {"WASHINGTON"}),   # the Marianas: Oakland Oceanic, not Tokyo
    # Offshore US continental FIRs east of Oakland Oceanic's edge (ZSE / ZOA).
    ((38.00, -125.50), {"WASHINGTON"}),  # genuine SQ34 PAINT
    # Alaska and north of N60 west of the Anchorage FIRs to E150.
    ((58.00, -155.00), {"ANCHORAGE"}),
    ((62.00, 175.00), {"ANCHORAGE"}),
])
def test_the_formerly_unassigned_pacific_bands_resolve_by_the_handbook(point, expected):
    assert centres_for_point(*point) == expected


@pytest.mark.parametrize("point,expected", [
    # The handbook's split line printed at N4812 (Anchorage row) and N4820 (Washington row), drawn straight or as a great
    # circle: a point the readings place differently is held by both centres, so both must be reached.
    ((48.25, -140.00), {"ANCHORAGE", "WASHINGTON"}),
    ((44.00, 170.00), {"ANCHORAGE", "WASHINGTON"}),
    # Within one arc-minute of the Anchorage Oceanic edge (genuine SQ34 -PAZA boundary point): both sides.
    ((47.55, 161.33), {"ANCHORAGE", "TOKYO"}),
])
def test_points_the_source_leaves_open_are_held_by_every_centre_it_could_mean(point, expected):
    assert centres_for_point(*point) == expected


def test_canada_north_of_60_is_no_longer_anchorage_and_resolves_only_by_its_named_fir():
    # The 21 Aug table ran Anchorage north of N60 east to W128 - Edmonton FIR, a Canadian Continental FIR (Montreal).
    assert centres_for_point(63.0, -130.0) == set()
    result = responsible_vaac_centres([(63.0, -130.0)], point_firs=["CZEG"])
    assert result["centres"] == ["MONTREAL"] and result["unresolved_points"] == 0
    unnamed = responsible_vaac_centres([(63.0, -130.0)])
    assert unnamed["unresolved_points"] == 1 and unnamed["review_required"] is True


def test_the_ofp_boundary_sequence_places_each_point_in_the_fir_it_entered():
    waypoints = [{"fir_boundary": None}, {"fir_boundary": "PAZA"}, {"fir_boundary": None},
                 {"fir_boundary": "CZEG"}, {"fir_boundary": None}]
    assert waypoint_firs(waypoints) == [None, "PAZA", "PAZA", "CZEG", "CZEG"]


def test_a_synthetic_north_pacific_crossing_is_fully_settled():
    # LABELLED SYNTHETIC: SIN - Kurils - Anchorage Oceanic - Oakland Oceanic - US west coast.
    route = [(1.3, 103.9), (14.5, 121.0), (35.0, 140.0), (44.2, 155.1), (49.0, 164.6), (50.0, 175.0),
             (49.0, -160.0), (45.0, -140.0), (40.0, -130.0), (37.6, -122.4)]
    result = responsible_vaac_centres(route)
    assert result["unresolved_points"] == 0, result
    assert set(result["centres"]) == {"ANCHORAGE", "DARWIN", "TOKYO", "WASHINGTON"}


def test_a_synthetic_polar_route_through_canada_is_settled_by_its_named_firs():
    # LABELLED SYNTHETIC: Kamchatka - Bering - Alaska - Yukon - prairies, with the OFP's FIR boundary points.
    waypoints = [
        {"latitude": 55.0, "longitude": 160.0, "fir_boundary": None},
        {"latitude": 60.5, "longitude": 175.0, "fir_boundary": "PAZA"},
        {"latitude": 63.0, "longitude": -150.0, "fir_boundary": None},
        {"latitude": 63.0, "longitude": -140.5, "fir_boundary": "CZEG"},
        {"latitude": 62.0, "longitude": -120.0, "fir_boundary": None},
        {"latitude": 55.5, "longitude": -100.0, "fir_boundary": "CZWG"},
    ]
    result = responsible_vaac_centres(
        [(w["latitude"], w["longitude"]) for w in waypoints],
        [w["fir_boundary"] for w in waypoints if w["fir_boundary"]],
        waypoint_firs(waypoints),
    )
    assert result["unresolved_points"] == 0, result
    assert set(result["centres"]) == {"ANCHORAGE", "MONTREAL", "TOKYO"}


def test_the_boundaries_cite_their_sources():
    assert "Doc9766" in VAAC_AREA_SOURCE["url"] and VAAC_AREA_SOURCE["url"].startswith("https://www.icao.int/")
    data = json.loads((ROOT / "app/odss/vaac_fir_boundaries.json").read_text())
    assert data["source"]["url"].startswith("https://nfdc.faa.gov/")
    assert set(data["firs"]) == {"OAKLAND_OCEANIC", "ANCHORAGE_OCEANIC", "ANCHORAGE_CONTINENTAL", "ANCHORAGE_ARCTIC"}
    # The FAA's own point counts for each boundary (ARB_SEG, cycle 2026-10-01).
    assert [len(data["firs"][name]["points"]) for name in
            ("OAKLAND_OCEANIC", "ANCHORAGE_OCEANIC", "ANCHORAGE_CONTINENTAL", "ANCHORAGE_ARCTIC")] == [37, 7, 133, 10]


PACIFIC_CORPUS = [
    "lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf",
    "SQ38-29AUG2026-OFP-for-prod-proof.pdf",
    "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf",
    "SQ02422072026SIN.pdf",
    "SQ02325072026JFK.pdf",
    "lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf",
]


@pytest.mark.parametrize("name", PACIFIC_CORPUS)
def test_genuine_routes_that_held_unassigned_points_are_settled(name):
    from app.odss.parser import extract_pages, parse_lido

    source = CORPUS / name
    if not source.is_file():
        pytest.skip(f"private corpus file {name} is not on this machine")
    flight = parse_lido(extract_pages(source), name)
    waypoints = flight["route_waypoints"]
    placed = [(w, fir) for w, fir in zip(waypoints, waypoint_firs(waypoints))
              if isinstance(w.get("latitude"), (int, float)) and isinstance(w.get("longitude"), (int, float))]
    result = responsible_vaac_centres(
        [(w["latitude"], w["longitude"]) for w, _ in placed],
        [w["fir_boundary"] for w in waypoints if w.get("fir_boundary")],
        [fir for _, fir in placed],
    )
    assert result["unresolved_points"] == 0, result
