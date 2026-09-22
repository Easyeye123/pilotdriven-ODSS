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
    # The real row (SQ023 25 Jul 2026 and five more held OFPs) is refused by
    # its name, which is prose rather than a place. FIR and UIR are no longer
    # refused as IATA codes: UIR is Quirindi (see the YQDI tests below).
    assert classify_bulletin_station_line(
        "EBBU/FIR - RESTRICTIONS RELATED TO THE RUSSIAN INVASION OF"
    ) is None
    assert classify_bulletin_station_line("EBBU/UIR - UPPER AIRSPACE NOTICE") is None


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


# An aerodrome whose IATA code collides with an abbreviation in the vocabulary.
# DME is Moscow Domodedovo's three-letter code (IATA code search, retrieved
# 22 Sep 2026). The vocabulary is an ICAO/NOTAM abbreviation dictionary, not a
# denylist over IATA code space, and applying it to the second column refused a
# real aerodrome (independent review of the deployed rule in both parsers).
IATA_COLLISIONS = [
    ("UUDD/DME MOSCOW/DOMODEDOVO", "UUDD", "DME"),
    ("EGGP/LPL LIVERPOOL/JOHN LENNON", "EGGP", "LPL"),
    ("LFPG/CDG PARIS/CHARLES DE GAULLE", "LFPG", "CDG"),
]


def test_a_real_aerodrome_is_kept_when_its_iata_code_is_also_an_abbreviation() -> None:
    for line, icao, iata in IATA_COLLISIONS:
        station = classify_bulletin_station_line(line)
        assert station is not None, line
        assert station["icao"] == icao
        assert station["iata"] == iata


def test_the_equipment_lines_are_still_refused_by_their_leading_word() -> None:
    """The refusal moved to the leading column; it did not go away."""
    assert "DME" in NON_STATION_ABBREVIATIONS
    for line in (ELEV_LINE, DVOR_LINE, DVOR_WITHDRAWN_LINE):
        assert classify_bulletin_station_line(line) is None, line


def test_a_collision_still_loses_to_the_prose_guards() -> None:
    """The name tests do not care which column carried the abbreviation."""
    assert classify_bulletin_station_line("UUDD/DME 113.200MHZ/CH 79X U/S") is None
    assert classify_bulletin_station_line("UUDD/DME MOSCOW FIR") is None


def test_the_section_scan_keeps_a_colliding_aerodrome() -> None:
    section = "\n".join([
        "FUEL ENROUTE AIRPORT(S):",
        "UUDD/DME MOSCOW/DOMODEDOVO",
        DVOR_WITHDRAWN_LINE,
        "EHAM/AMS AMSTERDAM/SCHIPHOL",
        ELEV_LINE,
    ])
    assert [station["airport"] for station in _fuel_enroute_stations(section)] == ["UUDD", "EHAM"]


def test_a_colliding_aerodrome_passes_the_corpus_identity_check() -> None:
    flight = {
        "departure": "EBBR",
        "destination": "WSSS",
        "fuel_enroute_airports": [{"airport": "UUDD", "name": "MOSCOW/DOMODEDOVO"}],
    }
    assert check_station_identities(flight) == []


# B5, third round: UIR is also a real aerodrome's IATA code. IATA's official
# Airline and Airport Code Search returns "Quirindi | Quirindi Airport | UIR"
# (queried in real Chrome, 22 Sep 2026); Airservices Australia's ERSA entry
# FAC_YQDI_09JUL2026 identifies QUIRINDI / YQDI. Identity only - the rows below
# are LABELLED SYNTHETIC station-header shapes built from those identifiers; no
# held OFP prints Quirindi. Both parsers refused them because FIR and UIR were
# refused unconditionally in the IATA column (independent review, 16:40Z).
def test_an_aerodrome_whose_iata_code_is_uir_is_still_an_aerodrome() -> None:
    for line in ("YQDI/UIR QUIRINDI", "YQDI /UIR QUIRINDI"):
        assert classify_bulletin_station_line(line) == {"icao": "YQDI", "iata": "UIR", "name": "QUIRINDI"}, line


def test_airspace_prose_is_still_refused_because_its_name_is_not_a_place() -> None:
    for line in (
        "EBBU/FIR - RESTRICTIONS RELATED TO THE RUSSIAN INVASION OF",  # real, six held OFPs
        "EBBU/UIR - UPPER AIRSPACE NOTICE",
        "EBBU/UIR",
        "NZZC/NEW ZEALAND FIR",
        "YQDI/UIR 113.200MHZ",
    ):
        assert classify_bulletin_station_line(line) is None, line


def test_a_row_whose_iata_code_is_also_an_airspace_volume_must_head_its_own_block() -> None:
    """Shape cannot tell "YQDI/UIR QUIRINDI" from an airspace line with a clean
    name; the OFP's structure can. Every real station row heads its own block -
    a dashed underline in the NOTAM appendix, its own records in the weather
    appendix - while every false station so far was an item-E body line. The
    requirement is for this ambiguous class only: applied to every row it drops
    real airports whose heading falls on a page break (measured on the JS twin
    across the held corpus). LABELLED SYNTHETIC text with the real appendix
    structure (fitz text of SQ30316072026BRU 81.pdf)."""
    notam_appendix = "\n".join([
        "FUEL ENROUTE AIRPORT",
        "====================",
        " ",
        "EHAM /AMS   AMSTERDAM/SCHIPHOL",
        "------------------------------",
        "++++++++++++++++++++++++ APPROACH PROCEDURE ++++++++++++++++++++++++",
        "1A2685/26                     VALID: 09-JUL-26 0720 - 06-AUG-26 2359",
        "  " + DVOR_WITHDRAWN_LINE,
        "1A2686/26                     VALID: 09-JUL-26 0720 - 06-AUG-26 2359",
        "  EBBU/UIR BRUSSELS UPPER AREA RESTRICTED",
        "  CHECK ACT WITH BRUSSELS FIC.",
        " ",
        "YQDI /UIR   QUIRINDI",
        "-------------------",
        "++++++++++++++++++++++++++++++ RUNWAY ++++++++++++++++++++++++++++++",
    ])
    assert [station["airport"] for station in _fuel_enroute_stations(notam_appendix)] == ["EHAM", "YQDI"]
    weather_appendix = "\n".join([
        "FUEL ENROUTE AIRPORT:",
        "YQDI/UIR QUIRINDI",
        "  SA 160620 05003KT CAVOK 19/14 Q1019=",
        "EHAM/AMS AMSTERDAM/SCHIPHOL",
        "  SA 160625 03006KT 350V080 9999 FEW016 21/17 Q1020 NOSIG=",
    ])
    assert [station["airport"] for station in _fuel_enroute_stations(weather_appendix)] == ["YQDI", "EHAM"]
