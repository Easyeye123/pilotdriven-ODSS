"""Where a route map draws the flight's departure and destination aerodromes.

Item 11 (David, 3 Oct 2026: "It ended up instead of Singapore now is in Bali") and QA496-03 (Codex, 13 Oct 2026).
Route maps used to give the departure ICAO to whichever coordinate-bearing route row came first and the destination
ICAO to whichever came last. Release 496 kept that, gated by a route-length allowance (GND MILES minus drawn length
within 25 NM + 1% of GND). An allowance bounds a distance; it does not make a route fix an aerodrome: with leading
rows removed, JUDDS (67 NM out) was still drawn as KJFK.

The rule now: an aerodrome is drawn only at a position from a source that proves its identity by ICAO code, tried in
order and recorded per marker as provenance:
(a) the governed aerodrome table (aerodrome_reference_points.json, built by scripts/build_aerodrome_reference_points.py
    from the operator's LIDO aerodrome records, each value pinned to its source);
(b) the OpenStreetMap aerodrome the app published for this analysis (flight["surface_overlays"]), whose ``icao`` is
    the code exactly: the app's lookup selects the aerodrome by its exact icao tag (osm-airport-surface.mjs,
    chooseAerodrome) and publishes that object's outline; its bounding-box centre is the aerodrome centre the same
    lookup reports. ODSS makes no network call for it.
(c) otherwise the aerodrome is not drawn, and every map says so with the reason.
A position is never taken from a route row of the flight being drawn, whatever its position, name or distance, and
identity is never inferred from distance. Route rows are drawn under their own printed names.
"""
from __future__ import annotations

from functools import lru_cache
import json
from math import isfinite
from pathlib import Path
from typing import Any

AERODROME_TABLE = Path(__file__).with_name("aerodrome_reference_points.json")
DRAWN = "reference_point"
NOT_DRAWN = "not_placed"


@lru_cache(maxsize=1)
def aerodrome_reference_points() -> dict[str, dict[str, Any]]:
    """The governed table, validated: every entry needs a finite position and at least one pinned source."""
    table = json.loads(AERODROME_TABLE.read_text(encoding="utf-8"))
    aerodromes: dict[str, dict[str, Any]] = {}
    for code, entry in (table.get("aerodromes") or {}).items():
        latitude, longitude = entry.get("latitude"), entry.get("longitude")
        sources = entry.get("sources") or []
        if not (
            isinstance(code, str) and len(code) == 4 and code.isalpha() and code.isupper()
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                    for value in (latitude, longitude))
            and abs(latitude) <= 90 and abs(longitude) <= 180
            and sources and all(source.get("sha256") and source.get("printed") for source in sources)
        ):
            raise ValueError(f"Governed aerodrome table entry {code!r} is incomplete")
        aerodromes[code] = {"latitude": float(latitude), "longitude": float(longitude), "sources": sources}
    return aerodromes


OSM_METHOD = (
    "bounding-box centre of the OpenStreetMap aerodrome outline the app published for this analysis, "
    "matched on its exact ICAO tag"
)


def _outline_centre(boundary: Any) -> tuple[float, float] | None:
    """Bounding-box centre of an outline's outer rings (antimeridian-safe), or None for an unusable outline."""
    rings = (boundary or {}).get("outer") if isinstance(boundary, dict) else None
    points: list[tuple[float, float]] = []
    for ring in rings or []:
        for point in ring if isinstance(ring, list) else []:
            if not (isinstance(point, (list, tuple)) and len(point) >= 2
                    and all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                            for value in point[:2])):
                return None
            points.append((float(point[0]), float(point[1])))
    if not points:
        return None
    reference = points[0][0]
    longitudes = []
    for longitude, _latitude in points:
        while longitude - reference > 180:
            longitude -= 360
        while longitude - reference < -180:
            longitude += 360
        longitudes.append(longitude)
    latitudes = [latitude for _longitude, latitude in points]
    latitude = (min(latitudes) + max(latitudes)) / 2
    longitude = (min(longitudes) + max(longitudes)) / 2
    while longitude > 180:
        longitude -= 360
    while longitude < -180:
        longitude += 360
    if abs(latitude) > 90:
        return None
    return latitude, longitude


def _published_osm_aerodrome(flight: dict[str, Any], code: str) -> dict[str, Any] | None:
    """The OpenStreetMap aerodrome published for this analysis under exactly ``code``, with its provenance."""
    for overlay in flight.get("surface_overlays") or []:
        if not isinstance(overlay, dict) or overlay.get("icao") != code:
            continue
        centre = _outline_centre(overlay.get("aerodromeBoundary"))
        if centre is None:
            continue
        source = overlay.get("source") if isinstance(overlay.get("source"), dict) else {}
        return {
            "latitude": centre[0],
            "longitude": centre[1],
            "reference": {
                "kind": "osm_aerodrome_published_outline",
                "icao": code,
                "name": overlay.get("name"),
                "method": OSM_METHOD,
                "provider": source.get("provider"),
                "fetchedAt": source.get("fetchedAt"),
                "sourceUpdatedAt": source.get("sourceUpdatedAt"),
                "attribution": source.get("attribution"),
                "licenceUrl": source.get("licenceUrl"),
            },
        }
    return None


def _row_name(row: Any) -> str:
    return str((row or {}).get("name") or "").strip().upper().lstrip("-") if isinstance(row, dict) else ""


def resolve_route_endpoints(flight: dict[str, Any]) -> dict[str, Any]:
    """Each aerodrome's drawn position, or why it is not drawn.

    ``status`` is ``"reference_point"`` when an identity-proven source places it (``reference.kind`` says which:
    ``lido_ofp_destination_aerodrome_record`` or ``osm_aerodrome_published_outline``), otherwise ``"not_placed"``.
    ``fix`` names the first (departure) or last (destination) route row that holds a position, so a statement can
    say where the drawn route starts or ends; it never carries the aerodrome's identity. No route row is ever an
    aerodrome: ``row_index`` and ``point_index`` are always None.
    """
    rows = [row for row in (flight.get("route_waypoints") or []) if isinstance(row, dict)]
    held = [row for row in rows if row.get("latitude") is not None and row.get("longitude") is not None]
    table = aerodrome_reference_points()
    result: dict[str, Any] = {}
    for role, end_row in (("departure", held[0] if held else None), ("destination", held[-1] if held else None)):
        code = str(flight.get(role) or "").strip().upper()
        entry = table.get(code)
        end: dict[str, Any] = {
            "icao": code or None,
            "status": NOT_DRAWN,
            "latitude": None,
            "longitude": None,
            "reference": None,
            "row_index": None,
            "point_index": None,
            "fix": _row_name(end_row) or None,
            "reason": None,
        }
        published = _published_osm_aerodrome(flight, code) if code and entry is None else None
        if not code:
            end["reason"] = f"the OFP {role} is not held"
        elif entry is None and published is not None:
            end.update(
                status=DRAWN,
                latitude=published["latitude"],
                longitude=published["longitude"],
                reference=published["reference"],
            )
        elif entry is None:
            end["reason"] = (
                f"no governed aerodrome reference point is held for {code}, and no OpenStreetMap aerodrome matched "
                "on its ICAO tag was published for this analysis"
            )
        else:
            source = entry["sources"][0]
            end.update(
                status=DRAWN,
                latitude=entry["latitude"],
                longitude=entry["longitude"],
                reference={
                    "kind": source.get("kind"),
                    "file": source.get("file"),
                    "page": source.get("page"),
                    "printed": source.get("printed"),
                    "sha256": source.get("sha256"),
                },
            )
        result[role] = end
    return result


def drawn_aerodromes(endpoints: dict[str, Any]) -> list[dict[str, Any]]:
    """The aerodromes a map draws, once each: a flight that returns to its departure draws one marker."""
    drawn: list[dict[str, Any]] = []
    for role in ("departure", "destination"):
        end = endpoints.get(role) or {}
        if end.get("status") != DRAWN:
            continue
        same = next((item for item in drawn if item["icao"] == end["icao"]), None)
        if same:
            same["roles"].append(role)
            continue
        drawn.append({
            "icao": end["icao"],
            "role": role,
            "roles": [role],
            "latitude": end["latitude"],
            "longitude": end["longitude"],
            "display_name": end["icao"],
            "reference": end["reference"],
        })
    return drawn


def unplaced_endpoint_statements(endpoints: dict[str, Any]) -> list[str]:
    """Pilot-facing sentences for every aerodrome a route map does not draw."""
    statements = []
    for role, word in (("departure", "Departure"), ("destination", "Destination")):
        end = endpoints.get(role) or {}
        if end.get("status") == DRAWN:
            continue
        code = end.get("icao") or word.lower()
        fix = end.get("fix")
        drawn = f" The route is drawn {'from' if role == 'departure' else 'to'} {fix}." if fix else ""
        statements.append(
            f"{word} aerodrome {code} not drawn: {end.get('reason') or 'its position is not established'}.{drawn}"
        )
    return statements


__all__ = [
    "AERODROME_TABLE",
    "DRAWN",
    "NOT_DRAWN",
    "aerodrome_reference_points",
    "drawn_aerodromes",
    "resolve_route_endpoints",
    "unplaced_endpoint_statements",
]
