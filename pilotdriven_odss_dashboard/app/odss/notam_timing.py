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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
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
_FIELD_LINE = re.compile(_FIELD["fieldLine"])
_FIELD_TIME = re.compile(_FIELD["fieldStartsWithTime"])
_REVIEW_LANGUAGE = re.compile(_FIELD["reviewLanguage"])
_FREE_TEXT_WORDS = re.compile(_FIELD["freeTextWords"])
_FREE_TEXT_TIME = re.compile(_FIELD["freeTextTime"])
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
    return " ".join(str(line or "").upper().split())


def read_lido_schedule_field(body_lines: Iterable[Any]) -> dict[str, Any]:
    """Item D of a LIDO record: the leading body lines made only of schedule tokens
    (the first must hold a time), joined with one space. ``review`` names schedule
    language this spec does not evaluate; such a record is a review."""
    lines = [text for text in (_field_text(line) for line in body_lines or []) if text]
    field: list[str] = []
    for line in lines:
        tokens = re.sub(r"\.$", "", line)
        if not _FIELD_LINE.search(tokens):
            break
        if not field and not _FIELD_TIME.search(tokens):
            break
        field.append(line)
    text = " ".join(field) if field else None
    if text and _REVIEW_LANGUAGE.search(text):
        return {"field": text, "lineCount": len(field), "review": TIMING_REVIEW_REASONS["reviewLanguage"]}
    if not text:
        free_text = " ".join(lines)
        if _FREE_TEXT_WORDS.search(free_text) and _FREE_TEXT_TIME.search(free_text):
            return {"field": None, "lineCount": 0, "review": TIMING_REVIEW_REASONS["freeText"]}
    return {"field": text, "lineCount": len(field), "review": None}


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
            tokens.append({"kind": "time", "start": start, "end": end + 1440 if end <= start else end})
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


def parse_schedule_field(field: Any, validity: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Item D read into entries; the error is a timing review. Month-less day numbers take
    the latest month named earlier in the field, else the validity month when B and C
    share one month."""
    text = str(field or "").upper()
    text = re.sub("[–—]", "-", text)
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
    if current["dates"] and not current["times"]:
        return [], f"Item D date without a time: {text}"
    if current["times"]:
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

    named_month: int | None = None
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        kinds = {token["kind"] for token in entry["dates"]}
        if not entry["dates"]:
            if index != 0:
                return [], f"Item D times without a date: {text}"
            entries.append({"kind": "daily", "times": entry["times"]})
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
                if not (1 <= from_day <= 31 and 1 <= to_day <= 31):
                    return [], f"Invalid date in Item D: {text}"
                ranges.append((from_month * 100 + from_day, to_month * 100 + to_day))
                named_month = to_month
            else:
                month = named_month if named_month is not None else validity_month
                if month is None:
                    return [], f"Item D day numbers name no month: {text}"
                if token["from"] < 1 or token["to"] > 31 or token["from"] > token["to"]:
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

    if notice.get("review"):
        return review(str(notice["review"]))
    if math.isnan(start_ms) or math.isnan(end_ms) or start_ms >= end_ms:
        return review(TIMING_REVIEW_REASONS["validity"])

    def decided(status: str, intervals: list[tuple[float, float]], **extra: Any) -> dict[str, Any]:
        state, delta, interval = _state_from(intervals, reference_ms)
        return {**base, **extra, "status": status, "stateAtReference": state, "minutesDelta": delta,
                "referenceInterval": _interval_out(interval)}

    validity_interval = [(start_ms, end_ms)]
    if not (start_ms < window_end and window_start < end_ms):
        return decided("outside_window", validity_interval, outsideBy="validity")
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
    field = read_lido_schedule_field(lines)
    return decide_notice_timing({"validity": read_lido_validity(validity_text), "schedule": field["field"],
                                 "review": field["review"]}, window)


def notice_timing_input(record: Mapping[str, Any]) -> dict[str, Any]:
    """The shared decision's input from a parsed LIDO station record (enrichment._parse_airport_notams).

    The record holds what the shared readers read: no valid_to only for an open end (UFN, PERM) - an absent or
    unreadable end is validity_review - and Item D in ``schedule``; schedule language with no Item D is
    schedule_review. An Item D the grammar cannot read is re-read here and decided as a review with its reason.
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
    review = TIMING_REVIEW_REASONS["freeText"] if record.get("schedule_review") and not schedule else None
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
