"""One vocabulary for a source's status on every surface (ITEM2-VOLCANIC, 24 Oct 2026).

Open item #2 (Jabe's baseline, 30 Sep 2026): "The PDF wrongly says a warning source wasn't checked." The genuine SQ314
analysis of release 440 held a VA SIGMET feed that answered (118 records, retrieved 27 Sep) while its checklist said
"VA SIGMET feed: reached, not current" - and its source row said NOT REACHED, so page 6 printed "VA SIGMET FEED not
reached". One response contradicted itself because a single status word carried two facts: whether the source answered
(reach) and whether its answer speaks for this flight (currency, completeness, evaluation, responsibility). Every
reached state other than "reached and complete" fell into NOT REACHED; an unknown status printed "not held".

A status is now composed from the two facts, never written as a free string:

- the REACH, exactly one of ``REACHES``: an uploaded document's record is HELD / NOT HELD; a live source is REACHED,
  PARTIAL (some of several answered), NOT REACHED (configured, no answer) or NOT QUERIED (not configured); a live source
  set whose responsibility could not be established at all is NOT SETTLED;
- the QUALIFIERS on an answer that was received, any of ``QUALIFIERS`` in their fixed order: NOT CURRENT (the answer
  does not speak for the flight's window - stale, or retrieved outside the window it could cover), CURRENCY UNKNOWN (no
  retrieval time or flight time to establish it), INCOMPLETE (records that could not be read or evaluated), NOT EVALUATED
  (the route/time/level evaluation could not run), COVERAGE GAP (the source by design does not cover part of the route),
  NOT SETTLED (part of the route's responsibility is unassigned).

The label is the reach followed by its qualifiers ("REACHED · NOT CURRENT"). Only a bare HELD or REACHED is met; every
other label - including any a later build adds - is unmet and is named on page 6 in its own words.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SOURCE_STATUS_VOCABULARY = "source-status-v2"

HELD = "HELD"
NOT_HELD = "NOT HELD"
REACHED = "REACHED"
PARTIAL = "PARTIAL"
NOT_REACHED = "NOT REACHED"
NOT_QUERIED = "NOT QUERIED"
NOT_SETTLED = "NOT SETTLED"

REACHES = (HELD, NOT_HELD, REACHED, PARTIAL, NOT_REACHED, NOT_QUERIED, NOT_SETTLED)
# A qualifier describes an answer that was received; a source with no answer carries none.
ANSWERED = frozenset({HELD, REACHED, PARTIAL})

NOT_CURRENT = "NOT CURRENT"
CURRENCY_UNKNOWN = "CURRENCY UNKNOWN"
INCOMPLETE = "INCOMPLETE"
NOT_EVALUATED = "NOT EVALUATED"
COVERAGE_GAP = "COVERAGE GAP"
QUALIFIERS = (NOT_CURRENT, CURRENCY_UNKNOWN, INCOMPLETE, NOT_EVALUATED, COVERAGE_GAP, NOT_SETTLED)

SEPARATOR = " · "
MET = frozenset({HELD, REACHED})


def source_status(reach: str, qualifiers: Iterable[str] = ()) -> str:
    """The one label for ``reach`` and its ``qualifiers``; anything outside the vocabulary is refused."""
    if reach not in REACHES:
        raise ValueError(f"Unknown source reach: {reach!r}")
    held = set(qualifiers or ())
    unknown = held - set(QUALIFIERS)
    if unknown:
        raise ValueError(f"Unknown source qualifier(s): {sorted(unknown)}")
    if held and reach not in ANSWERED and held != {NOT_SETTLED}:
        # Currency, completeness and evaluation describe an answer; responsibility can be unsettled either way.
        raise ValueError(f"{reach} carries no answer to qualify: {sorted(held)}")
    return SEPARATOR.join([reach, *(q for q in QUALIFIERS if q in held)])


def source_row(source: str, reach: str, qualifiers: Iterable[str], detail: str) -> dict[str, Any]:
    """One source-assurance row: the composed label plus the two facts it was composed from."""
    qualifiers = [q for q in QUALIFIERS if q in set(qualifiers or ())]
    return {
        "source": source,
        "status": source_status(reach, qualifiers),
        "reach": reach,
        "qualifiers": qualifiers,
        "detail": detail,
    }


def source_status_met(status: Any) -> bool:
    """Only a bare HELD or REACHED is met; an unknown or qualified label never is."""
    return str(status or "").strip().upper() in MET


def source_status_words(status: Any) -> str:
    """The label in page-6 words ("REACHED · NOT CURRENT" -> "reached, not current"); never another state's words."""
    label = " ".join(str(status or "").split()).upper()
    if not label:
        return "status not stated"
    return ", ".join(part.strip().lower() for part in label.split("·") if part.strip())


def _utc(value: Any) -> datetime | None:
    text = " ".join(str(value or "").split()).replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.strftime("%d%b %H%MZ")


def flight_window(flight: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Departure (ATOT when held, else scheduled) to arrival (departure plus the last route ACTM, else scheduled)."""
    flight = flight or {}
    departure = _utc(
        flight.get("actual_takeoff_utc")
        or (flight.get("timing_reference") or {}).get("actual_takeoff_utc")
        or flight.get("scheduled_departure_utc")
    )
    if departure is None:
        return None
    minutes = [int(w["actm_minutes"]) for w in flight.get("route_waypoints") or []
               if isinstance(w, dict) and isinstance(w.get("actm_minutes"), (int, float))]
    arrival = departure + timedelta(minutes=max(minutes)) if minutes else _utc(flight.get("scheduled_arrival_utc"))
    if arrival is None or arrival < departure:
        return None
    return departure, arrival


def answer_currency(
    retrieved_at: Any,
    flight: dict[str, Any],
    *,
    lead: timedelta,
    lag: timedelta = timedelta(0),
) -> tuple[str | None, str]:
    """Whether a live answer retrieved at ``retrieved_at`` can speak for the flight: (qualifier or None, words).

    It can when it was retrieved no earlier than ``lead`` before departure and no later than ``lag`` after arrival.
    Without a retrieval or flight time the currency is not established - never assumed."""
    window = flight_window(flight)
    retrieved = _utc(retrieved_at)
    if window is None or retrieved is None:
        missing = "retrieval time" if retrieved is None else "flight time"
        return CURRENCY_UNKNOWN, f"currency not established ({missing} not held)"
    departure, arrival = window
    if retrieved > arrival + lag:
        return NOT_CURRENT, f"not current: retrieved {_stamp(retrieved)}, after the flight ({_stamp(arrival)} arrival)"
    if retrieved < departure - lead:
        return NOT_CURRENT, f"not current: retrieved {_stamp(retrieved)}, too early for {_stamp(departure)} departure"
    return None, ""


__all__ = [
    "ANSWERED", "COVERAGE_GAP", "CURRENCY_UNKNOWN", "HELD", "INCOMPLETE", "MET", "NOT_CURRENT", "NOT_EVALUATED",
    "NOT_HELD", "NOT_QUERIED", "NOT_REACHED", "NOT_SETTLED", "PARTIAL", "QUALIFIERS", "REACHED", "REACHES",
    "SOURCE_STATUS_VOCABULARY", "answer_currency", "flight_window", "source_row", "source_status", "source_status_met", "source_status_words",
]
