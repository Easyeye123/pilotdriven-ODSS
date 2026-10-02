"""ATC-AIRWAY-BOUNDARIES (2 Oct 2026, Codex independent QA of release 448, ITEM1).

Release 448 reads an airway-only route list ("ALL ACFT VIA RTE B346, R474 AND G473 ...") against the airways the OFP
files inside the notice's own FIR, including the leg that crosses out of it, and calls the list not met only when every
such leg is known. Codex reproduced, in both languages, a crossing-out leg whose airway the OFP does not hold being
treated as known: the call became not applicable although the exit leg could be one of the listed airways
(support/release448/unknown-exit-leg-controlled-reproduction, receipt SHA a690d2c9...). The same accounting lost the
exit leg when another boundary row follows the exit boundary directly, and when the exit boundary is the last row.
Repaired in both languages (mirrored by tests/atc-airway-boundaries-20261002.test.mjs): an exit leg stays pending across
consecutive boundary rows until a waypoint closes it; a missing or never-printed exit leg makes the FIR's airways
incomplete. A known listed airway still makes the list met. All inputs here are labelled SYNTHETIC.
"""
from __future__ import annotations

import pytest

from app.odss.enroute_contact import compose_enroute_contact

CALL = "ALL ACFT VIA RTE B346, R474 AND G473 SHALL CTC SYNTHETIC ACC ON 126.500MHZ."


def flight(rows):
    """LABELLED SYNTHETIC: rows are (name, airway_in); a name starting with "-" is that FIR's boundary row."""
    waypoints = [{"name": name, "actm_minutes": 5 + 5 * index, "source_page": 1, "airway_in": airway,
                  "fir_boundary": name[1:] if name.startswith("-") else None} for index, (name, airway) in enumerate(rows)]
    return {"departure": "WSSS", "destination": "VHHH", "scheduled_departure_utc": "2026-06-01T01:00:00Z", "route_waypoints": waypoints,
            "notam_procedure_records": [{"notam_id": "SYNTHETIC/26", "validity": "01-JAN-26 0000 - 31-DEC-26 2359",
                                         "heading": "ZZAA SYNTHETIC FIR", "heading_kind": "fir", "fir": "ZZAA", "source_page": 2, "text": CALL}]}


ENTRY = [("SYNA", "Q1"), ("-ZZAA", None), ("SYNB", "A334")]


@pytest.mark.parametrize("label,rows,expected", [
    ("unknown exit leg", ENTRY + [("-ZZBB", None), ("SYNC", None)], None),
    ("known nonmatching exit leg", ENTRY + [("-ZZBB", None), ("SYNC", "Q9")], "not_met"),
    ("known matching exit leg", ENTRY + [("-ZZBB", None), ("SYNC", "B346")], "met"),
    ("unknown exit leg after consecutive boundary rows", ENTRY + [("-ZZBB", None), ("-ZZCC", None), ("SYNC", None)], None),
    ("matching exit leg after consecutive boundary rows", ENTRY + [("-ZZBB", None), ("-ZZCC", None), ("SYNC", "B346")], "met"),
    ("nonmatching exit leg after consecutive boundary rows", ENTRY + [("-ZZBB", None), ("-ZZCC", None), ("SYNC", "Q9")], "not_met"),
    ("exit boundary is the last row", ENTRY + [("-ZZBB", None)], None),
    ("route ends inside the FIR, every leg known", ENTRY + [("SYNC", "W14"), ("SYND", "DCT")], "not_met"),
    ("re-entry with an unknown inner leg", ENTRY + [("-ZZBB", None), ("SYNC", "Q9"), ("-ZZAA", None), ("SYND", None), ("-ZZBB", None), ("SYNE", "Q9")], None),
    ("re-entry with a matching inner leg", ENTRY + [("-ZZBB", None), ("SYNC", "Q9"), ("-ZZAA", None), ("SYND", "G473"), ("-ZZBB", None), ("SYNE", None)], "met"),
    ("unknown entry leg", [("SYNA", "Q1"), ("-ZZAA", None), ("SYNB", None), ("-ZZBB", None), ("SYNC", "Q9")], None),
])
def test_labelled_every_leg_inside_or_crossing_out_of_the_fir_must_be_known_before_a_list_is_not_met(label, rows, expected):
    procedure = compose_enroute_contact(flight(rows))["procedures"][0]
    route = [c for c in procedure["conditions"] if c["kind"] == "route"]
    if expected is None:
        assert route == [], label
        assert procedure["applicability_state"] == "conditions_unresolved", label
    else:
        assert route == [{"kind": "route", "text": "VIA RTE B346, R474 AND G473", "result": expected}], label
        if expected == "not_met":
            assert procedure["applicability_state"] == "not_applicable", label
    assert procedure["printed_details"]["frequencies"] == ["126.500MHZ"]
