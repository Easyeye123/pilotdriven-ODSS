"""ONE timing decision for an OFP station notice (item 3, Gatwick, 14 Oct 2026).

"Is this notice in force at this station's reference time" was decided by three
evaluators with three rule sets: the app (briefing.mjs on its first-line D
schedule) for the dashboard chart, the PDF map marks and the NOTAM records; this
service (``engines._assess_notam_window`` on ``enrichment``'s schedule-line
reader and ``_schedule_overlaps``) for the airport cards and the PDF text; and
``runway_closure_schedule`` for dated runway regimes. The same LIDO record
could be active on the card, under review on the chart and absent from the PDF
map. The rules now live once, in ``notam_timing_rules.json`` - a byte-identical
copy of the app's ``notam-timing-rules.json``, evaluated there by
``notam-timing-decision.mjs`` - and both suites run the same vectors
(``tests/fixtures/notam-timing-vectors.json``).

Nothing here forces a notice active: an unreadable validity, schedule or source
record is a review on every surface, and no end time is invented.

QA500 (Codex's QA of release 500, 15 Oct 2026): the reader itself treated "I could
not account for the schedule text" as a certain answer. A D field wrapped as
"AUG 16" / "1800-2000" was dropped because its first line held no time, so the
record had no schedule and was published active all day; a D field it did accept
silenced free text stating other hours; FEB 30 was "outside the window". The field
is now the whole leading run of schedule lines and is accepted only when the grammar
reads all of it; schedule language left in the free text must agree with it (or,
with no field, is a review); and every date is checked against the calendar.

QA502 (Codex's re-QA of release 502, 15 Oct 2026): the body was still read through
a few clock patterns, so "TWY T CLSD DAILY SR-SS", "EXC SUN" or "FROM 1745 UNTIL
1945" found no span and the record had "no schedule"; and body-to-Item D equivalence
sampled 400 days from B, missing a later leap day. One shared detector
(scheduleLanguage, datedPeriod) now finds every schedule-bearing statement anywhere
in the body; each must be accounted for (a dated period containing the validity, or a
run the grammar reads that is proven equal to Item D) or the record is a review.
Equality is proven structurally, or over the whole bounded validity - never sampled.

QA506 (Codex's re-QA of release 506, 15 Oct 2026): the detector was still a list of
phrasings, and text it did not match took the "no schedule" path ("TWY Y CLSD WEF 1800
UTC" was active all day; "H24" beside "DLY 1800-2000" was out of window); one-sided dates
on the far side of B/C were accepted; and day parts and hours were checked separately, so
"ON SUN BETWEEN HR 1800-2000" borrowed Monday's hours. The detector is now inverted to fail
closed: TEMPORAL CONTENT is defined broadly (temporal), stated benign classes are masked
first (benign), and every temporal token must sit in a statement the grammar reads whole -
periods with a year, and days bound to hours - that is proven equal on its own to Item D
(or to the whole validity), else the record is a review. A start date must lie at or before
B and an end date at or after C.

QA510 (Codex's QA of release 510, 16 Oct 2026): temporal content was still found by
VALIDITY - "2500-2600", "080O-100O", "0800A-1000A", "08.00/10.00", "FROM 18 00 TO 20 00",
"FROM 18H TO 20H" matched no class, and a free text with no token returned "no schedule" -
and the notice-duration mask hid a duration attached to the restriction ("FOR MAX 2 HOURS",
"DURING THE LAST 2 HOURS", "FOR A PERIOD OF 2 HOURS"). Temporal content is now found by
SHAPE: every clock-like shape, whatever its values, is a token the grammar must read (it
reads only its own forms), and "no schedule" comes only out of the accounting. A duration is
benign only as an explicit notice, permission or restoration lead time; every benign class
needs its stated context, and a benign span never holds or cuts a clock-like range, never
cuts a clock-like shape and is never one side of a range. Lines are NFKC-normalised,
stripped of format characters, and a lower-case l in a run holding a digit is written I.

QA518 (Codex's QA of release 518, 17 Oct 2026): punctuation still decided governance -
'UNTIL "121.35"', '[121.35]', '- 121.35' put a character between the connective and its
operand, so the operand was masked as a frequency - and a qualification in words no
detector knew ('AFTER HALF PAST EIGHT') read as no schedule. Every relation is now read on
the SYNTACTIC text (_syntax_text, read_body_line): punctuation that only wraps or joins
tokens is removed by role, clauses end at one boundary, and the field and free text are each
one stream. Number words are numeric content (I1), and the object of a temporal connective
in a restriction sentence is temporal content unless a mask or a role its connective admits
classifies it (I6): unclassified, a review.

QA520 (Codex's QA of release 520, 18 Oct 2026): an object was accounted for by a part of it -
any role word licensed the whole object ('DURING AIRPORT CURFEW' active), and a connective
whose operand was missing, separated or empty left nothing to account for ('TWY J CLSD
UNTIL.', 'AFTER, CURFEW'). I7: an operand is benign only if every content token of it is
positively classified by a role its connective admits; its head is defined by composition
(head-final), so a place word never classifies a temporal head, and a pre-modifier never hides
temporal content (_classify_np, _classify_operand, _head_view). I8: every connective creates an
obligation in one ledger per decision (_connective_ledger, explain_timing_ledger), checked once
at the end of _free_text_accounting: any undischarged obligation is a review.
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping

RULES_FILE = Path(__file__).with_name("notam_timing_rules.json")
NOTAM_TIMING_RULES: dict[str, Any] = json.loads(RULES_FILE.read_text(encoding="utf-8"))
NOTAM_TIMING_SPEC_VERSION: str = NOTAM_TIMING_RULES["specVersion"]

_MINUTE_MS = 60 * 1000
_DAY_MS = 24 * 60 * _MINUTE_MS
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_MONTH_SOURCE = "|".join(_MONTHS)
_WEEKDAY_SOURCE = "|".join(_WEEKDAYS)


def _ascii_digits(pattern: str) -> str:
    """JavaScript's \\d is 0-9 only; Python's, without re.ASCII, is any Unicode decimal digit. The grammar reads ASCII
    values only (QA516: an Arabic-Indic or Devanagari digit is never read as a value - in the free text it is an
    unaccounted digit, a review), so a pattern compiled without re.ASCII reads \\d as [0-9], as the app does."""
    return pattern.replace("\\d", "[0-9]")


_VALIDITY_RANGE = re.compile(_ascii_digits(NOTAM_TIMING_RULES["validity"]["range"]))
_VALIDITY_END = re.compile(_ascii_digits(NOTAM_TIMING_RULES["validity"]["end"]))
_OPEN_ENDS: dict[str, str] = NOTAM_TIMING_RULES["validity"]["openEnds"]
_FIELD = NOTAM_TIMING_RULES["scheduleField"]
_DASHES = re.compile(_FIELD["dashes"])
_FIELD_LINE = re.compile(_ascii_digits(_FIELD["fieldLine"]))
_REVIEW_LANGUAGE = re.compile(_ascii_digits(_FIELD["reviewLanguage"]))
_COLON_CLOCK = re.compile(_ascii_digits(_FIELD["colonClock"]))
_A = re.ASCII  # '\\b', '\\d' and '\\w' read as in JavaScript


def _js_replacement(replacement: str) -> str:
    """The rules file writes replacements as JavaScript does ('$1'); Python reads them as '\\g<1>'."""
    return re.sub(r"\$(\d)", r"\\g<\1>", replacement)


_LETTER_FOR_DIGIT_RUN = re.compile(_FIELD["letterForDigit"]["run"], _A)
_BENIGN = [(item["class"], re.compile(item["pattern"], _A), bool(item.get("allowClockRange")),
            bool(item.get("holdsNoTemporal")), int(item.get("maskGroup") or 0), bool(item.get("atLineStart")))
           for item in _FIELD["benign"]]
_BENIGN_NEVER_HOLDS = re.compile(_FIELD["benignNeverHolds"], _A)
_BENIGN_NEVER_CUTS = re.compile(_FIELD["benignNeverCuts"], _A)
_ABUTS_AFTER = re.compile(_FIELD["rangeAbutment"]["after"], _A)
_ABUTS_BEFORE = re.compile(_FIELD["rangeAbutment"]["before"], _A)
_GOVERNING_CONNECTIVE = re.compile(_FIELD["benignGovernance"]["connective"], _A)
_GOVERNED_OBJECT = re.compile(_FIELD["benignGovernance"]["object"], _A)
_PERIOD_CONNECTIVE = re.compile(_FIELD["benignGovernance"]["periodConnective"], _A)
_SELF_EVIDENT = re.compile(_FIELD["benignGovernance"]["selfEvident"], _A)
# Every decimal digit of any script (QA516: Unicode category Nd, i.e. str.isdecimal() - Arabic-Indic or Devanagari
# digits are digits the grammar never reads as values, so an unmasked run of them is unaccounted for: a review).
_RESIDUE_CATEGORY = _FIELD["accountedResidue"]["category"]
# QA518 I1: numeric content written in words (ONE..NINETY, HUNDRED, HALF, QUARTER, NOON, MIDNIGHT, O'CLOCK) is
# numeric content too; the grammar reads no clock from words, so an unmasked number word is a review.
_RESIDUE_WORDS = re.compile(_FIELD["accountedResidue"]["words"], _A)
# A benign span never touches a digit the grammar does not read (a decimal digit of another script).
_TOUCH_CATEGORY = _FIELD["benignNeverTouches"]["category"]
_TOUCH_EXCEPT = re.compile(_FIELD["benignNeverTouches"]["except"], _A)


def _unread_digit(ch: str) -> bool:
    return unicodedata.category(ch) == _TOUCH_CATEGORY and not _TOUCH_EXCEPT.fullmatch(ch)


def _residue_spans(masked: str) -> list[tuple[int, int]]:
    """Every run of decimal digits (accountedResidue: Unicode category Nd) left in the masked text."""
    spans: list[tuple[int, int]] = []
    start = None
    for index, ch in enumerate(masked + " "):
        digit = index < len(masked) and unicodedata.category(ch) == _RESIDUE_CATEGORY
        if digit and start is None:
            start = index
        elif not digit and start is not None:
            spans.append((start, index))
            start = None
    return spans


_TEMPORAL = [(item["class"], re.compile(item["pattern"], _A)) for item in _FIELD["temporal"]]
_STATEMENT = re.compile(_FIELD["statement"], _A)
_NEGATIONS = re.compile(_FIELD["negations"], _A)
_TRAILING_CONNECTIVES = re.compile(_FIELD["trailingConnectives"], _A)
_PREPARE = [(re.compile(pattern, _A), _js_replacement(replacement)) for pattern, replacement in _FIELD["prepare"]]
_PERIOD_RANGE = re.compile(_FIELD["periodRange"], _A)
_PERIOD_RANGE_GROUPS: dict[str, int] = _FIELD["periodRangeGroups"]
_PERIOD_SINGLE = re.compile(_FIELD["periodSingle"], _A)
_PERIOD_SINGLE_GROUPS: dict[str, int] = _FIELD["periodSingleGroups"]
_START_PREPOSITIONS = frozenset(_FIELD["startPrepositions"])
_END_PREPOSITIONS = frozenset(_FIELD["endPrepositions"])
_REWRITE = [(re.compile(pattern, _A), _js_replacement(replacement)) for pattern, replacement in _FIELD["rewrite"]]
_IGNORABLE = re.compile(_FIELD["ignorable"], _A)
_FATAL = re.compile(_FIELD["fatal"], _A)
_CLOCK_RANGE_TOKEN = re.compile(r"^(?:\d{4}-\d{4}|H24)$", _A)
_H24_DAILY: list[dict[str, Any]] = [{"kind": "daily", "times": [{"start": 0, "end": 1440}]}]
# Every month-day key (month index * 100 + day) of a leap year, in calendar order.
_CALENDAR_KEYS: tuple[int, ...] = tuple(month * 100 + day for month, days in enumerate((31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31))
                                        for day in range(1, days + 1))
_ENUMERATION_MAX_DAYS = _FIELD["equivalenceEnumerationMaxDays"]
_REGIME = re.compile(_ascii_digits(NOTAM_TIMING_RULES["runwayClosureRegimes"]["pattern"]), re.IGNORECASE)
_REGIME_GROUPS: dict[str, int] = NOTAM_TIMING_RULES["runwayClosureRegimes"]["groups"]
_OPEN_END_SEARCH_DAYS = NOTAM_TIMING_RULES["decision"]["openEndSearchDays"]
_LOOKBACK_DAYS = NOTAM_TIMING_RULES["decision"]["lookbackDays"]

# Stated as facts: the boss's R2 rule (22 Sep 2026) bans reminder wording in every string a surface prints.
TIMING_REVIEW_REASONS: dict[str, str] = dict(NOTAM_TIMING_RULES["reviewReasons"])


def _utc_ms(day: str, month_name: str, yy: str, hh: str, mm: str) -> int | None:
    month = _MONTHS.index(month_name.upper()) if month_name.upper() in _MONTHS else -1
    h, m = int(hh), int(mm)
    if month < 0 or h > 23 or m > 59:
        return None
    try:
        value = datetime(2000 + int(yy), month + 1, int(day), h, m, tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(value.timestamp() * 1000)


def iso_ms(ms: float) -> str:
    """The same ISO form the app writes: 2026-08-16T09:00:00.000Z."""
    value = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def parse_ms(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return math.nan
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() * 1000


def read_lido_validity(text: Any) -> dict[str, Any] | None:
    """The LIDO ``VALID:`` range: start, end (None when open) and how the end is stated; None when unreadable."""
    match = _VALIDITY_RANGE.match(str(text or "").upper())
    if not match:
        return None
    start = _utc_ms(*match.group(1, 2, 3, 4, 5))
    if start is None:
        return None
    end_text = match.group(6).strip()
    if end_text in _OPEN_ENDS:
        return {"startsAt": iso_ms(start), "endsAt": None, "endKind": _OPEN_ENDS[end_text]}
    end = _VALIDITY_END.match(end_text)
    end_ms = _utc_ms(*end.group(1, 2, 3, 4, 5)) if end else None
    if end_ms is None or end_ms <= start:
        return None
    return {"startsAt": iso_ms(start), "endsAt": iso_ms(end_ms), "endKind": "estimated" if end.group(6) else "explicit"}


_SYNTAX = _FIELD["syntax"]
_SYNTAX_QUOTES = frozenset(_SYNTAX["quotes"])
_SYNTAX_QUOTE_PAIRS = frozenset((opener, closer) for opener, closer in _SYNTAX["quotePairs"])
_SYNTAX_OPENERS = {opener: closer for opener, closer in _SYNTAX["brackets"]}
_SYNTAX_CLOSERS = {closer: opener for opener, closer in _SYNTAX["brackets"]}
_SYNTAX_LABEL_CLOSER = re.compile(_SYNTAX["labelCloser"], _A)
_SYNTAX_RANGE_SIDE = re.compile(_SYNTAX["rangeSide"], _A)
_SYNTAX_BOUNDARY = _SYNTAX["boundaryPunctuation"]
_SYNTAX_ELLIPSIS = re.compile(_SYNTAX["ellipsis"], _A)


def _letter_or_digit(ch: str) -> bool:
    return "A" <= ch <= "Z" or "0" <= ch <= "9"


def _syntax_text(text: str) -> tuple[str, list[int]]:
    """The syntactic text (QA518 I5: governance is punctuation-invariant) and, for each of its characters, the index of
    the character of ``text`` it stands for. ``text`` is upper-cased with dashes folded. Every piece of punctuation that
    can only wrap or join tokens is removed (syntax: a quote pair of matching kinds and any stray quote - never one glued
    on both sides or a unit mark after a digit -, a wrapping bracket pair, an ellipsis, a colon not between digits, a
    dash that joins no range); a removed wrapper leaves a space only where it alone kept two letters or digits apart, a
    removed colon or dash leaves a space; spaces are collapsed and a space before a boundary is dropped. Inserting,
    removing or moving such punctuation around a token never changes the result."""
    n = len(text)
    drop = [False] * n
    for match in _SYNTAX_ELLIPSIS.finditer(text):
        for index in range(*match.span()):
            drop[index] = True
    openings: list[int] = []
    for index, ch in enumerate(text):
        if ch not in _SYNTAX_QUOTES:
            continue
        left = text[index - 1] if index > 0 and not drop[index - 1] else " "
        right = text[index + 1] if index + 1 < n else " "
        if _letter_or_digit(left) and _letter_or_digit(right):
            continue  # glued on both sides: O'CLOCK, 26'15
        if (left == " " or left in _SYNTAX_OPENERS or (openings and openings[-1] == index - 1)) and right != " ":
            openings.append(index)  # an opening quote (after a space, an opening bracket or quote), until a closer of its kind
            continue
        if openings and (text[openings[-1]], ch) in _SYNTAX_QUOTE_PAIRS:
            drop[openings.pop()] = drop[index] = True
            continue
        if not ("0" <= left <= "9" and index > 0 and not drop[index - 1]):
            drop[index] = True  # a stray quote; right after a digit it stays as its unit mark (3000', '"3000'"')
    for index in openings:
        drop[index] = True
    stack: list[tuple[str, bool, int]] = []
    for index, ch in enumerate(text):
        if ch in _SYNTAX_OPENERS:
            glued = index > 0 and text[index - 1] != " " and not drop[index - 1]
            stack.append((ch, glued, index))
            drop[index] = not glued
        elif ch in _SYNTAX_CLOSERS:
            if stack and stack[-1][0] == _SYNTAX_CLOSERS[ch]:
                _, glued, at = stack.pop()
                # a pair inside a token - glued to it on the left (OCA(OCH)) or on the right ((A)2020) - stays
                internal = glued or (index + 1 < n and _letter_or_digit(text[index + 1]))
                drop[at] = drop[index] = not internal
            else:
                start = index
                while start > 0 and text[start - 1] != " ":
                    start -= 1
                run = "".join(text[pos] for pos in range(start, index) if not drop[pos])
                drop[index] = not _SYNTAX_LABEL_CLOSER.fullmatch(run)
    # A removed wrapper leaves a space only where it alone kept two letters or digits apart ('(1)APPLY'); elsewhere it
    # leaves nothing, so the text reads the same whether the wrapper was there or not ('(F))', '"121.35".').
    kept_at = [index for index in range(n) if not drop[index]]
    chars: list[tuple[str, int]] = []
    cursor = 0
    for index, ch in enumerate(text):
        if not drop[index]:
            chars.append((ch, index))
            cursor += 1
            continue
        before = text[kept_at[cursor - 1]] if cursor > 0 else " "
        after = text[kept_at[cursor]] if cursor < len(kept_at) else " "
        if _letter_or_digit(before) and _letter_or_digit(after):
            chars.append((" ", index))
    chars = [(" " if ch == ":" and not (0 < pos < len(chars) - 1 and "0" <= chars[pos - 1][0] <= "9"
                                        and "0" <= chars[pos + 1][0] <= "9") else ch, index)
             for pos, (ch, index) in enumerate(chars)]

    def collapse(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for ch, index in items:
            if ch == " " and (not out or out[-1][0] == " "):
                continue
            out.append((ch, index))
        while out and out[-1][0] == " ":
            out.pop()
        return out

    chars = collapse(chars)
    joined = "".join(ch for ch, _ in chars)
    kept: list[tuple[str, int]] = []
    for pos, (ch, index) in enumerate(chars):
        if ch == "-" and (pos == 0 or joined[pos - 1] == " " or pos == len(joined) - 1 or joined[pos + 1] == " "):
            before = joined[:pos].rstrip().split(" ")[-1].rstrip(_SYNTAX_BOUNDARY) if joined[:pos].strip() else ""
            after = joined[pos + 1:].lstrip().split(" ")[0].rstrip(_SYNTAX_BOUNDARY) if joined[pos + 1:].strip() else ""
            sides = [side for edge, side in ((not joined[:pos].strip(), before), (not joined[pos + 1:].strip(), after)) if not edge]
            # at a line's edge only the side present must be a range side ('AUG 16 1800-' wrapped before '2000'); a dash
            # alone on its line is read with the lines it joins ('MON' / '-' / 'FRI 0500-1500')
            if sides and not all(_SYNTAX_RANGE_SIDE.fullmatch(side.strip("-")) for side in sides):
                kept.append((" ", index))
                continue
        kept.append((ch, index))
    kept = collapse(kept)
    final: list[tuple[str, int]] = []
    for pos, item in enumerate(kept):
        if item[0] == " " and pos + 1 < len(kept) and kept[pos + 1][0] in _SYNTAX_BOUNDARY and (
                kept[pos + 1][0] != "." or pos + 2 == len(kept) or kept[pos + 2][0] == " "):
            continue
        final.append(item)
    return "".join(ch for ch, _ in final), [index for _, index in final]


def _field_text(line: Any) -> str:
    """A body line as the grammar reads it: format characters dropped and NFKC-normalised (normalisation: a full-width
    digit is a digit, no zero-width character splits a clock), upper-cased, dashes folded, whitespace collapsed. A
    lower-case 'l' inside a run holding a digit is written 'I' first (letterForDigit): a letter for a digit ('l800')
    stays a clock-like shape the grammar never reads, where upper-casing alone would turn it into a route designator
    (L800)."""
    rule, norm = _FIELD["letterForDigit"], _FIELD["normalisation"]
    text = "".join(ch for ch in str(line or "") if unicodedata.category(ch) != norm["drop"])
    text = _LETTER_FOR_DIGIT_RUN.sub(lambda run: run.group(0).replace(rule["letter"], rule["as"]),
                                     unicodedata.normalize(norm["form"], text))
    return _syntax_text(" ".join(_DASHES.sub("-", text.upper()).split()))[0]


def read_body_line(line: Any) -> str:
    """A LIDO body line as the timing grammar reads it - its syntactic text (QA518 I5): normalised, upper-cased, dashes
    folded, every piece of punctuation that can only wrap or join tokens removed. Two lines that differ only by such
    punctuation read the same, so every masking decision and every reading is the same for both."""
    return _field_text(line)


def _period_day(day: str, month: str, year: int) -> float | None:
    """The start of a calendar day in ms; None when no such day (or a year before 2000)."""
    if year < 2000:
        return None
    return _utc_ms(day, month[:3], str(year)[2:], "00", "00")


def _period_at(day_ms: float | None, time: str | None) -> float | None:
    if day_ms is None or not time:
        return day_ms
    hours, minutes = int(time[:2]), int(time[2:])
    if hours > 23 or minutes > 59:
        return None
    return day_ms + (hours * 60 + minutes) * _MINUTE_MS


def _full_year(year: str) -> int:
    return int(year) if len(year) == 4 else 2000 + int(year)


def _statement_periods(text: str) -> tuple[list[tuple[float, float]], str] | None:
    """A statement's calendar periods with a year (periodRange, then periodSingle) and what is left once they are
    taken out; None when a period cannot be read. A start with no time is the start of its day, an end with no time
    the end of its day; a start with no month or year takes the end's."""
    periods: list[tuple[float, float]] = []
    remainder = text
    g = _PERIOD_RANGE_GROUPS
    for match in list(_PERIOD_RANGE.finditer(text)):
        def group(key: str) -> str | None:
            return match.group(g[key])
        if group("endOpen"):
            if not group("startMonth") or not group("startYear"):
                return None
            start_day = _period_day(group("startDay"), group("startMonth"), _full_year(group("startYear")))
            end = math.inf
        else:
            end_day = _period_day(group("endDay"), group("endMonth"), _full_year(group("endYear")))
            if end_day is None:
                return None
            start_month = group("startMonth") or group("endMonth")
            if group("startYear"):
                start_year = _full_year(group("startYear"))
            else:
                end_year = _full_year(group("endYear"))
                start_year = end_year if _MONTHS.index(start_month[:3]) <= _MONTHS.index(group("endMonth")[:3]) else end_year - 1
            start_day = _period_day(group("startDay"), start_month, start_year)
            end_time = group("endTimeBefore") or group("endTimeAfter")
            end = _period_at(end_day, end_time) if end_time else end_day + _DAY_MS
        start = _period_at(start_day, group("startTimeBefore") or group("startTimeAfter"))
        if start is None or end is None or end <= start:
            return None
        periods.append((start, end))
        remainder = remainder[:match.start()] + " " * (match.end() - match.start()) + remainder[match.end():]
    g = _PERIOD_SINGLE_GROUPS
    for match in list(_PERIOD_SINGLE.finditer(remainder)):
        def group(key: str) -> str | None:
            return match.group(g[key])
        day = _period_day(group("day"), group("month"), _full_year(group("year")))
        if day is None:
            return None
        time = group("timeBefore") or group("timeAfter")
        preposition = group("prep")
        if preposition in _START_PREPOSITIONS:
            start = _period_at(day, time)
            if start is None:
                return None
            periods.append((start, math.inf))
        elif preposition in _END_PREPOSITIONS:
            end = _period_at(day, time) if time else day + _DAY_MS
            if end is None:
                return None
            periods.append((-math.inf, end))
        else:
            if time:
                return None  # a dated instant with no preposition is not a period
            periods.append((day, day + _DAY_MS))
        remainder = remainder[:match.start()] + " " * (match.end() - match.start()) + remainder[match.end():]
    return periods, remainder


def _merged_times(times: list[dict[str, int]]) -> str:
    merged: list[list[int]] = []
    for time in sorted(times, key=lambda item: (item["start"], item["end"])):
        if merged and time["start"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], time["end"])
        else:
            merged.append([time["start"], time["end"]])
    return ",".join(f"{start}-{end}" for start, end in merged)


def _day_part(entry: Mapping[str, Any]) -> str:
    """An entry's day part, canonical: D (daily), W<days> (weekdays) or M<month-days>R<ranges> (dates)."""
    if entry["kind"] == "daily" or (entry["kind"] == "weekdays" and set(entry["days"]) == set(range(7))):
        return "D"  # all seven weekdays are daily
    if entry["kind"] == "weekdays":
        return "W" + ",".join(str(day) for day in sorted(entry["days"]))
    # A date range is the month-day keys it matches (a leap year's 366, wrapping past DEC 31): 'AUG 10-AUG 20' and
    # 'AUG 10-20' are the same day part.
    keys = set(entry["monthDays"])
    for low, high in entry["ranges"]:
        keys.update(key for key in _CALENDAR_KEYS if (low <= key <= high if low <= high else key >= low or key <= high))
    return "M" + ",".join(str(key) for key in sorted(keys))


def _canonical_rules(entries: list[dict[str, Any]]) -> str:
    """The canonical rule set: each day part with its merged hours. Equal rule sets have equal occurrences every day."""
    by_part: dict[str, list[dict[str, int]]] = {}
    for entry in entries:
        by_part.setdefault(_day_part(entry), []).extend(entry["times"])
    return ";".join(sorted(f"{key}:{_merged_times(times)}" for key, times in by_part.items()))


def _whole_validity_coverage(entries: list[dict[str, Any]], validity: Mapping[str, Any]) -> str | None:
    """The merged occurrences over the WHOLE validity; None when it is open-ended or longer than the enumeration bound."""
    start_ms = parse_ms(validity.get("startsAt"))
    end_ms = parse_ms(validity.get("endsAt")) if validity.get("endsAt") else math.inf
    if not math.isfinite(end_ms) or end_ms - start_ms > _ENUMERATION_MAX_DAYS * _DAY_MS:
        return None
    merged: list[list[float]] = []
    for item_start, item_end in schedule_occurrences(entries, start_ms, end_ms, start_ms, end_ms):
        if merged and item_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], item_end)
        else:
            merged.append([item_start, item_end])
    return ",".join(f"{int(start)}-{int(end)}" for start, end in merged)


def _same_schedule(left: list[dict[str, Any]], right: list[dict[str, Any]], validity: Mapping[str, Any]) -> bool:
    """Proven equal: the same canonical rule set, or the same occurrences over the whole bounded validity."""
    if _canonical_rules(left) == _canonical_rules(right):
        return True
    coverage = _whole_validity_coverage(left, validity)
    return coverage is not None and coverage == _whole_validity_coverage(right, validity)


def _clipped_coverage(entries: list[dict[str, Any]], validity_start: float, validity_end: float,
                      clip_start: float, clip_end: float) -> str:
    """The merged occurrences inside the validity clipped to [clip_start, clip_end) (a bounded span)."""
    low, high = max(validity_start, clip_start), min(validity_end, clip_end)
    if not low < high:
        return ""
    merged: list[list[float]] = []
    for item_start, item_end in schedule_occurrences(entries, low, high, low, high):
        if merged and item_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], item_end)
        else:
            merged.append([item_start, item_end])
    return ",".join(f"{int(start)}-{int(end)}" for start, end in merged)


def _paint(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = "#" * (end - start)
    return "".join(chars)


def _temporal_tokens(masked: str) -> list[tuple[int, int]]:
    return [match.span() for _name, pattern in _TEMPORAL for match in pattern.finditer(masked) if match.end() > match.start()]


def _benign_spans(text: str, line_starts: Iterable[int] = (0,)) -> list[tuple[int, int, str]]:
    """The benign spans kept in one free-text line, as (start, end, class): every span a benign class POSITIVELY
    classifies as not temporal. A span never cuts a clock-like shape found in the unmasked text (benignNeverCuts: it
    may hold a whole one - 'TORA 2100' - never part of one: 'FL180/18' of 'FL180/18 00'), and never holds any
    temporal token of the unmasked text when its class states holdsNoTemporal; a span that holds or cuts a clock-
    like range is never benign unless its class states allowClockRange (benignNeverHolds); a span is never the
    object of a temporal connective (benignGovernance, QA514: one beginning with a digit or a time word directly
    after DURING, UNTIL, FROM, AT, TO ..., and any holding a digit after DURING, OUTSIDE, SINCE or WEF, unless it is
    self-evidently not a time); and a span is never one side of a range: it is refused when a range connector joins
    it to temporal content left unmasked once every candidate span is masked (rangeAbutment). A class that states
    maskGroup masks only that group of its match; a class that states atLineStart keeps a match only where a body
    line opens (QA514 G3: a list label at a line's start), ``line_starts`` being the offsets at which the free text's
    body lines open. A span never touches a digit the grammar does not read (benignNeverTouches, QA516: a decimal digit
    of another script before or after it)."""
    opens = set(line_starts)
    ranges = [match.span() for match in _BENIGN_NEVER_HOLDS.finditer(text)]
    shapes = [match.span() for match in _BENIGN_NEVER_CUTS.finditer(text)]

    def meets_range(start: int, end: int) -> bool:
        return any(low < end and start < high for low, high in ranges)

    def cuts_shape(start: int, end: int) -> bool:
        return any(low < start < high or low < end < high for low, high in shapes)

    temporal = _temporal_tokens(text)

    def holds_temporal(start: int, end: int) -> bool:
        return any(low < end and start < high for low, high in temporal)

    def governed(start: int, end: int) -> bool:
        span, before = text[start:end], text[:start]
        governing = ((_GOVERNED_OBJECT.search(span) and _GOVERNING_CONNECTIVE.search(before))
                     or (re.search(r"[0-9]", span) and _PERIOD_CONNECTIVE.search(before)))
        return bool(governing and not _SELF_EVIDENT.search(span))

    spans: list[tuple[int, int, str]] = []
    for name, pattern, allow_clock_range, holds_no_temporal, mask_group, at_line_start in _BENIGN:
        for match in pattern.finditer(text):
            start, end = match.span(mask_group)
            if (end <= start or (at_line_start and start not in opens) or cuts_shape(start, end)
                    or (not allow_clock_range and meets_range(start, end))):
                continue
            if (start > 0 and _unread_digit(text[start - 1])) or (end < len(text) and _unread_digit(text[end])):
                continue
            if (holds_no_temporal and holds_temporal(start, end)) or governed(start, end):
                continue
            spans.append((start, end, name))
    provisional = _paint(text, [(start, end) for start, end, _ in spans])
    tokens = _temporal_tokens(provisional)
    starts = {start for start, _ in tokens}
    ends = {end for _, end in tokens}

    def abuts(span: tuple[int, int, str]) -> bool:
        start, end, _name = span
        after = _ABUTS_AFTER.search(provisional[end:])
        if after and end + after.end() in starts:
            return True
        before = _ABUTS_BEFORE.search(provisional[:start])
        return bool(before and before.start() in ends)

    return [span for span in spans if not abuts(span)]


def _mask_benign(text: str, line_starts: Iterable[int] = (0,)) -> str:
    return _paint(text, [(start, end) for start, end, _ in _benign_spans(text, line_starts)])


def explain_schedule_free_text(text: str, line_starts: Iterable[int] = (0,)) -> dict[str, Any]:
    """The benign spans kept in one free-text line and the text they leave (QA514 tests and fuzzing: which class
    masked what). ``text`` is a body line as the grammar reads it (upper case, dashes folded, whitespace collapsed), or
    body lines joined with one space, ``line_starts`` the offsets at which they open. ``spans`` index ``text``;
    ``text``/``syntaxSpans`` are its syntactic text (QA518 I5) and the spans in it, ``origin`` the index in ``text`` of
    each syntactic character."""
    raw = str(text or "")
    syntax, origin = _syntax_text(raw)
    starts = sorted({next((pos for pos, index in enumerate(origin) if index >= start), len(syntax)) for start in line_starts})
    kept = _benign_spans(syntax, starts)
    spans = [(origin[start], origin[end - 1] + 1, name) for start, end, name in kept]
    return {"masked": _paint(raw, [(start, end) for start, end, _ in spans]),
            "spans": [{"class": name, "start": start, "end": end} for start, end, name in spans],
            "text": syntax, "origin": origin,
            "syntaxSpans": [{"class": name, "start": start, "end": end} for start, end, name in kept]}


def _regroup(text: str) -> str:
    """Days and hours bound in either order: a run that starts with hours and ends with days ('1800-2000 ON SUN',
    '1700-2200 SUN WED') is rewritten days-first, as Item D writes it."""
    groups: list[list[Any]] = []
    for token in text.split():
        kind = "T" if _CLOCK_RANGE_TOKEN.match(token) else "D"
        if groups and groups[-1][0] == kind:
            groups[-1][1].append(token)
        else:
            groups.append([kind, [token]])
    if len(groups) >= 2 and groups[0][0] == "T" and groups[-1][0] == "D":
        ordered: list[str] = []
        for index in range(0, len(groups), 2):
            ordered += groups[index + 1][1] + groups[index][1]
        return " ".join(ordered)
    return text


def _parse_statement(text: str, validity: Mapping[str, Any]) -> tuple[list[tuple[float, float]], list[dict[str, Any]]] | None:
    """A statement read whole: its periods and its schedule entries (days bound to hours); None when it cannot be."""
    statement = _TRAILING_CONNECTIVES.sub("", " " + text.strip(" ,;:/-")).strip(" ,;:/-")
    if _NEGATIONS.search(statement):
        return None
    for pattern, replacement in _PREPARE:
        statement = pattern.sub(replacement, statement)
    read = _statement_periods(statement)
    if read is None:
        return None
    periods, remainder = read
    for pattern, replacement in _REWRITE:
        remainder = pattern.sub(replacement, remainder)
    remainder = " ".join(re.sub(r"\s*-\s*", "-", remainder).split()).strip(" -")
    if _IGNORABLE.match(remainder):
        remainder = ""
    if _FATAL.search(remainder):
        return None
    if not remainder:
        return (periods, []) if periods else None
    entries, error = parse_schedule_field(_regroup(remainder), validity, allow_date_only=True)
    return None if error else (periods, entries)


def _statement_accounted(periods: list[tuple[float, float]], entries: list[dict[str, Any]],
                         field_entries: list[dict[str, Any]] | None, validity: Mapping[str, Any]) -> bool:
    """Periods alone must contain the whole validity (a start at or before B, an end at or after C). A schedule must be
    proven equal on its own to Item D (or, with no Item D, the whole validity), clipped by any period it holds."""
    start_ms = parse_ms(validity.get("startsAt"))
    end_ms = parse_ms(validity.get("endsAt")) if validity.get("endsAt") else math.inf
    if not entries:
        return all(low <= start_ms and high >= end_ms for low, high in periods)
    target = field_entries if field_entries is not None else _H24_DAILY
    low = max((period[0] for period in periods), default=-math.inf)
    high = min((period[1] for period in periods), default=math.inf)
    if low <= start_ms and high >= end_ms:
        return _same_schedule(entries, target, validity)
    if not math.isfinite(end_ms) or end_ms - start_ms > _ENUMERATION_MAX_DAYS * _DAY_MS:
        return False
    return (_clipped_coverage(entries, start_ms, end_ms, low, high)
            == _clipped_coverage(target, start_ms, end_ms, -math.inf, math.inf))


_OBJECT = _FIELD["temporalObject"]


def _words_rx(words: str) -> re.Pattern[str]:
    return re.compile(f"(?:{words})", _A)


_OBJECT_CLASSES = {name: _words_rx(words) for name, words in _OBJECT["connectives"].items()}
_OBJECT_RANGE_AFTER = _words_rx(_OBJECT["rangeEnd"]["after"])
_OBJECT_RANGE_END = _words_rx(_OBJECT["rangeEnd"]["connective"])
_OBJECT_RANGE_WITHIN = int(_OBJECT["rangeEnd"]["withinWords"])
_OBJECT_RESTRICTION = re.compile(f"(?<![A-Z0-9/])(?:{_OBJECT['restriction']})(?![A-Z0-9/])", _A)
_OBJECT_RESTRICTION_WORD = _words_rx(_OBJECT["restriction"])
_OBJECT_SKIP = _words_rx(_OBJECT["skip"])
_OBJECT_DETERMINER = _words_rx(_OBJECT["determiner"])
_OBJECT_FUNCTION = _words_rx(_OBJECT["function"])
_OBJECT_END = _words_rx(_OBJECT["objectEnd"])
_OBJECT_VERBS = _words_rx(_OBJECT["verbs"])
_OBJECT_LABELS = _words_rx(_OBJECT["labels"])
# a label opening a token of the unmasked text (a mask may cover it with what follows: 'F) 7000FT AMSL')
_OBJECT_LABEL_AT = re.compile(f"(?<![^ ])(?:{_OBJECT['labels']})(?![^ ,.;])", _A)
_OBJECT_HEAD_ONLY = _words_rx(_OBJECT["headOnly"])
_OBJECT_HEAD_ONLY_MASKS = frozenset(_OBJECT["headOnlyMasks"])
_OBJECT_END_MASKS = frozenset(_OBJECT["endMasks"])
_OBJECT_CANONICAL_CLOCK = _words_rx(_OBJECT["canonicalClock"])
_OBJECT_COMPLEMENT = _words_rx(_OBJECT["complement"])
_OBJECT_COORDINATION = _words_rx(_OBJECT["coordination"])
_OBJECT_POSTPOSITIVE = _words_rx(_OBJECT["postpositive"])
_OBJECT_OPEN_END_AFTER = _words_rx(_OBJECT["openEndAfter"])
_OBJECT_STOP = _words_rx(_OBJECT["stop"])
_OBJECT_OPEN_END = re.compile(f"(?:{_OBJECT['openEnd']})(?![A-Z0-9])", _A)
_OBJECT_MODIFIER = _words_rx(_OBJECT["temporalModifier"])
_OBJECT_BOUND_PART = tuple(_OBJECT["boundPart"])
_OBJECT_DEGREE = _words_rx(_OBJECT["degree"])
_OBJECT_DIRECTION = _words_rx(_OBJECT["direction"])
_GAZ = _OBJECT["gazetteer"]
_GAZ_STATION = re.compile(_GAZ["stationHeading"], _A)
_GAZ_FIR = re.compile(_GAZ["firHeading"], _A)
_GAZ_RULE = re.compile(_GAZ["rule"], _A)
_GAZ_TAIL = re.compile(_GAZ["headingTail"], _A)
_GAZ_SPLIT = re.compile(_GAZ["nameSplit"], _A)
_GAZ_LINK = _words_rx(_GAZ["routeLink"])
_GAZ_FIX = _words_rx(_GAZ["fix"])
_GAZ_INDICATOR = _words_rx(_GAZ["indicator"])
_GAZ_NAME_MIN = int(_GAZ["nameMin"])
_GAZ_LINKS = int(_GAZ["routeLinks"])
_OBJECT_LEAD = _words_rx(_OBJECT["leadModifier"])
_OBJECT_LEAD_HEADS = _words_rx(_OBJECT["leadHeads"])
_OBJECT_ANAPHORA = _words_rx(_OBJECT["anaphora"])
_OBJECT_ANAPHORA_PERIOD = _words_rx(_OBJECT["anaphoraPeriod"])
_OBJECT_CODE = _words_rx(_OBJECT["code"])
_OBJECT_CODE_NEVER = _words_rx(_OBJECT["codeNever"])
_OBJECT_CODE_ALONE = _words_rx(_OBJECT["codeAlone"])
_OBJECT_DESIGNATOR = _words_rx(_OBJECT["designator"])
_OBJECT_DESIGNATOR_NEVER = _words_rx(_OBJECT["designatorNever"])
_OBJECT_ROLES = {name: _words_rx(words) for name, words in _OBJECT["roles"].items()}
_OBJECT_ADMITS = {kind: tuple(roles) for kind, roles in _OBJECT["admits"].items()}
_OBJECT_MODIFIERS = {kind: tuple(roles) for kind, roles in _OBJECT["modifiers"].items()}
_OBJECT_DESIGNATION_NOUN = _words_rx(_OBJECT["designationNoun"])
_OBJECT_SENTENCE = re.compile(_FIELD["syntax"]["clauseBoundary"], _A)
_OBJECT_BOUNDARY = re.compile(_OBJECT["objectBoundary"], _A)
_CONTENT = re.compile(r"[A-Z0-9#]", _A)
# the ledger's statuses (QA520 I8): an obligation is discharged by classification, by accounting, or by the connective
# whose operand it takes; anything else is undischarged
LEDGER_DISCHARGED = ("classified", "accounted", "chained", "free")
LEDGER_STATUSES = (*LEDGER_DISCHARGED, "undischarged")


def _roles_of(word: str, roles: Iterable[str]) -> list[str]:
    """Every one of ``roles`` whose role list names ``word`` (a word may carry several: END is a place, a modifier)."""
    return [role for role in roles if role in _OBJECT_ROLES and _OBJECT_ROLES[role].fullmatch(word)]


def _object_words(masked: str, low: int, high: int) -> list[tuple[int, int, str, bool]]:
    """The words of masked[low:high] as (start, end, word, closed): a word is split at an object boundary (a comma not
    before a digit), and 'closed' says the boundary follows it."""
    words: list[tuple[int, int, str, bool]] = []
    for match in re.finditer(r"[^ ]+", masked[low:high]):
        at = low + match.start()
        rest = match.group()
        while rest:
            cut = _OBJECT_BOUNDARY.search(rest)
            if cut is None:
                words.append((at, at + len(rest), rest, False))
                break
            if cut.start():
                words.append((at, at + cut.start(), rest[:cut.start()], True))
            elif words:
                words[-1] = (*words[-1][:3], True)
            at += cut.end()
            rest = rest[cut.end():]
    return words


def _is_code(word: str) -> bool:
    return bool(_OBJECT_CODE.fullmatch(word)) and not _OBJECT_CODE_NEVER.fullmatch(word)


def _connective_class(word: str) -> str | None:
    """The connective class naming ``word`` (the classes are disjoint word lists, so at most one names it)."""
    for name, pattern in _OBJECT_CLASSES.items():
        if pattern.fullmatch(word):
            return name
    return None


def _ends_operand(word: str) -> bool:
    """A word no operand continues through: a stop word, a restriction word, a word ending a noun phrase, a verb that is
    no role word (the next clause's predicate), a label (a new item)."""
    return bool(_OBJECT_STOP.fullmatch(word) or _OBJECT_RESTRICTION_WORD.fullmatch(word) or _OBJECT_END.fullmatch(word)
                or _OBJECT_LABELS.fullmatch(word) or (_OBJECT_VERBS.fullmatch(word) and not _roles_of(word, _OBJECT_ROLES)))


def _list_continues(words: list[tuple[int, int, str, bool]], at: int) -> bool:
    """Whether a comma before words[at] separates items of a list: AND/OR follows before anything that ends the
    operand ('BTN FAI, ORT AND BRW'; 'EXCEPT FOR HUMANITARIAN, SAR AND LEASED AIRCRAFT')."""
    for _low, _high, word, closed in words[at:]:
        if _OBJECT_COORDINATION.fullmatch(word):
            return not closed
        if _ends_operand(word) or _connective_class(word):
            return False
    return False


def _shares_operand(word: str) -> bool:
    """A word coordinated after a connective that shares its operand: a connective, a preposition (objectEnd), or a verb
    (a verb that is no role word, or an -ING form with no other role) - 'AT OR BLW', 'FM OR OVERFLY', 'TO OR FROM, WITHIN,
    OR TRANSITING'; never a noun ('BEFORE, OR HOLDING POINT B' has no operand)."""
    if _connective_class(word) or _OBJECT_RANGE_END.fullmatch(word) or _OBJECT_END.fullmatch(word):
        return True
    roles = _roles_of(word, _OBJECT_ROLES)
    return bool(_OBJECT_VERBS.fullmatch(word) and not roles) or roles == ["action"]


def _conjunct() -> dict[str, Any]:
    return {"words": [], "complement": [], "complementDetermined": False}


def _read_conjuncts(words: list[tuple[int, int, str, bool]], at: int, labels: set[int], heads: set[int],
                    limit: int | None = None, inline: frozenset[int] = frozenset()) -> tuple[list[dict[str, Any]], bool]:
    """The operand's conjuncts read from words[at] (temporalObject: objectEnd, stop, restriction, label, complement,
    coordination; a list continues through commas to AND/OR; a head-only noun ends its phrase), and whether the operand
    is cut off: AND/OR or OF with nothing after it in the clause, or a boundary right after it ('BTN TWY B AND.'). No
    word limit: an operand is never truncated - but one the grammar reads (its first word in a statement) is that
    statement's, and ends where the statement does (``limit``)."""
    cut = False
    conjuncts = [_conjunct()]
    target = conjuncts[-1]["words"]
    while at < len(words):
        low, high, word, closed = words[at]
        if (target and low in labels) or (limit is not None and low >= limit):
            break
        if target:
            if _OBJECT_COORDINATION.fullmatch(word) or (_OBJECT_COMPLEMENT.fullmatch(word)
                                                        and target is conjuncts[-1]["words"]):
                follow = words[at + 1] if at + 1 < len(words) else None
                if (closed or follow is None or (follow[0] in labels and follow[0] not in inline)
                        or (limit is not None and follow[0] >= limit)):
                    cut = True  # 'BTN TWY B AND.', 'AT THE INTERSECTION OF.': the operand is cut off
                    break
            if _OBJECT_COORDINATION.fullmatch(word) and not closed:
                follow = words[at + 1][2]
                if _ends_operand(follow) or _connective_class(follow):
                    break
                conjuncts.append(_conjunct())
                target = conjuncts[-1]["words"]
                at += 1
                continue
            if _OBJECT_COMPLEMENT.fullmatch(word) and not closed and target is conjuncts[-1]["words"]:
                at += 1
                determined = False
                while at < len(words) and _OBJECT_SKIP.fullmatch(words[at][2]) and not words[at][3]:
                    determined = determined or bool(_OBJECT_DETERMINER.fullmatch(words[at][2]))
                    at += 1
                conjuncts[-1]["complementDetermined"] = determined
                target = conjuncts[-1]["complement"]
                continue
            if _ends_operand(word):
                break
        elif _connective_class(word):
            break
        target.append((low, high, word))
        at += 1
        if ((_OBJECT_HEAD_ONLY.fullmatch(word) or low in heads) and target is conjuncts[-1]["words"] and at < len(words)
                and not words[at - 1][3] and not _OBJECT_COMPLEMENT.fullmatch(words[at][2])
                and not _OBJECT_COORDINATION.fullmatch(words[at][2])):
            break  # 'DRG EXER PERIOD FLW RESTRICTIONS APPLY', 'AT PSN 512739N 0002745W HEATHROW': a head-only noun ends it
        if closed:
            if not _list_continues(words, at):
                break
            if at < len(words) and not _OBJECT_COORDINATION.fullmatch(words[at][2]):
                conjuncts.append(_conjunct())
                target = conjuncts[-1]["words"]
    return [item for item in conjuncts if item["words"]], cut


def _read_before(words: list[tuple[int, int, str, bool]], index: int) -> list[dict[str, Any]]:
    """A postpositive connective's operand: the noun phrase before words[index] (conjuncts through AND/OR), back to a
    boundary, a word that ends an operand or the sentence's start."""
    taken: list[tuple[int, int, str]] = []
    at = index - 1
    while at >= 0:
        low, high, word, closed = words[at]
        if closed:
            break
        if _OBJECT_COORDINATION.fullmatch(word):
            if not taken or at == 0 or words[at - 1][3] or _ends_operand(words[at - 1][2]) or _connective_class(words[at - 1][2]):
                break
        elif _ends_operand(word) or _connective_class(word):
            break
        taken.insert(0, (low, high, word))
        at -= 1
    conjuncts = [_conjunct()]
    for item in taken:
        if _OBJECT_COORDINATION.fullmatch(item[2]):
            conjuncts.append(_conjunct())
        else:
            conjuncts[-1]["words"].append(item)
    return [item for item in conjuncts if item["words"]]


def _statement_end(words: list[tuple[int, int, str, bool]], at: int, statements: list[tuple[int, int]]) -> int | None:
    """Where the statement holding the operand's first word ends, when the grammar reads that word: the grammar reads
    the operand, so the operand is the statement's ('WEF 09MAY2024 0400UTC ACFT STANDS ...'), else None."""
    if at >= len(words):
        return None
    low = words[at][0]
    return next((end for start, end in statements if start <= low < end), None)


def _read_operand(entry: dict[str, Any], words: list[tuple[int, int, str, bool]], index: int, masked: str,
                  labels: set[int], heads: set[int], statements: list[tuple[int, int]], text: str,
                  inline: frozenset[int] = frozenset()) -> None:
    """Fill ``entry`` with the operand of the connective words[index] (temporalObject; QA520 I8): a phrase (conjuncts),
    a chain to the connective that follows it, a shared operand, the noun phrase before a postpositive connective, an
    open end - or 'missing', with the reason no operand is there."""
    word, closed = words[index][2], words[index][3]
    postpositive = bool(_OBJECT_POSTPOSITIVE.fullmatch(word))

    def shared(at: int) -> None:
        # 'AT OR BLW 3000FT', 'BFR OR AFT THE CLOSURE', 'FROM, WITHIN, OR TRANSITING THE SFRA': the operand of the
        # coordinated word words[at] - a preposition or a verb, or a mask holding one ('OR BLW 3000FT')
        entry["reading"] = "shared"
        opening = text[words[at][0]:words[at][1]].split(" ")[0]  # a mask's own first word ('OR BLW 3000FT')
        if not _shares_operand(opening if "#" in words[at][2] else words[at][2]):
            entry.update(operand="missing", reason="separated")
        elif "#" in words[at][2]:
            entry.update(operand="phrase", conjuncts=[{**_conjunct(), "words": [words[at][:3]]}])
        elif _connective_class(words[at][2]) or (at in entry["_ranges"]):
            entry.update(operand="chain", chainAt=at)
        else:
            follow = at + 1
            determined = False
            entry["skipped"].append(words[at][2])  # the coordinated word stands between the connective and the operand
            while follow < len(words) and _OBJECT_SKIP.fullmatch(words[follow][2]) and not words[follow][3]:
                determined = determined or bool(_OBJECT_DETERMINER.fullmatch(words[follow][2]))
                entry["skipped"].append(words[follow][2])
                follow += 1
            entry["determined"] = determined
            conjuncts, cut = (_read_conjuncts(words, follow, labels, heads, _statement_end(words, follow, statements), inline)
                              if follow < len(words) and not words[at][3] else ([], False))
            if conjuncts:
                entry.update(operand="phrase", conjuncts=conjuncts, cut=cut)
            else:
                entry.update(operand="missing", reason="sharedEmpty")

    def before(reason: str) -> None:
        conjuncts = _read_before(words, index)  # a restriction verb ends it: a bare predicate is no noun phrase
        if conjuncts:
            entry.update(operand="postpositive", conjuncts=conjuncts)
        else:
            entry.update(operand="missing", reason=reason)

    if closed:
        at = index + 1
        while at < len(words) and words[at][3] and not _OBJECT_COORDINATION.fullmatch(words[at][2]):
            at += 1
        if at + 1 < len(words) and _OBJECT_COORDINATION.fullmatch(words[at][2]) and not words[at][3]:
            shared(at + 1)
        elif postpositive:
            before("separated")
        else:
            entry.update(operand="missing", reason="separated")
        return
    at = index + 1
    if at + 1 < len(words) and _OBJECT_COORDINATION.fullmatch(words[at][2]) and not words[at][3]:
        shared(at + 1)
        return
    determined = False
    while at < len(words) and _OBJECT_SKIP.fullmatch(words[at][2]) and not words[at][3]:
        determined = determined or bool(_OBJECT_DETERMINER.fullmatch(words[at][2]))
        entry["skipped"].append(words[at][2])
        at += 1
    entry["determined"] = determined
    if at >= len(words):
        if postpositive and at == index + 1:
            before("clauseEnd")
        else:
            entry.update(operand="missing", reason="skipExhausted" if at > index + 1 else "clauseEnd")
        return
    follow = words[at][2]
    if _connective_class(follow) or at in entry["_ranges"]:
        entry.update(operand="chain", chainAt=at)
        return
    if _OBJECT_OPEN_END_AFTER.fullmatch(word) and _OBJECT_OPEN_END.match(masked, words[at][0]):
        entry.update(operand="openEnd")
        return
    conjuncts, cut = _read_conjuncts(words, at, labels, heads, _statement_end(words, at, statements), inline)
    if conjuncts:
        entry.update(operand="phrase", conjuncts=conjuncts, cut=cut)
    else:
        entry.update(operand="missing", reason="empty")


def _designator(word: str, low: int, high: int, temporal: list[tuple[int, int]], noun: str | None = None) -> bool:
    """A designator: a single letter, a token holding a digit, a spelling-alphabet word, or two letters after a noun
    that takes them (designationNoun: 'TWY KE') - never a role word, a temporal modifier or temporal vocabulary
    (designatorNever, or any temporal token of the masked text)."""
    shaped = bool(_OBJECT_DESIGNATOR.fullmatch(word)) or (
        noun is not None and bool(re.fullmatch("[A-Z]{2}", word)) and bool(_OBJECT_DESIGNATION_NOUN.fullmatch(noun)))
    return (shaped and not _OBJECT_DESIGNATOR_NEVER.fullmatch(word) and not _OBJECT_MODIFIER.fullmatch(word)
            and not _roles_of(word, _OBJECT_ROLES) and not any(start < high and low < end for start, end in temporal))


def _mask_classifies(ctx: dict[str, Any], low: int, high: int, object_position: bool) -> bool:
    """A benign mask classifies a token of a governing connective's operand (benignGovernance.connective: a connective
    that takes a time) only where no place word licenses temporal content (I7): never (a) where QA514's governance
    would refuse it directly after the connective - its text begins with a digit or a time word, or after DURING,
    OUTSIDE, SINCE or WEF holds a digit - while only classified words (place, facility, designated place) stand between
    it and the connective in the operand's first noun phrase (``object_position``: pre-modifiers do not change the
    object: 'UNTIL AIRPORT 121.35', 'UNTIL RWY 08R 121.35' are 'UNTIL 121.35'); nor (b) anywhere, when a word of it is
    a canonical clock (four digits, 0000-2359) or a time designator
    glued to digits (UTC2865, Z0865) - a designation noun never licenses one ('UNTIL RUNWAY 1000'); unless it is
    self-evidently not a time (a unit of length, height, speed, mass or angle, a flight level, a position ...)."""
    if not ctx["governing"]:
        return True
    span = ctx["text"][low:high]
    if _SELF_EVIDENT.search(span):
        return True
    if object_position and (_GOVERNED_OBJECT.search(span) or (ctx["period"] and re.search(r"[0-9]", span))):
        return False
    return not any(_OBJECT_CANONICAL_CLOCK.fullmatch(word.strip(",.;:()")) for word in span.split(" "))


def build_timing_gazetteer(lines: Iterable[Any]) -> dict[str, list[str]]:
    """QA520: the places the briefing itself names, read once per analysis from the OFP's own text lines
    (temporalObject.gazetteer): the words of every NOTAM bulletin station heading's name and FIR heading's name
    ('VRMM /MLE MALE/VELANA INTL - DETAILED INFO': MALE, VELANA, INTL; 'VHHK HONG KONG FIR': HONG, KONG), their location
    indicators (VRMM, VHHK), and every five-letter fix a route string names next to DCT or an airway ('SAMKO W407').
    Plain data, the same in both runtimes for the same lines; the decision classifies an operand's token against it."""
    rows = [" ".join(str(line).upper().split()) for line in lines]
    rows = [row for row in rows if row]
    names: set[str] = set()
    indicators: set[str] = set()
    fixes: set[str] = set()
    for index, row in enumerate(rows):
        if index + 1 < len(rows) and _GAZ_RULE.fullmatch(rows[index + 1]):
            station = _GAZ_STATION.fullmatch(row)
            fir = None if station else _GAZ_FIR.fullmatch(row)
            heading = station or fir
            if heading:
                indicators.add(heading.group(1))
                name = _GAZ_TAIL.sub("", heading.group(2), count=1) if station else heading.group(2)
                names.update(word for word in _GAZ_SPLIT.split(name) if word)
        tokens = row.split(" ")
        if sum(1 for token in tokens if _GAZ_LINK.fullmatch(token)) < _GAZ_LINKS:
            continue
        for at, token in enumerate(tokens):
            if (_GAZ_FIX.fullmatch(token) and not _rule_word(token)
                    and ((at and _GAZ_LINK.fullmatch(tokens[at - 1]))
                         or (at + 1 < len(tokens) and _GAZ_LINK.fullmatch(tokens[at + 1])))):
                fixes.add(token)
    names = {word for word in names if len(word) >= _GAZ_NAME_MIN and word.isascii() and word.isalpha()}
    return {"names": sorted(names), "indicators": sorted(word for word in indicators if _GAZ_INDICATOR.fullmatch(word)),
            "fixes": sorted(fixes)}


def _rule_word(word: str) -> bool:
    """A word the rules know by another class - a role, stop, skip, function, verb, connective, label or temporal
    word - is never a fix."""
    return bool(_roles_of(word, _OBJECT_ROLES) or _OBJECT_STOP.fullmatch(word) or _OBJECT_SKIP.fullmatch(word)
                or _OBJECT_FUNCTION.fullmatch(word) or _OBJECT_END.fullmatch(word) or _OBJECT_VERBS.fullmatch(word)
                or _OBJECT_RESTRICTION_WORD.fullmatch(word) or _connective_class(word) or _OBJECT_LABELS.fullmatch(word)
                or _OBJECT_MODIFIER.fullmatch(word) or _OBJECT_DESIGNATOR_NEVER.fullmatch(word)
                or _OBJECT_CODE_NEVER.fullmatch(word) or _OBJECT_ANAPHORA.fullmatch(word))


def _gazetteer_lookup(gazetteer: Mapping[str, Any] | None) -> frozenset[str] | None:
    """Every word the gazetteer names as a place (names, indicators, fixes), or None."""
    if not gazetteer:
        return None
    return frozenset([*gazetteer.get("names", ()), *gazetteer.get("indicators", ()), *gazetteer.get("fixes", ())])


def _named_place(places: frozenset[str] | None, word: str, low: int, high: int, temporal: list[tuple[int, int]]) -> bool:
    """A token the briefing names as a place (QA520 gazetteer) - never a temporal token, a temporal modifier, a word that
    is never a designator (a day, a month, a time word) or a code that is never a code (ETD, NOW ...)."""
    return (places is not None and word in places and not _OBJECT_MODIFIER.fullmatch(word)
            and not _OBJECT_DESIGNATOR_NEVER.fullmatch(word) and not _OBJECT_CODE_NEVER.fullmatch(word)
            and not any(start < high and low < end for start, end in temporal))


def _compound_classified(kind: str, word: str, low: int, high: int, temporal: list[tuple[int, int]],
                         noun: str | None, places: frozenset[str] | None = None) -> bool:
    """A token joined by a slash or holding a bracketed part ('ALTITUDE/HEIGHT', 'TO/OUTBOUND', 'OCA(H)', 'TWY B/C') is
    classified when each of its parts is, read as a phrase after the classified noun before it (if any) - coordination
    and stop words among the parts aside - and one part at least by a role or a designator; never when it holds
    temporal content."""
    parts = [part for part in re.split(r"[/()]", word) if part]
    if len(parts) < 2 or any(start < high and low < end for start, end in temporal):
        return False
    words = [(0, 0, part) for part in parts if not (_OBJECT_COORDINATION.fullmatch(part) or _OBJECT_STOP.fullmatch(part))]
    if not words:
        return False
    lead = [(0, 0, noun)] if noun is not None else []
    classes = [item[3] for item in _classify_np(kind, lead + words, False, [], None, places)][len(lead):]
    return all(cls is not None and not cls.endswith("?") for cls in classes) and any(
        cls.startswith("role:") or cls == "designator" for cls in classes)


def _classify_np(kind: str, np: list[tuple[int, int, str]], determined: bool,
                 temporal: list[tuple[int, int]], ctx: dict[str, Any] | None,
                 places: frozenset[str] | None = None) -> list[list[Any]]:
    """Classify every token of one noun phrase (QA520 I7) as [start, end, word, class]; class None is unclassified. A
    token is classified only by a mask, a designator right after a classified token, the notice's own stated content
    (anaphora, with a determiner or a period noun in the phrase), a lead modifier right before a notice or permission
    noun, a role the connective admits, or - not as the head - a modifier role (modifiers); a temporal modifier is
    resolved by _classify_operand (a place part only when it heads OF and a place). The head is the last content token
    that is not a designator: English compounds are head-final ('AIRPORT CURFEW' is a curfew)."""
    admits = _OBJECT_ADMITS[kind]
    nouns = [role for role in admits if role in _OBJECT_ROLES]
    content = [word for _, _, word in np if _CONTENT.search(word) and not _OBJECT_FUNCTION.fullmatch(word)]
    anaphoric = "anaphora" in admits and (determined or any(_OBJECT_ANAPHORA_PERIOD.fullmatch(word) for word in content))
    out: list[list[Any]] = []
    previous: str | None = None
    noun: str | None = None
    modifiers_only = True  # every content token so far classified: a mask here stands in the object position
    for position, (low, high, word) in enumerate(np):
        if not _CONTENT.search(word) or _OBJECT_FUNCTION.fullmatch(word):
            out.append([low, high, word, "function"])
            continue
        follow = next((later for _, _, later in np[position + 1:]
                       if _CONTENT.search(later) and not _OBJECT_FUNCTION.fullmatch(later)), None)
        cls: str | None
        if "#" in word:
            cls = "mask" if ctx is None or _mask_classifies(ctx, low, high, modifiers_only and ctx["first"]) else None
        elif previous is not None and _designator(word, low, high, temporal, noun):
            cls = "designator"
        elif anaphoric and _OBJECT_ANAPHORA.fullmatch(word):
            cls = "anaphora"  # 'DURING THIS PERIOD', 'DRG THE CLOSURE', 'DRG EXER PERIOD'
        elif _OBJECT_MODIFIER.fullmatch(word):
            lead = (_OBJECT_LEAD.fullmatch(word) and follow is not None and _OBJECT_LEAD_HEADS.fullmatch(follow)
                    and _roles_of(follow, nouns))
            cls = "lead" if lead else "modifier?"  # 'AT SHORT NOTICE'; else resolved by the complement
        else:
            roles = _roles_of(word, nouns)
            if not roles and "place" in nouns and _named_place(places, word, low, high, temporal):
                roles = ["place"]  # a place the briefing itself names (QA520 gazetteer): 'AT VELANA INTL', 'AT LRBS'
            modifiers = _roles_of(word, _OBJECT_MODIFIERS[kind]) if not roles else []
            cls = ("role:" + roles[0]) if roles else ("modifier:" + modifiers[0]) if modifiers else None
            if cls is None and _compound_classified(kind, word, low, high, temporal, noun if previous is not None else None,
                                                    places):
                cls = "compound"
            if (cls is None and _OBJECT_DEGREE.fullmatch(word) and follow is not None and _OBJECT_DIRECTION.fullmatch(follow)
                    and "place" in _roles_of(follow, nouns)):
                cls = "degree"  # the degree of a place direction: 'A POINT IMMEDIATELY SOUTH OF TWY D2'

        out.append([low, high, word, cls])
        previous, noun = cls, word
        modifiers_only = modifiers_only and cls is not None
    items = [item for item in out if item[3] != "function"]
    head = next((item for item in reversed(items) if item[3] != "designator"), None)
    if head is not None and head[3] is not None and head[3].startswith("modifier:"):
        head[3] = None  # a modifier never classifies a head: 'AFTER ACFT' is no place
    designated = head is not None and (head[3] == "mask" or (head is not items[-1] and head[3] is not None))
    for item in items:
        if item[3] is not None and item[3].startswith("modifier:") and not designated:
            item[3] = None  # a modifier needs a designated head: 'ACFT STAND 517L', never 'ACFT AIRPORT'
    return out


def _designated_at(content: list[list[Any]], at: int, role: str, text: str, step: int) -> bool:
    """Whether content[at] is a designated ``role`` word (temporalObject.boundPart), read from the side ``step`` points
    away from: a mask whose text opens with a word of the role ('RWY 01R'), or a word of the role and its designator -
    after it ('APCH END RWY 25L': step 1) or before it ('RWY 01R END' as two words: step -1)."""
    if not 0 <= at < len(content):
        return False
    item = content[at]
    if item[3] == "mask":
        return bool(_roles_of(text[item[0]:item[1]].split(" ")[0], [role]))
    pair = (at, at + 1) if step > 0 else (at - 1, at)
    if not (0 <= pair[0] and pair[1] < len(content)):
        return False
    noun, designator = content[pair[0]], content[pair[1]]
    return noun[3] == f"role:{role}" and designator[3] == "designator"


def _classify_operand(entry: dict[str, Any], temporal: list[tuple[int, int]], ctx: dict[str, Any]) -> None:
    """Classify the operand of a 'phrase' or 'postpositive' entry (QA520 I7): every content token of every conjunct
    and complement. A temporal modifier is a place part only as the head of OF and a place ('FM BEGINNING OF RWY 19R'),
    else temporal - or, a word of a boundPart role, bound to a designated place right after or before it ('AT RWY 01R
    END'); designators of a designated conjunct ('TWY A AND B'); codes only in a structure of codes or in
    codeAlone form."""
    kind = entry["kind"]
    admits = _OBJECT_ADMITS[kind]
    classified: list[list[list[Any]]] = []
    for number, conjunct in enumerate(entry["conjuncts"]):
        tokens = _classify_np(kind, conjunct["words"], entry["determined"] if number == 0 else False, temporal,
                              {**ctx, "first": number == 0 and ctx["adjacent"]} if ctx is not None else None,
                              ctx.get("places") if ctx is not None else None)
        content = [item for item in tokens if item[3] != "function"]
        before = [item for item in classified[-1] if item[3] != "function"] if classified else []
        if (content and before and all(item[3] is not None for item in before)
                and all(_designator(item[2], item[0], item[1], temporal) for item in content)):
            for item in content:
                item[3] = "designator"  # 'TWY A AND B': B designates the noun of the conjunct before it
        complement = _classify_np(kind, conjunct["complement"], conjunct["complementDetermined"], temporal,
                                  {**ctx, "first": False} if ctx is not None else None,
                                  ctx.get("places") if ctx is not None else None)
        head = next((item for item in reversed(content) if item[3] != "designator"), None)
        if head is not None and head[3] == "modifier?":
            following = [item for item in complement if item[3] != "function"]
            noun = next((item for item in reversed(following) if item[3] != "designator"), None)
            if noun is not None and noun[3] in ("role:place", "mask") and all(
                    item[3] is not None and not item[3].endswith("?") for item in following):
                head[3] = "placePart"  # the place's part: 'FM BEGINNING OF RWY 19R', 'AT THE END OF TWY B'
        if ctx is not None and not any(item[3] != "function" for item in complement):
            for at, item in enumerate(content):
                if item[3] != "modifier?":
                    continue
                roles = _roles_of(item[2], [role for role in _OBJECT_BOUND_PART if role in admits])
                if any(_designated_at(content, at - 1, role, ctx["text"], -1) or _designated_at(content, at + 1, role, ctx["text"], 1)
                       for role in roles):
                    item[3] = "boundPart"  # the place's part: 'AT RWY 01R END', 'BTN APCH END RWY 25L AND TWY B'
        for item in tokens + complement:
            if item[3] == "modifier?":
                item[3] = None  # 'AFTER LAST FLIGHT', 'UNTIL COMPLETION OF WORKS', 'AFTER RWY END'
        classified.append(tokens + complement)
    if "code" in admits:
        singles = [[item for item in tokens if item[3] != "function"] for tokens in classified]
        singles = [content[0] for content in singles if len(content) == 1]
        shaped = [item for item in singles if item[3] == "mask" or (item[3] is None and _is_code(item[2]))]
        named = [item for item in shaped if item[3] is None]
        if named and len(shaped) >= 2:
            for item in named:
                item[3] = "code"  # a structure of codes: 'BTN ONATI AND POTAS', 'FM RKJY AND RKPS'
        for tokens in classified:
            for item in tokens:
                if item[3] is None and _OBJECT_CODE_ALONE.fullmatch(item[2]):
                    item[3] = "code"  # a route segment, an ILS identifier, a web address
    entry["tokens"] = [item for tokens in classified for item in tokens if item[3] != "function"]


def _head_view(entry: dict[str, Any], text: str) -> None:
    """I7 across pre-modifiers: every word or mask of the operand's first noun phrase that holds no digit and stands after
    classified words (place or other role words, designators, masks) is read again right after the connective, the
    words before it left out but the sentence's left context kept, masked and searched for temporal content by the same
    rules ('EXC RWY 08R SUN REFLECTIONS' as 'EXC SUN REFLECTIONS', 'DURING AIRPORT ACTIVATION' as 'DURING ACTIVATION',
    'ONLY AIRPORT DAY MARKED' as 'ONLY DAY MARKED'); temporal content or a digit left unaccounted there is that token's,
    and it is unclassified - a pre-modifier never hides it. (A numeric token is governed in its object position by
    _mask_classifies; a designation noun before it is its own.)"""
    if not entry["conjuncts"]:
        return
    words = entry["conjuncts"][0]["words"]
    classes = {item[0]: item for item in entry["tokens"]}
    left = text[:entry["connective"][1]]  # the sentence's own left context, the pre-modifiers left out
    seen = False
    for position, (low, high, _word) in enumerate(words):
        item = classes.get(low)
        if item is None:
            continue  # a function word
        if seen and item[3] != "designator" and not re.search(r"[0-9]", text[low:high]):
            probe = left + " " + text[low:words[-1][1]]
            shift = len(left) + 1 - low
            masked = _mask_benign(probe)
            found = (_temporal_tokens(masked) + _residue_spans(masked)
                     + [match.span() for match in _RESIDUE_WORDS.finditer(masked)])
            if any(start < high + shift and low + shift < end for start, end in found):
                item[3] = None
                entry["hidden"].append([low, high])
        if item[3] is None and entry["restricted"]:
            return  # unclassified already: the operand is temporal content
        seen = True


def _sentence_ledger(masked: str, text: str, start: int, end: int, temporal: list[tuple[int, int]],
                     statements: list[tuple[int, int]], heads: set[int], ends: set[int], offset: int,
                     restricted: bool, places: frozenset[str] | None = None,
                     inline: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
    """The obligations of one sentence: every connective of temporalObject.connectives (and TO/UNTIL/TIL/TILL closing
    a FROM/FM range, in the range's role) with its operand read - and, in a sentence that holds a restriction
    (``restricted``), classified."""
    words = _object_words(masked, start, end)
    labels = {match.start() for match in _OBJECT_LABEL_AT.finditer(text) if start <= match.start() < end} | ends
    entries: list[dict[str, Any]] = []
    by_word: dict[int, int] = {}
    ranges: set[int] = set()
    range_at: int | None = None
    range_entry: int | None = None
    # the range ends first, so a connective right before one chains to it
    for index, (_, _, word, _) in enumerate(words):
        if range_at is not None and index - range_at <= _OBJECT_RANGE_WITHIN and _OBJECT_RANGE_END.fullmatch(word):
            ranges.add(index)
        if _OBJECT_RANGE_AFTER.fullmatch(word):
            range_at = index
    range_at = None
    for index, (low, high, word, _closed) in enumerate(words):
        closes = None
        if index in ranges:
            kind: str | None = "spatial"
            closes = range_entry
        else:
            kind = _connective_class(word)
        if _OBJECT_RANGE_AFTER.fullmatch(word):
            range_at, range_entry = index, None
        if kind is None:
            continue
        entry: dict[str, Any] = {"index": offset + len(entries), "connective": [low, high], "word": word, "kind": kind,
                                 "operand": None, "reading": "direct", "reason": None, "determined": False,
                                 "conjuncts": [], "cut": False, "tokens": [], "unclassified": [], "chain": None,
                                 "rangeOf": None, "restricted": restricted, "skipped": [], "hidden": [],
                                 "status": None, "_ranges": ranges}
        _read_operand(entry, words, index, masked, labels, heads, statements, text, inline)
        if closes is not None:
            entry["rangeOf"] = offset + closes
        if _OBJECT_RANGE_AFTER.fullmatch(word):
            range_entry = len(entries)
        by_word[index] = len(entries)
        entries.append(entry)
    for entry in entries:
        if entry["operand"] == "chain":
            entry["chain"] = offset + by_word[entry.pop("chainAt")]
        if entry["operand"] in ("phrase", "postpositive"):
            before = text[:entry["connective"][1]]
            ctx = {"text": text, "governing": bool(_GOVERNING_CONNECTIVE.search(before)),
                   "period": bool(_PERIOD_CONNECTIVE.search(before)),
                   # QA514's object: right after the connective, at most an article between
                   "adjacent": all(word in ("THE", "A", "AN") for word in entry["skipped"]), "places": places}
            _classify_operand(entry, temporal, ctx)
            _head_view(entry, text)
    for entry in entries:
        # the two single-code ends of a FROM range make both a place ('FROM PUT UNTIL BBS')
        if entry["rangeOf"] is not None:
            first = entries[entry["rangeOf"] - offset]
            ends = [item["tokens"] for item in (first, entry)]
            if all(len(tokens) == 1 for tokens in ends):
                pair = [tokens[0] for tokens in ends]
                if all(item[3] in (None, "mask", "code") and (item[3] == "mask" or _is_code(item[2])) for item in pair) \
                        and any(item[3] != "mask" for item in pair) and "code" in _OBJECT_ADMITS["spatial"]:
                    for item in pair:
                        if item[3] is None:
                            item[3] = "code"
    for entry in entries:
        del entry["_ranges"]
        entry["conjuncts"] = [{"words": [list(item) for item in conjunct["words"]],
                               "complement": [list(item) for item in conjunct["complement"]]}
                              for conjunct in entry["conjuncts"]]
        if entry["operand"] in ("phrase", "postpositive") and not restricted:
            # a connective that qualifies no restriction needs its operand, not its operand's classification - but a
            # mask the governance refuses, or a token read again as temporal (_head_view), is temporal content there,
            # and an operand that holds temporal content is accounted for whole: every unclassified token of it
            # ('DURING THE LOCAL PRECEDING HOURS 24 HR' - LOCAL and PRECEDING lie in no statement)
            temporal_held = any(item[3] is None and ("#" in item[2] or [item[0], item[1]] in entry["hidden"])
                                for item in entry["tokens"])
            entry["unclassified"] = ([[item[0], item[1]] for item in entry["tokens"] if item[3] is None]
                                     if temporal_held else [])
            entry["status"] = "pending" if entry["unclassified"] else "free"
            if not entry["tokens"]:
                entry["status"], entry["reason"] = "undischarged", "empty"  # 'AFTER THE, ...': no operand
            if entry["cut"]:
                entry["status"], entry["reason"] = "undischarged", "cutOff"
        elif entry["operand"] in ("phrase", "postpositive"):
            entry["unclassified"] = [[item[0], item[1]] for item in entry["tokens"] if item[3] is None]
            entry["status"] = "classified" if not entry["unclassified"] else "pending"
            if not entry["tokens"]:
                entry["status"], entry["reason"] = "undischarged", "empty"  # 'UNTIL THE.': no content, no operand
            if entry["cut"]:
                entry["status"], entry["reason"] = "undischarged", "cutOff"
        elif entry["operand"] == "openEnd":
            entry["status"] = "classified" if restricted else "free"
        elif entry["operand"] == "missing":
            entry["status"] = "undischarged"
    return entries


def _connective_ledger(masked: str, text: str, temporal: list[tuple[int, int]], statements: list[tuple[int, int]],
                       heads: set[int], ends: set[int], places: frozenset[str] | None = None,
                       inline: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
    """QA520 I8: one obligation per temporal connective of every sentence (sentences found on ``text``, the unmasked
    syntactic text of which ``masked`` is the masked copy, character for character; a mask may paint over a sentence's
    period: '4.'). In a sentence that holds a restriction the operand must be accounted for or classified; in any other
    the connective qualifies no restriction, but it must still have its operand - a connective cut from its operand by a
    boundary ('DURING. CURFEW, RWY 08R/26L CLSD.') may qualify the restriction across it. Statuses 'pending' and chains
    are settled by _discharge."""
    ledger: list[dict[str, Any]] = []
    start = 0
    for boundary in [*_OBJECT_SENTENCE.finditer(text), None]:
        end = boundary.start() if boundary else len(masked)
        restricted = bool(_OBJECT_RESTRICTION.search(masked[start:end]))
        ledger.extend(_sentence_ledger(masked, text, start, end, temporal, statements, heads, ends, len(ledger), restricted,
                                       places, inline))
        start = boundary.end() if boundary else len(masked)
    return ledger


def _discharge(ledger: list[dict[str, Any]], accounted: Any) -> None:
    """Settle every obligation: a read operand whose unclassified tokens all lie in accounted statements is accounted
    for; a chain takes the status of the connective whose operand it shares (chains point forward)."""
    for entry in ledger:
        if entry["status"] == "pending":
            if all(accounted(span) for span in entry["unclassified"]):
                entry["status"] = "accounted"
            else:
                entry["status"], entry["reason"] = "undischarged", "unaccounted"
    for entry in reversed(ledger):
        if entry["operand"] == "chain":
            target = ledger[entry["chain"]]
            if target["status"] in LEDGER_DISCHARGED:
                entry["status"] = "chained"
            else:
                entry["status"], entry["reason"] = "undischarged", "chainUndischarged"


def _free_text_accounting(text: str, field: str | None, entries: list[dict[str, Any]] | None,
                          validity: Mapping[str, Any] | None, line_starts: Iterable[int] = (0,),
                          places: frozenset[str] | None = None) -> tuple[str | None, list[dict[str, Any]], str]:
    """The review the free text after the field calls for, or None, with the connective ledger and the masked text
    (QA506: fail closed; QA510: temporal content is found by SHAPE; QA514: every digit accounted for; QA520 I8: every
    connective's operand accounted for). Benign spans are masked; every temporal token left - every clock-like shape
    whatever its values - and EVERY digit left (accountedResidue) must sit in a statement the grammar reads whole and
    that is accounted for; every obligation of the ledger must be discharged. Both are checked once, at the end, so no
    path reaches None while a token is unaccounted or an obligation undischarged."""
    reason = TIMING_REVIEW_REASONS["freeTextConflict"] if field else TIMING_REVIEW_REASONS["freeText"]
    kept = _benign_spans(text or "", line_starts)
    masked = _paint(text or "", [(start, end) for start, end, _ in kept])
    heads = {start for start, _end, name in kept if name in _OBJECT_HEAD_ONLY_MASKS}
    ends = {start for start, _end, name in kept if name in _OBJECT_END_MASKS}
    # a numeric list label that opens no body line (QA520): after AND/OR it is a conjunct's number ('BTN SSYEF AND 2.2
    # TO SSYEM' - a DME distance), never a new item cutting the operand off
    opens = set(line_starts)
    inline = frozenset(start for start in ends if start not in opens)
    temporal = _temporal_tokens(masked)
    tokens = temporal + _residue_spans(masked) + [match.span() for match in _RESIDUE_WORDS.finditer(masked)]
    statements = [(match.start(), match.end(), match.group(0)) for match in _STATEMENT.finditer(masked)]
    ledger = _connective_ledger(masked, text or "", temporal, [(low, high) for low, high, _ in statements], heads, ends,
                                places, inline)
    verdicts: dict[int, bool] = {}

    def accounted(span: Iterable[int]) -> bool:
        start, end = span
        for number, (low, high, statement) in enumerate(statements):
            if low <= start and end <= high:
                if number not in verdicts:
                    parsed = _parse_statement(statement, validity) if (validity or {}).get("startsAt") else None
                    verdicts[number] = parsed is not None and _statement_accounted(
                        parsed[0], parsed[1], entries if field else None, validity)
                return verdicts[number]
        return False

    _discharge(ledger, accounted)
    unaccounted = [span for span in tokens if not accounted(span)]
    undischarged = [entry for entry in ledger if entry["status"] not in LEDGER_DISCHARGED]
    return (reason if unaccounted or undischarged else None), ledger, masked


def _free_text_review(text: str, field: str | None, entries: list[dict[str, Any]] | None,
                      validity: Mapping[str, Any] | None, line_starts: Iterable[int] = (0,)) -> str | None:
    """The review the free text after the field calls for, or None (see _free_text_accounting)."""
    return _free_text_accounting(text, field, entries, validity, line_starts)[0]


def _read_schedule_field(body_lines: Iterable[Any], validity: Mapping[str, Any] | None, explain: bool,
                         gazetteer: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """read_lido_schedule_field, and with ``explain`` the free text's accounting: its syntactic text, masked text and
    connective ledger (QA520 I8), computed on the same path."""
    lines = [text for text in (_field_text(line) for line in body_lines or []) if text]
    line_count = 0
    while line_count < len(lines) and _FIELD_LINE.search(re.sub(r"\.$", "", lines[line_count])):
        line_count += 1
    # QA518 I5: the field and the free text are each one token stream - their lines joined, then read as syntactic text
    # again, so punctuation that wraps or joins across a line break is read as it is within a line
    field = _syntax_text(" ".join(lines[:line_count]))[0] if line_count else None
    free_text, origin = _syntax_text(" ".join(lines[line_count:]))
    # Where each free-text body line opens in the joined text (QA514 G3: a list label opening a line is structure).
    line_starts, offset = [], 0
    for line in lines[line_count:]:
        line_starts.append(bisect.bisect_left(origin, offset))
        offset += len(line) + 1
    explained: dict[str, Any] | None = None
    places = _gazetteer_lookup(gazetteer)

    def account(field_text: str | None, entries: list[dict[str, Any]] | None,
                held: Mapping[str, Any] | None) -> str | None:
        nonlocal explained
        review, ledger, masked = _free_text_accounting(free_text, field_text, entries, held, line_starts, places)
        if explain:
            explained = {"text": free_text, "masked": masked, "ledger": ledger, "freeTextReview": review}
        return review

    def read(review: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        return {"field": field, "lineCount": line_count, "review": review}, explained

    if not field:
        return read(account(None, None, validity))
    if _REVIEW_LANGUAGE.search(field):
        if explain:
            account(field, None, None)
        return read(TIMING_REVIEW_REASONS["reviewLanguage"])
    if not (validity or {}).get("startsAt"):
        return read(account(field, None, None))
    entries, error = parse_schedule_field(field, validity)
    if error:
        if explain:
            account(field, None, None)
        return read(error)
    return read(account(field, entries, validity))


def read_lido_schedule_field(body_lines: Iterable[Any], validity: Mapping[str, Any] | None = None,
                             gazetteer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Item D of a LIDO record: the leading body lines made only of schedule tokens, joined with one space, across
    line wraps. ``review`` is why the record's timing cannot be read: schedule language this spec does not evaluate, a
    leading field the grammar cannot read in full, or schedule-bearing language in the free text that is not accounted
    for (QA506: every temporal token left once the stated benign classes are masked must sit in a statement the grammar
    reads whole and that is proven equal, on its own, to Item D or to the whole validity; QA520 I8: every temporal
    connective of a restriction sentence must have its operand accounted for or positively classified). ``validity`` is
    the record's read_lido_validity() result; without one the record is a validity review. ``gazetteer`` is the
    analysis's build_timing_gazetteer() result: the places the briefing itself names (QA520)."""
    return _read_schedule_field(body_lines, validity, False, gazetteer)[0]


def explain_timing_ledger(body_lines: Iterable[Any], validity: Mapping[str, Any] | None = None,
                          gazetteer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """QA520 I8: the free text's connective ledger as read_lido_schedule_field computes it - every temporal connective
    of every restriction sentence with its operand (reading, conjuncts, classified tokens), its status (classified,
    accounted, chained, undischarged) and why - plus the read itself, the syntactic and masked free text. A read with
    no review has every obligation discharged (the ledger balances)."""
    read, explained = _read_schedule_field(body_lines, validity, True, gazetteer)
    return {**(explained or {"text": "", "masked": "", "ledger": [], "freeTextReview": None}), "read": read}


_TOKEN = re.compile(_ascii_digits("|".join([
    rf"(?P<cross>({_MONTH_SOURCE}) (\d{{1,2}})-({_MONTH_SOURCE}) (\d{{1,2}}))(?!\d)",
    r"(?P<time>(\d{4})-(\d{4}))(?!\d)",
    r"(?P<h24>H24)\b",
    rf"(?P<wdrange>({_WEEKDAY_SOURCE})-({_WEEKDAY_SOURCE}))\b",
    rf"(?P<weekday>{_WEEKDAY_SOURCE})\b",
    rf"(?P<month>{_MONTH_SOURCE})\b",
    r"(?P<dayrange>(\d{1,2})-(\d{1,2}))(?!\d)",
    r"(?P<day>\d{1,2})(?!\d)",
    r"(?P<daily>DLY)\b",
    r"(?P<sep>[\s,;:]+)",
])))


_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def _validity_years(validity: Mapping[str, Any] | None) -> tuple[int, int | None] | None:
    """The validity's calendar years (from, to; to None for an open end), or None when the validity is not held."""
    start_ms = parse_ms((validity or {}).get("startsAt"))
    if math.isnan(start_ms):
        return None
    end_ms = parse_ms((validity or {}).get("endsAt"))
    start_year = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).year
    return start_year, None if math.isnan(end_ms) else datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).year


def _month_length(month: int, years: tuple[int, int | None] | None) -> int:
    """The longest the month can be within the validity: 29 FEB only when a leap year falls within it."""
    if month != 1:
        return _MONTH_DAYS[month]
    if years is None or years[1] is None:
        return 29
    return 29 if any(_is_leap(year) for year in range(years[0], years[1] + 1)) else 28


def _minutes_of(hhmm: str) -> int | None:
    h, m = int(hhmm[:2]), int(hhmm[2:])
    return None if h > 23 or m > 59 else h * 60 + m


def _tokenize(text: str) -> tuple[list[dict[str, Any]], str | None]:
    tokens: list[dict[str, Any]] = []
    at = 0
    while at < len(text):
        match = _TOKEN.match(text, at)
        if not match:
            return [], f"Unsupported Item D text: {text[at:at + 24]}"
        at = match.end()
        kind = match.lastgroup
        groups = match.groups()
        if kind == "sep":
            continue
        if kind == "cross":
            tokens.append({"kind": "cross", "from": (_MONTHS.index(groups[1]), int(groups[2])),
                           "to": (_MONTHS.index(groups[3]), int(groups[4]))})
        elif kind == "time":
            start, end = _minutes_of(groups[6]), _minutes_of(groups[7])
            if start is None or end is None:
                return [], f"Invalid UTC time in Item D: {match.group('time')}"
            # A zero-length range (1800-1800) states no period this spec can read: a review, never 24 hours.
            if start == end:
                return [], f"Zero-length time range in Item D: {match.group('time')}"
            tokens.append({"kind": "time", "start": start, "end": end + 1440 if end < start else end})
        elif kind == "h24":
            tokens.append({"kind": "time", "start": 0, "end": 1440})
        elif kind == "wdrange":
            first, last = _WEEKDAYS.index(groups[10]), _WEEKDAYS.index(groups[11])
            days = [first]
            cursor = first
            while cursor != last:
                cursor = (cursor + 1) % 7
                days.append(cursor)
            tokens.append({"kind": "weekdays", "days": days})
        elif kind == "weekday":
            tokens.append({"kind": "weekdays", "days": [_WEEKDAYS.index(match.group("weekday"))]})
        elif kind == "month":
            tokens.append({"kind": "month", "month": _MONTHS.index(match.group("month"))})
        elif kind == "dayrange":
            tokens.append({"kind": "days", "from": int(groups[15]), "to": int(groups[16])})
        elif kind == "day":
            value = int(match.group("day"))
            tokens.append({"kind": "days", "from": value, "to": value})
        elif kind == "daily":
            tokens.append({"kind": "daily"})
    return tokens, None


def parse_schedule_field(field: Any, validity: Mapping[str, Any] | None = None, *,
                         allow_date_only: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    """Item D read into entries; the error is a timing review. Month-less day numbers take
    the latest month named earlier in the field, else the validity month when B and C
    share one month. Every day must exist within the validity's years (FEB 30 never,
    FEB 29 only in a leap year); an HH:MM clock is not read."""
    text = str(field or "").upper()
    text = _DASHES.sub("-", text)
    text = re.sub(r"\bDAILY\b", "DLY", text)
    text = re.sub(r"([0-9]{4})(?:UTC|Z)\b", r"\1", text)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\b(?:EVERY|EV|AND)\b", " ", text)
    text = re.sub(r"\.\s*$", "", text)
    text = " ".join(text.split())
    if not text:
        return [], "Item D is empty."
    if _REVIEW_LANGUAGE.search(text):
        return [], TIMING_REVIEW_REASONS["reviewLanguage"]
    if _COLON_CLOCK.search(text):
        return [], f"Item D clock written HH:MM: {text}"
    tokens, error = _tokenize(text)
    if error:
        return [], error

    raw: list[dict[str, list[dict[str, Any]]]] = []
    current: dict[str, list[dict[str, Any]]] = {"dates": [], "times": []}
    for token in tokens:
        if token["kind"] == "time":
            current["times"].append(token)
            continue
        if current["times"]:
            raw.append(current)
            current = {"dates": [], "times": []}
        current["dates"].append(token)
    # A body run may restate days without hours ("ACT MON-FRI"); Item D itself may not end on a date.
    if current["dates"] and not current["times"] and not allow_date_only:
        return [], f"Item D date without a time: {text}"
    if current["times"] or current["dates"]:
        raw.append(current)
    if not raw:
        return [], "Item D holds no time."

    start_ms = parse_ms((validity or {}).get("startsAt"))
    end_ms = parse_ms((validity or {}).get("endsAt"))
    validity_month = None
    if not math.isnan(start_ms) and not math.isnan(end_ms):
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
        if (start_dt.year, start_dt.month) == (end_dt.year, end_dt.month):
            validity_month = start_dt.month - 1

    years = _validity_years(validity)
    named_month: int | None = None
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        kinds = {token["kind"] for token in entry["dates"]}
        if not entry["dates"]:
            if index != 0:
                return [], f"Item D times without a date: {text}"
            entries.append({"kind": "daily", "times": entry["times"], "undated": True})
            continue
        if "daily" in kinds:
            if len(entry["dates"]) != 1:
                return [], f"Unsupported Item D date part: {text}"
            entries.append({"kind": "daily", "times": entry["times"]})
            continue
        if kinds == {"weekdays"}:
            entries.append({"kind": "weekdays", "days": {day for token in entry["dates"] for day in token["days"]},
                            "times": entry["times"]})
            continue
        if "weekdays" in kinds:
            return [], f"Item D mixes weekdays and dates: {text}"
        month_days: set[int] = set()
        ranges: list[tuple[int, int]] = []
        for token in entry["dates"]:
            if token["kind"] == "month":
                named_month = token["month"]
            elif token["kind"] == "cross":
                (from_month, from_day), (to_month, to_day) = token["from"], token["to"]
                if not (1 <= from_day <= _month_length(from_month, years) and 1 <= to_day <= _month_length(to_month, years)):
                    return [], f"Invalid date in Item D: {text}"
                ranges.append((from_month * 100 + from_day, to_month * 100 + to_day))
                named_month = to_month
            else:
                month = named_month if named_month is not None else validity_month
                if month is None:
                    return [], f"Item D day numbers name no month: {text}"
                if token["from"] < 1 or token["to"] > _month_length(month, years) or token["from"] > token["to"]:
                    return [], f"Invalid date in Item D: {text}"
                month_days.update(month * 100 + day for day in range(token["from"], token["to"] + 1))
        if not month_days and not ranges:
            return [], f"Item D month without days: {text}"
        entries.append({"kind": "dates", "monthDays": month_days, "ranges": ranges, "times": entry["times"]})
    return entries, None


def _entry_matches(entry: Mapping[str, Any], day_ms: int) -> bool:
    date = datetime.fromtimestamp(day_ms / 1000, tz=timezone.utc)
    if entry["kind"] == "daily":
        return True
    if entry["kind"] == "weekdays":
        return date.weekday() in entry["days"]
    key = (date.month - 1) * 100 + date.day
    if key in entry["monthDays"]:
        return True
    return any((low <= key <= high) if low <= high else (key >= low or key <= high) for low, high in entry["ranges"])


def schedule_occurrences(entries: list[dict[str, Any]], validity_start_ms: float, validity_end_ms: float,
                         from_ms: float, to_ms: float) -> list[tuple[float, float]]:
    """Occurrences whose start day lies in [from - 1 day, to], clipped to the validity."""
    occurrences: list[tuple[float, float]] = []
    day = int(from_ms // _DAY_MS) * _DAY_MS - _DAY_MS
    while day <= to_ms:
        for entry in entries:
            if not _entry_matches(entry, day):
                continue
            for time in entry["times"]:
                start = max(day + time["start"] * _MINUTE_MS, validity_start_ms)
                end = min(day + time["end"] * _MINUTE_MS, validity_end_ms)
                if start < end:
                    occurrences.append((start, end))
        day += _DAY_MS
    return sorted(occurrences)


def _state_from(intervals: list[tuple[float, float]], reference_ms: float) -> tuple[str, int | None, tuple[float, float] | None]:
    if math.isnan(reference_ms):
        return "unknown_at_reference", None, None
    ordered = sorted(intervals)
    active = next((item for item in ordered if item[0] <= reference_ms < item[1]), None)
    if active:
        return "active_at_reference", 0, active
    upcoming = next((item for item in ordered if item[0] > reference_ms), None)
    if upcoming:
        return "begins_after_reference", _round_half_up((upcoming[0] - reference_ms) / _MINUTE_MS), upcoming
    previous = [item for item in ordered if item[1] <= reference_ms]
    if previous:
        return "ended_before_reference", _round_half_up((reference_ms - previous[-1][1]) / _MINUTE_MS), previous[-1]
    return "unknown_at_reference", None, None


def _round_half_up(value: float) -> int:
    """JavaScript Math.round, so both runtimes print the same minutes."""
    return int(math.floor(value + 0.5))


def _interval_out(item: tuple[float, float] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"startsAt": iso_ms(item[0]), "endsAt": iso_ms(item[1]) if math.isfinite(item[1]) else None}


def decide_notice_timing(notice: Mapping[str, Any], window: Mapping[str, Any]) -> dict[str, Any]:
    """The decision. ``notice``: {validity: read_lido_validity() result or None, schedule:
    Item D text or None, review: a source review reason or None}. ``window``: {startsAt,
    endsAt, referenceAt (None when the station holds no reference instant)}. Returns
    status affecting | outside_window | review, ``outsideBy`` (validity | schedule) and
    the state at the reference."""
    window_start, window_end = parse_ms(window.get("startsAt")), parse_ms(window.get("endsAt"))
    if math.isnan(window_start) or math.isnan(window_end) or window_start >= window_end:
        raise ValueError("A timing decision needs a valid window.")
    reference_ms = parse_ms(window.get("referenceAt"))
    validity = notice.get("validity") or None
    is_open = bool(validity) and validity.get("endKind") in set(_OPEN_ENDS.values())
    start_ms = parse_ms((validity or {}).get("startsAt"))
    end_ms = math.inf if is_open else parse_ms((validity or {}).get("endsAt"))
    base: dict[str, Any] = {
        "referenceAt": None if math.isnan(reference_ms) else iso_ms(reference_ms),
        "stateAtReference": "unknown_at_reference",
        "minutesDelta": None,
        "referenceInterval": None,
        "validityInterval": None if math.isnan(start_ms) else {
            "startsAt": iso_ms(start_ms), "endsAt": iso_ms(end_ms) if math.isfinite(end_ms) else None},
        "schedule": notice.get("schedule") or None,
        "occurrences": [],
        "outsideBy": None,
    }

    def review(reason: str) -> dict[str, Any]:
        return {**base, "status": "review", "reason": reason}

    readable_validity = not (math.isnan(start_ms) or math.isnan(end_ms) or start_ms >= end_ms)

    def decided(status: str, intervals: list[tuple[float, float]], **extra: Any) -> dict[str, Any]:
        state, delta, interval = _state_from(intervals, reference_ms)
        return {**base, **extra, "status": status, "stateAtReference": state, "minutesDelta": delta,
                "referenceInterval": _interval_out(interval)}

    validity_interval = [(start_ms, end_ms)]
    # QA500 refinement (15 Oct 2026): a readable validity wholly outside the window excludes the notice before any
    # source or schedule review - text that cannot be read cannot put a notice in force outside its own validity.
    if readable_validity and not (start_ms < window_end and window_start < end_ms):
        return decided("outside_window", validity_interval, outsideBy="validity")
    if notice.get("review"):
        return review(str(notice["review"]))
    if not readable_validity:
        return review(TIMING_REVIEW_REASONS["validity"])
    if not notice.get("schedule"):
        return decided("affecting", validity_interval)
    entries, error = parse_schedule_field(notice["schedule"], validity)
    if error:
        return review(error)
    in_window = [item for item in schedule_occurrences(entries, start_ms, end_ms, window_start, window_end)
                 if item[0] < window_end and window_start < item[1]]
    if in_window:
        return decided("affecting", in_window, occurrences=[_interval_out(item) for item in in_window])
    search_from = max(start_ms, window_start - _LOOKBACK_DAYS * _DAY_MS)
    search_to = end_ms if math.isfinite(end_ms) else window_end + _OPEN_END_SEARCH_DAYS * _DAY_MS
    return decided("outside_window", schedule_occurrences(entries, start_ms, end_ms, search_from, search_to),
                   outsideBy="schedule")


def decide_lido_record(validity_text: Any, lines: Iterable[Any], window: Mapping[str, Any],
                       gazetteer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read a LIDO record (validity text + body lines) and decide it: the whole shared path (``gazetteer``: the places
    the analysis's briefing names, build_timing_gazetteer)."""
    validity = read_lido_validity(validity_text)
    field = read_lido_schedule_field(lines, validity, gazetteer)
    return decide_notice_timing({"validity": validity, "schedule": field["field"], "review": field["review"]}, window)


def notice_timing_input(record: Mapping[str, Any]) -> dict[str, Any]:
    """The shared decision's input from a parsed LIDO station record (enrichment._parse_airport_notams).

    The record holds what the shared readers read: no valid_to only for an open end (UFN, PERM) - an absent or
    unreadable end is validity_review - and Item D in ``schedule``; schedule language with no Item D is
    schedule_review. An Item D the grammar cannot read is re-read here and decided as a review with its reason; an
    Item D it reads on a record still held for review is one whose free text states other hours (QA500).
    """
    if record.get("validity_review"):
        validity = None
    else:
        start = parse_ms(record.get("valid_from_utc"))
        end = parse_ms(record.get("valid_to_utc"))
        validity = None if math.isnan(start) else {
            "startsAt": iso_ms(start),
            "endsAt": None if math.isnan(end) else iso_ms(end),
            "endKind": "until_further_notice" if math.isnan(end) else "explicit",
        }
    schedule = record.get("schedule") or None
    review = None
    if record.get("schedule_review") and not schedule:
        review = TIMING_REVIEW_REASONS["freeText"]
    elif record.get("schedule_review") and validity is not None:
        # QA500 (15 Oct 2026): a held Item D the grammar reads, on a record the reader still held for review, is a
        # field whose free text states other hours (read_lido_schedule_field); it is never decided on the field alone.
        review = parse_schedule_field(schedule, validity)[1] or TIMING_REVIEW_REASONS["freeTextConflict"]
    return {"validity": validity, "schedule": schedule, "review": review}


def shared_station_window(role: str, reference: datetime) -> tuple[datetime, datetime] | None:
    """The shared departure/destination window around ``reference``; None for every other role."""
    policy = NOTAM_TIMING_RULES["stationWindows"].get(role)
    if not policy:
        return None
    return (reference - timedelta(minutes=policy["beforeMinutes"]),
            reference + timedelta(minutes=policy["afterMinutes"]))


def regime_matches(item_text: Any) -> list[re.Match[str]]:
    """Every dated runway-closure regime clause the notice prints (shared pattern)."""
    raw = " ".join(str(item_text or "").upper().split())
    return list(_REGIME.finditer(raw))


def regime_groups() -> dict[str, int]:
    return dict(_REGIME_GROUPS)


__all__ = [
    "NOTAM_TIMING_RULES",
    "NOTAM_TIMING_SPEC_VERSION",
    "TIMING_REVIEW_REASONS",
    "build_timing_gazetteer",
    "decide_lido_record",
    "decide_notice_timing",
    "iso_ms",
    "notice_timing_input",
    "parse_ms",
    "parse_schedule_field",
    "read_lido_schedule_field",
    "read_lido_validity",
    "regime_groups",
    "regime_matches",
    "schedule_occurrences",
    "shared_station_window",
]
