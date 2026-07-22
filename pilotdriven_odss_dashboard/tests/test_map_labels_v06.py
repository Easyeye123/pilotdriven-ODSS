from __future__ import annotations

from app.odss_map_v06.labels import choose_priority_labels


def _marker(name: str, role: str, priority: int, longitude: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, 1.0]},
        "properties": {"name": name, "role": role, "priority": priority},
    }


def test_priority_labels_are_unique_and_keep_terminals() -> None:
    labels = choose_priority_labels(
        [
            _marker("WSSS", "departure", 100, 103.0),
            _marker("RJJJ", "fir", 50, 139.0),
            _marker("RJJJ", "fir", 50, 140.0),
            _marker("KJFK", "destination", 100, -73.0),
        ]
    )

    assert labels.count("RJJJ") == 1
    assert "WSSS" in labels
    assert "KJFK" in labels
