"""The corpus gate has to be able to see what no parser extracted.

Production audit, 19 Sep 2026: release-30's 28-flight corpus and publication
parity gates passed while SQ882 lost two declarations and SIA605 described one
notice two ways. Every expectation those gates held was minted from the
analysis itself - the pinned ``deferred_items`` count for SQ882 10 Sep was 5
because the parser produced 5 - so an item the parser never extracted was
absent from both sides of every comparison, and no check compared two
statements about the same notice with each other.
"""
from __future__ import annotations

from scripts.run_private_cfp_corpus import (
    check_notam_statement_consistency,
    check_source_declaration_coverage,
    source_declaration_labels,
)

PAGE_ONE = """\
REMARKS:
ATTN ALL CONCERN FR MAINTROL
AA MEL 25-20-50A
   MAINT ENTRY
213/214 AIR CHILLER NOT COLD
EE CDL 27-06
   MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND
   EE BAY ALSO CHECKED
FF CDL 57-16
   572HB SEAL FOUND TORN
GG EN A35MEN-21-28871
   UPLIFT DRY ICE FOR ALL CHILLERS

        PLAN 8
RTE NO SINHKG01
BB NDB 365 ROUTE NOTE
"""


def _item(declaration, item_type, reference):
    return {"source_declaration": declaration, "item_type": item_type, "reference": reference}


def test_source_labels_are_read_from_the_page_not_from_the_parser() -> None:
    assert source_declaration_labels(PAGE_ONE) == [
        "AA MEL 25-20-50A", "EE CDL 27-06", "FF CDL 57-16", "GG EN A35MEN-21-28871",
    ]


def test_a_declaration_the_parser_never_extracted_fails_the_gate() -> None:
    # What release-30 held for this page: FF and GG folded into EE.
    flight = {"deferred_items": [_item("AA MEL 25-20-50A", "MEL", "25-20-50A"), _item("EE CDL 27-06", "CDL", "27-06")]}
    failures = check_source_declaration_coverage(PAGE_ONE, flight, "MEL 25-20-50A ... CDL 27-06 ...")

    assert any("FF CDL 57-16" in failure and "not held" in failure for failure in failures)
    assert any("GG EN A35MEN-21-28871" in failure and "not held" in failure for failure in failures)


def test_a_held_declaration_absent_from_the_download_fails_the_gate() -> None:
    flight = {"deferred_items": [
        _item("AA MEL 25-20-50A", "MEL", "25-20-50A"), _item("EE CDL 27-06", "CDL", "27-06"),
        _item("FF CDL 57-16", "CDL", "57-16"), _item("GG EN A35MEN-21-28871", "EN", "A35MEN-21-28871"),
    ]}
    failures = check_source_declaration_coverage(PAGE_ONE, flight, "MEL 25-20-50A; CDL 27-06; EN A35MEN-21-28871")

    assert failures == ["FF CDL 57-16: identity 57-16 is printed nowhere in the download."]


def test_complete_extraction_and_publication_passes() -> None:
    flight = {"deferred_items": [
        _item("AA MEL 25-20-50A", "MEL", "25-20-50A"), _item("EE CDL 27-06", "CDL", "27-06"),
        _item("FF CDL 57-16", "CDL", "57-16"), _item("GG EN A35MEN-21-28871", "EN", "A35MEN-21-28871"),
    ]}
    text = "MEL 25-20-50A; CDL 27-06; CDL 27-25 / 57-16; EN A35MEN-21-28871"

    assert check_source_declaration_coverage(PAGE_ONE, flight, text) == []


def test_an_opaque_group_holds_every_label_it_names() -> None:
    page = "AA SEAT 21A TRAY TABLE UNABLE TO STOW\n   X CLASS B\n   ECDL007905\nBB SEAT 21A TRAY TABLE UNABLE TO STOW\n   X CLASS B\nPLAN 1\n"
    flight = {"deferred_items": [{
        "source_declaration": "AA SEAT 21A TRAY TABLE UNABLE TO STOW", "item_type": "UNCLASSIFIED",
        "reference": "ECDL007905", "source_group_tokens": ["AA", "BB"],
    }]}

    assert check_source_declaration_coverage(page, flight, "DEFERRED ITEM ECDL007905") == []


# ----------------------------------------------------------- one notice, one story

def _view(summary, compact, consequence):
    return {
        "airport_operational_panels": [{"icao": "WSSS", "selected_notams": [
            {"notam_id": "SX120/25", "role": "destination", "summary": summary, "compact_text": compact},
        ], "card_summary_lines": [{"kind": "notam", "notam_id": "SX120/25", "text": compact}]}],
        "airport_pdf_analysis": [{"icao": "WSSS", "role": "destination", "lines": [
            {"notam_ids": ["SX120/25"], "state": "scheduled", "consequence": consequence,
             "text": f"{consequence} (SX120/25)"},
        ]}],
        "decision_findings": [{"title": "Destination NOTAM SX120/25", "summary": summary}],
    }


RESOLVED = "RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure. Planned RWY 20R differs from this affected runway."
UNRESOLVED = "Published RWY 02L/20R restriction could not be resolved for the applicable destination window; review required."


def test_release_30s_sia605_view_is_refused() -> None:
    conflicts = check_notam_statement_consistency(_view(UNRESOLVED, UNRESOLVED, RESOLVED), [])

    assert conflicts and all("SX120/25" in conflict for conflict in conflicts)


def test_a_single_story_passes_and_keeps_its_open_review() -> None:
    summary = RESOLVED + " Other scheduled clauses in this notice are not evaluated; review required."

    assert check_notam_statement_consistency(_view(summary, RESOLVED, RESOLVED), []) == []


def test_the_physical_download_is_read_too() -> None:
    pages = [
        "PERTINENT RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure. (SX120/25)",
        "MAJOR Destination NOTAM SX120/25 Published RWY 02L/20R restriction could not be resolved for the applicable destination window; review required. SOURCE",
    ]
    summary = RESOLVED

    conflicts = check_notam_statement_consistency(_view(summary, RESOLVED, RESOLVED), pages)

    assert conflicts == ["SX120/25: download page 2 calls the notice unresolved while the Airports analysis evaluates it."]


def test_the_oracle_reads_past_a_remark_that_begins_with_the_word_plan() -> None:
    page = (
        "REMARKS:\nPLAN VIA PACOTS TRK 2\n\nPLAN WITH PACKS OFF\n\n"
        "ATTN ALL CONCERN FR MAINTROL\nAA CDL 57-23 - HINGED DOOR SEAL\n   TORN 6 INCHES\n\n"
        "        PLAN 27/0/1\nRTE NO SINLAXT2\nBB MEL 99-99-99A NEVER\n"
    )

    assert source_declaration_labels(page) == ["AA CDL 57-23 - HINGED DOOR SEAL"]
