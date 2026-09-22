"""A NOTAM's item-E body is not a station header.

SQ303, 22 Sep 2026 review of release 390: "Jump to airport has 68 options
including the placeholder (67 airports), with exact entries
ELEV - (FT) - 135/153 (value ELEV) and DVOR - STJ 113.200MHZ/CH79X U/S
(value DVOR)", while the client parser's own manifest held 65 airports and
neither code. The analysis parses the uploaded OFP itself, so the client-side
rule shipped earlier never reached it, and the merged airport index published
what the analysis still carried.

The lines below are the real text of those NOTAMs, taken from the corpus OFP
SQ30316072026BRU 81.pdf (notam appendix lines 964, 1765 and 709).
"""
from __future__ import annotations

from app.odss.enrichment import (
    NON_STATION_ABBREVIATIONS,
    _fuel_enroute_stations,
    classify_bulletin_station_line,
)
from scripts.run_private_cfp_corpus import check_station_identities


ELEV_LINE = "ELEV/HGT (FT) - 135/153"
DVOR_LINE = "DVOR/DME STJ 113.200MHZ/CH 79X U/S"
DVOR_WITHDRAWN_LINE = "DVOR/DME VKL 116.100 MHZ CH108X WITHDRAWN"


def test_equipment_and_obstacle_lines_are_not_stations() -> None:
    assert classify_bulletin_station_line(ELEV_LINE) is None
    assert classify_bulletin_station_line(DVOR_LINE) is None
    assert classify_bulletin_station_line(DVOR_WITHDRAWN_LINE) is None


def test_a_genuine_station_header_is_still_read() -> None:
    assert classify_bulletin_station_line("EHAM/AMS AMSTERDAM/SCHIPHOL") == {
        "icao": "EHAM",
        "iata": "AMS",
        "name": "AMSTERDAM/SCHIPHOL",
    }
    assert classify_bulletin_station_line("VTSP/HKT PHUKET INTL") == {
        "icao": "VTSP",
        "iata": "HKT",
        "name": "PHUKET INTL",
    }


def test_an_airspace_volume_printed_in_an_airport_section_is_not_an_aerodrome() -> None:
    assert classify_bulletin_station_line("LBSR/SOF SOFIA FIR") is None


def test_the_refusal_is_not_only_the_two_codes_that_were_published() -> None:
    """The vocabulary covers the shape, not the two tokens somebody saw."""
    for code in ("ILS", "PAPI", "TWY", "RWY"):
        assert code in NON_STATION_ABBREVIATIONS
    # A name with no digit at all is still refused when the code is equipment.
    assert classify_bulletin_station_line("VORD/DME BRAVO BEACON") is None


def test_the_section_scan_keeps_genuine_stations_and_drops_the_notam_body() -> None:
    section = "\n".join([
        "FUEL ENROUTE AIRPORT(S):",
        "VTSP/HKT PHUKET INTL",
        "1A2685/26                     VALID: 09-JUL-26 0720 - 06-AUG-26 2359",
        DVOR_WITHDRAWN_LINE,
        "EHAM/AMS AMSTERDAM/SCHIPHOL",
        "OBST TYPE - UP TO 3 CRANES",
        ELEV_LINE,
        "EDDF/FRA FRANKFURT/MAIN",
        "DESTINATION AIRPORT:",
        "WSSS/SIN SINGAPORE/CHANGI",
    ])
    assert [station["airport"] for station in _fuel_enroute_stations(section)] == [
        "VTSP",
        "EHAM",
        "EDDF",
    ]


def test_the_corpus_identity_check_names_a_regressed_parser() -> None:
    clean = {
        "departure": "EBBR",
        "destination": "WSSS",
        "fuel_enroute_airports": [{"airport": "EHAM", "name": "AMSTERDAM/SCHIPHOL"}],
    }
    assert check_station_identities(clean) == []

    regressed = {
        "departure": "EBBR",
        "destination": "WSSS",
        "fuel_enroute_airports": [
            {"airport": "EHAM", "name": "AMSTERDAM/SCHIPHOL"},
            {"airport": "ELEV", "name": "(FT) - 135/153"},
            {"airport": "DVOR", "name": "STJ 113.200MHZ/CH 79X U/S"},
        ],
    }
    failures = check_station_identities(regressed)
    assert len(failures) == 2
    assert any("ELEV" in line for line in failures)
    assert any("DVOR" in line for line in failures)
