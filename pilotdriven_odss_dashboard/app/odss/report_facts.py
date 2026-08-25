from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Iterable

from .constants import format_actm
from .deferred_dispatch import (
    deferred_item_type_for_display,
    deferred_reference_for_display,
    deferred_source_declaration_for_display,
)


_NAT_SEGMENT = re.compile(
    r"\b([A-Z0-9]{2,7})\s+NAT([A-Z])\s+([A-Z0-9]{2,7})\b",
    re.IGNORECASE,
)


def _clean(value: Any, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _source_page(point: dict[str, Any]) -> str:
    page = point.get("source_page")
    return f"OFP p. {page}" if isinstance(page, int) and page > 0 else "Uploaded OFP"


def actual_timing_anchor(flight: dict[str, Any]) -> datetime | None:
    """Return an actual/derived take-off anchor, never a schedule surrogate."""
    reference = flight.get("timing_reference") or {}
    value = flight.get("actual_takeoff_utc") or reference.get("actual_takeoff_utc")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def actm_utc_clock(flight: dict[str, Any], actm_minutes: Any) -> str | None:
    """Return a UTC clock only when ATOT or waypoint ATA established time zero."""
    try:
        minutes = int(actm_minutes)
    except (TypeError, ValueError):
        return None
    anchor = actual_timing_anchor(flight)
    if anchor is None:
        return None
    utc = anchor + timedelta(minutes=minutes)
    return f"{utc:%d %b %H%MZ}".upper()


def actm_utc_label(flight: dict[str, Any], actm_minutes: Any) -> str:
    try:
        minutes = int(actm_minutes)
    except (TypeError, ValueError):
        return "Time review required"
    clock = actm_utc_clock(flight, minutes)
    if clock is None:
        return f"ACTM {format_actm(minutes)}"
    return f"ACTM {format_actm(minutes)} / {clock}"


def _named_point(
    points: Iterable[dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    target = name.upper().lstrip("-")
    return next(
        (
            point
            for point in points
            if _clean(point.get("name")).upper().lstrip("-") == target
        ),
        None,
    )


def build_route_gate_rows(flight: dict[str, Any]) -> list[dict[str, str]]:
    """Return OFP-grounded route gates without inventing procedures.

    The uploaded route can establish a named track segment, FIR boundary and
    crossing time. It cannot establish a current contact instruction or
    frequency unless an approved communications source is mounted. The
    report states that shared source gap once, outside these route rows.
    """

    points = [
        point
        for point in (flight.get("route_waypoints") or [])
        if isinstance(point, dict)
    ]
    rows: list[dict[str, str]] = []

    route_text = _clean(flight.get("route_text"))
    match = _NAT_SEGMENT.search(route_text)
    if match:
        entry_name, track, exit_name = match.groups()
        entry = _named_point(points, entry_name) or {}
        exit_point = _named_point(points, exit_name) or {}
        entry_actm = entry.get("actm_minutes")
        exit_actm = exit_point.get("actm_minutes")
        if entry_actm is not None and exit_actm is not None:
            time_label = (
                f"{actm_utc_label(flight, entry_actm)} - "
                f"{actm_utc_label(flight, exit_actm)}"
            )
        else:
            time_label = "Track timing review required"
        evidence = " / ".join(
            dict.fromkeys(
                value
                for value in (
                    _source_page(entry),
                    _source_page(exit_point),
                )
                if value
            )
        )
        rows.append(
            {
                "kind": "oceanic",
                "gate": f"NAT {track.upper()}",
                "basis": f"{entry_name.upper()} - {exit_name.upper()}",
                "time": time_label,
                "result": f"NAT {track.upper()} route segment",
                "status": "review_required",
                "evidence": evidence or "Uploaded OFP",
            }
        )

    previous_boundary = ""
    for point in points:
        boundary = _clean(point.get("fir_boundary")).upper()
        if not boundary or boundary == previous_boundary:
            continue
        previous_boundary = boundary
        rows.append(
            {
                "kind": "fir",
                "gate": boundary,
                "basis": _clean(point.get("name"), boundary).lstrip("-"),
                "time": actm_utc_label(flight, point.get("actm_minutes")),
                "result": "FIR boundary crossing",
                "status": "review_required",
                "evidence": _source_page(point),
            }
        )

    destination = _clean(flight.get("destination"), "Destination").upper()
    arrival_point = _named_point(points, destination)
    if arrival_point:
        rows.append(
            {
                "kind": "arrival",
                "gate": destination,
                "basis": "Arrival",
                "time": actm_utc_label(
                    flight,
                    arrival_point.get("actm_minutes"),
                ),
                "result": "Arrival",
                "status": "parsed",
                "evidence": _source_page(arrival_point),
            }
        )
    return rows


def select_route_gate_rows(
    rows: list[dict[str, str]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    """Select representative route gates without airport-specific rules."""

    if len(rows) <= limit:
        return rows
    pinned = [
        index
        for index, row in enumerate(rows)
        if row.get("kind") in {"oceanic", "arrival"}
    ]
    remaining = max(0, limit - len(pinned))
    candidates = [
        index
        for index in range(len(rows))
        if index not in pinned
    ]
    sampled: list[int] = []
    if remaining and candidates:
        if remaining == 1:
            sampled = [candidates[len(candidates) // 2]]
        else:
            sampled = [
                candidates[
                    round(position * (len(candidates) - 1) / (remaining - 1))
                ]
                for position in range(remaining)
            ]
    selected = sorted(dict.fromkeys(pinned + sampled))[:limit]
    return [rows[index] for index in selected]


def deferred_item_report_rows(
    flight: dict[str, Any],
    findings: Iterable[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Return OFP-declared deferred items with an honest source status.

    The declaration itself comes from OFP Page 1.  A model must never infer a
    missing MEL/CDL condition, so the row stays review-required unless the
    analysis already carries a governed-source result.
    """

    finding_list = [item for item in findings if isinstance(item, dict)]
    rows: list[dict[str, str]] = []
    for source_item in flight.get("deferred_items") or []:
        if not isinstance(source_item, dict):
            continue
        item_type = _clean(source_item.get("item_type"), "DEFERRED").upper()
        if item_type == "UNCLASSIFIED":
            source_declaration = deferred_source_declaration_for_display(
                source_item.get("source_declaration")
            )
            rows.append(
                {
                    "label": source_declaration or "DEFERRED ITEM - REVIEW REQUIRED",
                    "description": _clean(
                        source_item.get("description"),
                        "Following OFP text was not parsed.",
                    ),
                    "restriction": _clean(
                        source_item.get("company_remark"),
                        "No further OFP text was parsed.",
                    ),
                    "source_status": (
                        "OFP deferred declaration requires review; acronym meaning is not "
                        "inferred and no MEL, CDL or CDDL classification is asserted."
                    ),
                }
            )
            if limit is not None and len(rows) >= limit:
                break
            continue
        reference = deferred_reference_for_display(source_item.get("reference"))
        expected_engine = {
            "MEL": "mel",
            "CDL": "cdl",
            "CDDL": "cddl",
        }.get(item_type)
        matching = next(
            (
                item
                for item in finding_list
                if item.get("engine") == expected_engine
                and reference
                and reference in _clean(item.get("title")).upper()
            ),
            None,
        )
        summary = _clean(
            (matching or {}).get("summary"),
            "Approved deferred-item source is unavailable.",
        )
        severity = _clean((matching or {}).get("severity"), "unknown").lower()
        if severity == "unknown":
            source_status = f"Approved {item_type} source review required. {summary}"
        else:
            source_status = summary
        rows.append(
            {
                "label": " ".join(
                    value
                    for value in (
                        deferred_item_type_for_display(item_type),
                        reference,
                    )
                    if value
                ),
                "description": _clean(
                    source_item.get("description"),
                    "Description was not parsed from OFP Page 1.",
                ),
                "restriction": _clean(
                    source_item.get("company_remark"),
                    "No company restriction was parsed from OFP Page 1.",
                ),
                "source_status": source_status,
            }
        )
        if limit is not None and len(rows) >= limit:
            break
    return rows


def profile_findings_for_terrain_event(
    event: dict[str, Any],
    findings: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select only profile findings that belong to this terrain event.

    New analyses carry a stable ``terrain_event_id``. The ACTM fallback keeps
    previously stored analyses renderable without returning to the unsafe
    positional join that shifted profiles when an earlier event had no match.
    """

    candidates = [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("engine") == "depressurisation"
    ]
    event_id = _clean(event.get("terrain_event_id"))
    if event_id:
        direct = [
            finding
            for finding in candidates
            if _clean((finding.get("data") or {}).get("terrain_event_id"))
            == event_id
        ]
        if direct:
            return sorted(
                direct,
                key=lambda item: (
                    _clean((item.get("data") or {}).get("chart_number")),
                    _clean(item.get("summary")),
                ),
            )

    start_actm = (event.get("first_high") or {}).get("actm_minutes")
    if start_actm is None:
        return []
    legacy = [
        finding
        for finding in candidates
        if not _clean((finding.get("data") or {}).get("terrain_event_id"))
        and (finding.get("data") or {}).get("start_actm_minutes") == start_actm
    ]
    if legacy:
        return sorted(
            legacy,
            key=lambda item: (
                _clean((item.get("data") or {}).get("chart_number")),
                _clean(item.get("summary")),
            ),
        )
    global_review = [
        finding
        for finding in candidates
        if not _clean((finding.get("data") or {}).get("terrain_event_id"))
        and (finding.get("data") or {}).get("start_actm_minutes") is None
    ]
    return sorted(
        global_review,
        key=lambda item: (
            _clean((item.get("data") or {}).get("chart_number")),
            _clean(item.get("summary")),
        ),
    )


def is_confirmed_profile_finding(finding: dict[str, Any]) -> bool:
    data = finding.get("data") or {}
    return bool(
        data.get("chart_number")
        and data.get("reference_status") == "controlled-index-loaded"
        and data.get("coverage_complete") is True
    )


def profile_finding_label(finding: dict[str, Any]) -> str:
    data = finding.get("data") or {}
    chart = _clean(data.get("chart_number"), "UNNUMBERED")
    route_start = _clean(data.get("route_start"), "START")
    route_end = _clean(data.get("route_end"), "END")
    critical = _clean(data.get("critical_point"), "REVIEW")
    return f"{chart} {route_start}-{route_end} / CP {critical}"


def profile_coverage_label(findings: Iterable[dict[str, Any]]) -> str:
    candidates = [item for item in findings if isinstance(item, dict)]
    confirmed = [item for item in candidates if is_confirmed_profile_finding(item)]
    if confirmed:
        return "; ".join(profile_finding_label(item) for item in confirmed)
    partial = [
        _clean((item.get("data") or {}).get("chart_number"))
        for item in candidates
        if (item.get("data") or {}).get("chart_number")
    ]
    if partial:
        charts = ", ".join(dict.fromkeys(partial))
        return f"Incomplete coverage ({charts}) - review required"
    return "No exact profile confirmed - review required"


__all__ = [
    "actm_utc_clock",
    "actm_utc_label",
    "actual_timing_anchor",
    "build_route_gate_rows",
    "deferred_item_report_rows",
    "is_confirmed_profile_finding",
    "profile_coverage_label",
    "profile_finding_label",
    "profile_findings_for_terrain_event",
    "select_route_gate_rows",
]
