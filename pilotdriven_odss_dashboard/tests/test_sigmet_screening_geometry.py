"""Spatial intersection and flight timing are independent screening evidence."""
from copy import deepcopy

import pytest
from shapely.geometry import LineString, Polygon

from app.odss.briefing import _screening_geometry, _sigmet_screening_cards
from app.odss.weather_publication import sigmet_lines


SQUARE = [(-1, -1), (-1, 1), (1, 1), (1, -1)]  # lat, lon


def fix(lat, lon, actm, name="FIX"):
    return dict(latitude=lat, longitude=lon, actm_minutes=actm, name=name)


def flight_for(route, validity="111000/111100", departure="2026-07-11T10:30:00Z"):
    return {
        "scheduled_departure_utc": departure,
        "route_waypoints": route,
        "weather": [{"record_type": "SIGMET", "location": "WSJC", "text":
            f"WS SIGMET 1 VALID {validity} WSSS- WSJC SINGAPORE FIR EMBD TS OBS "
            "WI S0100 W00100 - S0100 E00100 - N0100 E00100 - N0100 W00100 TOP FL450 NC="}],
    }


@pytest.mark.parametrize("route", [
    [fix(0, -2, 0, "A"), fix(0, 2, 20, "B")],  # both fixes outside
    [fix(1, -2, 0), fix(1, 2, 20)],  # boundary overlap
    [fix(0, -2, 0), fix(2, 0, 20)],  # corner contact
    [fix(0, 0, 0), fix(0, 0, 20)],  # stationary inside
])
def test_crossing_or_boundary_contact_is_spatial_even_without_an_inside_fix(route):
    line = LineString([(w["longitude"], w["latitude"]) for w in route])
    polygon = Polygon([(lon, lat) for lat, lon in SQUARE])
    assert line.intersects(polygon)  # independent reference predicate
    result = _screening_geometry(SQUARE, route)
    assert result["route_intersects"] is True
    assert result["closest_nm"] == 0
    assert result["crossing_actm"] == (0, 20)  # filed leg bounds, not exact entry


@pytest.mark.parametrize("times", [(None, None), (0, None), (20, 0), (0, float("nan"))])
def test_missing_or_invalid_timing_never_becomes_outside_route(times):
    route = [fix(0, -2, times[0]), fix(0, 0, times[1])]
    result = _screening_geometry(SQUARE, route)
    assert result["route_intersects"] is True
    assert result["crossing_actm"] is None
    flight = flight_for(route)
    card = _sigmet_screening_cards(flight)[0]
    assert card["disposition"] == "REVIEW REQUIRED"
    assert "does not intersect" not in card["screening"]
    text = " ".join(sigmet_lines(flight, {"hazards": {"sigmet_cards": [card]}}))
    assert "Outside filed route" not in text
    assert "timing" in text.lower() and "unresolved" in text.lower()
    assert "review required" not in text.lower()


def test_all_intersecting_legs_must_have_timing_not_only_one_inside_fix():
    route = [fix(0, -2, None), fix(0, 0, 10), fix(0, 2, 20)]
    result = _screening_geometry(SQUARE, route)
    assert result["route_intersects"] is True and result["crossing_actm"] is None


def test_spatial_no_intersection_does_not_require_actm():
    result = _screening_geometry(SQUARE, [fix(3, -2, None), fix(3, 2, None)])
    assert result["route_intersects"] is False
    assert result["crossing_actm"] is None
    assert result["closest_nm"] > 0


@pytest.mark.parametrize("points,route", [
    ([(0, 0), (0, 1), (0, 2)], [fix(3, -2, 0), fix(3, 2, 20)]),
    ([(-1, -1), (1, 1), (-1, 1), (1, -1)], [fix(3, -2, 0), fix(3, 2, 20)]),
    (SQUARE, [fix(3, -2, 0), fix(None, None, 10), fix(3, 2, 20)]),
    (SQUARE, [fix(3, float("nan"), 0), fix(3, 2, 20)]),
    (SQUARE, [fix(91, 0, 0), fix(3, 2, 20)]),
    (SQUARE, [fix(3, 2, 20)]),
])
def test_invalid_or_incomplete_geometry_is_unresolved(points, route):
    assert _screening_geometry(points, route) is None


def test_antimeridian_crossing_and_far_side_are_distinct():
    points = [(-1, 179), (-1, -179), (1, -179), (1, 179)]
    crossing = _screening_geometry(points, [fix(0, 178, 0), fix(0, -178, 20)])
    outside = _screening_geometry(points, [fix(0, -2, 0), fix(0, 2, 20)])
    assert crossing["route_intersects"] is True
    assert outside["route_intersects"] is False


@pytest.mark.parametrize("validity,disposition,phrase", [
    ("111000/111100", "PROMOTED", "inside the product's validity"),
    ("111040/111045", "REVIEW REQUIRED", "overlaps the product's validity"),
    ("111000/111020", "NOT PROMOTED", "before the earliest possible"),
    ("111100/111200", "NOT PROMOTED", "after the latest possible"),
    ("111040/111030", "REVIEW REQUIRED", "validity"),
])
def test_validity_is_compared_to_conservative_filed_leg_bounds(validity, disposition, phrase):
    flight = flight_for([fix(0, -2, 0), fix(0, 2, 20)], validity)
    original = deepcopy(flight)
    card = _sigmet_screening_cards(flight)[0]
    assert card["disposition"] == disposition
    assert phrase in card["screening"]
    assert "filed leg bounds" in card["screening"]
    assert flight == original


def test_missing_utc_anchor_does_not_claim_within_validity():
    card = _sigmet_screening_cards(flight_for([fix(0, -2, 0), fix(0, 2, 20)], departure=None))[0]
    assert card["disposition"] == "REVIEW REQUIRED"
    assert "inside the product's validity" not in card["screening"]


def test_new_pdf_rechecks_legacy_false_outside_card_against_its_exact_source():
    flight = flight_for([fix(0, -2, 0), fix(0, 2, 20)])
    legacy = {
        "fir": "WSJC", "sigmet_id": "1", "phenomenon": "EMBD TS",
        "text": flight["weather"][0]["text"], "valid_from": "111000", "valid_to": "111100",
        "disposition": "NOT PROMOTED",
        "screening": "The filed route does not intersect the polygon. Closest deterministic screening distance is approximately 60 NM north. NOT PROMOTED.",
    }
    original = deepcopy(legacy)
    lines = " ".join(sigmet_lines(flight, {"hazards": {"sigmet_cards": [legacy]}}))
    assert "Outside filed route" not in lines
    assert "Crossing leg bounds" in lines and "1030-1050Z" in lines
    assert legacy == original


@pytest.mark.parametrize("changed_source", [False, True])
def test_legacy_verdict_without_identical_source_is_unverified(changed_source):
    flight = flight_for([fix(0, -2, 0), fix(0, 2, 20)])
    card = {"fir": "WSJC", "sigmet_id": "1", "text": flight["weather"][0]["text"],
            "screening": "The filed route does not intersect the polygon. NOT PROMOTED."}
    if changed_source:
        card["text"] = card["text"].replace("EMBD TS", "SEV TURB")
    else:
        flight["weather"] = []
    lines = " ".join(sigmet_lines(flight, {"hazards": {"sigmet_cards": [card]}}))
    assert "Outside filed route" not in lines and "unresolved" in lines
