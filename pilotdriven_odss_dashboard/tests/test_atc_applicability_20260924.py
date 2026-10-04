"""ATC-CONDITIONS-CLOCK-EXTRACTION-420 (independent production QA of release 420, 24 Sep 2026).

F1  A notice's printed restrictions are conditions. Release 420 evaluated only
    the conditions it recognised and let a valid date promote the rest to
    "conditions held": the genuine SQ24 (WSSS-KJFK) OFP prints 1F2293/26 for
    IFR aircraft planned to depart CYMM/OILSANDS that are unable to contact
    Edmonton Centre, and 1A1136/25's notification sentence is governed by the
    preceding "flights that experience or suspect GNSS interference". Now every
    action sentence carries the qualifiers of its own subject or of the sentence
    that governs it: an airport restriction is evaluated against this flight's
    departure / destination (a negative match is not applicable), and any other
    printed qualifier stays an explicit unresolved condition. Nothing unparsed
    defaults to met.
F3  One effective timing basis - the actual take-off when held, else the
    scheduled departure - governs the displayed crossing clocks AND every
    validity decision, on both readers.
F4  Every communication sentence of a notice is kept as an action with its own
    conditions and printed values (frequencies, leads, intervals, logon
    addresses); the headline is the directive sentence with printed values, not
    an introductory statement; the rest are exposed, not discarded.
F2  The parser stamps the extraction rules it applied; a composition over an
    analysis extracted by an earlier parser says so instead of presenting that
    extraction as current.
No flight, airport, notice, frequency or expected answer is special-cased.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.odss.enroute_contact import compose_enroute_contact
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
SOURCES = {"SQ24": "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", "SQ366": "SQ36604082026SIN.pdf"}
_FLIGHTS: dict[str, dict] = {}


def genuine_flight(key: str) -> dict:
    if key not in _FLIGHTS:
        source = CORPUS / SOURCES[key]
        if not source.is_file():
            pytest.skip(f"private CFP corpus file {SOURCES[key]} is not available")
        _FLIGHTS[key] = parse_lido(extract_pages(source), source.name)
    return copy.deepcopy(_FLIGHTS[key])


def rows_by_id(flight: dict, **kwargs) -> dict[str, dict]:
    return {row["notam_id"]: row for row in compose_enroute_contact(flight, [], **kwargs)["procedures"]}


def condition(row: dict, kind: str) -> dict:
    found = [c for c in row["conditions"] if c["kind"] == kind]
    assert found, f"{row['notam_id']}: no {kind} condition among {[c['kind'] for c in row['conditions']]}"
    return found[0]


# ---------------------------------------------------------------- F1: printed restrictions are conditions


def test_f1_a_departure_airport_restriction_for_another_airport_is_not_applicable_to_this_flight():
    flight = genuine_flight("SQ24")
    assert flight["departure"] == "WSSS" and flight["destination"] == "KJFK"
    row = rows_by_id(flight)["1F2293/26"]
    assert row["applicability_state"] == "not_applicable", row["conditions"]
    departure = condition(row, "departure")
    assert departure["result"] == "not_met" and "CYMM" in departure["text"] and "WSSS" in departure["text"]
    # The inability-to-contact trigger is kept as a condition the OFP cannot decide, not dropped.
    assert any(c["result"] == "unresolved" and "UNABLE TO CTC" in c["text"] for c in row["conditions"]), row["conditions"]


def test_f1_the_same_restriction_naming_this_flights_departure_is_met_but_its_trigger_stays_unresolved():
    # SYNTHETIC: the genuine 1F2293/26 text with the departure aerodrome renamed to this flight's own departure.
    flight = genuine_flight("SQ24")
    for record in flight["notam_procedure_records"]:
        if record["notam_id"] == "1F2293/26":
            record["notam_id"] = "SYN-DEP/26"
            record["text"] = record["text"].replace("DEP CYMM/OILSANDS", "DEP WSSS/CHANGI")
    row = rows_by_id(flight)["SYN-DEP/26"]
    assert condition(row, "departure")["result"] == "met"
    assert row["applicability_state"] == "conditions_unresolved", "unable-to-contact cannot be decided from the OFP"


def test_f1_a_trigger_in_the_governing_sentence_reaches_the_action_it_governs():
    row = rows_by_id(genuine_flight("SQ24"))["1A1136/25"]
    assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
    assert any(c["result"] == "unresolved" and "EXPERIENCE OR SUSPECT GNSS INTERFERENCE" in c["text"] for c in row["conditions"]), row["conditions"]
    assert "NOTIFICATION SHOULD BE VIA CPDLC" in row["instruction"] or any("NOTIFY ANCHORAGE ATC" in a["sentence"] for a in row["actions"])


def test_f1_nothing_unparsed_is_promoted_and_recognised_conditions_still_decide():
    # A sentence with no qualifier at all stays decidable by validity and scope (the Kabul TIBA overflight row).
    rows = rows_by_id(genuine_flight("SQ366"))
    tiba = rows["1G216/26"]
    assert tiba["applicability_state"] == "conditions_held"
    assert {c["kind"] for c in tiba["conditions"]} == {"validity", "scope"}
    # A notice whose crew action depends on ATC's request is not held as an unconditional call.
    assert rows["1A1891/26"]["applicability_state"] == "conditions_unresolved"
    assert any("REQUESTED BY ATC" in c["text"] for c in rows["1A1891/26"]["conditions"])
    # The 420 state sentence never claims "met" over an unresolved or failed row.
    composed = compose_enroute_contact(genuine_flight("SQ24"), [])
    counts = {state: sum(1 for r in composed["procedures"] if r["applicability_state"] == state) for state in ("conditions_held", "conditions_unresolved", "not_applicable")}
    assert f"printed conditions met on {counts['conditions_held']}, unresolved on {counts['conditions_unresolved']}, not applicable on {counts['not_applicable']}" in composed["state_sentence"]
    assert counts["not_applicable"] >= 1 and counts["conditions_unresolved"] >= 1


# ---------------------------------------------------------------- F4: every action kept, the directive one leads


def test_f4_every_communication_sentence_is_an_action_and_the_directive_one_with_printed_values_leads():
    row = rows_by_id(genuine_flight("SQ24"))["1A44/24"]
    sentences = [a["sentence"] for a in row["actions"]]
    assert len(row["actions"]) >= 5, sentences
    assert any("USE LOGON ADDRESS PAZN" in s for s in sentences) and any("USE LOGON ADDRESS PAZA" in s for s in sentences)
    assert any("REQUESTS TO ATC SHOULD BE MADE OVER VHF" in s for s in sentences)
    assert any("HF OR VHF MONITORING" in s for s in sentences)
    assert "TWO DIFFERENT CPDLC LOGON ADDRESSES" not in row["instruction"], "an introductory statement is not the headline"
    assert "LOGON ADDRESS" in row["instruction"] and row["printed_details"]["addresses"]
    for action in row["actions"]:
        assert action["kind"] and action["applicability_state"] in ("conditions_held", "conditions_unresolved", "not_applicable")
        assert isinstance(action["conditions"], list)
    # The address selection is conditional on where the aircraft is; that is stated, not promoted.
    headline = next(a for a in row["actions"] if a["sentence"] == row["instruction"])
    assert headline["applicability_state"] != "conditions_held" or not any("WHEN" in a["sentence"] for a in [headline])


def test_f4_printed_logon_addresses_are_values():
    rows = rows_by_id(genuine_flight("SQ24"))
    assert rows["1A44/24"]["printed_details"]["addresses"] in (["PAZN"], ["PAZN", "PAZA"])
    assert "WIIF" in rows["1A1891/26"]["printed_details"]["addresses"] or any("WIIF" in a["printed_details"]["addresses"] for a in rows["1A1891/26"]["actions"])


# ---------------------------------------------------------------- F3: one effective timing basis


def _expiry_flight(end: str) -> dict:
    """SYNTHETIC expiry edge on the genuine SQ366 route: one notice whose validity ends at ``end`` (24 Sep review probe)."""
    flight = genuine_flight("SQ366")
    source = next(r for r in flight["notam_procedure_records"] if r["notam_id"] == "1G216/26")
    flight["notam_procedure_records"] = [{**source, "notam_id": "SYNTHETIC-QA-EXPIRY", "validity": f"04-AUG-26 0000 - {end}"}]
    return flight


def test_f3_the_validity_decision_follows_the_actual_take_off_when_it_is_held():
    flight = _expiry_flight("04-AUG-26 2315")
    early = compose_enroute_contact(flight, [], actual_takeoff_utc="2026-08-04T17:30:00Z")
    late = compose_enroute_contact(flight, [], actual_takeoff_utc="2026-08-04T18:00:00Z")
    assert early["timing_basis"] == {"kind": "actual_takeoff", "utc": "2026-08-04T17:30:00Z"}
    assert next(r for r in early["crossings"] if r["fir"] == "OAKX")["utc"] == "2305Z"
    assert next(r for r in late["crossings"] if r["fir"] == "OAKX")["utc"] == "2335Z"
    assert early["procedures"][0]["applicability_state"] == "conditions_held"
    assert late["procedures"][0]["applicability_state"] == "not_applicable"
    assert condition(late["procedures"][0], "validity")["result"] == "not_met"
    assert "ATOT 1800Z" in condition(late["procedures"][0], "validity")["basis"]


def test_f3_the_held_analysis_take_off_is_the_default_basis_and_the_scheduled_departure_the_fallback():
    flight = _expiry_flight("04-AUG-26 2315")
    scheduled = compose_enroute_contact(flight, [])
    assert scheduled["timing_basis"] == {"kind": "scheduled_departure", "utc": "2026-08-04T17:30:00Z"}
    assert scheduled["procedures"][0]["applicability_state"] == "conditions_held"
    assert "scheduled departure" in condition(scheduled["procedures"][0], "validity")["basis"]
    flight["actual_takeoff_utc"] = "2026-08-04T18:00:00Z"
    held = compose_enroute_contact(flight, [])
    assert held["timing_basis"]["kind"] == "actual_takeoff" and held["procedures"][0]["applicability_state"] == "not_applicable"
    flight.pop("actual_takeoff_utc"); flight.pop("scheduled_departure_utc")
    none = compose_enroute_contact(flight, [])
    assert none["timing_basis"] == {"kind": "none", "utc": None}
    assert condition(none["procedures"][0], "validity")["result"] == "unresolved"


# ---------------------------------------------------------------- F2: the extraction rules travel with the analysis


def test_f2_the_parser_stamps_its_extraction_rules_and_an_older_extraction_is_stated():
    from app.odss.extraction_rules import EXTRACTION_RULES
    flight = genuine_flight("SQ366")
    assert flight["extraction_rules"] == EXTRACTION_RULES
    current = compose_enroute_contact(flight, [])
    assert current["extraction"] == {"rules": EXTRACTION_RULES, "current": True}
    assert not current["state_sentence"].startswith("Held extraction")
    older = dict(flight)
    older.pop("extraction_rules")
    stale = compose_enroute_contact(older, [])
    assert stale["extraction"] == {"rules": None, "current": False}
    assert stale["state_sentence"].startswith("Held extraction predates the current parser (rules not stated): the notices below are the ones that extraction held; Create updated briefing re-reads the OFP. ")
