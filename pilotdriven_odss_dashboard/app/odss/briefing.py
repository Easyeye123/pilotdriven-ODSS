from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from math import cos, radians
import re
from typing import Any

from reportlab.lib import colors

from .constants import format_actm, format_kg
from .engines import detect_terrain_events


_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}


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


def _weather_summary(flight: dict[str, Any], location: str) -> dict[str, str]:
    records = _weather_records(flight, location)
    metar = next((record for record in records if record.get("record_type") == "METAR"), None)
    taf = next((record for record in records if record.get("record_type") == "TAF"), None)
    return {
        "primary": _shorten((metar or taf or {}).get("text"), 125) or "No station weather parsed",
        "secondary": _shorten((taf or {}).get("text"), 145) if taf else "",
    }


def _notice_kind(text: str) -> str:
    upper = text.upper()
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


def _airport_panel(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    location: str,
    role: str,
    runway: str | None,
) -> dict[str, Any]:
    weather = _weather_summary(flight, location)
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
    bobcat_name = str((flight.get("bobcat") or {}).get("waypoint") or "").upper()
    terrain_maxima = {
        str(event["maximum"].get("name") or "").upper()
        for event in detect_terrain_events(flight.get("route_waypoints", []))
    }
    for index, point in enumerate(points):
        name = str(point.get("name") or "").upper().lstrip("-")
        if point.get("fir_boundary"):
            priority_indices.add(index)
        if name in {"TOC", "TOD"} or name.startswith(("ENTRY", "EXIT", "**ETP")):
            priority_indices.add(index)
        if bobcat_name and name == bobcat_name:
            priority_indices.add(index)
        if name in terrain_maxima:
            priority_indices.add(index)

    step = max(1, len(points) // 8)
    priority_indices.update(range(0, len(points), step))

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

    return {
        "available": len(points) >= 2,
        "points": points,
        "label_indices": sorted(priority_indices),
        "note": "Schematic route map from CFP coordinates - not for navigation.",
    }


def project_route_map(
    route_map: dict[str, Any],
    width: float,
    height: float,
    padding: float = 28.0,
) -> dict[str, Any]:
    points = route_map.get("points") or []
    if len(points) < 2:
        return {"points": [], "grid": []}

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
    return {"points": projected, "grid": grid}


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
    for grid in projection.get("grid") or []:
        parts.append(
            f'<line x1="{grid["x"]:.1f}" y1="36" x2="{grid["x"]:.1f}" y2="{height - 36}" '
            'stroke="#28425f" stroke-width="1" opacity="0.55"/>'
        )
        parts.append(
            f'<line x1="36" y1="{height - grid["y"]:.1f}" x2="{width - 36}" y2="{height - grid["y"]:.1f}" '
            'stroke="#28425f" stroke-width="1" opacity="0.55"/>'
        )
    parts.append(
        f'<polyline points="{polyline}" fill="none" stroke="#dceeff" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )

    role_colour = {
        "departure": "#4db8ff",
        "destination": "#4db8ff",
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


def draw_route_map_pdf(canvas, route_map: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    projection = project_route_map(route_map, width, height, 18.0)
    points = projection.get("points") or []
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#07111F"))
    canvas.roundRect(x, y, width, height, 6, fill=1, stroke=0)
    if len(points) < 2:
        canvas.setFillColor(colors.HexColor("#93A4B8"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawCentredString(x + width / 2, y + height / 2, "Route coordinates unavailable")
        canvas.restoreState()
        return

    canvas.setStrokeColor(colors.HexColor("#28425F"))
    canvas.setLineWidth(0.4)
    for grid in projection.get("grid") or []:
        canvas.line(x + grid["x"], y + 10, x + grid["x"], y + height - 10)
        canvas.line(x + 10, y + grid["y"], x + width - 10, y + grid["y"])

    canvas.setStrokeColor(colors.HexColor("#DCEEFF"))
    canvas.setLineWidth(1.8)
    path = canvas.beginPath()
    path.moveTo(x + points[0]["x"], y + points[0]["y"])
    for point in points[1:]:
        path.lineTo(x + point["x"], y + point["y"])
    canvas.drawPath(path, stroke=1, fill=0)

    role_colour = {
        "departure": colors.HexColor("#4DB8FF"),
        "destination": colors.HexColor("#4DB8FF"),
        "fir": colors.HexColor("#B38CFF"),
        "bobcat": colors.HexColor("#FFB84D"),
        "terrain": colors.HexColor("#FF7F66"),
        "edto": colors.HexColor("#55D6BE"),
        "route": colors.HexColor("#DCEEFF"),
    }
    canvas.setFont("Helvetica-Bold", 5.8)
    for index, point in enumerate(points):
        px, py = x + point["x"], y + point["y"]
        canvas.setFillColor(role_colour.get(point.get("role"), colors.HexColor("#DCEEFF")))
        radius = 3.2 if point.get("role") in {"departure", "destination"} else 1.9
        canvas.circle(px, py, radius, fill=1, stroke=0)
        if point.get("label"):
            canvas.setFillColor(colors.HexColor("#E8F2FF"))
            label = _shorten(point.get("display_name"), 16)
            if px < x + width * 0.75:
                canvas.drawString(px + 3.5, py + (3.5 if index % 2 == 0 else -7), label)
            else:
                canvas.drawRightString(px - 3.5, py + (3.5 if index % 2 == 0 else -7), label)
    canvas.setFillColor(colors.HexColor("#8396AB"))
    canvas.setFont("Helvetica", 4.8)
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
        [item for item in findings if item.get("engine") == "weather"],
        key=_finding_sort_key,
    )
    cards = []
    for item in weather:
        title = str(item.get("title") or "Weather")
        if any(role in title.lower() for role in ("departure", "destination")) and len(cards) < 2:
            continue
        cards.append({
            "title": _shorten(title, 30),
            "text": _shorten(item.get("summary"), 94),
            "severity": str(item.get("severity") or "information"),
        })
        if len(cards) >= 3:
            break
    if not cards:
        cards.append({"title": "Enroute weather", "text": "No significant enroute weather finding selected.", "severity": "information"})
    return cards


def build_briefing_view(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    timing_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        grouped[str(item.get("engine") or "other")].append(item)

    route_map = build_route_map(flight)
    waypoints = flight.get("route_waypoints") or []
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
    weather_warnings = [item for item in grouped.get("weather", []) if item.get("severity") in {"warning", "critical"}]
    edto_issues = [item for item in grouped.get("edto", []) if item.get("severity") in {"warning", "critical", "unknown"}]
    communication_items = grouped.get("communications", [])
    other_issues = [
        item
        for engine in ("bobcat", "cddl", "qa")
        for item in grouped.get(engine, [])
        if item.get("severity") in {"warning", "critical", "unknown"}
    ]

    exception_cards = [
        {"label": "Airport restrictions", "count": len(critical_airport_notams), "detail": "Critical departure/destination items", "severity": "critical" if critical_airport_notams else "information"},
        {"label": "Significant weather", "count": len(weather_warnings), "detail": "Operational weather findings", "severity": "warning" if weather_warnings else "information"},
        {"label": "EDTO", "count": len(edto_issues), "detail": "Issues requiring review" if edto_issues else "Checked-period summary available", "severity": "warning" if edto_issues else "information"},
        {"label": "FIR communication", "count": len(communication_items), "detail": "Early contact requirements", "severity": "warning" if communication_items else "information"},
        {"label": "Other", "count": len(other_issues), "detail": "MEL/CDL/QA exceptions", "severity": "warning" if other_issues else "information"},
    ]

    edto = flight.get("edto") or {}
    edto_airports = [
        {
            "airport": item.get("airport") or "----",
            "runway": item.get("runway") or "--",
            "approach": item.get("approach") or "",
            "period": f"{_display_utc(item.get('period_start_utc'))} - {_display_utc(item.get('period_end_utc'))}",
        }
        for item in (edto.get("airports") or [])[:4]
    ]

    scheduled_departure = _parse_utc(flight.get("scheduled_departure_utc"))
    scheduled_arrival = _parse_utc(flight.get("scheduled_arrival_utc"))
    generated_at = datetime.now(timezone.utc)
    return {
        "status": "BRIEFING COMPLETE",
        "generated_at_utc": generated_at.isoformat(),
        "generated_at_display": generated_at.strftime("%d %b %Y %H%MZ").upper(),
        "flight_number": flight.get("flight_number") or "----",
        "route_label": f"{flight.get('departure') or '----'} → {flight.get('destination') or '----'}",
        "flight_date": flight.get("flight_date") or "--",
        "metrics": {
            "distance": f"{int(flight.get('ground_distance_nm') or 0):,} NM" if flight.get("ground_distance_nm") else "-- NM",
            "eet": format_actm(final_actm),
            "fir_count": len(unique_firs),
            "etd": scheduled_departure.strftime("%d %b %H%MZ").upper() if scheduled_departure else "--",
            "eta": scheduled_arrival.strftime("%d %b %H%MZ").upper() if scheduled_arrival else "--",
            "aircraft": flight.get("aircraft_type") or "--",
            "cruise": _cruise_summary(flight.get("planned_level_profile")),
            "alternate": (alternates[0].get("airport") if alternates else "--"),
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
        "departure": departure_panel,
        "destination": destination_panel,
        "route_map": route_map,
        "route_svg": render_route_svg(route_map),
        "exception_cards": exception_cards,
        "communications": _communication_timeline(findings, timing_view),
        "edto": {
            "entry": format_actm(edto.get("entry_actm_minutes")),
            "exit": format_actm(edto.get("exit_actm_minutes")),
            "etps": [format_actm(value) for value in (edto.get("etp_actm_minutes") or [])],
            "airports": edto_airports,
        },
        "weather_cards": _enroute_weather_cards(findings),
        "counts": {
            "notams": sum(item.get("engine") == "notam" for item in findings),
            "weather": len(flight.get("weather") or []),
            "warnings": len(warnings),
        },
        "quick_links": [
            {"label": "Operational detail", "target": "operational_detail", "page": 2},
            {"label": "Departure detail", "target": "departure_detail", "page": 2},
            {"label": "Destination detail", "target": "destination_detail", "page": 2},
            {"label": "Route / contingency", "target": "route_contingency", "page": 3},
            {"label": "Communication plan", "target": "communications_detail", "page": 3},
            {"label": "EDTO analysis", "target": "edto_detail", "page": 3},
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
