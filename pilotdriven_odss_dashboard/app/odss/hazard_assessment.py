from __future__ import annotations

"""Deterministic meteorological hazard assessment and publication gate.

This module decides whether an official weather product deserves a Level 1
highlight.  It is intentionally conservative:

* a hazard name, FIR, front, jet stream, storm name, or proximity alone is not
  enough;
* Level 1 requires authoritative evidence, time relevance, route/airport
  applicability, vertical relevance when applicable, and an operational
  consequence;
* missing source coverage is recorded as a coverage gap, never converted to
  either a hazard or a NIL finding; and
* non-applicable products are retained in the audit result with the suppression
  reason rather than displayed to the pilot.

The browser and LLM layers must consume this result.  They must not reproduce
or override the gate.
"""

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.validation import make_valid

from .vaa import _planned_levels


GATE_VERSION = "1.0.0"
PROMOTE_LEVEL1 = "promote_level1"
MONITOR_LEVEL2 = "monitor_level2"
SUPPRESS = "suppress"
COVERAGE_GAP = "coverage_gap"

# These phenomena may be highlighted only after the route/time/level or
# airport-operating-window tests pass.  The gate itself uses amber; red remains
# reserved for a separately verified limit violation, airport unavailability,
# or unavailable avoidance margin.
_LEVEL1_PHENOMENA = {
    "embedded_thunderstorm",
    "obscured_thunderstorm",
    "frequent_thunderstorm",
    "squall_line_thunderstorm",
    "severe_thunderstorm",
    "tropical_cyclone",
    "volcanic_ash",
    "severe_turbulence",
    "severe_clear_air_turbulence",
    "severe_icing",
    "severe_mountain_wave",
    "heavy_duststorm",
    "heavy_sandstorm",
    "radioactive_cloud",
}

# Moderate WAFS/AIRMET hazards are retained for Level 2 by default.  They can
# be promoted only by a separate operator rule or verified operational limit.
_LEVEL2_DEFAULT_PHENOMENA = {
    "moderate_turbulence",
    "moderate_clear_air_turbulence",
    "moderate_icing",
    "mountain_wave",
}

_OPERATIONAL_EFFECTS = {
    "route_intersection",
    "planned_level_overlap",
    "runway_or_approach_unavailable",
    "below_published_minima",
    "wind_limit_exceeded",
    "low_level_wind_shear",
    "microburst",
    "freezing_precipitation",
    "airport_closure",
    "edto_suitability_conflict",
    "diversion_corridor_intersection",
    "company_promotion_rule",
}

_COORDINATE = re.compile(r"([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})")
_SIGMET_START = re.compile(
    r"^(?:[A-Z]{2}\s+)?SIGMET\s+(?P<identifier>[A-Z0-9]+)\s+VALID\s+"
    r"(?P<start>\d{6})/(?P<end>\d{6})\s+(?P<mwo>[A-Z]{4})-?\s*(?P<tail>.*)$",
    re.IGNORECASE,
)
_FIR_HEADER = re.compile(r"^(?P<fir>[A-Z]{4})\s+.+\bFIR\b\s*$", re.IGNORECASE)


def _utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start <= second_end and second_start <= first_end


def _resolve_ddhhmm(token: str, reference: datetime, *, prefer_after: bool = False) -> datetime | None:
    """Resolve an ICAO DDHHMM group near a known flight date."""
    if not re.fullmatch(r"\d{6}", token):
        return None
    day = int(token[:2])
    hour = int(token[2:4])
    minute = int(token[4:])
    if hour > 23 or minute > 59:
        return None
    candidates: list[datetime] = []
    for delta in range(-35, 36):
        date_value = (reference + timedelta(days=delta)).date()
        if date_value.day != day:
            continue
        candidates.append(
            datetime(
                date_value.year,
                date_value.month,
                date_value.day,
                hour,
                minute,
                tzinfo=timezone.utc,
            )
        )
    if not candidates:
        return None
    if prefer_after:
        after = [item for item in candidates if item >= reference]
        if after:
            return min(after)
    return min(candidates, key=lambda item: abs((item - reference).total_seconds()))


def _weather_pages(pages: list[str]) -> list[tuple[int, str]]:
    start = next((index for index, text in enumerate(pages) if "AIRPORT WX LIST" in text.upper()), None)
    if start is None:
        return []
    end = next(
        (index for index in range(start, len(pages)) if "AIRPORTLIST ENDED" in pages[index].upper()),
        min(start + 14, len(pages) - 1),
    )
    return [(index + 1, pages[index]) for index in range(start, end + 1)]


def _section_text(
    pages: list[tuple[int, str]],
    heading: str,
    stop_headings: tuple[str, ...],
) -> str:
    text = "\n".join(page for _, page in pages)
    match = re.search(rf"(?im)^{re.escape(heading)}\s*$", text)
    if not match:
        return ""
    tail = text[match.end():]
    stop_positions = [
        found.start()
        for stop in stop_headings
        if (found := re.search(rf"(?im)^{re.escape(stop)}\s*$", tail))
    ]
    return tail[: min(stop_positions)] if stop_positions else tail


def _source_status(section: str) -> str:
    normalized = " ".join(section.split()).upper()
    if not normalized:
        return "not_present"
    if re.search(r"\bNO\s+(?:WX|WEATHER)\s+DATA\s+AVAILABLE\b", normalized):
        return "unavailable"
    return "present"


def _hazard_type(raw_text: str) -> str:
    upper = " ".join(raw_text.upper().split())
    if re.search(r"\b(?:EMBD|EMBEDDED)\s+TS\b", upper):
        return "embedded_thunderstorm"
    if re.search(r"\b(?:OBSC|OBSCURED)\s+TS\b", upper):
        return "obscured_thunderstorm"
    if re.search(r"\b(?:FRQ|FREQUENT)\s+TS\b", upper):
        return "frequent_thunderstorm"
    if re.search(r"\b(?:SQL|SQUALL\s+LINE)\s+TS\b", upper):
        return "squall_line_thunderstorm"
    if re.search(r"\bSEV(?:ERE)?\s+TS\b", upper):
        return "severe_thunderstorm"
    if re.search(r"\b(?:SEV(?:ERE)?\s+CAT|SEV(?:ERE)?\s+CLEAR\s+AIR\s+TURB)", upper):
        return "severe_clear_air_turbulence"
    if re.search(r"\bSEV(?:ERE)?\s+TURB", upper):
        return "severe_turbulence"
    if re.search(r"\b(?:MOD(?:ERATE)?\s+CAT|MOD(?:ERATE)?\s+CLEAR\s+AIR\s+TURB)", upper):
        return "moderate_clear_air_turbulence"
    if re.search(r"\bMOD(?:ERATE)?\s+TURB", upper):
        return "moderate_turbulence"
    if re.search(r"\bSEV(?:ERE)?\s+ICE", upper):
        return "severe_icing"
    if re.search(r"\bMOD(?:ERATE)?\s+ICE", upper):
        return "moderate_icing"
    if re.search(r"\bSEV(?:ERE)?\s+MTW\b", upper):
        return "severe_mountain_wave"
    if re.search(r"\b(?:TC|TROPICAL\s+CYCLONE)\b", upper):
        return "tropical_cyclone"
    if re.search(r"\b(?:VA|VOLCANIC\s+ASH)\b", upper):
        return "volcanic_ash"
    if re.search(r"\bHVY\s+DS\b|\bHEAVY\s+DUST", upper):
        return "heavy_duststorm"
    if re.search(r"\bHVY\s+SS\b|\bHEAVY\s+SAND", upper):
        return "heavy_sandstorm"
    if re.search(r"\bRDOACT\s+CLD\b|\bRADIOACTIVE\s+CLOUD", upper):
        return "radioactive_cloud"
    if re.search(r"\bTS(?:RA)?\b|\bCB\b", upper):
        # An unqualified thunderstorm remains a Level 2 candidate until the
        # official severe/embedded/frequent/squall-line characteristic is known.
        return "thunderstorm"
    return "sigmet_other"


def _vertical_limits(raw_text: str, hazard_type: str) -> tuple[int | None, int | None]:
    upper = " ".join(raw_text.upper().split())
    layer = re.search(r"\b(?:BTN|BETWEEN)\s+FL(\d{2,3})\s+(?:AND|/)\s+FL?(\d{2,3})\b", upper)
    if layer:
        values = sorted((int(layer.group(1)), int(layer.group(2))))
        return values[0], values[1]
    layer = re.search(r"\bFL(\d{2,3})\s*/\s*FL?(\d{2,3})\b", upper)
    if layer:
        values = sorted((int(layer.group(1)), int(layer.group(2))))
        return values[0], values[1]
    top = re.search(r"\bTOP\s+(?:ABV\s+)?FL(\d{2,3})\b", upper)
    if top:
        lower = 0 if "thunderstorm" in hazard_type or hazard_type in {"tropical_cyclone", "volcanic_ash"} else None
        return lower, int(top.group(1))
    return (0, None) if "thunderstorm" in hazard_type else (None, None)


def _polygon(raw_text: str) -> dict[str, Any] | None:
    upper = " ".join(raw_text.upper().split())
    # Only a closed "WI ..." polygon is treated as structured geometry.  Line,
    # quadrant and radial descriptions remain Level 2 until a trusted parser
    # resolves their semantics.
    match = re.search(r"\bWI\s+(?P<body>.*?)(?=\s+TOP\b|\s+MOV\b|\s+STNR\b|\s+NC\b|\s+WKN\b|\s+INTSF\b|$)", upper)
    if not match:
        return None
    ring: list[list[float]] = []
    for coordinate in _COORDINATE.finditer(match.group("body")):
        latitude = int(coordinate.group(2)) + int(coordinate.group(3)) / 60
        longitude = int(coordinate.group(5)) + int(coordinate.group(6)) / 60
        if coordinate.group(1) == "S":
            latitude *= -1
        if coordinate.group(4) == "W":
            longitude *= -1
        ring.append([longitude, latitude])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    try:
        candidate = make_valid(Polygon(ring))
    except (TypeError, ValueError):
        return None
    if candidate.is_empty:
        return None
    # Keep the original ring because this parser intentionally accepts only a
    # single simple SIGMET polygon.
    return {"type": "Polygon", "coordinates": [ring]}


def extract_embedded_sigmets(pages: list[str], flight: dict[str, Any]) -> list[dict[str, Any]]:
    weather_pages = _weather_pages(pages)
    section = _section_text(
        weather_pages,
        "SIGMETs:",
        ("Tropical Cyclone SIGMETs:", "Volcanic Ash SIGMETs:", "DESTINATION AIRPORT:"),
    )
    if not section or _source_status(section) != "present":
        return []
    departure = _utc(flight.get("scheduled_departure_utc"))
    if departure is None:
        return []

    records: list[dict[str, Any]] = []
    current_fir: str | None = None
    current: dict[str, Any] | None = None

    def source_page(identifier: str, start_group: str) -> int | None:
        needle = re.compile(rf"SIGMET\s+{re.escape(identifier)}\s+VALID\s+{re.escape(start_group)}", re.IGNORECASE)
        return next((number for number, page in weather_pages if needle.search(page)), None)

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        raw_text = " ".join(current.pop("raw_lines")).strip()
        hazard_type = _hazard_type(raw_text)
        lower, upper = _vertical_limits(raw_text, hazard_type)
        current.update(
            raw_text=raw_text,
            hazard_type=hazard_type,
            lower_flight_level=lower,
            upper_flight_level=upper,
            geometry=_polygon(raw_text),
        )
        records.append(current)
        current = None

    for raw_line in section.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        fir_match = _FIR_HEADER.match(line)
        if fir_match and not _SIGMET_START.match(line):
            flush()
            current_fir = fir_match.group("fir").upper()
            continue
        start_match = _SIGMET_START.match(line)
        if start_match:
            flush()
            start = _resolve_ddhhmm(start_match.group("start"), departure)
            end = _resolve_ddhhmm(
                start_match.group("end"),
                start or departure,
                prefer_after=True,
            )
            if start and end and end < start:
                end += timedelta(days=1)
            identifier = start_match.group("identifier").upper()
            current = {
                "source_class": "official_sigmet",
                "authority": start_match.group("mwo").upper(),
                "product_id": f"{current_fir or 'FIR'}-{identifier}",
                "sigmet_id": identifier,
                "fir_id": current_fir,
                "valid_from_utc": _iso(start),
                "valid_to_utc": _iso(end),
                "source_page": source_page(identifier, start_match.group("start")),
                "raw_lines": [line],
            }
            continue
        if current is not None and not line.startswith(("SIA ", "Page ")):
            current["raw_lines"].append(line)
    flush()
    return records


def _route_segments(flight: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    waypoints = [
        item
        for item in (flight.get("route_waypoints") or [])
        if item.get("latitude") is not None
        and item.get("longitude") is not None
        and item.get("actm_minutes") is not None
    ]
    anchor = _utc(flight.get("scheduled_departure_utc"))
    if anchor is None or len(waypoints) < 2:
        return [], ["route_or_timing_unavailable"]
    levels, unresolved = _planned_levels(waypoints, flight.get("planned_level_profile"))
    current_fir = str(flight.get("departure_fir") or "").upper() or None
    segments: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(waypoints, waypoints[1:])):
        if start.get("fir_boundary"):
            current_fir = str(start["fir_boundary"]).upper()
        start_actm = int(start["actm_minutes"])
        end_actm = int(end["actm_minutes"])
        if end_actm < start_actm:
            continue
        segments.append({
            "index": index,
            "from": str(start.get("name") or "").lstrip("-").upper(),
            "to": str(end.get("name") or "").lstrip("-").upper(),
            "start_utc": anchor + timedelta(minutes=start_actm),
            "end_utc": anchor + timedelta(minutes=end_actm),
            "start_actm_minutes": start_actm,
            "end_actm_minutes": end_actm,
            "flight_level": levels[index] if index < len(levels) else None,
            "fir_id": current_fir,
            "line": LineString([
                (float(start["longitude"]), float(start["latitude"])),
                (float(end["longitude"]), float(end["latitude"])),
            ]),
        })
    reasons = ["flight_level_change_unresolved"] if unresolved else []
    return segments, reasons


def _geometry_intersects(segment: dict[str, Any], geometry: dict[str, Any]) -> bool:
    coordinates = (geometry.get("coordinates") or [[]])[0]
    try:
        polygon = make_valid(Polygon(coordinates))
        return not polygon.is_empty and segment["line"].intersects(polygon)
    except (TypeError, ValueError):
        return False


def _base_result(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "hazard_id": record.get("product_id"),
        "hazard_type": record.get("hazard_type"),
        "authority": record.get("authority"),
        "source_class": record.get("source_class"),
        "source_page": record.get("source_page"),
        "valid_from_utc": record.get("valid_from_utc"),
        "valid_to_utc": record.get("valid_to_utc"),
        "fir_id": record.get("fir_id"),
        "lower_flight_level": record.get("lower_flight_level"),
        "upper_flight_level": record.get("upper_flight_level"),
        "raw_text": record.get("raw_text"),
        "operational_effects": list(record.get("operational_effects") or []),
        "reason_codes": [],
        "route_segments": [],
    }


def _evaluate_record(record: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    result = _base_result(record)
    valid_from = _utc(record.get("valid_from_utc"))
    valid_to = _utc(record.get("valid_to_utc"))
    if valid_from is None or valid_to is None:
        result.update(disposition=MONITOR_LEVEL2, highlight=False)
        result["reason_codes"].append("validity_unresolved")
        return result

    time_segments = [
        segment
        for segment in segments
        if _overlap(segment["start_utc"], segment["end_utc"], valid_from, valid_to)
    ]
    if not time_segments:
        result.update(disposition=SUPPRESS, highlight=False)
        result["reason_codes"].append("outside_flight_window")
        return result

    fir_id = str(record.get("fir_id") or "").upper()
    route_firs = {str(segment.get("fir_id") or "").upper() for segment in segments if segment.get("fir_id")}
    fir_segments = [segment for segment in time_segments if fir_id and segment.get("fir_id") == fir_id]
    if fir_id and fir_id in route_firs and not fir_segments:
        result.update(disposition=SUPPRESS, highlight=False)
        result["reason_codes"].append("fir_not_traversed_during_validity")
        return result

    candidates = fir_segments or time_segments
    geometry = record.get("geometry")
    if not geometry:
        result.update(disposition=MONITOR_LEVEL2, highlight=False)
        result["reason_codes"].append("geometry_not_structured")
        result["route_segments"] = [
            {"from": item["from"], "to": item["to"], "start_utc": _iso(item["start_utc"]), "end_utc": _iso(item["end_utc"])}
            for item in candidates[:4]
        ]
        return result

    intersected = [segment for segment in candidates if _geometry_intersects(segment, geometry)]
    if not intersected:
        result.update(disposition=SUPPRESS, highlight=False)
        result["reason_codes"].append("verified_no_route_intersection")
        return result

    lower = record.get("lower_flight_level")
    upper = record.get("upper_flight_level")
    if lower is None or upper is None:
        result.update(disposition=MONITOR_LEVEL2, highlight=False)
        result["reason_codes"].append("vertical_extent_unresolved")
        return result
    level_segments = [
        segment
        for segment in intersected
        if segment.get("flight_level") is not None
        and int(lower) <= int(segment["flight_level"]) <= int(upper)
    ]
    if not level_segments:
        if any(segment.get("flight_level") is None for segment in intersected):
            result.update(disposition=MONITOR_LEVEL2, highlight=False)
            result["reason_codes"].append("planned_level_unresolved")
        else:
            result.update(disposition=SUPPRESS, highlight=False)
            result["reason_codes"].append("verified_no_vertical_overlap")
        return result

    result["route_segments"] = [
        {
            "from": item["from"],
            "to": item["to"],
            "start_actm_minutes": item["start_actm_minutes"],
            "end_actm_minutes": item["end_actm_minutes"],
            "start_utc": _iso(item["start_utc"]),
            "end_utc": _iso(item["end_utc"]),
            "planned_flight_level": item["flight_level"],
        }
        for item in level_segments[:8]
    ]
    result["operational_effects"] = sorted(
        set(result["operational_effects"] + ["route_intersection", "planned_level_overlap"])
    )
    hazard_type = str(record.get("hazard_type") or "")
    if hazard_type in _LEVEL1_PHENOMENA:
        result.update(
            disposition=PROMOTE_LEVEL1,
            highlight=True,
            highlight_colour="amber",
            reason_codes=["verified_time_route_level_intersection"],
        )
    elif hazard_type in _LEVEL2_DEFAULT_PHENOMENA or hazard_type in {"thunderstorm", "sigmet_other"}:
        result.update(disposition=MONITOR_LEVEL2, highlight=False)
        result["reason_codes"].append("level2_by_default")
    else:
        result.update(disposition=MONITOR_LEVEL2, highlight=False)
        result["reason_codes"].append("phenomenon_not_in_level1_allowlist")
    return result


def _normalize_external(record: dict[str, Any]) -> dict[str, Any]:
    value = dict(record)
    value.setdefault("source_class", "official_external_weather")
    value.setdefault("product_id", value.get("source_id") or value.get("hazard_id") or "OFFICIAL-WX")
    value.setdefault("authority", value.get("source_authority"))
    value.setdefault("hazard_type", "unknown")
    value.setdefault("operational_effects", [])
    return value


def _evaluate_external(record: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    value = _normalize_external(record)
    hazard_type = str(value.get("hazard_type") or "")
    effects = set(value.get("operational_effects") or [])

    # A synoptic feature is not itself an operational hazard.  A front, trough,
    # low or jet stream requires a separately verified effect.
    if hazard_type in {"front", "cold_front", "warm_front", "occluded_front", "stationary_front", "trough", "low", "jet_stream"}:
        if not effects.intersection(_OPERATIONAL_EFFECTS):
            result = _base_result(value)
            result.update(disposition=SUPPRESS, highlight=False)
            result["reason_codes"] = ["synoptic_feature_without_verified_operational_effect"]
            return result

    result = _evaluate_record(value, segments)
    if result.get("disposition") == PROMOTE_LEVEL1 and not effects.intersection(_OPERATIONAL_EFFECTS):
        result["disposition"] = MONITOR_LEVEL2
        result["highlight"] = False
        result["highlight_colour"] = None
        result["reason_codes"] = ["operational_consequence_not_verified"]
    if hazard_type in _LEVEL2_DEFAULT_PHENOMENA and "company_promotion_rule" not in effects:
        result["disposition"] = MONITOR_LEVEL2
        result["highlight"] = False
        result["highlight_colour"] = None
        if "level2_by_default" not in result["reason_codes"]:
            result["reason_codes"].append("level2_by_default")
    return result


def _review_coverage(
    review: dict[str, Any],
    hazard_type: str,
    label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    promoted: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    status = review.get("status")
    if status == "affected":
        matches = review.get("matches") or []
        promoted.append({
            "hazard_id": label,
            "hazard_type": hazard_type,
            "authority": review.get("provider"),
            "source_class": "official_sigmet_feed",
            "disposition": PROMOTE_LEVEL1,
            "highlight": True,
            "highlight_colour": "amber",
            "reason_codes": ["verified_time_route_level_intersection"],
            "route_segments": matches,
            "operational_effects": ["route_intersection", "planned_level_overlap"],
        })
    elif status in {"review_required", "not_assessed", None, ""}:
        gaps.append({
            "code": f"{hazard_type}_coverage_incomplete",
            "label": f"{label} coverage incomplete",
            "reason_codes": list(review.get("reason_codes") or ["source_not_assessed"]),
            "source": review.get("provider"),
        })
    return promoted, gaps


def assess_operational_hazards(
    flight: dict[str, Any],
    pages: list[str],
) -> dict[str, Any]:
    """Run the mandatory, non-exaggerating meteorological hazard gate."""
    segments, route_reasons = _route_segments(flight)
    embedded_sigmets = extract_embedded_sigmets(pages, flight)
    evaluated = [_evaluate_record(record, segments) for record in embedded_sigmets]
    evaluated.extend(
        _evaluate_external(record, segments)
        for record in (flight.get("official_weather_hazards") or [])
        if isinstance(record, dict)
    )

    promoted = [item for item in evaluated if item.get("disposition") == PROMOTE_LEVEL1]
    monitor = [item for item in evaluated if item.get("disposition") == MONITOR_LEVEL2]
    suppressed = [item for item in evaluated if item.get("disposition") == SUPPRESS]

    weather_pages = _weather_pages(pages)
    availability = {
        "airmet": _source_status(_section_text(weather_pages, "AIRMETs:", ("SIGMETs:",))),
        "sigmet": _source_status(_section_text(weather_pages, "SIGMETs:", ("Tropical Cyclone SIGMETs:",))),
        "tropical_cyclone_sigmet": _source_status(
            _section_text(weather_pages, "Tropical Cyclone SIGMETs:", ("Volcanic Ash SIGMETs:",))
        ),
        "volcanic_ash_sigmet": _source_status(
            _section_text(weather_pages, "Volcanic Ash SIGMETs:", ("DESTINATION AIRPORT:",))
        ),
    }

    gaps: list[dict[str, Any]] = []
    if availability["airmet"] != "present":
        gaps.append({"code": "airmet_coverage_incomplete", "label": "AIRMET coverage incomplete", "reason_codes": [availability["airmet"]]})

    tc_promoted, tc_gaps = _review_coverage(
        flight.get("tropical_cyclone_review") or {},
        "tropical_cyclone",
        "Tropical cyclone",
    )
    va_promoted, va_gaps = _review_coverage(
        flight.get("vaa_review") or {},
        "volcanic_ash",
        "Volcanic ash",
    )
    promoted.extend(tc_promoted)
    promoted.extend(va_promoted)
    if availability["tropical_cyclone_sigmet"] != "present":
        gaps.extend(tc_gaps or [{"code": "tropical_cyclone_coverage_incomplete", "label": "Tropical cyclone coverage incomplete", "reason_codes": [availability["tropical_cyclone_sigmet"]]}])
    if availability["volcanic_ash_sigmet"] != "present":
        gaps.extend(va_gaps or [{"code": "volcanic_ash_coverage_incomplete", "label": "Volcanic ash coverage incomplete", "reason_codes": [availability["volcanic_ash_sigmet"]]}])

    source_coverage = flight.get("weather_source_coverage") or {}
    if source_coverage.get("frontal_weather") != "complete":
        gaps.append({
            "code": "frontal_weather_coverage_incomplete",
            "label": "Frontal-weather analysis not mounted",
            "reason_codes": [str(source_coverage.get("frontal_weather") or "source_not_mounted")],
        })
    if source_coverage.get("clear_air_turbulence") != "complete":
        gaps.append({
            "code": "clear_air_turbulence_coverage_incomplete",
            "label": "CAT/turbulence forecast coverage not mounted",
            "reason_codes": [str(source_coverage.get("clear_air_turbulence") or "source_not_mounted")],
        })

    # Deduplicate source records and gaps without losing deterministic order.
    unique_promoted: list[dict[str, Any]] = []
    seen_promoted: set[tuple[str, str]] = set()
    for item in promoted:
        key = (str(item.get("hazard_type") or ""), str(item.get("hazard_id") or ""))
        if key not in seen_promoted:
            seen_promoted.add(key)
            unique_promoted.append(item)
    unique_gaps: list[dict[str, Any]] = []
    seen_gaps: set[str] = set()
    for gap in gaps:
        code = str(gap.get("code") or "coverage_incomplete")
        if code not in seen_gaps:
            seen_gaps.add(code)
            unique_gaps.append(gap)

    if unique_promoted:
        status = "significant_hazard_promoted"
    elif unique_gaps:
        status = "no_significant_hazard_promoted_coverage_incomplete"
    else:
        status = "no_significant_hazard_promoted"

    result = {
        "schema_version": "1.0",
        "gate_version": GATE_VERSION,
        "status": status,
        "promoted": unique_promoted,
        "monitor": monitor,
        "suppressed": suppressed,
        "coverage_gaps": unique_gaps,
        "source_availability": availability,
        "route_reason_codes": route_reasons,
        "counts": {
            "promoted": len(unique_promoted),
            "monitor": len(monitor),
            "suppressed": len(suppressed),
            "coverage_gaps": len(unique_gaps),
            "embedded_sigmet_records": len(embedded_sigmets),
        },
        "level1_statement": (
            f"{len(unique_promoted)} significant meteorological hazard(s) meet the highlight gate."
            if unique_promoted
            else None
        ),
        "level2_statement": (
            "No significant meteorological hazard was promoted from the available, time-matched products."
            + (
                " Coverage remains incomplete for: "
                + "; ".join(gap["label"] for gap in unique_gaps)
                + "."
                if unique_gaps
                else ""
            )
        ),
        "constraint": {
            "authoritative_source_required": True,
            "time_overlap_required": True,
            "route_or_airport_applicability_required": True,
            "vertical_overlap_required_when_applicable": True,
            "operational_consequence_required": True,
            "front_or_jet_alone_is_not_a_hazard": True,
            "moderate_wafs_or_airmet_default": MONITOR_LEVEL2,
            "red_reserved_for_verified_limit_or_unavailability": True,
        },
    }
    flight["operational_hazard_assessment"] = result
    return result


__all__ = [
    "COVERAGE_GAP",
    "GATE_VERSION",
    "MONITOR_LEVEL2",
    "PROMOTE_LEVEL1",
    "SUPPRESS",
    "assess_operational_hazards",
    "extract_embedded_sigmets",
]
