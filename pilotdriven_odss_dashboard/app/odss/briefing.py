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

from . import brief_theme as theme
from .brief_theme import SANS, SANS_BOLD, register_fonts
from .constants import edto_sectors, format_actm, format_kg
from .deferred_dispatch import build_deferred_dispatch_gates
from .engines import detect_terrain_events, detect_vws_events
from .pilot_briefing import prepare_pilot_findings, select_pertinent_notams
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
            "text": "No airport-specific NOTAM finding selected for this operating window.",
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


def _station_source_weather(
    flight: dict[str, Any],
    location: str,
    record_type: str,
) -> dict[str, Any] | None:
    for record in flight.get("weather") or []:
        if (
            str(record.get("location") or "").upper() == location
            and record.get("record_type") == record_type
            and str(record.get("text") or "").strip()
            and isinstance(record.get("source_page"), int)
        ):
            return {
                "record_type": record_type,
                "text": str(record["text"]).strip(),
                "source_page": record.get("source_page"),
                "source_role": record.get("source_role"),
            }
    return None


def _cfp_weather_records(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Weather records with direct uploaded-CFP page provenance only."""
    return [
        record
        for record in flight.get("weather") or []
        if isinstance(record, dict)
        and isinstance(record.get("source_page"), int)
    ]


_COMPACT_ENROUTE_FAMILY_ORDER = {
    "airport_closure": 0,
    "approach_navaid": 1,
    "information_service": 2,
    "runway_closure": 3,
    "runway_restriction": 4,
    "taxiway": 5,
    "apron_stand": 6,
    "obstacle": 7,
    "other": 8,
}
_COMPACT_PRIMARY_FAMILY_ORDER = {
    "airport_closure": 0,
    "runway_closure": 1,
    "approach_navaid": 2,
    "runway_restriction": 3,
    "taxiway": 4,
    "apron_stand": 5,
    "information_service": 6,
    "obstacle": 7,
    "other": 8,
}

_RUNWAY_TOKEN = re.compile(r"\b(?:RWY\s*)?(\d{2}[LCR]?)\b")
_RUNWAY_CLOSURE_SCHEDULE = re.compile(
    r"\bRWY\s+(?P<runways>\d{2}[LCR]?(?:/\d{2}[LCR]?)?)\s+"
    r"WILL\s+BE\s+CLSD\s+BTN\s+"
    r"(?P<start>\d{4})(?:UTC)?\s+TO\s+"
    r"(?P<end>\d{4})(?:UTC)?\s+EV\s+"
    r"(?P<weekdays>(?:MON|TUE|WED|THU|FRI|SAT|SUN)"
    r"(?:\s+AND\s+(?:MON|TUE|WED|THU|FRI|SAT|SUN))*)\s+"
    r"FM\s+(?P<valid_from>\d{2}[A-Z]{3}\d{2})\s+"
    r"TO\s+(?P<valid_to>\d{2}[A-Z]{3}\d{2})\b",
    re.IGNORECASE,
)
_WEEKDAY_INDEX = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


def _runway_designators(value: Any) -> set[str]:
    return {
        match.group(1).upper()
        for match in _RUNWAY_TOKEN.finditer(str(value or "").upper())
    }


def _notam_runway_designators(value: Any) -> set[str]:
    """Runway tokens anchored to RWY/RUNWAY, excluding dates and levels."""
    designators: set[str] = set()
    for match in re.finditer(
        r"\b(?:RWY|RUNWAY)\s*(\d{2}[LCR]?)"
        r"(?:\s*/\s*(\d{2}[LCR]?))?\b",
        str(value or "").upper(),
    ):
        designators.add(match.group(1))
        if match.group(2):
            designators.add(match.group(2))
    return designators


def _planned_runways(specification: dict[str, Any]) -> set[str]:
    return {
        runway
        for row in specification.get("operational_rows") or []
        for runway in _runway_designators(row.get("runway"))
    }


def _reference_time_for_roles(
    flight: dict[str, Any],
    role_keys: set[str],
    selected_notams: list[dict[str, Any]],
) -> datetime | None:
    if "departure" in role_keys:
        return _parse_utc(flight.get("scheduled_departure_utc"))
    if "destination" in role_keys:
        return _parse_utc(flight.get("scheduled_arrival_utc"))
    for item in selected_notams:
        start = _parse_utc(item.get("window_start_utc"))
        end = _parse_utc(item.get("window_end_utc"))
        if start and end:
            return start + (end - start) / 2
    return None


def _compact_runway_schedule_text(
    item: dict[str, Any],
    *,
    role: str,
    planned_runways: set[str],
    reference_time: datetime | None,
) -> str | None:
    """Summarise an explicit source schedule for the planned runway.

    The source can carry multiple dated runway regimes in one AIP supplement.
    A regime is used only when its printed date range, weekday and runway all
    match the current flight.  Anything ambiguous falls back to the existing
    shared review wording.
    """
    if not planned_runways or reference_time is None:
        return None
    raw = " ".join(str(item.get("item_e_text") or "").upper().split())
    for match in _RUNWAY_CLOSURE_SCHEDULE.finditer(raw):
        schedule_runways = _runway_designators(match.group("runways"))
        if not schedule_runways & planned_runways:
            continue
        try:
            valid_from = datetime.strptime(
                match.group("valid_from").upper(), "%d%b%y"
            ).date()
            valid_to = datetime.strptime(
                match.group("valid_to").upper(), "%d%b%y"
            ).date()
        except ValueError:
            continue
        if not valid_from <= reference_time.date() <= valid_to:
            continue
        weekdays = {
            _WEEKDAY_INDEX[token]
            for token in re.findall(
                r"MON|TUE|WED|THU|FRI|SAT|SUN",
                match.group("weekdays").upper(),
            )
        }
        if reference_time.weekday() not in weekdays:
            continue
        start_text = match.group("start")
        end_text = match.group("end")
        start_hour, start_minute = int(start_text[:2]), int(start_text[2:])
        end_hour, end_minute = int(end_text[:2]), int(end_text[2:])
        if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
            continue
        closure_start = reference_time.replace(
            hour=start_hour, minute=start_minute, second=0, microsecond=0
        )
        closure_end = reference_time.replace(
            hour=end_hour, minute=end_minute, second=0, microsecond=0
        )
        if closure_end <= closure_start:
            closure_end += timedelta(days=1)
        runway_label = match.group("runways").upper()
        reference_label = "ETA" if role == "destination" else (
            "ETD" if role == "departure" else "REFERENCE"
        )
        reference_display = reference_time.strftime("%H%MZ")
        if reference_time < closure_start:
            delta_minutes = int((closure_start - reference_time).total_seconds() // 60)
            return (
                f"RWY {runway_label} closes {start_text}-{end_text}Z; "
                f"{reference_label} {reference_display} precedes closure by "
                f"{delta_minutes // 60}h{delta_minutes % 60:02d}."
            )
        if reference_time < closure_end:
            return (
                f"RWY {runway_label} closes {start_text}-{end_text}Z; "
                f"{reference_label} {reference_display} is within the closure."
            )
        delta_minutes = int((reference_time - closure_end).total_seconds() // 60)
        return (
            f"RWY {runway_label} closure {start_text}-{end_text}Z ends "
            f"{delta_minutes // 60}h{delta_minutes % 60:02d} before "
            f"{reference_label} {reference_display}."
        )
    return None


def _compact_notam_family(item: dict[str, Any]) -> str:
    kind = str(item.get("pertinence_kind") or "")
    raw = str(item.get("item_e_text") or "").upper()
    if kind == "airport_closure":
        return "airport_closure"
    if "ATIS" in raw:
        return "information_service"
    if kind in {
        "approach_navaid_closure",
        "runway_approach_restriction",
        "obstacle",
    } and re.search(
        r"\b(?:ILS|LOC|LOCALISER|GP|GLIDEPATH|VOR|NDB|DME)\b",
        raw,
    ):
        return "approach_navaid"
    if kind == "approach_navaid_closure" or (
        kind == "runway_approach_restriction"
        and re.search(r"\b(?:ILS|LOC|LOCALISER|GP|GLIDEPATH|VOR|NDB|DME)\b", raw)
    ):
        return "approach_navaid"
    if kind == "runway_approach_restriction":
        return "runway_restriction"
    if kind == "runway_closure":
        return "runway_closure"
    if kind == "runway_lighting_restriction":
        return "runway_restriction"
    if kind in {"taxiway_closure", "taxiway_restriction"}:
        return "taxiway"
    if kind == "apron_stand_closure":
        return "apron_stand"
    if kind == "obstacle":
        return "obstacle"
    return "other"


def _compact_notam_text(
    item: dict[str, Any],
    family: str,
    *,
    role: str,
    planned_runways: set[str],
    reference_time: datetime | None,
) -> str:
    """One source-bounded line; fall back to the shared engine summary."""
    raw = " ".join(str(item.get("item_e_text") or "").split())
    upper = raw.upper()
    schedule_text = _compact_runway_schedule_text(
        item,
        role=role,
        planned_runways=planned_runways,
        reference_time=reference_time,
    )
    if schedule_text:
        return schedule_text
    unavailable = bool(
        re.search(
            r"\b(?:U/S|UNSERVICEAB(?:LE|ILITY)|NOT\s+AVBL|NOT\s+AVAILABLE)\b",
            upper,
        )
    )
    if family == "approach_navaid" and unavailable:
        runway = re.search(r"\bRWY\s*(\d{1,2}[LCR]?)\b", upper)
        if "ILS" in upper and re.search(r"\bGP\b", upper):
            suffix = f" RWY{runway.group(1)}" if runway else ""
            return f"ILS/GP{suffix} unavailable."
    if family == "approach_navaid":
        localiser = re.search(
            r"\bLOC\s+'?(?P<ident>[A-Z0-9]+)'?\s+"
            r"(?P<frequency>\d{3}\.\d)\s+RWY\s*(?P<runway>\d{1,2}[LCR]?)\b",
            upper,
        )
        if localiser and re.search(r"\b(?:INTRP|INTERRUPT|OSCILLAT)", upper):
            cause = " due crane operations" if "CRANE" in upper else ""
            return (
                f"LOC {localiser.group('ident')} {localiser.group('frequency')} "
                f"RWY{localiser.group('runway')} subject to interruption / "
                f"possible signal oscillation{cause}; runway is not reported closed."
            )
    if family == "information_service" and "D-ATIS" in upper:
        if "LIMITED TRIAL" in upper and "VOICE ATIS" in upper:
            return "D-ATIS limited trial; voice ATIS remains primary."
        if unavailable:
            return "D-ATIS unavailable."
    runways = sorted(_runway_designators(upper))
    runway_label = "/".join(runways)
    if (
        "RAPID EXIT TAXIWAY INDICATOR LIGHTS" in upper
        and "DEACTIVATION" in upper
    ):
        retil_runway = re.search(
            r"\bAT\s+RUNWAY\s+(\d{2}[LCR]?(?:/\d{2}[LCR]?)?)\b",
            upper,
        )
        retil_runway_label = (
            retil_runway.group(1) if retil_runway else runway_label
        )
        return (
            f"RETIL RWY {retil_runway_label} temporarily deactivated; use standard "
            "runway exit procedures with published taxiway, lighting/signage "
            "and ATC cues."
        )
    if (
        "GRADING OF RWY STRIP" in upper
        and "PRESENCE OF MEN AND EQPT" in upper
    ):
        return (
            f"RWY {runway_label} strip grading WIP; men and equipment present."
        )
    return str(item.get("summary") or raw or "Operational notice - review source.")


def _compact_notam_condition_key(
    item: dict[str, Any],
    family: str,
    runways: set[str],
    display_text: str,
) -> tuple[Any, ...]:
    """Collapse source duplicates without merging unrelated facilities."""
    raw = " ".join(str(item.get("item_e_text") or "").upper().split())
    if runways:
        state = (
            "closed_or_unavailable"
            if re.search(r"\b(?:CLSD|CLOSED|U/S|NOT\s+AVBL|NOT\s+AVAILABLE)\b", raw)
            else "work_in_progress"
            if re.search(r"\b(?:WIP|WORK\s+IN\s+PROGRESS)\b", raw)
            else "restriction"
        )
        equipment = tuple(sorted(set(re.findall(
            r"\b(?:ILS|LOC|LOCALISER|GP|GLIDEPATH|VOR|NDB|DME|RETIL)\b",
            raw,
        ))))
        return family, tuple(sorted(runways)), state, equipment
    normalized_text = re.sub(
        r"\s+",
        " ",
        str(display_text or "").strip().upper(),
    )
    return family, normalized_text


def _compact_notam_lines(
    selected_notams: list[dict[str, Any]],
    role: str,
    *,
    limit: int = 2,
    planned_runways: set[str] | None = None,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Pick category-diverse compact lines; full notices remain untouched.

    EDTO/fuel-enroute cards prefer persistent approach/navaid and information-
    service facts over repeated scheduled surface notices. Primary-airport
    cards retain runway-first ordering. At most one notice per semantic family
    is shown; deterministic ID ordering breaks equal-rank ties.
    """
    family_order = (
        _COMPACT_ENROUTE_FAMILY_ORDER
        if role in {"EDTO", "fuel enroute airport"}
        else _COMPACT_PRIMARY_FAMILY_ORDER
    )
    runway_basis = set(planned_runways or set())
    ranked = []
    for position, item in enumerate(selected_notams):
        raw = str(item.get("item_e_text") or "").upper()
        if role == "destination" and re.search(r"\bFLIGHTS?\s+DEPARTING\b", raw):
            continue
        if role == "departure" and re.search(r"\bFLIGHTS?\s+ARRIVING\b", raw):
            continue
        family = _compact_notam_family(item)
        operational_runways = (
            _notam_runway_designators(raw)
            if family in {
                "approach_navaid",
                "runway_closure",
                "runway_restriction",
            }
            else set()
        )
        display_text = _compact_notam_text(
            item,
            family,
            role=role,
            planned_runways=runway_basis,
            reference_time=reference_time,
        )
        ranked.append((
            0 if operational_runways & runway_basis else 1,
            family_order[family],
            int(item.get("pertinence_rank") or 99),
            -_SEVERITY_RANK.get(str(item.get("severity") or "information"), 0),
            str(item.get("notam_id") or ""),
            position,
            family,
            operational_runways,
            _compact_notam_condition_key(
                item,
                family,
                operational_runways,
                display_text,
            ),
            display_text,
            item,
        ))
    lines: list[dict[str, Any]] = []
    seen_family_runways: dict[str, set[str]] = {}
    seen_conditions: set[tuple[Any, ...]] = set()
    for (
        _, _, _, _, _, _, family, item_runways, condition_key, display_text, item
    ) in sorted(ranked):
        if condition_key in seen_conditions:
            continue
        seen_conditions.add(condition_key)
        if family in seen_family_runways:
            distinct_critical_runway = bool(
                str(item.get("severity") or "") == "critical"
                and item_runways
                and not item_runways.issubset(seen_family_runways[family])
            )
            if not distinct_critical_runway:
                continue
        seen_family_runways.setdefault(family, set()).update(item_runways)
        lines.append({
            "kind": "notam",
            "label": item.get("notam_id") or "NOTAM",
            "text": display_text,
            "notam_id": item.get("notam_id"),
            "source_page": item.get("source_page"),
            "signal_family": family,
            "planned_match": (
                bool(item_runways & runway_basis)
                if item_runways and runway_basis
                else None
            ),
            "different_runway": bool(
                item_runways
                and runway_basis
                and item_runways.isdisjoint(runway_basis)
            ),
        })
        if len(lines) >= limit:
            break
    return lines


def _airport_operational_panels(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The selected source-fact contract shared by dashboard and PDF.

    Each station gets exact CFP METAR/TAF records and a deterministic set of
    time-applicable NOTAM findings. A station used in more than one planning
    role remains one panel with ordered ``roles`` and combined planning rows.
    The notices carry item-E text and source evidence, not renderer-only copy.
    """
    specifications: list[dict[str, Any]] = []

    def add(
        role: str,
        role_key: str,
        airport: Any,
        operational_row: dict[str, Any],
        *,
        iata: Any = None,
        name: Any = None,
        source_pages: list[int] | None = None,
    ) -> None:
        location = str(airport or "").strip().upper()
        if not location:
            return
        existing = next(
            (
                item
                for item in specifications
                if item["icao"] == location
            ),
            None,
        )
        if existing is None:
            existing = {
                "icao": location,
                "iata": iata,
                "name": str(name or ""),
                "role": role,
                "role_key": role_key,
                "roles": [],
                "role_keys": [],
                "operational_rows": [],
                "declared_source_pages": list(source_pages or []),
            }
            specifications.append(existing)
        elif iata and not existing.get("iata"):
            existing["iata"] = iata
        if name and not existing.get("name"):
            existing["name"] = str(name)
        if role not in existing["roles"]:
            existing["roles"].append(role)
            existing["role_keys"].append(role_key)
        existing["declared_source_pages"] = sorted({
            *(
                page
                for page in existing["declared_source_pages"]
                if isinstance(page, int)
            ),
            *(
                page
                for page in (source_pages or [])
                if isinstance(page, int)
            ),
        })
        existing["operational_rows"].append({
            **dict(operational_row),
            "planning_role": role,
            "planning_role_key": role_key,
        })

    add(
        "departure",
        "departure",
        flight.get("departure"),
        {"runway": flight.get("departure_runway")},
    )
    add(
        "destination",
        "destination",
        flight.get("destination"),
        {"runway": flight.get("destination_runway")},
    )
    for alternate_index, alternate in enumerate(flight.get("alternates") or []):
        add(
            "destination alternate",
            "alternate",
            alternate.get("airport"),
            {
                **alternate,
                # LIDO orders the selected destination alternate first. The
                # remaining rows are alternates, not additional "preferred"
                # stations. Preserve that source order explicitly so every
                # publishing surface uses the same role label.
                "is_preferred": alternate_index == 0,
            },
        )
    for edto_airport in (flight.get("edto") or {}).get("airports") or []:
        add("EDTO", "edto", edto_airport.get("airport"), edto_airport)
    for station in flight.get("fuel_enroute_airports") or []:
        add(
            "fuel enroute airport",
            "fuel_enroute_airport",
            station.get("airport"),
            {"role": station.get("role") or "fuel_enroute_airport"},
            iata=station.get("iata"),
            name=station.get("name"),
            source_pages=[
                page
                for page in station.get("source_pages") or []
                if isinstance(page, int)
            ],
        )

    panels: list[dict[str, Any]] = []
    for specification in specifications:
        location = specification["icao"]
        roles = set(specification["roles"])
        applicable_findings = [
            item
            for item in findings
            if item.get("engine") == "notam"
            and str((item.get("data") or {}).get("location") or "").upper()
            == location
            and (item.get("data") or {}).get("role") in roles
        ]
        selected_findings = select_pertinent_notams(
            applicable_findings,
            # Engine findings are already inside the checked B/C/D window.
            # Keep every deduplicated applicable notice for the detail/
            # continuation surfaces; only card_summary_lines is compact.
            limit=len(applicable_findings),
        )
        selected_notams = []
        for item in selected_findings:
            data = item.get("data") or {}
            selected_notams.append({
                "notam_id": data.get("notam_id"),
                "summary": item.get("summary"),
                "item_e_text": data.get("raw_text"),
                "valid_from_utc": data.get("valid_from_utc"),
                "valid_to_utc": data.get("valid_to_utc"),
                "schedule": data.get("schedule"),
                "source_page": data.get("source_page"),
                "source_role": data.get("source_role"),
                "role": data.get("role"),
                "pertinence_rank": data.get("pertinence_rank"),
                "pertinence_kind": data.get("pertinence_kind"),
                "applicability": data.get("applicability"),
                "window_start_utc": data.get("window_start_utc"),
                "window_end_utc": data.get("window_end_utc"),
                "severity": item.get("severity"),
            })
        metar = _station_source_weather(flight, location, "METAR")
        taf = _station_source_weather(flight, location, "TAF")
        card_summary_lines = [
            {
                "kind": "weather",
                "label": record_type,
                "text": record["text"],
                "source_page": record.get("source_page"),
            }
            for record_type, record in (("METAR", metar), ("TAF", taf))
            if record is not None
        ]
        compact_role = (
            "EDTO"
            if roles & {"EDTO", "fuel enroute airport"}
            else specification["role"]
        )
        card_summary_lines.extend(
            _compact_notam_lines(
                selected_notams,
                compact_role,
                limit=(
                    3
                    if compact_role in {"departure", "destination"}
                    else 2
                ),
                planned_runways=_planned_runways(specification),
                reference_time=_reference_time_for_roles(
                    flight,
                    set(specification["role_keys"]),
                    selected_notams,
                ),
            )
        )
        source_pages = {
            page
            for page in specification["declared_source_pages"]
            if isinstance(page, int)
        }
        source_pages.update(
            record.get("source_page")
            for record in (metar, taf)
            if record is not None and isinstance(record.get("source_page"), int)
        )
        source_pages.update(
            item.get("source_page")
            for item in selected_notams
            if isinstance(item.get("source_page"), int)
        )
        panels.append({
            **specification,
            "weather": {"metar": metar, "taf": taf},
            "selected_notams": selected_notams,
            "card_summary_lines": card_summary_lines,
            "source_pages": sorted(source_pages),
        })
        panels[-1].pop("declared_source_pages", None)
    return panels


def _actm_clock(value: Any) -> str:
    """CFP ACTM ("03.21" / "03:21") as a clock string; empty when not held."""
    match = re.fullmatch(r"(\d{1,2})[.:](\d{2})", str(value or "").strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""


def _destination_actm(flight: dict[str, Any]) -> int | None:
    """Return ACTM only from a waypoint that is the filed destination."""
    destination = str(flight.get("destination") or "").lstrip("-").upper()
    if not destination:
        return None
    candidates: list[int] = []
    for waypoint in flight.get("route_waypoints") or []:
        name = str(waypoint.get("name") or "").lstrip("-").upper()
        if name != destination:
            continue
        try:
            actm = int(waypoint.get("actm_minutes"))
        except (TypeError, ValueError):
            continue
        if actm >= 0:
            candidates.append(actm)
    return max(candidates) if candidates else None


def _actual_arrival_hhmm(
    timing_view: dict[str, Any] | None,
    destination_actm: int | None,
) -> str | None:
    """Return ATOT + ACTM only when destination ACTM is explicitly held."""
    if not timing_view or destination_actm is None:
        return None
    for waypoint in reversed(list(timing_view.get("waypoints") or [])):
        try:
            waypoint_actm = int(waypoint.get("actm_minutes"))
        except (TypeError, ValueError):
            continue
        clock = str(waypoint.get("utc_clock") or "").strip().upper()
        if waypoint_actm == destination_actm and re.fullmatch(r"\d{4}Z", clock):
            return clock[:-1]
    actual_takeoff = _parse_utc(timing_view.get("actual_takeoff_utc"))
    if actual_takeoff is None:
        return None
    return (actual_takeoff + timedelta(minutes=destination_actm)).strftime("%H%M")


def _arrival_basis_line(
    etd_hhmm: Any,
    eta_hhmm: Any,
    block: Any,
    eet_actm: Any,
    *,
    actual_takeoff_hhmm: str | None = None,
    calculated_eta_hhmm: str | None = None,
) -> str:
    """State calculated ETA separately from the CFP schedule."""
    etd = str(etd_hhmm or "").strip()
    eta = str(eta_hhmm or "").strip()
    eet = _actm_clock(eet_actm)
    atot = str(actual_takeoff_hhmm or "").strip()
    calculated_eta = str(calculated_eta_hhmm or "").strip()
    if atot and calculated_eta:
        basis = f"ATOT {atot} + " + (f"filed EET {eet}" if eet else "CFP ACTM")
        if eta:
            basis += f" · scheduled STA {eta}Z"
        return basis
    if atot:
        basis = f"ATOT {atot} held; destination ACTM unavailable"
        if eta:
            basis += f" · scheduled STA {eta}Z"
        return basis
    parts: list[str] = []
    if etd:
        parts.append(f"STD {etd}Z" + (f" + SCHED {block}" if block else ""))
    if eet:
        parts.append(f"filed EET {eet}")
    return " · ".join(parts) or "Scheduled arrival per CFP page 1"


def _timeline_basis_line(
    etd_hhmm: Any,
    eta_hhmm: Any,
    block: Any,
    eet_actm: Any,
    actual_takeoff_hhmm: str | None,
    calculated_eta_hhmm: str | None,
) -> str:
    """Name the decision clock basis without mixing schedule and actual time."""
    etd = str(etd_hhmm or "").strip() or "--"
    eta = str(eta_hhmm or "").strip() or "--"
    eet = _actm_clock(eet_actm) or "--"
    schedule = str(block or "").strip() or "--"
    atot = str(actual_takeoff_hhmm or "").strip()
    calculated_eta = str(calculated_eta_hhmm or "").strip()
    if atot and calculated_eta:
        return (
            f"ATOT {atot} + CFP ACTM drives clocks; calculated ETA "
            f"{calculated_eta}Z from filed EET {eet}. Schedule: STD {etd}Z / "
            f"STA {eta}Z ({schedule})."
        )
    if atot:
        return (
            f"ATOT {atot} held; destination ACTM unavailable, so no calculated "
            f"ETA is published. Schedule: STD {etd}Z / STA {eta}Z ({schedule})."
        )
    return (
        f"Schedule: STD {etd}Z / STA {eta}Z ({schedule}). Filed EET {eet}; "
        "enter ATOT/ATA for calculated UTC clocks."
    )


def _performance_publication(flight: dict[str, Any]) -> dict[str, Any]:
    """One RTOW selection and margin contract for every publishing surface."""
    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    definitions = (
        ("performance", "RTOW PERF", "obstacle_rtow_kg"),
        ("landing", "RTOW LAND", "landing_rtow_kg"),
        ("structural", "RTOW STRUCT", "structural_rtow_kg"),
        ("cfp_controlling", "CFP RTOW", "controlling_rtow_kg"),
    )
    candidates = [
        {
            "key": key,
            "label": label,
            "source_field": source_field,
            "limit_kg": int(performance[source_field]),
        }
        for key, label, source_field in definitions
        if performance.get(source_field) is not None
    ]
    selected = min(
        (candidate["limit_kg"] for candidate in candidates),
        default=None,
    )
    for candidate in candidates:
        candidate["selected"] = candidate["limit_kg"] == selected
    ptow = masses.get("planned_takeoff_weight_kg")
    ptow = int(ptow) if ptow is not None else None
    margin = selected - ptow if selected is not None and ptow is not None else None
    if selected is None or ptow is None:
        status = "manual-review-required"
    elif margin < 0:
        status = "limit-exceeded"
    else:
        status = "within-limit"
    return {
        "status": status,
        "basis": (
            "selected_rtow_kg = minimum available parsed CFP RTOW candidate; "
            "margin_kg = selected_rtow_kg - ptow_kg."
        ),
        "ptow_kg": ptow,
        # The CFP performance inputs behind the selection, published once so
        # the page-1 PERFORMANCE card and the dashboard print the same basis.
        "inputs": {
            key: performance.get(key)
            for key in (
                "runway",
                "runway_condition",
                "thrust_setting",
                "flap_setting",
                "temperature_c",
                "qnh_hpa",
                "wind",
                "packs_on",
                "anti_ice_on",
                "eosid",
                "maximum_fuel_available_kg",
            )
        },
        "candidate_limits": candidates,
        "selected_rtow_kg": selected,
        "selected_candidate_keys": [
            candidate["key"]
            for candidate in candidates
            if candidate["selected"]
        ],
        "margin_kg": margin,
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
    map_label_size = float(route_map.get("pdf_label_size") or 7.2)
    map_note_size = float(route_map.get("pdf_note_size") or 7.2)

    def wrap_note(value: Any) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in str(value or "").replace("; ", " ; ").split():
            if word == ";":
                if current:
                    lines.append(current)
                    current = ""
                continue
            candidate = f"{current} {word}".strip()
            if pdfmetrics.stringWidth(candidate, SANS, map_note_size) > width - 10:
                if not current:
                    raise ValueError("Route-map source note has an unbreakable oversized token")
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

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
            for index, line in enumerate(
                reversed(wrap_note(f"{label} - Filed route from CFP coordinates"))
            ):
                canvas.drawString(x + 5, y + 4 + index * (map_note_size + 1.2), line)
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
    note = str(route_map.get("note") or "")
    note_lines = wrap_note(note)
    for index, line in enumerate(reversed(note_lines)):
        canvas.setFont(SANS, map_note_size)
        canvas.drawString(x + 5, y + 4 + index * (map_note_size + 1.2), line)
    canvas.restoreState()


def _fir_boundary_rows(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Lossless CFP FIR-boundary clocks; procedures remain a separate gap."""
    rows: list[dict[str, Any]] = []
    for waypoint in flight.get("route_waypoints") or []:
        fir = str(waypoint.get("fir_boundary") or "").strip().upper()
        actm = waypoint.get("actm_minutes")
        if not fir or not isinstance(actm, int):
            continue
        source_page = waypoint.get("source_page")
        rows.append({
            "time": "CFP BOUNDARY",
            "actm": f"+{format_actm(actm).replace('.', ':')}",
            "event": f"{fir} FIR boundary",
            "detail": " | ".join(
                part
                for part in (
                    f"CFP p{source_page}" if isinstance(source_page, int) else None,
                    "contact procedure/frequency unavailable",
                )
                if part
            ),
            "source_page": source_page,
            "record_kind": "fir_boundary_source",
        })
    return rows


def _fir_boundary_summary(rows: list[dict[str, Any]]) -> str:
    grouped: dict[str, dict[str, list[Any]]] = {}
    for row in rows:
        fir = str(row.get("event") or "").replace(" FIR boundary", "").strip()
        if not fir:
            continue
        group = grouped.setdefault(fir, {"actm": [], "pages": []})
        group["actm"].append(str(row.get("actm") or "--:--"))
        source_page = row.get("source_page")
        if isinstance(source_page, int):
            group["pages"].append(source_page)
    parts: list[str] = []
    for fir, group in grouped.items():
        pages = sorted(set(group["pages"]))
        page_text = (
            f"CFP p{pages[0]}"
            if len(pages) == 1
            else f"CFP pp{pages[0]}-{pages[-1]}"
            if pages
            else "CFP page unavailable"
        )
        parts.append(f"{fir} {'/'.join(group['actm'])} ({page_text})")
    if not parts:
        return (
            "No FIR boundary ACTM row is held in the parsed CFP; contact "
            "procedure/frequency unavailable."
        )
    return (
        " | ".join(parts)
        + ". Contact procedure/frequency unavailable; no lead or frequency is inferred."
    )


def _communication_timeline(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    timing_view: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    boundaries = _fir_boundary_rows(flight)
    if timing_view:
        return boundaries + [
            {
                "time": event.get("utc_clock") or event.get("utc_display") or "--",
                "actm": event.get("actm") or "--.--",
                "event": str(event.get("label") or ""),
                "detail": str(event.get("details") or ""),
            }
            for event in (timing_view.get("early_calls") or [])
        ]

    timeline = list(boundaries)
    for item in findings:
        if item.get("engine") != "communications":
            continue
        actm = item.get("data", {}).get("action_actm_minutes")
        timeline.append({
            "time": f"ACTM {format_actm(actm)}" if actm is not None else "ACTM --.--",
            "actm": format_actm(actm),
            "event": str(item.get("title") or ""),
            "detail": str(item.get("summary") or ""),
        })
    return timeline


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
    if classification.startswith("NON"):
        rows.append(("GATE", _edto_gate_sentence(edto_view)))
        return rows
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
                    str(airport.get("minima") or "").strip(),
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


def _validated_profile_coverage(
    terrain_events: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> tuple[int, int]:
    """Return how many current terrain windows have a controlled match.

    A depressurisation result belongs to a particular detected terrain event.
    Requiring that identity prevents a complete-but-stale result from another
    route window from making the current briefing appear fully matched.  A
    duplicate finding for one event also counts only once.
    """
    event_ids = {
        str(event.get("terrain_event_id") or "").strip()
        for event in terrain_events
        if str(event.get("terrain_event_id") or "").strip()
    }
    matched_event_ids = {
        str((item.get("data") or {}).get("terrain_event_id") or "").strip()
        for item in findings
        if item.get("engine") == "depressurisation"
        and bool((item.get("data") or {}).get("chart_number"))
        and (item.get("data") or {}).get("coverage_complete") is True
        and (item.get("data") or {}).get("reference_status")
        == "controlled-index-loaded"
        and str((item.get("data") or {}).get("terrain_event_id") or "").strip()
        in event_ids
    }
    return len(matched_event_ids), len(terrain_events)


def _terrain_summary(
    terrain_events: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> str:
    """Compose one source-backed terrain sentence naming every active window.

    Names and values come from the same detected events the page renders, so
    surfaces cannot disagree or substitute route-specific wording.
    """
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
    match_count, event_count = _validated_profile_coverage(terrain_events, findings)
    if match_count == event_count:
        return (
            f"{label}; {match_count}/{event_count} terrain windows have "
            "validated profile matches on the terrain page"
        )
    unmatched_count = event_count - match_count
    return (
        f"{label}; {match_count}/{event_count} terrain windows have validated "
        "profile matches - manual review required for "
        f"{unmatched_count} unmatched terrain "
        f"window{'s' if unmatched_count != 1 else ''}"
    )


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


_WEATHER_CHART_KINDS = {
    "sigwx_high_level",
    "sigwx_mid_level",
    "wind_temperature",
}
_WEATHER_CHART_SHARED_FIELDS = (
    "chart_number",
    "page_number",
    "kind",
    "issuer",
    "wmo_heading",
    "valid_time_utc",
    "flight_levels",
    "title",
    "confidence",
    "label",
    "image_sha256",
    "image_width",
    "image_height",
    "source",
)
_WEATHER_CHART_WINDOW_TOLERANCE = timedelta(0)

_ISO_UTC_DISPLAY_TOKEN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})\b"
)


def _weather_chart_display_label(
    chart: dict[str, Any],
    *,
    valid_time: datetime,
) -> tuple[str, str]:
    """Derive cockpit-readable text while preserving raw source fields."""
    validity = valid_time.strftime("%d %b %H%MZ").upper()
    source_label = str(chart.get("label") or "").strip()
    if source_label:
        display_label = _ISO_UTC_DISPLAY_TOKEN.sub(
            lambda match: _display_utc(match.group(0)),
            source_label,
        )
    else:
        kind = str(chart.get("kind") or "chart").strip().lower()
        kind_label = (
            "SIGWX"
            if kind.startswith("sigwx")
            else kind.replace("_", " ").upper()
        )
        levels = str(chart.get("flight_levels") or "").strip()
        display_label = " · ".join(
            part for part in (kind_label, levels, f"VALID {validity}") if part
        )
    return display_label, validity


def _weather_chart_selection(
    weather_charts: dict[str, Any] | None,
    flight: dict[str, Any],
) -> dict[str, Any]:
    """Project only explicitly governed route-context chart matches.

    Detection and visual classification alone do not prove that a fixed-time
    product covers this flight's route. A future governed matcher may attach
    ``route_context={status: "matched", governed: true, basis: "..."}`` to a
    classified chart. Until that explicit evidence exists, the held source
    pages remain in the raw manifest but the shared briefing selects none.
    """
    manifest = weather_charts or {}
    manifest_status = str(manifest.get("status") or "").strip().lower()
    charts = list(manifest.get("charts") or [])
    held_pages = sorted({
        int(chart["page_number"])
        for chart in charts
        if isinstance(chart, dict)
        and isinstance(chart.get("page_number"), int)
    })
    coverage = (weather_charts or {}).get("coverage") or {}
    if (
        isinstance(coverage, dict)
        and coverage.get("classification_incomplete") is True
    ):
        held_count = int(coverage.get("held_chart_count") or len(charts))
        capacity = int(coverage.get("classification_capacity") or 0)
        return {
            "status": "manual-review-required",
            "reason": (
                f"Chart classification coverage is incomplete: {held_count} "
                f"held pages exceed the {capacity}-page analysis capacity; "
                "all held pages remain available for manual review."
            ),
            "selected_charts": [],
            "raw_chart_count": len(charts),
            "held_pages": held_pages,
            "classification_incomplete": True,
        }
    departure_utc = _parse_utc(flight.get("scheduled_departure_utc"))
    arrival_utc = _parse_utc(flight.get("scheduled_arrival_utc"))
    midpoint = (
        departure_utc + (arrival_utc - departure_utc) / 2
        if departure_utc and arrival_utc
        else None
    )

    def flight_key(value: Any) -> str:
        # Carrier-code aliases need their own governed operator registry.
        # Until one is supplied, compare only the exact printed identifier;
        # silently translating one airline's ICAO code would be a
        # sample-specific publication rule.
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    governed_matches: list[
        tuple[tuple[Any, ...], tuple[str, str], dict[str, Any]]
    ] = []
    outside_matches: list[tuple[float, str]] = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        route_context = chart.get("route_context") or {}
        if not isinstance(route_context, dict) or chart.get("verified") is not True:
            continue
        governed_context: dict[str, Any] | None = None
        if (
            chart.get("classification_status") == "classified"
            and chart.get("kind") in _WEATHER_CHART_KINDS
            and route_context.get("status") == "matched"
            and route_context.get("governed") is True
            and str(route_context.get("basis") or "").strip()
        ):
            governed_context = {
                **route_context,
                "status": "matched",
                "governed": True,
                "basis": str(route_context["basis"]).strip(),
            }
        elif (
            chart.get("classification_status") == "ocr-classified"
            and route_context.get("status") == "printed"
            and route_context.get("source") == "tesseract_ocr"
            and route_context.get("chart_kind")
            in {"sigwx_high_level", "sigwx_mid_level"}
            and flight_key(route_context.get("flight_number"))
            == flight_key(flight.get("flight_number"))
            and str(route_context.get("departure_iata") or "").upper()
            == str(flight.get("departure_iata") or "").upper()
            and str(route_context.get("destination_iata") or "").upper()
            == str(flight.get("destination_iata") or "").upper()
        ):
            governed_context = {
                **route_context,
                "status": "matched",
                "governed": True,
                "basis": (
                    "Printed chart flight and route identity match the CFP; "
                    "validity ranked against the CFP flight window."
                ),
            }
        if governed_context is None:
            continue
        valid_time = _parse_utc(
            governed_context.get("valid_time_utc")
            or chart.get("valid_time_utc")
        )
        if valid_time is None:
            continue
        inside_window = bool(
            departure_utc
            and arrival_utc
            and departure_utc - _WEATHER_CHART_WINDOW_TOLERANCE
            <= valid_time
            <= arrival_utc + _WEATHER_CHART_WINDOW_TOLERANCE
        )
        if inside_window and midpoint:
            distance = abs((valid_time - midpoint).total_seconds())
        elif departure_utc and arrival_utc:
            distance = min(
                abs((valid_time - departure_utc).total_seconds()),
                abs((valid_time - arrival_utc).total_seconds()),
            )
        else:
            distance = 0.0
        if not inside_window:
            if departure_utc and valid_time < departure_utc:
                outside_matches.append((
                    abs((departure_utc - valid_time).total_seconds()),
                    "before-departure",
                ))
            elif arrival_utc and valid_time > arrival_utc:
                outside_matches.append((
                    abs((valid_time - arrival_utc).total_seconds()),
                    "after-arrival",
                ))
            continue
        projection = {
            key: chart.get(key)
            for key in _WEATHER_CHART_SHARED_FIELDS
            if key in chart
        }
        projection["route_context"] = governed_context
        display_label, valid_time_display = _weather_chart_display_label(
            chart,
            valid_time=valid_time,
        )
        projection["display_label"] = display_label
        projection["valid_time_display"] = valid_time_display
        product_kind = str(chart.get("kind") or "").strip().lower()
        raw_levels = str(
            governed_context.get("flight_levels")
            or chart.get("flight_levels")
            or ""
        )
        level_numbers = re.findall(r"\d{2,3}", raw_levels)
        level_family = (
            "-".join(str(int(value)) for value in level_numbers)
            if level_numbers
            else re.sub(r"[^A-Z0-9]+", "", raw_levels.upper()) or "UNSPECIFIED"
        )
        governed_matches.append((
            (
                0 if inside_window else 1,
                distance,
                int(chart.get("page_number") or 0),
                int(chart.get("chart_number") or 0),
            ),
            (product_kind, level_family),
            projection,
        ))
    governed_matches.sort(key=lambda item: item[0])
    if governed_matches:
        selected_charts: list[dict[str, Any]] = []
        selected_families: set[tuple[str, str]] = set()
        for _, family, projection in governed_matches:
            if family in selected_families:
                continue
            selected_families.add(family)
            selected_charts.append(projection)
        return {
            "status": "selected",
            "reason": (
                "Governed route-context chart selected inside the CFP flight window."
                if len(selected_charts) == 1
                else (
                    "Nearest governed route-context chart selected inside the CFP "
                    "flight window for each distinct product and flight-level family."
                )
            ),
            "selected_charts": selected_charts,
            "raw_chart_count": len(charts),
            "held_pages": held_pages,
        }
    if outside_matches:
        delta_seconds, relation = min(outside_matches, key=lambda item: item[0])
        delta_minutes = int(delta_seconds // 60)
        return {
            "status": "manual-review-required",
            "reason": (
                "No governed route-context chart is valid inside the CFP "
                f"flight window; closest printed validity is {delta_minutes} "
                f"minutes {relation.replace('-', ' ')}."
            ),
            "selected_charts": [],
            "raw_chart_count": len(charts),
            "held_pages": held_pages,
            "closest_validity_delta_minutes": delta_minutes,
            "closest_validity_relation": relation,
        }
    if charts:
        return {
            "status": "manual-review-required",
            "reason": "No governed route-context classification is available.",
            "selected_charts": [],
            "raw_chart_count": len(charts),
            "held_pages": held_pages,
        }
    if manifest_status == "none_detected":
        return {
            "status": "none-detected",
            "reason": "No weather-chart appendix was detected in the uploaded package.",
            "selected_charts": [],
            "raw_chart_count": 0,
            "held_pages": [],
        }
    return {
        "status": "unavailable",
        "reason": (
            "Weather-chart detection is unavailable; appendix presence was "
            "not established from the uploaded package."
        ),
        "selected_charts": [],
        "raw_chart_count": 0,
        "held_pages": [],
        "detection_error": str(manifest.get("error") or "") or None,
    }


def _vaac_reach_summary(flight: dict[str, Any]) -> dict[str, Any]:
    """Direct-VAAC reach, composed once for every surface.

    The tally and the per-centre strings were previously arithmetic inside
    the PDF renderer, so the dashboard never showed them; both surfaces now
    print these composed values verbatim."""
    ledger = (flight.get("vaa_review") or {}).get("vaac_centre_ledger") or []
    status_copy = {
        "available": "reached",
        "partial": "partial",
        "unavailable": "unavailable",
        "not_mounted": "not mounted",
    }
    centres = [
        {
            "centre": str(item.get("centre") or "UNKNOWN").upper(),
            "status": status_copy.get(str(item.get("status") or "").lower(), "unavailable"),
        }
        for item in ledger
    ]
    reached = sum(1 for item in ledger if item.get("status") in {"available", "partial"})

    # The responsible centres for THIS route, from the ICAO Doc 9766 Part 2
    # areas (boss, 21 Aug: "there's a VAAC ... in Manila? ... don't see any
    # [checking]"). Fail-closed: unsettled route geometry flags a review
    # instead of naming a centre it cannot prove.
    from .vaac_areas import responsible_vaac_centres

    waypoints = flight.get("route_waypoints") or []
    route_points = [
        (waypoint.get("latitude"), waypoint.get("longitude"))
        for waypoint in waypoints
        if isinstance(waypoint.get("latitude"), (int, float))
        and isinstance(waypoint.get("longitude"), (int, float))
    ]
    route_firs = [
        waypoint.get("fir_boundary")
        for waypoint in waypoints
        if waypoint.get("fir_boundary")
    ]
    responsibility = responsible_vaac_centres(route_points, route_firs)
    reached_names = {
        str(item.get("centre") or "").upper()
        for item in ledger
        if item.get("status") in {"available", "partial"}
    }
    responsible_rows = [
        {"centre": centre, "reached": centre in reached_names}
        for centre in responsibility["centres"]
    ]
    if not route_points:
        responsible_line = (
            "Responsible VAAC for this route is unresolved - no route "
            "coordinates are held; review coverage directly."
        )
    elif responsible_rows:
        named = ", ".join(row["centre"] for row in responsible_rows)
        missing = [row["centre"] for row in responsible_rows if not row["reached"]]
        responsible_line = (
            f"Responsible for this route: {named}"
            + (
                " - all reached"
                if not missing
                else f" - NOT reached: {', '.join(missing)} (review gap)"
            )
            + (
                "; boundary segments need review"
                if responsibility["review_required"]
                else ""
            )
        )
    else:
        responsible_line = (
            "Responsible VAAC for this route could not be settled from the "
            "Doc 9766 areas - review coverage directly."
        )

    return {
        "summary": f"{reached}/{len(ledger) or 9} reached",
        "centres": centres,
        "responsible": responsible_rows,
        "responsible_line": responsible_line,
        "responsible_review_required": bool(responsibility["review_required"]) or not responsible_rows,
        "responsible_source": responsibility["source"],
    }


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
        f"planned {levels}. Flight-analysis screening of the CFP advisory polygon - {tail}"
    )


def _va_cfp_advisories(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Named volcanic-ash advisories captured verbatim from the CFP.

    The name line is the label the 18 Aug defect was missing: the hazard is
    called VOLCANIC ASH with its volcano and SIGMET identity, never a generic
    "1 CFP advisory"."""
    advisories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for advisory in flight.get("volcanic_advisories") or []:
        volcano = str(advisory.get("volcano") or "UNNAMED VOLCANO").strip().upper()
        notam_id = str(advisory.get("notam_id") or "").strip().upper()
        text = str(advisory.get("text") or "").strip()
        key = " ".join(part for part in (volcano, notam_id, text) if part)
        if not text or key in seen:
            continue
        seen.add(key)
        advisories.append({
            "name": " · ".join(
                part
                for part in ("CFP VOLCANO ADVISORY", volcano, notam_id)
                if part
            ),
            "derived": (
                "Source-held CFP notice; operational applicability remains "
                "a crew/dispatch review."
            ),
            "text": text,
            "fir": None,
            "valid_from": _display_utc(advisory.get("valid_from_utc")),
            "valid_to": _display_utc(advisory.get("valid_to_utc")),
            "source_page": advisory.get("source_page"),
            "advisory_kind": "CFP_VAA_NOTICE",
            "volcano": volcano,
            "notam_id": notam_id,
        })
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
            "advisory_kind": "VA_SIGMET",
        })
    return advisories


def _overview_forecast_at_reference(
    findings: list[dict[str, Any]],
    *,
    location: str,
    phase: str,
) -> dict[str, Any] | None:
    """Return the engine-decoded conditions for one flight reference time.

    This deliberately does not parse raw METAR/TAF text. The weather engine
    owns time applicability; publishing surfaces receive its bounded result.
    """
    candidates = []
    for item in findings:
        data = item.get("data") or {}
        if (
            item.get("engine") == "weather"
            and str(data.get("location") or "").upper() == location.upper()
            and str(data.get("phase") or "").casefold() == phase.casefold()
            and str(data.get("applicable_conditions") or "").strip()
        ):
            candidates.append(data)
    if not candidates:
        return None
    # A TAF group is the engine's forecast-at-reference result. Retain input
    # ordering as the deterministic tie-break when multiple windows exist.
    selected = next(
        (
            item
            for item in candidates
            if "TAF" in {
                str(record_type or "").upper()
                for record_type in item.get("record_types") or []
            }
        ),
        candidates[0],
    )
    return {
        "applicable_conditions": str(selected["applicable_conditions"]).strip(),
        "utc_window": selected.get("utc_window"),
        "timing": selected.get("timing"),
        "window_status": selected.get("window_status"),
        "source_references": list(selected.get("source_references") or []),
    }


def _overview_primary_highlight(
    panels: list[dict[str, Any]],
    *,
    role_key: str,
) -> dict[str, Any] | None:
    panel = next(
        (
            item
            for item in panels
            if role_key in (item.get("role_keys") or [])
        ),
        None,
    )
    if panel is None:
        return None
    family_order = (
        {
            "approach_navaid": 0,
            "runway_closure": 1,
            "runway_restriction": 2,
        }
        if role_key == "departure"
        else {
            "approach_navaid": 0,
            "runway_closure": 1,
            "runway_restriction": 2,
        }
    )
    notices = [
        line
        for line in panel.get("card_summary_lines") or []
        if line.get("kind") == "notam"
        and not line.get("different_runway")
        and str(line.get("text") or "").strip()
    ]
    if not notices:
        return None
    _, selected = min(
        enumerate(notices),
        key=lambda pair: (
            family_order.get(str(pair[1].get("signal_family") or ""), 99),
            pair[0],
        ),
    )
    return {
        "text": str(selected["text"]).strip(),
        "signal_family": selected.get("signal_family"),
        "notam_id": selected.get("notam_id"),
        "source_page": selected.get("source_page"),
    }


def _overview_plan(runway: Any, procedure: Any) -> dict[str, Any]:
    runway_text = str(runway or "").strip() or None
    procedure_text = str(procedure or "").strip() or None
    display = " / ".join(
        part
        for part in (
            f"RWY {runway_text}" if runway_text else None,
            procedure_text,
        )
        if part
    )
    return {
        "runway": runway_text,
        "procedure": procedure_text,
        "display": display or "--",
    }


def _overview_schedule(value: Any, actm_minutes: int) -> dict[str, Any]:
    raw = str(value or "").strip() or None
    return {
        "scheduled_utc": raw,
        "display_utc": _display_utc(raw),
        "actm_minutes": actm_minutes,
    }


def _overview_anchor(
    *,
    kind: str,
    label: str,
    detail: str,
    actm_minutes: int | None,
    departure_utc: datetime | None,
    exact_utc: datetime | None = None,
) -> dict[str, Any]:
    moment = exact_utc
    if moment is None and departure_utc is not None and actm_minutes is not None:
        moment = departure_utc + timedelta(minutes=actm_minutes)
    return {
        "kind": kind,
        "label": label,
        "detail": detail,
        "actm_minutes": actm_minutes,
        "actm_display": format_actm(actm_minutes),
        "utc": moment.isoformat() if moment else None,
        "utc_display": moment.strftime("%H%MZ") if moment else "--",
    }


def _overview_projection(
    flight: dict[str, Any],
    source_findings: list[dict[str, Any]],
    airport_operational_panels: list[dict[str, Any]],
    terrain_events: list[dict[str, Any]],
    final_actm: int,
    destination_actm: int | None,
    timing_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared, source-backed contract for the compact route overview."""
    chips: list[dict[str, Any]] = []

    def add_chip(key: str, label: str, value: Any, source_field: str) -> None:
        if value is None or value == "":
            return
        chips.append({
            "key": key,
            "label": label,
            "value": value,
            "source_field": source_field,
        })

    route_identifier = str(flight.get("route_identifier") or "").strip()
    plan_number = str(flight.get("plan_number") or "").strip()
    # Route ID with its version (boss, 21 Aug: "I need the route ID and the
    # route version") — the chip every surface prints.
    add_chip(
        "route_identifier",
        f"{route_identifier} P{plan_number}" if route_identifier and plan_number else route_identifier,
        route_identifier,
        "route_identifier",
    )
    edto_rvsm = str(flight.get("edto_rvsm") or "").strip()
    add_chip("edto_rvsm", edto_rvsm, edto_rvsm, "edto_rvsm")
    # Keep the page-1 CFP classification independent from its printed FLT
    # RULES token. A STANDARD/NON EDTO flight can still print RVSM; those are
    # two different source facts and both must remain visible. Older EDTO
    # packages can omit EDTO from the separate rule token, so retain that
    # classification fallback without duplicating an already printed EDTO.
    source_classification = str(
        (flight.get("fuel_summary") or {}).get("source_classification") or ""
    ).strip().upper()
    if source_classification in {"STANDARD", "NON EDTO"}:
        add_chip(
            "classification",
            "NON-EDTO",
            source_classification,
            "fuel_summary.source_classification",
        )
    elif source_classification == "EDTO" and "EDTO" not in edto_rvsm.upper():
        add_chip(
            "classification",
            "EDTO",
            source_classification,
            "fuel_summary.source_classification",
        )
    cost_index = flight.get("cost_index")
    add_chip("cost_index", f"CI {cost_index}", cost_index, "cost_index")
    apd_percent = flight.get("apd_percent")
    add_chip(
        "apd_percent",
        f"APD {apd_percent}%",
        apd_percent,
        "apd_percent",
    )
    cruise_wind = (flight.get("fuel_summary") or {}).get("cruise_wind_component_kt")
    if cruise_wind is not None:
        add_chip(
            "cruise_wind_component",
            f"CRZ {'M' if cruise_wind < 0 else 'P'}{abs(int(cruise_wind))}",
            cruise_wind,
            "fuel_summary.cruise_wind_component_kt",
        )

    departure_icao = str(flight.get("departure") or "").upper()
    destination_icao = str(flight.get("destination") or "").upper()
    departure_utc = _parse_utc(flight.get("scheduled_departure_utc"))
    arrival_utc = _parse_utc(flight.get("scheduled_arrival_utc"))
    actual_departure_utc = (
        _parse_utc(timing_view.get("actual_takeoff_utc"))
        if timing_view
        else None
    )
    timeline_departure_utc = actual_departure_utc or departure_utc
    timeline_arrival_utc = (
        timeline_departure_utc + timedelta(minutes=destination_actm)
        if actual_departure_utc is not None
        and timeline_departure_utc is not None
        and destination_actm is not None
        else (arrival_utc if actual_departure_utc is None else None)
    )

    departure = {
        "icao": departure_icao,
        "iata": flight.get("departure_iata"),
        "plan": _overview_plan(flight.get("departure_runway"), flight.get("sid")),
        "schedule": _overview_schedule(flight.get("scheduled_departure_utc"), 0),
        "forecast_at_reference": _overview_forecast_at_reference(
            source_findings,
            location=departure_icao,
            phase="Departure",
        ),
        "primary_operational_highlight": _overview_primary_highlight(
            airport_operational_panels,
            role_key="departure",
        ),
    }
    destination = {
        "icao": destination_icao,
        "iata": flight.get("destination_iata"),
        "plan": _overview_plan(
            flight.get("destination_runway"),
            flight.get("star"),
        ),
        "schedule": _overview_schedule(
            flight.get("scheduled_arrival_utc"),
            destination_actm if destination_actm is not None else final_actm,
        ),
        "forecast_at_reference": _overview_forecast_at_reference(
            source_findings,
            location=destination_icao,
            phase="Destination",
        ),
        "primary_operational_highlight": _overview_primary_highlight(
            airport_operational_panels,
            role_key="destination",
        ),
    }

    timeline = [
        _overview_anchor(
            kind="departure",
            label="DEP",
            detail=departure_icao or "--",
            actm_minutes=0,
            departure_utc=timeline_departure_utc,
            exact_utc=timeline_departure_utc,
        )
    ]
    edto = flight.get("edto") or {}
    sectors = edto_sectors(edto)
    edto_entry = (
        sectors[0].get("entry_actm_minutes")
        if sectors
        else edto.get("entry_actm_minutes")
    )
    if edto_entry is not None:
        timeline.append(_overview_anchor(
            kind="edto",
            label="EDTO",
            detail="ENTRY",
            actm_minutes=int(edto_entry),
            departure_utc=timeline_departure_utc,
        ))

    vws_events = detect_vws_events(flight.get("route_waypoints") or [])
    if vws_events:
        vws_point = vws_events[0].get("first_high") or {}
        # When the very same point is already a strict-terrain anchor, the
        # compact timeline avoids printing two labels at one position.
        if int(vws_point.get("msa_hundreds_ft") or 0) <= 100:
            vws_actm = vws_point.get("actm_minutes")
            if vws_actm is not None:
                timeline.append(_overview_anchor(
                    kind="vws",
                    label=str(vws_point.get("name") or "VWS").lstrip("-"),
                    detail=f"VWS {int(vws_point.get('vws') or 0):03d}",
                    actm_minutes=int(vws_actm),
                    departure_utc=timeline_departure_utc,
                ))

    for event in terrain_events:
        first = event.get("first_high") or {}
        last = event.get("last_high") or first
        event_actm = first.get("actm_minutes")
        if event_actm is None:
            continue
        first_name = str(first.get("name") or "TERRAIN").lstrip("-")
        last_name = str(last.get("name") or first_name).lstrip("-")

        def msa_text(point: dict[str, Any]) -> str:
            value = point.get("msa_hundreds_ft")
            if value is None:
                return "---"
            suffix = "*" if point.get("msa_asterisk") else ""
            return f"{int(value):03d}{suffix}"

        timeline.append(_overview_anchor(
            kind="terrain",
            label=(first_name if first_name == last_name else f"{first_name}-{last_name}"),
            detail=(
                msa_text(first)
                if first_name == last_name
                else f"{msa_text(first)}-{msa_text(last)}"
            ),
            actm_minutes=int(event_actm),
            departure_utc=timeline_departure_utc,
        ))

    timeline.append(_overview_anchor(
        kind="arrival",
        label="ARR",
        detail=destination_icao or "--",
        actm_minutes=destination_actm,
        departure_utc=timeline_departure_utc,
        exact_utc=timeline_arrival_utc,
    ))
    timeline.sort(key=lambda item: (
        item["actm_minutes"] is None,
        item["actm_minutes"] if item["actm_minutes"] is not None else 0,
        {"departure": 0, "edto": 1, "vws": 2, "terrain": 3, "arrival": 4}.get(
            item["kind"],
            99,
        ),
    ))
    return {
        "chips": chips,
        "departure": departure,
        "destination": destination,
        "timeline": timeline,
    }


def _finding_source_reference(item: dict[str, Any]) -> str:
    """One short, traceable source label for a ranked decision finding."""
    data = item.get("data") or {}
    notam_id = str(data.get("notam_id") or "").strip().upper()
    source_references = list(
        data.get("source_references")
        or item.get("source_references")
        or []
    )
    if source_references:
        source = source_references[0] or {}
        title = str(
            source.get("display_title")
            or source.get("document_title")
            or source.get("source_type")
            or "Source"
        ).strip()
        pages = [
            int(page)
            for page in source.get("pages") or []
            if isinstance(page, int) or str(page).isdigit()
        ]
        section = str(source.get("section") or "").strip()
        return " · ".join(
            part
            for part in (
                notam_id or None,
                title or None,
                f"p{','.join(str(page) for page in pages)}" if pages else None,
                section or None,
            )
            if part
        )
    source_page = data.get("source_page") or item.get("source_page")
    return " · ".join(
        part
        for part in (
            notam_id or None,
            f"CFP p{source_page}" if isinstance(source_page, int) else None,
            f"{str(item.get('engine') or 'analysis').upper()} deterministic assessment",
        )
        if part
    )


def _decision_finding_projection(
    findings: list[dict[str, Any]],
    *,
    limit: int = 6,
    performance_rows: list[dict[str, str]] | None = None,
    deferred_gates: list[dict[str, Any]] | None = None,
    airport_panels: list[dict[str, Any]] | None = None,
    coverage_rows: list[dict[str, str]] | None = None,
    route_airspace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Severity-ranked findings with their source and evidence destination."""
    target_by_engine = {
        "performance": "sec_performance",
        "performance_reconciliation": "sec_performance",
        "qa": "sec_performance",
        "page1": "sec_overview",
        "mel": "sec_mel_cdl",
        "cddl": "sec_mel_cdl",
        "deferred_declaration": "sec_mel_cdl",
        "deferred_dispatch_gate": "sec_mel_cdl",
        "arrival_ground": "sec_airports",
        "alternate_weather": "sec_hazard",
        "weather_coverage": "sec_hazard",
        "notam": "sec_airports",
        "weather": "sec_hazard",
        "sigmet": "sec_hazard",
        "vaa": "sec_hazard",
        "tropical_cyclone": "sec_hazard",
        "communications": "sec_enroute",
        "route_airspace": "sec_enroute",
        "bobcat": "sec_enroute",
        "edto": "sec_enroute",
        # The compact renderer aliases ``sec_terrain`` to Enroute / Assurance
        # when no annex exists, and to the real appendix when terrain or a
        # controlled profile is held.
        "terrain": "sec_terrain",
        "vws": "sec_terrain",
        "depressurisation": "sec_terrain",
    }
    material_rows: list[dict[str, Any]] = []
    performance_open = next(
        (
            row
            for row in performance_rows or []
            if str(row.get("status") or "").upper() == "OPEN"
        ),
        None,
    )
    if performance_open:
        material_rows.append({
            "engine": "performance_reconciliation",
            "severity": "warning",
            "title": str(
                performance_open.get("label")
                or "Performance reconciliation open"
            ),
            "summary": str(
                performance_open.get("detail")
                or "Performance reconciliation requires review."
            ),
            "source_reference": str(
                performance_open.get("source_reference")
                or "Uploaded CFP performance inputs"
            ),
            "data": {"priority_score": 100},
        })

    route_airspace = route_airspace or {}
    if route_airspace.get("record_count"):
        military_record = route_airspace.get("military_source_record") or {}
        military_note = (
            f" Military-training record {military_record.get('notam_id')} is "
            "source-held."
            if str(military_record.get("notam_id") or "").strip()
            else ""
        )
        material_rows.append({
            "engine": "route_airspace",
            "severity": "warning",
            "title": "Route airspace source review",
            "summary": (
                f"{route_airspace.get('record_count')} source-held route-airspace "
                f"notice(s) ({route_airspace.get('source_page_text')})."
                f"{military_note} Confirm route/level applicability and any "
                "ATC-clearance effect against current controlled products; no "
                "polygon intersection is inferred."
            ),
            "source_reference": (
                "Uploaded CFP · route-airspace notice package · "
                f"{route_airspace.get('source_page_text')}"
            ),
            "data": {"priority_score": 95},
        })

    def deferred_gate_priority(gate: dict[str, Any]) -> tuple[int, int, str]:
        category = str(gate.get("category") or "").lower().replace("-", "_")
        summary = str(gate.get("summary") or "").upper()
        operational = category in {"in", "operational_restriction"}
        before_each_departure = "PRIOR EVERY DEPARTURE" in summary
        category_rank = {
            "in": 4,
            "operational_restriction": 4,
            "mel": 3,
            "cddl": 2,
            "cdl": 2,
            "ifeddl": 1,
        }.get(category, 0)
        return (
            int(before_each_departure or operational),
            category_rank,
            str(gate.get("title") or ""),
        )

    material_gate = max(
        (gate for gate in deferred_gates or [] if isinstance(gate, dict)),
        key=deferred_gate_priority,
        default=None,
    )
    if material_gate:
        declarations = [
            str(segment.get("source_declaration") or "").strip()
            for segment in material_gate.get("source_segments") or []
            if isinstance(segment, dict)
            and str(segment.get("source_declaration") or "").strip()
        ]
        material_rows.append({
            "engine": "deferred_dispatch_gate",
            "severity": "warning",
            "title": (
                f"{material_gate.get('title') or 'Deferred item'} - "
                "dispatch confirmation"
            ),
            "summary": str(
                material_gate.get("summary")
                or "Dispatch confirmation is required."
            ),
            "source_reference": " · ".join(
                part
                for part in (
                    "Uploaded CFP deferred declaration",
                    ", ".join(declarations) or None,
                )
                if part
            ),
            "data": {"priority_score": 90},
        })

    destination_panel = next(
        (
            panel
            for panel in airport_panels or []
            if "destination" in set(panel.get("role_keys") or [])
        ),
        None,
    )
    resolved_notam_ids = {
        str(line.get("notam_id") or "").upper()
        for panel in airport_panels or []
        for line in panel.get("card_summary_lines") or []
        if isinstance(line, dict)
        and str(line.get("notam_id") or "").strip()
        and any(
            phrase in str(line.get("text") or "").lower()
            for phrase in (
                "precedes closure",
                "ends before",
                "after the closure",
            )
        )
    }
    if destination_panel:
        ground_lines = [
            line
            for line in destination_panel.get("card_summary_lines") or []
            if isinstance(line, dict)
            and str(line.get("kind") or "").lower() == "notam"
            and str(line.get("signal_family") or "")
            in {
                "runway_restriction",
                "runway_closure",
                "taxiway",
                "apron_stand",
            }
        ][:2]
        bay_cranes = [
            item
            for item in destination_panel.get("selected_notams") or []
            if isinstance(item, dict)
            and re.search(
                r"PRKG\s+BAY\s+NR\s+\d+",
                str(item.get("item_e_text") or ""),
                re.IGNORECASE,
            )
            and "CRANE" in str(item.get("item_e_text") or "").upper()
        ]

        def bay_crane_priority(
            item: dict[str, Any],
        ) -> tuple[int, float, float, int, str]:
            valid_from = _parse_utc(item.get("valid_from_utc"))
            valid_to = _parse_utc(item.get("valid_to_utc"))
            window_start = _parse_utc(item.get("window_start_utc"))
            window_end = _parse_utc(item.get("window_end_utc"))
            overlaps_window = bool(
                valid_from
                and valid_to
                and window_start
                and window_end
                and valid_from < window_end
                and valid_to > window_start
            )
            duration = (
                (valid_to - valid_from).total_seconds()
                if valid_from and valid_to and valid_to >= valid_from
                else float("inf")
            )
            distance = float("inf")
            if valid_from and valid_to and window_start and window_end:
                validity_midpoint = valid_from + (valid_to - valid_from) / 2
                window_midpoint = window_start + (window_end - window_start) / 2
                distance = abs((validity_midpoint - window_midpoint).total_seconds())
            return (
                0 if overlaps_window else 1,
                duration,
                distance,
                int(item.get("pertinence_rank") or 99),
                str(item.get("notam_id") or ""),
            )

        bay_crane = min(bay_cranes, key=bay_crane_priority, default=None)
        ground_parts = [
            " - ".join(
                part
                for part in (
                    str(line.get("label") or "NOTICE").strip(),
                    str(line.get("text") or "").strip(),
                )
                if part
            )
            for line in ground_lines
        ]
        source_pages = {
            int(line["source_page"])
            for line in ground_lines
            if isinstance(line.get("source_page"), int)
        }
        if bay_crane:
            raw = str(bay_crane.get("item_e_text") or "")
            bay = re.search(r"PRKG\s+BAY\s+NR\s+(\d+)", raw, re.IGNORECASE)
            crane = re.search(
                r"CRANE\s+WITH\s+BOOM\s+HGT\s+APRX\s+(\d+)FT",
                raw,
                re.IGNORECASE,
            )
            ground_parts.append(
                " - ".join(
                    part
                    for part in (
                        str(bay_crane.get("notam_id") or "NOTICE"),
                        (
                            f"Bay {bay.group(1)} WIP with approx "
                            f"{crane.group(1)} ft crane during the destination window."
                            if bay and crane
                            else str(bay_crane.get("summary") or "").strip()
                        ),
                    )
                    if part
                )
            )
            if isinstance(bay_crane.get("source_page"), int):
                source_pages.add(int(bay_crane["source_page"]))
        if ground_parts:
            icao = str(destination_panel.get("icao") or "DESTINATION")
            material_rows.append({
                "engine": "arrival_ground",
                "severity": "warning",
                "title": f"{icao} arrival ground constraints",
                "summary": " | ".join(ground_parts),
                "source_reference": (
                    "Uploaded CFP · "
                    + ",".join(f"p{page}" for page in sorted(source_pages))
                    + " · Destination NOTAM package"
                ),
                "data": {"priority_score": 95},
            })

    alternate_icaos = {
        str(panel.get("icao") or "").upper()
        for panel in airport_panels or []
        if "alternate" in set(panel.get("role_keys") or [])
    }

    def alternate_weather_priority(item: dict[str, Any]) -> tuple[int, int, int]:
        data = item.get("data") or {}
        mechanism = str(data.get("mechanism") or "").upper()
        hazard_score = sum(
            weight
            for phrase, weight in (
                ("CONVECTION", 5),
                ("THUNDERSTORM", 5),
                ("LOW CLOUD", 4),
                ("CEILING", 4),
                ("GUST", 3),
                ("RAIN", 1),
            )
            if phrase in mechanism
        )
        return (
            _SEVERITY_RANK.get(
                str(item.get("severity") or "information"),
                0,
            ),
            hazard_score,
            -len(str(item.get("summary") or "")),
        )

    alternate_weather = max(
        (
            item
            for item in findings
            if str(item.get("engine") or "") == "weather"
            and str((item.get("data") or {}).get("location") or "").upper()
            in alternate_icaos
        ),
        key=alternate_weather_priority,
        default=None,
    )
    if alternate_weather:
        alternate_location = str(
            (alternate_weather.get("data") or {}).get("location") or ""
        ).upper()
        alternate_panel = next(
            (
                panel
                for panel in airport_panels or []
                if str(panel.get("icao") or "").upper() == alternate_location
            ),
            None,
        )
        source_weather = (alternate_panel or {}).get("weather") or {}
        source_records = [
            (label, record)
            for label, record in (
                ("METAR", source_weather.get("metar")),
                ("TAF", source_weather.get("taf")),
            )
            if isinstance(record, dict)
            and str(record.get("text") or "").strip()
            and isinstance(record.get("source_page"), int)
        ]
        source_pages = sorted({
            int(record["source_page"])
            for _, record in source_records
        })
        source_reference = (
            "Uploaded company CFP · "
            + ",".join(f"p{page}" for page in source_pages)
            + " · Airport weather list"
            if source_pages
            else _finding_source_reference(alternate_weather)
        )
        source_summary = (
            f"CFP-held {alternate_location} alternate weather "
            "(source only; applicability not re-inferred): "
            + " | ".join(
                f"{label} {str(record.get('text') or '').strip()}"
                for label, record in source_records
            )
            if source_records
            else str(alternate_weather.get("summary") or "Review required.")
        )
        material_rows.append({
            **alternate_weather,
            "engine": "alternate_weather",
            "summary": source_summary,
            "source_reference": source_reference,
            "data": {
                **dict(alternate_weather.get("data") or {}),
                "priority_score": 85,
                "source_scope": (
                    "uploaded_cfp_only" if source_records else "mixed_source"
                ),
                "source_pages": source_pages,
            },
        })

    unavailable_coverage = [
        str(row.get("label") or "").strip()
        for row in coverage_rows or []
        if str(row.get("status") or "").strip().lower() == "unavailable"
        and str(row.get("label") or "").strip()
    ]
    if unavailable_coverage:
        material_rows.append({
            "engine": "weather_coverage",
            "severity": "warning",
            "title": "WEATHER COVERAGE INCOMPLETE",
            "summary": (
                f"{', '.join(unavailable_coverage)} unavailable in the CFP. "
                "This source-coverage gap is not a NIL operational finding; "
                "held terminal weather or chart pages do not close it."
            ),
            "source_reference": "Uploaded CFP · weather coverage ledger",
            "data": {"priority_score": 98},
        })

    departure_panel = next(
        (
            panel
            for panel in airport_panels or []
            if "departure" in set(panel.get("role_keys") or [])
        ),
        None,
    )
    departure_runway_relations = {
        str(line.get("notam_id") or "").upper(): line
        for line in (departure_panel or {}).get("card_summary_lines") or []
        if isinstance(line, dict)
        and str(line.get("kind") or "") == "notam"
        and str(line.get("notam_id") or "").strip()
    }

    def non_planned_departure_runway_notice(item: dict[str, Any]) -> bool:
        data = item.get("data") or {}
        if (
            str(item.get("engine") or "") != "notam"
            or str(data.get("role") or "") != "departure"
        ):
            return False
        relation = departure_runway_relations.get(
            str(data.get("notam_id") or "").upper()
        ) or {}
        return relation.get("different_runway") is True

    source_findings = [
        item
        for item in findings
        if not non_planned_departure_runway_notice(item)
        and not (
            str((item.get("data") or {}).get("notam_id") or "").upper()
            in resolved_notam_ids
            and "could not be resolved"
            in str(item.get("summary") or "").lower()
        )
    ]
    ranked = sorted([*source_findings, *material_rows], key=_finding_sort_key)

    def decision_bucket(item: dict[str, Any]) -> str:
        engine = str(item.get("engine") or "other")
        if engine == "notam":
            return f"notam:{str((item.get('data') or {}).get('role') or 'route')}"
        if engine in {
            "mel",
            "cddl",
            "deferred_declaration",
            "deferred_dispatch_gate",
        }:
            return "deferred"
        if engine == "arrival_ground":
            return "arrival-ground"
        if engine == "route_airspace":
            return "route-airspace"
        if engine == "alternate_weather":
            return "alternate-weather"
        if engine in {
            "weather",
            "weather_coverage",
            "sigmet",
            "vaa",
            "tropical_cyclone",
        }:
            return "weather"
        if engine in {"performance", "performance_reconciliation", "qa"}:
            return "performance"
        if engine in {"communications", "bobcat"}:
            return "communications"
        if engine in {"terrain", "vws", "depressurisation"}:
            return "terrain-profile"
        return engine

    # Where all six operational buckets are available, retain the complete
    # boss-approved decision flow instead of allowing generic bookkeeping or
    # a non-planned-runway notice to crowd out a material gate. Other flights
    # keep the severity-ranked one-per-bucket fallback below.
    material_bucket_order = (
        "performance",
        "notam:destination",
        "weather",
        "deferred",
        "route-airspace",
        "arrival-ground",
    )
    def preferred_bucket_item(bucket: str) -> dict[str, Any] | None:
        return next(
            (item for item in ranked if decision_bucket(item) == bucket),
            None,
        )

    material_candidates = [
        item
        for bucket in material_bucket_order
        if (item := preferred_bucket_item(bucket)) is not None
    ]
    if len(material_candidates) == len(material_bucket_order) and limit >= 6:
        candidates = material_candidates
    else:
        candidates = []
        used_buckets: set[str] = set()
        for item in ranked:
            bucket = decision_bucket(item)
            if bucket in used_buckets:
                continue
            used_buckets.add(bucket)
            candidates.append(item)
            if len(candidates) >= limit:
                break
        if len(candidates) < limit:
            candidates.extend(item for item in ranked if item not in candidates)
    candidates = sorted(candidates[:limit], key=_finding_sort_key)

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        title = re.sub(
            r"\bNone\b",
            "reference",
            str(item.get("title") or "Review item").strip(),
            flags=re.IGNORECASE,
        )
        summary = str(item.get("summary") or "Review required.").strip()
        identity = (title, summary)
        if identity in seen:
            continue
        seen.add(identity)
        engine = str(item.get("engine") or "other")
        selected.append({
            "rank": len(selected) + 1,
            "title": title,
            "summary": summary,
            "severity": str(item.get("severity") or "information"),
            "engine": engine,
            "source_reference": str(
                item.get("source_reference")
                or _finding_source_reference(item)
            ),
            "target": target_by_engine.get(engine, "sec_enroute"),
        })
        if len(selected) >= limit:
            break
    return selected


def _deferred_gate_overview_summary(gate: dict[str, Any]) -> str | None:
    """A compact Page-1 line derived once from the governed gate summary."""
    summary = str(gate.get("summary") or "").upper()
    engine = re.search(r"\bENG(?:INE)?\s*(\d+)\b", summary)
    if engine and "LATCH" in summary:
        line = f"ENG {engine.group(1)} LATCH"
        if "PRIOR EVERY DEPARTURE" in summary:
            line += " · CHECK EACH DEPARTURE"
        return line
    return None


def _performance_reconciliation_projection(
    flight: dict[str, Any],
    publication: dict[str, Any],
) -> list[dict[str, str]]:
    """Direct arithmetic checks only; no invented performance clearance."""
    rows: list[dict[str, str]] = []
    fuel_summary = flight.get("fuel_summary") or {}
    fuel_rows = fuel_summary.get("rows") or {}
    state = str(fuel_summary.get("state") or "").strip().lower()
    taxi_kg = fuel_summary.get("taxi_fuel_kg")
    requirement_names = (
        ("BURNOFF", "burnoff"),
        ("STAT CONT", "stat_cont"),
        ("ALTN FUEL", "altn_fuel"),
        ("ALTN HOLD", "altn_hold"),
    )
    requirement_values = [
        (label, (fuel_rows.get(key) or {}).get("fuel_kg"))
        for label, key in requirement_names
    ]
    requirement_total = (fuel_rows.get("flt_plan_reqmt") or {}).get("fuel_kg")
    arithmetic_detail = (
        "Parsed page-1 fuel rows reconcile."
        if state == "verified"
        else "Parsed page-1 fuel arithmetic is not verified; review the source CFP."
    )
    if (
        requirement_total is not None
        and taxi_kg is not None
        and all(value is not None for _, value in requirement_values)
    ):
        optional_parts = []
        for label, key in (
            ("DEST HOLD TOP UP", "dest_hold_top_up"),
            ("EDTO TOP UP", "edto_top_up"),
        ):
            value = (fuel_rows.get(key) or {}).get("fuel_kg")
            if value:
                optional_parts.append((label, value))
        components = [*requirement_values, *optional_parts, ("TAXI", taxi_kg)]
        arithmetic_detail = (
            f"FPL REQ {int(requirement_total):,} kg = "
            + " + ".join(
                f"{label} {int(value):,}"
                for label, value in components
            )
            + " kg."
        )
        derived = fuel_summary.get("derived_fuel_kg") or {}
        takeoff_fuel = derived.get("takeoff")
        landing_fuel = derived.get("landing")
        tanks = (fuel_rows.get("fuel_in_tanks") or {}).get("fuel_kg")
        burnoff = (fuel_rows.get("burnoff") or {}).get("fuel_kg")
        if all(
            value is not None
            for value in (takeoff_fuel, landing_fuel, tanks, burnoff)
        ):
            arithmetic_detail += (
                f" Derived T/O FUEL {int(takeoff_fuel):,} = TANKS "
                f"{int(tanks):,} - TAXI {int(taxi_kg):,}; LDG FUEL "
                f"{int(landing_fuel):,} = T/O {int(takeoff_fuel):,} - "
                f"BURNOFF {int(burnoff):,}."
            )
    rows.append({
        "label": "PAGE-1 FUEL ARITHMETIC",
        "status": "VERIFIED" if state == "verified" else "REVIEW",
        "detail": arithmetic_detail,
        "source_reference": "Uploaded CFP · page 1 fuel summary",
    })
    selected_rtow = publication.get("selected_rtow_kg")
    ptow = publication.get("ptow_kg")
    margin = publication.get("margin_kg")
    if selected_rtow is not None and ptow is not None and margin is not None:
        rows.append({
            "label": "RTOW / PTOW",
            "status": "VERIFIED" if margin >= 0 else "OPEN",
            "detail": (
                f"Selected RTOW {selected_rtow:,} kg minus PTOW {ptow:,} kg "
                f"equals {margin:+,} kg."
            ),
            "source_reference": "Uploaded CFP · performance and mass pages",
        })
    else:
        rows.append({
            "label": "RTOW / PTOW",
            "status": "REVIEW",
            "detail": "A complete RTOW/PTOW pair is unavailable in the parsed CFP.",
            "source_reference": "Uploaded CFP · performance and mass pages",
        })
    maximum_fuel = (publication.get("inputs") or {}).get(
        "maximum_fuel_available_kg"
    )
    tanks = (fuel_rows.get("fuel_in_tanks") or {}).get("fuel_kg")
    if maximum_fuel is not None and tanks is not None:
        difference = int(maximum_fuel) - int(tanks)
        rows.append({
            "label": "PERFORMANCE MAX FUEL / TANKS",
            "status": "VERIFIED" if difference >= 0 else "OPEN",
            "detail": (
                f"Printed maximum fuel available {int(maximum_fuel):,} kg minus "
                f"fuel in tanks {int(tanks):,} kg equals {difference:+,} kg; "
                "reconcile against the final load/performance release."
            ),
            "source_reference": "Uploaded CFP · page 1 and performance inputs",
            "overview_summary": (
                f"MAX FUEL {int(maximum_fuel):,} vs tanks {int(tanks):,} · "
                f"{'VERIFIED' if difference >= 0 else 'RECONCILE'}"
            ),
        })
    return rows


def _release_gate_projection(
    decision_findings: list[dict[str, Any]],
    performance_rows: list[dict[str, str]],
    deferred_gates: list[dict[str, Any]],
    coverage_ledger: list[dict[str, str]],
    communications: list[dict[str, str]],
    route_airspace: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Five source-backed reviews reusing the material decision selection."""

    def first(engines: set[str]) -> dict[str, Any] | None:
        return next(
            (
                item for item in decision_findings
                if str(item.get("engine") or "") in engines
            ),
            None,
        )

    performance_open = next(
        (row for row in performance_rows if row.get("status") in {"OPEN", "REVIEW"}),
        performance_rows[0] if performance_rows else None,
    )
    performance_decision = first({"performance_reconciliation"})
    technical_decision = first({"deferred_dispatch_gate"})
    technical = (
        next(
            (
                gate
                for gate in deferred_gates
                if str(gate.get("overview_summary") or "").strip()
            ),
            None,
        )
        or (deferred_gates[0] if deferred_gates else None)
    )
    airport_decisions = [
        item
        for item in decision_findings
        if str(item.get("engine") or "") in {"notam", "arrival_ground"}
    ]
    weather = first({"weather_coverage"}) or first({
        "weather",
        "alternate_weather",
        "sigmet",
        "vaa",
        "tropical_cyclone",
    })
    weather_gaps = [
        row.get("label")
        for row in coverage_ledger
        if str(row.get("status") or "").lower() == "unavailable"
    ]
    communication = communications[0] if communications else first({"communications"})
    route_airspace = route_airspace or {}
    route_airspace_held = bool(route_airspace.get("record_count"))
    airport_severity = max(
        (
            str(item.get("severity") or "information")
            for item in airport_decisions
        ),
        key=lambda value: _SEVERITY_RANK.get(value, 0),
        default="NOT SELECTED",
    )
    airport_gate_decisions = (
        airport_decisions
        if len(airport_decisions) <= 2
        else airport_decisions[:1]
    )
    airport_detail = " | ".join(
        (
            f"{item.get('title')} - open the ranked/source airport evidence."
            if (
                str(item.get("engine") or "") == "arrival_ground"
                or len(str(item.get("summary") or "").strip()) > 120
            )
            else ": ".join(
                part
                for part in (
                    str(item.get("title") or "").strip(),
                    str(item.get("summary") or "").strip(),
                )
                if part
            )
        )
        for item in airport_gate_decisions
    )
    additional_airport_count = len(airport_decisions) - len(airport_gate_decisions)
    if additional_airport_count:
        airport_detail += (
            f" | {additional_airport_count} additional airport finding(s) remain "
            "in ranked/source evidence."
        )
    return [
        {
            "label": "PERFORMANCE",
            "status": str((performance_open or {}).get("status") or "REVIEW"),
            "detail": str(
                (performance_decision or {}).get("summary")
                or (performance_open or {}).get("detail")
                or "Performance reconciliation is unavailable."
            ),
            "target": "sec_performance",
        },
        {
            "label": "STATUS",
            "status": "OPEN" if technical_decision or technical else "NOT SELECTED",
            "detail": str(
                (technical_decision or {}).get("summary")
                or (technical or {}).get("summary")
                or "No deferred declaration is printed on CFP page 1."
            ),
            "target": "sec_mel_cdl",
        },
        {
            "label": "AIRPORTS",
            "status": airport_severity.upper(),
            "detail": airport_detail
            or "No airport warning was selected from the briefing view.",
            "target": "sec_airports",
        },
        {
            "label": "WEATHER",
            "status": str((weather or {}).get("severity") or ("GAP" if weather_gaps else "NOT SELECTED")).upper(),
            "detail": (
                str(weather.get("summary") or weather.get("title"))
                if weather
                else f"Unavailable coverage: {', '.join(str(value) for value in weather_gaps)}."
                if weather_gaps
                else "No weather warning was selected from the briefing view."
            ),
            "target": "sec_hazard",
        },
        (
            {
                "label": "ROUTE",
                "status": "REVIEW",
                "detail": str(route_airspace.get("release_detail") or "Route-airspace source notices require controlled-product review."),
                "target": "sec_enroute",
            }
            if route_airspace_held
            else {
                "label": "COMMUNICATIONS",
                "status": "REVIEW" if communication else "NOT SELECTED",
                "detail": str(
                    (communication or {}).get("event")
                    or (communication or {}).get("title")
                    or "No early-contact row is held in the briefing view."
                ),
                "target": "sec_enroute",
            }
        ),
    ]


def _source_assurance_projection(
    flight: dict[str, Any],
    volcanic_advisories: list[dict[str, Any]],
    coverage_ledger: list[dict[str, str]],
    route_airspace: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    selected_notams = len(flight.get("notams") or [])
    weather_records = len(_cfp_weather_records(flight))
    intam_records = list(flight.get("intam_records") or [])
    intam_pages = sorted({
        int(record["source_page"])
        for record in intam_records
        if isinstance(record, dict)
        and isinstance(record.get("source_page"), int)
    })
    intam_page_text = (
        f"CFP p{intam_pages[0]}"
        if len(intam_pages) == 1
        else f"CFP pp{intam_pages[0]}-{intam_pages[-1]}"
        if intam_pages
        else "CFP pages unavailable"
    )
    va_sigmet = next(
        (
            str(row.get("status") or "unavailable")
            for row in coverage_ledger
            if row.get("label") == "VA SIGMET"
        ),
        "unavailable",
    )
    route_airspace = route_airspace or {}
    rows = [
        {
            "source": "UPLOADED CFP",
            "status": "HELD",
            "detail": str(flight.get("document_id") or "Parsed flight-plan package"),
        },
        {
            "source": "AIRPORT NOTICES",
            "status": "HELD" if selected_notams else "NOT HELD",
            "detail": f"{selected_notams} parsed source record(s).",
        },
        {
            "source": "ROUTE AIRSPACE NOTICES",
            "status": "HELD" if route_airspace.get("record_count") else "NOT HELD",
            "detail": (
                f"{route_airspace.get('record_count')} source record(s) - "
                f"{route_airspace.get('source_page_text')}; applicability not inferred."
                if route_airspace.get("record_count")
                else "No bounded route-airspace notice is held in this parsed view."
            ),
        },
        {
            "source": "CFP WEATHER",
            "status": "HELD" if weather_records else "NOT HELD",
            "detail": f"{weather_records} parsed bulletin record(s).",
        },
        {
            "source": "CFP VOLCANO ADVISORIES",
            "status": "HELD" if volcanic_advisories else "NOT HELD",
            "detail": f"{len(volcanic_advisories)} named advisory record(s).",
        },
        {
            "source": "VA SIGMET COVERAGE",
            "status": va_sigmet.upper(),
            "detail": "A coverage state is not a NIL operational finding.",
        },
        {
            "source": "COMPANY BULLETINS / INTAM",
            "status": "HELD" if intam_records else "NOT HELD",
            "detail": (
                f"{len(intam_records)} structured source record(s) - "
                f"{intam_page_text}; relevance not inferred."
                if intam_records
                else "No structured INTAM record is held in this parsed briefing view."
            ),
        },
    ]
    return rows


def _source_category_review_queue(
    records: list[dict[str, Any]],
    *,
    category_key: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Stable source-order examples with category diversity, never relevance.

    The parser preserves physical record order.  Source page plus that stable
    order is the only ranking input: first take one record per printed
    category, then fill remaining capacity without displacing earlier source
    evidence.  No airport, fleet, headline or flight-specific term is used.
    """
    if limit <= 0:
        return []
    ordered = sorted(
        enumerate(records),
        key=lambda item: (
            item[1].get("source_page")
            if isinstance(item[1].get("source_page"), int)
            else 10**9,
            item[0],
        ),
    )
    selected: list[tuple[int, dict[str, Any]]] = []
    selected_indexes: set[int] = set()
    seen_categories: set[str] = set()
    for source_index, record in ordered:
        category = str(record.get(category_key) or "UNCLASSIFIED").strip().upper()
        if category in seen_categories:
            continue
        seen_categories.add(category)
        selected.append((source_index, record))
        selected_indexes.add(source_index)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for source_index, record in ordered:
            if source_index in selected_indexes:
                continue
            selected.append((source_index, record))
            if len(selected) >= limit:
                break
    return [dict(record) for _, record in selected]


def _route_airspace_projection(flight: dict[str, Any]) -> dict[str, Any]:
    """A source-held route-airspace contract with an explicit review gate."""
    records = [
        dict(record)
        for record in flight.get("route_airspace_notices") or []
        if isinstance(record, dict)
    ]
    pages = sorted({
        int(record["source_page"])
        for record in records
        if isinstance(record.get("source_page"), int)
    })
    page_text = (
        f"CFP p{pages[0]}"
        if len(pages) == 1
        else f"CFP pp{pages[0]}-{pages[-1]}"
        if pages
        else "CFP pages unavailable"
    )
    count = len(records)
    military_record = next(
        (
            record
            for record in records
            if str(record.get("activity_kind") or "").strip().lower()
            == "military_training"
            and str(record.get("notam_id") or "").strip()
        ),
        None,
    )
    military_source_note = (
        f" Military-training record {military_record['notam_id']} is source-held."
        if military_record
        else ""
    )
    release_detail = (
        f"{count} source-held route-airspace notice(s) ({page_text}); confirm "
        "route/level applicability and any ATC-clearance effect against current "
        "controlled products. No polygon intersection is inferred."
        if count
        else "No bounded route-airspace notice is held in this parsed view."
    )
    return {
        "status": "REVIEW" if count else "NOT HELD",
        "record_count": count,
        "source_pages": pages,
        "source_page_text": page_text,
        "records": records,
        "military_source_record": dict(military_record) if military_record else None,
        "review_queue": _source_category_review_queue(
            records,
            category_key="activity_kind",
        ),
        "summary": release_detail,
        "card_summary": (
            f"ROUTE AIRSPACE · REVIEW · {count} source notice(s) · {page_text}. "
            f"{military_source_note.strip()} "
            "Route/level applicability and any ATC-clearance effect are not inferred; "
            "full held records remain in the dashboard."
            if count
            else ""
        ),
        "release_detail": release_detail,
        "applicability_inferred": False,
    }


def _intam_review_queue(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generic source/category examples, explicitly without applicability."""
    return _source_category_review_queue(records, category_key="category")


def build_briefing_view(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    timing_view: dict[str, Any] | None = None,
    weather_charts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_findings = list(findings)
    findings = prepare_pilot_findings(findings, notam_limit=24)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        grouped[str(item.get("engine") or "other")].append(item)

    route_map = build_route_map(flight)
    waypoints = flight.get("route_waypoints") or []
    terrain_events = detect_terrain_events(waypoints)
    final_actm = max((int(item.get("actm_minutes")) for item in waypoints if item.get("actm_minutes") is not None), default=0)
    destination_actm = _destination_actm(flight)
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
    airport_operational_panels = _airport_operational_panels(
        flight,
        source_findings,
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
            "minima": item.get("minima") or "",
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
    scheduled_etd_hhmm = theme.utc_hhmm(
        flight.get("scheduled_departure_utc")
    ).rstrip("Z")
    scheduled_eta_hhmm = theme.utc_hhmm(
        flight.get("scheduled_arrival_utc")
    ).rstrip("Z")
    schedule_block = (
        str(theme.block_time_label(flight) or "").replace("BLOCK ", "") or None
    )
    actual_takeoff_hhmm = (
        theme.utc_hhmm(timing_view.get("actual_takeoff_utc"))
        if timing_view and timing_view.get("actual_takeoff_utc")
        else None
    )
    calculated_eta_hhmm = _actual_arrival_hhmm(timing_view, destination_actm)
    destination_eet_display = format_actm(destination_actm)
    eta_status = (
        "calculated"
        if calculated_eta_hhmm
        else ("unavailable" if actual_takeoff_hhmm else "scheduled")
    )
    generated_at = datetime.now(timezone.utc)
    performance_publication = _performance_publication(flight)
    deferred_dispatch_gates = [
        {
            **gate,
            "overview_summary": _deferred_gate_overview_summary(gate),
        }
        for gate in build_deferred_dispatch_gates(
            flight.get("deferred_items") or []
        )
    ]
    performance_reconciliation = _performance_reconciliation_projection(
        flight,
        performance_publication,
    )
    coverage_ledger = _weather_coverage_ledger(flight)
    route_airspace = _route_airspace_projection(flight)
    decision_findings = _decision_finding_projection(
        findings,
        performance_rows=performance_reconciliation,
        deferred_gates=deferred_dispatch_gates,
        airport_panels=airport_operational_panels,
        coverage_rows=coverage_ledger,
        route_airspace=route_airspace,
    )
    fir_boundaries = _fir_boundary_rows(flight)
    communications = _communication_timeline(flight, findings, timing_view)
    intam_records = [
        dict(record)
        for record in flight.get("intam_records") or []
        if isinstance(record, dict)
    ]
    intam_pages = sorted({
        int(record["source_page"])
        for record in intam_records
        if isinstance(record.get("source_page"), int)
    })
    cfp_weather_records = _cfp_weather_records(flight)
    cfp_weather_pages = sorted({
        int(record["source_page"])
        for record in cfp_weather_records
    })
    volcanic_advisories = _va_cfp_advisories(flight)
    release_gates = _release_gate_projection(
        decision_findings,
        performance_reconciliation,
        deferred_dispatch_gates,
        coverage_ledger,
        communications,
        route_airspace,
    )
    source_assurance = _source_assurance_projection(
        flight,
        volcanic_advisories,
        coverage_ledger,
        route_airspace,
    )
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
            "eet": destination_eet_display,
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
            "clock_basis": (
                "ATOT + CFP ACTM (destination held)"
                if calculated_eta_hhmm
                else (
                    "ATOT + CFP ACTM: destination ACTM unavailable"
                    if actual_takeoff_hhmm
                    else "CFP ACTM only"
                )
            ),
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
        # One flight-identity block for every surface (boss, 21 Aug: "I need
        # the route ID and the route version"). Composed here so the PDF's
        # FLIGHT BASIS card and the web dashboard print the same facts —
        # renderer-side raw reads are the leak the corpus gate forbids.
        "flight_identity": {
            "aircraft_type": flight.get("aircraft_type"),
            "registration": theme.normalized_registration(flight.get("registration")),
            "captain": flight.get("captain"),
            "ofp": flight.get("ofp_identifier"),
            "route_id": flight.get("route_identifier"),
            "plan_number": flight.get("plan_number"),
            "etd_hhmm": scheduled_etd_hhmm,
            "eta_hhmm": (
                calculated_eta_hhmm
                if calculated_eta_hhmm
                else ("--" if actual_takeoff_hhmm else scheduled_eta_hhmm)
            ),
            "eta_status": eta_status,
            "scheduled_eta_hhmm": scheduled_eta_hhmm,
            "actual_takeoff_hhmm": actual_takeoff_hhmm,
            "block": schedule_block,
            "rules": flight.get("edto_rvsm"),
            "cost_index": flight.get("cost_index"),
            "apd_percent": flight.get("apd_percent"),
            "arrival_basis": _arrival_basis_line(
                scheduled_etd_hhmm,
                scheduled_eta_hhmm,
                schedule_block,
                destination_eet_display,
                actual_takeoff_hhmm=actual_takeoff_hhmm,
                calculated_eta_hhmm=calculated_eta_hhmm,
            ),
            "timeline_basis": _timeline_basis_line(
                scheduled_etd_hhmm,
                scheduled_eta_hhmm,
                schedule_block,
                destination_eet_display,
                actual_takeoff_hhmm,
                calculated_eta_hhmm,
            ),
        },
        "performance_publication": performance_publication,
        "performance_reconciliation": performance_reconciliation,
        "decision_findings": decision_findings,
        "release_gates": release_gates,
        "source_assurance": source_assurance,
        # Compact dispatch confirmation gates are a source-preserving shared
        # view. Raw deferred_items remain untouched for the deterministic
        # engines and detailed report rows.
        "deferred_dispatch_gates": deferred_dispatch_gates,
        "departure": departure_panel,
        "destination": destination_panel,
        "airport_operational_panels": airport_operational_panels,
        "fuel_enroute_airports": [
            panel
            for panel in airport_operational_panels
            if "fuel_enroute_airport" in panel["role_keys"]
        ],
        "overview": _overview_projection(
            flight,
            source_findings,
            airport_operational_panels,
            terrain_events,
            final_actm,
            destination_actm,
            timing_view,
        ),
        "route_map": route_map,
        "route_svg": render_route_svg(route_map),
        # The one terrain opinion every surface prints. Events come from the
        # ODSS engine over the parsed route; the summary sentence is composed
        # here exactly once so overview, dashboard and PDF cannot disagree.
        "terrain": {
            "events": terrain_events,
            "summary": _terrain_summary(terrain_events, findings),
        },
        "exception_cards": exception_cards,
        "communications": communications,
        "fir_boundaries": fir_boundaries,
        "fir_boundary_summary": _fir_boundary_summary(fir_boundaries),
        "intam": {
            "status": "HELD" if intam_records else "NOT HELD",
            "record_count": len(intam_records),
            "source_pages": intam_pages,
            "records": intam_records,
            "review_queue": _intam_review_queue(intam_records),
            "applicability": "not_inferred",
        },
        "route_airspace": route_airspace,
        "cfp_weather": {
            "record_count": len(cfp_weather_records),
            "source_pages": cfp_weather_pages,
        },
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
            "coverage_ledger": coverage_ledger,
            "vaac_reach": _vaac_reach_summary(flight),
            "weather_chart_selection": _weather_chart_selection(
                weather_charts,
                flight,
            ),
        },
        "vaa": {
            "cfp_advisories": volcanic_advisories,
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
