"""AIRSPACE-HEADINGS-436 (independent QA of release 436, 27 Sep 2026: ATC / FIR completeness and the heading boundary).

The NOTAM section's FIR grammar accepted a heading only when it ended in "FIR" ("OAKX  KABUL FIR"). Genuine LIDO
bulletins also print a FIR's airspace part after the designator - `RJJJ FUKUOKA FIR OCEANIC`, `UBBA BAKU FIR LOWER`,
`KZNY NEW YORK DOMESTIC LOWER`, `LFFF FRANCE UIR` - and, inside the enroute ("AREA ...") parts, topic sub-headings that
name no FIR (`UAV 401614N 0250927E`, `VAA GREAT SITKIN`, `TEST FLIGHT N4202`, restricted areas) and NOTAM-number labels
with a location prefix (`KZLA A1657/26`). Every such underlined heading ended the held scope, so the communication
notices under it were never held. Corpus impact (genuine sources): SQ34 / SQ38 / both SQ24 lose Fukuoka-oceanic
ATS-data-link notices SX75/24 and SX90/23 on a route that crosses RJJJ; both SQ24 lose KZNY 1A487/26 (CPDLC route
messaging not available) on a route that crosses KZNY; SQ365 / SQ366 lose 1A2595/26 (UAV flights within ATHINAI FIR,
voice contact); SQ38 loses 1A1227/25 (Great Sitkin volcanic activity advisory, voice contact).

The general rule (no flight, FIR, notice, frequency or time is special-cased):
- a FIR heading may carry its airspace part after the designator (FIR / UIR / FIR/UIR followed by LOWER, UPPER, OCEANIC,
  DOMESTIC) or name the part without the word FIR (DOMESTIC / OCEANIC, optionally LOWER / UPPER, or UIR); the heading
  owns its notices for that FIR and the printed part is kept on every record (`airspace`), never dropped;
- a NOTAM-number label with a 1-4 letter location prefix continues the current section;
- inside an enroute ("AREA ...") part, any other underlined heading is a topic: its communication notices are held with
  heading_kind "topic" and no owning FIR - never under the FIR printed before it; in the airport parts nothing is held,
  as before, and an airport heading (ICAO /IATA NAME) always ends the enroute scope;
- the composition binds an airspace-part record to its FIR's crossing and states the printed part as a condition the OFP
  cannot evaluate; a topic record is bound to no crossing and says the owning FIR is not established.

Synthetic pages are LABELLED SYNTHETIC; the genuine cases read the private corpus.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.enroute_contact import ENROUTE_CONTACT_RULE, compose_enroute_contact
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.parser import _parse_notam_fir_names, _parse_notam_procedure_records, extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"

HEADER = "SIA 900/01Jan26/ZZAA-ZZCC Reg:9VQAA OFP:1/0/0"
RULE = "---------------------"
BAR = "=========================================="
AREA = [BAR, "AREA ENROUTE DEPARTURE - DESTINATION", BAR]
AIRPORTS = [BAR, "ENROUTE AIRPORT(S)", BAR]


def notice(identity: str, *text: str) -> list[str]:
    return [f"{identity}                      VALID: 01-JAN-26 0000 - 31-DEC-26 2359", *(f"  {line}" for line in text)]


CALL = ("ALL FLIGHTS SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ.",)
DATALINK = ("CPDLC LOGON TO ZZAA IS REQUIRED 15 MIN BEFORE ENTRY.",)
NO_CALL = ("RWY 01/19 CLSD DUE TO WIP.",)


def page(number: int, total: int, body: list[str]) -> str:
    """LABELLED SYNTHETIC: one LIDO page as the text extraction prints it (furniture after the page's own lines)."""
    return "\n".join([" ", *body, HEADER, f"Page {number} of {total}"])


def records(pages: list[str]) -> list[dict]:
    return _parse_notam_procedure_records(pages, (0, len(pages)))


def by_id(recs: list[dict], notam_id: str) -> dict:
    found = [r for r in recs if r["notam_id"] == notam_id]
    assert len(found) == 1, f"{notam_id}: {found}"
    return found[0]


# ------------------------------------------------------------------------------------ airspace-part FIR headings

@pytest.mark.parametrize("heading,icao,airspace", [
    ("ZZAA ALPHA FIR LOWER", "ZZAA", "FIR LOWER"),
    ("ZZAA ALPHA FIR UPPER", "ZZAA", "FIR UPPER"),
    ("ZZAA ALPHA FIR OCEANIC", "ZZAA", "FIR OCEANIC"),
    ("ZZAA NORTH ALPHA DOMESTIC LOWER", "ZZAA", "DOMESTIC LOWER"),
    ("ZZAA ALPHA OCEANIC", "ZZAA", "OCEANIC"),
    ("ZZAA ALPHA UIR", "ZZAA", "UIR"),
    ("ZZAA ALPHA FIR/UIR", "ZZAA", "FIR/UIR"),
], ids=["fir-lower", "fir-upper", "fir-oceanic", "domestic-lower", "oceanic", "uir", "fir-uir"])
def test_a_heading_that_names_the_firs_airspace_part_owns_its_notices_and_keeps_the_part(heading, icao, airspace):
    pages = [page(1, 1, [*AREA, heading, RULE, *notice("1G901/26", *CALL)])]
    held = by_id(records(pages), "1G901/26")
    assert (held["heading"], held["heading_kind"], held["fir"], held["airspace"]) == (heading, "fir", icao, airspace)


def test_the_classic_headings_are_unchanged():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G901/26", *CALL), " ",
                         "ZZBB BRAVO LOWER FIR", RULE, *notice("1G902/26", *CALL)])]
    recs = records(pages)
    assert (by_id(recs, "1G901/26")["fir"], by_id(recs, "1G901/26").get("airspace")) == ("ZZAA", None)
    assert (by_id(recs, "1G902/26")["heading"], by_id(recs, "1G902/26")["fir"], by_id(recs, "1G902/26").get("airspace")) == (
        "ZZBB BRAVO LOWER FIR", "ZZBB", None)
    assert _parse_notam_fir_names(pages, (0, 1)) == {"ZZAA": "ALPHA", "ZZBB": "BRAVO LOWER"}


def test_an_airspace_part_heading_names_a_fir_only_when_no_plain_fir_heading_did():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR OCEANIC", RULE, *notice("1G901/26", *CALL), " ",
                         "ZZAA ALPHA FIR", RULE, *notice("1G902/26", *CALL), " ",
                         "ZZBB BRAVO FIR LOWER", RULE, *notice("1G903/26", *NO_CALL), " ",
                         "ZZCC NEW CHARLIE DOMESTIC LOWER", RULE, *notice("1G904/26", *NO_CALL), " ",
                         "ZZDD DELTA UIR", RULE, *notice("1G905/26", *NO_CALL)])]
    assert _parse_notam_fir_names(pages, (0, 1)) == {"ZZAA": "ALPHA", "ZZBB": "BRAVO", "ZZCC": "NEW CHARLIE", "ZZDD": "DELTA"}


def test_an_airspace_part_heading_at_the_foot_of_a_page_owns_the_notices_on_the_next():
    pages = [page(1, 2, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *CALL), " ", "ZZBB BRAVO FIR OCEANIC"]),
             page(2, 2, [" ", RULE, *notice("1G901/26", *DATALINK)])]
    held = by_id(records(pages), "1G901/26")
    assert (held["fir"], held["airspace"], held["heading_page"], held["source_page"]) == ("ZZBB", "FIR OCEANIC", 1, 2)


def test_an_airspace_part_heading_printed_without_its_rule_leaves_the_owner_unresolved():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *CALL), " ",
                         "ZZBB BRAVO FIR OCEANIC", *notice("1G901/26", *DATALINK)])]
    held = by_id(records(pages), "1G901/26")
    assert (held["heading_kind"], held["fir"]) == ("unresolved", None)


# ------------------------------------------------------------------------------------ labels, topics, airports

def test_a_notam_number_label_with_a_location_prefix_continues_the_section():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *NO_CALL), " ",
                         "ZZAA A1234/26", RULE, *notice("1A1234/26", *CALL)])]
    held = by_id(records(pages), "1A1234/26")
    assert (held["heading"], held["heading_kind"], held["fir"]) == ("ZZAA ALPHA FIR", "fir", "ZZAA")


@pytest.mark.parametrize("topic", ["UAV 101010N 0101010E", "VAA SYNTHETIC PEAK", "TEST FLIGHT N4202", "FRNG AREA/SYNTHETIC",
                                   "D22 SYNTHETIC RANGE", "PACOTS AREA (NOTAM)", "ZZAA ALPHA FIR LOWER LIMIT FL245"])
def test_a_topic_heading_in_an_enroute_part_holds_its_calls_without_an_owner(topic):
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *CALL), " ",
                         topic, RULE, *notice("1G901/26", *CALL)])]
    recs = records(pages)
    held = by_id(recs, "1G901/26")
    assert (held["heading"], held["heading_kind"], held["fir"], held.get("airspace")) == (topic, "topic", None, None)
    assert by_id(recs, "1G900/26")["fir"] == "ZZAA"  # the FIR before it keeps only its own notices


def test_nothing_in_an_airport_part_is_held_and_an_airport_heading_ends_the_enroute_scope():
    pages = [page(1, 1, [*AIRPORTS, "ZZXX /ZZX SYNTHETIC INTL", RULE, *notice("1G800/26", *CALL), " ",
                         "RWY 01/19 IS NOT AVBL FOR CIV USE.", RULE, *notice("1G801/26", *CALL), " ",
                         *AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *CALL), " ",
                         "ZZYY /ZZY OTHER INTL", RULE, *notice("1G901/26", *CALL)])]
    ids = {r["notam_id"] for r in records(pages)}
    assert ids == {"1G900/26"}


def test_body_text_that_looks_like_a_heading_stays_notice_text():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE,
                         *notice("1G900/26", "THE ZZAA ALPHA FIR OCEANIC PART", "ALL FLIGHTS SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ.")])]
    held = by_id(records(pages), "1G900/26")
    assert (held["fir"], held.get("airspace")) == ("ZZAA", None)
    assert "THE ZZAA ALPHA FIR OCEANIC PART" in held["text"]


# ------------------------------------------------------------------------------------ the composition

def flight_with(recs: list[dict], firs: list[str]) -> dict:
    return {
        "route_waypoints": [{"name": f"WP{i}", "fir_boundary": fir, "actm_minutes": 30 * (i + 1), "source_page": 3} for i, fir in enumerate(firs)],
        "scheduled_departure_utc": "2026-06-01T00:00:00Z", "extraction_rules": EXTRACTION_RULES,
        "notam_procedure_records": recs, "notam_fir_names": {},
    }


def test_the_composition_binds_an_airspace_part_to_its_fir_and_states_the_part_it_cannot_evaluate():
    pages = [page(1, 1, [*AREA, "ZZBB BRAVO FIR OCEANIC", RULE, *notice("1G901/26", *CALL)])]
    composed = compose_enroute_contact(flight_with(records(pages), ["ZZAA", "ZZBB", "ZZCC"]))
    row = next(p for p in composed["procedures"] if p["notam_id"] == "1G901/26")
    assert (row["fir"], row["association"], row["actm"]) == ("ZZBB", "fir_heading", "01:00")
    assert {"kind": "qualifier", "text": "section ZZBB BRAVO FIR OCEANIC", "result": "unresolved"} in row["conditions"]
    assert row["applicability_state"] == "conditions_unresolved"
    assert "section ZZBB BRAVO FIR OCEANIC: not evaluable from the OFP" in composed["procedure_lines"][0]["conditions_summary"]


def test_the_composition_binds_a_topic_to_no_crossing_and_says_the_owning_fir_is_not_established():
    pages = [page(1, 1, [*AREA, "ZZAA ALPHA FIR", RULE, *notice("1G900/26", *NO_CALL), " ",
                         "UAV 101010N 0101010E", RULE, *notice("1G901/26", *CALL)])]
    composed = compose_enroute_contact(flight_with(records(pages), ["ZZAA", "ZZBB"]))
    row = next(p for p in composed["procedures"] if p["notam_id"] == "1G901/26")
    assert (row["fir"], row["actm"], row["latest_actm"], row["association"]) == ("", None, None, "unresolved")
    assert {"kind": "association", "text": "owning FIR not established: printed under UAV 101010N 0101010E", "result": "unresolved"} in row["conditions"]


# ------------------------------------------------------------------------------------ genuine sources

_PARSED: dict[str, dict] = {}


def genuine(name: str) -> dict:
    if name not in _PARSED:
        source = CORPUS / name
        if not source.is_file():
            pytest.skip(f"private corpus file {name} is not on this machine")
        _PARSED[name] = parse_lido(extract_pages(source), name)
    return _PARSED[name]


def held(flight: dict, notam_id: str) -> dict:
    found = [r for r in flight["notam_procedure_records"] if r["notam_id"] == notam_id]
    assert len(found) == 1, f"{notam_id}: {found}"
    return found[0]


@pytest.mark.parametrize("name", ["lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf", "SQ38-29AUG2026-OFP-for-prod-proof.pdf",
                                  "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", "SQ02422072026SIN.pdf"])
def test_genuine_pacific_flights_hold_the_fukuoka_oceanic_data_link_notices(name):
    flight = genuine(name)
    for notam_id in ("SX75/24", "SX90/23"):
        record = held(flight, notam_id)
        assert (record["heading"], record["heading_kind"], record["fir"], record["airspace"]) == (
            "RJJJ FUKUOKA FIR OCEANIC", "fir", "RJJJ", "FIR OCEANIC")
    composed = compose_enroute_contact(flight)
    rows = [p for p in composed["procedures"] if p["notam_id"] in ("SX75/24", "SX90/23")]
    assert {r["fir"] for r in rows} == {"RJJJ"} and all(r["association"] == "fir_heading" for r in rows)


@pytest.mark.parametrize("name", ["lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", "SQ02422072026SIN.pdf"])
def test_genuine_new_york_arrivals_hold_the_domestic_lower_cpdlc_notice(name):
    record = held(genuine(name), "1A487/26")
    assert (record["heading"], record["fir"], record["airspace"]) == ("KZNY NEW YORK DOMESTIC LOWER", "KZNY", "DOMESTIC LOWER")
    assert genuine(name)["notam_fir_names"].get("KZNY") == "NEW YORK"


@pytest.mark.parametrize("name,notam_id,topic", [
    ("SQ36604082026SIN.pdf", "1A2595/26", "UAV 401614N 0250927E"),
    ("SQ36507082026FCO.pdf", "1A2595/26", "UAV 401614N 0250927E"),
    ("SQ38-29AUG2026-OFP-for-prod-proof.pdf", "1A1227/25", "VAA GREAT SITKIN"),
])
def test_genuine_topic_notices_with_calls_are_held_without_an_owner(name, notam_id, topic):
    record = held(genuine(name), notam_id)
    assert (record["heading"], record["heading_kind"], record["fir"]) == (topic, "topic", None)


def test_genuine_baku_lower_heading_names_its_fir():
    assert genuine("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf")["notam_fir_names"].get("UBBA") == "BAKU"


def test_the_tokens_move_together():
    assert EXTRACTION_RULES == "2026-10-18-operand-accounted-whole-v23"
    assert ENROUTE_CONTACT_RULE == "enroute-contact-v16"
