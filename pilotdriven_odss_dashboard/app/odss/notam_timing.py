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
"""
from __future__ import annotations

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

_VALIDITY_RANGE = re.compile(NOTAM_TIMING_RULES["validity"]["range"])
_VALIDITY_END = re.compile(NOTAM_TIMING_RULES["validity"]["end"])
_OPEN_ENDS: dict[str, str] = NOTAM_TIMING_RULES["validity"]["openEnds"]
_FIELD = NOTAM_TIMING_RULES["scheduleField"]
_DASHES = re.compile(_FIELD["dashes"])
_FIELD_LINE = re.compile(_FIELD["fieldLine"])
_REVIEW_LANGUAGE = re.compile(_FIELD["reviewLanguage"])
_COLON_CLOCK = re.compile(_FIELD["colonClock"])
_A = re.ASCII  # '\\b', '\\d' and '\\w' read as in JavaScript


def _js_replacement(replacement: str) -> str:
    """The rules file writes replacements as JavaScript does ('$1'); Python reads them as '\\g<1>'."""
    return re.sub(r"\$(\d)", r"\\g<\1>", replacement)


_LETTER_FOR_DIGIT_RUN = re.compile(_FIELD["letterForDigit"]["run"], _A)
_BENIGN = [(item["class"], re.compile(item["pattern"], _A), bool(item.get("allowClockRange")),
            bool(item.get("holdsNoTemporal")), int(item.get("maskGroup") or 0)) for item in _FIELD["benign"]]
_BENIGN_NEVER_HOLDS = re.compile(_FIELD["benignNeverHolds"], _A)
_BENIGN_NEVER_CUTS = re.compile(_FIELD["benignNeverCuts"], _A)
_ABUTS_AFTER = re.compile(_FIELD["rangeAbutment"]["after"], _A)
_ABUTS_BEFORE = re.compile(_FIELD["rangeAbutment"]["before"], _A)
_GOVERNING_CONNECTIVE = re.compile(_FIELD["benignGovernance"]["connective"], _A)
_GOVERNED_OBJECT = re.compile(_FIELD["benignGovernance"]["object"], _A)
_PERIOD_CONNECTIVE = re.compile(_FIELD["benignGovernance"]["periodConnective"], _A)
_SELF_EVIDENT = re.compile(_FIELD["benignGovernance"]["selfEvident"], _A)
_ACCOUNTED_RESIDUE = re.compile(_FIELD["accountedResidue"], _A)
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
_REGIME = re.compile(NOTAM_TIMING_RULES["runwayClosureRegimes"]["pattern"], re.IGNORECASE)
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
    return " ".join(_DASHES.sub("-", text.upper()).split())


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


def _benign_spans(text: str) -> list[tuple[int, int, str]]:
    """The benign spans kept in one free-text line, as (start, end, class): every span a benign class POSITIVELY
    classifies as not temporal. A span never cuts a clock-like shape found in the unmasked text (benignNeverCuts: it
    may hold a whole one - 'TORA 2100' - never part of one: 'FL180/18' of 'FL180/18 00'), and never holds any
    temporal token of the unmasked text when its class states holdsNoTemporal; a span that holds or cuts a clock-
    like range is never benign unless its class states allowClockRange (benignNeverHolds); a span is never the
    object of a temporal connective (benignGovernance, QA514: one beginning with a digit or a time word directly
    after DURING, UNTIL, FROM, AT, TO ..., and any holding a digit after DURING, OUTSIDE, SINCE or WEF, unless it is
    self-evidently not a time); and a span is never one side of a range: it is refused when a range connector joins
    it to temporal content left unmasked once every candidate span is masked (rangeAbutment). A class that states
    maskGroup masks only that group of its match."""
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
    for name, pattern, allow_clock_range, holds_no_temporal, mask_group in _BENIGN:
        for match in pattern.finditer(text):
            start, end = match.span(mask_group)
            if end <= start or cuts_shape(start, end) or (not allow_clock_range and meets_range(start, end)):
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


def _mask_benign(text: str) -> str:
    return _paint(text, [(start, end) for start, end, _ in _benign_spans(text)])


def explain_schedule_free_text(text: str) -> dict[str, Any]:
    """The benign spans kept in one free-text line and the text they leave (QA514 tests and fuzzing: which class
    masked what). ``text`` is a body line as the grammar reads it (upper case, dashes folded, whitespace collapsed)."""
    spans = _benign_spans(str(text or ""))
    return {"masked": _paint(str(text or ""), [(start, end) for start, end, _ in spans]),
            "spans": [{"class": name, "start": start, "end": end} for start, end, name in spans]}


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


def _free_text_review(text: str, field: str | None, entries: list[dict[str, Any]] | None,
                      validity: Mapping[str, Any] | None) -> str | None:
    """The review the free text after the field calls for, or None (QA506: fail closed; QA510: temporal content is
    found by SHAPE; QA514: every digit accounted for). Benign spans are masked; every temporal token left - every
    clock-like shape whatever its values - and EVERY digit left (accountedResidue) must sit in a statement the grammar
    reads whole and that is accounted for, else a review. None comes only out of that accounting: free text that,
    masked, holds no digit and no temporal content of any shape, or whose every statement is proven."""
    reason = TIMING_REVIEW_REASONS["freeTextConflict"] if field else TIMING_REVIEW_REASONS["freeText"]
    masked = _mask_benign(text or "")
    tokens = _temporal_tokens(masked) + [match.span() for match in _ACCOUNTED_RESIDUE.finditer(masked)]
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
    field = " ".join(lines[:line_count]) if line_count else None
    free_text = " ".join(lines[line_count:])

    def read(review: str | None) -> dict[str, Any]:
        return {"field": field, "lineCount": line_count, "review": review}

    if not field:
        return read(_free_text_review(free_text, None, None, validity))
    if _REVIEW_LANGUAGE.search(field):
        return read(TIMING_REVIEW_REASONS["reviewLanguage"])
    if not (validity or {}).get("startsAt"):
        return read(_free_text_review(free_text, field, None, None))
    entries, error = parse_schedule_field(field, validity)
    if error:
        return read(error)
    return read(_free_text_review(free_text, field, entries, validity))


_TOKEN = re.compile("|".join([
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
]))


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
    text = re.sub(r"(\d{4})(?:UTC|Z)\b", r"\1", text)
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
