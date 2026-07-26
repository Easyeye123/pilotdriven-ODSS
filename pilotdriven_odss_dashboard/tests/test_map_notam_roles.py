from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def test_applicable_airport_notam_marks_canonical_endpoint_without_new_coordinates() -> None:
    flight = {
        "flight_number": "SQ24",
        "departure": "WSSS",
        "destination": "KJFK",
        "route_waypoints": [
            {
                "name": "WSSS",
                "latitude": 1.36,
                "longitude": 103.99,
                "actm_minutes": 0,
            },
            {
                "name": "KJFK",
                "latitude": 40.64,
                "longitude": -73.78,
                "actm_minutes": 1065,
            },
        ],
    }
    findings = [
        {
            "engine": "notam",
            "title": "Destination NOTAM A1234/26",
            "data": {
                "location": "KJFK",
                "role": "destination",
                "applicability": "active",
            },
        }
    ]

    contract = build_map_contract(flight, findings, MapSettings(provider="schematic"))
    departure, destination = contract.markers_geojson["features"]

    assert departure["properties"]["role"] == "departure"
    assert "notam_airport" not in departure["properties"]["roles"]
    assert destination["properties"]["role"] == "destination"
    assert "notam_airport" in destination["properties"]["roles"]
    assert destination["geometry"]["coordinates"] == [-73.78, 40.64]
