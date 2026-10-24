"""One selection of the route's maximum planned VWS, shared by every surface (open item #9, 24 Oct 2026).

David, 30 Sep 2026 (SIA297 WSSS-NZCH): "it seems only Sapda was flagged out but actually other waypoints also had
4 units as VWS". Each surface reduced the held samples with ``max()``, which keeps the first maximal waypoint in
route order and silently drops every other waypoint holding the same value. A maximum reached at several
waypoints is reached at each of them, so the selection here returns all of them, in route order, and every
surface - the governed review, the six-page PDF, the corroboration condition, the VWS event findings and the
timing events - reads it rather than choosing its own.

A printed surface with a fixed slot lists the first ``VWS_MAXIMUM_PRINT_LIMIT`` points and states how many more
are held at that value; the dashboard lists every point. Nothing is dropped without saying so.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from .constants import format_actm

# Waypoints a fixed printed slot names before it says "+K more at NNN (see dashboard)". Four covers the 16 Aug
# SQ297 SIN-CHC tie (RAMPY/UDONO/BLI/AS at 004) and every genuine corpus tie except SQ314 (8) and SQ910/SQ214 (5).
VWS_MAXIMUM_PRINT_LIMIT = 4


def held_vws(waypoint: dict[str, Any] | None) -> int | None:
    """The source-held planned VWS of one waypoint, or None. Missing is never zero."""
    value = (waypoint or {}).get("vws")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def vws_maximum_points(waypoints: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Every waypoint holding the greatest planned VWS value, in route order (empty when none is held)."""
    held = [(waypoint, value) for waypoint in waypoints or [] if (value := held_vws(waypoint)) is not None]
    if not held:
        return []
    top = max(value for _, value in held)
    return [waypoint for waypoint, value in held if value == top]


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def vws_maximum_entry(waypoint: dict[str, Any]) -> dict[str, Any]:
    """The published record of one maximum point: name, ACTM and OFP page, each None when not held."""
    actm = _non_negative_int(waypoint.get("actm_minutes"))
    return {
        "waypoint": str(waypoint.get("name") or "").lstrip("-").strip() or None,
        "actm_minutes": actm,
        "actm_display": format_actm(actm) if actm is not None else None,
        "source_page": _positive_int(waypoint.get("source_page")),
    }


def review_maximum_entries(review: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The maximum points a governed review publishes.

    A view built before the points were published carries only the single legacy fields; it is read as that one
    point, never widened by inference. Current views are rebuilt under the publication rules in service.
    """
    review = review or {}
    points = review.get("maximum_points")
    if isinstance(points, list):
        return [point for point in points if isinstance(point, dict)]
    if review.get("maximum") is None:
        return []
    return [{
        "waypoint": review.get("maximum_waypoint"),
        "actm_minutes": review.get("maximum_actm_minutes"),
        "actm_display": review.get("maximum_actm_display"),
        "source_page": review.get("source_page"),
    }]


def vws_maximum_listing(
    entries: list[dict[str, Any]],
    render: Callable[[dict[str, Any]], str],
    value_display: str,
    *,
    separator: str = ", ",
    limit: int = VWS_MAXIMUM_PRINT_LIMIT,
) -> str:
    """The first ``limit`` rendered points, then how many more are held at the value - never a silent cut."""
    listed = separator.join(render(entry) for entry in entries[:limit])
    more = len(entries) - limit
    if more > 0:
        listed += f"; +{more} more at {value_display} (see dashboard)"
    return listed


UNAVAILABLE_SUMMARY = "VWS review unavailable: no planned VWS value is held in the parsed OFP route."


def _located(entry: dict[str, Any]) -> str:
    evidence = [
        f"ACTM {entry['actm_display']}" if entry.get("actm_display") is not None else "",
        f"OFP p{entry['source_page']}" if entry.get("source_page") is not None else "",
    ]
    evidence = [item for item in evidence if item]
    return f"({', '.join(evidence)})" if evidence else ""


def vws_review_summary(review: dict[str, Any], *, limit: int = VWS_MAXIMUM_PRINT_LIMIT) -> str:
    """The governed VWS review sentence, composed from the review's own published fields.

    A single maximum reads as it always has. A tie names the first ``limit`` points and counts the rest; a fixed
    printed panel that cannot hold the published sentence asks for a smaller ``limit``, never a silent cut.
    """
    maximum = review.get("maximum")
    entries = review_maximum_entries(review)
    if maximum is None or not entries:
        return UNAVAILABLE_SUMMARY
    value = f"{int(maximum):03d}"
    maximum_text = f"maximum {value}"
    if len(entries) == 1:
        first = entries[0]
        if first.get("waypoint"):
            maximum_text += f" at {first['waypoint']}"
        if _located(first):
            maximum_text += f" {_located(first)}"
    else:
        maximum_text += f" at {len(entries)} waypoints: " + vws_maximum_listing(
            entries,
            lambda entry: " ".join(part for part in (entry.get("waypoint") or "unnamed waypoint", _located(entry)) if part),
            value,
            limit=limit,
        )
    event_count = int(review.get("event_count") or 0)
    if event_count:
        return f"VWS: {event_count} planned >004 trigger {'window' if event_count == 1 else 'windows'}; {maximum_text}."
    return f"VWS review: no planned >004 trigger in the source-held route values; {maximum_text}."


def vws_review_summary_variants(review: dict[str, Any] | None) -> list[str]:
    """The published sentence, then the same sentence naming fewer tied points (each still counting the rest).

    Only a fixed printed panel that cannot hold the published sentence takes a later variant.
    """
    review = review or {}
    published = str(review.get("summary") or "").strip() or UNAVAILABLE_SUMMARY
    variants = [published]
    count = len(review_maximum_entries(review))
    for limit in range(min(count, VWS_MAXIMUM_PRINT_LIMIT) - 1, 0, -1):
        variant = vws_review_summary(review, limit=limit)
        if variant not in variants:
            variants.append(variant)
    return variants
