from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    COMMUNICATION_RULES,
    MEL_REFERENCES,
    MONTHS,
    REFERENCE_LIBRARY_METADATA,
    format_actm,
    format_kg,
)

from .controlled_library import (
    CDL_LIBRARY_METADATA,
    CDL_REFERENCES,
    DEPRESS_LIBRARY_METADATA,
    DEPRESS_PROFILES,
    aircraft_effectivity_tokens,
    select_cdl_variants,
)

_WEEKDAYS = {name: index for index, name in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"))}
_TIME_RANGE = re.compile(r"\b(\d{4})(?:UTC|Z)?\s*(?:-|TO)\s*(\d{4})(?:UTC|Z)?\b")


def finding(
    engine: str,
    severity: str,
    title: str,
    summary: str,
    details: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": f"{engine.upper()}-AUTO",
        "engine": engine,
        "severity": severity,
        "title": title,
        "summary": summary,
        "details": details or [],
        "data": data or {},
    }


def _switch_state(value: bool | None) -> str:
    if value is True:
        return "ON"
    if value is False:
        return "OFF"
    return "not parsed"


def _intervals_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start < second_end and second_start < first_end


def _minute_of_day(value: str) -> int | None:
    hour = int(value[:2])
    minute = int(value[2:])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _schedule_weekdays(value: str) -> set[int] | None:
    weekday = r"MON|TUE|WED|THU|FRI|SAT|SUN"
    normalized = re.sub(r"\s*,\s*", " ", value.strip())
    range_match = re.fullmatch(rf"({weekday})-({weekday})", normalized)
    if range_match:
        start = _WEEKDAYS[range_match.group(1)]
        end = _WEEKDAYS[range_match.group(2)]
        result = {start}
        while start != end:
            start = (start + 1) % 7
            result.add(start)
        return result
    if not re.fullmatch(rf"(?:{weekday})(?:\s+(?:{weekday}))*", normalized):
        return None
    tokens = re.findall(weekday, normalized)
    return {_WEEKDAYS[token] for token in tokens}


def _schedule_overlaps(schedule: str, window_start: datetime, window_end: datetime) -> bool | None:
    months = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
    normalized = re.sub(rf",\s*(?=(?:{months})\b)", ";", schedule.upper())
    entries = [entry.strip() for entry in normalized.split(";") if entry.strip()]
    if not entries:
        return None
    parsed_entries = 0
    first_day = (window_start - timedelta(days=1)).date()
    day_count = (window_end.date() - first_day).days + 1
    for entry in entries:
        matches = list(_TIME_RANGE.finditer(entry))
        if not matches:
            return None
        gaps = [entry[matches[index].end():matches[index + 1].start()] for index in range(len(matches) - 1)]
        gaps.append(entry[matches[-1].end():])
        if any(not re.fullmatch(r"[\s,/]*", gap) for gap in gaps):
            return None
        ranges = []
        for match in matches:
            start_minutes = _minute_of_day(match.group(1))
            end_minutes = _minute_of_day(match.group(2))
            if start_minutes is None or end_minutes is None:
                return None
            ranges.append((start_minutes, end_minutes))
        prefix = entry[:matches[0].start()].strip(" ,")
        date_match = re.fullmatch(rf"({months})\s+(.+)", prefix)
        month_days: set[int] | None = None
        month_number = None
        if date_match:
            month_number = MONTHS[date_match.group(1)]
            date_expression = date_match.group(2)
            if not re.fullmatch(r"\d{2}(?:-\d{2})?(?:[ ,]+\d{2}(?:-\d{2})?)*", date_expression):
                return None
            month_days = set()
            for token in re.findall(r"\d{2}(?:-\d{2})?", date_expression):
                if "-" in token:
                    start_day, end_day = (int(value) for value in token.split("-", 1))
                    if start_day > end_day:
                        return None
                    month_days.update(range(start_day, end_day + 1))
                else:
                    month_days.add(int(token))
            if not month_days:
                return None
        daily = prefix in {"DAILY", "DLY"}
        weekdays = None if daily or date_match else _schedule_weekdays(prefix)
        if not daily and not date_match and weekdays is None:
            return None
        parsed_entries += 1
        for offset in range(day_count):
            day = first_day + timedelta(days=offset)
            if date_match and (day.month != month_number or day.day not in month_days):
                continue
            if weekdays is not None and day.weekday() not in weekdays:
                continue
            for start_minutes, end_minutes in ranges:
                occurrence_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=start_minutes)
                occurrence_end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=end_minutes)
                if end_minutes <= start_minutes:
                    occurrence_end += timedelta(days=1)
                if _intervals_overlap(occurrence_start, occurrence_end, window_start, window_end):
                    return True
    return False if parsed_entries == len(entries) else None


def _notam_role_window(
    flight: dict[str, Any],
    location: str,
    alternate_airports: set[str],
    edto_periods: dict[str, tuple[datetime, datetime]],
) -> tuple[str, datetime, datetime]:
    departure_utc = datetime.fromisoformat(flight["scheduled_departure_utc"])
    arrival_utc = datetime.fromisoformat(flight["scheduled_arrival_utc"])
    departure_margin = timedelta(
        minutes=_configured_window_minutes("ODSS_NOTAM_DEPARTURE_WINDOW_MINUTES", 60)
    )
    arrival_margin = timedelta(
        minutes=_configured_window_minutes("ODSS_NOTAM_ARRIVAL_WINDOW_MINUTES", 120)
    )
    if location == flight["departure"]:
        return "departure", departure_utc - departure_margin, departure_utc + departure_margin
    if location == flight["destination"]:
        return "destination", arrival_utc - arrival_margin, arrival_utc + arrival_margin
    if location in alternate_airports:
        return "destination alternate", arrival_utc - arrival_margin, arrival_utc + arrival_margin
    if location in edto_periods:
        starts_at, ends_at = edto_periods[location]
        return "EDTO", starts_at, ends_at
    return "informational", departure_utc, arrival_utc


def _configured_window_minutes(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number of minutes.") from exc
    if not 0 <= minutes <= 720:
        raise ValueError(f"{name} must be between 0 and 720 minutes.")
    return minutes


def _profile_applies_to_aircraft(
    profile: dict[str, Any],
    registration: str | None,
    aircraft_type: str | None,
) -> bool:
    effectivity = {
        re.sub(r"[^A-Z0-9]", "", str(value).upper())
        for value in profile.get("effectivity", [])
        if value
    }
    if not effectivity or "ALL" in effectivity:
        return True
    return bool(effectivity & aircraft_effectivity_tokens(registration, aircraft_type))


def detect_terrain_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    preceding = None
    last_msa = None
    for waypoint in waypoints:
        msa = waypoint.get("msa_hundreds_ft")
        if msa is None:
            continue
        if waypoint.get("msa_asterisk") or msa > 100:
            if not active:
                preceding = last_msa
            active.append(waypoint)
        elif active:
            events.append({
                "preceding": preceding,
                "first_high": active[0],
                "last_high": active[-1],
                "drop": waypoint,
                "maximum": max(active, key=lambda w: w.get("msa_hundreds_ft") or -1),
            })
            active = []
            preceding = None
        last_msa = waypoint
    if active:
        events.append({
            "preceding": preceding,
            "first_high": active[0],
            "last_high": active[-1],
            "drop": None,
            "maximum": max(active, key=lambda w: w.get("msa_hundreds_ft") or -1),
        })
    return events


def detect_vws_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for waypoint in waypoints:
        vws = waypoint.get("vws")
        if vws is None:
            if active and not waypoint.get("fir_boundary"):
                events.append({
                    "first_high": active[0],
                    "last_high": active[-1],
                    "drop": waypoint,
                    "maximum": max(active, key=lambda w: w.get("vws") or -1),
                })
                active = []
            continue
        if vws > 4:
            active.append(waypoint)
        elif active:
            events.append({
                "first_high": active[0],
                "last_high": active[-1],
                "drop": waypoint,
                "maximum": max(active, key=lambda w: w.get("vws") or -1),
            })
            active = []
    if active:
        events.append({
            "first_high": active[0],
            "last_high": active[-1],
            "drop": None,
            "maximum": max(active, key=lambda w: w.get("vws") or -1),
        })
    return events


def _subsequence(sequence: list[str], candidate: list[str]) -> bool:
    if not candidate:
        return True
    position = 0
    for item in sequence:
        if item == candidate[position]:
            position += 1
            if position == len(candidate):
                return True
    return False


def _route_waypoint_name(waypoint: dict[str, Any]) -> str:
    return str(waypoint.get("name") or "").lstrip("-").upper()


def _profile_aliases(profile: dict[str, Any], field: str) -> set[str]:
    fallback = str(profile.get(field) or "").upper()
    return {
        str(value).lstrip("-").upper()
        for value in profile.get(f"{field}_aliases", [fallback])
        if value
    }


def _route_airways_between(
    waypoints: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> list[str]:
    return [
        str(waypoints[index].get("airway_in") or "").upper()
        for index in range(start_index + 1, end_index + 1)
        if waypoints[index].get("airway_in")
    ]


def _profile_route_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    published_airways = [str(value).upper() for value in profile.get("airways", [])]
    spans: list[dict[str, Any]] = []
    for from_index, name in enumerate(names):
        if name not in from_aliases:
            continue
        for to_index, to_name in enumerate(names):
            if to_name not in to_aliases or to_index == from_index:
                continue
            if from_index < to_index:
                start_index, end_index = from_index, to_index
                expected_airways = published_airways
                direction = "forward"
            else:
                start_index, end_index = to_index, from_index
                expected_airways = list(reversed(published_airways))
                direction = "reverse"
            route_airways = _route_airways_between(waypoints, start_index, end_index)
            if expected_airways and not _subsequence(route_airways, expected_airways):
                continue
            spans.append(
                {
                    "start_index": start_index,
                    "end_index": end_index,
                    "route_start": names[start_index],
                    "route_end": names[end_index],
                    "airways": expected_airways,
                    "route_airways": route_airways,
                    "direction": direction,
                }
            )
    return spans


def match_profiles(
    flight: dict[str, Any],
    terrain_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waypoints = flight["route_waypoints"]
    matches: list[dict[str, Any]] = []
    for event in terrain_events:
        event_start_wp = event.get("preceding") or event["first_high"]
        event_start_index = waypoints.index(event_start_wp)
        event_end_index = waypoints.index(event["last_high"])
        required_edges = set(range(event_start_index, event_end_index))
        if not required_edges:
            required_edges = {event_start_index}

        candidate_by_chart: dict[str, dict[str, Any]] = {}
        for profile in DEPRESS_PROFILES:
            if not _profile_applies_to_aircraft(
                profile,
                flight.get("registration"),
                flight.get("aircraft_type"),
            ):
                continue
            for span in _profile_route_spans(profile, waypoints):
                if event_end_index == event_start_index:
                    covered = (
                        {event_start_index}
                        if span["start_index"] <= event_start_index <= span["end_index"]
                        else set()
                    )
                else:
                    covered = set(
                        range(
                            max(span["start_index"], event_start_index),
                            min(span["end_index"], event_end_index),
                        )
                    )
                if not covered:
                    continue
                candidate = {
                    **span,
                    "event": event,
                    "profile": profile,
                    "covered_edges": covered,
                }
                chart = str(profile.get("chart") or "")
                current = candidate_by_chart.get(chart)
                candidate_score = (len(covered), -(span["end_index"] - span["start_index"]))
                current_score = (
                    (len(current["covered_edges"]), -(current["end_index"] - current["start_index"]))
                    if current
                    else (-1, 0)
                )
                if current is None or candidate_score > current_score:
                    candidate_by_chart[chart] = candidate

        uncovered = set(required_edges)
        available = list(candidate_by_chart.values())
        selected: list[dict[str, Any]] = []
        while uncovered:
            useful = [
                (len(item["covered_edges"] & uncovered), item)
                for item in available
            ]
            useful = [entry for entry in useful if entry[0] > 0]
            if not useful:
                break
            _, best = max(
                useful,
                key=lambda entry: (
                    entry[0],
                    len(entry[1]["covered_edges"]),
                    -(entry[1]["end_index"] - entry[1]["start_index"]),
                    str(entry[1]["profile"].get("chart") or ""),
                ),
            )
            selected.append(best)
            uncovered -= best["covered_edges"]
            available = [item for item in available if item is not best]

        coverage_complete = not uncovered
        selected.sort(key=lambda item: (item["start_index"], item["end_index"]))
        for item in selected:
            matches.append(
                {
                    "event": event,
                    "profile": item["profile"],
                    "names": [
                        _route_waypoint_name(value)
                        for value in waypoints[item["start_index"] : item["end_index"] + 1]
                    ],
                    "airways": item["airways"],
                    "route_start": item["route_start"],
                    "route_end": item["route_end"],
                    "direction": item["direction"],
                    "coverage_complete": coverage_complete,
                    "uncovered_edge_count": len(uncovered),
                    "start_index": item["start_index"],
                    "end_index": item["end_index"],
                }
            )

    deduplicated: dict[tuple[int, str], dict[str, Any]] = {}
    for match in matches:
        key = (match["event"]["first_high"]["actm_minutes"], match["profile"]["chart"])
        deduplicated[key] = match
    return sorted(
        deduplicated.values(),
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )



def analyse(flight: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    reference_library_used = False
    fuel = flight["fuel"]
    masses = flight["masses"]
    performance = flight["performance"]

    findings.append(finding(
        "page1",
        "information",
        "CFP Page 1 organised control summary",
        f"{flight['flight_number']} {flight['departure']}-{flight['destination']}",
        [
            f"{flight['departure']}/{flight.get('departure_runway') or '-'} to "
            f"{flight['destination']}/{flight.get('destination_runway') or '-' }.",
            f"Scheduled departure {flight['scheduled_departure_utc']}; "
            f"arrival {flight['scheduled_arrival_utc']}.",
            f"Level profile: {flight.get('planned_level_profile') or 'not parsed'}.",
            f"Fuel required {format_kg(fuel['flight_plan_required_fuel_kg'])}; "
            f"tanks {format_kg(fuel['fuel_in_tanks_kg'])}; "
            f"trip {format_kg(fuel['trip_fuel_kg'])}.",
            f"PZFW {format_kg(masses['planned_zfw_kg'])}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; "
            f"PLWT {format_kg(masses['planned_landing_weight_kg'])}.",
        ],
    ))

    if flight.get("bobcat"):
        allocation = flight["bobcat"]
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"].upper() == allocation["waypoint"].upper()),
            None,
        )
        ctot = datetime.fromisoformat(allocation["ctot_utc"])
        cto = datetime.fromisoformat(allocation["cto_utc"])
        if cto < ctot:
            cto += timedelta(days=1)
        predicted = ctot + timedelta(minutes=waypoint["actm_minutes"]) if waypoint else None
        difference = round((predicted - cto).total_seconds() / 60) if predicted else None
        findings.append(finding(
            "bobcat",
            "critical" if difference not in (None, 0) else "warning" if difference is None else "information",
            "BOBCAT timing reconciliation",
            (
                f"{allocation['waypoint']}: predicted CTO difference {difference:+d} min."
                if difference is not None
                else "BOBCAT waypoint ACTM not found."
            ),
            [
                f"Allocation CTOT {ctot:%H%MZ}; CTO {cto:%H%MZ}; FL{allocation['flight_level']}.",
                f"CFP waypoint ACTM {format_actm(waypoint['actm_minutes']) if waypoint else 'not found'}.",
                "Treat the allocated CTO as controlling and recheck if take-off, route, level or speed changes.",
            ],
            {"difference_minutes": difference},
        ))

    for item in flight["deferred_items"]:
        if item["item_type"] == "MEL":
            reference = MEL_REFERENCES.get(item["reference"])
            if reference:
                reference_library_used = True
                details = [
                    f"Repair interval {reference.get('repair_interval')}; "
                    f"installed {reference.get('installed')}; required {reference.get('required')}.",
                    f"Placard {'required' if reference.get('placard_required') else 'not required/none stated'}; "
                    f"operational procedure {'required' if reference.get('operational_procedure_required') else 'not stated'}.",
                    *reference.get("terms", []),
                ]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "warning",
                    f"MEL {item['reference']} - {item['description']}",
                    "Candidate local-library match; verify the current approved MEL before use.",
                    details,
                    {
                        "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                    },
                ))
            else:
                findings.append(finding(
                    "mel",
                    "unknown",
                    f"MEL {item['reference']} not verified",
                    "The approved MEL reference is missing from the local library.",
                    [item["description"]],
                ))
        elif item["item_type"] == "CDL":
            reference_key = str(item.get("reference") or "").upper()
            record = CDL_REFERENCES.get(reference_key)
            if record is None:
                mounted = CDL_LIBRARY_METADATA.get("status") != "controlled-source-not-mounted"
                findings.append(finding(
                    "cdl",
                    "unknown",
                    f"CDL {reference_key} not resolved",
                    (
                        "Reference not found in the mounted controlled CDL index."
                        if mounted
                        else "The private controlled CDL index is not mounted."
                    ),
                    [
                        item.get("description") or "No Page 1 description parsed.",
                        item.get("company_remark") or "No Page 1 company remark parsed.",
                    ],
                    {
                        "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                        "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    },
                ))
                continue

            variants = select_cdl_variants(record, flight.get("registration"))
            if not variants:
                findings.append(finding(
                    "cdl",
                    "critical",
                    f"CDL {reference_key} effectivity conflict",
                    f"No controlled variant applies to registration {flight.get('registration') or 'not parsed'}.",
                    [record.get("title") or "Title not available."],
                    {
                        "source_pages": record.get("source_pages", []),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    },
                ))
                continue

            details = [
                f"Page 1: {item.get('description') or 'description not parsed'}.",
            ]
            if item.get("company_remark"):
                details.append(f"Company remark: {item['company_remark']}.")
            takeoff_penalties: list[int] = []
            enroute_penalties: list[int] = []
            fuel_penalties: list[float] = []
            for number, variant in enumerate(variants, start=1):
                label = variant.get("component") or record.get("title") or reference_key
                quantity = variant.get("quantity_installed")
                details.append(
                    f"Applicable variant {number}: {label}"
                    + (f"; quantity installed {quantity}." if quantity is not None else ".")
                )
                for field, prefix in (
                    ("dispatch_conditions", "Dispatch"),
                    ("limitations", "Limitation"),
                ):
                    if variant.get(field):
                        details.append(f"{prefix}: {variant[field]}")
                details.extend(f"Note: {value}" for value in variant.get("notes", []) if value)
                if variant.get("maintenance_references"):
                    details.append(
                        "Maintenance reference: "
                        + ", ".join(variant["maintenance_references"])
                        + "."
                    )
                if variant.get("mel_references"):
                    details.append(
                        "MEL interface: " + ", ".join(variant["mel_references"]) + "."
                    )
                takeoff_penalties.extend(variant.get("takeoff_approach_penalty_kg_values", []))
                enroute_penalties.extend(variant.get("enroute_penalty_kg_values", []))
                fuel_penalties.extend(variant.get("fuel_penalty_percent_values", []))

            takeoff_penalties = list(dict.fromkeys(takeoff_penalties))
            enroute_penalties = list(dict.fromkeys(enroute_penalties))
            fuel_penalties = list(dict.fromkeys(fuel_penalties))
            if takeoff_penalties:
                details.append(
                    "Published take-off/approach penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in takeoff_penalties)
                    + "."
                )
            if enroute_penalties:
                details.append(
                    "Published enroute penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in enroute_penalties)
                    + "."
                )
            if fuel_penalties:
                details.append(
                    "Published fuel increase value(s): "
                    + ", ".join(f"{value:g}%" for value in fuel_penalties)
                    + "."
                )
            details.append(
                f"Controlled source issue {CDL_LIBRARY_METADATA.get('issue_date')}; "
                f"page(s) {', '.join(str(value) for value in record.get('source_pages', [])) or 'not indexed'}."
            )
            findings.append(finding(
                "cdl",
                "warning",
                f"CDL {reference_key} - {record.get('title') or item.get('description') or 'item'}",
                "Controlled registration-specific CDL match.",
                details,
                {
                    "reference": reference_key,
                    "source_pages": record.get("source_pages", []),
                    "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                    "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    "takeoff_approach_penalty_kg_values": takeoff_penalties,
                    "enroute_penalty_kg_values": enroute_penalties,
                    "fuel_penalty_percent_values": fuel_penalties,
                    "applicable_variant_count": len(variants),
                },
            ))
        else:
            findings.append(finding(
                "cddl",
                "unknown",
                f"{item['item_type']} {item['reference']} not verified",
                "The approved configuration-deviation reference is missing.",
                [item["description"], item.get("company_remark") or "No company remark parsed."],
            ))

    candidates = [
        x for x in (
            performance.get("obstacle_rtow_kg"),
            performance.get("landing_rtow_kg"),
            performance.get("structural_rtow_kg"),
        )
        if x is not None
    ]
    controlling = performance.get("controlling_rtow_kg") or (min(candidates) if candidates else None)
    margin = controlling - masses["planned_takeoff_weight_kg"] if controlling is not None else None
    findings.append(finding(
        "performance",
        "warning" if margin is not None and margin < 5000 else "information",
        "Take-off performance summary",
        f"Conditional RTOW margin {format_kg(margin)}.",
        [
            f"Runway {performance.get('runway') or 'not parsed'}; "
            f"condition {performance.get('runway_condition') or 'not parsed'}; "
            f"thrust {performance.get('thrust_setting') or 'not parsed'}; "
            f"flaps {performance.get('flap_setting') if performance.get('flap_setting') is not None else 'not parsed'}.",
            f"Temperature {performance.get('temperature_c')} C; QNH {performance.get('qnh_hpa')} hPa; "
            f"wind {performance.get('wind')}.",
            f"Packs {_switch_state(performance.get('packs_on'))}; "
            f"anti-ice {_switch_state(performance.get('anti_ice_on'))}; "
            f"EOSID {performance.get('eosid') or 'not parsed'}.",
            f"Obstacle RTOW {format_kg(performance.get('obstacle_rtow_kg'))}; "
            f"landing RTOW {format_kg(performance.get('landing_rtow_kg'))}; "
            f"structural RTOW {format_kg(performance.get('structural_rtow_kg'))}.",
            f"Controlling RTOW {format_kg(controlling)}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; margin {format_kg(margin)}.",
            "The margin is conditional on every stated input and applicable MEL/CDL effect.",
        ],
        {"controlling_rtow_kg": controlling, "margin_kg": margin},
    ))

    vaa_review = flight.get("vaa_review") or {}
    if vaa_review.get("status") == "affected":
        vaa_matches = vaa_review.get("matches") or []
        first_match = vaa_matches[0] if vaa_matches else {}
        details = [
            (
                f"{item.get('advisory_id')}: {item.get('route_from')}-"
                f"{item.get('route_to')} at FL{item.get('planned_flight_level')}, "
                f"{item.get('segment_start_utc')} to {item.get('segment_end_utc')}."
            )
            for item in vaa_matches[:8]
        ]
        details.extend([
            f"Source: {vaa_review.get('provider') or 'not identified'}.",
            f"Retrieved: {vaa_review.get('retrieved_at_utc') or 'not available'}.",
            "Boundary contact is treated as an intersection; verify the original advisory and dispatch guidance.",
        ])
        findings.append(finding(
            "vaa",
            "critical",
            "Volcanic ash affects the planned route",
            f"{len(vaa_matches)} route/time/flight-level intersection(s) verified.",
            details,
            {
                "status": "affected",
                "start_actm_minutes": first_match.get("start_actm_minutes"),
                "match_count": len(vaa_matches),
                "provider": vaa_review.get("provider"),
                "reason_codes": vaa_review.get("reason_codes") or [],
            },
        ))
    elif vaa_review.get("status") == "review_required":
        reason_codes = vaa_review.get("reason_codes") or []
        human_reasons = {
            "source_unavailable": "The official live source was unavailable.",
            "source_stale": "The source snapshot did not meet the configured freshness limit.",
            "source_records_incomplete": "One or more volcanic-ash records could not be normalized.",
            "coverage_not_complete_for_flight": "The live active-SIGMET feed does not prove the full future flight window clear.",
            "cfp_weather_data_unavailable": "The CFP states that volcanic-ash weather data is unavailable.",
            "route_geometry_unavailable": "The CFP route geometry is incomplete.",
            "route_timing_unavailable": "The route timing anchor is unavailable.",
            "flight_level_unavailable": "The planned flight level could not be resolved.",
            "flight_level_change_unresolved": "A planned level-change waypoint could not be matched to the route.",
            "advisory_geometry_invalid": "An advisory geometry could not be evaluated safely.",
        }
        details = [human_reasons.get(code, code.replace("_", " ").capitalize() + ".") for code in reason_codes]
        details.extend([
            f"Source: {vaa_review.get('provider') or 'not available'}.",
            f"Retrieved: {vaa_review.get('retrieved_at_utc') or 'not available'}.",
            "Do not interpret this state as 'no volcanic ash'; complete the manual advisory review.",
        ])
        findings.append(finding(
            "vaa",
            "unknown",
            "Volcanic ash review required",
            "ODSS could not safely confirm that volcanic ash is not applicable to the route.",
            details,
            {
                "status": "review_required",
                "provider": vaa_review.get("provider"),
                "reason_codes": reason_codes,
            },
        ))
        warnings.append(
            "Volcanic ash applicability remains unresolved; review the current official advisory source."
        )

    alternate_airports = {a["airport"] for a in flight["alternates"]}
    edto_airports = {a["airport"] for a in flight["edto"]["airports"]}
    edto_periods: dict[str, tuple[datetime, datetime]] = {}
    for airport in flight["edto"]["airports"]:
        starts_at = datetime.fromisoformat(airport["period_start_utc"])
        ends_at = datetime.fromisoformat(airport["period_end_utc"])
        current = edto_periods.get(airport["airport"])
        edto_periods[airport["airport"]] = (
            min(starts_at, current[0]) if current else starts_at,
            max(ends_at, current[1]) if current else ends_at,
        )
    for record in flight["weather"]:
        location = record["location"]
        role = (
            "departure" if location == flight["departure"]
            else "destination" if location == flight["destination"]
            else "destination alternate" if location in alternate_airports
            else "EDTO airport" if location in edto_airports
            else "enroute"
        )
        upper = record["text"].upper()
        significant = bool(re.search(r"\b(TS|TSRA|CB|CAVOK|BKN00\d|OVC00\d|G\d{2}KT|WS)\b", upper))
        if role == "enroute" and not significant:
            continue
        severity = "warning" if any(x in upper for x in ("TS", "CB", "BKN00", "OVC00")) else "information"
        findings.append(finding(
            "weather",
            severity,
            f"{role.title()} weather - {location}",
            record["text"],
            [f"Record type: {record['record_type']}."],
        ))

    for record in flight["notams"]:
        location = record["location"]
        role, window_start, window_end = _notam_role_window(
            flight,
            location,
            alternate_airports,
            edto_periods,
        )
        valid_from = datetime.fromisoformat(record["valid_from_utc"])
        valid_to = (
            datetime.fromisoformat(record["valid_to_utc"])
            if record.get("valid_to_utc")
            else datetime.max.replace(tzinfo=timezone.utc)
        )
        applicability = "active"
        if record.get("validity_review"):
            applicability = "review"
            warnings.append(f"{record['notam_id']}: B/C validity could not be parsed; manual review required.")
        elif not _intervals_overlap(valid_from, valid_to, window_start, window_end):
            continue
        schedule = record.get("schedule")
        if schedule:
            schedule_active = _schedule_overlaps(schedule, window_start, window_end)
            if schedule_active is False:
                continue
            if schedule_active is None:
                applicability = "review"
                warnings.append(f"{record['notam_id']}: D schedule could not be evaluated; manual review required.")
        elif record.get("schedule_review"):
            applicability = "review"
            warnings.append(f"{record['notam_id']}: schedule language could not be structured; manual review required.")
        upper = record["text"].upper()
        severity = "warning"
        if re.search(r"(?<![A-Z0-9])(?:CLSD|CLOSED|U/S|NOT AVBL|SUSPENDED)(?![A-Z0-9])", upper):
            severity = "critical" if role in {"departure", "destination"} else "warning"
        details = [
            *([f"Schedule: {schedule}."] if schedule else []),
            f"Operating window {window_start.isoformat()} to {window_end.isoformat()}.",
            f"Location {location}; category {record['category']}.",
            f"Validity {record['valid_from_utc']} to {record.get('valid_to_utc') or 'UFN'}.",
            *(["Applicability requires manual review."] if applicability == "review" else []),
        ]
        findings.append(finding(
            "notam",
            severity,
            f"{role.title()} NOTAM {record['notam_id']}",
            record["text"][:260],
            details,
            {
                "role": role,
                "location": location,
                "notam_id": record["notam_id"],
                "priority_score": record.get("priority_score", 0),
                "applicability": applicability,
                "schedule": schedule,
                "window_start_utc": window_start.isoformat(),
                "window_end_utc": window_end.isoformat(),
            },
        ))

    waypoint_by_boundary = {
        w["fir_boundary"]: w
        for w in flight["route_waypoints"]
        if w.get("fir_boundary")
    }
    for rule in COMMUNICATION_RULES:
        waypoint = waypoint_by_boundary.get(rule["boundary"])
        if not waypoint:
            continue
        reference_library_used = True
        action_time = waypoint["actm_minutes"] - rule["lead"]
        details = [
            f"Boundary ACTM {format_actm(waypoint['actm_minutes'])}; lead {rule['lead']} min.",
            f"Action: {rule['action']}.",
        ]
        if rule.get("frequency"):
            details.append(
                f"Frequency {rule['frequency']} MHz"
                + (f"; backup {rule['backup']} MHz." if rule.get("backup") else ".")
            )
        if rule.get("notes"):
            details.append(rule["notes"])
        findings.append(finding(
            "communications",
            "warning",
            f"Early ATC/FIR action before {rule['boundary']}",
            f"ACTM {format_actm(action_time)} - {rule['agency']}.",
            details,
            {
                "action_actm_minutes": action_time,
                "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                "reference_status": REFERENCE_LIBRARY_METADATA["status"],
            },
        ))

    terrain_events = detect_terrain_events(flight["route_waypoints"])
    for index, event in enumerate(terrain_events, start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        max_msa = maximum["msa_hundreds_ft"]
        findings.append(finding(
            "terrain",
            "warning",
            f"High-MSA event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, max {max_msa}*.",
            [
                f"First high-MSA waypoint {event['first_high']['name']}; "
                f"last high-MSA waypoint {event['last_high']['name']}.",
                f"Threshold drop at {event['drop']['name'] if event['drop'] else 'end of route data'}.",
                f"Maximum {max_msa}* ({max_msa * 100:,} ft) at {maximum['name']}, "
                f"ACTM {format_actm(maximum['actm_minutes'])}.",
                *(
                    [f"Profile matching context begins at {event['preceding']['name']}."]
                    if event.get("preceding") else []
                ),
            ],
            {
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "end_actm_minutes": end_wp["actm_minutes"],
                "maximum_msa_hundreds_ft": max_msa,
            },
        ))

    for index, event in enumerate(detect_vws_events(flight["route_waypoints"]), start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        findings.append(finding(
            "vws",
            "warning",
            f"VWS event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, maximum {maximum['vws']:03d}.",
            [
                f"First qualifying waypoint {event['first_high']['name']}.",
                f"Last qualifying waypoint {event['last_high']['name']}.",
                f"Maximum at {maximum['name']}, ACTM {format_actm(maximum['actm_minutes'])}.",
                "Threshold is strictly greater than 4.",
            ],
            {"start_actm_minutes": event["first_high"]["actm_minutes"]},
        ))

    matches = sorted(
        match_profiles(flight, terrain_events),
        key=lambda x: (x["event"]["first_high"]["actm_minutes"], x["start_index"]),
    )
    for index, match in enumerate(matches, start=1):
        event = match["event"]
        profile = match["profile"]
        route_start = match["route_start"]
        route_end = match["route_end"]
        critical = profile["critical"]
        critical_aliases = _profile_aliases(profile, "critical")
        critical_wp = next(
            (
                waypoint
                for waypoint in flight["route_waypoints"]
                if _route_waypoint_name(waypoint) in critical_aliases
            ),
            None,
        )
        maximum = event["maximum"]
        end_wp = event["drop"] or event["last_high"]
        details = [
            f"High-MSA event ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}.",
            f"Maximum MSA {maximum['msa_hundreds_ft']}* "
            f"({maximum['msa_hundreds_ft'] * 100:,} ft) at {maximum['name']}.",
            f"Published chart route {profile['from']}-{profile['to']}; "
            f"airways {', '.join(profile['airways']) or 'none listed'}.",
            f"Critical point {critical}"
            + (
                f", CFP ACTM {format_actm(critical_wp['actm_minutes'])}."
                if critical_wp
                else "; ACTM not found."
            ),
            f"Controlled profile issue {DEPRESS_LIBRARY_METADATA.get('issue_date')}; "
            f"effective {profile.get('effective_date') or 'not indexed'}.",
        ]
        if profile.get("chart_page"):
            details.append(f"Controlled chart page {profile['chart_page']}.")
        if not match["coverage_complete"]:
            details.append(
                f"Coverage incomplete: {match['uncovered_edge_count']} event route leg(s) remain unmatched."
            )
        findings.append(finding(
            "depressurisation",
            "warning" if match["coverage_complete"] else "unknown",
            f"Profile {index} - {route_start} to {route_end} "
            f"({' / '.join(match['airways']) or 'airway review required'})",
            f"Proposed depressurisation chart {profile['chart']}; critical point {critical}.",
            details,
            {
                "chart_number": profile["chart"],
                "critical_point": critical,
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "route_start": route_start,
                "route_end": route_end,
                "coverage_complete": match["coverage_complete"],
                "controlled_issue_date": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "chart_page": profile.get("chart_page"),
            },
        ))
    if terrain_events and not matches:
        findings.append(finding(
            "depressurisation",
            "unknown",
            "High terrain detected but no profile matched",
            "Manual chart-index review is required.",
        ))

    edto = flight["edto"]
    if edto.get("entry_actm_minutes") is not None:
        details = [
            f"Entry ACTM {format_actm(edto['entry_actm_minutes'])}; "
            f"exit ACTM {format_actm(edto.get('exit_actm_minutes'))}."
        ]
        if edto.get("etp_actm_minutes"):
            details.append(
                "ETP ACTM: "
                + ", ".join(format_actm(x) for x in edto["etp_actm_minutes"])
                + "."
            )
        details.extend(
            f"{a['airport']} checked {datetime.fromisoformat(a['period_start_utc']):%H%MZ}-"
            f"{datetime.fromisoformat(a['period_end_utc']):%H%MZ}, RWY {a['runway']} "
            f"{a['approach']}, minima {a['minima']}."
            for a in edto["airports"]
        )
        findings.append(finding(
            "edto",
            "information",
            "EDTO checked-period summary",
            f"ACTM {format_actm(edto['entry_actm_minutes'])}-"
            f"{format_actm(edto.get('exit_actm_minutes'))}.",
            details,
            {"start_actm_minutes": edto["entry_actm_minutes"]},
        ))

    timeline_items: list[tuple[int, str, str]] = []
    for item in findings:
        if item["engine"] in {"vaa", "communications", "terrain", "vws", "depressurisation", "edto"}:
            data = item.get("data", {})
            actm = data.get("action_actm_minutes")
            if actm is None:
                actm = data.get("start_actm_minutes")
            if actm is not None:
                timeline_items.append((actm, item["title"], item["summary"]))
    if flight.get("bobcat"):
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"] == flight["bobcat"]["waypoint"]),
            None,
        )
        if waypoint:
            timeline_items.append((
                waypoint["actm_minutes"],
                f"BOBCAT {waypoint['name']}",
                f"FL{flight['bobcat']['flight_level']} CTO "
                f"{datetime.fromisoformat(flight['bobcat']['cto_utc']):%H%MZ}.",
            ))
    timeline_items.sort(key=lambda x: x[0])
    findings.append(finding(
        "timeline",
        "information",
        "Route-critical ACTM timeline",
        f"{len(timeline_items)} ordered operational events.",
        [f"ACTM {format_actm(a)} - {b}: {c}" for a, b, c in timeline_items[:24]],
    ))

    calculated_destination = (
        fuel["fuel_in_tanks_kg"] - fuel["taxi_fuel_kg"] - fuel["trip_fuel_kg"]
    )
    difference = calculated_destination - fuel["planned_destination_fuel_kg"]
    findings.append(finding(
        "qa",
        "information" if difference == 0 else "warning",
        "Destination fuel reconciliation",
        f"Calculated {format_kg(calculated_destination)}; "
        f"stated {format_kg(fuel['planned_destination_fuel_kg'])}; "
        f"difference {difference:+,} kg.",
    ))
    findings.append(finding(
        "qa",
        "information",
        "MSA 100* threshold handling",
        "A starred MSA qualifies; without an asterisk only numeric values strictly above 100 qualify.",
    ))
    if reference_library_used:
        warnings.insert(0, REFERENCE_LIBRARY_METADATA["notice"])
    return findings, warnings
