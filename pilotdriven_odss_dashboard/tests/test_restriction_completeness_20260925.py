"""RESTRICTION-COMPLETENESS-430 (independent QA of release 430, 25 Sep 2026, F1).

Genuine SQ366 pp67-68, SX50/25: "CPDLC WILL BE USED AS COMMUNICATION WITHIN UBAC ON THE ROUTE PORTION M300, ... AND
UBND UTA ON THE ROUTE PORTION A585, ... AND R206 BEYOND VOICE VHF COVERAGE;" was held on its validity alone. The
cause was not one missing phrase: every condition came from a recognizer for one grammatical position (the subject,
a population connector, a leading or trailing WHEN / IF clause), and the state was then computed as if that list
were complete. Anything in another position - a sector, a route portion, a coverage limit, DURING / DRG, ONLY AFTER,
an equipment population behind a section heading - vanished before the state was decided.

The contract now (rule enroute-contact-v7, both readers): an action's own sentence is ACCOUNTED FOR before its state
is computed. Every restrictive phrase in it is either consumed by an evaluated condition (validity, FIR scope,
direction, route, aerodrome, population, level), typed as non-restrictive (a printed frequency, lead or address, a
means such as VIA CPDLC / ON VHF, a manner or reference such as IN ACCORDANCE WITH / IN ITEM 18, a reason such as
AS THE GROUND SYSTEM USES ..., a role such as AS COMMUNICATION, a duration such as UNTIL), or kept as an explicit
unresolved restriction quoting the source. A named FIR scope is evaluated against the crossings the OFP prints; a
sub-area of a FIR is not the FIR. The leading-clause vocabulary includes the ICAO abbreviation DRG. A NOTAM's printed
vertical limits are a notice-level condition evaluated from the planned levels. No flight, notice, route, phrase or
expected count is special-cased: the synthetic cases rename the notice, reorder, abbreviate and re-punctuate, and the
unconditional controls must stay held.
"""
from __future__ import annotations

import re

import pytest

from app.odss.enroute_contact import classify_text, compose_enroute_contact, condition_phrase, conditions_summary
from tests.test_atc_applicability_20260924 import genuine_flight, rows_by_id
from tests.test_atc_conditions_20260924b import action_starting, genuine, with_synthetic


def action_containing(row: dict, needle: str) -> dict:
    found = [a for a in row["actions"] if needle in a["sentence"]]
    assert found, f"{row['notam_id']}: no action contains {needle!r}: {[a['sentence'][:60] for a in row['actions']]}"
    return found[0]


def restrictions(action: dict) -> list[dict]:
    return [c for c in action["conditions"] if c["kind"] == "restriction"]


def unresolved_beyond_validity(action: dict) -> list[dict]:
    return [c for c in action["conditions"] if c["kind"] != "validity" and c["result"] == "unresolved"]


def synthetic(text: str, new_id: str = "SYN-SCOPE/26") -> dict:
    """The reviewer's method: a genuine SQ366 notice (VABF 1G803/26, crossed, valid) renamed and re-worded."""
    return rows_by_id(with_synthetic(genuine("SQ366"), "1G803/26", new_id, text))[new_id]


# ---------------------------------------------------------------- the genuine F1 sentence and its siblings


def test_f1_the_genuine_sector_route_and_coverage_limited_cpdlc_sentence_is_not_held_on_dates_alone():
    row = rows_by_id(genuine("SQ366"))["SX50/25"]
    action = action_containing(row, "BEYOND VOICE VHF COVERAGE")
    assert action["sentence"].startswith("CPDLC WILL BE USED AS COMMUNICATION WITHIN UBAC"), "the source wording is printed as held"
    assert action["applicability_state"] == "conditions_unresolved", action["conditions"]
    assert action["conditions"][0]["kind"] == "validity" and action["conditions"][0]["result"] == "met"
    quoted = " | ".join(c["text"] for c in restrictions(action))
    for part in ("WITHIN UBAC", "ON THE ROUTE PORTION M300", "UBND UTA", "ON THE ROUTE PORTION A585", "R206", "BEYOND VOICE VHF COVERAGE"):
        assert part in quoted, (part, quoted)
    assert all(c["result"] == "unresolved" for c in restrictions(action))
    assert "not evaluable from the OFP" in conditions_summary(action)
    # The row still leads with the crew's manual-logon duty (the ranking does not read the state).
    assert row["actor"] == "crew" and "REQUIRED TO MANUALLY LOGON" in row["instruction"]


def test_f1_the_genuine_secondary_communication_sentence_keeps_its_sector_and_route_restriction():
    action = action_containing(rows_by_id(genuine("SQ366"))["SX50/25"], "AS SECONDARY COMMUNICATION WITHIN UIOS")
    assert action["applicability_state"] == "conditions_unresolved", action["conditions"]
    quoted = " | ".join(c["text"] for c in restrictions(action))
    assert "WITHIN UIOS" in quoted and "ON THE ROUTE PORTION L774" in quoted and "N633" in quoted, quoted


def test_f1_genuine_operational_prerequisites_in_other_positions_are_explicit():
    row = rows_by_id(genuine("SQ366"))["SX50/25"]
    only_after = action_containing(row, "CAN ONLY OCCUR AFTER THE AFN LOGON HAS BEEN COMPLETED")
    assert only_after["applicability_state"] == "conditions_unresolved", only_after["conditions"]
    assert any("AFTER THE AFN LOGON HAS BEEN COMPLETED" in c["text"] for c in restrictions(only_after)), only_after["conditions"]
    during = action_containing(row, "DURING THE CPDLC CONNECTION TRANSFER PROCESS")
    assert during["applicability_state"] == "conditions_unresolved", during["conditions"]
    assert any(c["text"].startswith("DURING THE CPDLC CONNECTION TRANSFER PROCESS") for c in restrictions(during)), during["conditions"]
    # An equipment population behind a section heading ("CONNECTION OF ADS-C A. FANS-1/A EQUIPPED AIRCRAFT ARE ...").
    fans = action_containing(row, "FANS-1/A EQUIPPED AIRCRAFT ARE ABLE TO HAVE UP TO FIVE")
    assert fans["applicability_state"] == "conditions_unresolved", fans["conditions"]
    assert any(c["kind"] == "equipment" and "FANS-1/A" in c["text"] and c["result"] == "unresolved" for c in fans["conditions"]), fans["conditions"]


def test_f1_a_named_fir_scope_is_evaluated_from_the_crossings_not_assumed():
    jakarta = action_containing(rows_by_id(genuine("SQ366"))["SX50/25"], "THE AFN LOGON FOR JAKARTA FIR IS WIII")
    scope = [c for c in jakarta["conditions"] if c["kind"] == "fir_scope"]
    assert scope and scope[0]["result"] == "met" and "WIIF" in condition_phrase(scope[0]), jakarta["conditions"]
    assert jakarta["applicability_state"] == "conditions_held"
    paza = rows_by_id(genuine_flight("SQ24"))["1A173/26"]
    entry = [c for c in paza["conditions"] if c["kind"] == "fir_scope"]
    assert entry and entry[0]["result"] == "met" and "PAZA" in condition_phrase(entry[0]), paza["conditions"]
    assert paza["applicability_state"] == "conditions_held"


def test_f1_an_area_of_responsibility_is_a_restriction_of_an_atc_provision():
    action = action_containing(rows_by_id(genuine("SQ23"))["1A1531/26"], "INCREASED CPDLC USAGE WILL BE ENDEAVOURED BY ATC")
    assert action["actor"] == "atc"
    assert action["applicability_state"] == "conditions_unresolved", action["conditions"]
    assert any("IN THE AREA OF RESPONSIBILITY OF ACC WIEN AND APP LOWW" in c["text"] for c in restrictions(action)), action["conditions"]


def test_f1_an_exception_runs_to_the_directive_modal_of_the_clause_it_qualifies():
    row = rows_by_id(genuine("SQ23"))["1G220/26"]
    assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
    assert [c["text"] for c in restrictions(row)] == ["AT FL320-FL510 EXCEPT ON M875/L509 ROUTES"], row["conditions"]


# ---------------------------------------------------------------- the SQ23 audit candidate (SX33/26 p110)


def test_audit_the_kabul_ats_nonavailability_prerequisite_is_an_explicit_unresolved_condition():
    row = rows_by_id(genuine("SQ23"))["SX33/26"]
    assert "DRG THE NON AVAILABILITY OF ATS (ATS) IN KABUL FIR" in row["instruction"]
    prerequisite = [c for c in row["conditions"] if "NON AVAILABILITY OF ATS" in c["text"]]
    assert prerequisite and prerequisite[0]["result"] == "unresolved", row["conditions"]
    direction = [c for c in row["conditions"] if c["kind"] == "direction"]
    assert direction and direction[0]["result"] == "met", row["conditions"]
    assert row["actor"] == "crew"
    assert row["applicability_state"] == "conditions_unresolved", row["conditions"]
    # On SQ366 (the other direction) the same notice stays not applicable: a failed condition still decides.
    other = rows_by_id(genuine("SQ366"))["SX33/26"]
    assert other["applicability_state"] == "not_applicable"
    assert any("NON AVAILABILITY OF ATS" in c["text"] for c in other["conditions"]), other["conditions"]


# ---------------------------------------------------------------- notice vertical limits (item F/G printed at the end)


def test_f1_a_notices_printed_vertical_limits_are_evaluated_from_the_planned_levels():
    mumbai = rows_by_id(genuine("SQ366"))["1G803/26"]
    limits = [c for c in mumbai["conditions"] if c["kind"] == "level" and "FL260" in c["text"] and "FL460" in c["text"]]
    assert limits and limits[0]["result"] == "met", mumbai["conditions"]
    anchorage = rows_by_id(genuine_flight("SQ24"))
    for notice in ("1A44/24", "1A1136/25"):
        limits = [c for c in anchorage[notice]["conditions"] if c["kind"] == "level" and c["text"].startswith("FROM SFC")]
        assert limits and limits[0]["result"] == "met", anchorage[notice]["conditions"]


# ---------------------------------------------------------------- synthetic: position, order, abbreviation, punctuation

RESTRICTED = [
    ("coverage in the predicate (the reviewer's)", "CPDLC SHALL BE USED BEYOND VOICE VHF COVERAGE."),
    ("coverage, other opener", "CPDLC SHALL BE USED OUTSIDE VHF COVERAGE."),
    ("sector code, ICAO abbreviation WI", "CPDLC SHALL BE USED WI UIOS."),
    ("coverage first, then the action", "BEYOND VHF COVERAGE, CPDLC SHALL BE USED."),
    ("coverage inside the verb group", "CPDLC SHALL, BEYOND VHF COVERAGE, BE USED."),
    ("semicolon, no stop", "CPDLC WILL BE USED BEYOND VOICE VHF COVERAGE;"),
    ("lower case, no punctuation", "cpdlc shall be used beyond voice vhf coverage"),
    ("route list", "CPDLC SHALL BE USED ON THE ROUTE PORTION L774, L896 AND N633."),
    ("route designators", "CPDLC SHALL BE USED ON L774 AND M300."),
    ("area noun", "CPDLC SHALL BE USED IN THE UIOS SECTOR."),
    ("bare area code", "CPDLC SHALL BE USED IN UIOS."),
    ("level, abbreviation ABV", "CPDLC SHALL BE USED ABV FL290."),
    ("during, abbreviation DRG, trailing", "CPDLC SHALL BE USED DRG ATS NON AVAILABILITY."),
    ("during, abbreviation DRG, leading", "DRG ATS NON AVAILABILITY, CPDLC SHALL BE USED."),
    ("while", "CPDLC SHALL BE USED WHILE IN OCEANIC AIRSPACE."),
    ("exception, abbreviation EXC", "CPDLC SHALL BE USED EXC ON ROUTE L774."),
    ("time window", "CPDLC SHALL BE USED BTN 2200 AND 0600."),
    ("latitude sub-area", "CPDLC SHALL BE USED S OF 73N."),
    ("only after (prerequisite)", "CPDLC CAN ONLY BE USED AFTER AFN LOGON."),
    ("emergency circumstance", "CPDLC SHALL BE USED IN EMERGENCY."),
    ("sub-area of a crossed FIR", "CPDLC SHALL BE USED IN OCEANIC AIRSPACE OF MUMBAI FIR."),
    ("population class prefix", "NON-RVSM ACFT SHALL CONTACT ZONE CONTROL ON 123.45 MHZ."),
    ("a temporal AS with a copula is a circumstance, not a reason", "CONTACT ZONE CONTROL ON 123.45 MHZ AS THE AIRCRAFT IS WITHIN VHF COVERAGE."),
]


@pytest.mark.parametrize("label,text", RESTRICTED, ids=[label for label, _ in RESTRICTED])
def test_f1_synthetic_a_restriction_in_any_position_is_never_held_on_validity_alone(label: str, text: str):
    row = synthetic(text)
    assert row["applicability_state"] == "conditions_unresolved", (label, row["conditions"])
    assert unresolved_beyond_validity(row), (label, row["conditions"])


HELD = [
    ("the reviewer's unconditional control", "CPDLC SHALL BE USED."),
    ("frequency and lead", "CONTACT MUMBAI CONTROL ON 132.7 MHZ 10 MIN BEFORE ENTERING THE FIR."),
    ("manner", "CPDLC SHALL BE USED IN ACCORDANCE WITH COMPANY PROCEDURES."),
    ("means", "CPDLC SHALL BE USED VIA SATCOM OR HF."),
    ("every route", "CPDLC SHALL BE USED ON ALL ATS ROUTES."),
    ("role", "CPDLC SHALL BE USED AS THE PRIMARY MEANS OF COMMUNICATION."),
    ("purpose", "CPDLC SHALL BE USED FOR POSITION REPORTS."),
    ("always", "CPDLC SHALL BE USED AT ALL TIMES."),
    ("duration", "CPDLC SHALL BE USED UNTIL FURTHER NOTICE."),
    ("reason clause", "AIRCRAFT REGISTRATION MUST BE INSERTED IN ITEM 18 AS THE GROUND SYSTEM USES IT DURING CPDLC LOGON."),
    ("the notice's own crossed FIR, named", "CPDLC SHALL BE USED WITHIN MUMBAI FIR."),
]


@pytest.mark.parametrize("label,text", HELD, ids=[label for label, _ in HELD])
def test_f1_synthetic_non_restrictive_wording_stays_held(label: str, text: str):
    row = synthetic(text)
    assert row["applicability_state"] == "conditions_held", (label, row["conditions"])
    assert not restrictions(row), (label, row["conditions"])


def test_f1_synthetic_a_named_fir_the_route_does_not_cross_is_not_applicable_and_an_unknown_one_is_unresolved():
    elsewhere = synthetic("CPDLC SHALL BE USED WITHIN BANGKOK FIR.")
    scope = [c for c in elsewhere["conditions"] if c["kind"] == "fir_scope"]
    assert scope and scope[0]["result"] == "not_met" and "VTBB" in condition_phrase(scope[0]), elsewhere["conditions"]
    assert elsewhere["applicability_state"] == "not_applicable"
    unknown = synthetic("CPDLC SHALL BE USED WITHIN ATLANTIS FIR.")
    scope = [c for c in unknown["conditions"] if c["kind"] == "fir_scope"]
    assert scope and scope[0]["result"] == "unresolved", unknown["conditions"]
    assert unknown["applicability_state"] == "conditions_unresolved"


def test_f1_synthetic_a_source_provenance_block_changes_nothing_but_the_printed_sentence():
    body = "CPDLC WILL BE USED AS COMMUNICATION WITHIN SECTOR ONE ON THE ROUTE PORTION A1, B2 BEYOND VOICE VHF COVERAGE;"
    bare = synthetic(body, "SYN-BARE/26")
    referenced = synthetic("SX9999/26 AIP SUPPLEMENT VABF/MUMBAI FIR VALIDITY: 01JAN26 - 31DEC26 " + body, "SYN-REF/26")
    non_validity = lambda row: sorted((c["kind"], c["text"], c["result"]) for c in row["conditions"] if c["kind"] != "validity")
    assert non_validity(bare) == non_validity(referenced), (bare["conditions"], referenced["conditions"])
    assert bare["applicability_state"] == referenced["applicability_state"] == "conditions_unresolved"


# ---------------------------------------------------------------- the accounting is complete on the genuine corpus

_ALWAYS_RESTRICTIVE = re.compile(r"\b(?:WITHIN|WI|INSIDE|OUTSIDE|BEYOND|DURING|DRG|WHILE|WHEN|WHENEVER|IF|UNLESS|WHERE|WHEREVER|EXCEPT|EXC)\b\s+\S+")
# The one deliberate exclusion, stated here independently of the code: a causal clause qualifies nothing it contains
# ("... INSERTED IN ITEM 18 AS THE GROUND SYSTEM USES THE INFORMATION DURING AFN LOGON").
_CAUSAL_CLAUSE = re.compile(r"\b(?:BECAUSE|DUE TO|OWING TO|AS (?:THE|THIS|IT|THEY)\s+(?:[A-Z/-]+\s+){0,3}?(?:USES|REQUIRES|NEEDS))\b[^.;,]*")


@pytest.mark.parametrize("key", ["SQ366", "SQ23"])
def test_f1_no_held_genuine_action_leaves_an_always_restrictive_phrase_outside_its_conditions(key: str):
    """Independent of the accounting code: in a held action, every always-restrictive opener (with the word after it)
    is quoted by one of the action's own conditions or by its printed lead; otherwise the restriction vanished."""
    record = compose_enroute_contact(genuine(key), [])
    held = [a for row in record["procedures"] for a in row["actions"] if a["applicability_state"] == "conditions_held"]
    assert held, "the genuine flight holds some unconditional actions"
    for action in held:
        quoted = [c["text"] for c in action["conditions"]] + [action["printed_details"].get("lead") or ""]
        upper = _CAUSAL_CLAUSE.sub("", classify_text(action["sentence"]))
        for match in _ALWAYS_RESTRICTIVE.finditer(upper):
            window = " ".join(match.group(0).split())
            assert any(window in text for text in quoted), (window, action["sentence"], action["conditions"])
