from __future__ import annotations

from app.odss.deferred_dispatch import build_deferred_dispatch_gates
from app.odss.parser import _parse_deferred_items


SQ481_PAGE_ONE_DEFERRED_BLOCK = """\
SINGAPORE AIRLINES - SUMMARY STANDARD CFP
REMARKS:
AA SEAT 21A TRAY TABLE UNABLE TO STOW
   X CLASS B
   ECDL007905
BB SEAT 21A TRAY TABLE UNABLE TO STOW
   X CLASS B
PLAN 12/0/1
RTE NO JNBSIN A350-941
"""


def test_sq481_opaque_ecdl_block_is_one_source_grouped_unresolved_entry() -> None:
    items = _parse_deferred_items(SQ481_PAGE_ONE_DEFERRED_BLOCK)

    assert len(items) == 1
    item = items[0]
    assert item["item_type"] == "UNCLASSIFIED"
    assert item["reference"] == "ECDL007905"
    assert item["source_identifier"] == "ECDL007905"
    assert item["description"] == "SEAT 21A TRAY TABLE UNABLE TO STOW"
    assert item["company_remark"] == "X CLASS B"
    assert item["classification_status"] == "unresolved"
    assert item["governed_match_status"] == "manual_review_required"
    assert item["source_group_tokens"] == ["AA", "BB"]
    assert item["source_page"] == 1
    assert item["source_line_start"] == 3
    assert item["source_line_end"] == 7
    assert item["source_lines"] == [
        {"line_number": 3, "text": "AA SEAT 21A TRAY TABLE UNABLE TO STOW"},
        {"line_number": 4, "text": "X CLASS B"},
        {"line_number": 5, "text": "ECDL007905"},
        {"line_number": 6, "text": "BB SEAT 21A TRAY TABLE UNABLE TO STOW"},
        {"line_number": 7, "text": "X CLASS B"},
    ]
    assert item["deferred_entry_id"].startswith("ofp-deferred-")
    assert len(item["deferred_entry_id"]) == len("ofp-deferred-") + 20


def test_opaque_ecdl_shape_does_not_guess_a_mel_or_cdl_item() -> None:
    item = _parse_deferred_items(SQ481_PAGE_ONE_DEFERRED_BLOCK)[0]

    assert item["item_type"] not in {"MEL", "CDL", "CDDL"}
    assert "25-21-08" not in str(item)


def test_opaque_deferred_identity_is_repeatable_and_source_position_bounded() -> None:
    first = _parse_deferred_items(SQ481_PAGE_ONE_DEFERRED_BLOCK)[0]
    repeated = _parse_deferred_items(SQ481_PAGE_ONE_DEFERRED_BLOCK)[0]
    shifted = _parse_deferred_items(
        "ADDITIONAL SOURCE LINE\n" + SQ481_PAGE_ONE_DEFERRED_BLOCK
    )[0]

    assert first["deferred_entry_id"] == repeated["deferred_entry_id"]
    assert first["deferred_entry_id"] != shifted["deferred_entry_id"]


def test_sq481_unresolved_entry_keeps_audit_provenance_in_dispatch_projection() -> None:
    item = _parse_deferred_items(SQ481_PAGE_ONE_DEFERRED_BLOCK)[0]

    gates = build_deferred_dispatch_gates([item])

    assert len(gates) == 1
    assert gates[0]["title"] == "DEFERRED ITEM ECDL007905"
    assert gates[0]["status"] == "dispatch-confirmation-required"
    segment = gates[0]["source_segments"][0]
    assert segment["deferred_entry_id"] == item["deferred_entry_id"]
    assert segment["classification_status"] == "unresolved"
    assert segment["governed_match_status"] == "manual_review_required"
    assert segment["source_line_start"] == 3
    assert segment["source_line_end"] == 7
    assert segment["source_lines"] == item["source_lines"]
