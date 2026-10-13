"""The shared route-endpoint resolver behind every route map (item 11, 13 Oct 2026).

``app.odss.route_anchors`` decides which drawn route row may carry the departure or destination aerodrome. See
tests/test_route_map_anchors_20261013.py for the corpus-wide placement invariant it serves.
"""
from __future__ import annotations

import pytest

from app.odss.route_anchors import departure_allowance_nm, resolve_route_endpoints, unplaced_endpoint_statements
from tests.test_route_map_anchors_20261013 import ARP, _corpus_files, _nm, _parsed


def _toy_flight(**overrides) -> dict:
    rows = [
        {"name": "IBIXU", "latitude": 1.27333, "longitude": 103.96167},
        {"name": "ANITO", "latitude": -0.28333, "longitude": 104.86667},
        {"name": "YPPH", "latitude": -31.94, "longitude": 115.96667},
    ]
    flight = {"departure": "WSSS", "destination": "YPPH", "ground_distance_nm": 2125, "route_waypoints": rows}
    flight.update(overrides)
    return flight


def test_genuine_departure_bound_holds_and_is_within_the_allowance_on_all_30_originals() -> None:
    """distance(departure aerodrome, first drawn row) <= GND MILES - drawn length, measured on every original."""
    for path in _corpus_files():
        flight = _parsed(str(path))
        departure = resolve_route_endpoints(flight)["departure"]
        first = flight["route_waypoints"][0]
        true_offset = _nm(ARP[flight["departure"]], (first["latitude"], first["longitude"]))
        assert departure["status"] == "placed", path.name
        assert true_offset <= departure["offset_bound_nm"] + 0.5, (path.name, true_offset, departure)
        assert departure["offset_bound_nm"] <= 0.7 * departure_allowance_nm(flight["ground_distance_nm"]), path.name


def test_resolver_places_both_ends_of_a_complete_route() -> None:
    endpoints = resolve_route_endpoints(_toy_flight())
    assert endpoints["departure"]["status"] == endpoints["destination"]["status"] == "placed"
    assert endpoints["departure"]["point_index"] == 0
    assert endpoints["destination"]["point_index"] == 2
    assert unplaced_endpoint_statements(endpoints) == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"ground_distance_nm": None}, "ground distance (GND MILES) is not held"),
        ({"ground_distance_nm": 3200}, "NM shorter than the OFP ground distance"),
        ({"ground_distance_nm": 1200}, "NM longer than the OFP ground distance"),
        ({"departure": ""}, "departure is not held"),
    ],
)
def test_resolver_reports_a_departure_it_cannot_place(overrides, reason) -> None:
    endpoints = resolve_route_endpoints(_toy_flight(**overrides))
    assert endpoints["departure"]["status"] == "not_placed"
    assert endpoints["departure"]["point_index"] is None
    assert reason in endpoints["departure"]["reason"]
    assert endpoints["destination"]["status"] == "placed"


def test_resolver_never_moves_an_aerodrome_onto_a_neighbouring_row() -> None:
    flight = _toy_flight()
    flight["route_waypoints"][0].update(latitude=None, longitude=None)
    endpoints = resolve_route_endpoints(flight)
    assert endpoints["departure"]["status"] == "not_placed"
    assert "IBIXU) holds no printed position" in endpoints["departure"]["reason"]

    flight = _toy_flight()
    flight["route_waypoints"][-1].update(latitude=None, longitude=None)
    endpoints = resolve_route_endpoints(flight)
    assert endpoints["destination"]["status"] == "not_placed"
    assert endpoints["departure"]["status"] == "not_placed", "length cannot be checked without the destination row"
    statements = unplaced_endpoint_statements(endpoints)
    assert statements[0].startswith("Departure aerodrome WSSS not drawn:")
    assert statements[1].startswith("Destination aerodrome YPPH not drawn: the printed YPPH row holds no position.")
    assert statements[1].endswith("The route is drawn to ANITO.")


def test_resolver_places_a_departure_printed_as_its_own_first_row() -> None:
    flight = _toy_flight(ground_distance_nm=None)
    flight["route_waypoints"].insert(0, {"name": "WSSS", "latitude": 1.35917, "longitude": 103.98944})
    endpoints = resolve_route_endpoints(flight)
    assert endpoints["departure"]["status"] == "placed"
    assert endpoints["departure"]["offset_bound_nm"] == 0.0
