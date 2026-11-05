"""The shared aerodrome resolver and its governed table (item 11; Codex QA496-03, 13 Oct 2026).

``app.odss.route_anchors`` decides where every route map draws the departure and destination aerodromes: only at the
reference point the governed table (``app/odss/aerodrome_reference_points.json``) holds for the ICAO code, never at a
route row. See tests/test_route_map_anchors_20261013.py for the corpus-wide placement invariant it serves.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.odss import route_anchors
from app.odss.route_anchors import (
    aerodrome_reference_points,
    drawn_aerodromes,
    resolve_route_endpoints,
    unplaced_endpoint_statements,
)
from tests.test_route_map_anchors_20261013 import (
    CORPUS,
    OFFICIAL,
    OSM_CENTRES,
    OSM_OUTLINES,
    _corpus_files,
    _nm,
    _osm_overlay,
    _parsed,
    _printed_records,
)

ROOT = Path(__file__).resolve().parents[1]


def _toy_flight(**overrides) -> dict:
    rows = [
        {"name": "IBIXU", "latitude": 1.27333, "longitude": 103.96167},
        {"name": "ANITO", "latitude": -0.28333, "longitude": 104.86667},
        {"name": "YPPH", "latitude": -31.94, "longitude": 115.96667},
    ]
    flight = {"departure": "WSSS", "destination": "YPPH", "ground_distance_nm": 2125, "route_waypoints": rows}
    flight.update(overrides)
    return flight


def test_every_governed_reference_point_agrees_with_its_independent_sources() -> None:
    """Product table (LIDO aerodrome records) against sources independent of it: the record each OFP prints, re-read
    from the PDF text (0.05 NM); the official CAAS/FAA point for WSSS and KJFK (0.1 NM); PD's published OpenStreetMap
    aerodrome where held (1.5 NM; measured at most 1.11 NM)."""
    table = aerodrome_reference_points()
    assert set(table) == set(_printed_records())
    for code, entry in table.items():
        position = (entry["latitude"], entry["longitude"])
        assert _nm(_printed_records()[code], position) <= 0.05, code
        if code in OFFICIAL:
            assert _nm(OFFICIAL[code], position) <= 0.1, code
        if code in OSM_CENTRES:
            assert _nm(OSM_CENTRES[code], position) <= 1.5, code
        for source in entry["sources"]:
            assert source["kind"] == "lido_ofp_destination_aerodrome_record"
            assert source["printed"].startswith(code + " ")
            assert len(source["sha256"]) == 64 and source["page"] >= 1


def test_governed_table_is_exactly_what_the_held_corpus_records() -> None:
    """Reproducible: the committed table is rebuilt from the held OFPs, byte for byte, and every pinned source hash
    is the hash of a held file."""
    _corpus_files()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_aerodrome_reference_points.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    import hashlib

    hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in CORPUS.glob("*.pdf")}
    assert all(source["sha256"] in hashes for entry in aerodrome_reference_points().values() for source in entry["sources"])


def test_resolver_draws_both_aerodromes_at_their_reference_points_and_never_names_a_row() -> None:
    endpoints = resolve_route_endpoints(_toy_flight())
    for role, code in (("departure", "WSSS"), ("destination", "YPPH")):
        end = endpoints[role]
        assert end["status"] == "reference_point"
        assert (end["latitude"], end["longitude"]) == (aerodrome_reference_points()[code]["latitude"], aerodrome_reference_points()[code]["longitude"])
        assert end["row_index"] is None and end["point_index"] is None
        assert end["reference"]["kind"] == "lido_ofp_destination_aerodrome_record"
    assert endpoints["departure"]["fix"] == "IBIXU"
    assert unplaced_endpoint_statements(endpoints) == []


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"name": "JUDDS", "latitude": 41.635, "longitude": -73.108333}, {"name": "ANITO", "latitude": -0.28, "longitude": 104.87}],
        [{"name": "IBIXU", "latitude": None, "longitude": None}, {"name": "ANITO", "latitude": -0.28, "longitude": 104.87}],
    ],
)
def test_route_rows_never_decide_where_an_aerodrome_is(rows) -> None:
    """Whatever the rows - none, a distant first fix, a first row without a position - the aerodromes are the same."""
    reference = resolve_route_endpoints(_toy_flight())
    endpoints = resolve_route_endpoints(_toy_flight(route_waypoints=rows, ground_distance_nm=None))
    for role in ("departure", "destination"):
        for key in ("status", "latitude", "longitude", "reference"):
            assert endpoints[role][key] == reference[role][key], (role, key)


def test_an_unheld_code_is_not_drawn_and_the_reason_is_stated() -> None:
    endpoints = resolve_route_endpoints(_toy_flight(destination="YBBN"))
    assert endpoints["destination"]["status"] == "not_placed"
    assert endpoints["destination"]["latitude"] is None
    assert unplaced_endpoint_statements(endpoints) == [
        "Destination aerodrome YBBN not drawn: no governed aerodrome reference point is held for YBBN, and no "
        "OpenStreetMap aerodrome matched on its ICAO tag was published for this analysis. The route is drawn to YPPH."
    ]
    endpoints = resolve_route_endpoints(_toy_flight(departure=""))
    assert endpoints["departure"]["reason"] == "the OFP departure is not held"


def test_a_return_to_the_departure_aerodrome_draws_one_marker_with_both_roles() -> None:
    endpoints = resolve_route_endpoints(_toy_flight(destination="WSSS"))
    drawn = drawn_aerodromes(endpoints)
    assert len(drawn) == 1 and drawn[0]["roles"] == ["departure", "destination"]


def test_an_incomplete_table_entry_is_refused(monkeypatch, tmp_path) -> None:
    broken = tmp_path / "table.json"
    broken.write_text(json.dumps({"aerodromes": {"WSSS": {"latitude": 1.36, "longitude": 103.99, "sources": []}}}))
    monkeypatch.setattr(route_anchors, "AERODROME_TABLE", broken)
    route_anchors.aerodrome_reference_points.cache_clear()
    try:
        with pytest.raises(ValueError, match="incomplete"):
            route_anchors.aerodrome_reference_points()
    finally:
        monkeypatch.undo()
        route_anchors.aerodrome_reference_points.cache_clear()


def test_genuine_corpus_resolves_both_aerodromes_without_reading_a_route_row() -> None:
    for path in _corpus_files():
        flight = deepcopy(_parsed(str(path)))
        reference = resolve_route_endpoints(flight)
        flight["route_waypoints"] = list(reversed(flight["route_waypoints"]))
        reversed_rows = resolve_route_endpoints(flight)
        for role in ("departure", "destination"):
            assert reference[role]["status"] == "reference_point", path.name
            assert (reference[role]["latitude"], reference[role]["longitude"]) == (
                reversed_rows[role]["latitude"], reversed_rows[role]["longitude"]
            ), path.name


def test_osm_source_is_the_centre_of_the_published_exact_icao_outline_with_provenance() -> None:
    """The second source: the bounding-box centre of the outline the app published for this analysis, matched on the
    exact ICAO code - the same point the app's own OpenStreetMap lookup reports as the aerodrome centre."""
    endpoints = resolve_route_endpoints(_toy_flight(destination="WMKK", surface_overlays=[_osm_overlay("WMKK", "destination")]))
    end = endpoints["destination"]
    assert end["status"] == "reference_point"
    osm = json.loads((ROOT / "tests" / "fixtures" / "osm_aerodromes_published_20261014.json").read_text())["centres"]["WMKK"]["osm"]
    assert _nm((osm["latitude"], osm["longitude"]), (end["latitude"], end["longitude"])) <= 0.001
    assert end["reference"] == {
        "kind": "osm_aerodrome_published_outline",
        "icao": "WMKK",
        "name": OSM_OUTLINES["WMKK"]["name"],
        "method": "bounding-box centre of the OpenStreetMap aerodrome outline the app published for this analysis, "
                  "matched on its exact ICAO tag",
        "provider": "openstreetmap",
        "fetchedAt": OSM_OUTLINES["WMKK"]["fetchedAt"],
        "sourceUpdatedAt": OSM_OUTLINES["WMKK"]["sourceUpdatedAt"],
        "attribution": "© OpenStreetMap contributors",
        "licenceUrl": "https://www.openstreetmap.org/copyright",
    }


@pytest.mark.parametrize(
    "overlay",
    [
        {"icao": "WMKP", "aerodromeBoundary": {"outer": [[[101.6, 2.7], [101.8, 2.7], [101.8, 2.8], [101.6, 2.7]]], "inner": []}},
        {"icao": "wmkk ", "aerodromeBoundary": None},
        {"icao": "WMKK", "aerodromeBoundary": {"outer": [], "inner": []}},
        {"icao": "WMKK", "aerodromeBoundary": {"outer": [[["x", 2.7]]], "inner": []}},
    ],
)
def test_osm_source_needs_the_exact_code_and_a_usable_outline(overlay) -> None:
    endpoints = resolve_route_endpoints(_toy_flight(destination="WMKK", surface_overlays=[overlay]))
    assert endpoints["destination"]["status"] == "not_placed"
    assert "no OpenStreetMap aerodrome matched on its ICAO tag" in endpoints["destination"]["reason"]


def test_osm_outline_centre_is_safe_across_the_antimeridian() -> None:
    ring = [[179.9, -16.6], [-179.9, -16.6], [-179.9, -16.5], [179.9, -16.5], [179.9, -16.6]]
    endpoints = resolve_route_endpoints(_toy_flight(
        destination="NFTV", surface_overlays=[{"icao": "NFTV", "aerodromeBoundary": {"outer": [ring], "inner": []}}],
    ))
    end = endpoints["destination"]
    assert end["status"] == "reference_point"
    assert end["latitude"] == pytest.approx(-16.55)
    assert abs(abs(end["longitude"]) - 180.0) < 1e-9
