from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
from html import escape
import json
from math import cos, radians
from pathlib import Path
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics

from .brief_theme import SANS, SANS_BOLD, register_fonts
from .constants import edto_sectors, format_actm, format_kg
from .engines import detect_terrain_events
from .pilot_briefing import prepare_pilot_findings
from .report_sections import level2_page


_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}
_NATURAL_EARTH_LAND = Path(__file__).with_name(
    "natural_earth_110m_land.geojson.gz.b64"
)


@lru_cache(maxsize=1)
def _natural_earth_land_rings() -> tuple[tuple[tuple[float, float], ...], ...]:
    """Load the bundled public-domain 1:110m land polygons once per process."""
    try:
        encoded = _NATURAL_EARTH_LAND.read_text(encoding="ascii")
        payload = gzip.decompress(base64.b64decode(encoded))
        geojson = json.loads(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, gzip.BadGzipFile):
        return ()

    rings: list[tuple[tuple[float, float], ...]] = []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Polygon":
            continue
        for ring in geometry.get("coordinates") or []:
            prepared = tuple(
                (float(coordinate[0]), float(coordinate[1]))
                for coordinate in ring
                if isinstance(coordinate, list) and len(coordinate) >= 2
            )
            if len(prepared) >= 3:
                rings.append(prepared)
    return tuple(rings)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _display_utc(value: str | None) -> str:
    parsed = _parse_utc(value)
    return parsed.strftime("%d %b %H%MZ").upper() if parsed else "--"


def _display_registration(value: str | None) -> str:
    text = str(value or "").strip().upper()
    compact = re.sub(r"[^A-Z0-9]", "", text)
    if compact.startswith("9V") and len(compact) == 5:
        return f"9V-{compact[2:]}"
    return text


def _shorten(value: str | None, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _cruise_summary(profile: str | None) -> str:
    if not profile:
        return "See CFP"
    levels = []
    for match in re.finditer(r"/(\d{3})(?=/|$)", profile):
        level = match.group(1)
        if level not in levels:
            levels.append(level)
    if not levels:
        return _shorten(profile, 24)
    return "/".join(f"FL{level}" for level in levels)


def _weather_records(flight: dict[str, Any], location: str) -> list[dict[str, Any]]:
    return [record for record in flight.get("weather", []) if record.get("location") == location]


def _weather_summary(
    findings: list[dict[str, Any]],
    location: str,
    role: str,
) -> dict[str, str]:
    selected = sorted(
        [
            item
            for item in findings
            if item.get("engine") == "weather"
            and (
                item.get("data", {}).get("location") == location
                or str(item.get("title") or "").endswith(f" - {location}")
            )
        ],
        key=_finding_sort_key,
    )
    primary = selected[0] if selected else None
    primary_data = primary.get("data", {}) if primary else {}
    status_text = str(primary_data.get("window_status_text") or "").strip()
    timing = str(primary_data.get("timing") or "").strip()
    primary_text = (
        " ".join(part for part in (status_text, timing) if part)
        if status_text
        else str(primary.get("summary") or "")
        if primary
        else ""
    )
    return {
        "primary": (
            _shorten(primary_text, 170)
            if primary
            else f"No significant {role} weather finding selected for the operating window"
        ),
        "secondary": (
            _shorten(
                f"{primary.get('data', {}).get('mechanism', '')}; "
                f"{primary.get('data', {}).get('flight_effect', '')}",
                170,
            )
            if primary
            else ""
        ),
    }


def _notice_kind(text: str) -> str:
    upper = text.upper()
    if any(token in upper for token in ("OBST", "OBSTACLE", "CRANE", "POLE")):
        return "Obstacle"
    if any(token in upper for token in ("RWY", "RUNWAY", "ILS", "LOC", "RNP", "VOR", "OCA", "MINIMA")):
        return "Runway / approach"
    if any(token in upper for token in ("TWY", "TAXIWAY", "STOP BAR", "TAXILANE")):
        return "Taxiway"
    if any(token in upper for token in ("STAND", "APRON", "PARKING")):
        return "Apron / stand"
    if any(token in upper for token in ("AIRSPACE", "TSA", "TRA", "MILITARY", "DANGER")):
        return "Airspace"
    return "Other / info"


def _finding_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    data = item.get("data", {})
    return (
        -_SEVERITY_RANK.get(str(item.get("severity") or "information"), 0),
        -int(data.get("priority_score") or 0),
        str(item.get("title") or ""),
    )


def _notam_cards(findings: list[dict[str, Any]], role: str, limit: int = 4) -> list[dict[str, str]]:
    selected = sorted(
        [
            item
            for item in findings
            if item.get("engine") == "notam" and item.get("data", {}).get("role") == role
        ],
        key=_finding_sort_key,
    )[:limit]
    cards = [
        {
            "kind": _notice_kind(f"{item.get('title', '')} {item.get('summary', '')}"),
            "text": _shorten(item.get("summary"), 92),
            "severity": str(item.get("severity") or "information"),
        }
        for item in selected
    ]
    if not cards:
        cards.append({
            "kind": "Pertinent review",
            "text": "No airport-specific ODSS NOTAM finding selected for this operating window.",
            "severity": "information",
        })
    return cards


def _station_weather_text(
    flight: dict[str, Any], location: str, record_type: str
) -> str | None:
    """First CFP-embedded bulletin of the given type for a station.

    These are the raw METAR/TAF strings LIDO prints in the wx section; the
    panels carry them verbatim so every surface shows the actual groups, not
    a synthesised overlap sentence."""
    for record in flight.get("weather") or []:
        if (
            record.get("location") == location
            and record.get("record_type") == record_type
            and str(record.get("text") or "").strip()
        ):
            return str(record["text"]).strip()
    return None


def _airport_panel(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    location: str,
    role: str,
    runway: str | None,
) -> dict[str, Any]:
    weather = _weather_summary(findings, location, role)
    weather["metar"] = _station_weather_text(flight, location, "METAR")
    weather["taf"] = _station_weather_text(flight, location, "TAF")
    return {
        "icao": location,
        "role": role,
        "runway": runway or "Review actual runway",
        "weather": weather,
        "considerations": _notam_cards(findings, role),
    }


def _unwrap_route_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous: float | None = None
    for point in points:
        longitude = float(point["longitude"])
        if previous is not None:
            while longitude - previous > 180:
                longitude -= 360
            while longitude - previous < -180:
                longitude += 360
        copied = dict(point)
        copied["plot_longitude"] = longitude
        result.append(copied)
        previous = longitude
    return result


def _evenly_spaced_indices(indices: list[int], limit: int) -> set[int]:
    """Keep representative labels without turning a long-haul map into a wall of text."""
    if limit <= 0 or not indices:
        return set()
    if len(indices) <= limit:
        return set(indices)
    if limit == 1:
        return {indices[len(indices) // 2]}
    return {
        indices[round(position * (len(indices) - 1) / (limit - 1))]
        for position in range(limit)
    }


def build_route_map(flight: dict[str, Any]) -> dict[str, Any]:
    raw_points: list[dict[str, Any]] = []
    for waypoint in flight.get("route_waypoints", []):
        latitude = waypoint.get("latitude")
        longitude = waypoint.get("longitude")
        if latitude is None or longitude is None:
            continue
        raw_points.append({
            "name": str(waypoint.get("name") or ""),
            "display_name": str(waypoint.get("fir_boundary") or waypoint.get("name") or "").lstrip("-"),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "actm_minutes": waypoint.get("actm_minutes"),
            "fir_boundary": waypoint.get("fir_boundary"),
            "msa_hundreds_ft": waypoint.get("msa_hundreds_ft"),
            "msa_asterisk": bool(waypoint.get("msa_asterisk")),
            "vws": waypoint.get("vws"),
            "airway_in": waypoint.get("airway_in"),
        })

    points = _unwrap_route_points(raw_points)
    if not points:
        return {
            "available": False,
            "points": [],
            "label_indices": [],
            "note": "No usable route coordinates were parsed.",
        }

    priority_indices: set[int] = {0, len(points) - 1}
    fir_indices: list[int] = []
    bobcat_name = str((flight.get("bobcat") or {}).get("waypoint") or "").upper()
    terrain_maxima = {
        str(event["maximum"].get("name") or "").upper()
        for event in detect_terrain_events(flight.get("route_waypoints", []))
    }
    for index, point in enumerate(points):
        name = str(point.get("name") or "").upper().lstrip("-")
        if point.get("fir_boundary"):
            fir_indices.append(index)
        if name in {"TOC", "TOD"} or name.startswith(("ENTRY", "EXIT", "**ETP")):
            priority_indices.add(index)
        if bobcat_name and name == bobcat_name:
            priority_indices.add(index)
        if name in terrain_maxima:
            priority_indices.add(index)

    priority_indices.update(_evenly_spaced_indices(fir_indices, 6))
    priority_indices.update(
        _evenly_spaced_indices(list(range(1, max(1, len(points) - 1))), 4)
    )

    for index, point in enumerate(points):
        role = "route"
        if index == 0:
            role = "departure"
            point["display_name"] = flight.get("departure") or point["display_name"]
        elif index == len(points) - 1:
            role = "destination"
            point["display_name"] = flight.get("destination") or point["display_name"]
        elif point.get("fir_boundary"):
            role = "fir"
        elif str(point.get("name") or "").upper().lstrip("-") == bobcat_name and bobcat_name:
            role = "bobcat"
        elif str(point.get("name") or "").upper().lstrip("-") in terrain_maxima:
            role = "terrain"
        elif str(point.get("name") or "").upper().startswith(("ENTRY", "EXIT")):
            role = "edto"
        point["role"] = role

    sigmet_features = list(
        ((flight.get("sigmet_review") or {}).get("hazard_features") or [])
    )
    vaa_features = list(
        ((flight.get("vaa_review") or {}).get("hazard_features") or [])
    )
    tc_features = list(
        ((flight.get("tropical_cyclone_review") or {}).get("hazard_features") or [])
    )
    hazard_features = sigmet_features + vaa_features + tc_features

    return {
        "available": len(points) >= 2,
        "points": points,
        "label_indices": sorted(priority_indices),
        "hazard_features": hazard_features,
        "sigmet_status": (flight.get("sigmet_review") or {}).get("status"),
        "vaa_status": (flight.get("vaa_review") or {}).get("status"),
        "tropical_cyclone_status": (
            flight.get("tropical_cyclone_review") or {}
        ).get("status"),
        "note": (
            "Filed route from CFP coordinates"
            + (
                "; active SIGMET geometry shown"
                if hazard_features
                else ""
            )
            + "."
        ),
    }


def project_route_map(
    route_map: dict[str, Any],
    width: float,
    height: float,
    padding: float = 28.0,
) -> dict[str, Any]:
    points = route_map.get("points") or []
    if len(points) < 2:
        return {"points": [], "grid": [], "frame": {}}

    mid_latitude = sum(float(point["latitude"]) for point in points) / len(points)
    longitude_factor = max(0.25, cos(radians(mid_latitude)))
    x_values = [float(point["plot_longitude"]) * longitude_factor for point in points]
    y_values = [float(point["latitude"]) for point in points]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(y_values), max(y_values)
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)
    drawn_width = span_x * scale
    drawn_height = span_y * scale
    offset_x = (width - drawn_width) / 2
    offset_y = (height - drawn_height) / 2
    frame = {
        "longitude_factor": longitude_factor,
        "center_longitude": (
            min(float(point["plot_longitude"]) for point in points)
            + max(float(point["plot_longitude"]) for point in points)
        )
        / 2,
        "min_x": min_x,
        "min_y": min_y,
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
    }

    projected = []
    for index, point in enumerate(points):
        x = offset_x + (x_values[index] - min_x) * scale
        y = offset_y + (y_values[index] - min_y) * scale
        copied = dict(point)
        copied.update({"x": x, "y": y, "label": index in set(route_map.get("label_indices") or [])})
        projected.append(copied)

    grid = []
    for step in range(1, 5):
        fraction = step / 5
        grid.append({
            "x": padding + fraction * (width - 2 * padding),
            "y": padding + fraction * (height - 2 * padding),
        })
    return {"points": projected, "grid": grid, "frame": frame}


def _project_land_ring(
    ring: tuple[tuple[float, float], ...],
    frame: dict[str, float],
) -> list[list[tuple[float, float]]]:
    """Project and split a land ring across the active longitude wrap."""
    longitude_factor = float(frame["longitude_factor"])
    center_longitude = float(frame["center_longitude"])
    min_x = float(frame["min_x"])
    min_y = float(frame["min_y"])
    scale = float(frame["scale"])
    offset_x = float(frame["offset_x"])
    offset_y = float(frame["offset_y"])

    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_longitude: float | None = None
    for raw_longitude, latitude in ring:
        longitude = raw_longitude
        while longitude - center_longitude > 180:
            longitude -= 360
        while longitude - center_longitude < -180:
            longitude += 360
        if previous_longitude is not None and abs(longitude - previous_longitude) > 180:
            if len(current) >= 3:
                segments.append(current)
            current = []
        current.append(
            (
                offset_x + (longitude * longitude_factor - min_x) * scale,
                offset_y + (latitude - min_y) * scale,
            )
        )
        previous_longitude = longitude
    if len(current) >= 3:
        segments.append(current)
    return segments


def _projected_land_segments(
    projection: dict[str, Any],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    frame = projection.get("frame") or {}
    if not frame:
        return ()
    return tuple(
        tuple(segment)
        for ring in _natural_earth_land_rings()
        for segment in _project_land_ring(ring, frame)
    )


def _projected_hazard_segments(
    route_map: dict[str, Any],
    projection: dict[str, Any],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    frame = projection.get("frame") or {}
    if not frame:
        return ()
    rings: list[tuple[tuple[float, float], ...]] = []
    for feature in route_map.get("hazard_features") or []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        polygon_sets = [coordinates] if geometry.get("type") == "Polygon" else coordinates
        for polygon_coordinates in polygon_sets:
            for ring in polygon_coordinates or []:
                try:
                    prepared = tuple((float(lon), float(lat)) for lon, lat in ring)
                except (TypeError, ValueError):
                    continue
                if len(prepared) >= 4:
                    rings.append(prepared)
    return tuple(
        tuple(segment)
        for ring in rings
        for segment in _project_land_ring(ring, frame)
    )


def render_route_svg(route_map: dict[str, Any], width: int = 1200, height: int = 600) -> str:
    projection = project_route_map(route_map, float(width), float(height), 44.0)
    points = projection.get("points") or []
    if len(points) < 2:
        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Route map unavailable">'
            '<rect width="100%" height="100%" fill="#07111f"/>'
            '<text x="50%" y="50%" text-anchor="middle" fill="#93a4b8" font-size="28">'
            'Route coordinates unavailable</text></svg>'
        )

    polyline = " ".join(f"{point['x']:.1f},{height - point['y']:.1f}" for point in points)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="CFP route map">',
        '<defs><linearGradient id="odssMapBg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#07111f"/><stop offset="1" stop-color="#102843"/>'
        '</linearGradient></defs>',
        f'<rect width="{width}" height="{height}" rx="18" fill="url(#odssMapBg)"/>',
    ]
    for segment in _projected_land_segments(projection):
        path = " ".join(
            (
                f"M {point[0]:.1f} {height - point[1]:.1f}"
                if index == 0
                else f"L {point[0]:.1f} {height - point[1]:.1f}"
            )
            for index, point in enumerate(segment)
        )
        parts.append(
            f'<path d="{path} Z" fill="#153044" stroke="#42647b" '
            'stroke-width="1" opacity="0.9"/>'
        )
    for grid in projection.get("grid") or []:
        parts.append(
            f'<line x1="{grid["x"]:.1f}" y1="36" x2="{grid["x"]:.1f}" y2="{height - 36}" '
            'stroke="#28425f" stroke-width="1" opacity="0.55"/>'
        )
        parts.append(
            f'<line x1="36" y1="{height - grid["y"]:.1f}" x2="{width - 36}" y2="{height - grid["y"]:.1f}" '
            'stroke="#28425f" stroke-width="1" opacity="0.55"/>'
        )
    for segment in _projected_hazard_segments(route_map, projection):
        path = " ".join(
            (
                f"M {point[0]:.1f} {height - point[1]:.1f}"
                if index == 0
                else f"L {point[0]:.1f} {height - point[1]:.1f}"
            )
            for index, point in enumerate(segment)
        )
        parts.append(
            f'<path d="{path} Z" fill="#ff6b6b" stroke="#ffb84d" '
            'stroke-width="3" opacity="0.38"/>'
        )
    parts.append(
        f'<polyline points="{polyline}" fill="none" stroke="#dceeff" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )

    role_colour = {
        "departure": "#4db8ff",
        "destination": "#7c4dff",
        "fir": "#b38cff",
        "bobcat": "#ffb84d",
        "terrain": "#ff7f66",
        "edto": "#55d6be",
        "route": "#dceeff",
    }
    for index, point in enumerate(points):
        cx, cy = point["x"], height - point["y"]
        colour = role_colour.get(point.get("role"), "#dceeff")
        radius = 7 if point.get("role") in {"departure", "destination"} else 4.2
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{colour}" '
            'stroke="#07111f" stroke-width="2"/>'
        )
        if point.get("label"):
            dy = -12 if index % 2 == 0 else 20
            anchor = "start" if cx < width * 0.76 else "end"
            dx = 9 if anchor == "start" else -9
            label = escape(_shorten(point.get("display_name"), 18))
            parts.append(
                f'<text x="{cx + dx:.1f}" y="{cy + dy:.1f}" text-anchor="{anchor}" '
                'fill="#e8f2ff" font-family="Arial, sans-serif" font-size="16" '
                f'font-weight="600">{label}</text>'
            )
    parts.append(
        f'<text x="20" y="{height - 16}" fill="#8396ab" font-family="Arial, sans-serif" '
        f'font-size="13">{escape(route_map.get("note") or "")}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _pilot_route_map_label(value: Any) -> str:
    label = " ".join(str(value or "").split())
    engineering_markers = (
        "fallback",
        "hybrid print",
        "rendering unavailable",
    )
    if not label or any(marker in label.lower() for marker in engineering_markers):
        return "Route map"
    return label


def draw_route_map_pdf(canvas, route_map: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    map_label_size = 7.2
    map_note_size = 7.2
    register_fonts()
    snapshot_path = route_map.get("snapshot_path")
    if snapshot_path:
        candidate = Path(str(snapshot_path))
        if candidate.is_file():
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#07111F"))
            canvas.roundRect(x, y, width, height, 6, fill=1, stroke=0)
            canvas.drawImage(
                ImageReader(str(candidate)),
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
            canvas.setFillColor(colors.HexColor("#E8F2FF"))
            canvas.setFont(SANS, map_note_size)
            label = _pilot_route_map_label(route_map.get("snapshot_label"))
            canvas.drawString(
                x + 5,
                y + 4,
                f"{label} - Filed route from CFP coordinates",
            )
            canvas.restoreState()
            return

    projection = project_route_map(route_map, width, height, 18.0)
    points = projection.get("points") or []
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#07111F"))
    canvas.roundRect(x, y, width, height, 6, fill=1, stroke=0)
    if len(points) < 2:
        canvas.setFillColor(colors.HexColor("#93A4B8"))
        canvas.setFont(SANS_BOLD, 10)
        canvas.drawCentredString(x + width / 2, y + height / 2, "Route coordinates unavailable")
        canvas.restoreState()
        return

    clip = canvas.beginPath()
    clip.rect(x, y, width, height)
    canvas.clipPath(clip, stroke=0, fill=0)
    canvas.setFillColor(colors.HexColor("#153044"))
    canvas.setStrokeColor(colors.HexColor("#42647B"))
    canvas.setLineWidth(0.35)
    for segment in _projected_land_segments(projection):
        land = canvas.beginPath()
        land.moveTo(x + segment[0][0], y + segment[0][1])
        for px, py in segment[1:]:
            land.lineTo(x + px, y + py)
        land.close()
        canvas.drawPath(land, stroke=1, fill=1)

    canvas.setStrokeColor(colors.HexColor("#28425F"))
    canvas.setLineWidth(0.4)
    for grid in projection.get("grid") or []:
        canvas.line(x + grid["x"], y + 10, x + grid["x"], y + height - 10)
        canvas.line(x + 10, y + grid["y"], x + width - 10, y + grid["y"])

    canvas.setFillColor(colors.Color(1.0, 0.42, 0.42, alpha=0.28))
    canvas.setStrokeColor(colors.HexColor("#FFB84D"))
    canvas.setLineWidth(1.1)
    for segment in _projected_hazard_segments(route_map, projection):
        hazard = canvas.beginPath()
        hazard.moveTo(x + segment[0][0], y + segment[0][1])
        for px, py in segment[1:]:
            hazard.lineTo(x + px, y + py)
        hazard.close()
        canvas.drawPath(hazard, stroke=1, fill=1)

    canvas.setStrokeColor(colors.HexColor("#DCEEFF"))
    canvas.setLineWidth(1.8)
    path = canvas.beginPath()
    path.moveTo(x + points[0]["x"], y + points[0]["y"])
    for point in points[1:]:
        path.lineTo(x + point["x"], y + point["y"])
    canvas.drawPath(path, stroke=1, fill=0)

    role_colour = {
        "departure": colors.HexColor("#4DB8FF"),
        "destination": colors.HexColor("#7C4DFF"),
        "fir": colors.HexColor("#B38CFF"),
        "bobcat": colors.HexColor("#FFB84D"),
        "terrain": colors.HexColor("#FF7F66"),
        "edto": colors.HexColor("#55D6BE"),
        "route": colors.HexColor("#DCEEFF"),
    }
    canvas.setFont(SANS_BOLD, map_label_size)
    for point in points:
        px, py = x + point["x"], y + point["y"]
        canvas.setFillColor(role_colour.get(point.get("role"), colors.HexColor("#DCEEFF")))
        radius = 3.2 if point.get("role") in {"departure", "destination"} else 1.9
        canvas.circle(px, py, radius, fill=1, stroke=0)

    role_priority = {
        "departure": 0,
        "destination": 0,
        "bobcat": 1,
        "edto": 2,
        "terrain": 3,
        "fir": 4,
        "route": 5,
    }
    labelled = sorted(
        [
            (index, point)
            for index, point in enumerate(points)
            if point.get("label")
        ],
        key=lambda item: (role_priority.get(str(item[1].get("role")), 6), item[0]),
    )
    occupied: list[tuple[float, float, float, float]] = []
    canvas.setFillColor(colors.HexColor("#E8F2FF"))
    for index, point in labelled:
        px, py = x + point["x"], y + point["y"]
        label = _shorten(point.get("display_name"), 16)
        text_width = pdfmetrics.stringWidth(label, SANS_BOLD, map_label_size)
        right_side = px < x + width * 0.72
        anchors = (
            [(px + 3.5, py + 4.0, "left"), (px + 3.5, py - 8.0, "left")]
            if right_side
            else [(px - 3.5, py + 4.0, "right"), (px - 3.5, py - 8.0, "right")]
        )
        anchors.extend(
            [(px - 3.5, py + 4.0, "right"), (px - 3.5, py - 8.0, "right")]
            if right_side
            else [(px + 3.5, py + 4.0, "left"), (px + 3.5, py - 8.0, "left")]
        )

        selected: tuple[float, float, str, tuple[float, float, float, float]] | None = None
        for tx, ty, anchor in anchors:
            left = tx if anchor == "left" else tx - text_width
            box = (left - 1.0, ty - 1.5, left + text_width + 1.0, ty + map_label_size)
            within_map = (
                box[0] >= x + 2
                and box[2] <= x + width - 2
                and box[1] >= y + 8
                and box[3] <= y + height - 2
            )
            overlaps = any(
                not (
                    box[2] + 1.5 < other[0]
                    or box[0] - 1.5 > other[2]
                    or box[3] + 1.5 < other[1]
                    or box[1] - 1.5 > other[3]
                )
                for other in occupied
            )
            if within_map and not overlaps:
                selected = (tx, ty, anchor, box)
                break

        if selected is None:
            continue
        tx, ty, anchor, box = selected
        if anchor == "left":
            canvas.drawString(tx, ty, label)
        else:
            canvas.drawRightString(tx, ty, label)
        occupied.append(box)
    canvas.setFillColor(colors.HexColor("#8396AB"))
    canvas.setFont(SANS, map_note_size)
    canvas.drawString(x + 5, y + 4, str(route_map.get("note") or ""))
    canvas.restoreState()


def _communication_timeline(
    findings: list[dict[str, Any]],
    timing_view: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if timing_view:
        return [
            {
                "time": event.get("utc_clock") or event.get("utc_display") or "--",
                "actm": event.get("actm") or "--.--",
                "event": _shorten(event.get("label"), 46),
                "detail": _shorten(event.get("details"), 58),
            }
            for event in (timing_view.get("early_calls") or [])[:5]
        ]

    timeline = []
    for item in findings:
        if item.get("engine") != "communications":
            continue
        actm = item.get("data", {}).get("action_actm_minutes")
        timeline.append({
            "time": f"ACTM {format_actm(actm)}" if actm is not None else "ACTM --.--",
            "actm": format_actm(actm),
            "event": _shorten(item.get("title"), 46),
            "detail": _shorten(item.get("summary"), 58),
        })
    return timeline[:5]


def _enroute_weather_cards(findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    weather = sorted(
        [
            item
            for item in findings
            if item.get("engine") in {"sigmet", "vaa", "tropical_cyclone", "weather"}
            and (
                item.get("engine") != "weather"
                or (item.get("data") or {}).get("window_status")
                != "no_significant_overlap"
            )
        ],
        key=_finding_sort_key,
    )
    cards = []
    for item in weather:
        title = str(item.get("title") or "Weather")
        if any(role in title.lower() for role in ("departure", "destination")) and len(cards) < 2:
            continue
        data = item.get("data") or {}
        if item.get("engine") == "weather":
            mechanism = str(data.get("mechanism") or "").strip()
            if mechanism.lower() == "none safely classified":
                mechanism = "Not safely classified from the available forecast"
            text = " | ".join(
                part
                for part in (
                    str(data.get("utc_window") or "").strip(),
                    mechanism,
                    str(data.get("timing") or "").strip(),
                    str(data.get("flight_effect") or "").strip(),
                )
                if part
            )
        else:
            text = str(item.get("summary") or "")
        cards.append({
            "title": _shorten(title, 30),
            "text": _shorten(text, 135),
            "severity": str(item.get("severity") or "information"),
        })
        if len(cards) >= 3:
            break
    if not cards:
        cards.append({"title": "Enroute weather", "text": "No significant enroute weather finding selected.", "severity": "information"})
    return cards


def _edto_assessment_view(edto: dict[str, Any]) -> dict[str, Any]:
    """Return only an internally consistent, evidence-bearing assessment.

    Legacy or malformed records fail closed. In particular, an empty EDTO
    object is not converted into a verified NIL assessment.
    """
    raw = edto.get("assessment")
    assessment = raw if isinstance(raw, dict) else {}
    raw_evidence = assessment.get("evidence")
    evidence = [
        dict(item)
        for item in (raw_evidence if isinstance(raw_evidence, list) else [])
        if isinstance(item, dict)
        and str(item.get("source") or "").strip()
        and str(item.get("reason_code") or "").strip()
    ]
    status = str(assessment.get("status") or "").strip()
    has_operational_data = bool(edto_sectors(edto) or edto.get("airports"))
    consistent = (
        (status == "affected" and has_operational_data)
        or (status == "verified_not_applicable" and not has_operational_data)
        or status == "review_required"
    )
    if not evidence or not consistent:
        status = "review_required"
        evidence.append({
            "source": "stored_odss_analysis",
            "reason_code": (
                "edto_assessment_evidence_missing"
                if not evidence
                else "edto_assessment_contract_conflict"
            ),
        })
    return {"status": status, "evidence": evidence}


def _edto_classification(flight: dict[str, Any]) -> str:
    classification = str(
        ((flight.get("fuel_summary") or {}).get("classification")) or ""
    ).strip().upper()
    if classification:
        return classification
    return "EDTO" if (flight.get("edto") or {}).get("sectors") else ""



def _edto_gate_sentence(edto_view: dict[str, Any]) -> str:
    assessment = edto_view.get("assessment")
    status = str((assessment or {}).get("status") if isinstance(assessment, dict) else assessment or "").strip()
    if status == "review_required":
        return "Checked-period suitability requires review - see the alternates page."
    if status in {"ok", "complete", "verified"}:
        return "Checked-period suitability verified against the governed window."
    return "Destination alternate and enroute suitability remain independent checks."



def _edto_operational_rows(
    classification: str,
    edto_view: dict[str, Any],
    fuel_summary: dict[str, Any],
) -> list[tuple[str, str]]:
    """Pilot-readable EDTO facts already parsed from the uploaded CFP."""
    source = str(fuel_summary.get("source_classification") or classification).strip().upper()
    source_sentence = (
        "CFP page 1: SUMMARY STANDARD CFP (non-EDTO)."
        if source == "STANDARD" and classification.startswith("NON")
        else f"CFP page 1: SUMMARY {source} CFP."
        if source
        else "CFP classification requires review."
    )
    rows: list[tuple[str, str]] = [("CLASSIFICATION", (
        source_sentence
    ))]
    sectors = edto_view.get("sectors") or []
    for index, sector in enumerate(sectors, start=1):
        number = sector.get("number") or index
        entry = sector.get("entry") or "--.--"
        exit_ = sector.get("exit") or "--.--"
        line = f"ENTRY ACTM {entry} | EXIT ACTM {exit_}"
        if entry == exit_ and entry != "--.--":
            # Canon wording (REV3 p4): a zero-duration boundary contact is a
            # printed CFP fact, and it stays an EDTO flight.
            line += (
                " - boundary-contact sector at CFP display resolution; "
                "retain the EDTO source status, do not reinterpret as non-EDTO"
            )
        rows.append((f"SECTOR {number}", line))
        etps = [str(value) for value in sector.get("etps") or [] if str(value).strip()]
        etp_count = sector.get("etp_count")
        if etps or etp_count:
            distinct = sorted(set(etps))
            rows.append((
                f"ETPS {number}",
                f"{etp_count or len(etps)} equal-time points"
                + (f" | ACTM {' / '.join(distinct)}" if distinct else ""),
            ))
    if not sectors and classification:
        rows.append((
            "ENTRY / EXIT",
            f"ENTRY ACTM {edto_view.get('entry') or '--.--'} | "
            f"EXIT ACTM {edto_view.get('exit') or '--.--'}",
        ))
    elif not sectors:
        rows.append(("ENTRY / EXIT", "No parsed EDTO sector is held."))
    for airport in edto_view.get("airports") or []:
        identity = f"{airport.get('airport') or '----'}/{airport.get('runway') or '--'}"
        rows.append((
            "EDTO ALTN",
            " | ".join(
                part for part in (
                    identity,
                    str(airport.get("approach") or "").strip(),
                    str(airport.get("period") or "").strip(),
                ) if part
            ),
        ))
    top_up = (((fuel_summary.get("rows") or {}).get("edto_top_up") or {}).get("fuel_kg"))
    rows.append((
        "FUEL",
        "No EDTO top-up or EDTO alternate sector."
        if top_up in (0, None) and classification.startswith("NON")
        else f"EDTO top-up {(top_up or 0):,} kg.",
    ))
    rows.append(("GATE", _edto_gate_sentence(edto_view)))
    return rows



_SIGMET_POINT = re.compile(r"([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})")
_SIGMET_LAYER = re.compile(r"\b(SFC|\d{4,5}FT|FL\d{3})/((?:FL)?\d{3})\b")


def _screening_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    return lon * 60.0 * cos(radians(ref_lat)), lat * 60.0


def _screening_geometry(
    points: list[tuple[float, float]],
    waypoints: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Deterministic route-vs-polygon screening: closest approach to the route
    LINE (legs vs vertices and edges vs fixes) plus the crossing window when
    route legs actually enter the polygon. Local equirectangular frames -
    screening precision, not navigation."""
    held = [
        (float(w["latitude"]), float(w["longitude"]),
         str(w.get("name") or "").lstrip("-"), w.get("actm_minutes"))
        for w in waypoints
        if w.get("latitude") is not None and w.get("longitude") is not None
    ]
    if len(points) < 3 or not held:
        return None

    def seg(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        cx, cy = ax + t * dx, ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5, t

    def inside(lat, lon):
        crossings = 0
        for j in range(len(points)):
            (alat, alon), (blat, blon) = points[j], points[(j + 1) % len(points)]
            if (alat > lat) != (blat > lat):
                lon_cross = alon + (lat - alat) * (blon - alon) / (blat - alat)
                if lon_cross > lon:
                    crossings += 1
        return crossings % 2 == 1

    best: tuple[float, str, float | None] | None = None
    for i in range(len(held) - 1):
        lat1, lon1, name1, actm1 = held[i]
        lat2, lon2, name2, actm2 = held[i + 1]
        ref = (lat1 + lat2) / 2.0
        ax, ay = _screening_xy(lat1, lon1, ref)
        bx, by = _screening_xy(lat2, lon2, ref)
        for (plat, plon) in points:
            px, py = _screening_xy(plat, plon, ref)
            nm, t = seg(px, py, ax, ay, bx, by)
            if best is None or nm < best[0]:
                place = name1 if t <= 0.05 else name2 if t >= 0.95 else f"between {name1} and {name2}"
                passage = (
                    float(actm1) + t * (float(actm2) - float(actm1))
                    if actm1 is not None and actm2 is not None else None
                )
                best = (nm, place if place.startswith("between") else f"near {place}", passage)
    for lat, lon, name, actm in held:
        for j in range(len(points)):
            p1, p2 = points[j], points[(j + 1) % len(points)]
            ax, ay = _screening_xy(p1[0], p1[1], lat)
            bx, by = _screening_xy(p2[0], p2[1], lat)
            px, py = _screening_xy(lat, lon, lat)
            nm, _ = seg(px, py, ax, ay, bx, by)
            if best is None or nm < best[0]:
                best = (nm, f"near {name}", float(actm) if actm is not None else None)
    if best is None:
        return None

    # Crossing window: contiguous run of fixes inside the polygon, expressed
    # in ACTM minutes. Fix-resolution is deliberate: no interpolated entry
    # point is invented between fixes.
    inside_actms = [
        actm for (lat, lon, name, actm) in held
        if actm is not None and inside(lat, lon)
    ]
    crossing = (min(inside_actms), max(inside_actms)) if inside_actms else None

    # Rough cardinal from the route toward the polygon for the no-intersect
    # sentence ("approximately 751 NM south").
    mid_lat = sum(p[0] for p in points) / len(points)
    mid_lon = sum(p[1] for p in points) / len(points)
    route_lat = sum(h[0] for h in held) / len(held)
    route_lon = sum(h[1] for h in held) / len(held)
    d_lat, d_lon = mid_lat - route_lat, mid_lon - route_lon
    if abs(d_lat) >= abs(d_lon):
        bearing = "south" if d_lat < 0 else "north"
    else:
        bearing = "west" if d_lon < 0 else "east"
    return {
        "closest_nm": best[0],
        "closest_place": best[1],
        "closest_passage_actm": best[2],
        "crossing_actm": crossing,
        "bearing": bearing,
    }


def _sigmet_utc(flight: dict[str, Any], ddhhmm: str, near: datetime | None = None) -> datetime | None:
    """A SIGMET ddhhmm resolved against the flight's departure month."""
    raw = str((flight or {}).get("scheduled_departure_utc") or "").replace("Z", "+00:00")
    try:
        base = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", str(ddhhmm or ""))
    if not match:
        return None
    day, hour, minute = (int(g) for g in match.groups())
    anchor = near or base
    candidates = []
    for offset in (-1, 0, 1):
        month_index = base.month - 1 + offset
        year = base.year + month_index // 12
        month = month_index % 12 + 1
        try:
            candidates.append(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))
        except ValueError:
            continue
    return min(candidates, key=lambda item: abs(item - anchor), default=None)


def _clock_from_actm(flight: dict[str, Any], actm: float | None) -> datetime | None:
    raw = str((flight or {}).get("scheduled_departure_utc") or "").replace("Z", "+00:00")
    if actm is None:
        return None
    try:
        base = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(minutes=float(actm))


def _terrain_summary(terrain_events: list[dict[str, Any]]) -> str:
    """One terrain sentence, now naming the window (REV3: 'IMABA 117* to
    HLM 124*, maximum 124* at HLM'). The names come from the same event the
    page renders, so no surface can call it 'event 1' while another names it."""
    if not terrain_events:
        return "No strict MSA >100* window detected"
    spans: list[str] = []
    for event in terrain_events:
        first = event.get("first_high") or {}
        last = event.get("last_high") or {}
        maximum = event.get("maximum") or {}
        first_name = str(first.get("name") or "").lstrip("-")
        last_name = str(last.get("name") or "").lstrip("-")
        if first_name and last_name:
            span = (
                f"{first_name} {first.get('msa_hundreds_ft')}*"
                if first_name == last_name
                else f"{first_name} {first.get('msa_hundreds_ft')}* to "
                     f"{last_name} {last.get('msa_hundreds_ft')}*"
            )
            if maximum.get("name"):
                span += (
                    f", max {maximum.get('msa_hundreds_ft')}* at "
                    f"{str(maximum.get('name') or '').lstrip('-')}"
                )
            spans.append(span)
    label = f"{len(terrain_events)} MSA >100* window{'s' if len(terrain_events) != 1 else ''}"
    if spans:
        label += f" ({'; '.join(spans)})"
    return f"{label}; profile match on the terrain page"


def _weather_coverage_ledger(flight: dict[str, Any]) -> list[dict[str, str]]:
    """Which CFP weather sections carry data, as canon honesty tiles.

    "unavailable" here means the CFP printed no data for the section - a
    source-coverage gap, never a NIL finding (REV3 coverage ledger)."""
    sections = flight.get("weather_section_availability") or {}
    rows = []
    for key, label in (
        ("airmet", "AIRMET"),
        ("tropical_cyclone", "TC SIGMET"),
        ("volcanic_ash", "VA SIGMET"),
    ):
        status = str(sections.get(key) or "").strip()
        if not status:
            held = any(
                record.get("record_type") == {"tropical_cyclone": "TC_SIGMET", "volcanic_ash": "VA_SIGMET"}.get(key)
                for record in flight.get("weather") or []
            ) if key != "airmet" else False
            status = "held" if held else "unavailable"
        rows.append({"label": label, "status": status})
    return rows


def _sigmet_screening_cards(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """One REV3-style verdict card per enroute SIGMET in the CFP.

    Every disposition carries its deterministic reason; a SIGMET whose
    polygon cannot be read gets 'screening unavailable - review required',
    never a NOT PROMOTED it did not earn (boss's REV3 canon, 20 Aug)."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    waypoints = flight.get("route_waypoints") or []
    for record in flight.get("weather") or []:
        if record.get("record_type") != "SIGMET":
            continue
        text = str(record.get("text") or "")
        # A CFP FIR block can print several SIGMETs in one record.
        pieces = re.split(r"(?=\bW[SVC]\s+SIGMET\s+\w+\s+VALID\b)", text)
        for piece in pieces:
            head = re.search(
                r"\b(W[SVC])\s+SIGMET\s+(\w+)\s+VALID\s+(\d{6})/(\d{6})", piece
            )
            if not head:
                continue
            fir = str(record.get("location") or "").strip().upper()
            key = f"{fir}-{head.group(2)}-{head.group(3)}"
            if key in seen:
                continue
            seen.add(key)
            phenomenon = re.search(r"FIR\s+([A-Z][A-Z ]+?)\s+(?:FCST|OBS)\b", piece)
            layer = _SIGMET_LAYER.search(piece)
            movement = re.search(r"\bMOV\s+([NSEW]{1,3})\s+(\d{1,3})\s*KT", piece)
            points = [
                (-(int(m[1]) + int(m[2]) / 60.0) if m[0] == "S" else int(m[1]) + int(m[2]) / 60.0,
                 -(int(m[4]) + int(m[5]) / 60.0) if m[3] == "W" else int(m[4]) + int(m[5]) / 60.0)
                for m in _SIGMET_POINT.findall(piece)
            ]
            geometry = _screening_geometry(points, waypoints)
            valid_from = _sigmet_utc(flight, head.group(3))
            valid_to = _sigmet_utc(flight, head.group(4), near=valid_from)
            name = f"{fir} SIGMET {head.group(2)}"
            if phenomenon:
                name += f" - {phenomenon.group(1).strip()}"
            card: dict[str, Any] = {
                "name": name,
                "fir": fir,
                "sigmet_id": head.group(2),
                "phenomenon": phenomenon.group(1).strip() if phenomenon else None,
                "valid_from": head.group(3),
                "valid_to": head.group(4),
                "layer": f"{layer.group(1)}/{layer.group(2)}" if layer else None,
                "movement": (
                    f"MOV {movement.group(1)} {movement.group(2)}KT" if movement else None
                ),
                "text": " ".join(piece.split()),
            }
            if geometry is None:
                card["disposition"] = "REVIEW REQUIRED"
                card["screening"] = (
                    "No readable polygon in the CFP record - deterministic "
                    "screening unavailable; review the original SIGMET."
                )
                cards.append(card)
                continue
            crossing = geometry["crossing_actm"]
            if crossing is None:
                card["disposition"] = "NOT PROMOTED"
                card["screening"] = (
                    "The filed route does not intersect the polygon. Closest "
                    f"deterministic screening distance is approximately "
                    f"{round(geometry['closest_nm'])} NM {geometry['bearing']}. "
                    "NOT PROMOTED."
                )
                cards.append(card)
                continue
            entry_utc = _clock_from_actm(flight, crossing[0])
            exit_utc = _clock_from_actm(flight, crossing[1])
            window = (
                f"about ACTM {int(crossing[0]) // 60:02d}:{int(crossing[0]) % 60:02d}"
                f"-{int(crossing[1]) // 60:02d}:{int(crossing[1]) % 60:02d}"
            )
            if entry_utc and exit_utc:
                window += f" / {entry_utc:%H%M}-{exit_utc:%H%M}Z"
            if valid_to and entry_utc and valid_to <= entry_utc:
                gap = round((entry_utc - valid_to).total_seconds() / 60.0)
                card["disposition"] = "NOT PROMOTED"
                card["screening"] = (
                    f"The polygon crosses the route {window}, but the product "
                    f"expires {gap} minutes before route entry. NOT PROMOTED."
                )
            elif valid_from and exit_utc and valid_from >= exit_utc:
                gap = round((valid_from - exit_utc).total_seconds() / 60.0)
                card["disposition"] = "NOT PROMOTED"
                card["screening"] = (
                    f"The polygon crosses the route {window}, but the product "
                    f"only becomes valid {gap} minutes after route exit. "
                    "NOT PROMOTED."
                )
            else:
                card["disposition"] = "PROMOTED"
                card["screening"] = (
                    f"The polygon crosses the route {window} inside the "
                    "product's validity. PROMOTED - review required."
                )
            cards.append(card)
    return cards


def _va_official_note(flight: dict[str, Any] | None, volcano: str | None) -> str | None:
    """The held official advisory for this volcano, as one sober sentence.

    Returns None when nothing official is held - the caller then prints the
    honest "confirmation unavailable" caveat. This is what stops the derived
    line contradicting a coverage manifest that says DARWIN: reached."""
    if not flight or not volcano:
        return None
    bare = re.sub(r"^(?:MT|MOUNT)\s+", "", str(volcano).upper()).strip()
    held = (
        ((flight.get("vaa_review") or {}).get("direct_vaac_snapshot") or {}).get("advisories")
    ) or []
    matches = [
        advisory for advisory in held
        if bare and bare in str(advisory.get("volcano") or "").upper()
    ]
    if not matches:
        return None
    latest = max(matches, key=lambda advisory: str(advisory.get("issued_at_utc") or ""))
    centre = str(latest.get("vaac") or latest.get("centre") or "VAAC").strip()
    number = str(latest.get("advisory_number") or "").strip()
    issued = str(latest.get("issued_at_utc") or "")
    stamp = ""
    stamp_match = re.search(r"\d{4}-\d{2}-(\d{2})T(\d{2}):(\d{2})", issued)
    if stamp_match:
        day, hour, minute = stamp_match.groups()
        stamp = f" ({day}/{hour}{minute}Z)"
    remarks = str(latest.get("remarks") or "").upper()
    if "TERMINATED" in remarks or "DISSIPATED" in remarks:
        state = "reports the ash dissipated - advisory terminated"
    else:
        state = "is held for this volcano - see hazard coverage"
    label = f"official {centre} advisory {number}".strip() if number else f"official {centre} advisory"
    return f"{label}{stamp} {state}."


def _va_derived_screening(
    text: str, waypoints: list[dict[str, Any]], profile: str | None,
    flight: dict[str, Any] | None = None,
    official_note: str | None = None,
) -> str | None:
    """Closest-approach screening of the CFP's ash polygon against the route.

    Pure derived facts (distance, layer, planned levels) with the same
    interpolation caveat the cyclone screening carries. Returns None when the
    advisory carries no readable polygon - the card then shows only the named
    advisory and the review status, never an invented distance."""
    cloud = re.search(r"\bWI\s+(.+?)\s+(SFC|FL\d{3})/(FL\d{3})", text)
    if not cloud:
        return None
    points = [
        (-(int(m[1]) + int(m[2]) / 60.0) if m[0] == "S" else int(m[1]) + int(m[2]) / 60.0,
         -(int(m[4]) + int(m[5]) / 60.0) if m[3] == "W" else int(m[4]) + int(m[5]) / 60.0)
        for m in re.findall(r"([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})", cloud.group(1))
    ]
    if len(points) < 3:
        return None
    held = [
        (float(w["latitude"]), float(w["longitude"]),
         str(w.get("name") or "").lstrip("-"), w.get("actm_minutes"))
        for w in waypoints
        if w.get("latitude") is not None and w.get("longitude") is not None
    ]
    if not held:
        return None

    # Closest approach is measured to the route LINE, not only its fixes: the
    # true minimum usually falls between waypoints (18 Aug SQ223: 88 NM on the
    # IKIBU-LEMUS leg vs 90 NM at IKIBU itself). Route legs are checked
    # against every polygon vertex and every polygon edge against every fix,
    # in a local equirectangular frame - screening precision, not navigation.
    def _xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
        return lon * 60.0 * cos(radians(ref_lat)), lat * 60.0

    def _seg(px: float, py: float, ax: float, ay: float,
             bx: float, by: float) -> tuple[float, float]:
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(
            0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq)
        )
        cx, cy = ax + t * dx, ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5, t

    best: tuple[float, str, float | None] | None = None  # nm, place, passage_actm
    for i in range(len(held) - 1):
        lat1, lon1, name1, actm1 = held[i]
        lat2, lon2, name2, actm2 = held[i + 1]
        ref = (lat1 + lat2) / 2.0
        ax, ay = _xy(lat1, lon1, ref)
        bx, by = _xy(lat2, lon2, ref)
        for (plat, plon) in points:
            px, py = _xy(plat, plon, ref)
            nm, t = _seg(px, py, ax, ay, bx, by)
            if best is None or nm < best[0]:
                place = name1 if t <= 0.05 else name2 if t >= 0.95 else f"between {name1} and {name2}"
                passage = (
                    float(actm1) + t * (float(actm2) - float(actm1))
                    if actm1 is not None and actm2 is not None else None
                )
                best = (nm, place if place.startswith("between") else f"near {place}", passage)
    for lat, lon, name, actm in held:
        for j in range(len(points)):
            p1, p2 = points[j], points[(j + 1) % len(points)]
            ax, ay = _xy(p1[0], p1[1], lat)
            bx, by = _xy(p2[0], p2[1], lat)
            px, py = _xy(lat, lon, lat)
            nm, _ = _seg(px, py, ax, ay, bx, by)
            if best is None or nm < best[0]:
                best = (nm, f"near {name}", float(actm) if actm is not None else None)
    if best is None:
        return None
    best_nm, place, passage_actm = best

    # Passage time against the SIGMET's own validity is derived, never
    # asserted beyond the data: both clauses drop out when the CFP does not
    # carry the inputs.
    timing = ""
    valid_to = re.search(r"\bVALID\s+\d{6}/(\d{2})(\d{2})(\d{2})", text)
    departure = None
    raw_departure = str((flight or {}).get("scheduled_departure_utc") or "").replace("Z", "+00:00")
    if raw_departure:
        try:
            departure = datetime.fromisoformat(raw_departure)
            if departure.tzinfo is None:
                departure = departure.replace(tzinfo=timezone.utc)
        except ValueError:
            departure = None
    if passage_actm is not None and departure is not None:
        passage_utc = departure + timedelta(minutes=passage_actm)
        timing = f"; route passes ~{passage_utc:%H%M}Z"
        if valid_to:
            day, hour, minute = (int(g) for g in valid_to.groups())
            candidates = []
            for month_offset in (-1, 0, 1):
                month_index = passage_utc.month - 1 + month_offset
                year = passage_utc.year + month_index // 12
                month = month_index % 12 + 1
                try:
                    candidates.append(passage_utc.replace(
                        year=year, month=month, day=day, hour=hour, minute=minute
                    ))
                except ValueError:
                    continue
            if candidates:
                expiry = min(candidates, key=lambda item: abs(item - passage_utc))
                delta = round((passage_utc - expiry).total_seconds() / 60.0)
                # A validity nowhere near the flight day is bad input, not a
                # sentence: the comparison only prints within a day.
                if abs(delta) <= 24 * 60:
                    timing += (
                        f", {delta} min after the SIGMET's {expiry:%H%M}Z expiry"
                        if delta > 0 else
                        f", inside the SIGMET's validity (to {expiry:%H%M}Z)"
                    )
    layer = f"{cloud.group(2)}/{cloud.group(3)}"
    levels = _cruise_summary(profile)
    tail = official_note or "official VAAC confirmation unavailable."
    return (
        f"Closest approach {round(best_nm)} NM {place}{timing}; ash layer {layer}; "
        f"planned {levels}. ODSS screening of the CFP advisory polygon - {tail}"
    )


def _va_cfp_advisories(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Named volcanic-ash advisories captured verbatim from the CFP.

    The name line is the label the 18 Aug defect was missing: the hazard is
    called VOLCANIC ASH with its volcano and SIGMET identity, never a generic
    "1 CFP advisory"."""
    advisories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in flight.get("weather") or []:
        if record.get("record_type") != "VA_SIGMET":
            continue
        text = str(record.get("text") or "")
        key = " ".join(text.split())
        if key in seen:
            # The CFP prints its wx list twice; one advisory, one card.
            continue
        seen.add(key)
        volcano = re.search(r"VA ERUPTION\s+((?:MT|MOUNT)\s+[A-Z]+)", text)
        sigmet_id = re.search(r"\bWV\s+SIGMET\s+(\w+)", text)
        valid = re.search(r"\bVALID\s+(\d{6})/(\d{6})", text)
        name = " · ".join(part for part in (
            "VOLCANIC ASH",
            volcano.group(1) if volcano else None,
            (
                f"{record.get('location')} WV SIGMET {sigmet_id.group(1)}"
                if sigmet_id else str(record.get("location") or "")
            ) or None,
        ) if part)
        advisories.append({
            "name": name,
            "derived": _va_derived_screening(
                text,
                flight.get("route_waypoints") or [],
                flight.get("planned_level_profile"),
                flight,
                official_note=_va_official_note(
                    flight, volcano.group(1) if volcano else None
                ),
            ),
            "text": text,
            "fir": record.get("location"),
            "valid_from": valid.group(1) if valid else None,
            "valid_to": valid.group(2) if valid else None,
            "source_page": record.get("source_page"),
        })
    return advisories


def build_briefing_view(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    timing_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = prepare_pilot_findings(findings, notam_limit=24)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        grouped[str(item.get("engine") or "other")].append(item)

    route_map = build_route_map(flight)
    waypoints = flight.get("route_waypoints") or []
    terrain_events = detect_terrain_events(waypoints)
    final_actm = max((int(item.get("actm_minutes")) for item in waypoints if item.get("actm_minutes") is not None), default=0)
    firs = [str(item.get("fir_boundary")) for item in waypoints if item.get("fir_boundary")]
    unique_firs = list(dict.fromkeys(firs))
    masses = flight.get("masses") or {}
    fuel = flight.get("fuel") or {}
    alternates = flight.get("alternates") or []

    departure_panel = _airport_panel(
        flight,
        findings,
        str(flight.get("departure") or "----"),
        "departure",
        flight.get("departure_runway"),
    )
    destination_panel = _airport_panel(
        flight,
        findings,
        str(flight.get("destination") or "----"),
        "destination",
        flight.get("destination_runway"),
    )

    critical_airport_notams = [
        item
        for item in findings
        if item.get("engine") == "notam"
        and item.get("severity") == "critical"
        and item.get("data", {}).get("role") in {"departure", "destination", "destination alternate"}
    ]
    weather_warnings = [
        item
        for item in grouped.get("sigmet", []) + grouped.get("vaa", []) + grouped.get("tropical_cyclone", []) + grouped.get("weather", [])
        if item.get("severity") in {"warning", "critical", "unknown"}
    ]
    edto_issues = [item for item in grouped.get("edto", []) if item.get("severity") in {"warning", "critical", "unknown"}]
    communication_items = grouped.get("communications", [])
    other_issues = [
        item
        for engine in (
            "bobcat",
            "mel",
            "cddl",
            "performance",
            "terrain",
            "vws",
            "depressurisation",
            "qa",
        )
        for item in grouped.get(engine, [])
        if item.get("severity") in {"warning", "critical", "unknown"}
    ]
    edto = flight.get("edto") or {}
    edto_assessment = _edto_assessment_view(edto)
    needs_review = bool(
        warnings
        or edto_assessment["status"] == "review_required"
        or any(
            item.get("severity") in {"warning", "critical", "unknown"}
            for item in findings
        )
    )

    edto_needs_review = bool(
        edto_issues or edto_assessment["status"] == "review_required"
    )
    edto_detail = (
        "Applicability review required"
        if edto_needs_review
        else "Verified not applicable"
        if edto_assessment["status"] == "verified_not_applicable"
        else "Checked-period summary available"
    )
    exception_cards = [
        {"label": "Airport restrictions", "count": len(critical_airport_notams), "detail": "Critical departure/destination items", "severity": "critical" if critical_airport_notams else "information"},
        {"label": "Significant weather", "count": len(weather_warnings), "detail": "Operational weather findings", "severity": "warning" if weather_warnings else "information"},
        {"label": "EDTO", "count": len(edto_issues), "detail": edto_detail, "severity": "warning" if edto_needs_review else "information"},
        {"label": "FIR communication", "count": len(communication_items), "detail": "Early contact requirements", "severity": "warning" if communication_items else "information"},
        {"label": "Other reviews", "count": len(other_issues), "detail": "MEL/performance/terrain/profile", "severity": "warning" if other_issues else "information"},
    ]

    edto_airports = [
        {
            "airport": item.get("airport") or "----",
            "runway": item.get("runway") or "--",
            "approach": item.get("approach") or "",
            "period": f"{_display_utc(item.get('period_start_utc'))} - {_display_utc(item.get('period_end_utc'))}",
        }
        for item in edto.get("airports") or []
    ]
    edto_sector_view = [
        {
            "number": sector.get("number", index),
            "entry": format_actm(sector.get("entry_actm_minutes")),
            "exit": format_actm(sector.get("exit_actm_minutes")),
            "etps": [
                format_actm(value)
                for value in (sector.get("etp_actm_minutes") or [])
            ],
            "etp_count": len(sector.get("etps") or sector.get("etp_actm_minutes") or []),
        }
        for index, sector in enumerate(edto_sectors(edto), start=1)
    ]

    edto_view: dict[str, Any] = {
        "assessment": edto_assessment,
        "entry": (
            edto_sector_view[0]["entry"]
            if edto_sector_view
            else format_actm(edto.get("entry_actm_minutes"))
        ),
        "exit": (
            edto_sector_view[0]["exit"]
            if edto_sector_view
            else format_actm(edto.get("exit_actm_minutes"))
        ),
        "etps": (
            edto_sector_view[0]["etps"]
            if edto_sector_view
            else [
                format_actm(value)
                for value in (edto.get("etp_actm_minutes") or [])
            ]
        ),
        "sectors": edto_sector_view,
        "airports": edto_airports,
    }
    # The pilot-readable EDTO rows, composed once. The combined PDF prints
    # them and the dashboard renders them verbatim - neither surface derives
    # its own EDTO story.
    edto_view["operational_rows"] = [
        {"label": label, "value": value}
        for label, value in _edto_operational_rows(
            _edto_classification(flight), edto_view, flight.get("fuel_summary") or {}
        )
    ]

    scheduled_departure = _parse_utc(flight.get("scheduled_departure_utc"))
    scheduled_arrival = _parse_utc(flight.get("scheduled_arrival_utc"))
    generated_at = datetime.now(timezone.utc)
    return {
        "status": "REVIEW REQUIRED" if needs_review else "BRIEFING COMPLETE",
        "status_severity": "warning" if needs_review else "information",
        "generated_at_utc": generated_at.isoformat(),
        "generated_at_display": generated_at.strftime("%d %b %Y %H%MZ").upper(),
        "flight_number": flight.get("flight_number") or "----",
        "registration": _display_registration(flight.get("registration")) or "--",
        "route_label": f"{flight.get('departure') or '----'} → {flight.get('destination') or '----'}",
        "flight_date": flight.get("flight_date") or "--",
        "metrics": {
            "distance": f"{int(flight.get('ground_distance_nm') or 0):,} NM" if flight.get("ground_distance_nm") else "-- NM",
            "eet": format_actm(final_actm),
            "fir_count": len(unique_firs),
            "etd": scheduled_departure.strftime("%d %b %H%MZ").upper() if scheduled_departure else "--",
            "eta": scheduled_arrival.strftime("%d %b %H%MZ").upper() if scheduled_arrival else "--",
            "aircraft": " / ".join(
                value
                for value in (
                    str(flight.get("aircraft_type") or "").strip(),
                    _display_registration(flight.get("registration")),
                )
                if value
            )
            or "--",
            "cruise": _cruise_summary(flight.get("planned_level_profile")),
            "captain": flight.get("captain"),
            "alternate": (alternates[0].get("airport") if alternates else "--"),
            "clock_basis": "ATOT + CFP ACTM" if timing_view else "CFP ACTM only",
            "atot": (
                str(timing_view.get("actual_takeoff_display") or "").strip()
                if timing_view
                else ""
            ),
        },
        "masses": {
            "pzfw": format_kg(masses.get("planned_zfw_kg")),
            "pldw": format_kg(masses.get("planned_landing_weight_kg")),
            "ptow": format_kg(masses.get("planned_takeoff_weight_kg")),
        },
        "fuel": {
            "tanks": format_kg(fuel.get("fuel_in_tanks_kg")),
            "trip": format_kg(fuel.get("trip_fuel_kg")),
            "destination": format_kg(fuel.get("planned_destination_fuel_kg")),
        },
        # Page-1 fuel/weight summary, arithmetic-verified at parse time. The
        # report's "CFP PAGE 1 - FLIGHT PLAN" panel reads this and must render
        # a review flag whenever state is not "verified".
        "fuel_summary": flight.get("fuel_summary"),
        "departure": departure_panel,
        "destination": destination_panel,
        "route_map": route_map,
        "route_svg": render_route_svg(route_map),
        # The one terrain opinion every surface prints. Events come from the
        # ODSS engine over the parsed route; the summary sentence is composed
        # here exactly once so overview, dashboard and PDF cannot disagree.
        "terrain": {
            "events": terrain_events,
            "summary": _terrain_summary(terrain_events),
        },
        "exception_cards": exception_cards,
        "communications": _communication_timeline(findings, timing_view),
        "edto": edto_view,
        "weather_cards": _enroute_weather_cards(findings),
        "sigmet": {
            "status": (flight.get("sigmet_review") or {}).get("status"),
            "page": (
                level2_page("weather_detail")
                if (flight.get("sigmet_review") or {}).get("status")
                in {"affected", "review_required"}
                else None
            ),
        },
        "hazards": {
            "sigmet_cards": _sigmet_screening_cards(flight),
            "coverage_ledger": _weather_coverage_ledger(flight),
        },
        "vaa": {
            "cfp_advisories": _va_cfp_advisories(flight),
            "status": (flight.get("vaa_review") or {}).get("status"),
            "page": (
                level2_page("weather_detail")
                if (flight.get("vaa_review") or {}).get("status")
                in {"affected", "review_required"}
                else None
            ),
        },
        "tropical_cyclone": {
            "status": (flight.get("tropical_cyclone_review") or {}).get("status"),
            "page": (
                level2_page("weather_detail")
                if (flight.get("tropical_cyclone_review") or {}).get("status")
                in {"affected", "review_required"}
                else None
            ),
        },
        "counts": {
            "notams": sum(item.get("engine") == "notam" for item in findings),
            "weather": len(flight.get("weather") or []),
            "warnings": len(warnings),
        },
        "quick_links": [
            {"label": "Analysis overview", "target": "analysis_overview", "page": level2_page("analysis_overview")},
            {"label": "Airport / performance basis", "target": "airport_basis", "page": level2_page("airport_basis")},
            {"label": "Airport / NOTAM detail", "target": "notam_detail", "page": level2_page("notam_detail")},
            {"label": "EDTO analysis", "target": "edto_detail", "page": level2_page("edto_detail")},
            {"label": "Communication plan", "target": "communications_detail", "page": level2_page("communications_detail")},
            {"label": "Terrain / profile matrix", "target": "terrain_detail", "page": level2_page("terrain_detail")},
            {"label": "Weather / VAAC review", "target": "weather_detail", "page": level2_page("weather_detail")},
            *(
                [{"label": "SIGMET review", "target": "sigmet_detail", "page": level2_page("weather_detail")}]
                if (flight.get("sigmet_review") or {}).get("status")
                in {"affected", "review_required"}
                and not (flight.get("sigmet_review") or {}).get(
                    "clean_current_feed_no_match"
                )
                else []
            ),
            *(
                [{"label": "Volcanic ash review", "target": "vaa_detail", "page": level2_page("weather_detail")}]
                if (flight.get("vaa_review") or {}).get("status")
                in {"affected", "review_required"}
                else []
            ),
            *(
                [{"label": "Tropical cyclone review", "target": "tropical_cyclone_detail", "page": level2_page("weather_detail")}]
                if (flight.get("tropical_cyclone_review") or {}).get("status")
                in {"affected", "review_required"}
                else []
            ),
        ],
        "warnings": warnings[:5],
    }


__all__ = [
    "build_briefing_view",
    "build_route_map",
    "draw_route_map_pdf",
    "project_route_map",
    "render_route_svg",
]
