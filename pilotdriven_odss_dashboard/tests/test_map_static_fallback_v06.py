from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss_map_v06.aws_location import (
    _bounding_box,
    _simplify_route_geometry,
    _static_overlay,
)
from app.odss_map_v06.contract import MapBounds, MapContract


def _contract(point_count: int = 160) -> MapContract:
    coordinates = [
        [1.0 + index * 0.45, -12.0 + index * 0.18]
        for index in range(point_count)
    ]
    markers = [
        {
            "type": "Feature",
            "id": f"wp-{index:04d}",
            "geometry": {"type": "Point", "coordinates": coordinate},
            "properties": {
                "name": f"P{index:03d}",
                "role": "departure" if index == 0 else "destination" if index == point_count - 1 else "route",
                "priority": 100 if index in {0, point_count - 1} else 0,
            },
        }
        for index, coordinate in enumerate(coordinates)
    ]
    return MapContract(
        route_hash="a" * 64,
        route_geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "planned-route",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {},
                }
            ],
        },
        markers_geojson={"type": "FeatureCollection", "features": markers},
        bounds=MapBounds(west=0, south=-15, east=75, north=20),
        priority_labels=["P000", f"P{point_count - 1:03d}"],
    )


def test_static_overlay_is_simplified_under_aws_budget() -> None:
    contract = _contract()
    overlay = _static_overlay(
        contract,
        marker_limit=12,
        route_point_limit=80,
    )
    encoded = json.dumps(overlay, separators=(",", ":"), ensure_ascii=True)
    route = overlay["features"][0]["geometry"]["coordinates"]

    assert len(encoded) <= 4200
    assert len(route) == 80
    assert route[0] == contract.route_geojson["features"][0]["geometry"]["coordinates"][0]
    assert route[-1] == contract.route_geojson["features"][0]["geometry"]["coordinates"][-1]
    assert _bounding_box(contract) == "0.000000,-15.000000,75.000000,20.000000"


def test_multiline_simplification_preserves_each_segment_endpoints() -> None:
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[float(index), 0.0] for index in range(20)],
            [[100.0 + float(index), 1.0] for index in range(20)],
        ],
    }
    simplified = _simplify_route_geometry(geometry, max_points=12)

    assert simplified["type"] == "MultiLineString"
    assert simplified["coordinates"][0][0] == [0.0, 0.0]
    assert simplified["coordinates"][0][-1] == [19.0, 0.0]
    assert simplified["coordinates"][1][0] == [100.0, 1.0]
    assert simplified["coordinates"][1][-1] == [119.0, 1.0]
