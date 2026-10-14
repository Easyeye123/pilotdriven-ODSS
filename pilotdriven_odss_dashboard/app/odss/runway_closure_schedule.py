"""One assessment of the dated runway-closure regimes a notice prints.

An AIP supplement can carry several dated closure regimes for several runways
in one notice (WSSS SX120/25: 02L/20R on SUN and WED, 02C/20C on TUE and FRI).
Production audit, 19 Sep 2026: one download said RWY 02C/20C was closed at the
ETA on two pages and that a "RWY 02L/20R restriction could not be resolved" on
a third, because each surface asked the evaluator about a different runway and
"no regime applies to the runway you asked about" came back as "cannot tell".

The assessment therefore belongs to the notice and the reference time - never
to the caller. Every regime is evaluated; the planned runway only decides how a
statement is annotated, not which statements exist. The engine, the dashboard
card, the decision page and the Airports page all read this module, and a
stored analysis from an older build is reconciled through it, so a saved pack
and a fresh one publish the same sentence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping, Sequence

from .notam_timing import regime_groups, regime_matches

_RUNWAY_TOKEN = re.compile(r"\b(?:RWY\s*)?(\d{2}[LCR]?)\b")
# ITEM 3 (14 Oct 2026): the regime grammar is the shared one (notam_timing_rules.json "runwayClosureRegimes"), so
# the app's dashboard chart draws each runway in the state this module publishes for it on the PDF.
_REGIME_GROUPS = regime_groups()
_WEEKDAY_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
# Schedule language the regime grammar above does not read. When any survives
# outside the parsed regimes, the notice keeps an open review.
_TIME_RANGE = re.compile(r"\b\d{4}(?:UTC|Z)?\s*(?:-|TO)\s*\d{4}(?:UTC|Z)?\b", re.IGNORECASE)

RESIDUAL_REVIEW_SENTENCE = (
    "Other scheduled clauses in this notice are not evaluated."
)


def _designators(value: Any) -> list[str]:
    return [match.group(1).upper() for match in _RUNWAY_TOKEN.finditer(str(value or "").upper())]


def _reference_label(role: str) -> str:
    return "ETA" if role == "destination" else ("ETD" if role == "departure" else "REFERENCE")


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _regimes(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Every dated regime the notice prints, and whether other schedule
    language remains outside them."""
    raw = " ".join(str(text or "").upper().split())
    regimes: list[dict[str, Any]] = []
    covered: list[tuple[int, int]] = []
    group = _REGIME_GROUPS
    for match in regime_matches(raw):
        try:
            valid_from = datetime.strptime(match.group(group["validFrom"]).upper(), "%d%b%y").date()
            valid_to = datetime.strptime(match.group(group["validTo"]).upper(), "%d%b%y").date()
        except ValueError:
            continue
        start_text, end_text = match.group(group["start"]), match.group(group["end"])
        start_minutes = int(start_text[:2]) * 60 + int(start_text[2:])
        end_minutes = int(end_text[:2]) * 60 + int(end_text[2:])
        if int(start_text[:2]) > 23 or int(end_text[:2]) > 23 or int(start_text[2:]) > 59 or int(end_text[2:]) > 59:
            continue
        # A zero-length regime (start = end) is not read, as an invalid clock is not (notam_timing_rules.json).
        if start_minutes == end_minutes:
            continue
        covered.append(match.span())
        regimes.append({
            "label": match.group(group["runways"]).upper(),
            "runways": sorted(set(_designators(match.group(group["runways"])))),
            "start": start_text,
            "end": end_text,
            "startMinutes": start_minutes,
            "endMinutes": end_minutes,
            "weekdays": sorted({
                _WEEKDAY_INDEX[token]
                for token in re.findall(r"MON|TUE|WED|THU|FRI|SAT|SUN", match.group(group["weekdays"]).upper())
            }),
            "validFrom": valid_from,
            "validTo": valid_to,
        })
    residual = any(
        not any(start <= found.start() and found.end() <= end for start, end in covered)
        for found in _TIME_RANGE.finditer(raw)
    )
    return regimes, residual


def _occurrence(regime: Mapping[str, Any], reference: datetime) -> tuple[datetime, datetime] | None:
    """The regime's closure on the reference day, or the one begun the evening
    before that is still running."""
    candidates = []
    for day_offset in (0, -1):
        day = (reference + timedelta(days=day_offset)).date()
        if not regime["validFrom"] <= day <= regime["validTo"] or day.weekday() not in regime["weekdays"]:
            continue
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=regime["startMinutes"])
        end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=regime["endMinutes"])
        if end <= start:
            end += timedelta(days=1)
        if day_offset == -1 and not start <= reference < end:
            continue
        candidates.append((start, end))
    if not candidates:
        return None
    active = [pair for pair in candidates if pair[0] <= reference < pair[1]]
    return (active or candidates)[0]


def assess_runway_closure_schedule(
    item_e_text: Any,
    *,
    role: str,
    reference_time: datetime | None,
    planned_runway: Any = None,
) -> dict[str, Any] | None:
    """Evaluate every dated closure regime in a notice at one reference time.

    ``None`` means the notice prints no such regime (or no reference is held)
    and the existing analysis owns it. Otherwise ``statements`` holds one entry
    per regime in effect on the reference day, in source order; it is empty
    when no regime applies that day. ``planned_runway`` annotates a statement;
    it never selects one.
    """
    reference = _utc(reference_time)
    if reference is None:
        return None
    regimes, residual = _regimes(item_e_text)
    if not regimes:
        return None
    planned = [token for token in _designators(planned_runway)]
    label = _reference_label(role)
    display = reference.strftime("%H%MZ")
    evaluated: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    for regime in regimes:
        in_dates = regime["validFrom"] <= reference.date() <= regime["validTo"]
        occurrence = _occurrence(regime, reference)
        row = {
            "label": regime["label"],
            "runways": regime["runways"],
            "window": f"{regime['start']}-{regime['end']}Z",
            "inDateRange": in_dates,
            "appliesOnReferenceDay": occurrence is not None,
        }
        evaluated.append(row)
        if occurrence is None:
            continue
        start, end = occurrence
        window = f"{regime['start']}-{regime['end']}Z"
        if reference < start:
            delta = int((start - reference).total_seconds() // 60)
            state = "begins_after_reference"
            text = (
                f"RWY {regime['label']} closes {window}; {label} {display} "
                f"precedes closure by {delta // 60}h{delta % 60:02d}."
            )
        elif reference < end:
            state = "active_at_reference"
            text = f"RWY {regime['label']} closes {window}; {label} {display} is within the closure."
        else:
            delta = int((reference - end).total_seconds() // 60)
            state = "ended_before_reference"
            text = (
                f"RWY {regime['label']} closure {window} ends "
                f"{delta // 60}h{delta % 60:02d} before {label} {display}."
            )
        planned_affected = bool(set(planned) & set(regime["runways"])) if planned else None
        line = text
        if planned_affected is False:
            line += f" Planned RWY {'/'.join(planned)} differs from this affected runway."
        statements.append({
            "text": text,
            "line": line,
            "runways": regime["runways"],
            "referenceAt": reference.isoformat(),
            "referenceInterval": {"startsAt": start.isoformat(), "endsAt": end.isoformat()},
            "stateAtReference": state,
            "plannedRunwayAffected": planned_affected,
        })
    return {
        "referenceAt": reference.isoformat(),
        "regimes": evaluated,
        "statements": statements,
        "residualReview": residual,
    }


def published_runway_closure_statement(
    item_e_text: Any,
    *,
    role: str,
    reference_time: datetime | None,
    planned_runway: Any = None,
) -> dict[str, Any] | None:
    """The sentence every surface publishes for the notice, or ``None`` when
    the assessment makes no closure claim for the reference day."""
    assessment = assess_runway_closure_schedule(
        item_e_text, role=role, reference_time=reference_time, planned_runway=planned_runway,
    )
    if not assessment or not assessment["statements"]:
        return None
    line = " ".join(statement["line"] for statement in assessment["statements"])
    return {
        "line": line,
        "text": f"{line} {RESIDUAL_REVIEW_SENTENCE}" if assessment["residualReview"] else line,
        "residualReview": assessment["residualReview"],
        "assessment": assessment,
    }


def notice_reference_time(notice: Mapping[str, Any], role: str, fallback: datetime | None = None) -> datetime | None:
    """The time the engine assessed this notice at, for this role.

    A caller may hold another clock (a window midpoint, a scheduled time). The
    notice was assessed once; its own ``referenceAt`` is the time basis, and a
    caller's clock is used only where an older record holds none.
    """
    for row in notice.get("role_applicability") or []:
        if isinstance(row, Mapping) and row.get("role") == role and row.get("referenceAt"):
            return _utc(row["referenceAt"])
    return _utc(notice.get("referenceAt")) or _utc(fallback)


def planned_runway_for_role(flight: Mapping[str, Any] | None, role: str) -> str:
    if role not in {"departure", "destination"}:
        return ""
    return str((flight or {}).get(f"{role}_runway") or "").strip().upper()


def reconcile_runway_closure_findings(
    findings: Sequence[Mapping[str, Any]] | None,
    flight: Mapping[str, Any] | None,
) -> list[Any]:
    """Give a stored NOTAM finding the statement a fresh analysis gives it.

    A pack analysed by an older build holds the engine's review sentence for a
    notice this module can evaluate. Publication rebuilds its view from those
    held findings, so they are reconciled here - on a copy, idempotently - and
    nothing that the assessment makes no claim about is touched.
    """
    reconciled: list[Any] = []
    for finding in findings or []:
        data = finding.get("data") if isinstance(finding, Mapping) else None
        if not isinstance(data, Mapping) or finding.get("engine") != "notam":
            reconciled.append(finding)
            continue
        role = str(data.get("role") or "")
        statement = published_runway_closure_statement(
            data.get("raw_text"),
            role=role,
            reference_time=notice_reference_time(data, role),
            planned_runway=planned_runway_for_role(flight, role),
        )
        if statement is None or finding.get("summary") == statement["text"]:
            reconciled.append(finding)
            continue
        reconciled.append({**finding, "summary": statement["text"]})
    return reconciled


__all__ = [
    "RESIDUAL_REVIEW_SENTENCE",
    "assess_runway_closure_schedule",
    "notice_reference_time",
    "planned_runway_for_role",
    "published_runway_closure_statement",
    "reconcile_runway_closure_findings",
]
