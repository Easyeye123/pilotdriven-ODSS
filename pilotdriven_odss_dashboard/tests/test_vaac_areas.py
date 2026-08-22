"""Responsible-VAAC resolution against ICAO Doc 9766 Part 2 areas."""

from __future__ import annotations

from app.odss.vaac_areas import (
    VAAC_AREA_SOURCE,
    responsible_vaac_centres,
)


def test_sin_mnl_route_crosses_darwin_and_tokyo() -> None:
    # SQ910: WSSS N1.3 E103.9 -> RPLL N14.5 E121.0. Doc 9766: Darwin holds
    # southward from N1000 between E10000 and E16000; Tokyo holds N1000 to
    # N6000 east of E09000 (the Philippines) - the boss's "there's a VAAC
    # in Manila?" answer is TOKYO, by the official table.
    result = responsible_vaac_centres([(1.3, 103.9), (7.0, 112.0), (14.5, 121.0)])
    assert result["centres"] == ["DARWIN", "TOKYO"]
    assert result["unresolved_points"] == 0


def test_per_sin_route_is_darwin_only() -> None:
    result = responsible_vaac_centres([(-31.9, 116.0), (-20.0, 112.0), (1.3, 103.9)])
    assert result["centres"] == ["DARWIN"]


def test_south_atlantic_point_is_buenos_aires_and_south_pacific_is_wellington() -> None:
    assert responsible_vaac_centres([(-30.0, -40.0)])["centres"] == ["BUENOS AIRES"]
    assert responsible_vaac_centres([(-20.0, 170.0)])["centres"] == ["WELLINGTON"]


def test_africa_and_western_asia_points_are_toulouse() -> None:
    assert responsible_vaac_centres([(-26.1, 28.2)])["centres"] == ["TOULOUSE"]  # Johannesburg
    assert responsible_vaac_centres([(25.2, 55.4)])["centres"] == ["TOULOUSE"]  # Dubai


def test_arctic_pacific_point_is_anchorage() -> None:
    assert responsible_vaac_centres([(62.0, 175.0)])["centres"] == ["ANCHORAGE"]


def test_named_fir_overrides_add_centres() -> None:
    # Gander Oceanic is Montreal's by name; Shanwick is London's.
    result = responsible_vaac_centres([], route_firs=["CZQX", "EGGX"])
    assert result["centres"] == ["LONDON", "MONTREAL"]


def test_unmapped_points_fail_closed_with_candidates() -> None:
    # A point in a boundary zone the table does not settle geometrically
    # must not produce a silent single-centre claim.
    result = responsible_vaac_centres([(55.0, -20.0)])
    assert result["unresolved_points"] == 1
    assert result["centres"] == []
    assert result["review_required"] is True


def test_source_is_the_icao_handbook() -> None:
    assert "9766" in VAAC_AREA_SOURCE["document"]
    assert VAAC_AREA_SOURCE["url"].startswith("https://www.icao.int/")
