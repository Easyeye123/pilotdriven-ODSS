from __future__ import annotations

from typing import Any


HIGH_MSA_THRESHOLD_HUNDREDS_FT = 100


def is_high_msa_waypoint(waypoint: dict[str, Any]) -> bool:
    """Return True only when the parsed MSA is strictly above 10,000 ft.

    Lido may retain an asterisk at the threshold value ``100*``. The asterisk is
    preserved as source metadata, but the PilotDriven v1.2 briefing trigger is
    strictly ``MSA > 100*``. Therefore an exact numeric value of 100 is a
    boundary waypoint, not a qualifying high-terrain exposure waypoint.
    """
    msa = waypoint.get("msa_hundreds_ft")
    return isinstance(msa, (int, float)) and msa > HIGH_MSA_THRESHOLD_HUNDREDS_FT


def detect_terrain_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segment discrete CFP MSA values into strict ``>100*`` events.

    Each event starts at the first waypoint whose parsed MSA is greater than
    100 hundreds of feet and ends at the first subsequent waypoint at or below
    the threshold. A threshold break always separates events. No terrain is
    interpolated between waypoints.
    """
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    preceding: dict[str, Any] | None = None
    last_msa: dict[str, Any] | None = None

    for waypoint in waypoints:
        msa = waypoint.get("msa_hundreds_ft")
        if msa is None:
            continue

        if is_high_msa_waypoint(waypoint):
            if not active:
                preceding = last_msa
            active.append(waypoint)
        elif active:
            events.append({
                "preceding": preceding,
                "first_high": active[0],
                "last_high": active[-1],
                "drop": waypoint,
                "maximum": max(active, key=lambda item: item.get("msa_hundreds_ft") or -1),
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
            "maximum": max(active, key=lambda item: item.get("msa_hundreds_ft") or -1),
        })

    return events
