from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import format_actm
from .engines import detect_terrain_events, detect_vws_events


def parse_utc(value: str) -> datetime:
    """Parse an ISO value and normalise it to minute-precision UTC."""
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Enter a valid UTC date and time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0)


def combine_utc_date_time(date_value: str, time_value: str) -> datetime:
    date_text = date_value.strip()
    time_text = time_value.strip()
    if not date_text or not time_text:
        raise ValueError("UTC date and time are required")
    if len(time_text) == 5:
        time_text = f"{time_text}:00"
    return parse_utc(f"{date_text}T{time_text}+00:00")


def display_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%d %b %H%MZ").upper()


def _normalised_waypoint(value: str) -> str:
    return value.strip().upper().lstrip("-")


def find_route_waypoint(flight: dict[str, Any], name: str) -> dict[str, Any]:
    wanted = _normalised_waypoint(name)
    if not wanted:
        raise ValueError("A reference waypoint is required for waypoint ATA mode")
    for waypoint in flight.get("route_waypoints", []):
        candidates = {
            _normalised_waypoint(str(waypoint.get("name") or "")),
            _normalised_waypoint(str(waypoint.get("fir_boundary") or "")),
        }
        if wanted in candidates:
            return waypoint
    raise ValueError(f"Waypoint {wanted} was not found in the parsed CFP route")


def derive_timing_reference(
    flight: dict[str, Any] | None,
    reference_type: str,
    reference_utc: str,
    reference_waypoint: str | None = None,
) -> dict[str, Any]:
    """Derive the time-zero anchor from ATOT or from an actual waypoint ATA."""
    reference = parse_utc(reference_utc)
    if reference_type == "takeoff":
        actual_takeoff = reference
        waypoint_name = None
        reference_actm = 0
    elif reference_type == "waypoint_ata":
        if not flight:
            raise ValueError("Run the CFP analysis before using waypoint ATA mode")
        waypoint = find_route_waypoint(flight, reference_waypoint or "")
        reference_actm = int(waypoint["actm_minutes"])
        actual_takeoff = reference - timedelta(minutes=reference_actm)
        waypoint_name = str(waypoint.get("fir_boundary") or waypoint.get("name") or "").lstrip("-")
    else:
        raise ValueError("Timing reference must be actual takeoff or waypoint ATA")

    return {
        "reference_type": reference_type,
        "reference_utc": reference.isoformat(),
        "reference_waypoint": waypoint_name,
        "reference_actm_minutes": reference_actm,
        "actual_takeoff_utc": actual_takeoff.isoformat(),
    }


def _time_at(anchor: datetime, actm_minutes: int) -> datetime:
    return anchor + timedelta(minutes=int(actm_minutes))


def _event(
    anchor: datetime,
    actm_minutes: int,
    label: str,
    category: str,
    details: str = "",
) -> dict[str, Any]:
    when = _time_at(anchor, actm_minutes)
    day_offset = (when.date() - anchor.date()).days
    return {
        "category": category,
        "label": label,
        "details": details,
        "actm_minutes": int(actm_minutes),
        "actm": format_actm(int(actm_minutes)),
        "utc_iso": when.isoformat(),
        "utc_display": display_utc(when),
        "utc_clock": when.strftime("%H%MZ"),
        "day_offset": day_offset,
        "day_label": f"D+{day_offset}" if day_offset >= 0 else f"D{day_offset}",
    }


def _deduplicate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[int, str, str], dict[str, Any]] = {}
    for event in events:
        key = (event["actm_minutes"], event["category"], event["label"])
        deduplicated[key] = event
    return sorted(
        deduplicated.values(),
        key=lambda item: (item["actm_minutes"], item["category"], item["label"]),
    )


def build_timing_view(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    actual_takeoff_utc: str,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate absolute UTC values while retaining ACTM as the source interval."""
    anchor = parse_utc(actual_takeoff_utc)
    scheduled_departure = parse_utc(flight["scheduled_departure_utc"])

    waypoint_times: list[dict[str, Any]] = []
    fir_crossings: list[dict[str, Any]] = []
    for waypoint in flight.get("route_waypoints", []):
        actm = waypoint.get("actm_minutes")
        if actm is None:
            continue
        calculated = _time_at(anchor, int(actm))
        waypoint["calculated_ata_utc"] = calculated.isoformat()
        item = {
            "name": waypoint.get("name"),
            "display_name": str(waypoint.get("fir_boundary") or waypoint.get("name") or "").lstrip("-"),
            "fir_boundary": waypoint.get("fir_boundary"),
            "airway_in": waypoint.get("airway_in"),
            "msa_hundreds_ft": waypoint.get("msa_hundreds_ft"),
            "vws": waypoint.get("vws"),
            "actm_minutes": int(actm),
            "actm": format_actm(int(actm)),
            "utc_iso": calculated.isoformat(),
            "utc_display": display_utc(calculated),
            "utc_clock": calculated.strftime("%H%MZ"),
            "day_offset": (calculated.date() - anchor.date()).days,
        }
        waypoint_times.append(item)
        if waypoint.get("fir_boundary"):
            fir_crossings.append(
                _event(
                    anchor,
                    int(actm),
                    f"{waypoint['fir_boundary']} FIR boundary",
                    "fir_crossing",
                    f"Route entry {waypoint.get('name')}; airway {waypoint.get('airway_in') or 'not parsed'}.",
                )
            )

    events: list[dict[str, Any]] = [
        _event(anchor, 0, "Actual takeoff / time-zero anchor", "takeoff", "UTC = ATOT + CFP ACTM."),
    ]

    for finding in findings:
        if finding.get("engine") != "communications":
            continue
        action_actm = finding.get("data", {}).get("action_actm_minutes")
        if action_actm is None:
            continue
        events.append(
            _event(
                anchor,
                int(action_actm),
                finding.get("title", "Early ATC/FIR action"),
                "early_call",
                finding.get("summary", ""),
            )
        )

    bobcat = flight.get("bobcat")
    if bobcat:
        try:
            waypoint = find_route_waypoint(flight, str(bobcat.get("waypoint") or ""))
        except ValueError:
            waypoint = None
        if waypoint:
            events.append(
                _event(
                    anchor,
                    int(waypoint["actm_minutes"]),
                    f"BOBCAT {bobcat['waypoint']} crossing",
                    "bobcat",
                    f"FL{bobcat.get('flight_level')} allocated CTO {bobcat.get('cto_utc')}.",
                )
            )

    edto = flight.get("edto") or {}
    if edto.get("entry_actm_minutes") is not None:
        events.append(_event(anchor, int(edto["entry_actm_minutes"]), "EDTO entry", "edto"))
    for index, actm in enumerate(edto.get("etp_actm_minutes") or [], start=1):
        events.append(_event(anchor, int(actm), f"EDTO ETP {index}", "edto"))
    if edto.get("exit_actm_minutes") is not None:
        events.append(_event(anchor, int(edto["exit_actm_minutes"]), "EDTO exit", "edto"))

    for index, terrain in enumerate(detect_terrain_events(flight.get("route_waypoints", [])), start=1):
        end_waypoint = terrain.get("drop") or terrain["last_high"]
        maximum = terrain["maximum"]
        events.extend([
            _event(
                anchor,
                int(terrain["first_high"]["actm_minutes"]),
                f"High-MSA event {index} starts at {terrain['first_high']['name']}",
                "terrain",
            ),
            _event(
                anchor,
                int(maximum["actm_minutes"]),
                f"High-MSA event {index} maximum at {maximum['name']}",
                "terrain",
                f"MSA {maximum['msa_hundreds_ft']}* ({maximum['msa_hundreds_ft'] * 100:,} ft).",
            ),
            _event(
                anchor,
                int(end_waypoint["actm_minutes"]),
                f"High-MSA event {index} ends at {end_waypoint['name']}",
                "terrain",
            ),
        ])

    for index, vws_event in enumerate(detect_vws_events(flight.get("route_waypoints", [])), start=1):
        end_waypoint = vws_event.get("drop") or vws_event["last_high"]
        maximum = vws_event["maximum"]
        events.extend([
            _event(
                anchor,
                int(vws_event["first_high"]["actm_minutes"]),
                f"VWS event {index} starts at {vws_event['first_high']['name']}",
                "vws",
            ),
            _event(
                anchor,
                int(maximum["actm_minutes"]),
                f"VWS event {index} maximum at {maximum['name']}",
                "vws",
                f"VWS {maximum['vws']:03d}.",
            ),
            _event(
                anchor,
                int(end_waypoint["actm_minutes"]),
                f"VWS event {index} ends at {end_waypoint['name']}",
                "vws",
            ),
        ])

    for finding in findings:
        if finding.get("engine") != "depressurisation":
            continue
        critical = finding.get("data", {}).get("critical_point")
        if not critical:
            continue
        try:
            waypoint = find_route_waypoint(flight, str(critical))
        except ValueError:
            continue
        events.append(
            _event(
                anchor,
                int(waypoint["actm_minutes"]),
                f"{finding['title']} critical point {critical}",
                "depressurisation",
                f"Chart {finding.get('data', {}).get('chart_number') or 'review required'}.",
            )
        )

    for waypoint_name, label, category in (
        ("TOD", "Top of descent", "descent"),
        (flight.get("destination", ""), "Destination crossing", "arrival"),
    ):
        if not waypoint_name:
            continue
        try:
            waypoint = find_route_waypoint(flight, str(waypoint_name))
        except ValueError:
            continue
        events.append(_event(anchor, int(waypoint["actm_minutes"]), label, category))

    events = _deduplicate(events)
    fir_crossings = _deduplicate(fir_crossings)
    early_calls = [event for event in events if event["category"] == "early_call"]
    takeoff_difference = round((anchor - scheduled_departure).total_seconds() / 60)
    timing_reference = reference or {
        "reference_type": "takeoff",
        "reference_utc": anchor.isoformat(),
        "reference_waypoint": None,
        "reference_actm_minutes": 0,
        "actual_takeoff_utc": anchor.isoformat(),
    }

    return {
        "actual_takeoff_utc": anchor.isoformat(),
        "actual_takeoff_display": display_utc(anchor),
        "scheduled_departure_utc": scheduled_departure.isoformat(),
        "schedule_difference_minutes": takeoff_difference,
        "reference": timing_reference,
        "calculation_basis": "Calculated UTC = derived actual takeoff UTC + CFP ACTM.",
        "events": events,
        "early_calls": early_calls,
        "fir_crossings": fir_crossings,
        "waypoints": waypoint_times,
        "event_count": len(events),
        "fir_crossing_count": len(fir_crossings),
        "waypoint_count": len(waypoint_times),
    }


def timing_finding(timing: dict[str, Any]) -> dict[str, Any]:
    reference = timing["reference"]
    if reference.get("reference_type") == "waypoint_ata":
        reference_summary = (
            f"Waypoint ATA {reference.get('reference_waypoint')} "
            f"{display_utc(parse_utc(reference['reference_utc']))} derives "
            f"ATOT {timing['actual_takeoff_display']}."
        )
    else:
        reference_summary = f"Actual takeoff {timing['actual_takeoff_display']}."

    details = [
        reference_summary,
        timing["calculation_basis"],
        f"Difference from scheduled departure {timing['schedule_difference_minutes']:+d} min.",
        *[
            f"{event['utc_display']} | ACTM {event['actm']} | {event['label']}"
            + (f" - {event['details']}" if event.get("details") else "")
            for event in timing["events"]
        ],
    ]
    return {
        "rule_id": "ACTUAL-TIMING-AUTO",
        "engine": "actual_timing",
        "severity": "information",
        "title": "Actual-time operational clock",
        "summary": (
            f"{timing['event_count']} pertinent UTC events, "
            f"{timing['fir_crossing_count']} FIR crossings and "
            f"{timing['waypoint_count']} waypoint times calculated."
        ),
        "details": details,
        "data": {
            "actual_takeoff_utc": timing["actual_takeoff_utc"],
            "reference_type": reference.get("reference_type"),
            "reference_waypoint": reference.get("reference_waypoint"),
            "event_count": timing["event_count"],
        },
    }


__all__ = [
    "build_timing_view",
    "combine_utc_date_time",
    "derive_timing_reference",
    "display_utc",
    "find_route_waypoint",
    "parse_utc",
    "timing_finding",
]
