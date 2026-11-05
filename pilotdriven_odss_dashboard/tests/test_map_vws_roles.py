from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def test_map_vws_role_uses_the_controlled_strictly_greater_than_004_boundary() -> None:
    flight = {
        "flight_number": "SQ481",
        "departure": "FAOR",
        "destination": "WSSS",
        "route_waypoints": [
            {
                "name": "FAOR",
                "latitude": -26.14,
                "longitude": 28.25,
                "actm_minutes": 0,
                "vws": 4,
            },
            {
                "name": "TAPIN",
                "latitude": -20.0,
                "longitude": 38.0,
                "actm_minutes": 40,
                "vws": 5,
            },
            {
                "name": "SOBAT",
                "latitude": -12.0,
                "longitude": 54.0,
                "actm_minutes": 100,
                "vws": 6,
            },
            {
                "name": "WSSS",
                "latitude": 1.36,
                "longitude": 103.99,
                "actm_minutes": 610,
                "vws": None,
            },
        ],
    }

    contract = build_map_contract(flight, [], MapSettings(provider="schematic"))
    markers = {
        feature["properties"]["name"]: feature["properties"]
        for feature in contract.markers_geojson["features"]
    }

    assert "vws_trigger" not in markers["FAOR"]["roles"]
    assert "vws_trigger" in markers["TAPIN"]["roles"]
    assert "vws_trigger" in markers["SOBAT"]["roles"]
    assert "vws_trigger" not in markers["WSSS"]["roles"]
    assert markers["TAPIN"]["role"] == "vws_trigger"
