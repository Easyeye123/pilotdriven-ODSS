"""ATC-CONDITIONS-ATTACHMENT-422 (independent production QA of release 422, 24 Sep 2026, F1).

Release 422 attached a sentence's own leading clause only when the sentence's
grammatical subject was one of the recognised crew subjects, and let a sentence
without such a subject borrow the nearest earlier crew subject's qualifiers.
Two genuine consequences: 1G216/26 (Kabul FIR, printed on SQ366 p88 and SQ23
p108) says IN THE EVENT OF EMERGENCY DESCENT before its broadcast instruction,
whose subject is "THE PROCEDURES IN ICAO DOC 4444 ... APPLY"; the clause was
dropped and the action labelled conditions held. 1A44/24 (Anchorage, SQ24 p84)
says AFTER LOGON, ARTCC AUTOMATION WILL PROVIDE ...; the clause was dropped and
the sentence inherited WI VHF COVERAGE from an earlier sentence about aircraft.

The contract now: a sentence's own leading and trailing clauses belong to that
sentence whatever its subject; a sentence with a subject of its own - a crew
subject, or another actor such as ATC, a centre or its automation - borrows
nothing; only a sentence that continues the governing crew sentence (no subject
of its own, or a subject naming the crew's own communication act: notification,
contact, logon, report, request, call, broadcast, message, transmission) takes
the governing sentence's qualifiers. The ordinary overflight instruction of the
same notice keeps its held state. No flight, notice, airport or answer is
special-cased; the synthetic controls rename everything.
"""
from __future__ import annotations

import pytest

from app.odss.enroute_contact import compose_enroute_contact
from tests.test_atc_applicability_20260924 import genuine_flight, rows_by_id

SOURCES_B = {"SQ23": "SQ02325072026JFK.pdf"}


def genuine(key: str) -> dict:
    if key in ("SQ24", "SQ366"):
        return genuine_flight(key)
    from tests.test_atc_applicability_20260924 import CORPUS, _FLIGHTS
    from app.odss.parser import extract_pages, parse_lido
    import copy
    if key not in _FLIGHTS:
        source = CORPUS / SOURCES_B[key]
        if not source.is_file():
            pytest.skip(f"private CFP corpus file {SOURCES_B[key]} is not available")
        _FLIGHTS[key] = parse_lido(extract_pages(source), source.name)
    return copy.deepcopy(_FLIGHTS[key])


def action_starting(row: dict, prefix: str) -> dict:
    found = [a for a in row["actions"] if a["sentence"].startswith(prefix)]
    assert found, f"{row['notam_id']}: no action starts with {prefix!r}: {[a['sentence'][:60] for a in row['actions']]}"
    return found[0]


def with_synthetic(flight: dict, template_id: str, new_id: str, text: str) -> dict:
    records = []
    for record in flight["notam_procedure_records"]:
        if record.get("notam_id") == template_id:
            records.append({**record, "notam_id": new_id, "text": text})
        else:
            records.append(record)
    flight["notam_procedure_records"] = records
    return flight


# ---------------------------------------------------------------- the reviewer's genuine cases

@pytest.mark.parametrize("key", ["SQ366", "SQ23"])
def test_f1_the_emergency_descent_clause_stays_with_its_own_sentence(key: str):
    row = rows_by_id(genuine(key))["1G216/26"]
    emergency = action_starting(row, "IN THE EVENT OF EMERGENCY DESCENT,")
    assert emergency["applicability_state"] != "conditions_held", emergency["conditions"]
    assert any(c["result"] == "unresolved" and "EMERGENCY DESCENT" in c["text"] for c in emergency["conditions"]), emergency["conditions"]
    # The ordinary overflight instruction of the same notice is a separate action and keeps its held state.
    routine = action_starting(row, "ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE")
    assert routine["applicability_state"] == "conditions_held", routine["conditions"]
    assert {c["kind"] for c in routine["conditions"]} == {"validity", "scope"}
    assert row["instruction"] == routine["sentence"] and row["applicability_state"] == "conditions_held"


def test_f1_a_sentence_about_another_actor_keeps_its_own_clause_and_borrows_none():
    row = rows_by_id(genuine("SQ24"))["1A44/24"]
    action = action_starting(row, "AFTER LOGON,")
    assert any(c["result"] == "unresolved" and "AFTER LOGON" in c["text"] for c in action["conditions"]), action["conditions"]
    assert not any("WI VHF COVERAGE" in c["text"] for c in action["conditions"]), action["conditions"]
    assert action["applicability_state"] == "conditions_unresolved"


def test_f1_the_governing_trigger_still_reaches_the_notification_that_continues_it():
    row = rows_by_id(genuine("SQ24"))["1A1136/25"]
    notification = action_starting(row, "NOTIFICATION SHOULD BE VIA CPDLC")
    assert any("EXPERIENCE OR SUSPECT GNSS INTERFERENCE" in c["text"] and c["result"] == "unresolved" for c in notification["conditions"])


# ---------------------------------------------------------------- source-independent controls (renamed ids, airports, actors)

def test_f1_synthetic_another_actor_with_its_own_clause_stands_alone():
    text = ("IF UNABLE TO ESTABLISH CONTACT, ZONE CONTROL WILL ADVISE AN ALTERNATIVE FREQUENCY. "
            "ALL ACFT SHALL CONTACT ZONE CONTROL ON 123.45 MHZ 10 MIN BEFORE ENTERING THE FIR.")
    row = rows_by_id(with_synthetic(genuine("SQ24"), "1A44/24", "SYN-ACTOR/26", text))["SYN-ACTOR/26"]
    other = action_starting(row, "IF UNABLE TO ESTABLISH CONTACT,")
    assert any(c["kind"] == "qualifier" and c["text"] == "IF UNABLE TO ESTABLISH CONTACT" and c["result"] == "unresolved" for c in other["conditions"])
    crew = action_starting(row, "ALL ACFT SHALL CONTACT")
    assert crew["applicability_state"] == "conditions_held", crew["conditions"]
    assert row["instruction"] == crew["sentence"]


def test_f1_synthetic_a_continuation_naming_the_crews_own_act_inherits_the_governing_qualifier():
    text = ("ACFT EXPERIENCING RADIO FAILURE MUST CONTACT ZONE CONTROL ON 121.5 MHZ. "
            "CALLS SHALL BE MADE ON 128.5 MHZ EVERY 5 MINUTES. THE CPDLC SERVICE WILL BE PROVIDED BY ZONE CENTRE VIA LOGON ADDRESS ZZZZ.")
    row = rows_by_id(with_synthetic(genuine("SQ24"), "1A44/24", "SYN-CONT/26", text))["SYN-CONT/26"]
    continuation = action_starting(row, "CALLS SHALL BE MADE")
    assert any("EXPERIENCING RADIO FAILURE" in c["text"] and c["result"] == "unresolved" for c in continuation["conditions"]), continuation["conditions"]
    service = action_starting(row, "THE CPDLC SERVICE WILL BE PROVIDED")
    assert not any("RADIO FAILURE" in c["text"] for c in service["conditions"]), service["conditions"]
    assert service["applicability_state"] == "conditions_held"


def test_f1_synthetic_an_evaluated_departure_restriction_reaches_only_its_continuation():
    text = ("ALL ACFT DEPARTING RJTT SHALL LOGON TO RJJJ BEFORE FL200. "
            "LOGON SHALL BE COMPLETED BEFORE FL200. THE CPDLC SERVICE WILL BE PROVIDED BY TOKYO CONTROL VIA LOGON ADDRESS RJJJ.")
    flight = with_synthetic(genuine("SQ24"), "1A44/24", "SYN-DEPT/26", text)
    row = rows_by_id(flight)["SYN-DEPT/26"]
    first = action_starting(row, "ALL ACFT DEPARTING RJTT")
    assert first["applicability_state"] == "not_applicable" and any(c["kind"] == "departure" and c["result"] == "not_met" for c in first["conditions"])
    logon = action_starting(row, "LOGON SHALL BE COMPLETED")
    assert logon["applicability_state"] == "not_applicable", logon["conditions"]
    service = action_starting(row, "THE CPDLC SERVICE WILL BE PROVIDED")
    assert service["applicability_state"] == "conditions_held", service["conditions"]


def test_f1_synthetic_a_crew_sentence_with_a_leading_clause_keeps_both_its_clause_and_its_qualifier():
    text = "WHEN INSTRUCTED BY ATC, FANS 1/A EQUIPPED ACFT SHALL LOGON TO ZONE CENTRE WI 10 MIN OF ENTERING THE FIR."
    row = rows_by_id(with_synthetic(genuine("SQ24"), "1A44/24", "SYN-BOTH/26", text))["SYN-BOTH/26"]
    action = row["actions"][0]
    kinds = {(c["kind"], c["text"]) for c in action["conditions"]}
    assert ("equipment", "FANS 1/A EQUIPPED") in kinds or ("equipment", "FANS 1/A") in kinds, kinds
    assert any(kind in ("qualifier", "atc_request") and "INSTRUCTED" in text for kind, text in kinds), kinds
    assert action["applicability_state"] == "conditions_unresolved"
