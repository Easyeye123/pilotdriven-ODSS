from __future__ import annotations

import pytest

from app.odss import engines


# A corridor with two charts whose coverage overlaps, so the selection has a
# genuine choice to make. Names are invented; nothing keys on a real route.
_PROFILES = [
    {
        "chart": "B-2", "from": "PPPPP", "to": "RRRRR", "critical": "QQQQQ",
        "airways": ["Z900"], "effectivity": ["ALL"],
    },
    {
        "chart": "A-1", "from": "PPPPP", "to": "SSSSS", "critical": "QQQQQ",
        "airways": ["Z900"], "effectivity": ["ALL"],
    },
]


def _waypoints() -> list[dict[str, object]]:
    names = ["PPPPP", "QQQQQ", "RRRRR", "SSSSS"]
    return [
        {
            "name": name,
            "airway_in": None if index == 0 else "Z900",
            "actm_minutes": index * 10,
            "msa_hundreds_ft": 150,
        }
        for index, name in enumerate(names)
    ]


def test_the_same_inputs_always_select_the_same_charts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A depressurisation chart is chosen by rule, never by a model, so repeating a
    run must not shuffle which chart a crew is shown. Ties are broken on chart
    id so ordering inside the index cannot change the answer either.
    """
    waypoints = _waypoints()
    events = engines.detect_terrain_events(waypoints)
    flight = {
        "route_waypoints": waypoints,
        "registration": "9V-SMA",
        "aircraft_type": "A350-941",
    }

    monkeypatch.setattr(engines, "DEPRESS_PROFILES", list(_PROFILES))
    first = [m["profile"]["chart"] for m in engines.match_profiles(flight, events)]

    # Same data, opposite index order.
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", list(reversed(_PROFILES)))
    second = [m["profile"]["chart"] for m in engines.match_profiles(flight, events)]

    assert first == second, "chart selection must not depend on index ordering"
    assert first, "a covered corridor must yield a match"


def test_repeated_runs_are_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    waypoints = _waypoints()
    events = engines.detect_terrain_events(waypoints)
    flight = {
        "route_waypoints": waypoints,
        "registration": "9V-SMA",
        "aircraft_type": "A350-941",
    }
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", list(_PROFILES))

    runs = {
        tuple(
            (m["profile"]["chart"], m["match_class"], m["route_start"], m["route_end"])
            for m in engines.match_profiles(flight, events)
        )
        for _ in range(5)
    }

    assert len(runs) == 1, "five identical runs must produce one identical result"


def test_an_unmapped_series_withholds_charts_rather_than_selecting_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = _waypoints()
    events = engines.detect_terrain_events(waypoints)
    scoped = [{**item, "effectivity": ["LH"]} for item in _PROFILES]
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", scoped)

    unmapped = {
        "route_waypoints": waypoints,
        "registration": "XX-YYY",
        "aircraft_type": "A350-941",
    }

    assert engines.match_profiles(unmapped, events) == []
    conflict = engines.effectivity_conflict(unmapped)
    assert conflict is not None
    assert conflict["withheld_profile_count"] == len(scoped)
