from __future__ import annotations

from app.odss.parser import _parse_performance


def test_parses_lido_tonne_rtow_without_treating_tonnes_as_kilograms() -> None:
    performance = _parse_performance(
        """
T/O PERF CALCULATED WITH LPC: RTOW(PERF) 297.4T
RWY : 13R DRY           T/O THR: TOGA/FLEX(STD)
WIND: 150/07
OAT : 26C
QNH : 1021HPA           A/ICE : OFF
                        A/C    : ON
KJFK RWY         RATING:
RWY COND:
RTOW(LAND) 312027
MLGW 205000
RTOW(STRUC) 280000
EOSID     :
OBSTACLES :
MAX FUEL AVAIL: 115274
"""
    )

    assert performance["runway"] == "13R"
    assert performance["runway_condition"] == "DRY"
    assert performance["thrust_setting"] == "TOGA/FLEX(STD)"
    assert performance["temperature_c"] == 26
    assert performance["qnh_hpa"] == 1021
    assert performance["wind"] == "150/07"
    assert performance["packs_on"] is True
    assert performance["anti_ice_on"] is False
    assert performance["eosid"] is None
    assert performance["obstacle_rtow_kg"] == 297_400
    assert performance["landing_rtow_kg"] == 312_027
    assert performance["maximum_landing_weight_kg"] == 205_000
    assert performance["structural_rtow_kg"] == 280_000


def test_rejects_unlabelled_table_headers_and_implausible_rtow_values() -> None:
    performance = _parse_performance(
        """
KJFK RWY         RATING:
RWY COND:
RTOW(PERF) 297
EOSID     :
OBSTACLES :
"""
    )

    assert performance["runway"] is None
    assert performance["runway_condition"] is None
    assert performance["eosid"] is None
    assert performance["obstacle_rtow_kg"] is None
