"""QA518 generators (LABELLED SYNTHETIC; Codex's QA of release 518, 17 Oct 2026, output/pd-518-codex-qa-20261017).

The app carries the same generators (tests/helpers/notam-timing-qa518-generators.mjs): the same lists, the same seeded
PRNG (QA514's mulberry32, integer draws) and the same order, so both runtimes build byte-identical variants and pin the
same digests.

Metamorphic transforms of a record's body lines (Item D lines included) - the proof that governance is
punctuation-invariant (I5) and that an unresolved temporal qualification is accounted for whole (I1, I6):
  wrap        T1: wrap one token, or a span of two or three tokens of one line, in a pair of quotes (of every kind),
              brackets, parentheses or braces;
  punctuate   T2: insert or remove non-boundary punctuation and spaces at token edges - a joiner dash between two tokens
              that are not both range sides, a label colon after a token, a doubled space, a space before a token's
              closing boundary mark, a space inside a wrapper; or remove a wrapping pair, a joiner dash, a label colon,
              a space before a boundary mark;
  wordClock   T3: write one four-digit clock (HHMM) in words (EIGHTEEN HUNDRED, SIX O'CLOCK, HALF PAST SIX, QUARTER TO
              SEVEN, TWENTY THREE FIFTY NINE ...);
  synonym     T4: replace one temporal connective by a synonym of the same role (UNTIL/TILL/TIL, AFTER/AFT, BEFORE/BFR,
              DURING/DRG, BETWEEN/BTN, FROM/FM, EXCEPT/EXC);
  contactMove T5: move a contact sentence to the other side of the restriction sentence.
T1 and T2 must leave every body line's syntactic text - the line as the grammar reads it - unchanged, so the decision
is unchanged (benign controls stay benign); T3 introduces unreadable temporal content, so the decision becomes a review
(unless the clock sat inside a benign span); T4 and T5 leave the decision unchanged or make it a review - never another
certain answer.

fuzz518_cases(): the QA514 fuzzer's restrictions and placements with the QA518 families - a temporal operand wrapped in
punctuation after a temporal connective, a clock in number words after a connective or alone, an unknown word after a
point or period connective, and a genuine benign control wrapped in punctuation - each with the verdict its syntax
gives (fuzz518_verdict).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tests.notam_timing_qa514_generators import VALIDITIES, WINDOWS, Mulberry32, restates_item_d

_A = re.ASCII

WRAPPERS: list[tuple[str, str]] = [('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("«", "»"),
                                   ("(", ")"), ("[", "]"), ("{", "}")]
TRANSFORMS = ["wrap", "punctuate", "wordClock", "synonym", "contactMove"]
SYNONYMS = {"UNTIL": "TILL", "TILL": "TIL", "TIL": "UNTIL", "AFTER": "AFT", "AFT": "AFTER", "BEFORE": "BFR", "BFR": "BEFORE",
            "DURING": "DRG", "DRG": "DURING", "BETWEEN": "BTN", "BTN": "BETWEEN", "FROM": "FM", "FM": "FROM",
            "EXCEPT": "EXC", "EXC": "EXCEPT"}
CONTACT_WORDS = re.compile(r"(?<![A-Z])(?:CONTACT|CTC|CALL|PHONE|TEL|TELEPHONE|NOTIFY|REQUEST|COORDINATE|E-?MAIL)(?![A-Z])", _A)
RESTRICTION_WORDS = re.compile(r"(?<![A-Z/])(?:CLSD|CLOSED|U/S|ACT|AVBL|AVAILABLE|OPR|RESTRICTED|PROHIBITED|SUSPENDED|"
                               r"LIMITED|INOP|WIP|OPEN)(?![A-Z/])", _A)
SENTENCE_END = re.compile(r"[;]|\.(?= |$)", _A)
CLOCK = re.compile(r"(?<![0-9A-Z.:/])([01][0-9]|2[0-3])([0-5][0-9])(?![0-9A-Z])", _A)
# A dash between two range sides is a range, never a joiner (the shared rules' syntax.rangeSide): T2 never inserts one
# there and never removes one.
RANGE_SIDE = re.compile(json.loads((Path(__file__).resolve().parents[1] / "app" / "odss" / "notam_timing_rules.json")
                                   .read_text(encoding="utf-8"))["scheduleField"]["syntax"]["rangeSide"], _A)
_EDGE_MARKS = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb`\u00b4\u201e\u201a\u2039\u203a()[]{}.,;:"
_UNITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
          "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = {2: "TWENTY", 3: "THIRTY", 4: "FORTY", 5: "FIFTY"}


def number_words(n: int) -> str:
    return _UNITS[n] if n < 20 else _TENS[n // 10] + ("" if n % 10 == 0 else " " + _UNITS[n % 10])


def clock_words(hh: int, mm: int, form: int) -> str:
    """A clock in words - never a form the grammar reads (a word clock is a review: no clock is guessed from words)."""
    h12 = hh % 12 or 12
    if mm == 0:
        return f"{number_words(hh)} HUNDRED" if form % 2 == 0 else f"{number_words(h12)} O'CLOCK"
    if mm == 30:
        return f"HALF PAST {number_words(h12)}"
    if mm == 15:
        return f"QUARTER PAST {number_words(h12)}"
    if mm == 45:
        return f"QUARTER TO {number_words(h12 % 12 + 1)}"
    if mm < 10:
        return f"{number_words(hh)} OH {number_words(mm)}"
    return f"{number_words(hh)} {number_words(mm)}"


def tokens(line: str) -> list[tuple[int, int, int]]:
    """The tokens of a line as (start, coreEnd, end): coreEnd excludes the token's trailing boundary marks (.,;)."""
    out = []
    for match in re.finditer(r"[^ ]+", line):
        start, end = match.span()
        core = end
        while core > start + 1 and line[core - 1] in ".,;":
            core -= 1
        out.append((start, core, end))
    return out


def _range_side(token: str) -> bool:
    return RANGE_SIDE.fullmatch(token.strip(_EDGE_MARKS).strip("-")) is not None


_QUOTE_FAMILY = {'"': '"', "'": "'", "\u201c": "\u201c", "\u201d": "\u201c", "\u201e": "\u201c", "\u2018": "\u2018",
                 "\u2019": "\u2018", "\u201a": "\u2018", "\u00ab": "\u00ab", "\u00bb": "\u00ab", "\u2039": "\u2039",
                 "\u203a": "\u2039", "`": "`", "\u00b4": "`"}


def well_formed(span: str) -> bool:
    """A span a wrapper can wrap: its brackets balance and its quotes pair (a quote opening a token against one closing a
    token, per family; a quote after a digit closing a token is a unit mark, 3000')."""
    stack: list[str] = []
    for ch in span:
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[ch]:
                return False
    if stack:
        return False
    balance: dict[str, int] = {}
    for i, ch in enumerate(span):
        if ch not in _QUOTE_FAMILY:
            continue
        opens = i == 0 or span[i - 1] == " " or span[i - 1] in "([{"
        closes = i + 1 == len(span) or span[i + 1] in " .,;)]}"
        if opens and not closes:
            balance[_QUOTE_FAMILY[ch]] = balance.get(_QUOTE_FAMILY[ch], 0) + 1
        elif closes and not opens and not (i > 0 and "0" <= span[i - 1] <= "9"):
            balance[_QUOTE_FAMILY[ch]] = balance.get(_QUOTE_FAMILY[ch], 0) - 1
    return all(count == 0 for count in balance.values())


def wrap_variants(lines: list[str], exhaustive: bool = True) -> Iterator[tuple[str, list[str]]]:
    """T1: every token with every wrapper; every span of two or three tokens with one wrapper (rotating). A span is
    wrapped only when it is well formed (well_formed) - wrapping half of a bracket pair crosses it, which no reader
    reads as wrapping."""
    for li, line in enumerate(lines):
        toks = tokens(line)
        for ti in range(len(toks)):
            for k in (1, 2, 3):
                if ti + k > len(toks):
                    break
                start, core = toks[ti][0], toks[ti + k - 1][1]
                if not well_formed(line[start:core]):
                    continue
                kinds = range(len(WRAPPERS)) if k == 1 else [(li + ti + k) % len(WRAPPERS)]
                for w in kinds:
                    left, right = WRAPPERS[w]
                    if left in line[start:core] or right in line[start:core]:
                        continue  # a quote of the wrapper's own kind inside the span is ambiguous to any reader
                    variant = line[:start] + left + line[start:core] + right + line[core:]
                    yield f"wrap L{li} T{ti} K{k} W{w}", [*lines[:li], variant, *lines[li + 1:]]


def _wrapping_pairs(line: str) -> list[tuple[int, int]]:
    """Pairs of wrapping marks in a line: an opener after a space or the line start, its closer before a space, a
    boundary mark or the line end (quotes pair with the next closer of their kind)."""
    pairs = []
    edge_left = lambda i: i == 0 or line[i - 1] == " "
    edge_right = lambda i: i + 1 == len(line) or line[i + 1] in " .,;"
    stack: list[tuple[str, int]] = []
    for i, ch in enumerate(line):
        if ch in "([{":
            stack.append((ch, i))
        elif ch in ")]}":
            if stack and stack[-1][0] == {")": "(", "]": "[", "}": "{"}[ch]:
                _, at = stack.pop()
                if edge_left(at) and edge_right(i):
                    pairs.append((at, i))
    for left, right in WRAPPERS[:5]:
        i = 0
        while i < len(line):
            if line[i] == left and edge_left(i) and i + 1 < len(line) and line[i + 1] != " ":
                j = line.find(right, i + 1)
                if j > i + 1 and edge_right(j) and line[j - 1] != " ":
                    pairs.append((i, j))
                    i = j + 1
                    continue
            i += 1
    return sorted(set(pairs))


def punctuate_variants(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """T2: insertions at every token gap and edge, and removals of every wrapping pair, joiner dash, label colon and
    space before a boundary mark."""
    for li, line in enumerate(lines):
        toks = tokens(line)
        put = lambda variant: [*lines[:li], variant, *lines[li + 1:]]
        for ti, (start, core, end) in enumerate(toks):
            word = lambda token: re.search(r"[A-Z0-9]", token) is not None
            right = line[toks[ti + 1][0]:toks[ti + 1][2]] if ti + 1 < len(toks) else ""
            if right and word(line[start:end]) and word(right) and not (_range_side(line[start:end]) and _range_side(right)):
                yield f"punctuate L{li} T{ti} dash", put(line[:end] + " -" + line[end:])
            yield f"punctuate L{li} T{ti} colon", put(line[:core] + ":" + line[core:])
            if ti + 1 < len(toks):
                yield f"punctuate L{li} T{ti} space", put(line[:end] + " " + line[end:])
            if core < end:
                yield f"punctuate L{li} T{ti} spaceBeforeMark", put(line[:core] + " " + line[core:])
        for at, close in _wrapping_pairs(line):
            yield f"punctuate L{li} P{at} unwrap", put(line[:at] + line[at + 1:close] + line[close + 1:])
            yield f"punctuate L{li} P{at} spaceInside", put(line[:at + 1] + " " + line[at + 1:close] + " " + line[close:])
        for match in re.finditer(r"(?<= )-(?= )", line):
            before, after = line[:match.start()].split(" ")[-2:-1], line[match.end():].split(" ")[1:2]
            if not (before and after and _range_side(before[0]) and _range_side(after[0])):
                yield f"punctuate L{li} D{match.start()} undash", put(line[:match.start()] + line[match.end() + 1:])
        for match in re.finditer(r":(?= )", line):
            if not (match.start() > 0 and "0" <= line[match.start() - 1] <= "9"):
                yield f"punctuate L{li} C{match.start()} uncolon", put(line[:match.start()] + line[match.end():])
        for match in re.finditer(r" (?=[,;]|\.(?: |$))", line):
            yield f"punctuate L{li} S{match.start()} unspace", put(line[:match.start()] + line[match.end():])


def word_clock_variants(lines: list[str]) -> Iterator[tuple[str, list[str], int, int, int]]:
    """T3: each four-digit clock written in words, one at a time; yields the line index and the clock's span too."""
    form = 0
    for li, line in enumerate(lines):
        for match in CLOCK.finditer(line):
            words = clock_words(int(match.group(1)), int(match.group(2)), form)
            form += 1
            yield (f"wordClock L{li} C{match.start()}", [*lines[:li], line[:match.start()] + words + line[match.end():], *lines[li + 1:]],
                   li, match.start(), match.end())


def synonym_variants(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """T4: each temporal connective replaced by its same-role synonym, one at a time."""
    for li, line in enumerate(lines):
        for match in re.finditer(r"(?<![A-Z0-9'/-])(?:" + "|".join(SYNONYMS) + r")(?![A-Z0-9'/-])", line):
            variant = line[:match.start()] + SYNONYMS[match.group(0)] + line[match.end():]
            yield f"synonym L{li} {match.group(0)}@{match.start()}", [*lines[:li], variant, *lines[li + 1:]]


def _sentences(line: str) -> list[str]:
    out, start = [], 0
    for match in SENTENCE_END.finditer(line):
        out.append(line[start:match.end()].strip())
        start = match.end()
    if line[start:].strip():
        out.append(line[start:].strip())
    return [s for s in out if s]


def contact_move_variants(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """T5: a contact sentence moved to the other side of a restriction sentence of the same line."""
    for li, line in enumerate(lines):
        parts = _sentences(line)
        for ci, part in enumerate(parts):
            if not CONTACT_WORDS.search(part) or RESTRICTION_WORDS.search(part):
                continue
            for ri, other in enumerate(parts):
                if ri == ci or not RESTRICTION_WORDS.search(other):
                    continue
                moved = [p for i, p in enumerate(parts) if i != ci]
                at = moved.index(other)
                moved.insert(at + 1 if ci < ri else at, part)
                ends = [p if p[-1] in ".;" else p + "." for p in moved]
                variant = " ".join(ends)
                if variant != line:
                    yield f"contactMove L{li} S{ci}>{ri}", [*lines[:li], variant, *lines[li + 1:]]


def variants(lines: list[str], transform: str) -> list[tuple[str, list[str]]]:
    if transform == "wrap":
        return list(wrap_variants(lines))
    if transform == "punctuate":
        return list(punctuate_variants(lines))
    if transform == "wordClock":
        return [(name, variant) for name, variant, *_ in word_clock_variants(lines)]
    if transform == "synonym":
        return list(synonym_variants(lines))
    return list(contact_move_variants(lines))


def sample(lines: list[str], rng: Mulberry32) -> list[tuple[str, str, list[str]]]:
    """One seeded variant per applicable transform (the default for the large bases)."""
    out = []
    for transform in TRANSFORMS:
        items = variants(lines, transform)
        if items:
            name, variant = items[rng.below(len(items))]
            out.append((transform, name, variant))
    return out


# ---- the QA518 fuzz families ----------------------------------------------------------------------------------------
FUZZ518: dict[str, list[Any]] = {
    "families": ["wrappedOperand", "wrappedOperand", "wordClock", "wordClock", "unknownObject", "wrappedBenign"],
    "connectives": ["UNTIL", "TILL", "TIL", "AFTER", "AFT", "BEFORE", "BFR", "SINCE", "WEF", "DURING", "DRG", "OUTSIDE",
                    "FROM", "FM", "AT", "BTN", "BY", "TO", "THRU"],
    "pointPeriod": ["UNTIL", "TILL", "TIL", "AFTER", "AFT", "BEFORE", "BFR", "SINCE", "WEF", "DURING", "DRG", "OUTSIDE"],
    "operands": ["121.35", "121.9", "0800", "08:00", "1800-2000", "18.00", "8:30", "2030", "0830Z", "1200 UTC", "18H",
                 "0800-10", "1.5H", "2.25H", "122.85", "1800", "10", "8"],
    "glue": ["", " ", ": ", " - ", "- ", " -", " : ", "  "],
    "syllables": ["BA", "LO", "MI", "KE", "RU", "TA", "NO", "VE", "SI", "DU", "PA", "GO", "ZE", "WI", "FU", "XO"],
    "benign": ["FREQ 122.850 MHZ", "CRANE HGT 2350FT AMSL", "TORA 3200M TODA 3400M", "STANDS 301-309", "TERMINAL 2",
               "REF A9876/26", "ATS RTE Q907", "OBST 1315N 12341E", "TEL +65 6789 1234", "PPR 36 HR", "FICON 5/5/5",
               "CONTACT CAA DURING NORMAL OFFICE HOURS", "FOR 90 MIN", "VIS 1500M RVR 0650M", "NOTIFY TWR 3 HR IN ADVANCE"],
    "restrictions": [["TWY J", "CLSD"], ["RWY 09/27", "CLSD"], ["TWY B", "CLSD DUE WIP"], ["STAND 12", "U/S"],
                     ["AREA R123", "ACT"]],
    "placements": ["end", "before", "sentence"],
    "itemD": ["NONE", "D0800", "D1800"],
    "validities": list(VALIDITIES),
}


def _wrap(rng: Mulberry32, text: str) -> str:
    """Wrap the text in zero to two nested random wrappers (never a kind already inside it)."""
    for _ in range(rng.below(3)):
        left, right = rng.pick(WRAPPERS)
        if left not in text and right not in text:
            text = left + text + right
    return text


def fuzz518_case(rng: Mulberry32) -> dict[str, Any]:
    family = rng.pick(FUZZ518["families"])
    item_d = rng.pick(FUZZ518["itemD"])
    validity = rng.pick(FUZZ518["validities"])
    subject, verb = rng.pick(FUZZ518["restrictions"])
    placement = rng.pick(FUZZ518["placements"])
    glue = rng.pick(FUZZ518["glue"])
    if family == "wrappedOperand":
        connective = rng.pick(FUZZ518["connectives"])
        segment = connective + glue.rstrip() + " " + _wrap(rng, rng.pick(FUZZ518["operands"]))
        if rng.below(2):
            segment = _wrap(rng, segment)
    elif family == "wordClock":
        words = clock_words(rng.below(24), rng.pick([0, 0, 15, 30, 45, 5, 20, 59]), rng.below(2))
        segment = (rng.pick(FUZZ518["connectives"]) + glue.rstrip() + " " if rng.below(4) else "") + _wrap(rng, words)
    elif family == "unknownObject":
        word = "".join(rng.pick(FUZZ518["syllables"]) for _ in range(3 + rng.below(2)))
        segment = rng.pick(FUZZ518["pointPeriod"]) + glue.rstrip() + " " + _wrap(rng, word)
    else:
        segment = _wrap(rng, rng.pick(FUZZ518["benign"]))
    if family == "wrappedBenign":
        # a separate sentence, so the restriction verb never governs it
        line, base = f"{subject} {verb}. {segment}.", f"{subject} {verb}. {_unwrap(segment)}."
    elif placement == "end":
        line, base = f"{subject} {verb} {segment}.", f"{subject} {verb}."
    elif placement == "before":
        line, base = f"{segment} {subject} {verb}.", f"{subject} {verb}."
    else:
        line, base = f"{subject} {verb}. {subject} {verb} {segment}.", f"{subject} {verb}. {subject} {verb}."
    return {"family": family, "itemD": item_d, "validity": validity, "line": line, "base": base, "segment": segment}


def _unwrap(text: str) -> str:
    """The text without its wrappers (the wrapped benign control's own form)."""
    pairs = {left: right for left, right in WRAPPERS}
    while text and text[0] in pairs and text[-1] == pairs[text[0]]:
        text = text[1:-1]
    return text


def fuzz518_cases(seed: int, count: int) -> Iterator[dict[str, Any]]:
    rng = Mulberry32(seed)
    for _ in range(count):
        yield fuzz518_case(rng)


_KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")


def segment_restates_item_d(segment: str, item_d: str) -> bool:
    """The segment restates Item D: its wrappers, joiner punctuation and leading connective dropped, the operand is Item
    D's own range (QA514's restates_item_d) - the grammar may then read it as equal to Item D."""
    plain = re.sub(r"[\"'\u201c\u201d\u2018\u2019\u00ab\u00bb()\[\]{}:]", " ", segment)
    plain = re.sub(r" +", " ", plain).strip()
    plain = re.sub(r"^(?:%s)(?: ?-)?(?= )" % "|".join(FUZZ518["connectives"]), "", plain).strip()
    return restates_item_d(plain, item_d)


def fuzz518_verdict(case: dict[str, Any], got: dict, canonical: dict) -> str | None:
    """The QA518 fuzz invariant for one decision: a wrapped temporal operand (unless it restates Item D), a word clock
    and an unknown object of a point or period connective are reviews; a wrapped benign control decides as itself
    unwrapped; and outside the validity every variant is excluded by validity."""
    same = all(got.get(key) == canonical.get(key) for key in _KEYS)
    if canonical.get("status") == "outside_window" and canonical.get("outsideBy") == "validity":
        return None if got.get("status") == "outside_window" and got.get("outsideBy") == "validity" else \
            "outside the validity, yet decided otherwise"
    if case["family"] == "wrappedBenign":
        return None if same else f"a wrapped benign control decides {got.get('status')}, unwrapped {canonical.get('status')}"
    if got.get("status") == "review":
        return None
    if case["family"] == "wrappedOperand" and same and segment_restates_item_d(case["segment"], case["itemD"]):
        return None
    return f"{case['family']} decided {got.get('status')}, not a review"


__all__ = ["VALIDITIES", "WINDOWS", "WRAPPERS", "TRANSFORMS", "SYNONYMS", "clock_words", "tokens", "wrap_variants",
           "punctuate_variants", "word_clock_variants", "synonym_variants", "contact_move_variants", "variants", "sample",
           "FUZZ518", "fuzz518_cases", "fuzz518_verdict"]
