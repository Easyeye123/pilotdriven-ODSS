from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import fitz

from .constants import actm_minutes, date_ddmmmyy, utc_on_date
from .enrichment import enrich_notams, enrich_weather


def extract_pages(path: Path) -> list[str]:
    document = fitz.open(str(path))
    try:
        return [page.get_text("text") for page in document]
    finally:
        document.close()


def _int_group(text: str, pattern: str, default: int | None = None) -> int | None:
    match = re.search(pattern, text, re.MULTILINE)
    return int(match.group(1)) if match else default


def _detect_sections(pages: list[str]) -> dict[str, tuple[int, int]]:
    starts: list[tuple[str, int]] = []
    for index, text in enumerate(pages):
        top = "\n".join(text.splitlines()[:10]).upper()
        if "ATC FLIGHT PLAN" in top:
            starts.append(("atc", index))
        elif "AIRPORT WX LIST" in top:
            starts.append(("weather", index))
        elif any(line.strip() == "NOTAM" for line in top.splitlines()):
            starts.append(("notam", index))
        elif any(line.strip() == "INTAM" for line in top.splitlines()):
            starts.append(("intam", index))
        elif index == 0 or "SUMMARY EDTO CFP" in top or "SUMMARY CFP" in top:
            if not any(name == "cfp" for name, _ in starts):
                starts.append(("cfp", index))
    starts.sort(key=lambda item: item[1])
    return {
        name: (start, starts[i + 1][1] if i + 1 < len(starts) else len(pages))
        for i, (name, start) in enumerate(starts)
    }


def _parse_deferred_items(page1: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in page1.splitlines():
        match = re.match(r"^(AA|BB|CC|DD|EE)\s+(CDDL|CDL|MEL)(?:\s+([0-9A-Z-]+))?", line.strip())
        if match:
            if current:
                items.append(current)
            current = {
                "reference": match.group(3) or "UNSPECIFIED",
                "description": "",
                "item_type": match.group(2),
                "company_remark": None,
            }
            continue
        if current:
            stripped = line.strip()
            if stripped.startswith("PLAN ") or stripped.startswith("RTE NO"):
                items.append(current)
                current = None
                break
            if stripped:
                if not current["description"]:
                    current["description"] = stripped
                else:
                    current["company_remark"] = f"{current['company_remark'] or ''} {stripped}".strip()
    if current:
        items.append(current)
    return items


def _parse_route_text(page1: str) -> str:
    route_lines: list[str] = []
    collecting = False
    for line in page1.splitlines():
        stripped = line.strip()
        if re.match(r"^[A-Z]{4}/[0-9A-Z]{2,3}\b", stripped):
            collecting = True
        if collecting:
            if re.match(r"^[A-Z]{3}/\d{3}(?:/|$)", stripped):
                break
            route_lines.append(stripped)
    return " ".join(route_lines)


def _parse_alternates(page1: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"^(?P<apt>[A-Z]{4})/(?P<rwy>[0-9A-Z]{2,3})\s+(?P<approach>[A-Z0-9]+)\s+"
        r"(?P<minima>\S+)\s+(?P<dist>\d{4})\s+\d{3}\s+[MP]\d{3}\s+"
        r"(?P<time>\d{4})\s+(?P<fuel>\d{5})$",
        re.MULTILINE,
    )
    return [
        {
            "airport": m.group("apt"),
            "runway": m.group("rwy"),
            "approach": m.group("approach"),
            "minima": m.group("minima"),
            "distance_nm": int(m.group("dist")),
            "time_minutes": int(m.group("time")[:2]) * 60 + int(m.group("time")[2:]),
            "fuel_kg": int(m.group("fuel")),
        }
        for m in pattern.finditer(page1)
    ]


def _parse_waypoints(route_pages: list[str], route_text: str) -> list[dict[str, Any]]:
    pending: dict[str, Any] | None = None
    waypoints: list[dict[str, Any]] = []
    waypoint_line = re.compile(
        r"^(?P<name>\*\*ETP\S*|-[A-Z0-9]+|[A-Z][A-Z0-9]{1,8}|TOC|TOD|ENTRY\d|EXIT\d)"
        r"(?:\s+\d{3}(?:\.\d+)?)?\s+(?P<actm>\d{2}\.\d{2})\b"
    )
    coordinate_line = re.compile(
        r"^[NS]\d{2}\s+\d{2}\.\d\s+[EW]\d{3}\s+\d{2}\.\d\s+(?P<msa>\d{3})(?P<star>\*)?"
    )
    vws_line = re.compile(r"\s(?P<tas>\d{3})\s+(?P<vws>\d{3})\s+\d{2}\.\d\s")
    for page_number, text in enumerate(route_pages, start=1):
        for line in text.splitlines():
            match = waypoint_line.match(line.strip())
            if match:
                if pending:
                    waypoints.append(pending)
                name = match.group("name")
                pending = {
                    "name": name,
                    "actm_minutes": actm_minutes(match.group("actm")),
                    "fir_boundary": name[1:] if name.startswith("-") else None,
                    "source_page": page_number,
                    "msa_hundreds_ft": None,
                    "msa_asterisk": False,
                    "vws": None,
                    "airway_in": None,
                }
                vws_match = vws_line.search(line)
                if vws_match:
                    pending["vws"] = int(vws_match.group("vws"))
                continue
            if pending:
                coordinate = coordinate_line.match(line.strip())
                if coordinate:
                    name = str(pending["name"])
                    computed = name.startswith("-") or name.startswith(("ENTRY", "EXIT", "**ETP")) or name in {"TOC", "TOD"}
                    if not computed:
                        pending["msa_hundreds_ft"] = int(coordinate.group("msa"))
                        pending["msa_asterisk"] = bool(coordinate.group("star"))
    if pending:
        waypoints.append(pending)

    names = {w["name"].lstrip("-").upper() for w in waypoints}
    current_airway: str | None = None
    airway_re = re.compile(r"^(?:DCT|[A-Z]{1,3}\d{1,4}[A-Z]?)$")
    anchors: list[tuple[str, str]] = []
    for token in route_text.replace("/", " ").split():
        upper = token.upper()
        if airway_re.fullmatch(upper):
            current_airway = upper
        elif upper in names and current_airway:
            anchors.append((upper, current_airway))
    search_from = -1
    for anchor_name, airway in anchors:
        anchor_index = next(
            (i for i in range(search_from + 1, len(waypoints)) if waypoints[i]["name"].lstrip("-").upper() == anchor_name),
            None,
        )
        if anchor_index is None:
            continue
        for i in range(search_from + 1, anchor_index + 1):
            if not waypoints[i]["fir_boundary"]:
                waypoints[i]["airway_in"] = airway
        search_from = anchor_index
    return waypoints


def parse_lido(pages: list[str], source_name: str) -> dict[str, Any]:
    sections = _detect_sections(pages)
    if "cfp" not in sections:
        raise ValueError("CFP section not detected")
    cfp_start, cfp_end = sections["cfp"]
    cfp_pages = pages[cfp_start:cfp_end]
    page1 = cfp_pages[0]
    identity = re.search(
        r"(?P<reg>[A-Z0-9-]{4,10})\s+(?P<flight>[A-Z]{2,3}\d{2,4})\s+"
        r"(?P<dep_iata>[A-Z]{3})/(?P<dest_iata>[A-Z]{3})\s+ETD\s+"
        r"(?P<etd>\d{4})\s+(?P<date>\d{2}[A-Z]{3}\d{2})",
        page1,
    )
    if not identity:
        raise ValueError("Unable to parse Lido flight identity")
    day = date_ddmmmyy(identity.group("date"))
    sched = re.search(r"SCHED DEP\s+(\d{4})\s+UTC\s+SCHED ARR\s+(\d{4})\s+UTC", page1)
    if not sched:
        raise ValueError("Unable to parse scheduled times")
    departure_utc = utc_on_date(day, sched.group(1))
    arrival_utc = utc_on_date(day, sched.group(2))
    if arrival_utc <= departure_utc:
        arrival_utc += timedelta(days=1)
    route_line = re.search(r"^(?P<departure>[A-Z]{4})/(?P<dep_rwy>[0-9A-Z]{2,3})\b", page1, re.MULTILINE)
    destination_line = re.search(r"\b(?P<destination>[A-Z]{4})/(?P<dest_rwy>[0-9A-Z]{2,3})\s*$", page1, re.MULTILINE)
    departure = route_line.group("departure") if route_line else identity.group("dep_iata")
    destination = destination_line.group("destination") if destination_line else identity.group("dest_iata")
    route_text = _parse_route_text(page1)
    waypoints = _parse_waypoints(cfp_pages[6:], route_text)

    bobcat = None
    match = re.search(r"BOBCAT ALLOCATION:\s*WPT\s+(\w+)\s+FL(\d+)\s+CTO\s+(\d{4})\s+CTOT\s+(\d{4})", page1)
    if match:
        bobcat = {
            "waypoint": match.group(1),
            "flight_level": int(match.group(2)),
            "cto_utc": utc_on_date(day, match.group(3)).isoformat(),
            "ctot_utc": utc_on_date(day, match.group(4)).isoformat(),
        }

    fuel = {
        "trip_fuel_kg": _int_group(page1, r"BURNOFF\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "contingency_fuel_kg": _int_group(page1, r"STAT CONT\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "alternate_fuel_kg": _int_group(page1, r"ALTN FUEL\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "alternate_holding_fuel_kg": _int_group(page1, r"ALTN HOLD\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "taxi_fuel_kg": _int_group(page1, r"TAXI FUEL\s+0*(\d+)") or 0,
        "flight_plan_required_fuel_kg": _int_group(page1, r"FLT PLAN REQMT\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "excess_fuel_kg": _int_group(page1, r"EXCESS FUEL\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
        "fuel_in_tanks_kg": _int_group(page1, r"FUEL IN TANKS\s+\d{2}\.\d{2}\s+0*(\d+)") or 0,
    }
    fuel["planned_destination_fuel_kg"] = fuel["fuel_in_tanks_kg"] - fuel["taxi_fuel_kg"] - fuel["trip_fuel_kg"]
    masses = {
        "planned_zfw_kg": _int_group(page1, r"PZFW\s+(\d+)") or 0,
        "planned_takeoff_weight_kg": _int_group(page1, r"PTOW\s+(\d+)") or 0,
        "planned_landing_weight_kg": _int_group(page1, r"PLWT\s+(\d+)") or 0,
    }
    perf_text = "\n".join(cfp_pages[:5])
    performance = {
        "runway": (re.search(r"[A-Z]{4} RWY\s+(\w+)", perf_text).group(1) if re.search(r"[A-Z]{4} RWY\s+(\w+)", perf_text) else None),
        "runway_condition": "DRY" if "RWY COND: DRY" in perf_text else None,
        "thrust_setting": "FULL" if "STD RATING: FULL" in perf_text else None,
        "flap_setting": _int_group(perf_text, r"FLAPS\s+(\d+)"),
        "temperature_c": _int_group(perf_text, r"PLAN TEMP P(\d+)"),
        "qnh_hpa": _int_group(perf_text, r"PLAN QNH\s+(\d+)"),
        "wind": (re.search(r"PLAN WIND\s+(\S+)", perf_text).group(1) if re.search(r"PLAN WIND\s+(\S+)", perf_text) else None),
        "packs_on": True if "PACKS ON" in perf_text else None,
        "anti_ice_on": False if "ANTI-ICE OFF" in perf_text else None,
        "eosid": (re.search(r"EOSID\s*:\s*(.+)", perf_text).group(1).strip() if re.search(r"EOSID\s*:\s*(.+)", perf_text) else None),
        "obstacle_rtow_kg": _int_group(perf_text, r"RTOW\(PERF\)\s+(\d+)"),
        "landing_rtow_kg": _int_group(perf_text, r"RTOW\(LAND\)\s+(\d+)"),
        "structural_rtow_kg": _int_group(perf_text, r"RTOW\(STRUC\)\s+(\d+)"),
        "controlling_rtow_kg": _int_group(perf_text, r"^\s*RTOW\s+(\d+)\s*$"),
        "maximum_fuel_available_kg": _int_group(perf_text, r"MAX FUEL AVAIL:\s*0*(\d+)"),
    }
    edto_text = next((text for text in cfp_pages if "EDTO INFORMATION" in text), "")
    entry_match = re.search(r"\n\s*(\d{1,2}\.\d{2})\s+N.*\nENTRY", edto_text)
    exit_match = re.search(r"\n\s*(\d{1,2}\.\d{2})\s+N.*\nEXIT", edto_text)
    edto_airports = []
    for m in re.finditer(r"^(\w{4})\s+(\d{4})-(\d{4})\s+(\w+)\s+(\S+)\s+(.+)$", edto_text, re.MULTILINE):
        apt, start_hhmm, end_hhmm, runway, approach, minima = m.groups()
        edto_airports.append({
            "airport": apt,
            "period_start_utc": utc_on_date(day, start_hhmm).isoformat(),
            "period_end_utc": utc_on_date(day, end_hhmm).isoformat(),
            "runway": runway,
            "approach": approach,
            "minima": minima.strip(),
        })
    level_match = re.search(r"^[A-Z]{3}/\d{3}(?:/.*)$", page1, re.MULTILINE)
    aircraft_match = re.search(r"RTE NO\s+\S+\s+(?P<aircraft>[A-Z0-9-]+)", page1)
    flight = {
        "document_id": source_name,
        "flight_number": identity.group("flight"),
        "flight_date": identity.group("date"),
        "aircraft_type": aircraft_match.group("aircraft") if aircraft_match else "UNKNOWN",
        "registration": identity.group("reg"),
        "departure": departure,
        "destination": destination,
        "departure_runway": route_line.group("dep_rwy") if route_line else None,
        "destination_runway": destination_line.group("dest_rwy") if destination_line else None,
        "scheduled_departure_utc": departure_utc.isoformat(),
        "scheduled_arrival_utc": arrival_utc.isoformat(),
        "route_text": route_text,
        "route_waypoints": waypoints,
        "planned_level_profile": level_match.group(0).strip() if level_match else None,
        "cost_index": _int_group(page1, r"CRUISE CI\s+(\d+)"),
        "edto_rvsm": "EDTO/RVSM" if "EDTO/RVSM" in page1 else None,
        "bobcat": bobcat,
        "deferred_items": _parse_deferred_items(page1),
        "alternates": _parse_alternates(page1),
        "performance": performance,
        "fuel": fuel,
        "masses": masses,
        "edto": {
            "entry_actm_minutes": actm_minutes(entry_match.group(1)) if entry_match else None,
            "exit_actm_minutes": actm_minutes(exit_match.group(1)) if exit_match else None,
            "etp_actm_minutes": [
                actm_minutes(m.group(1))
                for m in re.finditer(r"\*\*ETP\S*(?:\s+\S+)?\s+(\d{1,2}\.\d{2})", "\n".join(cfp_pages))
            ],
            "airports": edto_airports,
        },
        "notams": [],
        "weather": [],
    }
    enrich_weather(flight, pages)
    enrich_notams(flight, pages)
    return flight
