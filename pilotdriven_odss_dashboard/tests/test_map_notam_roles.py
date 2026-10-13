from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract


def test_applicable_airport_notam_marks_the_destination_aerodrome_marker_only() -> None:
    """Item 11 (QA496-03): the NOTAM-airport role belongs to the aerodrome marker drawn at the governed reference
    point, never to a route row, even one printed with the aerodrome's code."""
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
    first_row, last_row, departure, destination = contract.markers_geojson["features"]

    for row in (first_row, last_row):
        assert row["properties"]["role"] == "route"
        assert row["properties"]["roles"] == []
    assert departure["id"] == "aerodrome-departure"
    assert departure["properties"]["role"] == "departure"
    assert "notam_airport" not in departure["properties"]["roles"]
    assert destination["id"] == "aerodrome-destination"
    assert destination["properties"]["role"] == "destination"
    assert "notam_airport" in destination["properties"]["roles"]
    # The governed KJFK reference point (LIDO N40 38.4 W073 46.7), not the row's coordinates.
    assert destination["geometry"]["coordinates"] == [-73.778333, 40.64]
