"""Does a notice that limits a movement area by aircraft size concern THIS aircraft?

Boss, 9 Sep 2026, Hong Kong SQ882: the briefing said "TWY E ... downgraded to
code E" and stopped. A label is not an answer - the pilot still had to know that
an A350-900 is itself Code E and work out which side of the limit that puts it.

This is the ODSS evaluator of ONE specification. The app evaluates the same
rules in ``aircraft-restriction-applicability.mjs``; ``aircraft_restriction_rules.json``
here is a byte-identical copy of the app's generated file, and both suites
replay the same hand-written vectors (``tests/fixtures/aircraft-restriction-vectors.json``),
so the dashboard, Decision Analysis, the PDF and HelpYou cannot disagree. Change
the rules in the app's ``aircraft-restriction-rules.mjs``, regenerate, copy the
JSON across and update the pinned digest in both suites - never edit it here.

What it is NOT. A code letter is a planning dimension (a wingspan band), and
EASA CS-ADR-DSN GM1 ADR-DSN.A.005(d) says it is not intended to regulate the
operation of an aircraft. A favourable comparison is therefore reported as
"within this limit" and never as a clearance. Timing, location and every other
restriction stay with the engines that already own them; nothing here reads a
date. An unknown or conflicting aircraft, a wording outside the closed grammar,
two different limits in one notice, or a span within rounding of the limit all
stay unknown/review - never a guess.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

_RULES_FILE = Path(__file__).with_name("aircraft_restriction_rules.json")
_CODE_ORDER = "ABCDEF"
_FEET_TO_METRES = 0.3048
_SENTENCE_BOUNDARY = re.compile(r"(?:[;\n]|(?<!\d)\.(?!\d))")
_CLASS_SEMANTICS = {"prohibited_code_class", "prohibited_wingspan_class"}
_NOT_A_CLEARANCE = "Size check only, not a clearance; other restrictions still apply."
_CONDITION_QUOTE_MAX_WORDS = 12
_CONDITION_QUOTE_MAX_CHARS = 80
_CONDITION_QUOTES_SHOWN = 2
_QUOTE_LEAD_WORDS = 3
_RELATION = {
    "within_limit": "within",
    "exceeds_limit": "above",
    "in_restricted_class": "inside the class named by",
    "outside_restricted_class": "outside the class named by",
}


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    return json.loads(_RULES_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _forms() -> tuple[tuple[dict[str, Any], re.Pattern[str]], ...]:
    return tuple((form, re.compile(form["pattern"])) for form in rules()["restrictionForms"])


@lru_cache(maxsize=1)
def _markers() -> tuple[tuple[dict[str, Any], re.Pattern[str]], ...]:
    return tuple((marker, re.compile(marker["pattern"])) for marker in rules()["conditionMarkers"])


@lru_cache(maxsize=1)
def _guards() -> tuple[tuple[dict[str, Any], re.Pattern[str]], ...]:
    return tuple((guard, re.compile(guard["pattern"])) for guard in rules()["readingGuards"])


@lru_cache(maxsize=1)
def _negation() -> re.Pattern[str]:
    return re.compile(rules()["qualifierContext"]["negation"])


@lru_cache(maxsize=1)
def _limit_vocabulary() -> re.Pattern[str]:
    return re.compile(rules()["qualifierContext"]["limitVocabulary"])


@lru_cache(maxsize=1)
def _clause_boundary() -> re.Pattern[str]:
    return re.compile(rules()["qualifierContext"]["clauseBoundary"])


@lru_cache(maxsize=1)
def _excused() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((rule["markerId"], re.compile(rule["pattern"])) for rule in rules()["qualifierContext"]["excused"])


@lru_cache(maxsize=1)
def _not_reversal() -> tuple[dict[str, Any], tuple[dict[str, Any], ...], re.Pattern[str], re.Pattern[str]]:
    context = rules()["qualifierContext"]["notReversal"]
    usages = tuple({"pattern": re.compile(usage["pattern"]),
                    "proof": context["proofs"][usage["proof"]],
                    "before": re.compile(context["proofs"][usage["proof"]]["before"]),
                    "after": re.compile(context["proofs"][usage["proof"]]["after"])}
                   for usage in context["usages"])
    return (context, usages,
            re.compile(context["precedingReference"]), re.compile(context["subjectVocabulary"]))


def _blank_non_reversal_usages(text: str, limit_index: int = -1, limit_length: int = 0) -> str:
    """Spec v13 (F26/F27): prove the owner and continuation on original text.

    A leading parsed limit may precede an independent locative/setting only
    with a closed movement-area subject and an explicit join. All vetoes keep
    reading original text. Unknown subjects or objects cannot be swallowed.
    Positive
    place/setting patterns alone are eligible; bare FULL REVERSE and imperative END STAND are not proof. Blank only
    the exact eligible word, preserving offsets and every other qualifier, including later reversals. This
    intentionally stays cautious when a mixed clause's scope is unclear.
    """
    vocabulary = _limit_vocabulary()
    context, usages, preceding_reference, subject_vocabulary = _not_reversal()
    limit_subject = re.compile(context["ownLimitSubject"])
    limit_join = re.compile(context["ownLimitJoin"])
    blanked = text
    for begin, finish in _clause_ranges(text, rules()["qualifierContext"]["notReversal"]["scopeBoundary"]):
        clause = text[begin:finish]
        if subject_vocabulary.search(clause):
            continue
        for usage in usages:
            for match in usage["pattern"].finditer(clause):
                if preceding_reference.search(clause[:match.start()]):
                    continue
                # Include the usage: a designator must not swallow CODE, etc.
                if vocabulary.search(clause[match.start():]):
                    continue
                if not usage["after"].search(clause[match.end():]):
                    continue
                before = clause[:match.start()]
                if not usage["before"].search(before):
                    limit_at = limit_index - begin
                    limit_end = limit_at + limit_length
                    if (not usage["proof"].get("allowOwnLimit") or limit_at < 0 or limit_end > match.start()
                            or not limit_subject.search(clause[:limit_at])):
                        continue
                    before = clause[limit_end:match.start()]
                    join = limit_join.search(before)
                    if not join or not usage["before"].search(before[join.end():]):
                        continue
                at = begin + match.start(2)
                end = begin + match.end(2)
                blanked = f"{blanked[:at]}{' ' * (end - at)}{blanked[end:]}"
    return blanked


def _excused_occurrences(stretch: str) -> list[tuple[str, int]]:
    """The exact qualifier words spec v6 proves are about something else (F15/F16).

    Each excused pattern ends with ONE captured word; only the qualifier at that word is excused, and only where the
    matched stretch names no limit vocabulary.
    """
    vocabulary = _limit_vocabulary()
    return [
        (marker_id, match.start(1))
        for marker_id, pattern in _excused()
        for match in pattern.finditer(stretch)
        if not vocabulary.search(match.group(0))
    ]


@lru_cache(maxsize=1)
def _rule_by_alias() -> dict[str, dict[str, Any]]:
    return {alias: rule for rule in rules()["aircraft"] for alias in rule["aliases"]}


def spec_version() -> str:
    return str(rules()["specVersion"])


def _number(value: float) -> str:
    """The shortest decimal, as JavaScript prints a number (36, 68.6, 64.75)."""
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def aerodrome_code_letter_for_wingspan(wingspan_m: Any) -> str | None:
    """ICAO Annex 14 Vol I Table 1-1: bands are "up to but not including"."""
    try:
        span = float(wingspan_m)
    except (TypeError, ValueError):
        return None
    if not span > 0:
        return None
    for band in rules()["codeLetterTable"]["bands"]:
        if band["minM"] <= span < band["maxExclusiveM"]:
            return band["code"]
    return None


def _normalized_aircraft_type(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).strip()).upper()


def assess_aircraft_aerodrome_code(
    aircraft_type: Any,
    explicit_governed_code: Any = None,
) -> dict[str, Any]:
    """Mirror of the app's ``assessAircraftAerodromeCode``: closed catalogue, no family guess."""
    normalized = _normalized_aircraft_type(aircraft_type)
    supplied = str(explicit_governed_code or "").strip()
    explicit = supplied.upper() if re.fullmatch(r"[A-Fa-f]", supplied) else None
    rule = _rule_by_alias().get(normalized)

    def assessment(**values: Any) -> dict[str, Any]:
        return {
            "status": values["status"],
            "code": values.get("code"),
            "derivedCode": values.get("derivedCode"),
            "explicitGovernedCode": values.get("explicitGovernedCode"),
            "normalizedAircraftType": normalized or None,
            "ruleId": rule["ruleId"] if rule else None,
            "aircraftFamily": rule["aircraftFamily"] if rule else None,
            "wingspanM": rule["wingspanM"] if rule else None,
            "basis": values["basis"],
            "reviewReason": values.get("reviewReason"),
        }

    if supplied and not explicit:
        return assessment(
            status="review_required", derivedCode=rule["code"] if rule else None,
            basis="invalid_explicit_governed_code",
            reviewReason="The explicit governed aerodrome code is not Code A, B, C, D, E, or F.",
        )
    if not rule:
        return assessment(
            status="review_required" if explicit else "unknown", explicitGovernedCode=explicit,
            basis="no_approved_aircraft_rule",
            reviewReason=(
                f"Code {explicit} could not be checked because aircraft type {normalized or 'UNKNOWN'} "
                "has no approved applicability rule."
                if explicit
                else f"Aircraft type {normalized or 'UNKNOWN'} has no approved aerodrome-code rule."
            ),
        )
    if explicit and explicit != rule["code"]:
        return assessment(
            status="review_required", derivedCode=rule["code"], explicitGovernedCode=explicit,
            basis="explicit_code_conflicts_with_official_derivation",
            reviewReason=(
                f"Explicit Code {explicit} conflicts with the source-backed "
                f"{rule['aircraftFamily']} derivation of Code {rule['code']}."
            ),
        )
    return assessment(
        status="confirmed", code=rule["code"], derivedCode=rule["code"], explicitGovernedCode=explicit,
        basis=(
            "explicit_governed_code_confirmed_against_official_derivation"
            if explicit
            else "official_aircraft_dimensions_and_icao_threshold"
        ),
    )


def _normalized_notice_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().upper()


def _sentence_bounds(text: str, index: int, length: int) -> tuple[int, int]:
    start, end = 0, len(text)
    for boundary in _SENTENCE_BOUNDARY.finditer(text):
        if boundary.start() < index:
            start = boundary.start() + 1
        elif boundary.start() >= index + length:
            end = boundary.start()
            break
    return start, end


def _unread_reason(text: str, index: int, length: int) -> dict[str, str] | None:
    """Is the matched phrase the WHOLE limit its clause states?

    Codex review, 22 Sep 2026: "CLSD FOR ACFT CODE E AND F" was read as "Code E"
    and "NOT RESTRICTED TO MAX ACFT CODE C" as a Code C limit. A guard that
    fires means the phrase is only part of the clause, and it is not compared.
    """
    start, end = _sentence_bounds(text, index, length)
    clause_start, clause_end = next(
        ((begin, finish) for begin, finish in _clause_ranges(text) if begin <= index < finish), (start, end)
    )
    def views_of(source: str) -> dict[str, str]:
        return {
            "sentence_before": source[start:index],
            "sentence": source[start:end],
            "clause": source[clause_start:clause_end],
            "before": source[start:index],
            "after": source[index + length:end],
        }

    views = views_of(text)
    # Resolve usage before a limit or a view can hide its object (F25).
    reversal_views = views_of(_blank_non_reversal_usages(text, index, length))
    guard_id = _not_reversal()[0]["guardId"]
    for guard, pattern in _guards():
        where = guard["where"]
        view = reversal_views[where] if guard["id"] == guard_id else views[where]
        if pattern.search(view):
            return {"id": guard["id"], "label": guard["label"]}
    return None


def _clause_ranges(text: str, boundary: str | None = None) -> list[tuple[int, int]]:
    """Every clause of the notice as [start, end) ranges: a sentence, split again at each LIDO list item (" - ").

    Spec v4 (F7, WSSS SX168/26).
    """
    ranges: list[tuple[int, int]] = []
    start = 0
    pattern = re.compile(boundary) if boundary is not None else _clause_boundary()
    for match in pattern.finditer(text):
        ranges.append((start, match.start()))
        start = match.end()
    ranges.append((start, len(text)))
    return [(begin, finish) for begin, finish in ranges if text[begin:finish].strip()]


def _tidy(value: str) -> str:
    return re.sub(r"^[,:.\s]+|[,:.\s]+$", "", re.sub(r"\s+", " ", value).strip())


def _bounded_quote(stretch: str, first_qualifier_offset: int) -> str:
    """The notice's own qualifying words, bounded.

    The quote is the WHOLE stretch so a negator can never be cut off it ("DOES
    NOT APPLY TO A350" must not become "APPLY TO A350"); only a stretch too long
    to quote is windowed, starting a few words before its first qualifier.
    """
    clean = _tidy(stretch)
    words = clean.split(" ")
    if len(words) <= _CONDITION_QUOTE_MAX_WORDS and len(clean) <= _CONDITION_QUOTE_MAX_CHARS:
        return clean
    lead = _tidy(stretch[:max(0, first_qualifier_offset)])
    begin = max(0, (len(lead.split(" ")) if lead else 0) - _QUOTE_LEAD_WORDS)
    window = words[begin:begin + _CONDITION_QUOTE_MAX_WORDS]
    quote = " ".join(window)
    cut_at_end = begin + len(window) < len(words)
    if len(quote) > _CONDITION_QUOTE_MAX_CHARS:
        quote = quote[:_CONDITION_QUOTE_MAX_CHARS].rstrip()
        cut_at_end = True
    return f"{'...' if begin > 0 else ''}{quote}{'...' if cut_at_end else ''}"


def _notice_conditions(text: str, index: int, length: int) -> list[dict[str, Any]]:
    """Every qualifier anywhere in the notice, outside the limit phrase itself.

    Codex fix2 review, 22 Sep 2026: "... CODE C. THIS LIMIT DOES NOT APPLY TO A350
    ACFT.", "... A350 ACFT ARE EXEMPT." and "... CODE C NOT APPLICABLE TO A350 ACFT"
    still concluded an exclusion. A condition, exception, exemption, applicability
    statement, permission or reversal counts wherever it stands; a bare negation
    counts where it can be about the limit - after the phrase in its own clause,
    or in a clause that speaks of aircraft or limits. Spec v4 reads clause by
    clause; spec v5 (F14) never skips a clause and, in a clause other than the
    limit's own, excuses only the qualifier matches ``qualifierContext.excused``
    proves are about something else (a feature's passive reversal, a WHEN inside
    an advisory), where that stretch names no limit vocabulary. One entry per
    qualifying stretch, in notice order.
    """
    masked = f"{text[:index]}{' ' * length}{text[index + length:]}"
    reversal_text = _blank_non_reversal_usages(text, index, length)
    limit_end = index + length
    context = rules()["qualifierContext"]
    negation = _negation()
    vocabulary = _limit_vocabulary()
    conditions: list[dict[str, Any]] = []
    for begin, finish in _clause_ranges(masked):
        own = begin <= index < finish
        stretches = [(begin, index), (limit_end, finish)] if own else [(begin, finish)]
        for start, end in stretches:
            stretch = masked[start:end]
            if not stretch.strip():
                continue
            excused = [] if own else _excused_occurrences(stretch)
            reversal_stretch = reversal_text[start:end]
            reversal_marker = _not_reversal()[0]["markerId"]
            found: list[dict[str, Any]] = []
            for marker, pattern in _markers():
                read = reversal_stretch if marker["id"] == reversal_marker else stretch
                for match in pattern.finditer(read):
                    if any(marker["id"] == marker_id and match.start() == at for marker_id, at in excused):
                        continue
                    found.append({"id": marker["id"], "label": marker["label"], "at": match.start()})
            negation_counts = (start == limit_end) if own else bool(vocabulary.search(stretch))
            if negation_counts:
                for match in negation.finditer(stretch):
                    found.append({"id": "negation", "label": context["negationLabel"], "at": match.start()})
            if not found:
                continue
            found.sort(key=lambda entry: entry["at"])
            ids: list[str] = []
            for entry in found:
                if entry["id"] not in ids:
                    ids.append(entry["id"])
            conditions.append({
                "id": found[0]["id"],
                "label": found[0]["label"],
                "ids": ids,
                "text": _bounded_quote(stretch, found[0]["at"]),
            })
    return conditions


def _class_direction(word: str | None) -> str:
    if not word:
        return "exact"
    return "and_above" if word in {"ABV", "ABOVE", "HIGHER", "LARGER"} else "and_below"


@lru_cache(maxsize=1)
def _scope_patterns() -> dict[str, re.Pattern[str]]:
    return {name: re.compile(pattern) for name, pattern in rules()["restrictionScope"].items()}


def _scope_key(subject: str) -> str:
    return _scope_patterns()["aircraftPrefix"].sub("", subject)


def _restriction_scope(text: str, match: re.Match[str], subject: str | None) -> dict[str, Any]:
    """Bind the limit to its stated source subject; never substitute a summary."""
    unresolved = {"status": "unresolved", "subjects": []}
    patterns = _scope_patterns()
    begin, end = next((start, finish) for start, finish in _clause_ranges(text)
                      if start <= match.start() < finish)
    before = text[begin:match.start()]
    boundaries = list(patterns["prefixBoundary"].finditer(before))
    if boundaries:
        before = before[boundaries[-1].end():]
    candidates = []
    if subject:
        if not patterns["subject"].search(subject.strip()):
            return unresolved
        candidates.append(subject.strip())
    else:
        preceding = patterns["before"].search(before)
        if preceding:
            candidates.append(preceding.group(1))
    after = text[match.end():end]
    following = patterns["after"].search(after)
    if following:
        candidates.append(following.group(1))
    else:
        # A named parent area does not establish its complete scope. Account
        # for the whole continuation before a positively independent record.
        next_record = patterns["independentRecord"].search(after)
        complete = (patterns["beforeRecord"].search(after[:next_record.start()]) if next_record
                    else patterns["continuation"].search(after))
        if not complete:
            return unresolved
    if not candidates or any(_scope_key(value) != _scope_key(candidates[0]) for value in candidates):
        return unresolved
    return {"status": "stated", "subjects": [candidates[0]]}


def _reading_from(form: dict[str, Any], match: re.Match[str], text: str) -> dict[str, Any]:
    def group(name: str) -> str | None:
        position = form["groups"].get(name)
        return match.group(position) if position else None

    reading: dict[str, Any] = {
        "formId": form["id"],
        "kind": form["kind"],
        "semantics": form["semantics"],
        "evidence": match.group(0),
        "index": match.start(),
        "otherConditions": _notice_conditions(text, match.start(), len(match.group(0))),
    }
    unread = _unread_reason(text, match.start(), len(match.group(0)))
    if unread:
        reading["unread"] = unread
    subject = group("subject")
    if subject:
        reading["subject"] = subject.strip()
    reading["scope"] = _restriction_scope(text, match, subject)
    if form["kind"] == "aerodrome_code":
        reading["code"] = group("code")
        if form["semantics"] == "prohibited_code_class":
            reading["classDirection"] = _class_direction(group("direction"))
        return reading
    value = float(group("value") or 0)
    unit = group("unit")
    reading["limitValue"] = value
    reading["limitUnit"] = unit
    reading["limitM"] = value * _FEET_TO_METRES if unit == "FT" else value
    reading["inclusive"] = bool(form.get("inclusive"))
    return reading


def _same_limit(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(left.get("unread")) == bool(right.get("unread")) and all(
        left.get(key) == right.get(key)
        for key in ("kind", "semantics", "code", "classDirection", "limitM", "inclusive")
    )


def read_aircraft_size_restrictions(value: Any) -> list[dict[str, Any]]:
    """Every aircraft-size limit the closed grammar reads, in text order, one per distinct limit."""
    text = _normalized_notice_text(value)
    if not text:
        return []
    found: list[dict[str, Any]] = []
    for form, pattern in _forms():
        for match in pattern.finditer(text):
            end = match.end()
            if any(match.start() < entry["end"] and entry["index"] < end for entry in found):
                continue
            found.append({**_reading_from(form, match, text), "end": end})
    found.sort(key=lambda entry: entry["index"])
    distinct: list[dict[str, Any]] = []
    for entry in found:
        reading = {key: item for key, item in entry.items() if key != "end"}
        held = next((row for row in distinct if _same_limit(row, reading)), None)
        if held is None:
            distinct.append(reading)
            continue
        if held["scope"]["status"] != "stated" or reading["scope"]["status"] != "stated":
            held["scope"] = {"status": "unresolved", "subjects": []}
        else:
            for subject in reading["scope"]["subjects"]:
                if all(_scope_key(value) != _scope_key(subject) for value in held["scope"]["subjects"]):
                    held["scope"]["subjects"].append(subject)
        for condition in reading["otherConditions"]:
            if all(row["id"] != condition["id"] for row in held["otherConditions"]):
                held["otherConditions"].append(condition)
    return distinct


def _limit_label(reading: dict[str, Any]) -> str:
    if reading["kind"] == "aerodrome_code":
        if reading["semantics"] != "prohibited_code_class":
            return f"Code {reading['code']}"
        if reading.get("classDirection") == "and_above":
            return f"Code {reading['code']} and above"
        if reading.get("classDirection") == "and_below":
            return f"Code {reading['code']} and below"
        return f"Code {reading['code']}"
    stated = (
        f"{_number(reading['limitValue'])} ft ({reading['limitM']:.2f} m)"
        if reading["limitUnit"] == "FT"
        else f"{_number(reading['limitValue'])} m"
    )
    if reading["semantics"] == "prohibited_wingspan_class":
        return f"wingspan more than {stated}"
    return f"wingspan up to {stated}" if reading["inclusive"] else f"wingspan below {stated}"


def _public_aircraft(assessment: dict[str, Any], type_source: str | None) -> dict[str, Any]:
    return {
        "type": assessment["normalizedAircraftType"],
        "typeSource": type_source or None,
        "status": assessment["status"],
        "code": assessment["code"],
        "wingspanM": assessment["wingspanM"] if assessment["status"] == "confirmed" else None,
        "ruleId": assessment["ruleId"],
        "aircraftFamily": assessment["aircraftFamily"],
        "reviewReason": assessment["reviewReason"],
    }


def _public_restriction(reading: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in reading.items() if key != "index"},
        "limitLabel": _limit_label(reading),
    }


def _result(
    *,
    status: str,
    reason: str,
    sentence: str,
    outcome: str | None = None,
    restriction: dict[str, Any] | None = None,
    aircraft: dict[str, Any] | None = None,
    detail: str | None = None,
    comparison: dict[str, Any] | None = None,
    unread: dict[str, Any] | None = None,
) -> dict[str, Any]:
    concerns = (
        True if outcome in {"exceeds_limit", "in_restricted_class"}
        else False if outcome in {"within_limit", "outside_restricted_class"}
        else None
    )
    return {
        "specVersion": spec_version(),
        "codeTableRuleId": rules()["codeLetterTable"]["ruleId"],
        "status": status,
        "outcome": outcome,
        "restrictsThisAircraft": concerns,
        # A comparison never authorises anything.
        "operationalPermission": False,
        "reason": reason,
        # The pure size relation, kept even when the conclusion above is withheld.
        "comparison": comparison,
        # Set when a limit phrase matched but its clause was not fully read.
        "unread": unread,
        "restriction": restriction,
        "aircraft": aircraft,
        "sentence": sentence,
        "detail": detail,
    }


def _compare_code(reading: dict[str, Any], aircraft_code: str) -> tuple[str | None, str]:
    aircraft = _CODE_ORDER.index(aircraft_code)
    limit = _CODE_ORDER.index(reading["code"])
    if reading["semantics"] == "maximum_code":
        if aircraft <= limit:
            return "within_limit", (
                "aircraft_code_equals_maximum" if aircraft == limit else "aircraft_code_below_maximum"
            )
        return "exceeds_limit", "aircraft_code_above_maximum"
    if reading["semantics"] == "code_only":
        if aircraft == limit:
            return "within_limit", "aircraft_code_equals_named_code"
        if aircraft > limit:
            return "exceeds_limit", "aircraft_code_above_named_code"
        return None, "smaller_aircraft_not_addressed_by_notice"
    direction = reading.get("classDirection")
    in_class = (
        aircraft >= limit if direction == "and_above"
        else aircraft <= limit if direction == "and_below"
        else aircraft == limit
    )
    return (
        ("in_restricted_class", "aircraft_code_in_restricted_class")
        if in_class
        else ("outside_restricted_class", "aircraft_code_outside_restricted_class")
    )


def _compare_wingspan(reading: dict[str, Any], wingspan_m: float) -> tuple[str | None, str]:
    if abs(wingspan_m - reading["limitM"]) < rules()["wingspanComparisonToleranceM"]:
        return None, "wingspan_within_rounding_of_limit"
    if reading["semantics"] == "maximum_wingspan":
        return (
            ("within_limit", "wingspan_below_limit")
            if wingspan_m < reading["limitM"]
            else ("exceeds_limit", "wingspan_above_limit")
        )
    return (
        ("in_restricted_class", "wingspan_in_restricted_class")
        if wingspan_m > reading["limitM"]
        else ("outside_restricted_class", "wingspan_outside_restricted_class")
    )


def _aircraft_phrase(aircraft: dict[str, Any], reading: dict[str, Any]) -> str:
    span = f"{_number(aircraft['wingspanM'])} m wingspan"
    if reading["kind"] == "aerodrome_code":
        return f"{aircraft['type']} is Code {aircraft['code']} ({span})"
    return f"{aircraft['type']} has a {span}"


def _quoted_conditions(reading: dict[str, Any]) -> str:
    """The notice's own condition words, quoted, so the pilot sees WHAT is unresolved."""
    shown = [f'"{entry["text"]}"' for entry in reading["otherConditions"][:_CONDITION_QUOTES_SHOWN]]
    more = len(reading["otherConditions"]) - len(shown)
    return " and ".join(shown) + (f" and {more} more" if more > 0 else "")


def _unresolved_condition_sentence(relation: str, aircraft: dict[str, Any], reading: dict[str, Any]) -> str:
    """The size relation is stated; the conclusion is not."""
    return (
        f"{_aircraft_phrase(aircraft, reading)}: {_RELATION[relation]} the stated limit ({_limit_label(reading)}). "
        f"The notice also says {_quoted_conditions(reading)}, which this check cannot resolve, so whether the limit "
        "applies to this flight was not decided. Read the notice."
    )


def _outcome_sentence(outcome: str, aircraft: dict[str, Any], reading: dict[str, Any]) -> str:
    who = _aircraft_phrase(aircraft, reading)
    limit = _limit_label(reading)
    if outcome == "within_limit":
        return f"{who}: within this limit ({limit}). {_NOT_A_CLEARANCE}"
    if outcome == "exceeds_limit":
        return f"{who}: above this limit ({limit}), so the notice excludes this aircraft from the stated area."
    if outcome == "in_restricted_class":
        return f"{who}: inside the restricted class ({limit}), so the notice applies to this aircraft."
    return f"{who}: outside the restricted class ({limit}). {_NOT_A_CLEARANCE}"


def assess_aircraft_restriction_applicability(
    notice_text: Any,
    aircraft_type: Any = None,
    *,
    explicit_governed_code: Any = None,
    aircraft_type_source: str | None = None,
) -> dict[str, Any] | None:
    """Compare one notice against one aircraft; ``None`` when no size limit is stated."""
    readings = read_aircraft_size_restrictions(notice_text)
    if not readings:
        return None

    assessment = assess_aircraft_aerodrome_code(aircraft_type, explicit_governed_code)
    aircraft = _public_aircraft(assessment, aircraft_type_source)

    unread = next((entry for entry in readings if entry.get("unread")), None)
    if unread:
        return _result(
            status="review_required",
            reason="size_limit_wording_not_fully_read",
            unread={**unread["unread"], "matched": unread["evidence"]},
            aircraft=aircraft,
            sentence=(
                "This notice words an aircraft-size limit in a way the verified rules do not fully read "
                f"({unread['unread']['label']}), so it was not compared. Read the notice."
            ),
            detail=f'Matched only "{unread["evidence"]}"; guard {unread["unread"]["id"]}.',
        )

    if len(readings) > 1:
        labels = "; ".join(_limit_label(entry) for entry in readings)
        evidence = ", ".join(f'"{entry["evidence"]}"' for entry in readings)
        return _result(
            status="review_required",
            reason="notice_states_more_than_one_aircraft_size_limit",
            aircraft=aircraft,
            sentence=(
                f"This notice states more than one aircraft-size limit ({labels}); which one "
                "applies to each area was not decided. Read the notice."
            ),
            detail=f"Limits read: {evidence}.",
        )

    reading = readings[0]
    restriction = _public_restriction(reading)

    if assessment["status"] != "confirmed":
        unknown = assessment["status"] == "unknown"
        aircraft_label = assessment["normalizedAircraftType"] or "this aircraft"
        why = (
            f"no verified size data is held for {aircraft_label}"
            if unknown
            else f"the aircraft code for {aircraft_label} needs review"
        )
        return _result(
            status="unknown" if unknown else "review_required",
            reason="aircraft_size_not_verified" if unknown else "aircraft_code_conflict",
            restriction=restriction,
            aircraft=aircraft,
            sentence=(
                f"This limit ({restriction['limitLabel']}) was not compared: {why}. "
                "Compare it against the notice yourself."
            ),
            detail=assessment["reviewReason"],
        )

    outcome, reason = (
        _compare_code(reading, assessment["code"])
        if reading["kind"] == "aerodrome_code"
        else _compare_wingspan(reading, float(assessment["wingspanM"]))
    )

    if outcome is None:
        who = _aircraft_phrase(aircraft, reading)
        sentence = (
            f"{who}. The notice names Code {reading['code']} only and does not say whether smaller "
            "aircraft are included; not decided. Read the notice."
            if reason == "smaller_aircraft_not_addressed_by_notice"
            else f"{who}, within rounding of this limit ({restriction['limitLabel']}); not decided by "
            "arithmetic. Check the aircraft's exact span against the notice."
        )
        return _result(
            status="review_required", reason=reason, restriction=restriction,
            aircraft=aircraft, sentence=sentence,
        )

    comparison = {"relation": outcome, "basis": reason}
    if reading["otherConditions"]:
        conditions = "; ".join(f'{entry["id"]} "{entry["text"]}"' for entry in reading["otherConditions"])
        return _result(
            status="review_required",
            reason="unresolved_condition_in_notice",
            comparison=comparison,
            restriction=restriction,
            aircraft=aircraft,
            sentence=_unresolved_condition_sentence(outcome, aircraft, reading),
            detail=(
                f"Rule {assessment['ruleId']}; code table {rules()['codeLetterTable']['ruleId']}; "
                f'read from "{reading["evidence"]}"; conditions: {conditions}.'
            ),
        )

    return _result(
        status="confirmed",
        outcome=outcome,
        reason=reason,
        comparison=comparison,
        restriction=restriction,
        aircraft=aircraft,
        sentence=_outcome_sentence(outcome, aircraft, reading),
        detail=(
            f"Rule {assessment['ruleId']}; code table {rules()['codeLetterTable']['ruleId']}; "
            f'read from "{reading["evidence"]}".'
        ),
    )


def notam_aircraft_size_check(flight: dict[str, Any] | None, item: dict[str, Any] | None) -> dict[str, Any] | None:
    """The comparison for one analysed NOTAM record of one uploaded OFP flight."""
    if not isinstance(item, dict):
        return None
    notice = str(item.get("item_e_text") or item.get("raw_text") or item.get("text") or "")
    if not notice.strip():
        return None
    return assess_aircraft_restriction_applicability(
        notice,
        (flight or {}).get("aircraft_type"),
        aircraft_type_source="uploaded_ofp",
    )
