from __future__ import annotations

from odss_map_v06.config import MapSettings
from odss_map_v06.geojson import build_map_contract


def _flight() -> dict:
    return {
        "flight_number": "SQ999",
        "departure": "WSSS",
        "destination": "RJBB",
        "route_waypoints": [
            {
                "name": "WSSS",
                "latitude": 1.36,
                "longitude": 103.99,
                "actm_minutes": 0,
                "source_page": 7,
            },
            {
                "name": "-WMFC",
                "fir_boundary": "WMFC",
                "latitude": 3.0,
                "longitude": 104.5,
                "actm_minutes": 30,
                "source_page": 7,
            },
            {
                "name": "TOD",
                "latitude": 33.0,
                "longitude": 135.0,
                "actm_minutes": 590,
                "source_page": 14,
            },
            {
                "name": "RJBB",
                "latitude": 34.43,
                "longitude": 135.24,
                "actm_minutes": 615,
                "source_page": 14,
            },
        ],
        "bobcat": None,
        "edto": {},
    }


def test_map_contract_is_stable_and_keeps_route_order() -> None:
    settings = MapSettings(provider="schematic")
    first = build_map_contract(_flight(), [], settings)
    second = build_map_contract(_flight(), [], settings)

    assert first.route_hash == second.route_hash
    assert first.metadata["point_count"] == 4
    assert first.route_geojson["features"][0]["geometry"]["type"] == "LineString"
    names = [
        item["properties"]["name"]
        for item in first.markers_geojson["features"]
    ]
    assert names == ["WSSS", "WMFC", "TOD", "RJBB"]
    assert "WSSS" in first.priority_labels
    assert "RJBB" in first.priority_labels


def test_style_descriptor_url_never_enters_contract() -> None:
    settings = MapSettings(
        aws_location_api_key="v1.public.example",
        aws_region="ap-southeast-1",
        style="Hybrid",
    )
    contract = build_map_contract(_flight(), [], settings)

    payload = contract.public_dict()
    assert "v1.public.example" not in str(payload)
    assert settings.style_descriptor_url.endswith(
        "/v2/styles/Hybrid/descriptor?key=v1.public.example"
    )
