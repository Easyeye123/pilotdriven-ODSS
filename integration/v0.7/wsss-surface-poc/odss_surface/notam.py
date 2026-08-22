from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from .models import ApplicabilityState, NotamFields, SurfaceClause
from .osm import normalize_ref

_FIELD_PATTERNS = {
    "id": re.compile(r"(?:^|\s)([A-Z]\d{4}/\d{2})\s+(?:NOTAMN|NOTAMR|NOTAMC)\b", re.I),
    "A": re.compile(r"(?:^|\s)A\)\s*([A-Z]{4})\b", re.I),
    "B": re.compile(r"(?:^|\s)B\)\s*(\d{10})\b", re.I),
    "C": re.compile(r"(?:^|\s)C\)\s*(\d{10}(?:\s*EST)?|PERM)\b", re.I),
    "D": re.compile(r"(?:^|\s)D\)\s*(.*?)(?=(?:\s+[EFG]\))|\Z)", re.I | re.S),
    "E": re.compile(r"(?:^|\s)E\)\s*(.*?)(?=(?:\s+[FG]\))|\Z)", re.I | re.S),
}

_SURFACE = r"(?:TWY|TXL|TAXIWAY|TAXILANE)"
_REF = r"([A-Z]{1,3}\d*[A-Z]?)"
_RANGE_RE = re.compile(
    rf"\b(?P<prefix>TWY|TXL|TAXIWAY|TAXILANE)\s+(?P<target>[A-Z]{{1,3}}\d*[A-Z]?)\s+"
    rf"(?:BTN|BETWEEN)\s+{_SURFACE}\s+(?P<start>[A-Z]{{1,3}}\d*[A-Z]?)\s+"
    rf"(?:AND|TO|-)\s+{_SURFACE}\s+(?P<end>[A-Z]{{1,3}}\d*[A-Z]?)\b",
    re.I,
)
_BEHIND_RANGE_RE = re.compile(
    rf"\b(?P<prefix>TWY|TXL|TAXIWAY|TAXILANE)\s+(?P<target>[A-Z]{{1,3}}\d*[A-Z]?)\s+"
    rf"BEHIND\s+(?:ACFT\s+)?STANDS?\s+(?P<start>[A-Z0-9]+)\s+(?:TO|AND|-)\s+(?P<end>[A-Z0-9]+)\b",
    re.I,
)
_BEHIND_ONE_RE = re.compile(
    rf"\b(?P<prefix>TWY|TXL|TAXIWAY|TAXILANE)\s+(?P<target>[A-Z]{{1,3}}\d*[A-Z]?)\s+"
    rf"BEHIND\s+(?:ACFT\s+)?STAND\s+(?P<stand>[A-Z0-9]+)\b",
    re.I,
)
_CODE_RESTRICTION_RE = re.compile(
    rf"\b(?P<prefix>TWY|TXL|TAXIWAY|TAXILANE)\s+(?P<target>[A-Z]{{1,3}}\d*[A-Z]?)\b"
    rf".*?\b(?:NOT\s+AVBL|UNAVAILABLE|RESTRICTED)\s+FOR\s+(?:ACFT\s+)?CODE\s+(?P<code>[A-F])"
    rf"(?P<above>\s+(?:AND|OR)\s+ABOVE)?\b",
    re.I | re.S,
)
_WHOLE_RE = re.compile(
    rf"\b(?P<prefix>TWY|TXL|TAXIWAY|TAXILANE)\s+(?P<target>[A-Z]{{1,3}}\d*[A-Z]?)\s+"
    rf"(?:IS\s+)?(?:CLSD|CLOSED|NOT\s+AVBL|UNAVAILABLE|RESTRICTED)\b",
    re.I,
)
_JUNCTION_RE = re.compile(r"\bJUNCTION(?:S)?\s+OF\s+([^.;\n]+)", re.I)
_REF_IN_JUNCTION_RE = re.compile(rf"(?:TWY|TXL|TAXIWAY|TAXILANE)?\s*{_REF}", re.I)

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_CODE_ORDER = {letter: index for index, letter in enumerate("ABCDEF", start=1)}


def _parse_utc(value: str | None) -> datetime | None:
    if not value or value.upper().startswith("PERM"):
        return None
    match = re.match(r"^(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", value.strip())
    if not match:
        return None
    year = 2000 + int(match.group(1))
    return datetime(
        year,
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
        tzinfo=timezone.utc,
    )


def parse_notam_fields(raw: str) -> NotamFields:
    text = str(raw or "").replace("\r", "").strip()
    matches = {name: pattern.search(text) for name, pattern in _FIELD_PATTERNS.items()}
    c_value = matches["C"].group(1).strip() if matches["C"] else None
    return NotamFields(
        notam_id=matches["id"].group(1).upper() if matches["id"] else None,
        airport=matches["A"].group(1).upper() if matches["A"] else None,
        starts_at=_parse_utc(matches["B"].group(1)) if matches["B"] else None,
        ends_at=_parse_utc(c_value),
        schedule=matches["D"].group(1).strip() if matches["D"] else None,
        e_line=(matches["E"].group(1).strip() if matches["E"] else text),
        raw=text,
    )


def _split_numbered_clauses(e_line: str) -> list[str]:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in e_line.replace("\r", "").splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    matches = list(re.finditer(r"(?m)^\s*\d+[.)]\s*", text))
    if not matches:
        return [re.sub(r"^FLW\s+.*?CLSD(?:\s+DUE\s+\w+)?\s*:?\s*", "", text, flags=re.I).strip()]
    clauses: list[str] = []
    prefix = text[: matches[0].start()].strip()
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip(" ;\n")
        if value:
            clauses.append(value)
    return clauses


def _surface_kind(prefix: str) -> str:
    return "taxilane" if prefix.upper() in {"TXL", "TAXILANE"} else "taxiway"


def _junction_refs(text: str) -> tuple[str, ...]:
    match = _JUNCTION_RE.search(text)
    if not match:
        return ()
    result: list[str] = []
    for token in re.findall(r"(?:TWY|TXL|TAXIWAY|TAXILANE)?\s*([A-Z]{1,3}\d*[A-Z]?)", match.group(1), flags=re.I):
        ref = normalize_ref(token)
        if ref and ref not in result and ref not in {"AND", "INCL", "INCLUDING"}:
            result.append(ref)
    return tuple(result)


def parse_surface_clauses(fields_or_raw: NotamFields | str) -> list[SurfaceClause]:
    fields = fields_or_raw if isinstance(fields_or_raw, NotamFields) else parse_notam_fields(fields_or_raw)
    clauses: list[SurfaceClause] = []
    for raw_clause in _split_numbered_clauses(fields.e_line):
        text = raw_clause.upper()
        junctions = _junction_refs(text)

        match = _CODE_RESTRICTION_RE.search(text)
        if match:
            clauses.append(
                SurfaceClause(
                    raw=raw_clause,
                    target_ref=normalize_ref(match.group("target")) or match.group("target"),
                    target_kind=_surface_kind(match.group("prefix")),
                    operation="restricted",
                    method="aircraft_code_restriction",
                    restricted_code=match.group("code").upper(),
                    restricted_code_and_above=bool(match.group("above")),
                    include_junction_refs=junctions,
                )
            )
            continue

        match = _RANGE_RE.search(text)
        if match:
            clauses.append(
                SurfaceClause(
                    raw=raw_clause,
                    target_ref=normalize_ref(match.group("target")) or match.group("target"),
                    target_kind=_surface_kind(match.group("prefix")),
                    operation="closed" if re.search(r"\b(?:CLSD|CLOSED)\b", text) else "restricted",
                    method="between_intersections",
                    start_ref=normalize_ref(match.group("start")),
                    end_ref=normalize_ref(match.group("end")),
                    include_junction_refs=junctions,
                )
            )
            continue

        match = _BEHIND_RANGE_RE.search(text)
        if match:
            clauses.append(
                SurfaceClause(
                    raw=raw_clause,
                    target_ref=normalize_ref(match.group("target")) or match.group("target"),
                    target_kind=_surface_kind(match.group("prefix")),
                    operation="closed" if re.search(r"\b(?:CLSD|CLOSED)\b", text) else "restricted",
                    method="behind_stand_range",
                    stand_start=normalize_ref(match.group("start")),
                    stand_end=normalize_ref(match.group("end")),
                    include_junction_refs=junctions,
                )
            )
            continue

        match = _BEHIND_ONE_RE.search(text)
        if match:
            clauses.append(
                SurfaceClause(
                    raw=raw_clause,
                    target_ref=normalize_ref(match.group("target")) or match.group("target"),
                    target_kind=_surface_kind(match.group("prefix")),
                    operation="closed" if re.search(r"\b(?:CLSD|CLOSED)\b", text) else "restricted",
                    method="behind_stand",
                    stand_start=normalize_ref(match.group("stand")),
                    include_junction_refs=junctions,
                )
            )
            continue

        match = _WHOLE_RE.search(text)
        if match:
            clauses.append(
                SurfaceClause(
                    raw=raw_clause,
                    target_ref=normalize_ref(match.group("target")) or match.group("target"),
                    target_kind=_surface_kind(match.group("prefix")),
                    operation="closed" if re.search(r"\b(?:CLSD|CLOSED)\b", text) else "restricted",
                    method="whole_surface",
                    include_junction_refs=junctions,
                )
            )
    return clauses


def evaluate_aircraft_code(clause: SurfaceClause, selected_code: str | None) -> bool | None:
    if clause.method != "aircraft_code_restriction" or not clause.restricted_code:
        return None
    if not selected_code or selected_code.upper() not in _CODE_ORDER:
        return None
    selected = _CODE_ORDER[selected_code.upper()]
    restricted = _CODE_ORDER[clause.restricted_code]
    return selected >= restricted if clause.restricted_code_and_above else selected == restricted


def evaluate_applicability(fields: NotamFields, briefing_time: datetime | None) -> ApplicabilityState:
    if briefing_time is None:
        return "unknown"
    if briefing_time.tzinfo is None:
        briefing_time = briefing_time.replace(tzinfo=timezone.utc)
    briefing_time = briefing_time.astimezone(timezone.utc)
    if fields.starts_at and briefing_time < fields.starts_at:
        return "inactive"
    if fields.ends_at and briefing_time > fields.ends_at:
        return "inactive"
    if fields.schedule:
        return _evaluate_schedule(fields.schedule, briefing_time, fields.starts_at)
    return "active"


def _hm_minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[2:])


def _within_time_window(now_minutes: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= now_minutes <= end
    return now_minutes >= start or now_minutes <= end


def _evaluate_schedule(schedule: str, briefing_time: datetime, starts_at: datetime | None) -> ApplicabilityState:
    value = re.sub(r"\s+", " ", schedule.upper()).strip()
    windows = re.findall(r"\b(\d{4})-(\d{4})\b", value)
    if not windows:
        return "schedule_review"
    now_minutes = briefing_time.hour * 60 + briefing_time.minute
    if value.startswith("DLY") or " DAILY " in f" {value} ":
        return "active" if any(_within_time_window(now_minutes, _hm_minutes(a), _hm_minutes(b)) for a, b in windows) else "inactive"

    month_match = re.search(r"\b(" + "|".join(_MONTHS) + r")\b", value)
    if not month_match:
        return "schedule_review"
    month = _MONTHS[month_match.group(1)]
    if briefing_time.month != month:
        return "inactive"
    before_window = value[: windows and value.find(windows[0][0])]
    day_tokens = [int(token) for token in re.findall(r"\b(?:0?[1-9]|[12]\d|3[01])\b", before_window)]
    if not day_tokens:
        return "schedule_review"
    if briefing_time.day not in day_tokens:
        return "inactive"
    return "active" if any(_within_time_window(now_minutes, _hm_minutes(a), _hm_minutes(b)) for a, b in windows) else "inactive"
