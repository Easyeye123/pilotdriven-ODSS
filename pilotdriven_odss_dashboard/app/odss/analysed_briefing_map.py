"""Readable report overlay from source polygons and calculated event positions.

The historical audit renderer is unchanged. This map is a publication of held
coordinates: it neither substitutes a web snapshot nor invents hazard areas.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import re

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

from .analysed_briefing_content import cyclone_content, flight_window, level_profile_label
from .briefing import (_SIGMET_TIME_DISPOSITION, _screening_geometry, _sigmet_time_state,
                       _sigmet_utc, _projected_land_segments, project_route_map)
from .vaa import _flight_anchor, _planned_levels, _unwrap, _utc
from .sigmet_geometry import source_layer, source_polygon

_MAP_NOTE = ("VWS: OFP samples. NM: distance from route. "
             "Dashed area: flight applicability not fully verified.")
_EMPTY_HAZARD_KEY = "No mapped hazard geometry is held for this route. Coverage conditions are on the assurance page."


def phenomenon_label(value):
    """Expand held ICAO phenomenon codes without inferring severity."""
    words = str(value or "").upper().replace("_", " ")
    names = {"TS": "Thunderstorms", "TC": "Tropical cyclone", "VA": "Volcanic ash",
             "TURB": "Turbulence", "ICE": "Icing", "MTW": "Mountain waves",
             "DS": "Duststorm", "SS": "Sandstorm"}
    for code, name in names.items():
        if re.search(rf"\b{code}\b", words):
            return ("Severe " + name.lower()) if re.search(r"\bSEV\b", words) else name
    if words in {"VOLCANIC ASH", "TROPICAL CYCLONE"}:
        return words.capitalize()
    return "Weather advisory"


def event_affects_flight(event):
    """Route, time and level all matched: the only state drawn as a solid area."""
    return bool(event.get("level_matched")) and event.get("time_matched") is True \
        and event.get("route_intersects") is True and not event.get("disposition_conflict")


def key_disposition(event):
    """The verdict the printed key line states, in the SIGMET card's vocabulary.

    The card prints PROMOTED / NOT PROMOTED / REVIEW REQUIRED; the key prints
    plain words. This is the mapping back, so a gate can hold the two pages
    of one briefing to the same verdict."""
    if event.get("disposition_conflict"):
        return "UNRESOLVED"
    crosses = event.get("route_intersects")
    if crosses is False:
        return "NOT PROMOTED"
    if crosses is not True:
        return "UNRESOLVED"
    state = event.get("time_state")
    if state is None:
        return "PROMOTED" if event.get("time_matched") else "UNRESOLVED"
    return _SIGMET_TIME_DISPOSITION.get(state, "UNRESOLVED")


def _passage_window(event):
    start, end = _utc(event.get("passage_from_utc")), _utc(event.get("passage_to_utc"))
    return f"{start:%H%M}-{end:%H%M}Z" if start and end else ""


def _relevance_parts(event):
    """Plain words for what the screening established: crossing, validity, level.

    David, 9 Sep 2026: "hazard analysis okay. But not WX ... that is for
    what???" - a SIGMET the route crosses inside its validity and one it
    crosses outside must not read the same, and neither may disagree with the
    SIGMET card's verdict on the same page. A disposition badge is never
    printed here; the words carry the verdict."""
    if event.get("disposition_conflict"):
        return ["held screening verdict and current route geometry disagree; review the SIGMET card"]
    crosses = event.get("route_intersects")
    if crosses is False:
        return ["route does not cross area"]
    if crosses is not True:
        return ["route crossing unresolved"]
    state = event.get("time_state")
    if state is None:
        state = "inside" if event.get("time_matched") else "time_unverified"
    crossing = f"crosses route {_passage_window(event)}".rstrip()
    gap = event.get("gap_minutes")
    if state == "inside":
        parts = [f"{crossing} inside validity"]
    elif state == "expires_before":
        parts = [f"{crossing} outside validity (expired {gap} min before earliest crossing)"]
    elif state == "starts_after":
        parts = [f"{crossing} outside validity (starts {gap} min after latest crossing)"]
    elif state == "overlap":
        parts = [f"{crossing}; validity covers only part of that window; timing unresolved"]
    elif state == "timing_unresolved":
        parts = ["crosses route; crossing time not held"]
    elif state == "validity_unresolved":
        parts = ["crosses route; validity or passage clock not held"]
    else:
        parts = [f"{crossing}; time applicability unverified"]
    layer, planned = event.get("layer_label"), event.get("planned_level_label")
    noun = "top" if event.get("layer_kind") == "top" else "layer"
    if event.get("level_matched") is True and layer and planned:
        parts.append(f"planned {planned} {'below top' if noun == 'top' else 'within layer'} {layer}")
    elif event.get("level_matched") is False and layer and planned:
        parts.append(f"planned {planned} {event.get('level_side') or 'outside'} {noun} {layer}")
    elif "layer_label" in event:
        parts.append("level not verified" if layer else "layer not held")
    if event_affects_flight(event):
        parts.append("affects flight: route/time/level match")
    return parts


def event_description(event):
    parts = [event.get("marker_label") or event["id"],
             event.get("short_label") or event["label"]]
    if event.get("polygon"):
        begin, end = _utc(event.get("valid_from_utc")), _utc(event.get("valid_to_utc"))
        if begin and end:
            parts.append((f"{begin:%d%b %H%M}-{end:%H%MZ}" if begin.date() == end.date()
                          else f"{begin:%d%b %H%MZ}-{end:%d%b %H%MZ}").upper())
        else:
            parts.append("validity not held")
        parts.extend(_relevance_parts(event))
    if event.get("distance_nm") is not None:
        parts.append(f"~{event['distance_nm']:.0f} NM from route")
    return "; ".join(str(part) for part in parts if part)


def _crossing_state(row, screening, begin, end, passage_start, passage_end):
    """Route and time in the SIGMET card's own terms.

    The verdict is read from the card when it holds one (``route_intersection``
    marks a card screened by the current REV3 rules), and derived by the same
    shared decision otherwise, so the key and the card cannot part ways. A
    held verdict the current geometry contradicts is published as a
    disagreement, never silently resolved either way."""
    crosses = screening["route_intersects"]
    if crosses is not True:
        state, gap = None, None
    elif screening.get("crossing_actm") is None:
        state, gap = "timing_unresolved", None
    else:
        state, gap = _sigmet_time_state(begin, end, passage_start, passage_end)
    derived = ("NOT PROMOTED" if crosses is False
               else "UNRESOLVED" if state == "timing_unresolved"
               else _SIGMET_TIME_DISPOSITION[state])
    held = row.get("disposition") if row.get("route_intersection") else None
    result = {"route_intersects": crosses, "time_state": state, "time_matched": state == "inside",
              "gap_minutes": gap,
              "passage_from_utc": passage_start.isoformat() if passage_start else None,
              "passage_to_utc": passage_end.isoformat() if passage_end else None,
              "disposition": held or derived}
    if held and held != derived:
        result["disposition_conflict"] = True
    return result


def _level_state(flight, screening, row):
    """Planned level against the SIGMET's layer: held facts, never a downgrade.

    The layer comes from the SIGMET text (a top alone only for surface-based
    phenomena) and the level from the OFP's planned profile over the crossing
    legs, widened by one fix so a step climb at the crossing is inside the
    band. "Inside" is conservative. "Outside" is asserted only for a crossing
    between the held TOC and TOD: in the climb or descent the planned cruise
    level says nothing about the level at the crossing, and the state stays
    unverified."""
    layer = source_layer(row.get("text"), row.get("phenomenon"))
    result = {"level_matched": None, "layer_label": layer["label"] if layer else None,
              "layer_kind": layer["kind"] if layer else None, "planned_level_label": None}
    waypoints = flight.get("route_waypoints") or []
    legs = screening.get("crossing_leg_indexes") or []
    if not layer or screening.get("route_intersects") is not True or not legs or not waypoints:
        return result
    levels, unresolved = _planned_levels(waypoints, flight.get("planned_level_profile"))
    if unresolved:
        return result
    first, last = max(0, min(legs) - 1), min(len(waypoints) - 1, max(legs) + 1)
    band = levels[first:last + 1]
    if not band or any(level is None for level in band):
        return result
    low, high = min(band), max(band)
    result["planned_level_label"] = f"FL{low:03d}" if low == high else f"FL{low:03d}-FL{high:03d}"
    lower, upper = layer["lower_ft"], layer["upper_ft"]
    if (upper is None or low * 100 <= upper) and (lower is None or high * 100 >= lower):
        result["level_matched"] = True
        return result
    names = [str(point.get("name") or "").lstrip("-").upper() for point in waypoints]
    if "TOC" not in names or "TOD" not in names:
        return result
    if min(legs) < names.index("TOC") or max(legs) + 1 > names.index("TOD"):
        return result
    result["level_matched"] = False
    result["level_side"] = "above" if upper is not None and low * 100 > upper else "below"
    return result


def build_publication_map(flight, view):
    route = deepcopy(view.get("route_map") or {})
    # A server snapshot may only contain the route. Compose every layer from
    # the same held input instead of trusting an opaque image as an overlay.
    route.pop("snapshot_path", None)
    matched_features = route.pop("hazard_features", [])
    events = []
    rows = [r for r in (view.get("vaa") or {}).get("cfp_advisories") or [] if r.get("advisory_kind") == "VA_SIGMET"]
    rows += (view.get("hazards") or {}).get("sigmet_cards") or []
    seen = set()
    for row in rows:
        polygon = source_polygon(row.get("text"))
        key = (tuple(polygon), row.get("source_id") or row.get("name"), row.get("valid_from"), row.get("valid_to"))
        if not polygon or key in seen:
            continue
        seen.add(key)
        screening = _screening_geometry(polygon, flight.get("route_waypoints") or [])
        if not screening:
            continue
        anchor = _flight_anchor(flight)
        actm = screening.get("closest_passage_actm")
        when = anchor + timedelta(minutes=actm) if anchor and actm is not None else None
        begin = _sigmet_utc(flight, str(row.get("valid_from") or ""))
        end = _sigmet_utc(flight, str(row.get("valid_to") or ""), near=begin)
        crossing = screening.get("crossing_actm")
        passage_start = anchor + timedelta(minutes=crossing[0]) if anchor and crossing else None
        passage_end = anchor + timedelta(minutes=crossing[1]) if anchor and crossing else None
        kind = "VA" if row.get("advisory_kind") == "VA_SIGMET" else "WX"
        label = row.get("volcano") or row.get("name") or kind
        if kind == "VA":
            label = f"{label} SIGMET ash area"
        event = {"kind": kind, "label": str(label), "polygon": polygon,
                 "phenomenon_label": "Volcanic ash" if kind == "VA" else phenomenon_label(row.get("phenomenon")),
                 "short_label": (f"{row.get('fir', '?')}/{row.get('sigmet_id', '?')}" if kind == "WX" else str(label)),
                 # The legacy fix/vertex distance is not area-to-route
                 # distance when a leg crosses between outside fixes.
                 # Do not publish it as a distance from this hazard area.
                 "position": {"latitude": sum(p[0] for p in polygon) / len(polygon), "longitude": sum(p[1] for p in polygon) / len(polygon)},
                 "time_utc": when.isoformat() if when else None,
                 "valid_from_utc": begin.isoformat() if begin else None,
                 "valid_to_utc": end.isoformat() if end else None,
                 "source_id": row.get("source_id") or row.get("name"),
                 "place": screening["closest_place"]}
        # Geometry is explicit even when ACTM is unavailable; route and time
        # are stated in the SIGMET card's terms and read from its verdict.
        event.update(_crossing_state(row, screening, begin, end, passage_start, passage_end))
        # Level from the SIGMET's own layer and the OFP's planned profile.
        event.update(_level_state(flight, screening, row))
        events.append(event)
    # Preserve the existing live matcher output as well as the held CFP
    # polygons. These features already passed route/time/level screening.
    # Keep holes and multipolygon parts instead of filling an invented area.
    start, end = flight_window(flight)
    for feature in matched_features:
        properties = feature.get("properties") or {}
        begin, finish = _utc(properties.get("valid_from_utc")), _utc(properties.get("valid_to_utc"))
        if not (start and end and begin and finish and start <= finish and begin <= end
                and properties.get("hazard_state") == "affecting"):
            continue
        geometry = feature.get("geometry") or {}
        from shapely.geometry import shape
        try:
            area = shape(geometry)
            if not area.is_valid or area.is_empty or area.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("Invalid matched hazard area")
            parts = list(area.geoms) if area.geom_type == "MultiPolygon" else [area]
            kind = {"volcanic_ash": "VA", "tropical_cyclone": "TC"}.get(properties.get("hazard"), "WX")
            for part in parts:
                rings = [[(lat, lon) for lon, lat in ring.coords] for ring in [part.exterior, *part.interiors]]
                if any(abs(lat) > 90 or abs(lon) > 180 for ring in rings for lat, lon in ring):
                    raise ValueError("Invalid matched hazard coordinates")
                position = part.representative_point()
                source_id = str(properties.get("advisory_id") or feature.get("id") or "held advisory")
                events.append({"kind": kind, "label": source_id, "short_label": source_id,
                               "phenomenon_label": phenomenon_label(properties.get("hazard_code") or properties.get("hazard")),
                               "valid_from_utc": begin.isoformat(), "valid_to_utc": finish.isoformat(),
                               "polygon": rings[0], "rings": rings,
                               "position": {"latitude": position.y, "longitude": position.x},
                               "time_matched": True, "level_matched": True,
                               "route_intersects": True, "source_id": source_id})
        except (TypeError, ValueError) as exc:
            raise ValueError("Matched route hazard has no valid publication geometry") from exc
    # Existing VWS threshold and grouping, not a new threshold from REV1.
    vws = (view.get("terrain") or {}).get("vws_review") or {}
    from .engines import detect_vws_events
    for event in detect_vws_events(flight.get("route_waypoints") or []):
        first, last, maximum = (event[k] for k in ("first_high", "last_high", "maximum"))
        if maximum.get("latitude") is None or maximum.get("longitude") is None:
            continue
        sample_label = (f"{first['name']} sample" if first['name'] == last['name']
                        else f"{first['name']}-{last['name']} samples")
        events.append({"kind": "VWS", "label": f"{sample_label}; max {maximum['vws']:03d}",
                       "position": maximum, "source_id": "ofp-vws:" + str(maximum['name']),
                       "time_matched": True})
    events.extend(cyclone_content(flight)["markers"])
    for i, event in enumerate(events, 1):
        event["id"] = f"{event['kind']}{i}"
        event["marker_label"] = f"{event.get('phenomenon_label') or {'VA':'Volcanic ash','TC':'Cyclone','VWS':'VWS'}.get(event['kind'], 'Weather advisory')} {i}"
    route["publication_events"] = events
    route["level_profile"] = level_profile_label(flight)
    route["vws_summary"] = vws.get("summary")
    return route


def publication_key_width(route, width, height):
    """Fit complete descriptions before projection; retain a usable map width."""
    from .operational_format import wrap
    # Reserve the off-frame suffix before projection so a wider key cannot
    # cause a newly off-frame event to overflow. Font size and content stay fixed.
    descriptions = [event_description(event) + "; off frame."
                    for event in route.get("publication_events") or []] or [_EMPTY_HAZARD_KEY]
    maximum = width - 12 - 320
    candidates = [246.0]
    while candidates[-1] + 16 < maximum:
        candidates.append(candidates[-1] + 16)
    if maximum > candidates[-1]:
        candidates.append(maximum)
    # Match the key header, map footer and bottom inset used below; retaining
    # a full final line advance leaves a little additional baseline clearance.
    available_height = height - 31 - 37 - 8
    for key_width in candidates:
        required = sum(len(wrap(value, key_width - 10, size=9)) * 11 + 3
                       for value in descriptions)
        if key_width <= maximum and required <= available_height:
            return key_width
    raise ValueError("Route hazard key exceeds readable capacity")


def publication_key_entries(route):
    """Readable hazard descriptions in plotted order, with their mark colour."""
    palette = {"VA": "#FFBC38", "WX": "#EB83D9", "TC": "#FF5267", "VWS": "#50D5EF"}
    entries = [(event_description(event) + ".", colors.HexColor(palette[event["kind"]]))
               for event in route.get("publication_events") or []]
    return entries or [(_EMPTY_HAZARD_KEY, colors.HexColor("#B1C0CD"))]


# The schematic keeps at least this much height for the route itself; the
# footer may take the rest. Four lines was the flat limit while the page-1
# station cards were short; since 23 Sep 2026 they print the full METAR / TAF
# records, so the row - and the map beside it - can be much taller, and page 1
# then gives the stations the widest grid, which narrows the map and wraps its
# footer onto a fifth line (SQ214 PER-SIN of 19 Aug: a 244-character departure
# TAF). A taller map has the room; a short one keeps the old four-line limit.
MAP_PLOT_MIN_HEIGHT = 140.0


def map_footer_line_limit(height, leading=11.0):
    """Footer lines the map at ``height`` can carry above ``MAP_PLOT_MIN_HEIGHT``."""
    return max(4, int((float(height) - MAP_PLOT_MIN_HEIGHT - 4) // leading))


# The footer's type ladder: its published size first, two readable steps down
# for a narrow map, never smaller. SQ214 PER-SIN of 19 Aug: at 198 pt the note
# and a seven-waypoint level profile wrap to six lines at 9 pt and to four at
# 8 pt; the 8 pt footer keeps the route schematic its full height.
MAP_FOOTER_LADDER = ((9.0, 11.0), (8.5, 10.5), (8.0, 10.0))


def map_footer_layout(route, width, height):
    """``(size, leading, lines)`` for the map footer at this box, or ValueError.

    The largest size on the ladder whose wrapped lines fit the map's line limit
    wins; the footer text itself is never cut or reworded.
    """
    from .operational_format import wrap
    profile = "Level profile: " + str(route.get("level_profile") or "not held")
    for size, leading in MAP_FOOTER_LADDER:
        lines = wrap(_MAP_NOTE, width - 10, size=size) + wrap(profile, width - 10, size=size)
        if len(lines) <= map_footer_line_limit(height, leading):
            return size, leading, lines
    raise ValueError("Route map footer exceeds readable capacity")


def draw_publication_map(canvas, route, x, y, width, height, *, show_key=True):
    from .operational_format import wrap
    # Reserve a right-hand key so annotations never obscure dense waypoint
    # labels or disappear because of a label-placement heuristic. The
    # overview map publishes its key on the weather / route hazards page, so
    # the schematic itself can use the full width between the two stations.
    key_width = publication_key_width(route, width, height) if show_key else 0.0
    map_width = width - key_width - 12 if show_key else width - 6
    # Measure the footer caption before projecting: a narrower schematic wraps
    # it onto a second line and must not write over the neighbouring column.
    footer_size, footer_leading, footer = map_footer_layout(route, width, height)
    footer_height = footer_leading * len(footer) + 4
    plot_height = height - footer_height
    projection = project_route_map(route, map_width, plot_height, 20)
    points, frame = projection.get("points") or [], projection.get("frame") or {}
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#07111F"))
    canvas.roundRect(x, y, width, height, 6, fill=1, stroke=0)
    if len(points) < 2:
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 10.5)
        canvas.drawString(x + 10, y + height / 2, "Route coordinates unavailable")
        canvas.restoreState()
        return
    bottom = y + footer_height
    def xy(position):
        lon = _unwrap(float(position["longitude"]), frame["center_longitude"])
        return (x + frame["offset_x"] + (lon * frame["longitude_factor"] - frame["min_x"]) * frame["scale"],
                bottom + frame["offset_y"] + (float(position["latitude"]) - frame["min_y"]) * frame["scale"])
    clip = canvas.beginPath()
    clip.rect(x, bottom, map_width, plot_height)
    canvas.saveState()
    canvas.clipPath(clip, stroke=0, fill=0)
    canvas.setFillColor(colors.HexColor("#153044"))
    canvas.setStrokeColor(colors.HexColor("#42647B"))
    canvas.setLineWidth(.4)
    for segment in _projected_land_segments(projection):
        path = canvas.beginPath()
        path.moveTo(x + segment[0][0], bottom + segment[0][1])
        for px, py in segment[1:]:
            path.lineTo(x + px, bottom + py)
        path.close()
        canvas.drawPath(path, stroke=1, fill=1)
    palette = {"VA": "#FFBC38", "WX": "#EB83D9", "TC": "#FF5267", "VWS": "#50D5EF"}
    for event in route.get("publication_events") or []:
        polygon = event.get("polygon")
        if not polygon:
            continue
        canvas.setStrokeColor(colors.HexColor(palette[event["kind"]]))
        canvas.setFillColor(colors.Color(1, .7, .2, alpha=.25))
        # Solid only when route, time and level all matched: a level match
        # alone must not draw a crossing outside validity as an applicable area.
        canvas.setDash([] if event_affects_flight(event) else [3, 2])
        path = canvas.beginPath()
        for ring in event.get("rings") or [polygon]:
            path.moveTo(*xy({"latitude": ring[0][0], "longitude": ring[0][1]}))
            for lat, lon in ring[1:]:
                path.lineTo(*xy({"latitude": lat, "longitude": lon}))
            path.close()
        canvas.drawPath(path, fill=1, stroke=1, fillMode=0)
    canvas.setDash([])
    canvas.setStrokeColor(colors.HexColor("#DCEEFF"))
    canvas.setLineWidth(1.6)
    path = canvas.beginPath()
    path.moveTo(x + points[0]["x"], bottom + points[0]["y"])
    for point in points[1:]:
        path.lineTo(x + point["x"], bottom + point["y"])
    canvas.drawPath(path)
    canvas.restoreState()
    # Explicit IDs join the plotted evidence and the readable map key.
    occupied = []
    for event in route.get("publication_events") or []:
        px, py = xy(event["position"])
        occupied.append((px-4, py-4, px+4, py+4))
    entries = []
    def label(px, py, value, colour):
        tw = stringWidth(value, "Helvetica-Bold", 9)
        anchors = [(6, 6), (6, -14), (-tw - 6, 6), (-tw - 6, -14)]
        anchors += [(dx, dy) for step in range(1, 8) for dy in (step * 16 + 6, -step * 16 - 6) for dx in (6, -tw - 6, step * 18, -tw - step * 18)]
        for dx, dy in anchors:
            left, base = px + dx, py + dy
            box = (left - 2, base - 3, left + tw + 2, base + 10)
            if not (x + 2 <= box[0] and box[2] <= x + map_width - 2 and bottom + 2 <= box[1] and box[3] <= y + height - 2):
                continue
            if any(box[0] < r[2] and box[2] > r[0] and box[1] < r[3] and box[3] > r[1] for r in occupied):
                continue
            canvas.setStrokeColor(colour)
            canvas.setLineWidth(.4)
            canvas.line(px, py, left if dx > 0 else left + tw, base + 3)
            canvas.setFillColor(colors.HexColor("#07111F"))
            canvas.rect(box[0], box[1], box[2]-box[0], box[3]-box[1], fill=1, stroke=0)
            canvas.setFillColor(colour)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(left, base, value)
            occupied.append(box)
            return True
        return False
    for point in [points[0], points[-1]]:
        px, py = x + point["x"], bottom + point["y"]
        canvas.setFillColor(colors.white)
        canvas.circle(px, py, 3, fill=1, stroke=0)
        if not label(px, py, point["display_name"], colors.white):
            raise ValueError("Route endpoint has no readable label")
    for event in route.get("publication_events") or []:
        px, py = xy(event["position"])
        colour = colors.HexColor(palette[event["kind"]])
        visible = x + 4 <= px <= x + map_width - 4 and bottom + 4 <= py <= y + height - 4
        if visible:
            canvas.setFillColor(colour)
            canvas.circle(px, py, 3.5, fill=1, stroke=0)
            if not label(px, py, event.get("marker_label") or event["id"], colour):
                raise ValueError(f"Hazard marker has no readable label: {event['id']}")
        description = event_description(event)
        if not visible:
            description += "; off frame"
        entries.append((description + ".", colour))
    # Label source fixes only after every hazard and endpoint has a home.
    for point in points[1:-1]:
        if point.get("label"):
            label(x + point["x"], bottom + point["y"], str(point["display_name"]), colors.HexColor("#B1C0CD"))
    if not show_key:
        entries = []
    canvas.setFont("Helvetica-Bold", 10)
    canvas.setFillColor(colors.HexColor("#50D5EF"))
    kx, ky = x + map_width + 14, y + height - 14
    if show_key:
        canvas.drawString(kx, ky, "FLIGHT HAZARD KEY")
    ky -= 17
    if not entries and show_key:
        entries = [(_EMPTY_HAZARD_KEY, colors.HexColor("#B1C0CD"))]
    for value, colour in entries:
        lines = wrap(value, key_width - 10, size=9)
        canvas.setFillColor(colour)
        canvas.setFont("Helvetica", 9)
        for line in lines:
            if ky < bottom + 8:
                raise ValueError("Route hazard key exceeds readable capacity")
            canvas.drawString(kx, ky, line)
            ky -= 11
        ky -= 3
    canvas.setFont("Helvetica", footer_size)
    canvas.setFillColor(colors.HexColor("#B1C0CD"))
    baseline = y + 2 + footer_leading * (len(footer) - 1)
    for line in footer:
        canvas.drawString(x + 5, baseline, line)
        baseline -= footer_leading
    canvas.restoreState()
