"""Which terrain windows an issued depressurisation chart covers.

One shared reading for every surface (David, 24 Oct 2026). The engine issues
each chart once per flight; its finding names every terrain window it protects
(``terrain_event_ids``) and, per window, the legs it covers and whether the
issued chart set covers that window completely (``window_coverage``). A window
that an issued chart covers only in part carries its own finding with
``coverage_state == "partial"`` naming the legs no indexed chart covers.

Findings saved before this contract carry one ``terrain_event_id`` and one
``coverage_complete`` flag; they are read as one chart for one window.
"""

from __future__ import annotations

from typing import Any

CONTROLLED = "controlled-index-loaded"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _data(finding: dict[str, Any]) -> dict[str, Any]:
    return (finding.get("data") or {}) if isinstance(finding, dict) else {}


def is_profile_chart_finding(finding: dict[str, Any]) -> bool:
    return (
        isinstance(finding, dict)
        and finding.get("engine") == "depressurisation"
        and bool(_text(_data(finding).get("chart_number")))
    )


def profile_window_coverage(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-window coverage rows of one chart finding (legacy: its one window)."""
    data = _data(finding)
    rows = data.get("window_coverage")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    event_id = _text(data.get("terrain_event_id"))
    if not event_id:
        return []
    return [{
        "terrain_event_id": event_id,
        "covered_legs": [],
        "window_complete": data.get("coverage_complete") is True,
    }]


def profile_finding_event_ids(finding: dict[str, Any]) -> list[str]:
    """Every terrain window a chart finding covers, in route order."""
    ids = [
        _text(row.get("terrain_event_id"))
        for row in profile_window_coverage(finding)
        if _text(row.get("terrain_event_id"))
    ]
    return list(dict.fromkeys(ids))


def window_row(finding: dict[str, Any], event_id: Any) -> dict[str, Any] | None:
    wanted = _text(event_id)
    return next(
        (
            row for row in profile_window_coverage(finding)
            if _text(row.get("terrain_event_id")) == wanted
        ),
        None,
    )


def covers_window_completely(finding: dict[str, Any], event_id: Any) -> bool:
    """A controlled chart finding whose issued chart set covers this window."""
    if not is_profile_chart_finding(finding):
        return False
    if _data(finding).get("reference_status") != CONTROLLED:
        return False
    row = window_row(finding, event_id)
    return bool(row and row.get("window_complete") is True)


def covers_window_partly(finding: dict[str, Any], event_id: Any) -> bool:
    """A controlled chart issued for some, not all, of this window's legs."""
    if not is_profile_chart_finding(finding):
        return False
    if _data(finding).get("reference_status") != CONTROLLED:
        return False
    row = window_row(finding, event_id)
    return bool(row and row.get("window_complete") is not True)


def window_status(event_id: Any, findings: list[dict[str, Any]]) -> str:
    """``complete``, ``partial`` (an issued chart covers part) or ``none``."""
    if any(covers_window_completely(item, event_id) for item in findings):
        return "complete"
    if any(covers_window_partly(item, event_id) for item in findings):
        return "partial"
    return "none"


def chart_legs_for_window(finding: dict[str, Any], event_id: Any) -> list[str]:
    row = window_row(finding, event_id) or {}
    return [str(leg) for leg in row.get("covered_legs") or [] if str(leg)]


def window_gap_finding(
    event_id: Any,
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The window's own finding when it is not fully covered."""
    wanted = _text(event_id)
    return next(
        (
            item for item in findings
            if isinstance(item, dict)
            and item.get("engine") == "depressurisation"
            and not is_profile_chart_finding(item)
            and _text(_data(item).get("terrain_event_id")) == wanted
        ),
        None,
    )


__all__ = [
    "chart_legs_for_window",
    "covers_window_completely",
    "covers_window_partly",
    "is_profile_chart_finding",
    "profile_finding_event_ids",
    "profile_window_coverage",
    "window_gap_finding",
    "window_row",
    "window_status",
]
