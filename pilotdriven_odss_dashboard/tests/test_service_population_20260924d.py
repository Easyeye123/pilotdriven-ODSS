"""SERVICE-POPULATION-428 (independent QA of release 428, 24 Sep 2026, F1).

Genuine SQ366 p67, SX50/25: "ADS-C/CPDLC TRIAL SERVICES WILL INITIALLY BE AVAILABLE TO FANS 1/A, PACKAGE
AIRCRAFT WITHIN JAKARTA FIR ON ALL ATS ROUTES WITHIN THE INDIAN OCEANIC UPPER CONTROL AREA (UIOS), …". The
service is restricted to a qualified population (FANS 1/A package aircraft, on stated routes) and the OFP
establishes none of it; release 428 returned actor crew, conditions held, validity only, for three reasons:
the population grammar demanded a modifier AFTER the aircraft noun (a qualifying prefix alone fell through),
the source's AIP SUP reference folded into the sentence made it a "fragment" for the actor test, and the strict
passive expected an adjacent "WILL BE".

The contract now: (1) a qualification-bearing PREFIX on a population noun (equipment, flight rules) is a
qualification by itself, with or without a modifier after the noun; (2) a source provenance block (an AIP SUP /
NOTAM reference with its validity) is set aside for the sentence's grammatical analysis only - the printed
sentence keeps the source wording - so the actor and the population are read from the sentence itself;
(3) a service passive tolerates adverbs ("WILL INITIALLY BE AVAILABLE"), a sentence whose agent is the crew
("… BY ALL AIRCRAFT") is the crew's, and an uncertain actor stays the crew's (never "ATC provision" by
default). No notice, flight, punctuation, adverb or expected count is special-cased; the controls rename.
"""
from __future__ import annotations

import pytest

from app.odss.enroute_contact import compose_enroute_contact, conditions_summary
from tests.test_atc_applicability_20260924 import genuine_flight, rows_by_id
from tests.test_atc_conditions_20260924b import action_starting, with_synthetic


def action_containing(row: dict, needle: str) -> dict:
    found = [a for a in row["actions"] if needle in a["sentence"]]
    assert found, f"{row['notam_id']}: no action contains {needle!r}"
    return found[0]


def test_f1_the_genuine_jakarta_service_population_is_not_held_on_dates_alone():
    row = rows_by_id(genuine_flight("SQ366"))["SX50/25"]
    action = action_containing(row, "TRIAL SERVICES WILL INITIALLY BE AVAILABLE")
    assert action["actor"] == "atc", action
    assert action["applicability_state"] == "conditions_unresolved", action["conditions"]
    equipment = [c for c in action["conditions"] if c["kind"] == "equipment" and c["result"] == "unresolved"]
    assert equipment and "FANS 1/A" in equipment[0]["text"], action["conditions"]
    assert conditions_summary(action).startswith("ATC provision")
    # The printed sentence keeps the source wording, provenance included; the row still leads with the crew's logon duty.
    assert action["sentence"].startswith("SX0050/25 AIP SUPPLEMENT")
    assert row["actor"] == "crew" and "REQUIRED TO MANUALLY LOGON" in row["instruction"]


def test_f1_synthetic_a_qualifying_prefix_alone_is_a_population_qualification():
    provided = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-PREFIX/26", "CPDLC SERVICE WILL BE PROVIDED FOR ADS-B EQUIPPED ACFT."))["SYN-PREFIX/26"]
    assert provided["actor"] == "atc"
    assert provided["applicability_state"] == "conditions_unresolved", provided["conditions"]
    assert any(c["kind"] == "equipment" and "ADS-B" in c["text"] for c in provided["conditions"]), provided["conditions"]
    everyone = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-ALL/26", "CPDLC SERVICE WILL BE PROVIDED TO ALL ACFT."))["SYN-ALL/26"]
    assert everyone["actor"] == "atc"
    assert everyone["applicability_state"] == "conditions_held", everyone["conditions"]
    rules = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-RULES/26", "CONTACT ZONE CONTROL ON 123.45 MHZ FOR VFR FLIGHTS."))["SYN-RULES/26"]
    assert rules["actor"] == "crew"
    assert any(c["kind"] == "flight_rules" and c["result"] == "unresolved" for c in rules["conditions"]), rules["conditions"]


def test_f1_synthetic_an_adverb_inside_the_passive_still_reads_as_a_provision():
    text = "CPDLC SERVICE WILL NORMALLY BE AVAILABLE TO IFR FLIGHTS WITHIN ZONE FIR."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-ADVERB/26", text))["SYN-ADVERB/26"]
    assert row["actor"] == "atc"
    kinds = {(c["kind"], c["result"]) for c in row["conditions"]}
    assert ("flight_rules", "unresolved") in kinds, row["conditions"]
    assert not any(c["kind"] == "qualifier" for c in row["conditions"]), "an evaluated FIR scope adds no unresolved qualifier"


def test_f1_synthetic_a_source_provenance_block_changes_nothing_but_the_printed_sentence():
    body = "CPDLC TRIAL SERVICES WILL INITIALLY BE AVAILABLE TO FANS 1/A, PACKAGE AIRCRAFT WITHIN ZONE FIR."
    with_ref = "SX0001/26 AIP SUPPLEMENT ZZZZ/ZONE FIR VALIDITY: 01JAN26 - 31DEC26 CPDLC TRIAL WI ZONE FIR " + body
    bare = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-BARE/26", body))["SYN-BARE/26"]
    referenced = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-REF/26", with_ref))["SYN-REF/26"]
    for row in (bare, referenced):
        assert row["actor"] == "atc", row
        assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
        assert any(c["kind"] == "equipment" and "FANS 1/A" in c["text"] for c in row["conditions"]), row["conditions"]
    non_validity = lambda row: sorted((c["kind"], c["text"], c["result"]) for c in row["conditions"] if c["kind"] != "validity")
    assert non_validity(bare) == non_validity(referenced)
    assert referenced["instruction"].startswith("SX0001/26 AIP SUPPLEMENT"), "the source wording is printed as held"


def test_f1_synthetic_a_crew_agent_keeps_a_passive_sentence_the_crews():
    text = "TIBA PROCEDURES SHALL BE APPLIED BY ALL AIRCRAFT ON TIBA FREQ 125.2MHZ WHEN CROSSING THE FIR BOUNDARY."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-AGENT/26", text))["SYN-AGENT/26"]
    assert row["actor"] == "crew", row
    assert not conditions_summary(row).startswith("ATC provision")
