from __future__ import annotations

import json

import pytest

from app.odss import controlled_library, engines
from app.odss.controlled_library import (
    DEFAULT_FLEET_REGISTER,
    resolve_aircraft_effectivity,
)


@pytest.fixture(autouse=True)
def _no_mounted_register(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(controlled_library.FLEET_EFFECTIVITY_ENV, raising=False)


def test_the_shipped_register_is_data_not_code() -> None:
    assert DEFAULT_FLEET_REGISTER.is_file(), "fleet series belong in a register file"
    payload = json.loads(DEFAULT_FLEET_REGISTER.read_text(encoding="utf-8"))
    assert isinstance(payload["registration_series"], dict)


def test_a_series_may_hold_more_than_one_variant() -> None:
    """
    A registration series can be certified for several configurations, and a
    chart tagged for any one of them applies. Mapping such a series to a single
    variant withholds every chart held under the other.
    """
    tokens, resolved = resolve_aircraft_effectivity("9V-SJB", "A350-941")

    assert resolved is True
    assert {"LH", "ULR"} <= tokens


def test_single_variant_series_still_resolve_to_one() -> None:
    assert "LH" in resolve_aircraft_effectivity("9V-SMA", "A350-941")[0]
    assert "ULR" in resolve_aircraft_effectivity("9V-SGE", "A350-941")[0]
    assert "MH" in resolve_aircraft_effectivity("9V-SHA", "A350-941")[0]
    assert "ULR" not in resolve_aircraft_effectivity("9V-SMA", "A350-941")[0]


def test_an_unlisted_series_is_a_conflict_not_a_guess() -> None:
    tokens, resolved = resolve_aircraft_effectivity("XX-YYY", "A350-941")

    assert resolved is False
    assert tokens == {"A350941"}


def test_a_multi_variant_series_can_use_a_chart_held_for_either_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ulr_only = {
        "chart": "T-1", "from": "AAAAA", "to": "BBBBB", "critical": "CCCCC",
        "airways": ["Z100"], "effectivity": ["ULR"],
    }
    lh_only = {
        "chart": "T-2", "from": "DDDDD", "to": "EEEEE", "critical": "FFFFF",
        "airways": ["Z200"], "effectivity": ["LH"],
    }
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", [ulr_only, lh_only])

    for profile in (ulr_only, lh_only):
        assert engines._profile_applies_to_aircraft(profile, "9V-SJB", "A350-941")
    # A single-variant tail still only sees its own.
    assert engines._profile_applies_to_aircraft(lh_only, "9V-SMA", "A350-941")
    assert not engines._profile_applies_to_aircraft(ulr_only, "9V-SMA", "A350-941")


def test_another_airline_is_added_by_mounting_a_register_not_by_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    register = tmp_path / "other-airline.json"
    register.write_text(
        json.dumps({"registration_series": {"G-AB": ["FLEETA"], "N7": "FLEETB"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.FLEET_EFFECTIVITY_ENV, str(register))

    assert "FLEETA" in resolve_aircraft_effectivity("G-ABCD", "A350-941")[0]
    assert "FLEETB" in resolve_aircraft_effectivity("N701XX", "A350-941")[0]
    # The shipped operator's series remain available alongside the mounted one.
    assert "LH" in resolve_aircraft_effectivity("9V-SMA", "A350-941")[0]


def test_a_mounted_register_overrides_the_shipped_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    register = tmp_path / "override.json"
    register.write_text(
        json.dumps({"registration_series": {"9V-SJ": ["ULR"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.FLEET_EFFECTIVITY_ENV, str(register))

    tokens, _ = resolve_aircraft_effectivity("9V-SJB", "A350-941")
    assert "ULR" in tokens
    assert "LH" not in tokens, "a mounted register is authoritative for its series"


def test_no_carrier_or_flight_identifier_is_branched_on_in_the_matcher() -> None:
    source = (
        controlled_library.Path(engines.__file__).read_text(encoding="utf-8")
    )
    for token in ("SQ366", "SIA366", "9V-SJB", "BIROS", "LIRF"):
        assert token not in source, f"{token} must not appear as product logic"
