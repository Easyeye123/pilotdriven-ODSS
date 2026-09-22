"""SQ352 EKCH — three real notices whose scope was lost on the way to publication.

Independent live QA of release 392 and its candidate review, 22 Sep 2026. The
source is the real OFP page 36 of
`private_cfp_corpus/lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf`; every raw
string below is quoted from it.

The three defects were the reason page 1 published nothing for a destination
whose closures page 2 listed. Fixing the wording of the empty state was not
enough: the scope had to survive the classifiers.
"""
from __future__ import annotations

from app.odss.airport_pdf_analysis import _complete_runway_closures
from app.odss.engines import (
    _extent_end_text,
    _further_taxiway_extents,
    _notam_subject,
    _BOUNDED_TAXIWAY_EXTENT,
)

A1380 = "DAILY 0400-1600 RWY 12/30 CLSD FOR TKOF AND LDG DUE TO WIP."
A1312 = "RWY 22L CAT II/III OPS NOT AVBL DUE TO WIP."
A1383 = (
    "FOLLOWING TWY ARE CLSD DUE TO WIP:\n"
    "TWY B BTN TWY Y AND RWY 12/30.\n"
    "TWY Y BTN TWY B AND DEICING PLATFORM B.\n"
    "TWY Z BTN TWY D AND DEICING PLATFORM B."
)


def test_a_closure_naming_its_movements_is_recognised_and_keeps_them() -> None:
    scopes, unresolved = _complete_runway_closures(A1380)
    assert unresolved is False, "the clause is complete and must not fall to unresolved"
    assert scopes == {"closed for take-off and landing": ["12/30"]}


def test_an_unscoped_closure_still_reads_as_it_did() -> None:
    scopes, unresolved = _complete_runway_closures("RWY 12/30 CLSD DUE TO WIP.")
    assert unresolved is False
    assert scopes == {"closed to the affected movement": ["12/30"]}


def test_a_movement_scope_this_cannot_read_is_not_stripped() -> None:
    """An unknown qualifier keeps the notice unresolved rather than losing it."""
    scopes, unresolved = _complete_runway_closures("RWY 12/30 CLSD FOR SOMETHING ELSE.")
    assert scopes == {}
    assert unresolved is True


def test_a_category_limitation_keeps_its_category_and_its_scope() -> None:
    subject = _notam_subject(A1312, "approach_navaid_closure")
    assert subject == "RWY 22L CAT II/III operations"
    # Not a broader subject, and not a component outage.
    assert "approach/navaid" not in subject
    assert "ILS" not in subject


def test_a_named_aid_outage_is_unchanged_by_the_category_rule() -> None:
    assert _notam_subject("ILS RWY 22L U/S DUE TO WIP.", "approach_navaid_closure") == "ILS RWY 22L"
    assert _notam_subject("RWY 22L APCH LGT U/S.", "approach_navaid_closure") == "approach/navaid RWY 22L"


def test_an_extent_ending_at_a_runway_keeps_the_designator() -> None:
    subject = _notam_subject(A1383, "taxiway_closure")
    assert subject == "TWY B between Y and RWY 12/30"
    assert not subject.endswith("RWY"), "an extent that ends nowhere is worse than none"


def test_an_extent_ending_at_a_named_place_keeps_the_place() -> None:
    match = _BOUNDED_TAXIWAY_EXTENT.search("TWY Y BTN TWY B AND DEICING PLATFORM B.")
    assert match is not None
    assert _extent_end_text(match) == "DEICING PLATFORM B"


def test_a_taxiway_to_taxiway_extent_reads_as_before() -> None:
    assert _notam_subject("TWY B BTN TWY Y AND TWY Z CLSD.", "taxiway_closure") == "TWY B between Y and Z"


def test_the_extents_a_notice_states_beyond_the_first_are_counted() -> None:
    assert _further_taxiway_extents(A1383) == 2
    assert _further_taxiway_extents("TWY B BTN TWY Y AND TWY Z CLSD.") == 0
