from __future__ import annotations

import pytest

from app.odss.governed_deferred_extract import (
    governed_deferred_extracts,
    normalize_governed_deferred_reference_payload,
)


ACTIVE_FLIGHT = {
    "registration": "9V-SMA",
    "aircraft_type": "A350-941",
}


def _citation(*, section: str, page: str = "125") -> dict:
    return {
        "sourceClass": "company_manual",
        "documentTitle": "SIA A350 MEL",
        "version": "Revision 39",
        "effectiveDate": "2025-11-18",
        "page": page,
        "section": section,
        "safeTarget": "/api/help-you/references/ref-test/open?page=125",
        "applicability": {
            "scope": "specified",
            "fleet": "LH",
            "aircraft": "A350-941",
            "status": "confirmed",
        },
    }


def test_exact_current_governed_reference_binds_to_printed_mel_item() -> None:
    items = [{
        "item_type": "MEL",
        "reference": "25-20-50A",
        "description": "GALLEY CHILLER",
    }]
    payload = {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-20-50A permits dispatch under the conditions below.",
            "citation": _citation(section="MEL 25-20-50A"),
        }],
    }

    extracts = governed_deferred_extracts(items, payload)

    assert len(extracts) == 1
    assert extracts[0]["source_item_index"] == 0
    assert extracts[0]["match_status"] == "exact"
    assert extracts[0]["item_type"] == "MEL"
    assert extracts[0]["reference"] == "25-20-50A"
    assert extracts[0]["revision"] == "Revision 39"
    assert extracts[0]["effective_date"] == "2025-11-18"
    assert extracts[0]["page"] == "125"
    assert extracts[0]["effectivity"] == "LH / A350-941 - CONFIRMED"


def test_exact_binding_rejects_wrong_reference_or_incomplete_effectivity() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    wrong_reference = {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-20-50B permits dispatch.",
            "citation": _citation(section="MEL 25-20-50B"),
        }],
    }
    incomplete_effectivity = {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-20-50A permits dispatch.",
            "citation": {
                **_citation(section="MEL 25-20-50A"),
                "applicability": {"status": "review_required"},
            },
        }],
    }

    assert governed_deferred_extracts(items, wrong_reference) == []
    assert governed_deferred_extracts(items, incomplete_effectivity) == []


def test_exact_binding_rejects_duplicate_source_items_instead_of_choosing_first() -> None:
    items = [
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "deferred_entry_id": "ofp-deferred-entry-one",
        },
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "deferred_entry_id": "ofp-deferred-entry-two",
        },
    ]
    payload = {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-20-50A permits dispatch under the conditions below.",
            "citation": _citation(section="MEL 25-20-50A"),
        }],
    }

    assert governed_deferred_extracts(items, payload) == []
    with pytest.raises(ValueError, match="does not bind to an exact deferred declaration"):
        normalize_governed_deferred_reference_payload(
            items,
            payload,
            flight=ACTIVE_FLIGHT,
        )


@pytest.mark.parametrize("scope", ["", "free_text_scope", "operator_defined"])
def test_normalized_storage_rejects_non_contract_applicability_scope(scope: str) -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    citation = _citation(section="MEL 25-20-50A")
    citation["applicability"] = {
        **citation["applicability"],
        "scope": scope,
    }

    with pytest.raises(ValueError, match="incomplete or does not bind"):
        normalize_governed_deferred_reference_payload(
            items,
            {
                "status": "available",
                "references": [{
                    "excerpt": "MEL 25-20-50A exact controlled extract.",
                    "citation": citation,
                }],
            },
            flight=ACTIVE_FLIGHT,
        )


def test_all_operations_applicability_rejects_conflicting_aircraft_constraints() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    citation = _citation(section="MEL 25-20-50A")
    citation["applicability"] = {
        "scope": "all_operations",
        "fleet": "LH",
        "aircraft": None,
        "status": "confirmed",
    }

    with pytest.raises(ValueError, match="incomplete or does not bind"):
        normalize_governed_deferred_reference_payload(
            items,
            {
                "status": "available",
                "references": [{
                    "excerpt": "MEL 25-20-50A exact controlled extract.",
                    "citation": citation,
                }],
            },
            flight=ACTIVE_FLIGHT,
        )


def test_unresolved_sq481_entry_accepts_only_explicit_governed_candidates() -> None:
    items = [{
        "item_type": "UNCLASSIFIED",
        "reference": "ECDL007905",
        "deferred_entry_id": "ofp-deferred-sq481",
        "classification_status": "unresolved",
        "description": "SEAT 21A TRAY TABLE UNABLE TO STOW",
    }]
    candidate = lambda suffix: {
        "excerpt": (
            f"MEL 25-21-08{suffix} Passenger Seat Meal Table - exact controlled extract."
        ),
        "citation": _citation(
            section=f"MEL 25-21-08{suffix}",
            page="221",
        ),
        "deferredBinding": {
            "deferredEntryId": "ofp-deferred-sq481",
            "matchStatus": "candidate",
            "itemType": "MEL",
            "reference": f"25-21-08{suffix}",
            "ambiguityReason": (
                "The OFP does not state whether the tray table blocks a cabin door."
            ),
            "confirmationRequired": (
                "Confirm the Tech Log door-access condition before selecting B or C."
            ),
        },
    }
    payload = {
        "status": "available",
        "references": [candidate("B"), candidate("C")],
    }

    extracts = governed_deferred_extracts(items, payload)

    assert [extract["reference"] for extract in extracts] == [
        "25-21-08B",
        "25-21-08C",
    ]
    assert {extract["match_status"] for extract in extracts} == {"candidate"}
    assert all(extract["source_item_index"] == 0 for extract in extracts)
    assert all(extract["ambiguity_reason"] for extract in extracts)
    assert all(extract["confirmation_required"] for extract in extracts)


def test_unresolved_entry_never_binds_from_similarity_without_explicit_candidate() -> None:
    items = [{
        "item_type": "UNCLASSIFIED",
        "reference": "ECDL007905",
        "deferred_entry_id": "ofp-deferred-sq481",
        "classification_status": "unresolved",
        "description": "SEAT 21A TRAY TABLE UNABLE TO STOW",
    }]
    payload = {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-21-08B Passenger Seat Meal Table.",
            "citation": _citation(section="MEL 25-21-08B", page="221"),
        }],
    }

    assert governed_deferred_extracts(items, payload) == []


def test_duplicate_reference_is_rendered_only_once() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    reference = {
        "excerpt": "MEL 25-20-50A exact controlled extract.",
        "citation": _citation(section="MEL 25-20-50A"),
    }

    extracts = governed_deferred_extracts(
        items,
        {"status": "available", "references": [reference, reference]},
    )

    assert len(extracts) == 1


def test_normalized_storage_payload_keeps_only_the_closed_governed_contract() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    raw = {
        "excerpt": "MEL 25-20-50A exact controlled extract.",
        "citation": {
            **_citation(section="MEL 25-20-50A"),
            "untrustedExtra": "must not persist",
        },
        "untrustedExtra": "must not persist",
    }

    normalized = normalize_governed_deferred_reference_payload(
        items,
        {"status": "available", "references": [raw]},
        flight=ACTIVE_FLIGHT,
    )

    assert normalized == {
        "status": "available",
        "references": [{
            "excerpt": "MEL 25-20-50A exact controlled extract.",
            "citation": {
                "sourceClass": "company_manual",
                "documentTitle": "SIA A350 MEL",
                "version": "Revision 39",
                "effectiveDate": "2025-11-18",
                "page": "125",
                "section": "MEL 25-20-50A",
                "safeTarget": "/api/help-you/references/ref-test/open?page=125",
                "applicability": {
                    "scope": "specified",
                    "fleet": "LH",
                    "aircraft": "A350-941",
                    "status": "confirmed",
                },
            },
        }],
    }


def test_normalized_storage_rechecks_applicability_against_active_flight() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    raw = {
        "excerpt": "MEL 25-20-50A exact controlled extract.",
        "citation": _citation(section="MEL 25-20-50A"),
    }

    with pytest.raises(ValueError, match="active flight applicability"):
        normalize_governed_deferred_reference_payload(
            items,
            {"status": "available", "references": [raw]},
            flight={
                "registration": "9V-SHA",
                "aircraft_type": "B787-10",
            },
        )


def test_normalized_storage_accepts_explicit_governance_withdrawal() -> None:
    normalized = normalize_governed_deferred_reference_payload(
        [],
        {"status": "unavailable", "references": []},
        flight=ACTIVE_FLIGHT,
    )

    assert normalized == {"status": "unavailable", "references": []}
    with pytest.raises(ValueError, match="must contain no entries"):
        normalize_governed_deferred_reference_payload(
            [],
            {
                "status": "unavailable",
                "references": [{"untrusted": "stale"}],
            },
            flight=ACTIVE_FLIGHT,
        )


def test_normalized_storage_rejects_a_mixed_valid_and_similarity_only_payload() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    valid = {
        "excerpt": "MEL 25-20-50A exact controlled extract.",
        "citation": _citation(section="MEL 25-20-50A"),
    }
    similarity_only = {
        "excerpt": "MEL 25-20-50B similar but different extract.",
        "citation": _citation(section="MEL 25-20-50B"),
    }

    with pytest.raises(ValueError, match="reference 2 is incomplete"):
        normalize_governed_deferred_reference_payload(
            items,
            {
                "status": "available",
                "references": [valid, similarity_only],
            },
            flight=ACTIVE_FLIGHT,
        )


def test_normalized_storage_drops_an_external_source_target() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    raw = {
        "excerpt": "MEL 25-20-50A exact controlled extract.",
        "citation": {
            **_citation(section="MEL 25-20-50A"),
            "safeTarget": "https://attacker.example/manual",
        },
    }

    normalized = normalize_governed_deferred_reference_payload(
        items,
        {"status": "available", "references": [raw]},
        flight=ACTIVE_FLIGHT,
    )

    assert "safeTarget" not in normalized["references"][0]["citation"]


def test_normalized_storage_preserves_controlled_extract_line_boundaries() -> None:
    items = [{"item_type": "MEL", "reference": "25-20-50A"}]
    excerpt = (
        "MEL 25-20-50A exact controlled extract.\n"
        "(a) First condition.\n"
        "(b) Second condition."
    )

    normalized = normalize_governed_deferred_reference_payload(
        items,
        {
            "status": "available",
            "references": [{
                "excerpt": excerpt,
                "citation": _citation(section="MEL 25-20-50A"),
            }],
        },
        flight=ACTIVE_FLIGHT,
    )

    assert normalized["references"][0]["excerpt"] == excerpt
