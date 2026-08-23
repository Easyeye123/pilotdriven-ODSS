from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


# Lido page-one declarations use a two-letter sequence token followed by a
# governed class.  Only known classes are split from a flattened company
# remark.  Unknown uppercase prose remains attached to the parsed item rather
# than being promoted into a dispatch gate by guesswork.
_EMBEDDED_DECLARATION = re.compile(
    r"(?<![A-Z0-9])(?P<token>[A-Z]{2})\s+"
    r"(?:"
    r"(?P<deferred_kind>CDDL|CDL|MEL)"
    r"(?:\s+(?P<deferred_reference>[0-9A-Z][0-9A-Z-]*))?"
    r"|"
    r"(?P<operational_kind>IN)\s+"
    r"(?P<operational_reference>"
    r"[A-Z0-9][A-Z0-9/.-]*(?:\s+R[0-9A-Z.-]+)?"
    r")"
    r")(?=\s|$)"
)

_NORMALIZED_SPACE = re.compile(r"\s+")
_SUBJECT_TOKEN = re.compile(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)*")
_STATE = (
    r"REMOVED|INOPERATIVE|INOP|UNAVAILABLE|NOT\s+AVAILABLE|"
    r"UNSERVICEABLE|U/S|FAILED|DEACTIVATED"
)
_EQUIPMENT_STATE = re.compile(
    rf"\b(?:BOTH\s+|ALL\s+|THE\s+)?"
    rf"(?P<equipment>[A-Z][A-Z0-9/-]{{2,}})"
    rf"(?:\s*\([^)]*\))?"
    rf"(?:\s+(?:SYS|SYSTEM))?\s+(?:{_STATE})\b"
)
_UPLIFT_REFERENCE = re.compile(r"\b(?P<reference>\d{2,4})\s+UPLIFT\b")
_MAINTENANCE_PREFIX = re.compile(
    r"^(?:MAINT(?:ENANCE)?\s+ENTRY:\s*)?(?:DURING\s+WAC,?\s+)?"
    r"(?:WAC\s+)?FOUND\s+",
    re.IGNORECASE,
)
_UPLIFT_INSTRUCTION = re.compile(r"\bTO\s+UPLIFT\s+[^.]+", re.IGNORECASE)
_INTERNAL_REFERENCE_PLACEHOLDERS = {"UNSPECIFIED", "UNKNOWN"}
_INTERNAL_TYPE_PLACEHOLDERS = {"UNCLASSIFIED", "UNSPECIFIED", "UNKNOWN"}

# These words express source boilerplate, position, quantity or condition.
# Excluding them from a two-word subject fingerprint lets two declarations of
# the same component group together without grouping every "RH ... torn"
# defect.  The complete source text is still retained in source_segments.
_NON_SUBJECT_TOKENS = {
    "ALL",
    "BOTH",
    "DAMAGED",
    "DURING",
    "ENTRY",
    "FOUND",
    "INBD",
    "INBOARD",
    "LEFT",
    "LH",
    "MAINT",
    "MAINTENANCE",
    "MISSING",
    "OUTBD",
    "OUTBOARD",
    "PARTIAL",
    "PARTIALLY",
    "QTY",
    "RIGHT",
    "RH",
    "TORN",
    "WAC",
}


def _clean(value: Any) -> str:
    return _NORMALIZED_SPACE.sub(" ", str(value or "")).strip()


def deferred_reference_for_display(value: Any) -> str:
    """Return a printed reference or empty text for an internal marker.

    An older stored analysis may retain a placeholder value. Publication
    keeps that absence truthful instead of turning the marker into identity
    text shown to a pilot.
    """
    reference = _clean(value).upper()
    return "" if reference in _INTERNAL_REFERENCE_PLACEHOLDERS else reference


def deferred_item_type_for_display(value: Any) -> str:
    """Return a pilot-safe type label without changing the parsed value."""
    item_type = _clean(value).upper()
    if not item_type or item_type in _INTERNAL_TYPE_PLACEHOLDERS:
        return "DEFERRED ITEM"
    return item_type


def deferred_source_declaration_for_display(value: Any) -> str:
    """Hide only synthetic placeholder-only declarations from publication.

    A meaningful printed declaration remains verbatim, even if one of its
    words happens to resemble a parser state. The raw parsed value is never
    mutated; this helper is only for pilot-facing projections.
    """
    declaration = _clean(value)
    tokens = re.findall(r"[A-Z0-9]+", declaration.upper())
    if len(tokens) > 1 and re.fullmatch(r"[A-Z]{2}", tokens[0]):
        tokens = tokens[1:]
    if tokens and all(
        token in (_INTERNAL_TYPE_PLACEHOLDERS | _INTERNAL_REFERENCE_PLACEHOLDERS)
        for token in tokens
    ):
        return ""
    return declaration


def _accepted_markers(text: str) -> list[re.Match[str]]:
    """Return unambiguous embedded declarations in flattened source text.

    A marker is accepted at the beginning of the field or after sentence-like
    punctuation.  This intentionally refuses ambiguous prose such as
    ``PROCEED TO IN CABIN ...``; failing to split is safer than inventing a
    source declaration.
    """
    accepted: list[re.Match[str]] = []
    for match in _EMBEDDED_DECLARATION.finditer(text):
        if match.start() == 0:
            accepted.append(match)
            continue
        prefix = text[: match.start()].rstrip()
        if prefix and prefix[-1] in ".;:":
            accepted.append(match)
    return accepted


def _main_declaration(item: Mapping[str, Any]) -> str | None:
    explicit = deferred_source_declaration_for_display(
        item.get("source_declaration")
    )
    if explicit:
        return explicit
    item_type = _clean(item.get("item_type")).upper()
    reference = deferred_reference_for_display(item.get("reference"))
    if item_type in _INTERNAL_TYPE_PLACEHOLDERS:
        item_type = ""
    if not item_type and not reference:
        return None
    return " ".join(value for value in (item_type, reference) if value)


def _source_text(description: str, restriction: str | None) -> str:
    return " ".join(value for value in (description, restriction or "") if value)


def split_deferred_source_segments(
    deferred_items: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Project parsed items into source-bounded declarations without mutation.

    The parser contract remains untouched.  When a later page-one declaration
    was flattened into an earlier item's ``company_remark``, this projection
    recovers only declarations with an unambiguous two-letter marker and keeps
    an index/field trail back to the raw item.
    """
    segments: list[dict[str, Any]] = []
    sources = list(deferred_items or [])
    for source_item_index, source in enumerate(sources):
        item = dict(source)
        next_declaration = (
            deferred_source_declaration_for_display(
                sources[source_item_index + 1].get("source_declaration")
            )
            if source_item_index + 1 < len(sources)
            else ""
        )
        source_page = item.get("source_page")
        description = _clean(item.get("description"))
        company_remark = _clean(item.get("company_remark"))
        markers = _accepted_markers(company_remark)
        main_restriction = (
            _clean(company_remark[: markers[0].start()])
            if markers
            else company_remark
        )
        item_type = _clean(item.get("item_type")).upper() or "UNCLASSIFIED"
        reference = deferred_reference_for_display(item.get("reference")) or None
        if description or main_restriction or _main_declaration(item):
            segments.append({
                "source_item_index": source_item_index,
                "source_segment_index": 0,
                "origin": "parsed-item",
                "source_field": f"deferred_items[{source_item_index}]",
                "source_token": None,
                "source_declaration": _main_declaration(item),
                "source_page": source_page,
                "crop_end_needle": next_declaration or "PLAN",
                "declaration_kind": item_type,
                "item_type": item_type,
                "reference": reference,
                "description": description,
                "restriction": main_restriction or None,
                "source_text": _source_text(description, main_restriction),
            })

        for embedded_index, marker in enumerate(markers, start=1):
            end = (
                markers[embedded_index].start()
                if embedded_index < len(markers)
                else len(company_remark)
            )
            body = _clean(company_remark[marker.end() : end]).strip(" ;")
            declaration = _clean(marker.group(0))
            deferred_kind = marker.group("deferred_kind")
            if deferred_kind:
                embedded_type = deferred_kind
                embedded_reference = (
                    _clean(marker.group("deferred_reference")).upper() or None
                )
            else:
                embedded_type = "OPERATIONAL_RESTRICTION"
                embedded_reference = (
                    _clean(marker.group("operational_reference")).upper() or None
                )
            segments.append({
                "source_item_index": source_item_index,
                "source_segment_index": embedded_index,
                "origin": "embedded-declaration",
                "source_field": (
                    f"deferred_items[{source_item_index}].company_remark"
                ),
                "source_token": marker.group("token"),
                "source_declaration": declaration,
                "source_page": source_page,
                "crop_end_needle": next_declaration or "PLAN",
                "declaration_kind": (
                    deferred_kind or marker.group("operational_kind")
                ),
                "item_type": embedded_type,
                "reference": embedded_reference,
                "description": body,
                "restriction": None,
                "source_text": _source_text(declaration, body),
            })
    return segments


def _subject_phrases(segment: Mapping[str, Any]) -> set[str]:
    tokens = _SUBJECT_TOKEN.findall(
        _clean(segment.get("description") or segment.get("source_text")).upper()
    )
    phrases: set[str] = set()
    for left, right in zip(tokens, tokens[1:]):
        if (
            left in _NON_SUBJECT_TOKENS
            or right in _NON_SUBJECT_TOKENS
            or left.isdigit()
            or right.isdigit()
            or len(left) < 3
            or len(right) < 3
        ):
            continue
        phrases.add(f"{left} {right}")
    return phrases


def _same_reference(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_reference = deferred_reference_for_display(left.get("reference"))
    right_reference = deferred_reference_for_display(right.get("reference"))
    return bool(
        left_reference
        and left_reference == right_reference
    )


def _group_segments(
    segments: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    parent = list(range(len(segments)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    subjects = [_subject_phrases(segment) for segment in segments]
    for left_index, left in enumerate(segments):
        left_type = str(left.get("item_type") or "")
        if left_type not in {"CDDL", "CDL", "MEL"}:
            continue
        for right_index in range(left_index + 1, len(segments)):
            right = segments[right_index]
            if right.get("item_type") != left_type:
                continue
            if _same_reference(left, right) or (
                subjects[left_index] & subjects[right_index]
            ):
                union(left_index, right_index)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, segment in enumerate(segments):
        groups.setdefault(find(index), []).append(segment)
    return list(groups.values())


def _common_subject(group: list[dict[str, Any]]) -> str | None:
    if not group:
        return None
    phrase_sets = [_subject_phrases(segment) for segment in group]
    common = set.intersection(*phrase_sets) if phrase_sets else set()
    if not common:
        return None
    first_text = _clean(group[0].get("description")).upper()
    return min(
        common,
        key=lambda phrase: (
            first_text.find(phrase) if phrase in first_text else len(first_text),
            phrase,
        ),
    )


def _operational_equipment(group: list[dict[str, Any]]) -> list[str]:
    equipment: list[str] = []
    for segment in group:
        for match in _EQUIPMENT_STATE.finditer(
            _clean(segment.get("description")).upper()
        ):
            value = match.group("equipment")
            if value not in equipment:
                equipment.append(value)
    return equipment


def _gate_title(group: list[dict[str, Any]]) -> str:
    item_type = str(group[0].get("item_type") or "UNCLASSIFIED")
    display_item_type = deferred_item_type_for_display(item_type)
    if item_type == "OPERATIONAL_RESTRICTION":
        equipment = _operational_equipment(group)
        if equipment:
            return " / ".join(equipment)
        declaration = deferred_source_declaration_for_display(
            group[0].get("source_declaration")
        )
        return declaration or "OPERATIONAL RESTRICTION"

    references = list(dict.fromkeys(
        reference
        for reference in (
            deferred_reference_for_display(segment.get("reference"))
            for segment in group
        )
        if reference
    ))
    if references:
        return f"{display_item_type} " + " / ".join(references)

    subject = _common_subject(group)
    if subject:
        if len(group) > 1 and not subject.endswith("S"):
            subject += "S"
        return subject
    declaration = deferred_source_declaration_for_display(
        group[0].get("source_declaration")
    )
    return declaration or f"{display_item_type} REVIEW REQUIRED"


def _grouping_basis(group: list[dict[str, Any]]) -> str:
    if len(group) == 1:
        return (
            "embedded-source-declaration"
            if group[0].get("origin") == "embedded-declaration"
            else "single-source-declaration"
        )
    references = {
        deferred_reference_for_display(segment.get("reference"))
        for segment in group
        if deferred_reference_for_display(segment.get("reference"))
    }
    if len(references) == 1:
        return "same-governing-reference"
    return "shared-source-subject"


def _publication_row(segment: Mapping[str, Any]) -> dict[str, Any]:
    """Return one compact display row without losing source provenance.

    Grouped gates are useful for dispatch decisions, while the REV3 technical
    table publishes every source declaration.  The only fallback reference we
    derive is the numeric token printed immediately before ``UPLIFT`` on an
    otherwise unnumbered CDDL declaration; it remains a display reference and
    never changes the parsed source item or its governing status.
    """
    item_type = _clean(segment.get("item_type")).upper() or "UNCLASSIFIED"
    display_item_type = deferred_item_type_for_display(item_type)
    reference = deferred_reference_for_display(segment.get("reference"))
    if not reference and item_type == "CDDL":
        match = _UPLIFT_REFERENCE.search(
            _clean(segment.get("restriction") or segment.get("source_text")).upper()
        )
        reference = match.group("reference") if match else ""
    title = (
        reference
        if item_type == "OPERATIONAL_RESTRICTION" and reference
        else " ".join(
            value for value in (display_item_type, reference) if value
        )
    )
    description = _clean(segment.get("description"))
    restriction = _clean(segment.get("restriction"))
    if item_type == "CDDL":
        compact_parts: list[str] = []
        if "NO POWER" in description.upper():
            compact_parts.append("NO POWER")
        compact_restriction = _UPLIFT_REFERENCE.sub("UPLIFT", restriction)
        compact_restriction = re.sub(
            r"\bPUSH\s+COMPACT\s+TO\s+RESET\b",
            "RESET",
            compact_restriction,
            flags=re.IGNORECASE,
        ).replace(". ", "; ").rstrip(".")
        if compact_restriction:
            compact_parts.append(compact_restriction)
        summary = "; ".join(dict.fromkeys(compact_parts)) or description
    elif item_type == "CDL":
        summary = _MAINTENANCE_PREFIX.sub("", description).strip()
    elif item_type == "OPERATIONAL_RESTRICTION":
        state_phrases = list(dict.fromkeys(
            _clean(match.group(0))
            for match in _EQUIPMENT_STATE.finditer(description.upper())
        ))
        state_phrases = [
            re.sub(r"\s+", " ", re.sub(r"\s*\([^)]*\)", "", phrase))
            .replace(" SYS NOT AVAILABLE", " UNAVAILABLE")
            .replace(" SYSTEM NOT AVAILABLE", " UNAVAILABLE")
            for phrase in state_phrases
        ]
        uplift = _UPLIFT_INSTRUCTION.search(description)
        if uplift:
            state_phrases.append(
                _clean(uplift.group(0))
                .removeprefix("TO ")
                .replace(" FOR ALL ", " - ALL ")
            )
        summary = "; ".join(state_phrases) or description
    else:
        summary = _source_text(description, restriction or None)
    summary = (
        summary.replace("LANDING GEAR DOOR", "GEAR-DOOR")
        .replace("PARTIALLY", "PARTLY")
    )
    return {
        "title": title or f"{display_item_type} REVIEW REQUIRED",
        "category": item_type.lower().replace("_", "-"),
        "summary": summary,
        "reference": reference or None,
        "source_item_index": int(segment["source_item_index"]),
        "source_segment_index": int(segment["source_segment_index"]),
        "source_field": segment.get("source_field"),
        "source_declaration": segment.get("source_declaration"),
    }


def _publication_rows(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for segment in group:
        row = _publication_row(segment)
        reference = str(row.get("reference") or "")
        key = (str(row.get("category") or ""), reference)
        if not reference or key not in keyed:
            rows.append(row)
            if reference:
                keyed[key] = row
            continue
        existing = keyed[key]
        summary = str(row.get("summary") or "")
        if summary and summary not in str(existing.get("summary") or ""):
            existing["summary"] = " | ".join(
                value
                for value in (str(existing.get("summary") or ""), summary)
                if value
            )
    return rows


def build_deferred_dispatch_gates(
    deferred_items: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build compact, source-traceable dispatch gates for every UI surface.

    This is a projection only: raw ``deferred_items`` remain the engine input
    and are never modified.  The result carries complete source segments so a
    renderer can shorten presentation copy without losing the audit trail.
    """
    groups = _group_segments(split_deferred_source_segments(deferred_items))
    priority = {
        "CDDL": 0,
        "OPERATIONAL_RESTRICTION": 1,
        "CDL": 2,
        "MEL": 3,
        # Engineering information notices ride with the technical items they
        # annotate (SQ910 21 Aug: ENG 2 fan-cowl latch check), ahead of
        # cabin-only IFE deferrals.
        "IN": 4,
        "IFEDDL": 5,
        "UNCLASSIFIED": 6,
    }
    groups.sort(key=lambda group: (
        priority.get(str(group[0].get("item_type") or ""), 5),
        min(int(segment["source_item_index"]) for segment in group),
        min(int(segment["source_segment_index"]) for segment in group),
    ))

    gates: list[dict[str, Any]] = []
    for number, group in enumerate(groups, start=1):
        item_types = list(dict.fromkeys(
            str(segment.get("item_type") or "UNCLASSIFIED")
            for segment in group
        ))
        references = list(dict.fromkeys(
            reference
            for reference in (
                deferred_reference_for_display(segment.get("reference"))
                for segment in group
            )
            if reference
        ))
        source_texts = list(dict.fromkeys(
            _clean(segment.get("source_text"))
            for segment in group
            if _clean(segment.get("source_text"))
        ))
        gates.append({
            "gate_id": f"deferred-dispatch-gate-{number}",
            "title": _gate_title(group),
            "category": item_types[0].lower().replace("_", "-"),
            "status": "dispatch-confirmation-required",
            "item_types": item_types,
            "references": references,
            "summary": " | ".join(source_texts),
            "grouping_basis": _grouping_basis(group),
            "source_item_indices": sorted({
                int(segment["source_item_index"])
                for segment in group
            }),
            "source_segments": group,
            "publication_rows": _publication_rows(group),
        })
    return gates


__all__ = [
    "build_deferred_dispatch_gates",
    "deferred_item_type_for_display",
    "deferred_reference_for_display",
    "deferred_source_declaration_for_display",
    "split_deferred_source_segments",
]
