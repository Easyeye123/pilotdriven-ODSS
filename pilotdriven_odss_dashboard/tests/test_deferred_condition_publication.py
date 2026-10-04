"""A declaration's own conditions reach the download, and nothing else's does.

Independent review of the 19 Sep 2026 candidate. Printing a declaration's
identity is not enough when its physical condition or expiry is lost: the
download named CDL 57-16 and EN A35MEN-21-28871 but not "572HB seal found
torn", "573BB and 573DB seals found torn", "RCCB 1003HW tripped until 10 June
2027". The subject rule returned the first description line as soon as it
could stand alone and never read the line the form wrapped under it - which on
SQ214 19 Aug published "found RH aft nose landing gear" for a door seal that is
partially missing, and on SQ322 published the MEL item's title instead of
"lavatory LM46 nil flushing".

The other half of the same boundary problem is where a declaration ENDS. SQ24
15 Aug prints general dispatcher remarks (a ZFW restriction, an EDTO top-up
note, take-off performance inputs, the excess-fuel table) after a blank line
under its one CDL, and both parsers attached them all to the door seal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.odss.analysed_briefing_content import deferred_consequence_rows, deferred_source_subject
from app.odss.deferred_dispatch import build_deferred_dispatch_gates
from app.odss.parser import _parse_deferred_items, extract_pages
from tests.test_deferred_declaration_boundaries import SQ882_BLOCK

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"


def _subjects(block: str) -> dict[str, str]:
    """Each declaration's published subject, keyed by its sequence label."""
    items = _parse_deferred_items(block)
    subjects = {}
    for gate in build_deferred_dispatch_gates(items):
        for segment in gate["source_segments"]:
            label = str(items[segment["source_item_index"]]["source_declaration"])[:2]
            subjects[label] = deferred_source_subject(segment, gate["title"])
    return subjects


def _parse_page1_remarks(page: str):
    # Imported where used so the tests above still run - and fail on the
    # behaviour - against a build that predates the remarks domain.
    from app.odss.parser import _parse_page1_remarks as shared

    return shared(page)


def _folded(value: str) -> str:
    return " ".join(str(value or "").upper().split())


SQ214_BLOCK = """\
ATTN ALL CONCERN FR MAINTROL
EE IN SIA/00-003 R9
   MAINT ENTRY: BOTH VCRU (101HW & 103HW) REMOVED AS PER
   MAF 23224.
   REFER TO NPE SN: 070492. CB: 1001HW, 1003HW, 1005HW,
   1006HW, 3501HW,
   3503HW, 3505HW, 3506HW, 3507HW & 3509HW TRIPPED & TAGGED.
   SCS SYS NOT AVAILABLE.
   TO UPLIFT DRY ICE FOR ALL SECTOR.
FF CDL 53-66
   MAINT ENTRY: DURING WAC, FOUND RH AFT NOSE LANDING GEAR
   DOOR SEAL PARTIALLY MISSING

        PLAN 7/0/1
"""

SQ322_BLOCK = """\
AA MEL 25-21-50A - NON-ESSENTIAL EQUIPMENT AND FURNISHINGS
   MAINT ENTRY LAVATORY LM46 NIL FLUSHING
   LAV LM46
BB EN A380EN-38-29161
   MAINT ENTRY: REF EN A380EN-38-29161, DUE TO REPORTS OF
   WATER LEAKAGE
   INTO MAIN CABIN AND SUSPECTED DAMAGED U2R DRAIN TUBES,
   TO CARRY OUT TEMP SEALAGE OF FWD AND AFT FLOOR DRAIN PORTS
   ON U2R DOOR.
   TO INSPECT FWD AND AFT FLOOR DRAIN PORTS ON U2R DOOR
   FOR HST CONDITION AND WATER POOLING PRIOR TO EVERY
   DEPARTURE.
   TO REAPPLY HST IF NECESSARY AND CLEAN UP ANY WATER
CC CDL 27-27 - FLAP TRACK FAIRING LINK BRACKET SEAL
   MAINT ENTRY LH FLAP TRACK #5 FAIRING LINK BRACKET SEAL
   FOUND DAMAGED
   LH FLAP TRACK #5

         PLAN 77
"""

SQ24_PAGE = """\
REMARKS:
PLANNED ON COMPANY RTE SINJFK01 X

AA CDL 57-23 HINGED DOOR SEAL X HINGED DOOR SEAL AT RH FWD SIDE
   FOUND PARTIALLY MISSING X  MISSING DIM APPROX 5CM X

ZFW RESTRICTED TO 161,229KGS DUE MTOW X

EDTO TOP-UP UNAVOIDABLE X
DUE HIGH FUEL REQMT, PSE CHECK WITH LC EARLY FOR THE TRIM FUEL X

TAKEOFF PERF CALC WITH LPC AS FOLLOWS:
RWY: 20C; WIND: 160/08KT; OAT: 35; QNH: 1013;
RTOW(PERF) = 280,000KGS

EXCESS FUEL
1.INTAM  2464KGS ALL FLEETS-8980 (SUBJ. TO PAXLOAD)

        PLAN 12/0/1
RTE NO SINJFK01
"""


# ----------------------------------------------- the wrapped condition survives

@pytest.mark.parametrize(("label", "conditions"), [
    ("DD", ["AILERON TRAILING EDGE PANEL", "573BB AND 573DB SEALS FOUND TORN"]),
    ("EE", ["SLAT #6 LOWER SEAL FOUND DETERIORATED (QTY: 04 OFF)"]),
    ("FF", ["TRAILING EDGE ACCESS PANEL", "572HB SEAL FOUND TORN"]),
    ("GG", ["VCRU #3 DEACTIVATED", "RCCB 1003HW TRIPPED UNTIL 10 JUNE 2027"]),
    ("CC", ["O/B CUSHION SEAL FOUND WORN"]),
])
def test_sq882_each_declaration_publishes_its_whole_condition(label, conditions) -> None:
    subject = _folded(_subjects(SQ882_BLOCK)[label])

    for condition in conditions:
        assert condition in subject, (label, subject)


def test_a_condition_is_published_only_under_the_declaration_that_prints_it() -> None:
    subjects = {label: _folded(text) for label, text in _subjects(SQ882_BLOCK).items()}
    owners = {"573BB": "DD", "572HB": "FF", "1003HW": "GG", "10 JUNE 2027": "GG", "SLAT #6": "EE"}

    for phrase, owner in owners.items():
        for label, subject in subjects.items():
            assert (phrase in subject) == (label == owner), (phrase, label, subject)


def test_the_wrap_is_read_before_the_first_line_is_trusted() -> None:
    sq214 = _subjects(SQ214_BLOCK)
    sq322 = _subjects(SQ322_BLOCK)

    assert "DOOR SEAL PARTIALLY MISSING" in _folded(sq214["FF"])
    assert "LAVATORY LM46 NIL FLUSHING" in _folded(sq322["AA"])
    assert "FOUND DAMAGED" in _folded(sq322["CC"])
    # Later sentences that state a condition belong to the statement too.
    assert "TRIPPED & TAGGED" in _folded(sq214["EE"])
    assert "SCS SYS NOT AVAILABLE" in _folded(sq214["EE"])


def test_an_instruction_is_analysed_not_copied_into_the_subject() -> None:
    gg = _folded(_subjects(SQ882_BLOCK)["GG"])
    en = _folded(_subjects(SQ322_BLOCK)["BB"])
    notice = _folded(_subjects(SQ214_BLOCK)["EE"])

    assert "UPLIFT" not in gg and "UPLIFT" not in notice
    assert "SUSPECTED DAMAGED U2R DRAIN TUBES" in en
    assert "TO CARRY OUT" not in en and "TO INSPECT" not in en
    # ...and it is still represented, by its analysed consequence.
    rows = deferred_consequence_rows({"deferred_dispatch_gates": build_deferred_dispatch_gates(_parse_deferred_items(SQ882_BLOCK))})
    assert any("A35MEN-21-28871" in row["text"] and "dry-ice uplift" in row["text"] for row in rows)


def test_published_subjects_stay_readable_statements() -> None:
    for block in (SQ882_BLOCK, SQ214_BLOCK, SQ322_BLOCK):
        for label, subject in _subjects(block).items():
            assert subject, label
            assert subject == subject.strip() and subject[0].isalnum(), subject
            assert subject.rstrip(".")[-1] not in ",;:/-&+(", subject
            assert "MAINT ENTRY" not in subject.upper(), subject


# ----------------------------------------------------- where a declaration ends

def test_a_paragraph_break_ends_the_declaration() -> None:
    items = _parse_deferred_items(SQ24_PAGE)

    assert len(items) == 1
    assert items[0]["company_remark"] == "FOUND PARTIALLY MISSING X  MISSING DIM APPROX 5CM X"
    held = _folded(json.dumps(items[0]))
    for foreign in ("ZFW RESTRICTED", "EDTO TOP-UP", "TRIM FUEL", "TAKEOFF PERF", "RTOW(PERF)", "EXCESS FUEL", "INTAM"):
        assert foreign not in held, foreign


def test_general_remarks_are_held_in_their_own_domain_not_discarded() -> None:
    remarks = [row["text"] for row in _parse_page1_remarks(SQ24_PAGE)]

    assert "ZFW RESTRICTED TO 161,229KGS DUE MTOW X" in remarks
    assert "EDTO TOP-UP UNAVOIDABLE X" in remarks
    assert "DUE HIGH FUEL REQMT, PSE CHECK WITH LC EARLY FOR THE TRIM FUEL X" in remarks
    assert "PLANNED ON COMPANY RTE SINJFK01 X" in remarks
    # Nothing a declaration owns is repeated here.
    assert not any("HINGED DOOR SEAL" in text or "PARTIALLY MISSING" in text for text in remarks)


def test_an_indented_line_after_a_gap_still_continues_its_declaration() -> None:
    items = _parse_deferred_items(
        "AA MEL 21-26-08A\n   DM VENT AVNCS FILTER CLOGGED\n\n   FILTER CHANGE DEFERRED TO NEXT A-CHECK\n\nGENERAL NOTE X\n        PLAN 1\n"
    )

    assert items[0]["company_remark"] == "FILTER CHANGE DEFERRED TO NEXT A-CHECK"


def test_a_declaration_after_general_remarks_is_still_a_declaration() -> None:
    items = _parse_deferred_items(
        "AA MEL 21-26-08A\n   DM VENT AVNCS FILTER CLOGGED\n\nGENERAL NOTE X\n\nBB CDL 57-23\n   SEAL TORN\n        PLAN 1\n"
    )

    assert [item["source_declaration"] for item in items] == ["AA MEL 21-26-08A", "BB CDL 57-23"]
    assert "GENERAL NOTE" not in json.dumps(items)


def test_the_zfw_restriction_is_published_as_the_ofps_remark_not_as_the_door_seals() -> None:
    from app.odss.analysed_briefing_content import page1_remark_consequences

    items = _parse_deferred_items(SQ24_PAGE)
    rows = deferred_consequence_rows({
        "deferred_dispatch_gates": build_deferred_dispatch_gates(items),
        "fuel_summary": {"masses_kg": {"pzfw": 161800}},
    })
    door_seal = " ".join(row["text"] for row in rows)
    remark_lines = page1_remark_consequences(
        _parse_page1_remarks(SQ24_PAGE), {"masses_kg": {"pzfw": 161800}},
    )

    assert "ZFW" not in door_seal
    assert remark_lines == [
        "OFP remark: ZFW restricted to 161,229 kg. Planned ZFW 161,800 kg gives -571 kg margin."
    ]


# ------------------------------------------------------------ the real download

def test_real_sq882_download_prints_every_condition_under_its_owner(tmp_path) -> None:
    import fitz

    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.parser import parse_lido

    source = CORPUS / "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"
    if not source.is_file():
        pytest.skip("private source for SQ882 10 Sep not available")
    flight = parse_lido(extract_pages(source), source.name)
    flight["briefing"] = build_briefing_view(flight, [], [])
    path = tmp_path / "download.pdf"
    render_combined_briefing(flight, [], [], path, source_pdf_path=source)
    with fitz.open(path) as document:
        technical = _folded(document[2].get_text())

    for condition in ("573BB AND 573DB SEALS FOUND TORN", "572HB SEAL FOUND TORN", "RCCB 1003HW TRIPPED UNTIL 10 JUNE 2027"):
        assert technical.count(condition) == 1, condition
    # Ownership on the page: each condition sits after its own identity and
    # before the next declaration's.
    assert technical.index("57-16") < technical.index("572HB")
    assert technical.index("A35MEN-21-28871") < technical.index("1003HW") < technical.index("10 JUNE 2027")


# ------------------------------------------- the copy gate still guards the page

def _gate_inputs():
    items = _parse_deferred_items(SQ882_BLOCK)
    view = {"deferred_dispatch_gates": build_deferred_dispatch_gates(items)}
    return items, view


def test_gate_admits_a_wrapped_defect_line_only_in_its_own_statement() -> None:
    from app.odss.concise_pdf_gate import PERFORMANCE_PAGE, _wrapped_defect_statement_is_published

    items, view = _gate_inputs()
    own = ("CDL 27-25 / 57-16: LH wing, aileron trailing edge panel 573BB and 573DB seals found torn LH wing; "
           "LH wing, trailing edge access panel 572HB seal found torn LH wing. Reconcile this deferred external component.")

    assert _wrapped_defect_statement_is_published(own, PERFORMANCE_PAGE, items[3], 3, view) is True


@pytest.mark.parametrize("page", [
    # Block capitals: a copy of the source cell, not a statement.
    "CDL 27-25: LH wing, aileron trailing edge panel 573BB AND 573DB SEALS FOUND TORN LH WING. Reconcile.",
    # Not after its own description: attached to another declaration.
    "CDL 27-06: LH wing, slat #6 lower seal found 573BB and 573DB seals found torn LH wing. Reconcile.",
    # Twice on the page.
    "CDL 27-25: LH wing, aileron trailing edge panel 573BB and 573DB seals found torn LH wing. "
    "Again: LH wing, aileron trailing edge panel 573BB and 573DB seals found torn LH wing.",
])
def test_gate_still_refuses_a_copied_or_misplaced_remark(page) -> None:
    from app.odss.concise_pdf_gate import PERFORMANCE_PAGE, _wrapped_defect_statement_is_published

    items, view = _gate_inputs()

    assert _wrapped_defect_statement_is_published(page, PERFORMANCE_PAGE, items[3], 3, view) is False


def test_gate_never_admits_an_instruction_block_as_a_statement() -> None:
    from app.odss.concise_pdf_gate import PERFORMANCE_PAGE, _wrapped_defect_statement_is_published

    items = _parse_deferred_items(
        "AA MEL 25-20-50A\n   GALLEY CHILLER NOT COLD\n   CHECK FILTER AND INSPECT DUCT BEFORE EVERY DEPARTURE WITHOUT FAIL\nPLAN 1\n"
    )
    view = {"deferred_dispatch_gates": build_deferred_dispatch_gates(items)}
    page = "MEL 25-20-50A: Galley chiller not cold check filter and inspect duct before every departure without fail."

    assert _wrapped_defect_statement_is_published(page, PERFORMANCE_PAGE, items[0], 0, view) is False


def test_real_sq24_download_publishes_the_zfw_remark_in_the_mass_domain(tmp_path) -> None:
    import fitz

    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.parser import parse_lido

    source = CORPUS / "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf"
    if not source.is_file():
        pytest.skip("private source for SQ24 15 Aug not available")
    flight = parse_lido(extract_pages(source), source.name)
    assert "ZFW RESTRICTED" not in _folded(json.dumps(flight["deferred_items"]))
    assert any("ZFW RESTRICTED TO 161,229KGS" in row["text"] for row in flight["page1_remarks"])
    flight["briefing"] = build_briefing_view(flight, [], [])
    path = tmp_path / "download.pdf"
    render_combined_briefing(flight, [], [], path, source_pdf_path=source)
    with fitz.open(path) as document:
        technical = " ".join(document[2].get_text().split())

    assert "OFP remark: ZFW restricted to 161,229 kg." in technical
    assert "gives -571 kg margin" in technical
    door_seal = technical.split("CDL 57-23", 1)[1].split("RECONCILIATION", 1)[0]
    assert "ZFW" not in door_seal, door_seal
    assert "missing DIM approx 5CM" in door_seal or "MISSING DIM APPROX 5CM" in door_seal.upper()


# ------------------------------------------------ what a statement is made of

def test_a_dashed_header_title_is_the_manuals_heading_and_the_body_is_the_defect() -> None:
    subjects = _subjects(
        "AA MEL 30-81-01A - ICE DETECTION SYSTEM\n   ECAM A-ICE ICE DET FAULT\n"
        "BB MEL 25-20-50A - NON-ESSENTIAL EQUIPMENT AND FURNISHINGS\n   JCL GALLEY 2 AIR CHILLER NOT WORKING\n   TO UPLIFT DRY ICE\n"
        "CC CDL 57-23 - HINGED DOOR SEAL\n   HINGED DOOR RUBBER SEAL TORN 6 INCHES\n   L/H MAIN L/G\n"
        "DD MEL 25-20-50A LAV L53 TOILET BOWL NIL WATER\n"
        "EE CDL 38-05 - DRAINAGE PIPE\n"
        "        PLAN 1\n"
    )

    assert _folded(subjects["AA"]) == "ECAM A-ICE ICE DET FAULT"
    assert _folded(subjects["BB"]) == "JCL GALLEY 2 AIR CHILLER NOT WORKING"
    assert _folded(subjects["CC"]) == "HINGED DOOR RUBBER SEAL TORN 6 INCHES L/H MAIN L/G"
    # Undashed words on the label line ARE the defect; a bare title with no
    # body is all the OFP printed, so it is what is published.
    assert _folded(subjects["DD"]) == "LAV L53 TOILET BOWL NIL WATER"
    assert _folded(subjects["EE"]) == "DRAINAGE PIPE"


def test_a_later_sentence_is_kept_when_it_states_a_condition_and_analysed_when_it_asks_for_action() -> None:
    subjects = _subjects(
        "DD IN SIA/00-017 R1\n"
        "   ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE.\n"
        "   HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE\n"
        "   TO APPLY WHENEVER NECESSARY\n"
        "        PLAN 3\n"
    )
    notice = _folded(_subjects(SQ214_BLOCK)["EE"])

    assert _folded(subjects["DD"]) == "ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE."
    assert notice.startswith("BOTH VCRU (101HW & 103HW) REMOVED AS PER MAF 23224.")
    assert "CB: 1001HW" in notice and "3509HW TRIPPED & TAGGED." in notice and notice.endswith("SCS SYS NOT AVAILABLE.")


def test_a_bare_form_class_field_is_not_part_of_the_defect() -> None:
    subjects = _subjects("AA MEL 25-21-05A\n   SEAT 12A OUTSIDE ARMREST EXTEND STUCK\n   CLASS B\n        PLAN 1\n")

    assert _folded(subjects["AA"]) == "SEAT 12A OUTSIDE ARMREST EXTEND STUCK"


def test_gate_binds_a_dashed_title_declarations_body_to_its_identity() -> None:
    # SQ365 7 Aug: the label line carries the manual item's title, the defect
    # is the body, and the page prints "CDL 38-05: <body>".
    from app.odss.concise_pdf_gate import ANALYSIS_PAGE, PERFORMANCE_PAGE, _wrapped_defect_statement_is_published

    items = _parse_deferred_items(
        "BB CDL 38-05 - DRAINAGE PIPE\n   RERAISED FROM PREVIOUS DDL #M003961, APU DRAINAGE PIPE MISSING.\n        PLAN 1\n"
    )
    from app.odss.analysed_briefing_content import deferred_consequence_rows

    view = {"deferred_dispatch_gates": build_deferred_dispatch_gates(items)}
    # R2: the analysis page prints "<subject> <consequence> SOURCE ..." with no
    # "dispatch confirmation" suffix, and the gate binds the body through its
    # own analysed row, exactly as the production view carries it.
    view["deferred_pdf_analysis"] = deferred_consequence_rows(view)
    row = next(row for row in view["deferred_pdf_analysis"] if 0 in row["source_item_indices"])
    technical = "CDL 38-05: Reraised from previous DDL #M003961, APU drainage pipe missing. Reconcile this deferred external component."
    decision = "MODERATE " + row["subject"].rstrip(" .;") + " " + " ".join(row["consequences"])
    elsewhere = "CDL 57-23: Reraised from previous DDL #M003961, APU drainage pipe missing. Reconcile."

    assert _wrapped_defect_statement_is_published(technical, PERFORMANCE_PAGE, items[0], 0, view) is True
    assert _wrapped_defect_statement_is_published(decision, ANALYSIS_PAGE, items[0], 0, view) is True
    assert _wrapped_defect_statement_is_published(elsewhere, PERFORMANCE_PAGE, items[0], 0, view) is False


def test_gate_binds_a_dashed_title_body_inside_a_row_shared_with_other_declarations() -> None:
    # SQ910 15 Aug: CC and DD share one consequence, so the page prints
    # "CDL 27-23; CDL 57-21: <CC statement>; <DD statement>. Reconcile ...".
    from app.odss.analysed_briefing_content import deferred_consequence_rows
    from app.odss.concise_pdf_gate import PERFORMANCE_PAGE, _wrapped_defect_statement_is_published

    items = _parse_deferred_items(
        "CC CDL 27-23 - AILERON END SEAL\n   LH WING INBOARD AILERON INBOARD END SEAL FOUND DAMAGED\n   X PERFORMANCE [P]\n"
        "DD CDL 57-21 - FTE PANEL 3 SEAL\n   LH WING FTE PANEL 3 SEAL WITH 5CM OF MISSING MATERIAL.\n        PLAN 1\n"
    )
    view = {"deferred_dispatch_gates": build_deferred_dispatch_gates(items)}
    view["deferred_pdf_analysis"] = deferred_consequence_rows(view)
    page = " ".join(row["text"] for row in view["deferred_pdf_analysis"])

    assert "LH wing FTE panel 3 seal with 5CM of missing material" in page
    assert _wrapped_defect_statement_is_published(page, PERFORMANCE_PAGE, items[1], 1, view) is True
    # The same words under a row that does not own them are still refused.
    foreign = "MEL 21-26-08A: LH wing FTE panel 3 seal with 5CM of missing material. The declaration does not establish."
    assert _wrapped_defect_statement_is_published(foreign, PERFORMANCE_PAGE, items[1], 1, view) is False


def test_a_negative_imperative_is_a_request_not_part_of_the_defect() -> None:
    # SQ910 15 Aug: "BOTH SIDE VACUUM GENERATOR INOP DO NOT USE LAVATORIES ON
    # GROUND." The restriction is published by its analysed consequence.
    items = _parse_deferred_items(
        "BB MEL 25-20-50A - NON-ESSENTIAL EQUIPMENT AND NEF\n   BOTH SIDE VACUUM GENERATOR INOP DO NOT USE LAVATORIES ON GROUND.\n        PLAN 1\n"
    )
    gates = build_deferred_dispatch_gates(items)
    subject = deferred_source_subject(gates[0]["source_segments"][0], gates[0]["title"])
    row = deferred_consequence_rows({"deferred_dispatch_gates": gates})[0]["text"]

    assert _folded(subject) == "BOTH SIDE VACUUM GENERATOR INOP"
    assert "Ground turnaround must avoid using the affected lavatories" in row
