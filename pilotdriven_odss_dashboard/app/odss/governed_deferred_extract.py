from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .controlled_library import aircraft_effectivity_tokens


GOVERNED_DEFERRED_TYPES = frozenset({"MEL", "CDL", "CDDL"})
_REFERENCE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,79}$")
_SAFE_TARGET = re.compile(
    r"^/api/help-you/references/[A-Za-z0-9._-]+/open(?:\?[^#\s]*)?$"
)
_SPACE = re.compile(r"\s+")
_A350_900_ALIASES = frozenset({"A359", "A350900", "A350941"})
_FLEET_ALIASES = {"LR": "LH"}


def _text(value: Any) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()


def _excerpt_text(value: Any) -> str:
    return "\n".join(
        normalized
        for line in str(value or "").splitlines()
        if (normalized := _text(line))
    )


def _upper(value: Any) -> str:
    return _text(value).upper()


def _value(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in source:
            return source[name]
    return None


def _contains_token(text: str, token: str) -> bool:
    return bool(re.search(
        rf"(?:^|[^A-Z0-9]){re.escape(token)}(?:$|[^A-Z0-9])",
        text,
    ))


def _held_governed_types(text: str) -> set[str]:
    return {
        item_type
        for item_type in GOVERNED_DEFERRED_TYPES
        if _contains_token(text, item_type)
    }


def _confirmed_applicability(
    citation: Mapping[str, Any],
) -> dict[str, str | None] | None:
    applicability = citation.get("applicability")
    if not isinstance(applicability, Mapping):
        return None
    if _text(applicability.get("status")).lower() != "confirmed":
        return None
    scope = _text(applicability.get("scope")).lower()
    fleet = _upper(applicability.get("fleet")) or None
    aircraft = _upper(applicability.get("aircraft")) or None
    if scope not in {"specified", "all_operations"}:
        return None
    if scope == "all_operations":
        if fleet or aircraft:
            return None
        return {
            "scope": "all_operations",
            "fleet": None,
            "aircraft": None,
            "status": "confirmed",
        }
    if not fleet and not aircraft:
        return None
    return {
        "scope": "specified",
        "fleet": fleet,
        "aircraft": aircraft,
        "status": "confirmed",
    }


def _effectivity(applicability: Mapping[str, Any]) -> str:
    if applicability.get("scope") == "all_operations":
        return "ALL OPERATIONS - CONFIRMED"
    values = list(dict.fromkeys(
        str(value)
        for value in (
            applicability.get("fleet"),
            applicability.get("aircraft"),
        )
        if value
    ))
    return " / ".join(values) + " - CONFIRMED"


def _compact_token(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _upper(value))


def _aircraft_family(value: Any) -> str:
    token = _compact_token(value)
    return "A350900" if token in _A350_900_ALIASES else token


def _fleet_token(value: Any) -> str:
    token = _compact_token(value)
    return _FLEET_ALIASES.get(token, token)


def _applicability_matches_active_flight(
    applicability: Mapping[str, Any],
    flight: Mapping[str, Any] | None,
) -> bool:
    """Recheck every declared source constraint against ODSS-held identity."""

    if applicability.get("scope") == "all_operations":
        return True
    if not isinstance(flight, Mapping):
        return False
    registration = _text(flight.get("registration")) or None
    aircraft_type = _text(flight.get("aircraft_type")) or None
    expected_aircraft = _aircraft_family(applicability.get("aircraft"))
    active_aircraft = _aircraft_family(aircraft_type)
    if expected_aircraft and (
        not active_aircraft or active_aircraft != expected_aircraft
    ):
        return False
    expected_fleet = _fleet_token(applicability.get("fleet"))
    if expected_fleet:
        active_tokens = {
            _fleet_token(token)
            for token in aircraft_effectivity_tokens(
                registration,
                aircraft_type,
            )
        }
        if expected_fleet not in active_tokens:
            return False
    return bool(expected_aircraft or expected_fleet)


def _normalized_reference(
    raw: Mapping[str, Any],
) -> dict[str, Any] | None:
    citation = raw.get("citation")
    if not isinstance(citation, Mapping):
        return None
    excerpt = _excerpt_text(raw.get("excerpt"))
    document_title = _text(_value(citation, "documentTitle", "document_title"))
    revision = _text(_value(citation, "version", "revision"))
    effective_date = _text(
        _value(citation, "effectiveDate", "effective_date")
    )
    page = _text(citation.get("page"))
    section = _text(citation.get("section"))
    source_class = _text(
        _value(citation, "sourceClass", "source_class")
    ).lower()
    applicability = _confirmed_applicability(citation)
    if (
        source_class != "company_manual"
        or not excerpt
        or not document_title
        or not revision
        or not effective_date
        or not page
        or not section
        or not applicability
        or len(excerpt) > 12_000
        or len(document_title) > 500
        or len(revision) > 100
        or len(effective_date) > 64
        or len(page) > 64
        or len(section) > 500
    ):
        return None
    held_text = _upper(" ".join((section, excerpt)))
    title_text = _upper(document_title)
    raw_safe_target = _text(
        _value(citation, "safeTarget", "safe_target")
    )
    return {
        "excerpt": excerpt,
        "document_title": document_title,
        "revision": revision,
        "effective_date": effective_date,
        "page": page,
        "section": section,
        "applicability": applicability,
        "effectivity": _effectivity(applicability),
        "held_text": held_text,
        "held_types": _held_governed_types(held_text),
        "title_types": _held_governed_types(title_text),
        "safe_target": (
            raw_safe_target
            if raw_safe_target and _SAFE_TARGET.fullmatch(raw_safe_target)
            else None
        ),
    }


def _governed_item_matches(
    normalized: Mapping[str, Any],
    *,
    item_type: str,
    reference: str,
) -> bool:
    if (
        item_type not in GOVERNED_DEFERRED_TYPES
        or not _REFERENCE.fullmatch(reference)
    ):
        return False
    held_types = set(normalized.get("held_types") or [])
    title_types = set(normalized.get("title_types") or [])
    exact_type = (
        held_types == {item_type}
        or (not held_types and title_types == {item_type})
    )
    return exact_type and _contains_token(
        _upper(normalized.get("held_text")),
        reference,
    )


def _extract_identity(extract: Mapping[str, Any]) -> str:
    canonical = "|".join(_text(extract.get(key)).upper() for key in (
        "match_status",
        "deferred_entry_id",
        "item_type",
        "reference",
        "document_title",
        "revision",
        "effective_date",
        "page",
        "section",
        "excerpt",
    ))
    return "governed-deferred-" + hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:20]


def governed_deferred_extracts(
    deferred_items: Sequence[Mapping[str, Any]] | None,
    company_briefing_references: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Bind complete current-approved excerpts to exact source declarations.

    Exact bindings require the OFP itself to print a governed item type and
    reference.  An unresolved opaque declaration may receive one or more
    *candidate* excerpts only when the upstream governed matcher explicitly
    binds them to its stable ``deferred_entry_id`` and provides both the
    ambiguity reason and the condition that must be confirmed.  Text
    similarity alone is never accepted as a candidate or exact match.
    """

    payload = company_briefing_references
    if not isinstance(payload, Mapping) or _text(payload.get("status")).lower() != "available":
        return []
    raw_references = payload.get("references")
    if not isinstance(raw_references, Sequence) or isinstance(
        raw_references,
        (str, bytes),
    ):
        return []

    items = [item for item in (deferred_items or []) if isinstance(item, Mapping)]
    extracts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_references:
        if not isinstance(raw, Mapping):
            continue
        normalized = _normalized_reference(raw)
        if normalized is None:
            continue
        binding = _value(raw, "deferredBinding", "deferred_binding")
        binding = binding if isinstance(binding, Mapping) else {}
        binding_status = _text(
            _value(binding, "matchStatus", "match_status")
        ).lower()
        if binding and binding_status != "candidate":
            continue
        bound_entry_id = _text(
            _value(binding, "deferredEntryId", "deferred_entry_id")
        )
        bound_type = _upper(_value(binding, "itemType", "item_type"))
        bound_reference = _upper(binding.get("reference"))

        selected_index: int | None = None
        match_status: str | None = None
        ambiguity_reason: str | None = None
        confirmation_required: str | None = None
        item_type = ""
        reference = ""

        if binding_status == "candidate":
            ambiguity_reason = _text(
                _value(binding, "ambiguityReason", "ambiguity_reason")
            )
            confirmation_required = _text(
                _value(binding, "confirmationRequired", "confirmation_required")
            )
            if (
                not bound_entry_id
                or bound_type not in GOVERNED_DEFERRED_TYPES
                or not _REFERENCE.fullmatch(bound_reference)
                or not ambiguity_reason
                or not confirmation_required
                or len(ambiguity_reason) > 1_000
                or len(confirmation_required) > 1_000
                or not _governed_item_matches(
                    normalized,
                    item_type=bound_type,
                    reference=bound_reference,
                )
            ):
                continue
            selected_index = next((
                index
                for index, item in enumerate(items)
                if _text(item.get("deferred_entry_id")) == bound_entry_id
                and _text(item.get("classification_status")).lower()
                == "unresolved"
            ), None)
            if selected_index is None:
                continue
            item_type = bound_type
            reference = bound_reference
            match_status = "candidate"
        else:
            matching_indexes = []
            for index, item in enumerate(items):
                candidate_type = _upper(item.get("item_type"))
                candidate_reference = _upper(item.get("reference"))
                if _governed_item_matches(
                    normalized,
                    item_type=candidate_type,
                    reference=candidate_reference,
                ):
                    matching_indexes.append(index)
            # Type + number is exact only when it identifies one source row.
            # Duplicate declarations need an explicit stable entry binding;
            # silently choosing the first would manufacture provenance.
            if len(matching_indexes) != 1:
                continue
            selected_index = matching_indexes[0]
            item_type = _upper(items[selected_index].get("item_type"))
            reference = _upper(items[selected_index].get("reference"))
            match_status = "exact"

        extract = {
            "source_item_index": selected_index,
            "deferred_entry_id": (
                _text(items[selected_index].get("deferred_entry_id")) or None
            ),
            "source_declaration": _text(
                items[selected_index].get("source_declaration")
            ) or None,
            "match_status": match_status,
            "item_type": item_type,
            "reference": reference,
            "excerpt": normalized["excerpt"],
            "document_title": normalized["document_title"],
            "revision": normalized["revision"],
            "effective_date": normalized["effective_date"],
            "page": normalized["page"],
            "section": normalized["section"],
            "applicability": normalized["applicability"],
            "effectivity": normalized["effectivity"],
            "safe_target": normalized["safe_target"],
            "ambiguity_reason": ambiguity_reason,
            "confirmation_required": confirmation_required,
        }
        extract["extract_id"] = _extract_identity(extract)
        if extract["extract_id"] in seen:
            continue
        seen.add(extract["extract_id"])
        extracts.append(extract)
    return extracts


def normalize_governed_deferred_reference_payload(
    deferred_items: Sequence[Mapping[str, Any]] | None,
    payload: Mapping[str, Any] | None,
    *,
    flight: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only complete, source-bound references suitable for storage.

    Every submitted reference must independently bind to one exact OFP item or
    to one explicitly named unresolved candidate.  A mixed payload containing
    one valid reference and one incomplete/similarity-only reference is
    rejected as a whole instead of silently dropping the unsafe row.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Company briefing references must be an object.")
    status = _text(payload.get("status")).lower()
    raw_references = payload.get("references")
    if status == "unavailable":
        if raw_references != []:
            raise ValueError(
                "Unavailable company briefing references must contain no entries."
            )
        return {"status": "unavailable", "references": []}
    if status != "available":
        raise ValueError(
            "Company briefing references must have status available or unavailable."
        )
    if (
        not isinstance(raw_references, Sequence)
        or isinstance(raw_references, (str, bytes))
        or not raw_references
        or len(raw_references) > 16
    ):
        raise ValueError("Company briefing references must contain 1 to 16 entries.")

    normalized_references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_references, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Company briefing reference {index} is malformed.")
        extracts = governed_deferred_extracts(
            deferred_items,
            {"status": "available", "references": [raw]},
        )
        if len(extracts) != 1:
            raise ValueError(
                f"Company briefing reference {index} is incomplete or does not "
                "bind to an exact deferred declaration."
            )
        extract = extracts[0]
        if not _applicability_matches_active_flight(
            extract["applicability"],
            flight,
        ):
            raise ValueError(
                f"Company briefing reference {index} does not match the "
                "active flight applicability."
            )
        extract_id = str(extract["extract_id"])
        if extract_id in seen:
            continue
        seen.add(extract_id)
        citation: dict[str, Any] = {
            "sourceClass": "company_manual",
            "documentTitle": extract["document_title"],
            "version": extract["revision"],
            "effectiveDate": extract["effective_date"],
            "page": extract["page"],
            "section": extract["section"],
            "applicability": dict(extract["applicability"]),
        }
        if extract.get("safe_target"):
            citation["safeTarget"] = extract["safe_target"]
        stored: dict[str, Any] = {
            "excerpt": extract["excerpt"],
            "citation": citation,
        }
        if extract["match_status"] == "candidate":
            stored["deferredBinding"] = {
                "deferredEntryId": extract["deferred_entry_id"],
                "matchStatus": "candidate",
                "itemType": extract["item_type"],
                "reference": extract["reference"],
                "ambiguityReason": extract["ambiguity_reason"],
                "confirmationRequired": extract["confirmation_required"],
            }
        normalized_references.append(stored)
    if not normalized_references:
        raise ValueError("No unique governed deferred reference was supplied.")
    return {
        "status": "available",
        "references": normalized_references,
    }


__all__ = [
    "GOVERNED_DEFERRED_TYPES",
    "governed_deferred_extracts",
    "normalize_governed_deferred_reference_payload",
]
