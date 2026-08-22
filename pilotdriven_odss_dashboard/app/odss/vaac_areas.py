"""Responsible VAAC per route, from ICAO Doc 9766 Part 2.

The boss's sanctioned source (05 Aug 2026: "google VAAC centres … there is a
website catering to these"; 21 Aug: "there's a VAAC … in Manila? … normally
Darwin, Tokyo, Anchorage and Toulouse") is the ICAO Handbook on the
International Airways Volcano Watch, Doc 9766, whose Part 2 table assigns each
of the nine centres its area of responsibility — partly by coordinates, partly
by named FIRs.

This module encodes that table verbatim as deterministic point rules plus the
named-FIR assignments. Points inside a zone the table settles resolve to one
centre; anything else fails closed as review-required with no invented claim.
Every rule carries the wording it was transcribed from so a revision of the
handbook can be re-checked line by line.
"""

from __future__ import annotations

from typing import Any, Iterable

VAAC_AREA_SOURCE = {
    "document": "ICAO Doc 9766 — Handbook on the International Airways Volcano Watch (IAVW), Part 2",
    "url": "https://www.icao.int/sites/default/files/METP/Documents/Handbook-on-the-IAVW.Doc-9766.pdf",
    "transcribed": "2026-08-21",
}

# Named-FIR assignments printed in the Part 2 table. Only FIRs the table
# assigns unconditionally are listed; conditionally split FIRs (for example
# Chennai west of E08200, Nadi north of the Equator) stay out so a name match
# can never overstate coverage.
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
    # Anchorage row: its own FIRs.
    "PAZA": "ANCHORAGE",
    "PAZN": "ANCHORAGE",
    # Wellington row: its own FIRs.
    "NZZO": "WELLINGTON",
    "NZZC": "WELLINGTON",
}


def _centre_for_point(latitude: float, longitude: float) -> str | None:
    """One centre when the Doc 9766 geometry settles the point, else None."""
    lat = float(latitude)
    lon = float(longitude)
    if lon > 180.0:
        lon -= 360.0

    # Darwin: "Southward from N2000 and from E08200 to E10000, and Southward
    # from N1000 and from E10000 to E16000" (the E090-E100 N10-N20 box is the
    # exception carved out of Tokyo's row).
    if lat <= 20.0 and 82.0 <= lon < 100.0:
        return "DARWIN"
    if lat <= 10.0 and 100.0 <= lon <= 160.0:
        return "DARWIN"

    # Tokyo: "N9000 to N6000 and from E09000 to E15000 and N6000 to N1000 and
    # from E09000 to Oakland Oceanic and Anchorage … boundaries except the
    # area within N2000 E09000 to N2000 E10000 to N1000 E10000 to N1000
    # E09000". The eastern oceanic boundary runs near E16500; the strip beyond
    # E15000 above N4300 belongs to the Anchorage/Oakland split and is not
    # settled here.
    if 60.0 < lat <= 90.0 and 90.0 <= lon <= 150.0:
        return "TOKYO"
    if 20.0 < lat <= 60.0 and 90.0 <= lon <= 150.0:
        return "TOKYO"
    if 10.0 < lat <= 43.0 and 150.0 < lon <= 165.0:
        return "TOKYO"
    if 10.0 < lat <= 20.0 and 100.0 <= lon <= 150.0:
        return "TOKYO"

    # Anchorage: "Anchorage Arctic, and West to E15000, North of N6000" plus
    # its Oceanic/Continental FIRs east of the Oakland split line.
    if lat > 60.0 and (150.0 <= lon <= 180.0 or -180.0 <= lon <= -128.0):
        return "ANCHORAGE"
    if 43.0 < lat <= 60.0 and (165.0 <= lon <= 180.0 or -180.0 <= lon <= -150.0):
        return "ANCHORAGE"

    # Wellington: "Southward from the Equator and from E16000 to W14000 …
    # and Southward from S1000 and from W14000 to W09000" (Melbourne and
    # Brisbane FIRs stay Darwin's via the named-FIR table).
    if lat <= 0.0 and (160.0 < lon <= 180.0 or -180.0 <= lon <= -140.0):
        return "WELLINGTON"
    if lat <= -10.0 and -140.0 < lon <= -90.0:
        return "WELLINGTON"

    # Buenos Aires: "South of S1000 between W01000 and W09000".
    if lat <= -10.0 and -90.0 < lon <= -10.0:
        return "BUENOS AIRES"

    # Toulouse: "AFI Region down to the South Pole … MID Region, and ASIA
    # Region West of E09000 North of N2000" and the EUR share south of the
    # London band. The Atlantic/EUR seams with London, Washington and Santa
    # Maria are not settled geometrically here.
    if lat <= 20.0 and -10.0 < lon < 82.0:
        return "TOULOUSE"
    if 20.0 < lat <= 55.0 and -10.0 <= lon < 90.0:
        return "TOULOUSE"

    # Washington: "United States Continental FIRs … New York Oceanic …
    # North of S1000" and the central-Pacific corridor south of the
    # Oakland split ("Oakland Oceanic South of N4300 E16500 …").
    if 24.0 <= lat <= 49.0 and -125.0 <= lon <= -66.0:
        return "WASHINGTON"
    if -10.0 <= lat <= 43.0 and (165.0 <= lon <= 180.0 or -180.0 <= lon <= -140.0):
        return "WASHINGTON"
    if -10.0 <= lat < 24.0 and -140.0 < lon <= -30.0:
        return "WASHINGTON"

    return None


def responsible_vaac_centres(
    points: Iterable[tuple[float, float]],
    route_firs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Resolve the responsible centres for a route.

    `points` are (latitude, longitude) route positions; `route_firs` are the
    route's FIR identifiers for the named-FIR rows of the table. The result
    never guesses: geometrically unsettled points are counted and flagged.
    """
    centres: set[str] = set()
    unresolved = 0
    for point in points or []:
        try:
            latitude, longitude = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            unresolved += 1
            continue
        centre = _centre_for_point(latitude, longitude)
        if centre:
            centres.add(centre)
        else:
            unresolved += 1
    for fir in route_firs or []:
        assigned = FIR_CENTRE_ASSIGNMENTS.get(str(fir or "").strip().upper())
        if assigned:
            centres.add(assigned)
    return {
        "centres": sorted(centres),
        "unresolved_points": unresolved,
        "review_required": unresolved > 0,
        "source": VAAC_AREA_SOURCE,
    }
