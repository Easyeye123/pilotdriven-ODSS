"""Flight-specific publication of held calculations and source constraints.

This projection never supplies missing weather, aircraft limits or a release
decision. Source quotations stay in the app. Rules identify only consequences
supported by a declaration; an unresolved manual constraint stays open.
"""
from __future__ import annotations

import math
import re

from .report_facts import operational_reference_times
from .vaa import _utc


def clean(value) -> str:
    return " ".join(str(value or "").split())


# ------------------------------------------------- the carried excess's name
#
# OFP page 1 itemises the excess by allocation. When every positive allocation
# is TANKER the excess IS tankering, and David's briefings say so in the OFP's
# own word: his SQ910_21AUG2026 reference prints ``TANKER +18,847 KG`` in the
# page-1 FUEL tile and ``TANKER EXCESS 18,847 KG`` in the page-3 fuel chain
# (his 21 Aug 2026 fuel lesson).
#
# Before C2 the rule lived in three places that could drift - the dashboard
# (``web/src/lib/overview-cards.ts`` ``tankerOnly``), the nine-page composition
# in ``combined_brief`` - and not at all in the six-page download, which always
# printed EXCESS. One rule, one place, so the two surfaces cannot disagree
# about the same OFP line again.

TANKER_EXCESS_TILE_LABEL = "TANKER"
TANKER_EXCESS_CHAIN_LABEL = "TANKER EXCESS"
EXCESS_LABEL = "EXCESS"


def tanker_only_excess(fuel_summary) -> bool:
    """True when every positive excess allocation on OFP page 1 is TANKER.

    The dashboard's rule, restated: at least one strictly positive allocation,
    and every positive allocation labelled TANKER. A zero MEL line beside a
    positive TANKER line is still tankering; a mixed INTAM/TMM excess is not.
    """
    if not isinstance(fuel_summary, dict):
        return False
    positive = [
        item for item in (fuel_summary.get("excess_breakdown") or [])
        if isinstance(item, dict)
        and isinstance(item.get("fuel_kg"), (int, float))
        and not isinstance(item.get("fuel_kg"), bool)
        and item["fuel_kg"] > 0
    ]
    return bool(positive) and all(
        str(item.get("label") or "").strip().upper() == "TANKER" for item in positive
    )


def excess_fuel_tile_label(fuel_summary) -> str:
    """Page-1 FUEL tile row name, in his reference's word."""
    return TANKER_EXCESS_TILE_LABEL if tanker_only_excess(fuel_summary) else EXCESS_LABEL


def excess_fuel_chain_label(fuel_summary) -> str:
    """Page-3 FUEL PLAN / MASS CHAIN row name, in his reference's words."""
    return TANKER_EXCESS_CHAIN_LABEL if tanker_only_excess(fuel_summary) else EXCESS_LABEL


def flight_window(flight):
    return operational_reference_times(flight)


def window_label(flight) -> str:
    start, end = flight_window(flight)
    if start and end:
        return f"{start:%d%b %H%MZ}-{end:%d%b %H%MZ}".upper()
    return "the unresolved flight UTC window"


def level_profile_label(flight) -> str:
    tokens = clean(flight.get("planned_level_profile")).split("/")
    if len(tokens) < 2 or len(tokens) % 2 or any(not re.fullmatch(r"\d{3}", tokens[i]) for i in range(1, len(tokens), 2)):
        return "Level profile not held"
    return " / ".join(f"{tokens[i]} FL{tokens[i + 1]}" for i in range(0, len(tokens), 2))


def cyclone_content(flight):
    """Use the existing time-matched track screening, never movement alone."""
    review = flight.get("tropical_cyclone_review") or {}
    track = flight.get("tropical_cyclone_track_review") or review.get("track_context") or {}
    start, end = flight_window(flight)
    lines, markers = [], []
    for cyclone in track.get("cyclones") or []:
        closest = cyclone.get("closest_route_screening") or {}
        when = _utc(closest.get("time_utc"))
        distance = closest.get("distance_nm")
        position = closest.get("cyclone_centre_position") or {}
        if not (start and end and when and start <= when <= end
                and isinstance(distance, (int, float)) and math.isfinite(distance) and distance >= 0):
            continue
        name = clean(cyclone.get("name")) or "Named cyclone"
        leg = "-".join(filter(None, [clean(closest.get("route_from")), clean(closest.get("route_to"))]))
        lines.append(f"{name}: centre about {distance:.0f} NM from {leg or 'the timed route'} at {when:%d%b %H%MZ}. Interpolated official-position screening; this distance is not a wind-field clearance.")
        if (all(isinstance(position.get(k), (int, float)) and math.isfinite(position[k]) for k in ("latitude", "longitude"))
                and abs(position["latitude"]) <= 90 and abs(position["longitude"]) <= 180):
            markers.append({"kind": "TC", "label": name, "position": position, "time_utc": closest["time_utc"], "distance_nm": distance})
    if not lines:
        lines = [f"No time-matched cyclone centre-distance result is held for {window_label(flight)}. Later live tracks cannot establish cyclone conditions for this flight."]
    return {"lines": lines, "markers": markers, "time_matched": bool(markers)}


def deferred_item_label(value, fallback="Deferred item"):
    """Publish a declaration's identity without the app's item-level badge.

    ``build_deferred_dispatch_gates`` falls back to "<TYPE> ITEM" (before R2, "<TYPE> REVIEW REQUIRED")
    when a declaration cannot be resolved to a subject or a reference. That is
    an in-app review badge, not an analysed statement, and the published
    briefing rejects repeated item-level badges on its analysed pages.
    """
    cleaned = re.sub(r"\s*(?:REVIEW REQUIRED|\bITEM\b)\s*", " ", str(value or ""), flags=re.I)
    return " ".join(cleaned.split()).strip(" -") or fallback


_SOURCE_ENTRY_PREFIX = re.compile(r"^(?:MAINT ENTRY\s*:?\s*|WAC FOUND\s*)+", re.I)
_SENTENCE_START = re.compile(r"(^|[.!?]\s+)([a-z])")
_WORD = re.compile(r"[A-Za-z0-9]+")


def _readable_word(match: re.Match[str]) -> str:
    """Lower a block-capital source word only when it is ordinary English.

    The test is ``plain_english.is_plain_english_word``: a dictionary for words
    of five letters and longer, a hand-checked safe list for the two-to-four
    letter band where abbreviations live. Anything it does not recognise - and
    that is every abbreviation - is left exactly as the source wrote it.

    The rule this replaced ran the other way: lower any word that carries a
    vowel unless it was one of 25 listed abbreviations. That destroyed every
    vowel-carrying abbreviation outside the list ("MEL" -> "mel", "NEF" ->
    "nef", "ILS" -> "Ils", "CAT II/III" -> "cat ii/iii"), because vowel
    presence measures nothing about whether a token is an abbreviation.

    Punctuation splits the word, so "AFT-MOST" cases as two words while
    "I/B", "D4L" and "FC2161F1FK" keep the shorthand the source wrote.
    """
    from .plain_english import is_plain_english_word

    word = match.group(0)
    if not word.isupper():
        return word
    if len(word) == 1 or any(character.isdigit() for character in word):
        return word
    return word.lower() if is_plain_english_word(word) else word


def source_subject_sentence(value) -> str:
    """Publish a declaration's own subject in sentence case, not block capitals.

    David, 9 Sep 2026 21:28: "by copying in blocks and capital is very hard to
    read". His reference briefing still names the defect - "The aft-most
    fan-cowl latch access-panel latch is loose" - so the answer to the block
    capitals is to case them, never to drop the subject: a deferred card that
    does not say what is wrong with the aircraft is not a finding.

    Nothing is added or re-worded: this only changes letter case, and only for
    words the source wrote in full capitals that are recognised English.
    """
    subject = clean(value)
    if not subject or subject != subject.upper():
        # A source that already wrote mixed case is readable as it stands;
        # only block capitals are re-cased, and only ever in case.
        return subject
    cased = _WORD.sub(_readable_word, subject)
    return _SENTENCE_START.sub(lambda match: match.group(1) + match.group(2).upper(), cased)


# ---------------------------------------------------------------------------
# What may be published as a declaration's subject
#
# The OFP's deferred table is a form. Its "description" cell holds whatever the
# engineer typed, wrapped at the cell edge with the remainder pushed into the
# company-remark cell, and it carries the form's own furniture: a repeated
# drop-down label, an "OTHERS (PLS ENTER COMMENTS)" placeholder, a manual
# section heading. Publishing that cell unconditionally puts mid-sentence
# fragments on the page he circled in green - "Both VCRU (101HW & 103HW)
# removed as per", "LH wing, slat #6 lower seal found" - which is his 9 Sep
# 20:52 "Why are the MEL/CDL content repeated?" and 21:23 "This is also rubbish
# generated" in a new shape.
#
# So a subject is published only when it stands on its own. When it does not,
# the row keeps the declaration reference and the analysed consequence, and
# says nothing it cannot stand behind.
# ---------------------------------------------------------------------------

# Words that leave a phrase open, so a subject ending in one was cut by the
# form and is not a statement.
_OPEN_TAIL_WORDS = frozenset({
    # Articles, prepositions, conjunctions and auxiliaries.
    "A", "AN", "THE", "AND", "OR", "NOR", "BUT", "AS", "AT", "BY", "FOR",
    "FROM", "IN", "INTO", "OF", "ON", "ONTO", "OUT", "OVER", "PER", "TO",
    "UNDER", "UP", "UPON", "VIA", "WITH", "WITHIN", "WITHOUT", "THAN", "THEN",
    "THAT", "WHICH", "WHEN", "WHILE", "IF", "SO", "PLUS", "DUE", "BOTH",
    "EACH", "ALL", "ANY", "NO", "NOT", "IS", "ARE", "WAS", "WERE", "BE",
    "BEEN", "BEING", "HAS", "HAVE", "HAD", "WILL", "SHALL", "MUST", "MAY",
    "CAN", "DO", "DOES", "DID", "X",
    # Participles of discovery: the form habitually breaks the line between
    # what was found and what was found wrong with it ("... SLAT #6 LOWER SEAL
    # FOUND" + remark "DETERIORATED (QTY: 04 OFF)").
    "FOUND", "NOTED", "REPORTED", "OBSERVED", "SUSPECTED", "DEEMED",
    # Attributive only in this domain: the sibling row in the same OFP writes
    # "CHILLING COMPARTMENT", so a subject ending in CHILLING is half a
    # compound.
    "CHILLING",
})
# The final word, only when it stands alone: the trailing "A" of a MEL
# reference such as "25-20-50A" is a suffix letter, not the article.
_TRAILING_WORD = re.compile(r"(?:^|[^A-Za-z0-9])([A-Za-z]+)\s*$")
_SEGMENT_SPLIT = re.compile(r"(\s*,\s*|\s*;\s*|\s+X\s+)")
_FORM_PLACEHOLDER = re.compile(
    r"\(\s*(?:PLS|PLEASE)\b[^)]*\)|\bENTER\s+COMMENTS?\b"
    r"|\b(?:PLS|PLEASE)\s+(?:SPECIFY|STATE)\b|\bSELECT\s+ONE\b",
    re.I,
)
# What the drop-down leaves behind once its instruction is removed.
_UNSELECTED_OPTION = frozenset({"OTHER", "OTHERS"})
# A subject that only cites other paperwork is provenance, not a defect. These
# tokens are stripped before asking whether anything is left.
_REFERENCE_TOKEN = re.compile(
    r"^(?:CDL|CDDL|MEL|IFEDDL|DDL|EDDL|IN|EN|NPE|MAF|REF|REFER|WRT|ITEM|NO|NR"
    r"|AND|OR|X|TO|R\d*|[-#/&.]+|[0-9][0-9A-Z/.\-]*)$",
    re.I,
)
_MANUAL_HEADING = re.compile(
    r"^SECTION\b|\bPREAMBLE\b|\bREV\s*\d|\bREVISION\s*\d|\bCHAPTER\s*\d",
    re.I,
)


def _normalised_label(value: str) -> str:
    """Compare a segment with a gate title without plural or spacing noise."""
    words = [word.rstrip("S") for word in _WORD.findall(clean(value).upper())]
    return " ".join(words)


def _subject_segments(subject: str) -> list[tuple[str, str]]:
    """Split on the form's own separators, keeping each separator verbatim.

    The separator is part of what the source wrote (the OFP writes " X " for
    "and"), so it is carried through rather than normalised away.
    """
    parts = _SEGMENT_SPLIT.split(subject)
    segments: list[tuple[str, str]] = [("", parts[0])] if parts else []
    for index in range(1, len(parts) - 1, 2):
        segments.append((parts[index], parts[index + 1]))
    return segments


def _without_label_prefix(segment: str, normalised: str, label: str) -> str:
    """Strip a leading restatement of the gate title from one segment."""
    if not label or not normalised.startswith(label + " "):
        return segment
    pattern = (
        r"^\W*"
        + r"\W+".join(re.escape(word) + "S?" for word in label.split())
        + r"\W+"
    )
    trimmed = re.sub(pattern, "", segment, count=1, flags=re.I)
    if len(_WORD.findall(trimmed)) < 2 or not trimmed[:1].isalnum():
        # "AIR CHILLERS" + "INOP" leaves a single token; keep the source's
        # phrase rather than publish a bare word.
        return segment
    return trimmed


def _collapse_form_furniture(subject: str, item_label: str) -> str:
    """Drop a repeated drop-down label, a form placeholder and the gate title.

    The OFP writes the selected drop-down twice ("TRASH COMPACTOR, TRASH
    COMPACTOR, NO POWER") and leaves the unselected "OTHERS (PLS ENTER
    COMMENTS)" behind. The gate the row is published under already names the
    item, so a segment that only restates it is repetition.
    """
    segments = _subject_segments(subject)
    label = _normalised_label(item_label)
    kept: list[tuple[str, str]] = []
    for index, (separator, segment) in enumerate(segments):
        normalised = _normalised_label(segment)
        if not normalised:
            continue
        residue = {
            word.upper()
            for word in _WORD.findall(_FORM_PLACEHOLDER.sub(" ", segment))
        }
        if _FORM_PLACEHOLDER.search(segment) and residue <= _UNSELECTED_OPTION:
            continue
        if label and normalised == label:
            continue
        if label:
            # "AIR CHILLERS: AIR chillers inop" repeats the gate's own name.
            # Drop the restated opening, but only when what is left still
            # stands as a statement of its own.
            segment = _without_label_prefix(segment, normalised, label)
            normalised = _normalised_label(segment)
            if not normalised:
                continue
        if any(_normalised_label(text) == normalised for _, text in kept):
            continue
        # A segment the next one repeats in full is the form's label again.
        if any(
            _normalised_label(text).startswith(normalised + " ")
            for _, text in segments[index + 1:]
        ):
            continue
        kept.append((separator if kept else "", segment))
    return "".join(f"{separator}{segment}" for separator, segment in kept)


def _is_self_contained(subject: str) -> bool:
    """True when the subject stands on its own as a statement of the defect."""
    if not subject or not re.search(r"[A-Za-z]", subject):
        return False
    if not subject[0].isalnum():
        # "- GALLEY WASTE COMPARTMENT ACCESS DOOR INSTALLED)" is a slice out of
        # the middle of the cell, not the start of a statement.
        return False
    if subject.count("(") != subject.count(")") or subject.count("[") != subject.count("]"):
        return False
    if subject.rstrip()[-1] in ",;:/-&+(":
        return False
    if _MANUAL_HEADING.search(subject):
        # "SECTION MEL AND CMS REV 18NOV 25" is a manual heading, not a defect.
        return False
    trailing = _TRAILING_WORD.search(subject)
    if trailing and trailing.group(1).upper() in _OPEN_TAIL_WORDS:
        return False
    if _FORM_PLACEHOLDER.search(subject):
        return False
    if not [
        word
        for word in _WORD.findall(subject)
        if not _REFERENCE_TOKEN.match(word)
    ]:
        # Nothing but references to other paperwork.
        return False
    return True


def publishable_source_subject(value, item_label: str = "") -> str:
    """The declaration's subject, or "" when the source cell is not a statement."""
    subject = _SOURCE_ENTRY_PREFIX.sub("", clean(value)).lstrip(" :").strip()
    subject = _collapse_form_furniture(subject, item_label)
    if not _is_self_contained(subject):
        return ""
    return subject


def deferred_subject(value, item_label: str = "") -> str:
    """The declaration's identification of the defect, made readable."""
    return source_subject_sentence(publishable_source_subject(value, item_label))


_NEXT_DECLARATION = re.compile(
    r"\s+[A-Z]{2}\s+(?:CDDL|CDL|MEL|IFEDDL|IN|EN)\s+[A-Z0-9][A-Z0-9/.-]*", re.I,
)
_INTERIOR_ENTRY_MARKER = re.compile(r"\bMAINT(?:ENANCE)?\s+ENTRY\s*[.:]?\s*", re.I)
_REFERENCE_ONLY_OPENING = re.compile(
    r"^(?:WRT|FROM)\s+(?:(?:CDL|MEL|CDDL)\s+[0-9A-Z/-]+(?:,?\s+(?:AND\s+)?)?)+", re.I,
)
# Where the engineer stops describing the aircraft and starts asking for
# something, or where the form prints one of its own fields. The statement is
# cut here; the request is published as its analysed consequence. A shape this
# does not recognise stays in the statement, so the failure is a longer
# sentence, never a lost condition. A two- or three-digit token before UPLIFT is
# the CDDL form's own number ("923 UPLIFT TRASH BAG"); four digits is a year
# ("... UNTIL 10 JUNE 2027 / UPLIFT DRY ICE ...") and stays in the statement.
_REQUEST_OR_FORM_FIELD = re.compile(
    r"(?:^|\s+)(?:"
    r"X\s+PERFORMANCE\b|PERFORMANCE\s*\[P\]|(?:X\s+)?CLASS\s+[A-Z]\b(?=\s*(?:$|X\b))"
    r"|(?:\b\d{2,3}\s+)?UPLIFT\b"
    r"|DO\s+NOT\s+[A-Z]+\b"
    r"|(?:TO|PLS|PLSE|PLEASE)\s+(?:RE-?)?(?:UPLIFT|INSPECT|APPLY|CARRY|CHECK|CLEAN|REPLACE|MONITOR|ENSURE)\b"
    r")|(?<=[.,;])\s+(?:TO|PLS|PLSE|PLEASE)\s+(?=[A-Z])",
    re.I,
)


_MAINTENANCE_ACTION = re.compile(
    r"\b(?:UPLIFT|APPLY|APPLIED|REAPPLY|REAPPLIED|INSPECT\w*|CHECK(?:ED)?|PRIOR|BEFORE)\b", re.I,
)


def _is_dashed_header_title(source, description: str) -> bool:
    declaration = clean(source.get("source_declaration"))
    return bool(description) and bool(
        re.search(r"\s-\s*" + re.escape(description) + r"\s*$", declaration, re.I)
    )


def deferred_source_subject(source, item_label: str = "") -> str:
    """The declaration's whole statement of what is wrong, read across the wrap.

    The OFP's description cell wraps into the cell beneath it, so the first
    line is never the statement just because it parses as one: "LH WING,
    TRAILING EDGE ACCESS PANEL" is followed by "572HB SEAL FOUND TORN", and
    "FOUND RH AFT NOSE LANDING GEAR" by "DOOR SEAL PARTIALLY MISSING". The
    statement is the declaration's OWN text - its description and the
    continuation the parser bounded to it - from the engineer's entry to the
    first request or form field. Nothing is inferred from the reference, an
    unbound or borrowed tail is refused, and a statement that still cannot
    stand alone is not published.
    """
    description = clean(source.get("description"))
    own = clean(source.get("source_text"))
    if not own and description:
        own = " ".join(value for value in (description, clean(source.get("restriction"))) if value)
    bound = bool(description) and (
        own.upper() == description.upper() or own.upper().startswith(description.upper() + " ")
    )
    if not bound:
        # A segment whose text does not begin with its own description is not
        # evidence about this declaration.
        return deferred_subject(description, item_label)
    # Even a malformed stored segment must not borrow another item's defect.
    raw = _NEXT_DECLARATION.split(own, maxsplit=1)[0]
    interior = next(
        (match for match in _INTERIOR_ENTRY_MARKER.finditer(raw) if match.start() > 0), None,
    )
    if interior is not None:
        # "NON-ESSENTIAL EQUIPMENT AND FURNISHINGS / MAINT ENTRY LAVATORY LM46
        # NIL FLUSHING": what precedes the engineer's entry is the manual
        # item's printed title, already named by the declaration itself.
        raw = raw[interior.end():]
    elif description and len(raw) > len(description) and (
        _MANUAL_HEADING.search(description)
        or not description[0].isalnum()
        or _is_dashed_header_title(source, description)
    ):
        # A manual heading, a mid-cell bracket fragment, or the manual item's
        # title printed after a dash on the label line ("BB MEL 25-20-50A -
        # NON-ESSENTIAL EQUIPMENT AND FURNISHINGS") is form furniture, not the
        # beginning of the defect the following cell states. With no body at
        # all, the title is everything the OFP printed and is kept.
        raw = raw[len(description):].strip()
    raw = re.sub(r"^(?:MAINT ENTRY\s*[.:]?\s*)+", "", raw, flags=re.I)
    # A reference-only cell can precede an intact defect in the continuation.
    raw = _REFERENCE_ONLY_OPENING.sub("", raw)
    raw = re.sub(r"\bOTHERS?\s*\((?:PLS|PLEASE)\s+ENTER\s+COMMENTS?\)\s*", "", raw, flags=re.I)
    statement = _REQUEST_OR_FORM_FIELD.split(raw, maxsplit=1)[0].strip(" ,;:")
    # The first sentence says what is wrong. A later sentence is kept when it
    # states a further condition ("CB: ... TRIPPED & TAGGED.") and left to the
    # analysed consequences when it asks for maintenance action ("HST APPLIED,
    # CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE").
    sentences = re.split(r"(?<=[.!?])\s+", statement)
    statement = " ".join(
        [sentences[0], *(value for value in sentences[1:] if not _MAINTENANCE_ACTION.search(value))]
    )
    # The OFP closes a remark line with its own " X" separator; at the very end
    # of a statement it separates nothing.
    statement = re.sub(r"(?:\s+X)+\s*$", "", statement).strip(" ,;:")
    subject = deferred_subject(statement, item_label)
    if subject:
        return subject
    first_sentence = re.split(r"(?<=[.!?])\s+", statement, maxsplit=1)[0]
    return deferred_subject(first_sentence, item_label) or deferred_subject(description, item_label)


_ZFW_RESTRICTION = re.compile(r"\bZFW RESTRICTED TO\s+([\d,]+)\s*KGS?\b", re.I)


def page1_remark_consequences(remarks, fuel_summary) -> list[str]:
    """What the dispatcher's general page-1 remarks mean for this flight.

    These are the OFP's remarks, not any declaration's conditions: SQ24 15 Aug
    prints "ZFW RESTRICTED TO 161,229KGS DUE MTOW" under its one CDL, after a
    paragraph break, and the door seal does not limit the zero-fuel weight.
    """
    lines: list[str] = []
    for remark in remarks or []:
        limit = _ZFW_RESTRICTION.search(clean(remark.get("text") if isinstance(remark, dict) else remark))
        if not limit:
            continue
        limit_kg = int(limit.group(1).replace(",", ""))
        mass = ((fuel_summary or {}).get("masses_kg") or {}).get("pzfw")
        comparison = (
            f"Planned ZFW {mass:,.0f} kg gives {limit_kg - mass:,.0f} kg margin."
            if isinstance(mass, (int, float))
            else "Planned ZFW is not held for comparison."
        )
        line = f"OFP remark: ZFW restricted to {limit_kg:,.0f} kg. {comparison}"
        if line not in lines:
            lines.append(line)
    return lines


def held_page1_remarks(flight) -> list:
    """The flight's general remarks; for an analysis stored before they had a
    domain of their own, the ones an old parse left inside a declaration."""
    if isinstance((flight or {}).get("page1_remarks"), list):
        return flight["page1_remarks"]
    return [
        {"text": match.group(0)}
        for item in (flight or {}).get("deferred_items") or []
        for match in _ZFW_RESTRICTION.finditer(clean(item.get("company_remark")))
    ]


def deferred_consequence_rows(view):
    """Bind practical consequences to typed source segments, not MEL numbers.

    A reference number never determines an effect. Only explicit, non-negated
    source constraints activate the narrow rules below. Unknown effects are
    named and sent to the closing record instead of inventing a procedure.
    """
    rows = []
    for gate in view.get("deferred_dispatch_gates") or []:
        sources = gate.get("source_segments") or []
        # Titles from unresolved declarations may contain an old UI warning.
        title = deferred_item_label(clean(gate.get("title")))
        for source in sources or [{}]:
            # A shared MEL reference can cover different physical defects.
            # Analyse every segment before grouping identical consequences;
            # one recognised action must not hide an unassessed sibling.
            effects = []
            subjects = []
            description = clean(source.get("description"))
            raw = clean(source.get("source_text") or " ".join((description, clean(source.get("restriction"))))).upper()
            # The gate already names the item, so the form's own repeat of
            # that label is dropped rather than published a second time.
            subject = deferred_source_subject(source, title)
            if subject:
                subjects.append(subject)
            # Explicit uplift is a catering action, never an inferred MEL
            # allowance, dry-ice quantity or aircraft dispatch approval.
            if re.search(r"\b(?:UPLIFT(?:ED)?\s+DRY[- ]?ICE|DRY[- ]?ICE\s+(?:NEEDS TO BE UPLIFTED|REQ(?:UIRED)?))\b", raw) and not re.search(r"\b(?:NO|NOT|DO NOT)\s+(?:NEED\s+TO\s+)?UPLIFT\s+DRY[- ]?ICE|DRY[- ]?ICE\s+NOT\s+REQ", raw):
                effects.append("Catering must arrange the source-requested dry-ice uplift before departure; quantity and carriage limits are not established by the defect entry.")
            if re.search(r"\bUPLIFT\s+TRASH\s+BAGS?\b", raw) and not re.search(r"\b(?:NO|NOT|DO NOT)\s+UPLIFT\s+TRASH", raw):
                effects.append("Waste handling needs the source-requested trash bags for the unavailable compactor; the declaration supplies no aircraft performance penalty.")
            if "DO NOT USE LAVATORIES ON GROUND" in raw:
                effects.append("Ground turnaround must avoid using the affected lavatories; the source restriction is specific to ground use.")
            if ("FWD CARGO DOOR CTRL ACCESS PNL NOT FLUSH" in raw
                    and "TO INSPECT HST CONDITION AND REAPPLIED" in raw
                    and not re.search(r"\b(?:DO NOT|NOT TO)\s+INSPECT\b", raw)):
                effects.append("Forward cargo-door control-panel fit needs maintenance acceptance, including the source-requested HST inspection and reapplication; completion and an acceptable panel condition are not established.")
            if ("WASTE CONTAINER DOOR" in raw and "LATCH MISSING" in raw
                    and not re.search(r"\b(?:LATCH (?:IS )?NOT MISSING|NO MISSING LATCH)\b", raw)):
                effects.append("Waste-container door retention needs a permitted-configuration decision for the missing latch; the declaration does not establish an acceptable securing method or permission to use it.")
            seat = re.search(r"\bSEAT\s+(\d{1,2}[A-K])\b", raw)
            if seat and re.search(r"\bARMREST\b[^.]*\bSTUCK\b", raw) and not re.search(r"\b(?:NOT|NO LONGER)\s+STUCK\b", raw):
                effects.append(f"Seat {seat.group(1)} needs a seating-configuration decision for its stuck armrest before allocation; the declaration does not establish an occupied-seat allowance.")
            if re.search(r"\b(?:CHECKED|INSPECT\w*)\b.*\b(?:PRIOR|BEFORE)\s+(?:TO\s+)?EVERY\s+DEPARTURE\b", raw):
                effects.append("The source makes inspection a condition of every departure; carry that check into this flight's turnaround and operative Tech Log.")
            # An interim repair the declaration records is part of the state of
            # the aircraft, not a conclusion about it: publish that it is
            # applied and decline to say how long it stays acceptable.
            if (re.search(r"\bHST\s+(?:IS\s+|HAS\s+BEEN\s+)?(?:RE-?)?APPLIED\b", raw)
                    and not re.search(r"\bHST\b[^.]*\b(?:NOT|NEVER)\s+(?:RE-?)?APPLIED\b", raw)
                    and not any("HST" in effect for effect in effects)):
                effects.append("The declaration records HST applied as an interim condition; it does not establish how long that condition stays acceptable.")
            # A ZFW restriction is the dispatcher's general remark, never a
            # defect's own limit: see page1_remark_consequences.
            if source.get("item_type") == "CDL":
                effects.append("Reconcile this deferred external component with the approved CDL performance allowance for this aircraft; the declaration alone does not quantify a fuel or weight correction.")
            if not effects:
                # Keep an unanalysable defect identifiable, but do not invent
                # an airworthiness/dispatch conclusion.
                effects.append("The declaration does not establish the permitted configuration or flight limitation; its exact effect remains open in the closing release record.")
            subject = "; ".join(dict.fromkeys(subjects))
            indices = ([source["source_item_index"]] if isinstance(source.get("source_item_index"), int)
                       else gate.get("source_item_indices") or [])
            rows.append({"title": title, "subject": subject, "consequences": list(dict.fromkeys(effects)),
                         "references": gate.get("references") or [], "source_item_indices": indices,
                         "gate_id": gate.get("gate_id")})
    # Several gates can share a single action; publish their identities once.
    grouped = {}
    for row in rows:
        key = tuple(row["consequences"])
        grouped.setdefault(key, []).append(row)
    lines = []
    for consequences, group in grouped.items():
        titles = "; ".join(dict.fromkeys(r["title"] for r in group))
        subjects = list(dict.fromkeys(r["subject"] for r in group if r["subject"]))
        # The subject is what is wrong with the aircraft, and it is published
        # whether or not a rule could analyse it. An analysed consequence that
        # does not say what it is a consequence OF is not a finding: David's
        # own reference card names the defect ("The aft-most fan-cowl latch
        # access-panel latch is loose") before it states the condition.
        subject = "; ".join(value.rstrip(" .;") for value in subjects)
        identity = f"{titles}: " + (f"{subject}. " if subject else "")
        lines.append({
            "text": identity + " ".join(consequences),
            # The declaration's own subject, for a caller that lays the card
            # out itself (the ranked decision page) instead of printing
            # ``text``.
            "subject": subject,
            # The analysed sentences on their own, so a caller that already
            # names the item (a ranked decision card) does not repeat it.
            "consequences": list(consequences),
            "references": list(dict.fromkeys(reference for row in group for reference in row["references"])),
            "source_item_indices": list(dict.fromkeys(index for row in group for index in row["source_item_indices"])),
            "source_gate_ids": list(dict.fromkeys(row["gate_id"] for row in group if row["gate_id"])),
        })
    return lines


def deferred_consequences(view):
    return [row["text"] for row in deferred_consequence_rows(view)]


def airport_review_constraints(view, analyses):
    """Name the unresolved conclusion, never publish raw clauses or counts.

    These labels describe gaps in the existing assessment. They do not turn
    an unrecognised clause into a closure or declare a runway available.
    """
    from .airport_pdf_analysis import _SURFACE
    result = []
    for analysis in analyses:
        ids = set(analysis.get("unresolved_ids") or [])
        if not ids:
            continue
        panel = next((p for p in view.get("airport_operational_panels") or [] if p.get("icao") == analysis.get("icao")), {})
        topics = []
        for notice in panel.get("selected_notams") or []:
            if notice.get("notam_id") not in ids:
                continue
            raw = clean(notice.get("item_e_text")).upper()
            runways = list(dict.fromkeys(m.replace(" ", "") for m in _SURFACE.findall(raw)))
            scope = "RWY " + "/".join(dict.fromkeys(r for pair in runways for r in pair.split("/"))) if runways else "planned movement"
            if movement_clocks := re.findall(r"\b(?:TSAT|ELDT)\b", raw):
                topic = "/".join(dict.fromkeys(movement_clocks)) + " runway-availability conditions"
            elif re.search(r"\b(?:EXC|EXCEPT)\s+(?:TAX|TAXI)\b", raw):
                topic = "runway closure and taxi-exception extent"
            elif re.search(r"\b(?:IAC|AERONAUTICAL DATA TABULATION)\b", raw):
                topic = "approach-chart status and scope"
            elif "RETIL" in raw:
                topic = f"{scope} exit-lighting effect"
            elif re.search(r"\b(?:LOC|LOCALISER|LOCALIZER)\b", raw) and re.search(r"\b(?:INTRP|OSCILLATIONS|INTERFERENCE)\b", raw):
                topic = f"{scope} localizer interference"
            elif "FRICTION" in raw:
                topic = f"{scope} braking-performance effect"
            elif re.search(r"\b\d+-MIN\s+INSPECTION\b", raw):
                topic = "short-inspection timing"
            elif route := re.search(r"\bATS ROUTE\s+([A-Z]\d+)\b", raw):
                topic = f"{route.group(1)} clearance/equipment applicability"
            else:
                names = {"runway_closure": "runway closure timing", "taxiway_closure": "taxiway restriction extent", "approach_navaid_closure": "approach-aid serviceability", "runway_approach_restriction": "runway/procedure restrictions"}
                topic = names.get(notice.get('pertinence_kind'), 'obstacle effects on the approach' if notice.get('approach_affected') else 'movement restriction scope')
            topics.append(topic)
        if not topics:
            topics = ["source-linked movement assessment"]
        planned = clean(analysis.get("planned_runway"))
        role = "alternate" if analysis.get("role") == "destination alternate" else clean(analysis.get("role"))
        result.append(f"{analysis['icao']} {role}" + (f" RWY {planned}" if planned else "") + ": unresolved " + "; ".join(dict.fromkeys(topics)) + ".")
    return result


def release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts):
    """Specific source limits, grouped for a readable single closing page."""
    complete = {"HELD", "FOUND", "CHECKED · NO MATCH", "CHECKED · NO TRIGGER", "NOT APPLICABLE"}
    pending = {r["key"]: r for r in receipt["rows"] if r["state"] not in complete}
    groups = {"weather": [], "operations": [], "technical": []}
    weather, operations, technical = groups.values()
    weather_keys = {"metar_taf": "METAR/TAF", "sigmet": "SIGMET", "vaa_vaac": "VAA/VAAC", "tropical_cyclone": "TC advisory/SIGMET"}
    missing = [label for key, label in weather_keys.items() if key in pending]
    if missing:
        weather.append(f"{flight.get('departure', '?')}-{flight.get('destination', '?')} {window_label(flight)}: complete {', '.join(missing)} coverage is not established.")
    unresolved_sigmets = [clean(r.get("name")) for r in (view.get("hazards") or {}).get("sigmet_cards") or []
                          if r.get("disposition") == "REVIEW REQUIRED" and "does not intersect the polygon" not in str(r.get("screening") or "")]
    unassessed_ash = [clean(r.get("volcano") or r.get("name")) for r in (view.get("vaa") or {}).get("cfp_advisories") or []
                     if r.get("advisory_kind") == "CFP_VAA_NOTICE"]
    if unresolved_sigmets or unassessed_ash:
        affected = list(dict.fromkeys(filter(None, unresolved_sigmets + unassessed_ash)))
        weather.append(", ".join(affected) + ": held advisory route/time/level assessment is incomplete (weather / route hazards page).")
    cat = [label for key, label in (("wafs_sigwx", "WAFS/SIGWX"), ("airep_pirep", "AIREP/PIREP")) if key in pending]
    if cat:
        vws = (view.get("terrain") or {}).get("vws_review") or {}
        near = clean(vws.get("maximum_waypoint"))
        weather.append((f"VWS {vws.get('maximum_display')} at {near}: " if near else "CAT: ") + f"{' and '.join(cat)} corroboration missing; VWS alone does not establish CAT.")
    declared = view.get("deferred_dispatch_gates") or []
    if declared:
        names = ", ".join(dict.fromkeys(re.sub(r"\s*REVIEW REQUIRED", "", clean(g.get("title"))) for g in declared))
        technical.append(f"{names}: operative Tech Log confirmation and completion of the technical status actions are not recorded in this briefing.")
    candidate_groups = {}
    for extract in extracts:
        if extract.get("match_status") == "candidate":
            candidate_groups.setdefault(extract.get("deferred_entry_id"), []).append(extract)
    for candidates in candidate_groups.values():
        names = ", ".join(dict.fromkeys(f"{e['item_type']} {e['reference']}" for e in candidates))
        conditions = " ".join(dict.fromkeys(clean(e.get("ambiguity_reason")) + " " + clean(e.get("confirmation_required")) for e in candidates))
        technical.append(f"MEL/CDL candidates: {names}; no candidate selected. {conditions}")
    operations.extend(airport_review_constraints(view, [*airport_analysis, *alternate_analysis]))
    missing_geometry = [a["icao"] for a in airport_analysis if not any(
        o.get("icao") == a["icao"] and o.get("role") == a["role"] and o.get("bounds")
        and (o.get("featureCollection") or {}).get("features") for o in view.get("surface_overlays") or [])]
    if missing_geometry:
        operations.append("No validated surface figure: " + ", ".join(missing_geometry) + ". Official surface charts remain necessary.")
    if "airport_intelligence" in pending:
        stations = list(dict.fromkeys(a["icao"] for a in airport_analysis))
        operations.append("Released Airport Notes coverage incomplete: " + "/".join(stations) + ".")
    if "depressurisation_profile" in pending:
        events = (view.get("terrain") or {}).get("events") or []
        legs = ["-".join(dict.fromkeys([(e.get("first_high") or {}).get("name", "?"), (e.get("last_high") or {}).get("name", "?")])) for e in events]
        technical.append("Escape/depressurisation profile not bound" + (": " + ", ".join(legs) if legs else "") + "; high MSA alone is not an escape procedure.")
    if "edto" in pending:
        stations = list(dict.fromkeys(clean(a.get("airport")) for a in (view.get("edto") or {}).get("airports") or []))
        technical.append("EDTO checked-period suitability unresolved" + (": " + "/".join(stations) if stations else "") + " (weather / route hazards page).")
    if "enroute_notam" in pending:
        technical.append("Complete route-airspace assessment is not held for the filed route.")
    for key in ("ofp_parse", "flight_timing", "fuel_performance", "vws", "airports_alternates", "airport_notam"):
        if key in pending:
            target = weather if key == "vws" else operations if key in {"airports_alternates", "airport_notam"} else technical
            target.append(pending[key]["detail"])
    number = 1
    for key, lines in groups.items():
        groups[key] = []
        for line in dict.fromkeys(lines):
            groups[key].append(f"{number}. {line}")
            number += 1
    return groups


def release_conditions(flight, view, receipt, airport_analysis, alternate_analysis, extracts):
    groups = release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts)
    return [line for lines in groups.values() for line in lines] or ["1. No unresolved automated source condition is recorded; crew operational release remains separate."]
