"""Responsible VAAC per route, from ICAO Doc 9766 Part 2.

The boss's sanctioned source (05 Aug 2026: "google VAAC centres … there is a
website catering to these"; 21 Aug: "there's a VAAC … in Manila? … normally
Darwin, Tokyo, Anchorage and Toulouse") is the ICAO Handbook on the
International Airways Volcano Watch, Doc 9766, whose Part 2 table assigns each
of the nine centres its area of responsibility — partly by coordinates, partly
by named FIRs.

This module encodes that table as deterministic point rules plus the named-FIR
assignments. Every rule carries the wording it was transcribed from so a
revision of the handbook can be re-checked line by line.

ITEM2-VOLCANIC (24 Oct 2026). The 21 Aug transcription left every Pacific
crossing with route points in the Kuril/Kamchatka band (N43-N60, E150-E165) and
the NE Pacific (N43-N60, W150-W128) assigned to no centre. The handbook does
assign them: Tokyo runs east "to Oakland Oceanic and Anchorage Oceanic and
Continental FIR boundaries"; Anchorage holds "Anchorage Oceanic, Anchorage
Continental, Oakland Oceanic North of N4300 E16500, N4812 W15000, N4812 W12800
Anchorage Arctic, and West to E15000, North of N6000"; Washington holds "Oakland
Oceanic South of N4300 E16500 to N4820 W15000 to N4820 W12800, United States
Continental FIRs". The table was incomplete because those rows are bounded by
FIRs, not coordinates, and the FIR edges were never encoded. They are now read
from the FAA's published boundary points (vaac_fir_boundaries.json). Two of the
old coordinate approximations were also wrong and are removed: Anchorage north
of N60 ran east to W128 (Canadian FIRs - Montreal's), and Tokyo held N10-N20
E130-E150 (Oakland Oceanic - Washington's).

A boundary the sources leave open is never decided here. Where the readings of
the source differ - each FIR edge as a straight line or as a great circle; the
Oakland Oceanic split at N4812 (Anchorage row) or N4820 (Washington row); a
point within one arc-minute of a boundary; two rows that both claim an area
(Darwin and Oakland Oceanic south of N1000) - every centre any reading names is
responsible, so each must be reached. A point no row assigns stays unsettled.

Points can also be placed by the OFP itself: each "-XXXX" route point marks the
FIR the flight enters, so the points up to the next boundary lie in that FIR. A
FIR the table assigns unconditionally adds its centre to those points.
"""

from __future__ import annotations

import json
from functools import lru_cache
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, Point, Polygon

VAAC_AREA_SOURCE = {
    "document": "ICAO Doc 9766 — Handbook on the International Airways Volcano Watch (IAVW), Part 2",
    "url": "https://www.icao.int/sites/default/files/METP/Documents/IAVW%20docs/Doc9766_IAVW-Handbook_Operational-Procedures.pdf",
    # The 16 Sep 2024 version (…/METP/Documents/Handbook-on-the-IAVW.Doc-9766.pdf, transcribed 2026-08-21) carries
    # the same area wording; the cited copy is the newer one (change record 31.3.26).
    "transcribed": "2026-10-24",
    "fir_boundaries": "FAA NASR ARB boundary points, cycle 2026-10-01 (vaac_fir_boundaries.json)",
}

_BOUNDARY_FILE = Path(__file__).with_name("vaac_fir_boundaries.json")

# One arc-minute: the resolution an OFP prints a route point at. A point that close to a boundary is on it.
BOUNDARY_TOLERANCE_DEG = 1.0 / 60.0

# Named-FIR assignments printed in the Part 2 table. Only FIRs the table
# assigns unconditionally are listed; conditionally split FIRs (for example
# Chennai west of E08200, Nadi north of the Equator, Oakland Oceanic north or
# south of its split line) stay out so a name match can never overstate
# coverage.
FIR_CENTRE_ASSIGNMENTS = {
    # "the Colombo, Melbourne and Brisbane FIRs" — Darwin row.
    "VCBI": "DARWIN",
    "YMMM": "DARWIN",
    "YBBB": "DARWIN",
    # London row: "Bodo Oceanic, Finland, Kobenhavn, London, Norway,
    # Reykjavik, Scottish, Shannon, Shanwick Oceanic and Sweden".
    "ENOB": "LONDON",
    "EFIN": "LONDON",
    "EKDK": "LONDON",
    "EGTT": "LONDON",
    "ENOR": "LONDON",
    "BIRD": "LONDON",
    "EGPX": "LONDON",
    "EISN": "LONDON",
    "EGGX": "LONDON",
    "ESAA": "LONDON",
    # Montreal row: "Sondrestrom, Gander Oceanic, Canadian Continental FIRs".
    "BGGL": "MONTREAL",
    "CZQX": "MONTREAL",
    "CZQM": "MONTREAL",
    "CZUL": "MONTREAL",
    "CZYZ": "MONTREAL",
    "CZWG": "MONTREAL",
    "CZEG": "MONTREAL",
    "CZVR": "MONTREAL",
    # Toulouse row: "(plus Mumbai … and Male FIRs)".
    "VABF": "TOULOUSE",
    "VRMF": "TOULOUSE",
    # Anchorage row: "Anchorage Oceanic, Anchorage Continental … Anchorage
    # Arctic" (the FAA identifies Anchorage Oceanic PAZN and the continental
    # FIR PAZA; LIDO and the AWC feed print PAZA for the oceanic FIR).
    "PAZA": "ANCHORAGE",
    "PAZN": "ANCHORAGE",
    # Washington row: "New York Oceanic … United States Continental FIRs" -
    # the twenty contiguous-US ARTCC FIRs (New York Oceanic is KZWY).
    "KZWY": "WASHINGTON",
    "KZAB": "WASHINGTON", "KZAU": "WASHINGTON", "KZBW": "WASHINGTON", "KZDC": "WASHINGTON",
    "KZDV": "WASHINGTON", "KZFW": "WASHINGTON", "KZHU": "WASHINGTON", "KZID": "WASHINGTON",
    "KZJX": "WASHINGTON", "KZKC": "WASHINGTON", "KZLA": "WASHINGTON", "KZLC": "WASHINGTON",
    "KZMA": "WASHINGTON", "KZME": "WASHINGTON", "KZMP": "WASHINGTON", "KZNY": "WASHINGTON",
    "KZOA": "WASHINGTON", "KZOB": "WASHINGTON", "KZSE": "WASHINGTON", "KZTL": "WASHINGTON",
    # Wellington row: its own FIRs.
    "NZZO": "WELLINGTON",
    "NZZC": "WELLINGTON",
}

# The Oakland Oceanic split, as each row prints it: Anchorage holds the part
# "North of N4300 E16500, N4812 W15000, N4812 W12800"; Washington the part
# "South of N4300 E16500 to N4820 W15000 to N4820 W12800".
_OAKLAND_SPLIT_READINGS = (
    ((43.0, 165.0), (48.2, -150.0), (48.2, -128.0)),
    ((43.0, 165.0), (48.0 + 20.0 / 60.0, -150.0), (48.0 + 20.0 / 60.0, -128.0)),
)


def _east(longitude: float) -> float:
    """Longitude in the 0..360 frame the North Pacific boundaries are drawn in."""
    return float(longitude) % 360.0


def _great_circle(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    """(lat, lon) points along the great circle from ``start`` to ``end``, every ~0.25 degree."""
    lat1, lon1, lat2, lon2 = map(radians, (start[0], start[1], end[0], end[1]))
    angle = 2 * asin(sqrt(sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2))
    if angle < 1e-9:
        return [start, end]
    steps = max(1, int(degrees(angle) / 0.25))
    points = []
    for step in range(steps + 1):
        fraction = step / steps
        a = sin((1 - fraction) * angle) / sin(angle)
        b = sin(fraction * angle) / sin(angle)
        x = a * cos(lat1) * cos(lon1) + b * cos(lat2) * cos(lon2)
        y = a * cos(lat1) * sin(lon1) + b * cos(lat2) * sin(lon2)
        z = a * sin(lat1) + b * sin(lat2)
        points.append((degrees(atan2(z, sqrt(x * x + y * y))), degrees(atan2(y, x))))
    return points


def _plane(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(lon, lat) in the 0..360 frame, continuous across the date line."""
    out: list[tuple[float, float]] = []
    for lat, lon in points:
        x = _east(lon)
        if out:
            while x - out[-1][0] > 180:
                x -= 360
            while x - out[-1][0] < -180:
                x += 360
        out.append((x, lat))
    return out


def _readings(points: list[tuple[float, float]], closed: bool) -> list[list[tuple[float, float]]]:
    """The two readings of a boundary: straight lines between its points, and great circles."""
    straight = _plane(points + ([points[0]] if closed else []))
    pairs = list(zip(points, points[1:] + ([points[0]] if closed else [])))
    curved: list[tuple[float, float]] = []
    for start, end in pairs:
        arc = _great_circle(start, end)
        curved.extend(arc if not curved else arc[1:])
    return [straight, _plane(curved)]


@lru_cache(maxsize=1)
def _firs() -> dict[str, list[Polygon]]:
    data = json.loads(_BOUNDARY_FILE.read_text())
    firs: dict[str, list[Polygon]] = {}
    for name, fir in data["firs"].items():
        points = [(float(lat), float(lon)) for lat, lon in fir["points"]]
        firs[name] = [Polygon(ring).buffer(0) for ring in _readings(points, closed=True)]
    return firs


@lru_cache(maxsize=1)
def _oakland_split_lines() -> list[LineString]:
    return [LineString(ring) for reading in _OAKLAND_SPLIT_READINGS for ring in _readings(list(reading), closed=False)]


def _candidates(polygons: list[Polygon], lat: float, lon: float) -> tuple[bool, bool]:
    """(inside in some reading, outside in some reading) - both when the readings differ or the point is on the edge."""
    inside = outside = False
    for polygon in polygons:
        for shift in (0.0, 360.0, -360.0):
            point = Point(_east(lon) + shift, lat)
            if polygon.boundary.distance(point) <= BOUNDARY_TOLERANCE_DEG:
                return True, True
        point = Point(_east(lon), lat)
        held = any(polygon.contains(Point(point.x + shift, lat)) for shift in (0.0, 360.0, -360.0))
        inside = inside or held
        outside = outside or not held
    return inside, outside


def _oakland_split_sides(lat: float, lon: float) -> set[str]:
    """Which side(s) of the Oakland Oceanic split line a point lies on, over every reading of the line."""
    sides: set[str] = set()
    x = _east(lon)
    for line in _oakland_split_lines():
        start, end = line.coords[0][0], line.coords[-1][0]
        if x < start:
            # West of N4300 E16500 the line does not run. Oakland Oceanic south of N4300 there is south of it on any
            # reading; the sliver north of N4300 (to N4542 E16255, where Fukuoka and Anchorage Oceanic meet it) is
            # assigned by neither row's wording, so both rows hold it.
            sides |= {"south"} if lat < 43.0 - BOUNDARY_TOLERANCE_DEG else {"north", "south"}
            continue
        if x > end:
            # East of W12800 Oakland Oceanic lies south of N4810, below either printed latitude of the line.
            sides |= {"south"} if lat < 48.2 - BOUNDARY_TOLERANCE_DEG else {"north", "south"}
            continue
        point = Point(x, lat)
        if line.distance(point) <= BOUNDARY_TOLERANCE_DEG:
            return {"north", "south"}
        # The line's latitude at this longitude (it is single-valued in longitude).
        coords = list(line.coords)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            if min(x1, x2) <= x <= max(x1, x2) and x1 != x2:
                y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
                sides.add("north" if lat > y else "south")
                break
    return sides


def centres_for_point(latitude: float, longitude: float) -> set[str]:
    """Every centre some reading of Doc 9766 Part 2 makes responsible for the point; empty when no row assigns it."""
    lat = float(latitude)
    lon = float(longitude)
    if lon > 180.0:
        lon -= 360.0
    east = _east(lon)
    centres: set[str] = set()
    firs = _firs()
    in_oakland, out_oakland = _candidates(firs["OAKLAND_OCEANIC"], lat, lon)
    in_anchorage = any(_candidates(firs[name], lat, lon)[0]
                       for name in ("ANCHORAGE_OCEANIC", "ANCHORAGE_CONTINENTAL", "ANCHORAGE_ARCTIC"))
    # Outside every US Pacific FIR in some reading: the region Tokyo holds "to" their boundaries.
    out_us_pacific = all(
        _candidates(firs[name], lat, lon)[1]
        for name in ("OAKLAND_OCEANIC", "ANCHORAGE_OCEANIC", "ANCHORAGE_CONTINENTAL", "ANCHORAGE_ARCTIC")
    )

    # Darwin: "Southward from N2000 and from E08200 to E10000, and Southward
    # from N1000 and from E10000 to E16000" (the E090-E100 N10-N20 box is the
    # exception carved out of Tokyo's row).
    if lat <= 20.0 and 82.0 <= lon < 100.0:
        centres.add("DARWIN")
    if lat <= 10.0 and 100.0 <= lon <= 160.0:
        centres.add("DARWIN")

    # Tokyo: "N9000 to N6000 and from E09000 to E15000 and N6000 to N1000 and
    # from E09000 to Oakland Oceanic and Anchorage Oceanic and Continental FIR
    # boundaries except the area within N2000 E09000 to N2000 E10000 to N1000
    # E10000 to N1000 E09000".
    if 60.0 < lat <= 90.0 and 90.0 <= lon <= 150.0:
        centres.add("TOKYO")
    if 10.0 < lat <= 60.0 and 90.0 <= east <= 180.0 and out_us_pacific and not (lat <= 20.0 and east < 100.0):
        centres.add("TOKYO")

    # Anchorage: "Anchorage Oceanic, Anchorage Continental, Oakland Oceanic
    # North of N4300 E16500, N4812 W15000, N4812 W12800 Anchorage Arctic, and
    # West to E15000, North of N6000". West of its FIRs, north of N6000, the
    # area runs to E15000; its FIRs end at W14100 (the FAA's common boundary
    # with Edmonton FIR) - Canadian FIRs east of that are Montreal's.
    if in_anchorage:
        centres.add("ANCHORAGE")
    if lat > 60.0 - BOUNDARY_TOLERANCE_DEG and 150.0 <= east <= 219.0:
        centres.add("ANCHORAGE")
    split = _oakland_split_sides(lat, lon) if in_oakland else set()
    if "north" in split:
        centres.add("ANCHORAGE")

    # Washington: "Oakland Oceanic South of N4300 E16500 to N4820 W15000 to
    # N4820 W12800, United States Continental FIRs …". The continental FIRs
    # meet Oakland Oceanic along its eastern edge (the FAA's "COMMON OAKLAND
    # CTA/FIR-ZSE", "-ZSE-ZOA", "-ZOA-ZLA" points from N4810 W12755 to N3430
    # W12315); their offshore part west of W12500 is held here, the remainder
    # by the coarse rule below.
    if "south" in split:
        centres.add("WASHINGTON")
    if 34.5 <= lat <= 48.0 + 10.0 / 60.0 and -128.0 <= lon <= -120.0:
        centres.add("WASHINGTON")
    if 24.0 <= lat <= 49.0 and -125.0 <= lon <= -66.0:
        centres.add("WASHINGTON")
    if -10.0 <= lat < 24.0 and -140.0 < lon <= -30.0:
        centres.add("WASHINGTON")

    # Wellington: "Southward from the Equator and from E16000 to W14000 …
    # and Southward from S1000 and from W14000 to W09000" (Melbourne and
    # Brisbane FIRs stay Darwin's via the named-FIR table).
    if lat <= 0.0 and (160.0 < lon <= 180.0 or -180.0 <= lon <= -140.0):
        centres.add("WELLINGTON")
    if lat <= -10.0 and -140.0 < lon <= -90.0:
        centres.add("WELLINGTON")

    # Buenos Aires: "South of S1000 between W01000 and W09000".
    if lat <= -10.0 and -90.0 < lon <= -10.0:
        centres.add("BUENOS AIRES")

    # Toulouse: "AFI Region down to the South Pole … MID Region, and ASIA
    # Region West of E09000 North of N2000" and the EUR share south of the
    # London band. The Atlantic/EUR seams with London, Washington and Santa
    # Maria are not settled geometrically here.
    if lat <= 20.0 and -10.0 < lon < 82.0:
        centres.add("TOULOUSE")
    if 20.0 < lat <= 55.0 and -10.0 <= lon < 90.0:
        centres.add("TOULOUSE")

    return centres


def _centre_for_point(latitude: float, longitude: float) -> str | None:
    """One centre when the point is settled to exactly one, else None (kept for older callers)."""
    centres = centres_for_point(latitude, longitude)
    return next(iter(centres)) if len(centres) == 1 else None


def waypoint_firs(waypoints: Iterable[dict[str, Any]]) -> list[str | None]:
    """The FIR each route point lies in, by the OFP's own boundary points ("-XXXX" enters FIR XXXX); None before the
    first boundary. A boundary point lies on the edge of both FIRs; it is given the one it enters."""
    current: str | None = None
    firs: list[str | None] = []
    for waypoint in waypoints or []:
        boundary = str(waypoint.get("fir_boundary") or "").strip().upper()
        if boundary:
            current = boundary
        firs.append(current)
    return firs


def responsible_vaac_centres(
    points: Iterable[tuple[float, float]],
    route_firs: Iterable[str] | None = None,
    point_firs: Iterable[str | None] | None = None,
) -> dict[str, Any]:
    """Resolve the responsible centres for a route.

    `points` are (latitude, longitude) route positions; `route_firs` are the
    route's FIR identifiers for the named-FIR rows of the table; `point_firs`
    (parallel to `points`) is the FIR each point lies in by the OFP's own
    boundary sequence. The result never guesses: a point no row assigns is
    counted and flagged; a point two readings assign differently is held by
    every centre they name.
    """
    centres: set[str] = set()
    unresolved = 0
    shared = 0
    point_list = list(points or [])
    fir_list = list(point_firs or [])
    for index, point in enumerate(point_list):
        try:
            latitude, longitude = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            point_centres: set[str] = set()
        else:
            point_centres = centres_for_point(latitude, longitude)
        fir = fir_list[index] if index < len(fir_list) else None
        named = FIR_CENTRE_ASSIGNMENTS.get(str(fir or "").strip().upper())
        if named:
            point_centres = point_centres | {named}
        if not point_centres:
            unresolved += 1
        elif len(point_centres) > 1:
            shared += 1
        centres |= point_centres
    for fir in route_firs or []:
        assigned = FIR_CENTRE_ASSIGNMENTS.get(str(fir or "").strip().upper())
        if assigned:
            centres.add(assigned)
    return {
        "centres": sorted(centres),
        "unresolved_points": unresolved,
        "shared_boundary_points": shared,
        "review_required": unresolved > 0,
        "source": VAAC_AREA_SOURCE,
    }
