from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Iterable

from .constants import format_actm


_NAT_SEGMENT = re.compile(
    r"\b([A-Z0-9]{2,7})\s+NAT([A-Z])\s+([A-Z0-9]{2,7})\b",
    re.IGNORECASE,
)


def _clean(value: Any, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _source_page(point: dict[str, Any]) -> str:
    page = point.get("source_page")
    return f"CFP p. {page}" if isinstance(page, int) and page > 0 else "Uploaded CFP"


def _departure_anchor(flight: dict[str, Any]) -> datetime | None:
    value = flight.get("scheduled_departure_utc")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def actm_utc_label(flight: dict[str, Any], actm_minutes: Any) -> str:
    try:
        minutes = int(actm_minutes)
    except (TypeError, ValueError):
        return "Time review required"
    anchor = _departure_anchor(flight)
    if anchor is None:
        return f"ACTM {format_actm(minutes)} / UTC anchor unavailable"
    utc = anchor + timedelta(minutes=minutes)
    return f"ACTM {format_actm(minutes)} / {utc:%d %b %H%MZ}".upper()


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
    """Return CFP-grounded route gates without inventing procedures.

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
                "result": "Track and timing parsed.",
                "status": "review_required",
                "evidence": evidence or "Uploaded CFP",
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
                "result": "Crossing time parsed.",
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
                "result": "Arrival timing parsed.",
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


__all__ = [
    "actm_utc_label",
    "build_route_gate_rows",
    "select_route_gate_rows",
]
