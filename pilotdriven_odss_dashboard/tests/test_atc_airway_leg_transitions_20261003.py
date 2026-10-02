"""ATC-AIRWAY-LEG-TRANSITIONS (3 Oct 2026, Codex independent QA of release 450, ITEM1).

Release 450 still lost an open crossing leg in one boundary combination: owner FIR A entered, a known non-listed airway,
an exit boundary to B, a consecutive boundary returning to A, then the end of the route. The return to A cleared the
pending exit, so the airway-only list read as not met and the call as not applicable (support/release450/
consecutive-reentry-EOF-control, receipt SHA bd84cc5f...). The invariant repaired in both languages (mirrored by
tests/atc-airway-leg-transitions-20261003.test.mjs): a leg is the stretch between two waypoints; it touches the owner FIR
when it starts inside it or crosses one of its boundary rows; every touching leg's airway (the closing waypoint's
airway_in) must be held, and a leg still open at the end of the route is unknown. Boundary rows move location only; only
a waypoint closes a leg. The bounded test checks every route of up to five rows after an outside start against a
structurally separate segment reference (closed legs plus a trailing open leg, classified per leg), and hand-written
controls fix the expected result of the boundary cases. All inputs are labelled SYNTHETIC.
"""
from __future__ import annotations

import itertools

import pytest

from app.odss.enroute_contact import compose_enroute_contact

CALL = "ALL ACFT VIA RTE B346, R474 AND G473 SHALL CTC SYNTHETIC ACC ON 126.500MHZ."
LISTED = {"B346", "R474", "G473"}
TOKENS = {"-A": ("-ZZAA", None), "-B": ("-ZZBB", None), "K": ("SYNK", "A334"), "U": ("SYNU", None), "M": ("SYNM", "G473"), "D": ("SYND", "DCT")}


def flight(sequence):
    """LABELLED SYNTHETIC: an outside start waypoint, then the token sequence."""
    rows = [("SYN0", "Q1"), *(TOKENS[token] for token in sequence)]
    waypoints = [{"name": f"{name}{index}" if not name.startswith("-") else name, "actm_minutes": 5 + 5 * index, "source_page": 1,
                  "airway_in": airway, "fir_boundary": name[1:] if name.startswith("-") else None} for index, (name, airway) in enumerate(rows)]
    return {"departure": "WSSS", "destination": "VHHH", "scheduled_departure_utc": "2026-06-01T01:00:00Z", "route_waypoints": waypoints,
            "notam_procedure_records": [{"notam_id": "SYNTHETIC/26", "validity": "01-JAN-26 0000 - 31-DEC-26 2359",
                                         "heading": "ZZAA SYNTHETIC FIR", "heading_kind": "fir", "fir": "ZZAA", "source_page": 2, "text": CALL}]}


def legs(sequence):
    """Split a route into legs: each closed leg is (start location, boundary FIRs crossed, closing airway); the trailing
    stretch after the last waypoint is an open leg with no airway. The route starts outside every FIR."""
    closed, crossed, start, location = [], [], None, None
    for token in sequence:
        if token.startswith("-"):
            crossed.append(TOKENS[token][0][1:])
            location = crossed[-1]
        else:
            closed.append((start, tuple(crossed), TOKENS[token][1]))
            crossed, start = [], location
    return closed, (start, tuple(crossed))


def reference(sequence):
    """Segment reference, structurally separate from the implementation: classify each leg that touches the owner FIR."""
    closed, (open_start, open_crossed) = legs(sequence)
    touches = lambda start, crossed: start == "ZZAA" or "ZZAA" in crossed
    touching = [airway for start, crossed, airway in closed if touches(start, crossed)]
    entered = any("ZZAA" in crossed for _, crossed, _ in closed) or "ZZAA" in open_crossed
    # The trailing leg exists only when boundary rows follow the last waypoint; if it touches the owner it is unknown.
    missing = any(airway is None for airway in touching) or (bool(open_crossed) and touches(open_start, open_crossed))
    if any(airway in LISTED for airway in touching):
        return "met"
    return "not_met" if entered and not missing else None


# Hand-written expectations (fixed controls, independent of both the reference and the implementation).
EXPLICIT = [
    (("-A", "K", "-B", "-A"), None),            # Codex release 450: consecutive re-entry, then end of route
    (("-A", "K", "-B", "-A", "M"), "met"),      # the same re-entry closed by a listed airway
    (("-A", "K", "-B", "-A", "K"), "not_met"),  # closed by a known non-listed airway
    (("-A", "K", "-B", "-A", "U"), None),       # closed by an unknown airway
    (("-A", "K", "-B", "-A", "D"), "not_met"),  # closed by DCT
    (("-A",), None),                            # route ends just after entering the owner FIR
    (("-A", "K"), "not_met"),                   # route ends inside the owner FIR, leg known
    (("-A", "K", "-B"), None),                  # exit boundary is the last row
    (("-A", "K", "-B", "U"), None),             # exit leg unknown
    (("-A", "K", "-B", "K"), "not_met"),        # exit leg known, not listed
    (("-A", "K", "-B", "M"), "met"),            # exit leg listed
    (("-A", "K", "-B", "-B", "U"), None),       # consecutive boundaries, then unknown
    (("-B", "K", "-B"), None),                  # owner FIR never entered
    (("K", "-B", "M"), None),                   # a listed airway outside the owner FIR does not count
    (("-A", "U", "-B", "M"), "met"),            # a known listed airway decides even with another leg unknown
]


SEQUENCES = [s for n in range(1, 6) for s in itertools.product(TOKENS, repeat=n)]


def route_result(sequence):
    procedure = compose_enroute_contact(flight(sequence))["procedures"][0]
    route = [c for c in procedure["conditions"] if c["kind"] == "route"]
    assert len(route) <= 1 and all(c["text"] == "VIA RTE B346, R474 AND G473" for c in route)
    state = procedure["applicability_state"]
    result = route[0]["result"] if route else None
    assert (state == "not_applicable") == (result == "not_met"), (sequence, state, result)
    return result


@pytest.mark.parametrize("sequence,expected", EXPLICIT)
def test_labelled_explicit_leg_controls(sequence, expected):
    assert route_result(sequence) == expected
    assert reference(sequence) == expected, "the segment reference must agree with the hand-written control"


def test_labelled_every_bounded_boundary_transition_matches_the_segment_reference():
    mismatches = [(s, route_result(s), reference(s)) for s in SEQUENCES if route_result(s) != reference(s)]
    assert len(SEQUENCES) == 9330
    assert mismatches == [], mismatches[:12]
