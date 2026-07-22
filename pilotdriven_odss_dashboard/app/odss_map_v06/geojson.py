from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config import MapSettings
from .contract import MapBounds, MapContract
from .labels import choose_priority_labels, role_priority


def build_map_contract(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    settings: MapSettings,
) -> MapContract:
    """Build the canonical ODSS/PilotDriven map contract.

    The function consumes normalized ODSS data only; it never reparses the
    source PDF and never calculates operational significance independently.
    """
    points = _route_points(flight)
    if len(points) < 2:
        raise ValueError("At least two coordinate-bearing route points are required")

    significance = _significance_index(flight, findings, points)
    route_geometry = _route_geometry(points)
    route_feature = {
        "type": "Feature",
        "id": "planned-route",
        "geometry": route_geometry,
        "properties": {
            "flight_number": flight.get("flight_number"),
            "departure": flight.get("departure"),
            "destination": flight.get("destination"),
            "not_for_navigation": True,
        },
    }
    route_geojson = {
        "type": "FeatureCollection",
        "features": [route_feature],
    }

    marker_features: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        normalized_name = _normalized_name(point)
        roles = significance.get(normalized_name, set())
        role = _highest_role(roles) if roles else "route"
        priority = max(
            [role_priority(candidate) for candidate in roles] or [role_priority(role)]
        )
        if index == 0:
            role = "departure"
            priority = role_priority(role)
        elif index == len(points) - 1:
            role = "destination"
            priority = role_priority(role)

        marker_features.append(
            {
                "type": "Feature",
                "id": f"wp-{index:04d}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        point["longitude"],
                        point["latitude"],
                    ],
                },
                "properties": {
                    "name": (
                        str(flight.get("departure") or normalized_name)
                        if index == 0
                        else str(flight.get("destination") or normalized_name)
                        if index == len(points) - 1
                        else normalized_name
                    ),
                    "source_name": point.get("name"),
                    "role": role,
                    "roles": sorted(roles),
                    "priority": priority,
                    "actm_minutes": point.get("actm_minutes"),
                    "airway_in": point.get("airway_in"),
                    "fir_boundary": point.get("fir_boundary"),
                    "msa_hundreds_ft": point.get("msa_hundreds_ft"),
                    "vws": point.get("vws"),
                    "source_page": point.get("source_page"),
                    "not_for_navigation": True,
                },
            }
        )

    labels = choose_priority_labels(marker_features)
    markers_geojson = {
        "type": "FeatureCollection",
        "features": marker_features,
    }
    route_hash_payload = [
        {
            "name": _normalized_name(point),
            "longitude": round(float(point["longitude"]), 7),
            "latitude": round(float(point["latitude"]), 7),
            "actm_minutes": point.get("actm_minutes"),
        }
        for point in points
    ]
    warnings = []
    if settings.provider != "aws-location":
        warnings.append("Primary realistic basemap provider is disabled.")
    if settings.provider == "aws-location" and not settings.aws_location_api_key:
        warnings.append(
            "AWS Location API key is not configured; fallback rendering will be used."
        )

    return MapContract(
        provider=settings.provider,
        style=settings.style,
        route_hash=MapContract.route_digest(route_hash_payload),
        route_geojson=route_geojson,
        markers_geojson=markers_geojson,
        bounds=_bounds(points),
        priority_labels=labels,
        attribution=[
            "Amazon Location Service" if settings.provider == "aws-location" else "ODSS",
            "Briefing orientation only — not for navigation",
        ],
        warnings=warnings,
        metadata={
            "flight_number": flight.get("flight_number"),
            "departure": flight.get("departure"),
            "destination": flight.get("destination"),
            "point_count": len(points),
            "label_count": len(labels),
            "actual_takeoff_utc": flight.get("actual_takeoff_utc"),
        },
    )


def _route_points(flight: dict[str, Any]) -> list[dict[str, Any]]:
    points = []
    for waypoint in flight.get("route_waypoints") or []:
        latitude = waypoint.get("latitude")
        longitude = waypoint.get("longitude")
        if latitude is None or longitude is None:
            continue
        points.append(
            {
                **waypoint,
                "latitude": float(latitude),
                "longitude": _normalize_longitude(float(longitude)),
            }
        )
    return points


def _normalize_longitude(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value < -180.0:
        value += 360.0
    return value


def _route_geometry(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Split the route at the antimeridian for stable MapLibre rendering."""
    segments: list[list[list[float]]] = [[]]
    previous = None

    for point in points:
        coordinate = [point["longitude"], point["latitude"]]
        if previous is not None and abs(coordinate[0] - previous[0]) > 180.0:
            segments.append([])
        segments[-1].append(coordinate)
        previous = coordinate

    segments = [segment for segment in segments if len(segment) >= 2]
    if len(segments) == 1:
        return {"type": "LineString", "coordinates": segments[0]}
    return {"type": "MultiLineString", "coordinates": segments}


def _bounds(points: list[dict[str, Any]]) -> MapBounds:
    longitudes = [point["longitude"] for point in points]
    latitudes = [point["latitude"] for point in points]
    padding_lon = max(1.0, (max(longitudes) - min(longitudes)) * 0.04)
    padding_lat = max(1.0, (max(latitudes) - min(latitudes)) * 0.06)
    return MapBounds(
        west=max(-180.0, min(longitudes) - padding_lon),
        south=max(-90.0, min(latitudes) - padding_lat),
        east=min(180.0, max(longitudes) + padding_lon),
        north=min(90.0, max(latitudes) + padding_lat),
    )


def _normalized_name(waypoint: dict[str, Any]) -> str:
    return str(
        waypoint.get("fir_boundary")
        or waypoint.get("name")
        or ""
    ).upper().lstrip("-")


def _significance_index(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    points: list[dict[str, Any]],
) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)

    if points:
        index[_normalized_name(points[0])].add("departure")
        index[_normalized_name(points[-1])].add("destination")

    for point in points:
        name = _normalized_name(point)
        raw_name = str(point.get("name") or "").upper()
        if point.get("fir_boundary"):
            index[name].add("fir")
        if raw_name == "TOC":
            index[name].add("toc")
        if raw_name == "TOD":
            index[name].add("tod")
        if raw_name.startswith("ENTRY"):
            index[name].add("edto_entry")
        if raw_name.startswith("EXIT"):
            index[name].add("edto_exit")
        if raw_name.startswith("**ETP"):
            index[name].add("edto_etp")

    bobcat = flight.get("bobcat") or {}
    if bobcat.get("waypoint"):
        index[str(bobcat["waypoint"]).upper()].add("bobcat")

    for finding in findings:
        engine = str(finding.get("engine") or "")
        title = str(finding.get("title") or "")
        data = finding.get("data") or {}
        if engine == "depressurisation" and data.get("critical_point"):
            index[str(data["critical_point"]).upper()].add(
                "depressurisation_critical"
            )
        if engine == "terrain":
            maximum = data.get("maximum_waypoint")
            if maximum:
                index[str(maximum).upper()].add("terrain_critical")
        if engine == "communications":
            boundary = data.get("boundary")
            if boundary:
                index[str(boundary).upper()].add("early_contact")
            else:
                marker = _extract_after(title, "before ")
                if marker:
                    index[marker].add("early_contact")

    return index


def _extract_after(text: str, token: str) -> str | None:
    lower = text.lower()
    position = lower.rfind(token)
    if position < 0:
        return None
    return text[position + len(token):].strip().split()[0].upper().lstrip("-")


def _highest_role(roles: set[str]) -> str:
    return max(roles, key=role_priority)
