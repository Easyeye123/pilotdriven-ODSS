"""QA520 generators (LABELLED SYNTHETIC; Codex's QA of release 520, 18 Oct 2026, output/pd-520-codex-qa-20261018).

The app carries the same generators (tests/helpers/notam-timing-qa520-generators.mjs): the same lists, the same seeded
PRNG (QA514's mulberry32, integer draws) and the same order, so both runtimes build byte-identical variants and pin the
same digests.

Metamorphic transforms of a record's body lines - the proof that a temporal connective's operand is classified whole
(I7) and accounted for on every path (I8). A connective is a word of the rules' temporalObject.connectives, or TO,
UNTIL, TIL or TILL within rangeEnd.withinWords words after FROM/FM on its line, written bare (no mark glued to it);
its operand starts at the first token after it and its skip words on the line, a bare content word (a connective
followed by another connective, by AND/OR, by a wrapped token or by skip words alone has no operand of its own to
transform).
  roleWord   (a) a place, facility or designator word inserted around the operand without changing the role of its
             tokens: before a word head (after its skip words: AIRPORT, AERODROME, RUNWAY, TERMINAL, RWY 08R), after
             its first word (AT AIRPORT, AIRPORT), or both (LOCAL ... HOURS) - 'DURING AIRPORT CURFEW', 'DURING CURFEW
             AT AIRPORT', 'DURING RWY 08R CURFEW', 'DURING LOCAL CURFEW HOURS'; after a numeric head (a token holding a
             digit, or a number word) only a phrase after it (AT AIRPORT) or the time-zone wrap (LOCAL ... HOURS): a word
             before a number makes the number its label or designator (QA514 G2: 'TERMINAL 2', 'RWY 27'), and a noun
             right after a number word makes it a count (QA518: 'TWO MARKINGS') - a new role, not a modifier;
  damage     (b) the operand damaged: deleted to its sentence's end (delete), separated from the connective by a comma,
             a period or a semicolon (comma, period, semicolon: the operand moved across a clause boundary), cut to a
             determiner (truncate: 'UNTIL THE.'), the record ending at the connective (recordEnd); and, as a control,
             the operand moved to the next body line (lineBreak), which the joined token stream reads as before.
The invariant: a roleWord variant decides as the base or is a review - an inserted role word never classifies a token
that was not classified (a decision excluded by validity stays excluded by validity); a damage variant is a review (the
obligation has no operand, wherever the connective stands: cut from its operand, it may qualify the restriction across
the boundary); a lineBreak variant decides as the base or is a review (the joined stream reads the line as before, but a
body line's opening carries structure: '3.2 ISW DME' opening a line is a list label - QA514 G3).

fuzz520_cases(): the QA518 fuzz families, plus role compositions (a temporal, event or unknown operand of a point or
period connective with place, facility or designator words around it: a review), operand damage (a connective with no
operand, or its operand cut off: a review) and benign role compositions (a spatial operand with a place word before
it: the canonical decision) - each with the verdict its syntax gives (fuzz520_verdict).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.odss.notam_timing import explain_schedule_free_text
from tests import notam_timing_qa518_generators as G518
from tests.notam_timing_qa514_generators import VALIDITIES, WINDOWS, Mulberry32

_A = re.ASCII
_FIELD = json.loads((Path(__file__).resolve().parents[1] / "app" / "odss" / "notam_timing_rules.json")
                    .read_text(encoding="utf-8"))["scheduleField"]
_OBJECT = _FIELD["temporalObject"]
CONNECTIVE = re.compile("(?:" + "|".join(_OBJECT["connectives"].values()) + ")", _A)
RANGE_AFTER = re.compile(f"(?:{_OBJECT['rangeEnd']['after']})", _A)
RANGE_END = re.compile(f"(?:{_OBJECT['rangeEnd']['connective']})", _A)
RANGE_WITHIN = int(_OBJECT["rangeEnd"]["withinWords"])
SKIP = re.compile(f"(?:{_OBJECT['skip']})", _A)
COORDINATION = re.compile(f"(?:{_OBJECT['coordination']})", _A)
RESTRICTION = re.compile(f"(?<![A-Z0-9/])(?:{_OBJECT['restriction']})(?![A-Z0-9/])", _A)
CLAUSE = re.compile(_FIELD["syntax"]["clauseBoundary"], _A)
CONTENT = re.compile(r"[A-Z0-9]", _A)

TRANSFORMS = ["roleWord", "damage"]
# (form, words): prefix after the connective and its skip words; suffix after the operand's first word; around both
ROLE_INSERTS: list[tuple[str, str]] = [("prefix", "AIRPORT"), ("prefix", "AERODROME"), ("prefix", "RUNWAY"),
                                       ("prefix", "TERMINAL"), ("prefix", "RWY 08R"), ("suffix", "AT AIRPORT"),
                                       ("suffix", "AIRPORT"), ("around", "LOCAL|HOURS")]
DAMAGES = ["delete", "comma", "period", "semicolon", "truncate", "recordEnd", "lineBreak"]
NUMBER_WORD = re.compile(_FIELD["accountedResidue"]["words"], _A)
# a focus connective's operand may stand before it ('CODE C ACFT ONLY'): damage after it leaves that reading, so (b)
# damages the other connectives only
POSTPOSITIVE = re.compile(f"(?:{_OBJECT['postpositive']})", _A)


def _core(token: str) -> str:
    return token.rstrip(".,;")


def connectives(lines: list[str]) -> Iterator[tuple[int, int, int, int, int]]:
    """Every bare connective token with an operand on its line: (line, token index, start, end, operand token index)."""
    for li, line in enumerate(lines):
        toks = G518.tokens(line)
        words = [line[start:end] for start, _core_end, end in toks]
        # a connective that a benign span covers while its next word lies outside that span is part of a positively
        # classified phrase whose operand is stated or implied inside it - a notice lead time ('PRIOR PERMISSION AT
        # LEAST 1HR BFR') - not an operand-taking connective of its own; one whose operand the span holds too ('CONTACT
        # CAA DURING OFFICE HOURS', 'OBST LGTD AT NIGHT') stays a target: damaging it breaks the span
        spans = explain_schedule_free_text(line)["spans"]

        def own_phrase(start: int, end: int, nxt: tuple[int, int, int]) -> bool:
            return any(span["start"] <= start and end <= span["end"] and not (span["start"] <= nxt[0] and nxt[1] <= span["end"])
                       for span in spans)

        range_at = None
        for ti, (start, core, end) in enumerate(toks):
            word = words[ti]
            is_range_end = range_at is not None and ti - range_at <= RANGE_WITHIN and RANGE_END.fullmatch(word) is not None
            if RANGE_AFTER.fullmatch(word):
                range_at = ti
            if not (CONNECTIVE.fullmatch(word) or is_range_end) or ti + 1 >= len(toks) or own_phrase(start, core, toks[ti + 1]):
                continue
            at = ti + 1
            while at + 1 < len(toks) and SKIP.fullmatch(words[at]):
                at += 1
            follow = _core(words[at])
            if (not CONTENT.search(follow) or SKIP.fullmatch(follow) or COORDINATION.fullmatch(follow)
                    or CONNECTIVE.fullmatch(follow) or follow != re.sub(r"[^A-Z0-9/.'-]", "", follow)
                    or (at > ti + 1 and any(t[1] < t[2] for t in toks[ti:at]))):
                continue  # a chain, a shared, wrapped or skip-word-only operand: (a) and (b) need a bare first word
            yield li, ti, start, end, at


def role_word_variants(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """(a): every role insertion around the operand of every connective."""
    for li, ti, _start, _end, at in connectives(lines):
        line = lines[li]
        toks = G518.tokens(line)
        first_start, first_core = toks[at][0], toks[at][1]
        numeric = re.search(r"[0-9]", line[first_start:first_core]) is not None or \
            NUMBER_WORD.search(line[first_start:first_core]) is not None
        for form, words in ROLE_INSERTS:
            if numeric and form == "prefix" or numeric and words == "AIRPORT":
                continue  # a number's role would change: its label or designator, a count
            if form == "prefix":
                variant = line[:first_start] + words + " " + line[first_start:]
            elif form == "suffix":
                variant = line[:first_core] + " " + words + line[first_core:]
            else:
                before, after = words.split("|")
                variant = line[:first_start] + before + " " + line[first_start:first_core] + " " + after + line[first_core:]
            yield f"roleWord L{li} T{ti} {form} {words}", [*lines[:li], variant, *lines[li + 1:]]


def damage_variants(lines: list[str]) -> Iterator[tuple[str, list[str], bool]]:
    """(b): every damage of the operand of every connective but a postpositive one; each variant must be a review
    (lineBreak excepted, which must decide as the base)."""
    for li, ti, _start, end, _at in connectives(lines):
        line = lines[li]
        toks = G518.tokens(line)
        if POSTPOSITIVE.fullmatch(line[toks[ti][0]:toks[ti][2]]):
            continue
        # the operand runs to the first token closed by a boundary mark on the line (that mark is kept), else the line end
        stop = next((k for k in range(ti + 1, len(toks)) if toks[k][1] < toks[k][2]), None)
        tail = (line[toks[stop][1]:toks[stop][2]][:1] + line[toks[stop][2]:]) if stop is not None else "."
        put = lambda variant: [*lines[:li], variant, *lines[li + 1:]]
        for damage in DAMAGES:
            if damage == "delete":
                variant = put(line[:end] + tail)
            elif damage == "comma":
                variant = put(line[:end] + "," + line[end:])
            elif damage == "period":
                variant = put(line[:end] + "." + line[end:])
            elif damage == "semicolon":
                variant = put(line[:end] + ";" + line[end:])
            elif damage == "truncate":
                variant = put(line[:end] + " THE" + tail)
            elif damage == "recordEnd":
                variant = [*lines[:li], line[:end]]
            else:
                variant = [*lines[:li], line[:end], line[end + 1:], *lines[li + 1:]]
            yield f"damage L{li} T{ti} {damage}", variant, True


def variants(lines: list[str], transform: str) -> list[tuple[str, list[str], bool]]:
    if transform == "roleWord":
        return [(name, variant, False) for name, variant in role_word_variants(lines)]
    return list(damage_variants(lines))


def sample(lines: list[str], rng: Mulberry32) -> list[tuple[str, str, list[str], bool]]:
    """One seeded variant per applicable transform (the default for the large bases)."""
    out = []
    for transform in TRANSFORMS:
        items = variants(lines, transform)
        if items:
            name, variant, restriction = items[rng.below(len(items))]
            out.append((transform, name, variant, restriction))
    return out


# ---- the QA520 fuzz families ----------------------------------------------------------------------------------------
FUZZ520: dict[str, list[Any]] = {
    "families": ["roleComposition", "roleComposition", "operandDamage", "operandDamage", "benignRole", "qa518"],
    "pointPeriod": ["UNTIL", "TILL", "TIL", "AFTER", "AFT", "BEFORE", "BFR", "SINCE", "WEF", "DURING", "DRG", "OUTSIDE"],
    "connectives": ["UNTIL", "TILL", "TIL", "AFTER", "AFT", "BEFORE", "BFR", "SINCE", "WEF", "DURING", "DRG", "OUTSIDE",
                    "FROM", "FM", "AT", "BTN", "BETWEEN", "EXCEPT", "EXC"],
    "heads": ["CURFEW", "QUIET PERIOD", "NIGHT BAN", "LDG", "TKOF", "LAST FLT", "COMPLETION OF WORKS", "PRAYER", "LUNCH",
              "SUNDOWN", "HALF PAST EIGHT", "1800", "SKED FLT", "FIRING", "THE TRIAL", "END OF WORKS", "PSG WPT TOPUN"],
    "roleWords": ["AIRPORT", "AERODROME", "RUNWAY", "RWY", "TERMINAL", "AD", "APRON", "TWY", "RWY 08R", "TWY B", "STAND 12",
                  "LOCAL", "THE"],
    "suffixes": ["", "", "AT AIRPORT", "AIRPORT", "HOURS", "OF THE AERODROME", "RWY 08R", "PERIOD"],
    "syllables": ["BA", "LO", "MI", "KE", "RU", "TA", "NO", "VE", "SI", "DU", "PA", "GO", "ZE", "WI", "FU", "XO"],
    "damages": ["", ",", ".", ";", " THE", " ( )", " THE,", ", OR"],
    "operands": ["TWY B", "HOLDING POINT B", "1800", "CURFEW", "THE AIRPORT CURFEW", "APRON A", "121.35", "SKED FLT",
                 "THE WORKS", "RWY 08R"],
    "benignObjects": [["AFTER", "TWY B"], ["BEFORE", "HOLDING POINT B"], ["AT", "APRON A"], ["FROM", "TWY B TO TWY C"],
                      ["BTN", "TWY B AND TWY C"], ["AT", "THE INTERSECTION WITH TWY B"], ["OUTSIDE", "THE AERODROME BOUNDARY"],
                      ["FROM", "THE NORTH END OF RWY 08R"], ["AFTER", "THE EXIT FROM TWY B"], ["EXC", "SKED ACFT"],
                      ["BFR", "THR 27"], ["DURING", "THE CLOSURE"]],
    "placeWords": ["AIRPORT", "AERODROME", "RUNWAY", "TERMINAL", "APRON"],
    "restrictions": [["TWY J", "CLSD"], ["RWY 09/27", "CLSD"], ["TWY B", "CLSD DUE WIP"], ["STAND 12", "U/S"],
                     ["AREA R123", "ACT"]],
    "placements": ["end", "before", "sentence"],
    "itemD": ["NONE", "D0800", "D1800"],
    "validities": list(VALIDITIES),
}


def _place(subject: str, verb: str, segment: str, placement: str) -> tuple[str, str]:
    if placement == "end":
        return f"{subject} {verb} {segment}.", f"{subject} {verb}."
    if placement == "before":
        return f"{segment}, {subject} {verb}.", f"{subject} {verb}."
    return f"{subject} {verb}. {subject} {verb} {segment}.", f"{subject} {verb}. {subject} {verb}."


def fuzz520_case(rng: Mulberry32) -> dict[str, Any]:
    family = rng.pick(FUZZ520["families"])
    if family == "qa518":
        case = G518.fuzz518_case(rng)
        return {**case, "family": "qa518:" + case["family"]}
    item_d = rng.pick(FUZZ520["itemD"])
    validity = rng.pick(FUZZ520["validities"])
    subject, verb = rng.pick(FUZZ520["restrictions"])
    placement = rng.pick(FUZZ520["placements"])
    if family == "roleComposition":
        head = rng.pick(FUZZ520["heads"]) if rng.below(4) else "".join(rng.pick(FUZZ520["syllables"]) for _ in range(3))
        words = [rng.pick(FUZZ520["roleWords"]) for _ in range(rng.below(3))]
        suffix = rng.pick(FUZZ520["suffixes"])
        segment = " ".join([rng.pick(FUZZ520["pointPeriod"]), *words, head, *([suffix] if suffix else [])])
    elif family == "operandDamage":
        connective = rng.pick(FUZZ520["connectives"])
        damage = rng.pick(FUZZ520["damages"])
        segment = connective + damage
        if damage in (",", ".", ";", ", OR") and rng.below(2):
            segment += " " + rng.pick(FUZZ520["operands"])  # the operand separated, or moved past the boundary
        placement = "end"
    else:
        connective, operand = rng.pick(FUZZ520["benignObjects"])
        words = [rng.pick(FUZZ520["placeWords"]) for _ in range(rng.below(2))]
        parts = operand.split(" ")
        lead = 0
        while lead < len(parts) - 1 and SKIP.fullmatch(parts[lead]):
            lead += 1  # a place word goes after the operand's determiner: 'DURING THE AIRPORT CLOSURE'
        segment = " ".join([connective, *parts[:lead], *words, *parts[lead:]])
    line, base = _place(subject, verb, segment, placement)
    return {"family": family, "itemD": item_d, "validity": validity, "line": line, "base": base, "segment": segment}


def fuzz520_cases(seed: int, count: int) -> Iterator[dict[str, Any]]:
    rng = Mulberry32(seed)
    for _ in range(count):
        yield fuzz520_case(rng)


_KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")


def fuzz520_verdict(case: dict[str, Any], got: dict, canonical: dict) -> str | None:
    """The QA520 fuzz invariant for one decision: a role composition and operand damage are reviews; a benign role
    composition decides as the restriction alone; the QA518 families keep their verdict; outside the validity every
    variant is excluded by validity."""
    if case["family"].startswith("qa518:"):
        return G518.fuzz518_verdict({**case, "family": case["family"][6:]}, got, canonical)
    same = all(got.get(key) == canonical.get(key) for key in _KEYS)
    if canonical.get("status") == "outside_window" and canonical.get("outsideBy") == "validity":
        return None if got.get("status") == "outside_window" and got.get("outsideBy") == "validity" else \
            "outside the validity, yet decided otherwise"
    if case["family"] == "benignRole":
        return None if same else f"a benign role composition decides {got.get('status')}, the restriction alone {canonical.get('status')}"
    if got.get("status") == "review":
        return None
    return f"{case['family']} decided {got.get('status')}, not a review"


__all__ = ["VALIDITIES", "WINDOWS", "TRANSFORMS", "ROLE_INSERTS", "DAMAGES", "POSTPOSITIVE", "connectives", "role_word_variants",
           "damage_variants", "variants", "sample", "FUZZ520", "fuzz520_cases", "fuzz520_verdict"]
