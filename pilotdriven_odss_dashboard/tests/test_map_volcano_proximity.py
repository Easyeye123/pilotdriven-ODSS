from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def _flight() -> dict:
    return {
        "flight_number": "SQ38",
        "departure": "WSSS",
        "destination": "KLAX",
        "route_waypoints": [
            {"name": "WSSS", "latitude": 1.36, "longitude": 103.99, "actm_minutes": 0},
            {"name": "KLAX", "latitude": 33.94, "longitude": -118.41, "actm_minutes": 900},
        ],
    }


def test_advisory_volcanoes_near_the_corridor_draw_ring_and_marker() -> None:
    flight = _flight()
    flight["va_sigmet_review"] = {
        "status": "not_applicable",
        "hazard_features": [],
        "monitoring_features": [],
        "volcano_proximity": {
            "corridor_nm": 200.0,
            "entries": [
                {
                    "volcano": "GREAT SITKIN 311120",
                    "centre": "ANCHORAGE",
                    "aviation_colour_code": "ORANGE",
                    "position": {"latitude": 52.08, "longitude": -176.13},
                    "distance_nm": 31.5,
                    "within_corridor": True,
                },
                {
                    # Far outside the display bound: stays in the review list,
                    # never buries the route map.
                    "volcano": "ETNA 211060",
                    "centre": "TOULOUSE",
                    "aviation_colour_code": None,
                    "position": {"latitude": 37.75, "longitude": 14.99},
                    "distance_nm": 5000.0,
                    "within_corridor": False,
                },
            ],
        },
    }

    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    features = contract.hazards_geojson["features"]
    rings = [f for f in features if f["properties"].get("volcano_ring")]
    markers = [f for f in features if f["properties"].get("volcano_marker")]

    assert len(rings) == 1
    assert len(markers) == 1
    ring = rings[0]
    assert ring["geometry"]["type"] == "Polygon"
    assert len(ring["geometry"]["coordinates"][0]) == 37
    assert ring["properties"]["volcano"].startswith("GREAT SITKIN")
    assert ring["properties"]["not_for_navigation"] is True
    marker = markers[0]
    assert marker["geometry"] == {
        "type": "Point",
        "coordinates": [-176.13, 52.08],
    }
    assert marker["properties"]["aviation_colour_code"] == "ORANGE"


def test_no_held_advisories_draw_no_rings() -> None:
    flight = _flight()
    flight["va_sigmet_review"] = {"status": "review_required"}
    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    assert not [
        feature
        for feature in contract.hazards_geojson["features"]
        if feature["properties"].get("volcano_ring")
        or feature["properties"].get("volcano_marker")
    ]
