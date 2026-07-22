from __future__ import annotations

from collections.abc import Iterable
from math import cos, radians
from typing import Any


ROLE_PRIORITY: dict[str, int] = {
    "departure": 100,
    "destination": 100,
    "bobcat": 95,
    "kabul": 90,
    "early_contact": 85,
    "edto_entry": 80,
    "edto_etp": 80,
    "edto_exit": 80,
    "depressurisation_critical": 75,
    "terrain_critical": 70,
    "toc": 60,
    "tod": 60,
    "fir": 50,
    "orientation": 20,
    "route": 0,
}


def role_priority(role: str) -> int:
    return ROLE_PRIORITY.get(role, 0)


def choose_priority_labels(
    markers: Iterable[dict[str, Any]],
    *,
    max_labels: int = 12,
    minimum_distance_degrees: float = 2.0,
) -> list[str]:
    """Select a compact label set.

    MapLibre performs final symbol collision handling. This pre-filter keeps
    the PDF and dashboard label candidate set small and deterministic.
    """
    ordered = sorted(
        markers,
        key=lambda item: (
            -int(item.get("properties", {}).get("priority", 0)),
            int(item.get("properties", {}).get("actm_minutes", 0)),
            str(item.get("properties", {}).get("name", "")),
        ),
    )
    selected: list[dict[str, Any]] = []
    names: list[str] = []

    for marker in ordered:
        props = marker.get("properties", {})
        name = str(props.get("name") or "")
        geometry = marker.get("geometry", {})
        coordinates = geometry.get("coordinates")
        if not name or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue

        role = str(props.get("role") or "route")
        mandatory = role in {"departure", "destination", "bobcat", "kabul"}
        if not mandatory:
            too_close = any(
                _approx_distance(coordinates, prior["geometry"]["coordinates"])
                < minimum_distance_degrees
                for prior in selected
            )
            if too_close:
                continue

        selected.append(marker)
        names.append(name)
        if len(names) >= max_labels:
            break

    return names


def _approx_distance(first: list[float], second: list[float]) -> float:
    lon1, lat1 = float(first[0]), float(first[1])
    lon2, lat2 = float(second[0]), float(second[1])
    mean_lat = radians((lat1 + lat2) / 2.0)
    return (((lon2 - lon1) * cos(mean_lat)) ** 2 + (lat2 - lat1) ** 2) ** 0.5
