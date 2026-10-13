"""Which drawn route rows may stand for the flight's departure and destination aerodromes.

Item 11 (David, 3 Oct 2026: "It ended up instead of Singapore now is in Bali"). Every route map used to give the
departure ICAO to whichever coordinate-bearing row came first and the destination ICAO to whichever came last. When
navlog rows were lost or held no position, "WSSS" moved with them - on SQ297 SIN-CHC as far as BLI, the Bali VOR.
An aerodrome identity is now attached to a drawn row only when the OFP itself places that row at the aerodrome; a
map that cannot place an aerodrome says so and draws the row under its own name.

Destination: LIDO prints the destination aerodrome as the navlog's final row, with its coordinates. The last parsed
row must be that row, by name, and must hold its position.

Departure: a first row printed as the departure aerodrome itself places it. LIDO, though, never prints the
departure aerodrome; the navlog starts at the first fix after take-off (4.6-14.2 NM from the aerodrome on the 30
held originals). The OFP does print the route's ground distance (GND MILES), from aerodrome to aerodrome. The drawn route is a chain of great-circle legs between printed rows, and every printed leg
is at least as long as its great circle, so

    distance(departure aerodrome, first drawn row) <= GND MILES - drawn length

whenever the drawn route ends at the printed destination row. The first parsed row is accepted as the departure end
only when it holds a position and that shortfall is within the allowance below. Lost leading rows make the drawn route
too short (SQ297 starting at BLI: about 900 NM short) and are reported instead of drawn as the aerodrome.

The allowance absorbs the airway and procedure track excess over great circles: 9-74 NM (at most 0.82% of GND) on
the 30 originals. 25 NM plus 1% of GND leaves every original placed and bounds a placed departure label to within
that distance of the aerodrome.
"""
from __future__ import annotations

from math import acos, cos, radians, sin
from typing import Any

DEPARTURE_ALLOWANCE_FIXED_NM = 25.0
DEPARTURE_ALLOWANCE_FRACTION = 0.01
_EARTH_RADIUS_NM = 3440.065


def _position(row: Any) -> tuple[float, float] | None:
    """The same "held position" test every map builder applies, so point indexes line up."""
    if not isinstance(row, dict):
        return None
    latitude, longitude = row.get("latitude"), row.get("longitude")
    if latitude is None or longitude is None:
        return None
    return float(latitude), float(longitude)


def _great_circle_nm(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*first, *second))
    value = sin(lat1) * sin(lat2) + cos(lat1) * cos(lat2) * cos(lon2 - lon1)
    return _EARTH_RADIUS_NM * acos(max(-1.0, min(1.0, value)))


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or "").strip().upper()


def departure_allowance_nm(ground_distance_nm: float) -> float:
    return DEPARTURE_ALLOWANCE_FIXED_NM + DEPARTURE_ALLOWANCE_FRACTION * float(ground_distance_nm)


def _end(icao: str) -> dict[str, Any]:
    return {
        "icao": icao or None,
        "status": "not_placed",
        "row_index": None,
        "point_index": None,
        "fix": None,
        "reason": None,
        "offset_bound_nm": None,
    }


def resolve_route_endpoints(flight: dict[str, Any]) -> dict[str, Any]:
    """Decide which drawn rows carry the departure and destination aerodromes.

    ``point_index`` counts only rows that hold a position, in route order: the sequence every map draws.
    """
    rows = list(flight.get("route_waypoints") or [])
    held = [index for index, row in enumerate(rows) if _position(row) is not None]
    departure_code = str(flight.get("departure") or "").strip().upper()
    destination_code = str(flight.get("destination") or "").strip().upper()
    departure, destination = _end(departure_code), _end(destination_code)
    if held:
        departure["fix"] = _row_name(rows[held[0]]).lstrip("-")
        destination["fix"] = _row_name(rows[held[-1]]).lstrip("-")

    # Destination: the printed aerodrome row, last in the log, holding its position.
    if not destination_code:
        destination["reason"] = "the OFP destination is not held"
    elif not held:
        destination["reason"] = "no route row holds a printed position"
    elif _row_name(rows[-1]) != destination_code:
        last = _row_name(rows[-1]).lstrip("-") or "an unnamed row"
        destination["reason"] = f"the parsed route ends at {last}, not at the printed {destination_code} row"
    elif held[-1] != len(rows) - 1:
        destination["reason"] = f"the printed {destination_code} row holds no position"
    else:
        destination.update(status="placed", row_index=held[-1], point_index=len(held) - 1, offset_bound_nm=0.0)

    # Departure: the first parsed row, when the OFP's own ground distance bounds its distance from the aerodrome.
    ground = flight.get("ground_distance_nm")
    ground_nm = float(ground) if isinstance(ground, (int, float)) and not isinstance(ground, bool) and ground > 0 else None
    if not departure_code:
        departure["reason"] = "the OFP departure is not held"
    elif not held:
        departure["reason"] = "no route row holds a printed position"
    elif held[0] != 0:
        first = _row_name(rows[0]).lstrip("-") or "the first row"
        departure["reason"] = f"the first route row ({first}) holds no printed position"
    elif _row_name(rows[0]) == departure_code:
        # An OFP that prints the departure aerodrome as its own first row places it directly.
        departure.update(status="placed", row_index=0, point_index=0, offset_bound_nm=0.0)
    elif destination["status"] != "placed":
        departure["reason"] = "the route does not reach the printed destination row, so its length cannot be checked"
    elif ground_nm is None:
        departure["reason"] = "the OFP ground distance (GND MILES) is not held"
    else:
        positions = [_position(rows[index]) for index in held]
        drawn = sum(_great_circle_nm(a, b) for a, b in zip(positions, positions[1:]))
        shortfall = ground_nm - drawn
        allowance = departure_allowance_nm(ground_nm)
        if shortfall > allowance:
            departure["reason"] = (
                f"the held route is {shortfall:.0f} NM shorter than the OFP ground distance ({ground_nm:.0f} NM), "
                "so its first held row is not the start of the route"
            )
        elif shortfall < -allowance:
            departure["reason"] = (
                f"the held route is {-shortfall:.0f} NM longer than the OFP ground distance ({ground_nm:.0f} NM)"
            )
        else:
            departure.update(
                status="placed", row_index=0, point_index=0, offset_bound_nm=round(max(shortfall, 0.0), 1),
            )
    return {"departure": departure, "destination": destination}


def unplaced_endpoint_statements(endpoints: dict[str, Any]) -> list[str]:
    """Pilot-facing sentences for every aerodrome a route map does not draw."""
    statements = []
    for role, word in (("departure", "Departure"), ("destination", "Destination")):
        end = endpoints.get(role) or {}
        if end.get("status") == "placed":
            continue
        code = end.get("icao") or word.lower()
        fix = end.get("fix")
        drawn = f" The route is drawn {'from' if role == 'departure' else 'to'} {fix}." if fix else ""
        statements.append(
            f"{word} aerodrome {code} not drawn: {end.get('reason') or 'its position is not established'}.{drawn}"
        )
    return statements


__all__ = [
    "DEPARTURE_ALLOWANCE_FIXED_NM",
    "DEPARTURE_ALLOWANCE_FRACTION",
    "departure_allowance_nm",
    "resolve_route_endpoints",
    "unplaced_endpoint_statements",
]
