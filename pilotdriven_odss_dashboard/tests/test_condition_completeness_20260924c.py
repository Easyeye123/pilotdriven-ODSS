"""CONDITION-COMPLETENESS-424 (independent production QA of release 424, 24 Sep 2026, F1).

Genuine SQ366 p85, VABF 1G803/26: "OPPORTUNITY BASED APPLICATION OF 10 MINUTES SEPARATION ON XNG TRACKS
SHALL BE APPLIED IN OCEANIC AIRSPACE OF MUMBAI FIR, ON TRIAL BASIS, BTN ADS-B EQUIPPED ACFT THAT ARE
CORRELATED WITH CPL USING SPACE BASED ADS-B AND IN POSITIVE CTC WITH MUMBAI OCEANIC CTL ON VHF/HF OR
CPDLC." Release 424 evaluated only the sentence's subject and its leading / trailing clauses, found none,
and labelled the row conditions held on date validity alone. The qualifications live in the body: the
aircraft population the provision applies to (ADS-B equipped, correlated with CPL, in positive contact),
none of which the OFP establishes.

The contract now: a positive applicability claim needs evidence for every relevant qualification of the
sentence; a qualification of the aircraft population anywhere in the sentence - a crew noun with a
restrictive modifier introduced by BTN / FOR / TO / OF / APPLICABLE TO / ONLY FOR - is evaluated like a
subject qualifier (equipment prefixes, aerodrome restrictions, evaluated FIR scopes) and everything else
about it stays an explicit unresolved condition. A sentence whose actor is ATC - a service, a separation, a
procedure applied or provided - is an ATC provision, labelled as such, not a required crew call. Ordinary
unconditional instructions, evaluated negative controls and object mentions without a modifier are unchanged.
No flight, notice, airport, phrase or expected outcome is special-cased; the controls rename everything.
"""
from __future__ import annotations

import pytest

from app.odss.enroute_contact import compose_enroute_contact, conditions_summary
from tests.test_atc_applicability_20260924 import genuine_flight, rows_by_id
from tests.test_atc_conditions_20260924b import action_starting, with_synthetic


def test_f1_the_genuine_provision_between_qualified_aircraft_is_not_held_on_dates_alone():
    row = rows_by_id(genuine_flight("SQ366"))["1G803/26"]
    assert row["applicability_state"] != "conditions_held", row["conditions"]
    unresolved = [c for c in row["conditions"] if c["result"] == "unresolved" and c["kind"] != "validity"]
    assert unresolved, row["conditions"]
    texts = " | ".join(c["text"] for c in unresolved)
    assert "ADS-B" in texts and ("CORRELATED WITH CPL" in texts or "POSITIVE CTC" in texts), texts
    assert row["actor"] == "atc", "a separation applied by ATC is an ATC provision, not a crew call"
    assert conditions_summary(row).startswith("ATC provision"), conditions_summary(row)


def test_f1_the_state_counts_move_with_the_row():
    composed = compose_enroute_contact(genuine_flight("SQ366"), [])
    counts = {state: sum(1 for r in composed["procedures"] if r["applicability_state"] == state) for state in ("conditions_held", "conditions_unresolved", "not_applicable")}
    assert f"printed conditions met on {counts['conditions_held']}, unresolved on {counts['conditions_unresolved']}, not applicable on {counts['not_applicable']}" in composed["state_sentence"]


def test_f1_synthetic_a_provision_between_qualified_aircraft_is_unresolved_on_each_qualification():
    text = ("CPDLC SEPARATION SHALL BE APPLIED IN ZONE OCEANIC AIRSPACE BTN FANS 1/A EQUIPPED ACFT THAT ARE LOGGED ON TO ZZZZ "
            "AND IN POSITIVE CTC WITH ZONE OCEANIC CTL ON HF.")
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-PROV/26", text))["SYN-PROV/26"]
    assert row["actor"] == "atc"
    assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
    kinds = {c["kind"] for c in row["conditions"] if c["result"] == "unresolved"}
    assert "equipment" in kinds and "qualifier" in kinds, row["conditions"]


def test_f1_synthetic_an_unconditional_provision_stays_held_and_is_still_an_atc_provision():
    text = "CPDLC SERVICE WILL BE PROVIDED BY ZONE CENTRE VIA LOGON ADDRESS ZZZZ."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-UNCOND/26", text))["SYN-UNCOND/26"]
    assert row["actor"] == "atc"
    assert row["applicability_state"] == "conditions_held", row["conditions"]
    assert {c["kind"] for c in row["conditions"]} == {"validity"}


def test_f1_synthetic_a_crew_instruction_for_an_evaluable_population_is_decided_not_guessed():
    flight = genuine_flight("SQ366")
    away = rows_by_id(with_synthetic(flight, "1G803/26", "SYN-AWAY/26", "CONTACT ZONE CONTROL ON 123.45 MHZ FOR ACFT DEPARTING RJTT."))["SYN-AWAY/26"]
    assert away["actor"] == "crew"
    assert away["applicability_state"] == "not_applicable", away["conditions"]
    home = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-HOME/26", "CONTACT ZONE CONTROL ON 123.45 MHZ FOR ACFT DEPARTING WSSS."))["SYN-HOME/26"]
    assert home["applicability_state"] == "conditions_held", home["conditions"]


def test_f1_synthetic_an_evaluated_fir_scope_in_the_body_adds_no_unresolved_condition():
    text = "CONTACT ZONE CONTROL ON 123.45 MHZ FOR ACFT OPERATING IN THE KABUL FIR."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-FIR/26", text))["SYN-FIR/26"]
    assert row["applicability_state"] == "conditions_held", row["conditions"]


def test_f1_synthetic_an_object_mention_without_a_modifier_is_not_a_qualification():
    text = "PILOTS SHALL CONTACT ZONE CONTROL ON 123.45 MHZ TO REPORT ANY ACFT WITHOUT A TRANSPONDER."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-OBJ/26", text))["SYN-OBJ/26"]
    assert row["actor"] == "crew"
    assert row["applicability_state"] == "conditions_held", row["conditions"]


def test_f1_synthetic_a_crew_instruction_qualified_in_its_body_stays_unresolved():
    text = "CONTACT ZONE CONTROL ON 123.45 MHZ 10 MIN BEFORE THE FIR BOUNDARY FOR ACFT UNABLE TO LOGON TO CPDLC."
    row = rows_by_id(with_synthetic(genuine_flight("SQ366"), "1G803/26", "SYN-BODY/26", text))["SYN-BODY/26"]
    assert row["actor"] == "crew"
    assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
    assert any(c["kind"] == "qualifier" and "UNABLE TO LOGON" in c["text"] for c in row["conditions"]), row["conditions"]


# ---------------------------------------------------------------- the actor label on genuine sentences that are not provisions

def test_f1_genuine_informational_sentences_about_the_crew_are_not_labelled_atc_provisions():
    rows = rows_by_id(genuine_flight("SQ366"))
    sup = rows["SX50/25"]
    assert sup["actor"] == "crew"
    call_sign = action_starting(sup, "THE CALL SIGN TO BE USED FOR AFN LOGON")
    assert call_sign["actor"] == "crew", "the crew's call sign is the crew's, not a service ATC provides"
    capability = next(a for a in sup["actions"] if "ARE ABLE TO HAVE UP TO FIVE ADS-C CONNECTIONS" in a["sentence"])
    assert capability["actor"] == "crew"
    initiated = next(a for a in sup["actions"] if a["sentence"].startswith("THE CPDLC CONNECTION IS INITIATED BY SENDING"))
    assert initiated["actor"] == "atc", "a connection the ATSU initiates is ATC's act"


def test_f1_genuine_a_service_endeavoured_by_atc_is_a_provision_but_the_crew_request_leads_the_row():
    from tests.test_atc_conditions_20260924b import genuine
    row = rows_by_id(genuine("SQ23"))["1A1531/26"]
    assert row["actor"] == "crew" and "ARE REQUESTED TO LOG ON" in row["instruction"]
    endeavoured = action_starting(row, "INCREASED CPDLC USAGE WILL BE ENDEAVOURED BY ATC")
    assert endeavoured["actor"] == "atc"
    assert conditions_summary(endeavoured).startswith("ATC provision")
    assert not conditions_summary(row).startswith("ATC provision")
