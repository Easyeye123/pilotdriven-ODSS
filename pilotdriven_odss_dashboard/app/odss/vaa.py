from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import os
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from shapely.affinity import translate
from shapely import make_valid
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.ops import split


AWC_ISIGMET_URL = "https://aviationweather.gov/api/data/isigmet?format=json"
_CACHE_LOCK = Lock()
# Keyed by AWC hazard code so volcanic ash and tropical cyclone snapshots
# never overwrite one another.
_CACHE_BY_HAZARD: dict[str, tuple[float, dict[str, Any]]] = {}


def extract_embedded_vaa(pages: list[str]) -> dict[str, Any]:
    """Extract the CFP's volcanic-ash source statement without interpreting it."""
    for page_number, page in enumerate(pages, start=1):
        match = re.search(r"VOLCANIC\s+ASH\s+SIGMETS?\s*:", page, re.IGNORECASE)
        if not match:
            continue
        tail = page[match.end():]
        lines: list[str] = []
        for raw_line in tail.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if lines and re.match(
                r"^(?:DESTINATION|TROPICAL\s+CYCLONE|SIGMETS?|AIRMETS?|NOTAMS?)\b",
                line,
                re.IGNORECASE,
            ):
                break
            lines.append(line)
            if len(lines) >= 20:
                break
        raw_excerpt = "\n".join(lines).strip()
        unavailable = bool(
            re.search(
                r"\b(?:NO\s+(?:WX|WEATHER)\s+DATA\s+AVAILABLE|DATA\s+NOT\s+AVAILABLE)\b",
                raw_excerpt,
                re.IGNORECASE,
            )
        )
        return {
            "status": "unavailable" if unavailable else "present",
            "source_page": page_number,
            "raw_excerpt": raw_excerpt,
            "raw_sha256": sha256(raw_excerpt.encode("utf-8")).hexdigest(),
        }
    return {
        "status": "not_present",
        "source_page": None,
        "raw_excerpt": "",
        "raw_sha256": None,
    }


def _utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _normalize_awc_advisory(
    record: dict[str, Any],
    hazard_code: str = "VA",
) -> tuple[dict[str, Any] | None, str | None]:
    hazard_code = hazard_code.upper()
    if str(record.get("hazard") or "").upper() != hazard_code:
        return None, None
    valid_from = _utc(record.get("validTimeFrom"))
    valid_to = _utc(record.get("validTimeTo"))
    coords = record.get("coords")
    if not valid_from or not valid_to or not isinstance(coords, list):
        return None, "missing_time_or_geometry"
    ring: list[list[float]] = []
    for coordinate in coords:
        if not isinstance(coordinate, dict):
            continue
        try:
            longitude = float(coordinate["lon"])
            latitude = float(coordinate["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            continue
        ring.append([longitude, latitude])
    if len(ring) < 3:
        return None, "missing_time_or_geometry"
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))

    raw_base = record.get("base")
    if raw_base is None and hazard_code == "TC":
        # An ICAO tropical cyclone SIGMET describes a surface-based cyclone area
        # and publishes only a top. An absent base means surface, not unknown.
        # A missing top stays unknown and is refused below.
        raw_base = 0
    try:
        lower_feet = int(raw_base)
        upper_feet = int(record["top"])
    except (KeyError, TypeError, ValueError):
        return None, "missing_vertical_limits"
    if lower_feet > upper_feet:
        return None, "invalid_vertical_limits"

    raw_text = str(record.get("rawSigmet") or "").strip()
    identifier_parts = [
        str(record.get("firId") or "GLOBAL"),
        str(record.get("seriesId") or hazard_code),
        str(int(valid_from.timestamp())),
    ]
    return {
        "advisory_id": "-".join(identifier_parts),
        "hazard": hazard_code,
        "fir_id": record.get("firId"),
        "fir_name": record.get("firName"),
        "series_id": record.get("seriesId"),
        "valid_from_utc": _iso(valid_from),
        "valid_to_utc": _iso(valid_to),
        "lower_flight_level": lower_feet // 100,
        "upper_flight_level": (upper_feet + 99) // 100,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "raw_text": raw_text,
        "raw_sha256": sha256(raw_text.encode("utf-8")).hexdigest(),
        "receipt_time_utc": _iso(_utc(record.get("receiptTime"))),
    }, None


def fetch_awc_snapshot(
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    hazard_code: str = "VA",
) -> dict[str, Any]:
    """Fetch a bounded, auditable snapshot of current international SIGMETs.

    ``hazard_code`` selects the AWC hazard class to normalise (``VA`` for
    volcanic ash, ``TC`` for tropical cyclone). The upstream feed is the same
    international SIGMET endpoint in both cases.
    """
    hazard_code = hazard_code.upper()
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    url = os.environ.get("ODSS_VA_SIGMET_URL", AWC_ISIGMET_URL).strip() or AWC_ISIGMET_URL
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in {
        "aviationweather.gov",
        "www.aviationweather.gov",
    }:
        return {
            "schema_version": "1.0",
            "provider": "noaa-awc-international-sigmet",
            "source_url": None,
            "status": "unavailable",
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "freshness_status": "unknown",
            "advisories": [],
            "parse_warnings": [],
            "error": "ODSS_VA_SIGMET_URL must use the approved aviationweather.gov HTTPS host",
        }
    try:
        timeout = _float_setting("ODSS_VA_SIGMET_TIMEOUT_SECONDS", 8.0, 1.0, 30.0)
        freshness_limit = _float_setting("ODSS_VA_SIGMET_FRESHNESS_MINUTES", 15.0, 1.0, 180.0)
    except ValueError as exc:
        return {
            "schema_version": "1.0",
            "provider": "noaa-awc-international-sigmet",
            "source_url": url,
            "status": "unavailable",
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "freshness_status": "unknown",
            "advisories": [],
            "parse_warnings": [],
            "error": str(exc),
        }
    user_agent = os.environ.get("ODSS_VA_SIGMET_USER_AGENT", "").strip() or (
        "PilotDriven-ODSS/0.6.1 (operational-briefing service)"
    )
    headers = {
        "Accept": "application/json",
        "User-Agent": user_agent,
    }
    own_client = client is None
    active_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = active_client.get(url, headers=headers)
        response.raise_for_status()
        raw_bytes = response.content
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("AWC response is not a JSON array")
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema_version": "1.0",
            "provider": "noaa-awc-international-sigmet",
            "source_url": url,
            "status": "unavailable",
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "freshness_status": "unknown",
            "advisories": [],
            "parse_warnings": [],
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    finally:
        if own_client:
            active_client.close()

    advisories: list[dict[str, Any]] = []
    parse_warnings: list[str] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            continue
        advisory, warning = _normalize_awc_advisory(record, hazard_code)
        if advisory:
            advisories.append(advisory)
        elif warning and str(record.get("hazard") or "").upper() == hazard_code:
            parse_warnings.append(f"record_{index}:{warning}")

    response_date = None
    try:
        if response.headers.get("date"):
            response_date = parsedate_to_datetime(response.headers["date"]).astimezone(timezone.utc)
    except (TypeError, ValueError):
        response_date = None
    reference_time = response_date or retrieved_at
    freshness_minutes = abs((retrieved_at - reference_time).total_seconds()) / 60
    valid_starts = [_utc(item["valid_from_utc"]) for item in advisories]
    valid_ends = [_utc(item["valid_to_utc"]) for item in advisories]
    hazard_label = "TC" if hazard_code == "TC" else "VA"
    return {
        "schema_version": "1.0",
        "provider": "noaa-awc-international-sigmet",
        "hazard_code": hazard_code,
        "source_url": url,
        "status": "available",
        "retrieved_at_utc": _iso(retrieved_at),
        "response_date_utc": _iso(response_date),
        "raw_sha256": sha256(raw_bytes).hexdigest(),
        "raw_record_count": len(payload),
        "advisory_count": len(advisories),
        "coverage_status": "global_current_active_sigmet",
        "coverage_start_utc": _iso(min((item for item in valid_starts if item), default=None)),
        "coverage_end_utc": _iso(max((item for item in valid_ends if item), default=None)),
        "freshness_status": "fresh" if freshness_minutes <= freshness_limit else "stale",
        "advisories": advisories,
        "parse_warnings": parse_warnings,
        "source_note": (
            "Official NOAA Aviation Weather Center international SIGMET feed. "
            f"This feed proves active {hazard_label} SIGMET matches but is not a "
            "full-flight future forecast archive."
        ),
    }


def live_vaa_snapshot(hazard_code: str = "VA") -> dict[str, Any]:
    """Cache the public feed briefly to respect the published API rate limit."""
    hazard_code = hazard_code.upper()
    try:
        cache_seconds = _float_setting("ODSS_VA_SIGMET_CACHE_SECONDS", 60.0, 30.0, 600.0)
    except ValueError:
        cache_seconds = 60.0
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE_BY_HAZARD.get(hazard_code)
        if cached and now_monotonic - cached[0] < cache_seconds:
            return deepcopy(cached[1])
        snapshot = fetch_awc_snapshot(hazard_code=hazard_code)
        _CACHE_BY_HAZARD[hazard_code] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


def _normalized_waypoint_name(waypoint: dict[str, Any]) -> str:
    return str(waypoint.get("name") or "").upper().lstrip("-")


def _planned_levels(
    waypoints: list[dict[str, Any]],
    profile: str | None,
) -> tuple[list[int | None], list[str]]:
    tokens = [token.strip().upper() for token in str(profile or "").split("/") if token.strip()]
    changes: list[tuple[str, int]] = []
    for index in range(0, len(tokens) - 1, 2):
        if not re.fullmatch(r"\d{3}", tokens[index + 1]):
            continue
        changes.append((tokens[index].lstrip("-"), int(tokens[index + 1])))
    if not changes:
        return [None] * len(waypoints), []

    def coordinate_anchor(name: str) -> tuple[float, float] | None:
        compact = re.fullmatch(r"(\d{2})([NS])(\d{3})([EW])", name)
        if compact:
            latitude = float(compact.group(1)) * (-1 if compact.group(2) == "S" else 1)
            longitude = float(compact.group(3)) * (-1 if compact.group(4) == "W" else 1)
            return latitude, longitude
        detailed = re.fullmatch(r"(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])", name)
        if detailed:
            latitude = (float(detailed.group(1)) + float(detailed.group(2)) / 60) * (
                -1 if detailed.group(3) == "S" else 1
            )
            longitude = (float(detailed.group(4)) + float(detailed.group(5)) / 60) * (
                -1 if detailed.group(6) == "W" else 1
            )
            return latitude, longitude
        return None

    change_by_index: dict[int, int] = {}
    unresolved: list[str] = []
    for change_position, (name, level) in enumerate(changes):
        match_index = next(
            (
                index
                for index, waypoint in enumerate(waypoints)
                if _normalized_waypoint_name(waypoint) == name
            ),
            None,
        )
        target = coordinate_anchor(name)
        if match_index is None and target is not None:
            match_index = next(
                (
                    index
                    for index, waypoint in enumerate(waypoints)
                    if abs(float(waypoint["latitude"]) - target[0]) <= 0.2
                    and abs(_unwrap(float(waypoint["longitude"]), target[1]) - target[1]) <= 0.2
                ),
                None,
            )
        if match_index is None:
            if change_position > 0:
                unresolved.append(name)
            continue
        change_by_index[match_index] = level

    current_level = changes[0][1]
    levels: list[int | None] = []
    for index, waypoint in enumerate(waypoints):
        current_level = change_by_index.get(index, current_level)
        levels.append(current_level)
    return levels, unresolved


def _flight_anchor(flight: dict[str, Any]) -> datetime | None:
    return _utc(
        flight.get("actual_takeoff_utc")
        or (flight.get("timing_reference") or {}).get("actual_takeoff_utc")
        or flight.get("scheduled_departure_utc")
    )


def _unwrap(value: float, reference: float) -> float:
    while value - reference > 180:
        value -= 360
    while value - reference < -180:
        value += 360
    return value


def _segment_intersects_geometry(
    start: dict[str, Any],
    end: dict[str, Any],
    geometry: dict[str, Any],
) -> bool:
    start_lon = float(start["longitude"])
    end_lon = _unwrap(float(end["longitude"]), start_lon)
    center = (start_lon + end_lon) / 2
    line = LineString(
        [(start_lon, float(start["latitude"])), (end_lon, float(end["latitude"]))]
    )

    geometry_type = geometry.get("type")
    coordinate_sets = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        polygons = [coordinate_sets]
    elif geometry_type == "MultiPolygon":
        polygons = coordinate_sets
    else:
        raise ValueError(f"Unsupported geometry type {geometry_type}")

    for polygon_coordinates in polygons:
        if not polygon_coordinates:
            continue
        projected_rings = [
            [(_unwrap(float(lon), center), float(lat)) for lon, lat in ring]
            for ring in polygon_coordinates
            if len(ring) >= 4
        ]
        if not projected_rings:
            continue
        candidate = Polygon(projected_rings[0], projected_rings[1:])
        if not candidate.is_valid:
            candidate = make_valid(candidate)
        if not candidate.is_empty and line.intersects(candidate):
            return True
    return False


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    return [
        polygon
        for child in getattr(geometry, "geoms", ())
        for polygon in _polygon_parts(child)
    ]


def _unwrapped_ring(
    ring: list[list[float]],
    reference: float | None = None,
) -> list[tuple[float, float]]:
    prepared: list[tuple[float, float]] = []
    previous = reference
    for raw_longitude, raw_latitude in ring:
        longitude = float(raw_longitude)
        if previous is not None:
            longitude = _unwrap(longitude, previous)
        prepared.append((longitude, float(raw_latitude)))
        previous = longitude
    return prepared


def _split_antimeridian_polygon(polygon: Polygon) -> list[Polygon]:
    parts = [polygon]
    for boundary, shift_direction in ((180.0, -360.0), (-180.0, 360.0)):
        adjusted: list[Polygon] = []
        splitter = LineString([(boundary, -1000.0), (boundary, 1000.0)])
        for part in parts:
            minimum, _, maximum, _ = part.bounds
            crosses = maximum > boundary if boundary > 0 else minimum < boundary
            pieces = _polygon_parts(split(part, splitter)) if crosses else [part]
            for piece in pieces:
                center = piece.representative_point().x
                should_shift = center > boundary if boundary > 0 else center < boundary
                adjusted.append(
                    translate(piece, xoff=shift_direction) if should_shift else piece
                )
        parts = adjusted
    return parts


def _map_safe_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Cut polygons at the date line so map clients do not fill across the globe."""
    geometry_type = geometry.get("type")
    coordinate_sets = geometry.get("coordinates") or []
    polygons = [coordinate_sets] if geometry_type == "Polygon" else coordinate_sets
    output: list[Polygon] = []
    try:
        for polygon_coordinates in polygons:
            if not polygon_coordinates:
                continue
            exterior = _unwrapped_ring(polygon_coordinates[0])
            if len(exterior) < 4:
                continue
            reference = sum(point[0] for point in exterior) / len(exterior)
            holes = [
                _unwrapped_ring(ring, reference)
                for ring in polygon_coordinates[1:]
                if len(ring) >= 4
            ]
            candidate = make_valid(Polygon(exterior, holes))
            for part in _polygon_parts(candidate):
                output.extend(_split_antimeridian_polygon(part))
    except (TypeError, ValueError):
        return geometry
    if not output:
        return geometry
    rendered = output[0] if len(output) == 1 else MultiPolygon(output)
    return dict(mapping(rendered))


def _intervals_touch_or_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start <= second_end and second_start <= first_end


def evaluate_vaa(
    flight: dict[str, Any],
    snapshot: dict[str, Any],
    embedded_source: dict[str, Any] | None = None,
    *,
    hazard_label: str = "volcanic_ash",
    default_advisory_id: str = "VA-SIGMET",
) -> dict[str, Any]:
    """Evaluate route, time, and planned flight level against source geometry.

    The evaluation is hazard-agnostic: ``hazard_label`` and
    ``default_advisory_id`` only affect how matched features are tagged for the
    map and report layers.
    """
    embedded = embedded_source or {
        "status": "not_present",
        "source_page": None,
        "raw_excerpt": "",
        "raw_sha256": None,
    }
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "review_required",
        "provider": snapshot.get("provider"),
        "source_url": snapshot.get("source_url"),
        "retrieved_at_utc": snapshot.get("retrieved_at_utc"),
        "coverage_status": snapshot.get("coverage_status"),
        "freshness_status": snapshot.get("freshness_status"),
        "embedded_source": embedded,
        "source_snapshot": snapshot,
        "reason_codes": [],
        "matches": [],
        "hazard_features": [],
    }

    if snapshot.get("status") == "disabled":
        result.update(status="not_assessed", reason_codes=["source_disabled"])
        return result
    if snapshot.get("status") != "available":
        result["reason_codes"].append("source_unavailable")
        if embedded.get("status") == "unavailable":
            result["reason_codes"].append("cfp_weather_data_unavailable")
        return result
    if snapshot.get("freshness_status") != "fresh":
        result["reason_codes"].append("source_stale")
    if snapshot.get("parse_warnings"):
        result["reason_codes"].append("source_records_incomplete")

    waypoints = [
        waypoint
        for waypoint in (flight.get("route_waypoints") or [])
        if waypoint.get("latitude") is not None
        and waypoint.get("longitude") is not None
        and waypoint.get("actm_minutes") is not None
    ]
    anchor = _flight_anchor(flight)
    if len(waypoints) < 2:
        result["reason_codes"].append("route_geometry_unavailable")
        return result
    if anchor is None:
        result["reason_codes"].append("route_timing_unavailable")
        return result
    levels, unresolved_level_anchors = _planned_levels(
        waypoints,
        flight.get("planned_level_profile"),
    )
    if any(level is None for level in levels):
        result["reason_codes"].append("flight_level_unavailable")
    if unresolved_level_anchors:
        result["reason_codes"].append("flight_level_change_unresolved")
        result["unresolved_level_anchors"] = unresolved_level_anchors

    matches: list[dict[str, Any]] = []
    matched_features: dict[str, dict[str, Any]] = {}
    for segment_index, (start, end) in enumerate(zip(waypoints, waypoints[1:])):
        start_actm = int(start["actm_minutes"])
        end_actm = int(end["actm_minutes"])
        if end_actm < start_actm:
            result["reason_codes"].append("route_timing_non_monotonic")
            continue
        segment_start = anchor + timedelta(minutes=start_actm)
        segment_end = anchor + timedelta(minutes=end_actm)
        flight_level = levels[segment_index]
        if flight_level is None:
            continue
        for advisory in snapshot.get("advisories") or []:
            valid_from = _utc(advisory.get("valid_from_utc"))
            valid_to = _utc(advisory.get("valid_to_utc"))
            if not valid_from or not valid_to:
                result["reason_codes"].append("advisory_time_unavailable")
                continue
            if not _intervals_touch_or_overlap(
                segment_start,
                segment_end,
                valid_from,
                valid_to,
            ):
                continue
            lower_level = advisory.get("lower_flight_level")
            upper_level = advisory.get("upper_flight_level")
            if lower_level is None or upper_level is None:
                result["reason_codes"].append("advisory_level_unavailable")
                continue
            if not int(lower_level) <= flight_level <= int(upper_level):
                continue
            try:
                intersects = _segment_intersects_geometry(
                    start,
                    end,
                    advisory.get("geometry") or {},
                )
            except (TypeError, ValueError):
                result["reason_codes"].append("advisory_geometry_invalid")
                continue
            if not intersects:
                continue
            advisory_id = str(advisory.get("advisory_id") or default_advisory_id)
            matches.append({
                "advisory_id": advisory_id,
                "fir_id": advisory.get("fir_id"),
                "route_segment_index": segment_index,
                "route_from": _normalized_waypoint_name(start),
                "route_to": _normalized_waypoint_name(end),
                "start_actm_minutes": start_actm,
                "end_actm_minutes": end_actm,
                "segment_start_utc": _iso(segment_start),
                "segment_end_utc": _iso(segment_end),
                "planned_flight_level": flight_level,
                "advisory_valid_from_utc": advisory.get("valid_from_utc"),
                "advisory_valid_to_utc": advisory.get("valid_to_utc"),
                "advisory_lower_flight_level": lower_level,
                "advisory_upper_flight_level": upper_level,
                "boundary_contact_counts": True,
            })
            matched_features[advisory_id] = {
                "type": "Feature",
                "id": advisory_id,
                "geometry": _map_safe_geometry(advisory["geometry"]),
                "properties": {
                    "advisory_id": advisory_id,
                    "hazard": hazard_label,
                    "fir_id": advisory.get("fir_id"),
                    "valid_from_utc": advisory.get("valid_from_utc"),
                    "valid_to_utc": advisory.get("valid_to_utc"),
                    "lower_flight_level": lower_level,
                    "upper_flight_level": upper_level,
                    "source": snapshot.get("provider"),
                    "not_for_navigation": True,
                },
            }

    result["matches"] = matches
    result["hazard_features"] = list(matched_features.values())
    if matches:
        result["status"] = "affected"
        result["reason_codes"] = sorted(set(result["reason_codes"] + ["verified_intersection"]))
        return result

    coverage_start = _utc(snapshot.get("coverage_start_utc"))
    coverage_end = _utc(snapshot.get("coverage_end_utc"))
    flight_start = anchor + timedelta(minutes=int(waypoints[0]["actm_minutes"]))
    flight_end = anchor + timedelta(minutes=int(waypoints[-1]["actm_minutes"]))
    coverage_complete = (
        snapshot.get("coverage_status") == "complete"
        and snapshot.get("freshness_status") == "fresh"
        and coverage_start is not None
        and coverage_end is not None
        and coverage_start <= flight_start
        and flight_end <= coverage_end
    )
    if coverage_complete and not result["reason_codes"]:
        result["status"] = "not_applicable"
        result["reason_codes"] = ["verified_no_intersection"]
    else:
        result["reason_codes"].append("coverage_not_complete_for_flight")
        if embedded.get("status") == "unavailable":
            result["reason_codes"].append("cfp_weather_data_unavailable")
        result["reason_codes"] = sorted(set(result["reason_codes"]))
    return result


def assess_volcanic_ash(
    flight: dict[str, Any],
    pages: list[str],
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    embedded = extract_embedded_vaa(pages)
    configured_source = os.environ.get("ODSS_VA_SIGMET_SOURCE", "awc").strip().lower()
    if snapshot is None:
        if configured_source in {"", "disabled", "off", "none"}:
            snapshot = {
                "schema_version": "1.0",
                "provider": None,
                "source_url": None,
                "status": "disabled",
                "coverage_status": "disabled",
                "freshness_status": "unknown",
                "advisories": [],
            }
        elif configured_source == "awc":
            snapshot = live_vaa_snapshot()
        else:
            snapshot = {
                "schema_version": "1.0",
                "provider": configured_source,
                "source_url": None,
                "status": "unavailable",
                "coverage_status": "unavailable",
                "freshness_status": "unknown",
                "advisories": [],
                "error": "Unsupported ODSS_VA_SIGMET_SOURCE setting",
            }
    review = evaluate_vaa(flight, snapshot, embedded)
    flight["vaa_review"] = review
    return review


__all__ = [
    "AWC_ISIGMET_URL",
    "assess_volcanic_ash",
    "evaluate_vaa",
    "extract_embedded_vaa",
    "fetch_awc_snapshot",
    "live_vaa_snapshot",
]
