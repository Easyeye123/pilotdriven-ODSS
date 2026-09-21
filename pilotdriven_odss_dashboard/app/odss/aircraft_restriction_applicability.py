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
    views = {
        "sentence_before": text[start:index],
        "sentence": text[start:end],
        "before": text[start:index],
        "after": text[index + length:end],
    }
    for guard, pattern in _guards():
        if pattern.search(views[guard["where"]]):
            return {"id": guard["id"], "label": guard["label"]}
    return None


def _quoted_condition(text: str, index: int) -> str:
    """The notice's own condition words from a marker to the end of its sentence, bounded."""
    _, end = _sentence_bounds(text, index, 1)
    words = text[index:end].strip().split(" ")[:_CONDITION_QUOTE_MAX_WORDS]
    quote = " ".join(words)
    if len(quote) > _CONDITION_QUOTE_MAX_CHARS:
        quote = f"{quote[:_CONDITION_QUOTE_MAX_CHARS].rstrip()}..."
    return re.sub(r"[,:]+$", "", quote)


def _notice_conditions(text: str, index: int, length: int) -> list[dict[str, str]]:
    """Every condition marker anywhere in the notice, outside the limit phrase itself."""
    masked = f"{text[:index]}{' ' * length}{text[index + length:]}"
    found: list[dict[str, Any]] = []
    for marker, pattern in _markers():
        for match in pattern.finditer(masked):
            found.append({
                "id": marker["id"], "label": marker["label"], "at": match.start(),
                "text": _quoted_condition(masked, match.start()),
            })
    # Stable, like the app's sort: by position, markers keep their catalogue order on a tie.
    found.sort(key=lambda entry: entry["at"])
    conditions: list[dict[str, str]] = []
    for entry in found:
        condition = {key: value for key, value in entry.items() if key != "at"}
        if any(condition["text"] in held["text"] or held["text"] in condition["text"] for held in conditions):
            continue
        conditions.append(condition)
    return conditions


def _class_direction(word: str | None) -> str:
    if not word:
        return "exact"
    return "and_above" if word in {"ABV", "ABOVE", "HIGHER", "LARGER"} else "and_below"


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
