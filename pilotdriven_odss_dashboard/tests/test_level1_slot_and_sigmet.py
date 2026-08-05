from __future__ import annotations

from app.odss.pertinent_brief import _slot_allocation_line


def test_the_slot_allocation_reaches_the_level_1_timing_line() -> None:
    """
    The pertinent brief drew the slot waypoint on the route map and named BOBCAT
    as a source, but printed none of its clocks, so the allocation a captain has
    to fly was Level 2 only. Values below are invented; the line is built from
    whatever the CFP holds.
    """
    line = _slot_allocation_line({
        "bobcat": {
            "waypoint": "ZZZZZ",
            "flight_level": 380,
            "ctot_utc": "2026-08-04T17:52:00+00:00",
            "cto_utc": "2026-08-04T23:28:00+00:00",
        }
    })

    assert "ZZZZZ" in line
    assert "FL380" in line
    assert "1752Z" in line
    assert "2328Z" in line


def test_a_pack_without_an_allocation_prints_no_slot_line() -> None:
    assert _slot_allocation_line({}) == ""
    assert _slot_allocation_line({"bobcat": None}) == ""
    assert _slot_allocation_line({"bobcat": {"flight_level": 380}}) == ""


def test_a_partial_allocation_still_prints_what_is_held() -> None:
    line = _slot_allocation_line({"bobcat": {"waypoint": "ZZZZZ"}})

    assert line.startswith("SLOT ZZZZZ")
    assert "FL" not in line, "a level that is not held is not invented"
