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
classifies it (I6, _object_tokens): unclassified, a review.
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
_OBJECT_END = _words_rx(_OBJECT["objectEnd"])
_OBJECT_COORDINATION = _words_rx(_OBJECT["coordination"])
_OBJECT_LISTS = frozenset(_OBJECT["lists"])
_OBJECT_STOP = _words_rx(_OBJECT["stop"])
_OBJECT_OPEN_END = re.compile(f"(?:{_OBJECT['openEnd']})(?![A-Z0-9])", _A)
_OBJECT_MODIFIER = _words_rx(_OBJECT["temporalModifier"])
_OBJECT_MODIFIER_OF = _words_rx(_OBJECT["modifierOf"])
_OBJECT_ANAPHORA = _words_rx(_OBJECT["anaphora"])
_OBJECT_ANAPHORA_PERIOD = _words_rx(_OBJECT["anaphoraPeriod"])
_OBJECT_CODE = _words_rx(_OBJECT["code"])
_OBJECT_CODE_NEVER = _words_rx(_OBJECT["codeNever"])
_OBJECT_CODE_ALONE = _words_rx(_OBJECT["codeAlone"])
_OBJECT_DESIGNATOR = _words_rx(_OBJECT["designator"])
_OBJECT_DESIGNATION_NOUN = _words_rx(_OBJECT["designationNoun"])
_OBJECT_GOVERNOR_ROLES = tuple(_OBJECT["governorRoles"])
_OBJECT_ROLES = {name: _words_rx(words) for name, words in _OBJECT["roles"].items()}
_OBJECT_ADMITS = _OBJECT["admits"]
_OBJECT_WINDOW = int(_OBJECT["windowWords"])
_OBJECT_SENTENCE = re.compile(_FIELD["syntax"]["clauseBoundary"], _A)
_OBJECT_BOUNDARY = re.compile(_OBJECT["objectBoundary"], _A)


def _has_role(word: str, roles: Iterable[str]) -> bool:
    return any(_OBJECT_ROLES[role].fullmatch(word) for role in roles if role in _OBJECT_ROLES)


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


def _object_is_temporal(kind: str, determined: bool, phrase: list[str], of_word: str | None,
                        previous: str | None, structured: bool) -> bool:
    """Whether a connective's object is temporal content (temporalObject): it is, unless positively classified by a
    benign mask or by a role the connective admits."""
    admits = _OBJECT_ADMITS[kind]
    head = phrase[0]
    if "#" in head:
        return False  # a benign class (designator, position, quantity ...) governs it
    if "anaphora" in admits:
        lead = 0
        while lead < len(phrase) and _OBJECT_ANAPHORA.fullmatch(phrase[lead]):
            lead += 1
        if lead and (determined or any(_OBJECT_ANAPHORA_PERIOD.fullmatch(word) for word in phrase[:lead])):
            return False  # 'DURING THIS PERIOD', 'DRG THE CLOSURE', 'DRG EXER PERIOD': the notice's own stated content
    if "notice" in admits and any(_has_role(word, ("notice",)) for word in phrase):
        return False  # 'AT SHORT NOTICE': the notification's lead time, not the restriction's time
    if "governor" in admits and previous is not None and ("#" in previous or _has_role(previous, _OBJECT_GOVERNOR_ROLES)):
        return False  # 'PAL 253.2MHZ AT CHIBOUGAMAU', 'ENERGY PLANT AT OLIVIA': the location of what precedes
    if _OBJECT_MODIFIER.fullmatch(head):
        # 'AFTER LAST FLIGHT', 'AT SHORT NOTICE' are temporal; 'FM BEGINNING OF RWY 19R' is the place's part
        return not (of_word is not None and ("#" in of_word or _has_role(of_word, ("place",))))
    for index, word in enumerate(phrase):
        if "#" in word and all(_has_role(before, _OBJECT_ROLES) for before in phrase[:index]):
            return False  # 'AFTER ACFT STAND 517L': a masked designator headed by role words
    if any(_has_role(word, admits) and not (index and index + 1 < len(phrase) and _OBJECT_DESIGNATION_NOUN.fullmatch(word)
                                             and _OBJECT_DESIGNATOR.fullmatch(phrase[index + 1]))
           for index, word in enumerate(phrase)):
        return False  # a role word heads the object's noun phrase ('AT AIMING POINT', 'EXC SKED ACFT')
    if "code" in admits and (structured or _OBJECT_CODE_ALONE.fullmatch(head)):
        return False  # codes in a structure of codes, a route segment, a web address
    return True


def _connective_objects(masked: str, start: int, end: int) -> list[dict[str, Any]]:
    """The connectives of masked[start:end] with their objects (temporalObject; see _object_tokens)."""
    words = _object_words(masked, start, end)
    objects: list[dict[str, Any]] = []
    range_at: int | None = None
    range_object: dict[str, Any] | None = None
    for index, (_, _, word, closed) in enumerate(words):
        closes = None
        if range_at is not None and index - range_at <= _OBJECT_RANGE_WITHIN and _OBJECT_RANGE_END.fullmatch(word):
            kind: str | None = "spatial"
            closes = range_object
        else:
            kind = next((name for name, pattern in _OBJECT_CLASSES.items() if pattern.fullmatch(word)), None)
        opens = bool(_OBJECT_RANGE_AFTER.fullmatch(word))
        if opens:
            range_at, range_object = index, None
        if kind is None or closed:
            continue  # not a connective, or 'UNTIL,' - its object ends before it starts
        previous = words[index - 1][2] if index and not words[index - 1][3] else None
        at = index + 1
        determined = False
        while at < len(words) and _OBJECT_SKIP.fullmatch(words[at][2]) and not words[at][3]:
            determined = determined or bool(_OBJECT_DETERMINER.fullmatch(words[at][2]))
            at += 1
        if at >= len(words) or _OBJECT_OPEN_END.match(masked, words[at][0]):
            continue
        phrase: list[tuple[int, int, str]] = []
        joined: str | None = None
        while at < len(words) and len(phrase) < _OBJECT_WINDOW:
            low, high, word, closed = words[at]
            if kind in _OBJECT_LISTS and phrase and _OBJECT_COORDINATION.fullmatch(word) and not closed:
                if joined is None and at + 1 < len(words):
                    joined = words[at + 1][2]
                at += 1
                continue
            if (_OBJECT_STOP.fullmatch(word) or _OBJECT_RESTRICTION_WORD.fullmatch(word)
                    or (phrase and _OBJECT_END.fullmatch(word))):
                break
            phrase.append((low, high, word))
            at += 1
            if closed and not (kind in _OBJECT_LISTS and any(
                    _OBJECT_COORDINATION.fullmatch(later[2]) for later in words[at:at + _OBJECT_WINDOW])):
                break
        if not phrase:
            continue
        of_word = None
        if at < len(words) and _OBJECT_MODIFIER_OF.fullmatch(words[at][2]) and not words[at][3]:
            after = at + 1
            while after < len(words) and _OBJECT_SKIP.fullmatch(words[after][2]) and not words[after][3]:
                after += 1
            of_word = words[after][2] if after < len(words) else None
        head = phrase[0][2]
        item = {"kind": kind, "phrase": phrase, "determined": determined, "of": of_word, "previous": previous,
                "structured": _is_code(head) and joined is not None and (_is_code(joined) or "#" in joined)}
        if closes is not None:
            # the two ends of a FROM range: codes (or a mask) on both sides make both a place
            ends = (closes["phrase"][0][2], head)
            if all(_is_code(end) or "#" in end for end in ends) and any(_is_code(end) for end in ends):
                closes["structured"] = item["structured"] = True
        if opens:
            range_object = item
        objects.append(item)
    return objects


def _object_tokens(masked: str, text: str) -> list[tuple[int, int]]:
    """QA518 I6: the objects of temporal connectives that are temporal content. In a sentence (syntax.clauseBoundary)
    of the masked syntactic text that holds a restriction, every connective of temporalObject.connectives (and
    TO/UNTIL/TIL/TILL closing a FROM/FM range, in the range's role) takes as its object the words after it - determiners
    and prepositions skipped - up to windowWords, an object boundary, a stop word, a restriction verb or a word ending
    the phrase; a list object (spatial, exception) continues through AND/OR. The object is temporal content - its head a
    token the grammar must account for - unless it is an open end or _object_is_temporal classifies it by a mask or an
    admitted role. A connective followed by another connective, a stop word or a boundary has no object of its own.
    The sentences are found on ``text``, the unmasked syntactic text (a mask may paint over a sentence's period: '4.')
    of which ``masked`` is the masked copy, character for character."""
    found: list[tuple[int, int]] = []
    start = 0
    for boundary in [*_OBJECT_SENTENCE.finditer(text), None]:
        end = boundary.start() if boundary else len(masked)
        if _OBJECT_RESTRICTION.search(masked[start:end]):
            for item in _connective_objects(masked, start, end):
                words = [word for _, _, word in item["phrase"]]
                if _object_is_temporal(item["kind"], item["determined"], words, item["of"], item["previous"],
                                       item["structured"]):
                    found.append(item["phrase"][0][:2])
        start = boundary.end() if boundary else len(masked)
    return found


def _free_text_review(text: str, field: str | None, entries: list[dict[str, Any]] | None,
                      validity: Mapping[str, Any] | None, line_starts: Iterable[int] = (0,)) -> str | None:
    """The review the free text after the field calls for, or None (QA506: fail closed; QA510: temporal content is
    found by SHAPE; QA514: every digit accounted for). Benign spans are masked; every temporal token left - every
    clock-like shape whatever its values - and EVERY digit left (accountedResidue) must sit in a statement the grammar
    reads whole and that is accounted for, else a review. None comes only out of that accounting: free text that,
    masked, holds no digit and no temporal content of any shape, or whose every statement is proven."""
    reason = TIMING_REVIEW_REASONS["freeTextConflict"] if field else TIMING_REVIEW_REASONS["freeText"]
    masked = _mask_benign(text or "", line_starts)
    tokens = (_temporal_tokens(masked) + _residue_spans(masked)
              + [match.span() for match in _RESIDUE_WORDS.finditer(masked)] + _object_tokens(masked, text or ""))
    statements = [(match.start(), match.end(), match.group(0)) for match in _STATEMENT.finditer(masked)]
    if any(not any(low <= start and end <= high for low, high, _ in statements) for start, end in tokens):
        return reason
    for low, high, statement in statements:
        if not any(low <= start and end <= high for start, end in tokens):
            continue
        if not (validity or {}).get("startsAt"):
            return reason
        parsed = _parse_statement(statement, validity)
        if parsed is None or not _statement_accounted(parsed[0], parsed[1], entries if field else None, validity):
            return reason
    return None


def read_lido_schedule_field(body_lines: Iterable[Any], validity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Item D of a LIDO record: the leading body lines made only of schedule tokens, joined with one space, across
    line wraps. ``review`` is why the record's timing cannot be read: schedule language this spec does not evaluate, a
    leading field the grammar cannot read in full, or schedule-bearing language in the free text that is not accounted
    for (QA506: every temporal token left once the stated benign classes are masked must sit in a statement the grammar
    reads whole and that is proven equal, on its own, to Item D or to the whole validity). ``validity`` is the record's
    read_lido_validity() result; without one the record is a validity review."""
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

    def read(review: str | None) -> dict[str, Any]:
        return {"field": field, "lineCount": line_count, "review": review}

    if not field:
        return read(_free_text_review(free_text, None, None, validity, line_starts))
    if _REVIEW_LANGUAGE.search(field):
        return read(TIMING_REVIEW_REASONS["reviewLanguage"])
    if not (validity or {}).get("startsAt"):
        return read(_free_text_review(free_text, field, None, None, line_starts))
    entries, error = parse_schedule_field(field, validity)
    if error:
        return read(error)
    return read(_free_text_review(free_text, field, entries, validity, line_starts))


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


def decide_lido_record(validity_text: Any, lines: Iterable[Any], window: Mapping[str, Any]) -> dict[str, Any]:
    """Read a LIDO record (validity text + body lines) and decide it: the whole shared path."""
    validity = read_lido_validity(validity_text)
    field = read_lido_schedule_field(lines, validity)
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
