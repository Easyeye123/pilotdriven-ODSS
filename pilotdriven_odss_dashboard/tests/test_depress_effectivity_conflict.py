from __future__ import annotations

import json

import pytest

from app.odss import controlled_library, engines
from app.odss.controlled_library import resolve_aircraft_effectivity


# Shaped like the mounted approved index: variant-scoped profiles alongside a
# smaller set that applies to every airframe. Registrations and charts below are
# invented; nothing keys on a particular tail or route.
def _profiles() -> list[dict[str, object]]:
    return [
        {
            "chart": "T-1", "from": "AAAAA", "to": "BBBBB", "critical": "CCCCC",
            "airways": ["Z100"], "effectivity": ["LH", "ULR"],
        },
        {
            "chart": "T-2", "from": "DDDDD", "to": "EEEEE", "critical": "FFFFF",
            "airways": ["Z200"], "effectivity": ["LH", "ULR"],
        },
        {
            "chart": "T-3", "from": "GGGGG", "to": "HHHHH", "critical": "IIIII",
            "airways": ["Z300"], "effectivity": ["ALL"],
        },
    ]


@pytest.fixture(autouse=True)
def _mounted_index(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", _profiles())
    monkeypatch.delenv(controlled_library.FLEET_EFFECTIVITY_ENV, raising=False)


def _flight(registration: str) -> dict[str, object]:
    return {"registration": registration, "aircraft_type": "A350-941"}


def test_a_known_series_resolves_its_variant() -> None:
    tokens, resolved = resolve_aircraft_effectivity("9V-SMA", "A350-941")

    assert resolved is True
    assert "LH" in tokens


def test_an_unknown_series_resolves_no_variant_and_is_not_guessed() -> None:
    tokens, resolved = resolve_aircraft_effectivity("9V-SJB", "A350-941")

    assert resolved is False
    assert tokens == {"A350941"}, "no variant may be assumed for an unlisted series"


def test_an_unknown_series_is_reported_as_an_effectivity_conflict() -> None:
    """
    This is the defect the boss saw: every variant-scoped chart was withheld and
    the page reported an empty index instead of an unresolved airframe variant.
    """
    conflict = engines.effectivity_conflict(_flight("9V-SJB"))

    assert conflict is not None
    assert conflict["registration"] == "9V-SJB"
    assert conflict["withheld_profile_count"] == 2
    assert conflict["index_profile_count"] == 3
    assert conflict["withheld_variants"] == ["LH", "ULR"]


def test_a_resolved_aircraft_reports_no_conflict() -> None:
    assert engines.effectivity_conflict(_flight("9V-SMA")) is None


def test_a_mounted_fleet_register_resolves_a_new_series(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    register = tmp_path / "fleet.json"
    register.write_text(
        json.dumps({"registration_series": {"9V-SJ": "LH"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.FLEET_EFFECTIVITY_ENV, str(register))

    tokens, resolved = resolve_aircraft_effectivity("9V-SJB", "A350-941")

    assert resolved is True
    assert "LH" in tokens
    assert engines.effectivity_conflict(_flight("9V-SJB")) is None


def test_a_mounted_register_may_refine_a_built_in_series(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    # The longer prefix wins, so an operator can describe a sub-series exactly.
    register = tmp_path / "fleet.json"
    register.write_text(
        json.dumps({"registration_series": {"9V-SMF": "ULR"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.FLEET_EFFECTIVITY_ENV, str(register))

    assert "ULR" in resolve_aircraft_effectivity("9V-SMF", "A350-941")[0]
    assert "LH" in resolve_aircraft_effectivity("9V-SMA", "A350-941")[0]


def test_no_conflict_is_raised_when_the_index_holds_no_variant_scoped_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A genuinely unscoped index withholds nothing, so an unresolved series is
    # not a conflict — it is simply a route with no applicable chart.
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [item for item in _profiles() if item["effectivity"] == ["ALL"]],
    )

    assert engines.effectivity_conflict(_flight("9V-SJB")) is None


def test_a_missing_fleet_register_is_refused_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        controlled_library.FLEET_EFFECTIVITY_ENV, str(tmp_path / "absent.json")
    )

    with pytest.raises(ValueError):
        resolve_aircraft_effectivity("9V-SJB", "A350-941")
