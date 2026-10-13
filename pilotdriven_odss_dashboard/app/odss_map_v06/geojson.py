from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from ..odss.constants import edto_sectors
from ..odss.enrichment import ofp_volcano_records
from ..odss.route_anchors import (
    DRAWN,
    drawn_aerodromes,
    resolve_route_endpoints,
    unplaced_endpoint_statements,
)
from .config import MapSettings
from .contract import MapBounds, MapContract
from .labels import choose_priority_labels, role_priority


def _circle_geometry(
    latitude: float,
    longitude: float,
    radius_nm: float,
    points: int = 36,
) -> dict[str, Any]:
    """A great-circle ring polygon around a point, for proximity display."""
    from math import asin, atan2, cos, degrees, radians, sin

    delta = radius_nm / 3440.065
    phi = radians(latitude)
    lam = radians(longitude)
    ring: list[list[float]] = []
    for index in range(points + 1):
        theta = radians(index * 360.0 / points)
        phi2 = asin(
            sin(phi) * cos(delta) + cos(phi) * sin(delta) * cos(theta)
        )
        lam2 = lam + atan2(
            sin(theta) * sin(delta) * cos(phi),
            cos(delta) - sin(phi) * sin(phi2),
        )
        ring.append([
            round(((degrees(lam2) + 540.0) % 360.0) - 180.0, 5),
            round(degrees(phi2), 5),
        ])
    return {"type": "Polygon", "coordinates": [ring]}


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

    # An aerodrome is drawn only at the reference point the governed table
    # holds for its ICAO code, as its own marker; no route row is ever given an
    # aerodrome's name or role, whatever its position (item 11, QA496-03).
    endpoints = resolve_route_endpoints(flight)
    aerodromes = drawn_aerodromes(endpoints)
    significance = _significance_index(flight, findings, points)
    notam_aerodromes = _notam_aerodromes(findings)
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
        roles = set(significance.get(normalized_name, set()))
        role = _highest_role(roles) if roles else "route"
        priority = max(
            [role_priority(candidate) for candidate in roles] or [role_priority(role)]
        )

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
                    "name": normalized_name,
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

    edto_etp_marker_count = 0
    for sector in edto_sectors(flight.get("edto")):
        sector_number = int(sector.get("number") or 1)
        grouped_etps: dict[tuple[float, float, int | None], dict[str, Any]] = {}
        for etp in sector.get("etps") or []:
            latitude = etp.get("latitude")
            longitude = etp.get("longitude")
            if latitude is None or longitude is None:
                continue
            normalized_longitude = _normalize_longitude(float(longitude))
            marker_key = (
                round(normalized_longitude, 7),
                round(float(latitude), 7),
                etp.get("actm_minutes"),
            )
            grouped = grouped_etps.setdefault(
                marker_key,
                {
                    "latitude": float(latitude),
                    "longitude": normalized_longitude,
                    "actm_minutes": etp.get("actm_minutes"),
                    "labels": [],
                    "airports": [],
                },
            )
            label = str(etp.get("label") or "ETP")
            if label not in grouped["labels"]:
                grouped["labels"].append(label)
            for airport in etp.get("airports") or []:
                if airport and airport not in grouped["airports"]:
                    grouped["airports"].append(airport)

        for etp_index, grouped in enumerate(grouped_etps.values(), start=1):
            labels = list(grouped["labels"])
            label = " / ".join(labels)
            marker_features.append(
                {
                    "type": "Feature",
                    "id": f"edto-s{sector_number}-etp-{etp_index}",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            grouped["longitude"],
                            grouped["latitude"],
                        ],
                    },
                    "properties": {
                        "name": f"S{sector_number} ETP {label}",
                        "source_name": label,
                        "role": "edto_etp",
                        "roles": ["edto_etp"],
                        "priority": role_priority("edto_etp"),
                        "actm_minutes": grouped["actm_minutes"],
                        "etp_labels": labels,
                        "airports": grouped["airports"],
                        "sector_number": sector_number,
                        "not_for_navigation": True,
                    },
                }
            )
            edto_etp_marker_count += 1

    for aerodrome in aerodromes:
        roles = set(aerodrome["roles"])
        if aerodrome["icao"] in notam_aerodromes:
            roles.add("notam_airport")
        marker_features.append(
            {
                "type": "Feature",
                "id": f"aerodrome-{aerodrome['role']}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        _normalize_longitude(aerodrome["longitude"]),
                        aerodrome["latitude"],
                    ],
                },
                "properties": {
                    "name": aerodrome["icao"],
                    "source_name": aerodrome["icao"],
                    "role": aerodrome["role"],
                    "roles": sorted(roles),
                    "priority": role_priority(aerodrome["role"]),
                    "aerodrome_reference": aerodrome["reference"],
                    "not_for_navigation": True,
                },
            }
        )

    labels = choose_priority_labels(marker_features)
    markers_geojson = {
        "type": "FeatureCollection",
        "features": marker_features,
    }
    va_sigmet_review = flight.get("va_sigmet_review") or flight.get("vaa_review") or {}
    sigmet_review = flight.get("sigmet_review") or {}
    tropical_cyclone_review = flight.get("tropical_cyclone_review") or {}
    sigmet_features = (
        list(sigmet_review.get("hazard_features") or [])
        if sigmet_review.get("status") == "affected"
        else []
    )
    vaa_features = (
        list(va_sigmet_review.get("hazard_features") or [])
        if va_sigmet_review.get("status") == "affected"
        else []
    )
    # A held ash advisory is drawn even when the verified result is
    # no-intersection (boss 30 Aug: "develop the polygon"); the feature's
    # hazard_state property lets the client style monitoring vs affecting.
    vaa_features = vaa_features + list(
        va_sigmet_review.get("monitoring_features") or []
    )
    # REV1 page 2: a proximity ring per advisory volcano near the corridor.
    # Rings ride the hazards collection tagged volcano_ring/volcano_marker so
    # the client styles them apart from ash geometry; proximity is not ash.
    volcano_proximity = va_sigmet_review.get("volcano_proximity") or {}
    corridor_nm = float(volcano_proximity.get("corridor_nm") or 200.0)
    for entry in volcano_proximity.get("entries") or []:
        position = entry.get("position") or {}
        latitude = position.get("latitude")
        longitude = position.get("longitude")
        if latitude is None or longitude is None:
            continue
        distance_nm = float(entry.get("distance_nm") or 0.0)
        if distance_nm > corridor_nm * 3:
            # Display bound only: distant advisory volcanoes stay in the
            # review list; drawing every global ring would bury the route.
            continue
        properties = {
            "volcano": entry.get("volcano"),
            "centre": entry.get("centre"),
            "aviation_colour_code": entry.get("aviation_colour_code"),
            "distance_nm": distance_nm,
            "within_corridor": bool(entry.get("within_corridor")),
            "corridor_nm": corridor_nm,
            "not_for_navigation": True,
        }
        vaa_features = vaa_features + [
            {
                "type": "Feature",
                "id": f"volcano-ring:{entry.get('volcano')}",
                "geometry": _circle_geometry(
                    float(latitude), float(longitude), corridor_nm
                ),
                "properties": {**properties, "volcano_ring": True},
            },
            {
                "type": "Feature",
                "id": f"volcano:{entry.get('volcano')}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(longitude), float(latitude)],
                },
                "properties": {**properties, "volcano_marker": True},
            },
        ]
    # A source-held NOTAM position is a location marker, not an ash polygon,
    # proximity finding or current activity claim. Preserve source identity
    # even when an official VAAC advisory also names the same volcano.
    for advisory in ofp_volcano_records(flight):
        position = advisory.get("volcano_position") or {}
        if position.get("source") != "ofp_printed_position":
            continue
        latitude, longitude = position.get("latitude"), position.get("longitude")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                   for value in (latitude, longitude)):
            continue
        if abs(latitude) > 90 or abs(longitude) > 180:
            continue
        vaa_features.append({
            "type": "Feature",
            "id": advisory.get("source_id") or f"ofp-volcano:{advisory.get('volcano')}:{advisory.get('notam_id')}",
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": {
                "volcano_marker": True,
                "volcano": advisory.get("volcano"),
                "notam_id": advisory.get("notam_id"),
                "source_id": advisory.get("source_id"),
                "source_page": advisory.get("source_page"),
                "source": "ofp_printed_position",
                "not_for_navigation": True,
            },
        })
    tropical_cyclone_features = (
        list(tropical_cyclone_review.get("hazard_features") or [])
        if tropical_cyclone_review.get("status") == "affected"
        else []
    )
    hazard_features = sigmet_features + vaa_features + tropical_cyclone_features
    hazards_geojson = {
        "type": "FeatureCollection",
        "features": hazard_features,
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
    warnings = unplaced_endpoint_statements(endpoints)
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
        hazards_geojson=hazards_geojson,
        bounds=_bounds(
            points
            + [
                {"latitude": item["latitude"], "longitude": _normalize_longitude(item["longitude"])}
                for item in aerodromes
            ]
        ),
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
            "hazard_count": len(hazard_features),
            "sigmet_status": sigmet_review.get("status"),
            "va_sigmet_status": va_sigmet_review.get("status"),
            # Deprecated alias retained for older map clients.
            "vaa_status": va_sigmet_review.get("status"),
            "tropical_cyclone_status": tropical_cyclone_review.get("status"),
            "actual_takeoff_utc": flight.get("actual_takeoff_utc"),
            "edto_sector_count": len(edto_sectors(flight.get("edto"))),
            "edto_etp_marker_count": edto_etp_marker_count,
            "aerodrome_marker_count": len(aerodromes),
            "route_endpoints": {
                role: {
                    "icao": end["icao"],
                    "status": end["status"],
                    "marker_id": (
                        next(
                            f"aerodrome-{item['role']}"
                            for item in aerodromes
                            if item["icao"] == end["icao"]
                        )
                        if end["status"] == DRAWN
                        else None
                    ),
                    "fix": end["fix"],
                    "reason": end["reason"],
                    "reference": end["reference"],
                }
                for role, end in endpoints.items()
            },
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
    # Airport roles (departure, destination, NOTAM airport) belong only to the
    # aerodrome markers. Keyed by name here they leaked to every row sharing
    # the name: SQ23's second -KZBW boundary, 52 NM from JFK, was drawn as the
    # departure and as a NOTAM airport.
    index: dict[str, set[str]] = defaultdict(set)

    for point in points:
        name = _normalized_name(point)
        raw_name = str(point.get("name") or "").upper()
        vws = point.get("vws")
        # The controlled ODSS engine defines a trigger as strictly greater
        # than 004. Publish that governed result as a marker role so browser
        # presentation never reinterprets or relaxes the threshold.
        if (
            isinstance(vws, (int, float))
            and not isinstance(vws, bool)
            and isfinite(float(vws))
            and float(vws) > 4
        ):
            index[name].add("vws_trigger")
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


def _notam_aerodromes(findings: list[dict[str, Any]]) -> set[str]:
    """ICAO codes named as a NOTAM location; only an aerodrome marker of the
    same code carries the NOTAM-airport role. A route row never does: a FIR
    location such as KZBW names no aerodrome."""
    return {
        str((finding.get("data") or {}).get("location")).upper()
        for finding in findings
        if str(finding.get("engine") or "") == "notam"
        and (finding.get("data") or {}).get("location")
    }


def _extract_after(text: str, token: str) -> str | None:
    lower = text.lower()
    position = lower.rfind(token)
    if position < 0:
        return None
    return text[position + len(token):].strip().split()[0].upper().lstrip("-")


def _highest_role(roles: set[str]) -> str:
    return max(roles, key=role_priority)
