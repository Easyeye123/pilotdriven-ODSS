from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    COMMUNICATION_RULES,
    MEL_REFERENCES,
    MONTHS,
    REFERENCE_LIBRARY_METADATA,
    edto_sectors,
    format_actm,
    format_kg,
)

from .controlled_library import (
    CDL_LIBRARY_METADATA,
    CDL_REFERENCES,
    DEPRESS_LIBRARY_METADATA,
    DEPRESS_PROFILES,
    aircraft_effectivity_tokens,
    select_cdl_variants,
)
from .pilot_briefing import (
    concise_weather_finding,
    notam_pertinence,
    notam_sort_key,
    pilot_notam_key,
)
from .reviewed_publications import reviewed_publication_for_notam
from .weather_timing import summarize_metar_for_window, summarize_taf_for_window

_WEEKDAYS = {name: index for index, name in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"))}
_TIME_RANGE = re.compile(r"\b(\d{4})(?:UTC|Z)?\s*(?:-|TO)\s*(\d{4})(?:UTC|Z)?\b")


def finding(
    engine: str,
    severity: str,
    title: str,
    summary: str,
    details: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": f"{engine.upper()}-AUTO",
        "engine": engine,
        "severity": severity,
        "title": title,
        "summary": summary,
        "details": details or [],
        "data": data or {},
    }


def _cfp_source_reference(
    flight: dict[str, Any],
    pages: list[int | None],
    section: str,
) -> dict[str, Any]:
    return {
        "source_type": "uploaded_cfp",
        "document_title": flight.get("document_id") or "Uploaded CFP",
        "display_title": "Uploaded company CFP",
        "pages": sorted(
            {
                int(page)
                for page in pages
                if isinstance(page, int) and page > 0
            }
        ),
        "section": section,
    }


def _weather_source_reference(
    flight: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    page = record.get("source_page")
    if isinstance(page, int) and page > 0:
        return _cfp_source_reference(
            flight,
            [page],
            "Airport weather list",
        )
    return {
        "source_type": record.get("source") or "official_weather",
        "provider": record.get("provider"),
        "display_title": (
            "NOAA Aviation Weather Center"
            if record.get("provider") == "noaa-awc-data-api"
            else None
        ),
        "source_url": record.get("source_url"),
        "retrieved_at_utc": record.get("retrieved_at_utc"),
        "observed_at_utc": record.get("observed_at_utc"),
        "issued_at_utc": record.get("issue_time_utc"),
        "valid_from_utc": record.get("valid_from_utc"),
        "valid_to_utc": record.get("valid_to_utc"),
    }


def _official_weather_review_finding(
    review: dict[str, Any],
) -> dict[str, Any] | None:
    """Surface official-source gaps as weather, never as an invisible ledger."""
    if review.get("status") == "complete":
        return None
    reason_codes = list(review.get("reason_codes") or ["coverage_not_confirmed"])
    human_reasons = {
        "source_disabled": "The official public METAR/TAF connector is disabled.",
        "unsupported_source": "The configured weather source is not approved by this connector.",
        "airport_identifiers_unavailable": "The airport identifiers needed for the public weather lookup are unavailable.",
        "source_unavailable": "The official public METAR/TAF source was unavailable.",
        "source_stale": "The official public METAR/TAF receipt expired and was not used.",
        "essential_forecast_missing": "A departure or destination TAF is missing.",
        "station_product_missing": "One or more requested station products are missing.",
        "essential_forecast_window_not_covered": "A departure or destination TAF does not cover the operating window.",
        "forecast_window_not_covered": "A requested station TAF does not cover its operating window.",
        "coverage_not_confirmed": "Official public weather coverage was not confirmed.",
    }
    products = review.get("products") or {}
    references: list[dict[str, Any]] = []
    for product_name in ("METAR", "TAF"):
        product = products.get(product_name) or {}
        if not product:
            continue
        references.append({
            "source_type": "official_weather",
            "provider": review.get("provider"),
            "display_title": "NOAA Aviation Weather Center",
            "section": product_name,
            "source_url": product.get("source_url"),
            "retrieved_at_utc": product.get("retrieved_at_utc"),
            "valid_from_utc": product.get("effective_start_utc"),
            "valid_to_utc": product.get("effective_end_utc"),
            "availability_status": "source-incomplete",
        })
    return finding(
        "weather",
        "unknown",
        "Official weather source review required",
        "Official public METAR/TAF coverage is incomplete.",
        [
            *(human_reasons.get(code, code.replace("_", " ").capitalize() + ".") for code in reason_codes),
            "Missing, expired or non-covering weather is not a no-significant-weather result.",
        ],
        {
            "phase": "Flight",
            "location": "",
            "utc_window": "Official source coverage check",
            "mechanism": "; ".join(human_reasons.get(code, code.replace("_", " ")) for code in reason_codes),
            "flight_effect": "Review current official operational weather before use.",
            "window_status": "review_required",
            "window_status_text": "Official public weather coverage is incomplete — review required.",
            "provider": review.get("provider"),
            "reason_codes": reason_codes,
            "source_references": references,
        },
    )


# Hazard reviews share one deterministic route x time x flight-level evaluator,
# so they also share one finding shape. Only the wording differs.
_HAZARD_REVIEWS = (
    {
        "review_key": "sigmet_review",
        "engine": "sigmet",
        "affected_title": "SIGMET affects the planned route",
        "review_title": "SIGMET review required",
        "review_summary": (
            "The official source could not fully cover the flight window."
        ),
        "record_phrase": "SIGMET",
        "cfp_phrase": "SIGMET",
        "negative_claim": "no SIGMET",
        "unresolved_warning": (
            "SIGMET applicability remains unresolved; "
            "review the current official source."
        ),
    },
    {
        "review_key": "vaa_review",
        "engine": "vaa",
        "affected_title": "Volcanic ash affects the planned route",
        "review_title": "Volcanic ash review required",
        "review_summary": (
            "The official sources could not safely confirm that volcanic ash "
            "is not applicable to the route."
        ),
        "record_phrase": "volcanic-ash",
        "cfp_phrase": "volcanic-ash",
        "negative_claim": "no volcanic ash",
        "unresolved_warning": (
            "Volcanic ash applicability remains unresolved; "
            "review the current official advisory source."
        ),
    },
    {
        "review_key": "tropical_cyclone_review",
        "engine": "tropical_cyclone",
        "affected_title": "Tropical cyclone affects the planned route",
        "review_title": "Tropical cyclone review required",
        "review_summary": (
            "The official sources could not safely confirm that a tropical "
            "cyclone is not applicable to the route."
        ),
        "record_phrase": "tropical-cyclone",
        "cfp_phrase": "tropical-cyclone",
        "negative_claim": "no tropical cyclone",
        "unresolved_warning": (
            "Tropical cyclone applicability remains unresolved; "
            "review the current official advisory source."
        ),
    },
)


def _hazard_review_findings(
    review: dict[str, Any],
    hazard: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build findings for one hazard review without interpreting the hazard."""
    track_context = (
        review.get("track_context") or {}
        if hazard["engine"] == "tropical_cyclone"
        else {}
    )

    def source_references() -> list[dict[str, Any]]:
        snapshot = review.get("source_snapshot") or {}
        provider = review.get("provider") or snapshot.get("provider")
        if not provider:
            return []
        return [{
            "source_type": "official_advisory",
            "provider": provider,
            "retrieved_at_utc": (
                review.get("retrieved_at_utc")
                or snapshot.get("retrieved_at_utc")
            ),
            "valid_from_utc": (
                snapshot.get("effective_start_utc")
                or snapshot.get("coverage_start_utc")
            ),
            "valid_to_utc": (
                snapshot.get("effective_end_utc")
                or snapshot.get("coverage_end_utc")
            ),
            "availability_status": (
                "source-incomplete"
                if review.get("status") == "review_required"
                else "available"
            ),
        }]

    def track_details() -> list[str]:
        details: list[str] = []
        for cyclone in (track_context.get("cyclones") or [])[:3]:
            movement = cyclone.get("movement") or {}
            closest = cyclone.get("closest_route_screening") or {}
            if movement:
                details.append(
                    f"{cyclone.get('name') or cyclone.get('cyclone_id') or 'Cyclone'} "
                    f"centre movement: {movement.get('bearing_degrees')}° at "
                    f"{movement.get('speed_knots')} kt, based on official timed positions."
                )
            if closest:
                details.append(
                    f"Centre-track screening: {closest.get('distance_nm')} NM from "
                    f"{closest.get('route_from')}-{closest.get('route_to')} at "
                    f"{closest.get('time_utc')}; ODSS interpolation, not an official "
                    "hazard boundary."
                )
        if track_context.get("status") == "review_required":
            details.append(
                "Official tropical-cyclone centre-track context was unavailable; "
                "review the responsible meteorological authority."
            )
        return details

    status = review.get("status")
    if status == "affected":
        matches = review.get("matches") or []
        first_match = matches[0] if matches else {}
        details = [
            (
                f"{item.get('hazard_code') or 'SIGMET'} "
                f"{item.get('advisory_id')}: {item.get('route_from')}-"
                f"{item.get('route_to')} at FL{item.get('planned_flight_level')}, "
                f"{item.get('segment_start_utc')} to {item.get('segment_end_utc')}."
            )
            for item in matches[:8]
        ]
        details.append(
            "Boundary contact is treated as an intersection; verify the "
            "original advisory and dispatch guidance."
        )
        details.extend(track_details())
        return [finding(
            hazard["engine"],
            "critical",
            hazard["affected_title"],
            f"{len(matches)} route/time/flight-level intersection(s) verified.",
            details,
            {
                "status": "affected",
                "start_actm_minutes": first_match.get("start_actm_minutes"),
                "match_count": len(matches),
                "provider": review.get("provider"),
                "reason_codes": review.get("reason_codes") or [],
                "source_references": source_references(),
            },
        )], []

    if status != "review_required":
        return [], []
    if review.get("clean_current_feed_no_match"):
        return [], []

    reason_codes = review.get("reason_codes") or []
    human_reasons = {
        "source_unavailable": "The official live source was unavailable.",
        "source_stale": "The source snapshot did not meet the configured freshness limit.",
        "source_records_incomplete": (
            f"Some official {hazard['record_phrase']} records could not be read "
            "completely; review required."
        ),
        "coverage_not_complete_for_flight": (
            "Official-source coverage is incomplete for the flight window."
        ),
        "cfp_weather_data_unavailable": (
            f"The CFP states that {hazard['cfp_phrase']} weather data is unavailable."
        ),
        "route_geometry_unavailable": "The CFP route geometry is incomplete.",
        "route_timing_unavailable": "The route timing anchor is unavailable.",
        "flight_level_unavailable": "The planned flight level could not be resolved.",
        "flight_level_change_unresolved": "A planned level-change waypoint could not be matched to the route.",
        "advisory_geometry_invalid": "An advisory geometry could not be evaluated safely.",
        "direct_vaac_advisory_source_not_mounted": (
            "The responsible VAAC advisory and VAG source is not mounted."
        ),
        "direct_vaac_advisory_source_unavailable": (
            "The configured responsible VAAC advisory source was unavailable."
        ),
        "direct_vaac_coverage_partial": (
            "The checked VAAC source does not cover every responsible VAAC for "
            "the route."
        ),
        "direct_tca_advisory_source_not_mounted": (
            "The responsible tropical-cyclone advisory and wind-field source is "
            "not mounted."
        ),
    }
    details = [human_reasons.get(code, code.replace("_", " ").capitalize() + ".") for code in reason_codes]
    details.append(
        f"Incomplete coverage is not a '{hazard['negative_claim']}' result; "
        "complete the advisory review."
    )
    details.extend(track_details())
    return [finding(
        hazard["engine"],
        "unknown",
        hazard["review_title"],
        hazard["review_summary"],
        details,
        {
            "status": "review_required",
            "provider": review.get("provider"),
            "reason_codes": reason_codes,
            "source_references": source_references(),
        },
    )], [hazard["unresolved_warning"]]


def _switch_state(value: bool | None) -> str:
    if value is True:
        return "ON"
    if value is False:
        return "OFF"
    return "not parsed"


def _reference_library_is_approved() -> bool:
    return str(REFERENCE_LIBRARY_METADATA.get("status") or "").lower() in {
        "approved",
        "approved-current",
        "current-approved",
    }


def _intervals_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start < second_end and second_start < first_end


def _minute_of_day(value: str) -> int | None:
    hour = int(value[:2])
    minute = int(value[2:])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _schedule_weekdays(value: str) -> set[int] | None:
    weekday = r"MON|TUE|WED|THU|FRI|SAT|SUN"
    normalized = re.sub(r"\s*,\s*", " ", value.strip())
    range_match = re.fullmatch(rf"({weekday})-({weekday})", normalized)
    if range_match:
        start = _WEEKDAYS[range_match.group(1)]
        end = _WEEKDAYS[range_match.group(2)]
        result = {start}
        while start != end:
            start = (start + 1) % 7
            result.add(start)
        return result
    if not re.fullmatch(rf"(?:{weekday})(?:\s+(?:{weekday}))*", normalized):
        return None
    tokens = re.findall(weekday, normalized)
    return {_WEEKDAYS[token] for token in tokens}


def _schedule_overlaps(schedule: str, window_start: datetime, window_end: datetime) -> bool | None:
    months = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
    normalized = re.sub(rf",\s*(?=(?:{months})\b)", ";", schedule.upper())
    entries = [entry.strip() for entry in normalized.split(";") if entry.strip()]
    if not entries:
        return None
    parsed_entries = 0
    first_day = (window_start - timedelta(days=1)).date()
    day_count = (window_end.date() - first_day).days + 1
    for entry in entries:
        matches = list(_TIME_RANGE.finditer(entry))
        if not matches:
            return None
        gaps = [entry[matches[index].end():matches[index + 1].start()] for index in range(len(matches) - 1)]
        gaps.append(entry[matches[-1].end():])
        if any(not re.fullmatch(r"[\s,/]*", gap) for gap in gaps):
            return None
        ranges = []
        for match in matches:
            start_minutes = _minute_of_day(match.group(1))
            end_minutes = _minute_of_day(match.group(2))
            if start_minutes is None or end_minutes is None:
                return None
            ranges.append((start_minutes, end_minutes))
        prefix = entry[:matches[0].start()].strip(" ,")
        date_match = re.fullmatch(rf"({months})\s+(.+)", prefix)
        month_days: set[int] | None = None
        month_number = None
        if date_match:
            month_number = MONTHS[date_match.group(1)]
            date_expression = date_match.group(2)
            if not re.fullmatch(r"\d{2}(?:-\d{2})?(?:[ ,]+\d{2}(?:-\d{2})?)*", date_expression):
                return None
            month_days = set()
            for token in re.findall(r"\d{2}(?:-\d{2})?", date_expression):
                if "-" in token:
                    start_day, end_day = (int(value) for value in token.split("-", 1))
                    if start_day > end_day:
                        return None
                    month_days.update(range(start_day, end_day + 1))
                else:
                    month_days.add(int(token))
            if not month_days:
                return None
        daily = prefix in {"DAILY", "DLY"}
        weekdays = None if daily or date_match else _schedule_weekdays(prefix)
        if not daily and not date_match and weekdays is None:
            return None
        parsed_entries += 1
        for offset in range(day_count):
            day = first_day + timedelta(days=offset)
            if date_match and (day.month != month_number or day.day not in month_days):
                continue
            if weekdays is not None and day.weekday() not in weekdays:
                continue
            for start_minutes, end_minutes in ranges:
                occurrence_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=start_minutes)
                occurrence_end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=end_minutes)
                if end_minutes <= start_minutes:
                    occurrence_end += timedelta(days=1)
                if _intervals_overlap(occurrence_start, occurrence_end, window_start, window_end):
                    return True
    return False if parsed_entries == len(entries) else None


def _notam_role_window(
    flight: dict[str, Any],
    location: str,
    alternate_airports: set[str],
    edto_periods: dict[str, tuple[datetime, datetime]],
) -> tuple[str, datetime, datetime]:
    departure_utc = datetime.fromisoformat(flight["scheduled_departure_utc"])
    arrival_utc = datetime.fromisoformat(flight["scheduled_arrival_utc"])
    departure_margin = timedelta(
        minutes=_configured_window_minutes("ODSS_NOTAM_DEPARTURE_WINDOW_MINUTES", 60)
    )
    arrival_margin = timedelta(
        minutes=_configured_window_minutes("ODSS_NOTAM_ARRIVAL_WINDOW_MINUTES", 120)
    )
    if location == flight["departure"]:
        return "departure", departure_utc - departure_margin, departure_utc + departure_margin
    if location == flight["destination"]:
        return "destination", arrival_utc - arrival_margin, arrival_utc + arrival_margin
    if location in alternate_airports:
        return "destination alternate", arrival_utc - arrival_margin, arrival_utc + arrival_margin
    if location in edto_periods:
        starts_at, ends_at = edto_periods[location]
        return "EDTO", starts_at, ends_at
    return "informational", departure_utc, arrival_utc


def _utc_window_label(window_start: datetime, window_end: datetime) -> str:
    start = window_start.astimezone(timezone.utc)
    end = window_end.astimezone(timezone.utc)
    if start.date() == end.date():
        return f"{start:%d %b %H%MZ}-{end:%H%MZ}".upper()
    return f"{start:%d %b %H%MZ}-{end:%d %b %H%MZ}".upper()


def _notam_reference_at(
    flight: dict[str, Any],
    role: str,
    window_start: datetime,
) -> datetime:
    if role == "departure":
        return datetime.fromisoformat(flight["scheduled_departure_utc"])
    if role in {"destination", "destination alternate"}:
        return datetime.fromisoformat(flight["scheduled_arrival_utc"])
    # EDTO windows use sector entry as their operational reference. Enroute
    # informational records use the beginning of the checked flight window.
    return window_start


def _notam_reference_state(
    record: dict[str, Any],
    reference_at: datetime,
    valid_from: datetime,
    valid_to: datetime,
) -> tuple[str, int | None]:
    if record.get("validity_review"):
        return "unknown_at_reference", None
    if reference_at < valid_from:
        return (
            "begins_after_reference",
            round((valid_from - reference_at).total_seconds() / 60),
        )
    if reference_at >= valid_to:
        return (
            "ended_before_reference",
            round((reference_at - valid_to).total_seconds() / 60),
        )

    schedule = record.get("schedule")
    if schedule:
        active_at_reference = _schedule_overlaps(
            schedule,
            reference_at,
            reference_at + timedelta(minutes=1),
        )
        if active_at_reference is not True:
            return "unknown_at_reference", None
    elif record.get("schedule_review"):
        return "unknown_at_reference", None
    return "active_at_reference", 0


def _weather_role_window(
    flight: dict[str, Any],
    location: str,
    alternate_airports: set[str],
    edto_periods: dict[str, tuple[datetime, datetime]],
) -> tuple[str, datetime, datetime]:
    departure_utc = datetime.fromisoformat(flight["scheduled_departure_utc"])
    arrival_utc = datetime.fromisoformat(flight["scheduled_arrival_utc"])
    preference = _weather_window_preference(flight)
    before = timedelta(minutes=preference["before_minutes"])
    after = timedelta(minutes=preference["after_minutes"])
    if location == flight["departure"]:
        return "Departure", departure_utc - before, departure_utc + after
    if location == flight["destination"]:
        return "Destination", arrival_utc - before, arrival_utc + after
    if location in alternate_airports:
        return "Destination alternate", arrival_utc - before, arrival_utc + after
    if location in edto_periods:
        starts_at, ends_at = edto_periods[location]
        return "EDTO", starts_at, ends_at
    return "Enroute", departure_utc, arrival_utc


def _compact_taxiway_identifiers(identifiers: list[str]) -> list[str]:
    """Compress a published taxiway list without inventing missing members."""

    ordered_prefixes: list[str] = []
    bare: set[str] = set()
    numbers: dict[str, set[int]] = {}
    for identifier in identifiers:
        match = re.fullmatch(r"([A-Z])(\d{1,2})?", identifier)
        if not match:
            continue
        prefix, number = match.groups()
        if prefix not in ordered_prefixes:
            ordered_prefixes.append(prefix)
        if number is None:
            bare.add(prefix)
        else:
            numbers.setdefault(prefix, set()).add(int(number))

    compact: list[str] = []
    for prefix in ordered_prefixes:
        if prefix in bare:
            compact.append(prefix)
        values = sorted(numbers.get(prefix, set()))
        start = end = None
        for value in [*values, None]:
            if value is not None and start is None:
                start = end = value
                continue
            if value is not None and end is not None and value == end + 1:
                end = value
                continue
            if start is not None and end is not None:
                compact.append(
                    f"{prefix}{start}-{prefix}{end}"
                    if end > start
                    else f"{prefix}{start}"
                )
            start = end = value
    return compact


def _associated_taxiway_subject(upper: str) -> str | None:
    """Summarise a tabulated associated-taxiway closure from its actual list."""

    if not re.search(
        r"\bCLOSURE\s+OF\s+(?:TWY|TAXIWAY)\s+ASSOCIATED\s+WITH\s+(?:RWY|RUNWAY)\s*\d{1,2}[LCR]?/\d{1,2}[LCR]?\b",
        upper,
    ):
        return None
    listed = re.search(
        r"\bTWY\s+CLOSURE\s+PERIOD:.*?\b\d{4}UTC\s+"
        r"(?P<list>TWY\s+.+?)(?:\s+ALL\s+MARKINGS|\Z)",
        upper,
    )
    if not listed:
        runway = re.search(r"\b(?:RWY|RUNWAY)\s*(\d{1,2}[LCR]?/\d{1,2}[LCR]?)", upper)
        return f"listed TWYs associated with RWY {runway.group(1)}" if runway else None

    list_text = listed.group("list")
    between = re.search(
        r"\bTWY\s+([A-Z]\d{0,2})\s+BTN\s+TWY\s+([A-Z]\d{0,2})\s+([A-Z]\d{0,2})\b",
        list_text,
    )
    between_label = None
    if between:
        between_label = (
            f"{between.group(1)} between {between.group(2)} and {between.group(3)}"
        )
        list_text = f"{list_text[:between.start()]} {list_text[between.end():]}"

    identifiers: list[str] = []
    for group in re.findall(r"\bTWY\s+(.+?)(?=\s+TWY\s+|\Z)", list_text):
        identifiers.extend(re.findall(r"\b[A-Z](?:\d{1,2})?\b", group))
    compact = _compact_taxiway_identifiers(identifiers)
    if between_label:
        compact.append(between_label)
    if not compact:
        return None
    if len(compact) == 1:
        joined = compact[0]
    else:
        joined = f"{', '.join(compact[:-1])}, and {compact[-1]}"
    return f"TWYs {joined}"


def _notam_subject(text: str, kind: str) -> str:
    upper = " ".join(text.upper().split())
    runway_pattern = r"(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?(?:/\d{1,2}[LCR]?)?"
    taxiway_pattern = r"(?:TWY|TAXIWAY)\s+[A-Z0-9][A-Z0-9/-]*"
    closure_pattern = r"(?:CLSD|CLOSED|NOT\s+AVBL|NOT\s+AVAILABLE|SUSPENDED)"
    if kind == "runway_closure":
        match = (
            re.search(
                rf"\b({runway_pattern})\s+(?:WILL\s+BE\s+|IS\s+)?{closure_pattern}\b",
                upper,
            )
            or re.search(rf"\bCLOSURE\s+OF\s+({runway_pattern})\b", upper)
        )
        return match.group(1).replace("RUNWAY", "RWY") if match else "runway"
    if kind in {"runway_approach_restriction", "runway_lighting_restriction"}:
        match = re.search(rf"\b{runway_pattern}\b", upper)
        return match.group(0).replace("RUNWAY", "RWY") if match else "runway"
    if kind == "approach_navaid_closure":
        system = re.search(
            r"\b(?:ILS|LOC|LOCALIZER|GLIDE\s*PATH|GLIDESLOPE|DME|VOR|NDB|RNP|PAPI)\b",
            upper,
        )
        runway = re.search(r"\b(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?\b", upper)
        parts = [
            system.group(0).replace("LOCALIZER", "LOC").replace("RUNWAY", "RWY")
            if system
            else "approach/navaid",
            runway.group(0).replace("RUNWAY", "RWY") if runway else "",
        ]
        return " ".join(part for part in parts if part)
    if kind in {"taxiway_closure", "taxiway_restriction"}:
        compound = re.search(
            r"\b(?:TWY|TAXIWAY)\s+(?P<closed>[A-Z0-9][A-Z0-9/-]*)\s+AND\s+"
            r"(?:THE\s+)?JUNCTION\s+OF\s+(?:TWY|TAXIWAY)\s+(?P=closed)[,\s]+"
            r"(?:TWY|TAXIWAY)\s+(?P<left>[A-Z0-9][A-Z0-9/-]*)\s+AND\s+"
            r"(?:TWY|TAXIWAY)\s+(?P<right>[A-Z0-9][A-Z0-9/-]*)\b",
            upper,
        )
        if compound:
            return (
                f"TWY {compound.group('closed')} and "
                f"{compound.group('closed')}/{compound.group('left')}/{compound.group('right')} junction"
            )
        associated = _associated_taxiway_subject(upper)
        if associated:
            return associated
        bounded = re.search(
            r"\b(?:TWY|TAXIWAY)\s+(?P<name>[A-Z][A-Z0-9/-]*)\s+BTN\s+"
            r"(?:TWY|TAXIWAY)\s+(?P<start>[A-Z][A-Z0-9/-]*)\s+AND\s+"
            r"(?:(?:TWY|TAXIWAY)\s+)?(?P<end>[A-Z][A-Z0-9/-]*)\b",
            upper,
        )
        if bounded:
            return (
                f"TWY {bounded.group('name')} between "
                f"{bounded.group('start')} and {bounded.group('end')}"
            )
        invalid_identifiers = {
            "AND",
            "ASSOCIATED",
            "CLSD",
            "CLOSED",
            "CLOSURE",
            "INDICATOR",
            "IS",
            "LIGHT",
            "LIGHTS",
            "MARKINGS",
            "PAVEMENT",
            "WILL",
            "WITH",
        }
        for match in re.finditer(
            r"\b(?:TWY|TAXIWAY)\s+(?P<identifier>[A-Z][A-Z0-9/-]*)\b",
            upper,
        ):
            identifier = match.group("identifier")
            if identifier not in invalid_identifiers:
                return f"TWY {identifier}"
        phonetic = re.search(r"\b([A-Z]{2,})\s+TWY\b", upper)
        turnoffs = re.search(
            r"\bHIGH-SPEED\s+TURN-OFFS?\s+([A-Z]\d{1,2})\s+AND\s+([A-Z]\d{1,2})\b",
            upper,
        )
        if phonetic and turnoffs:
            return (
                f"{phonetic.group(1).title()} TWY segment and "
                f"{turnoffs.group(1)}/{turnoffs.group(2)} high-speed turn-offs"
            )
        if phonetic:
            return f"{phonetic.group(1).title()} TWY segment"
        if turnoffs:
            return f"{turnoffs.group(1)}/{turnoffs.group(2)} high-speed turn-offs"
        return "taxiway operational area"
    if kind == "apron_stand_closure":
        match = re.search(
            r"\b(?:ACFT\s+STAND|STAND|APRON|APN|RAMP|GATE)\s+[A-Z0-9][A-Z0-9/-]*\b",
            upper,
        )
        return match.group(0).replace("APN", "APRON") if match else "apron or stand"
    return ""


def _notam_operational_summary(
    text: str,
    kind: str,
    role: str,
    applicability: str = "active",
) -> str:
    upper = " ".join(text.upper().split())
    if kind == "taxiway_restriction" and "CONSTRUCTION SURVEY LASER" in upper:
        taxilanes: list[str] = []
        for group in re.findall(r"\bTAXILANE\s+((?:[A-Z]\d+(?:,\s*|\s+AND\s+)?)+)", upper):
            for identifier in re.findall(r"\b[A-Z]\d+\b", group):
                if identifier not in taxilanes:
                    taxilanes.append(identifier)
        locations = "/".join(taxilanes) if taxilanes else "the published taxilanes"
        phase = role.replace("destination alternate", "alternate").replace("informational", "flight")
        return (
            f"Construction survey lasers near taxilanes {locations} require "
            f"operational review during the applicable {phase} window."
        )
    subject = _notam_subject(text, kind)
    phase = role.replace("destination alternate", "alternate").replace("informational", "flight")
    if applicability == "review":
        return (
            f"Published {subject or 'airport'} restriction could not be resolved "
            f"for the applicable {phase} window; review required."
        )
    if kind == "airport_closure":
        return f"Entire airport closed or unavailable during the applicable {phase} window."
    if kind == "runway_closure":
        return f"{subject.title()} closed or unavailable during the applicable {phase} window."
    if kind == "approach_navaid_closure":
        return f"{subject} unavailable during the applicable {phase} window."
    if kind == "runway_approach_restriction":
        return f"{subject.title()} restriction applies during the applicable {phase} window."
    if kind == "runway_lighting_restriction":
        return f"Lighting affecting {subject.upper()} is unavailable during the applicable {phase} window."
    if kind == "taxiway_closure":
        return f"{subject.upper()} closed during the applicable {phase} window."
    if kind == "taxiway_restriction":
        return f"{subject.upper()} restriction applies during the applicable {phase} window."
    if kind == "apron_stand_closure":
        return f"{subject.upper()} closed during the applicable {phase} window."
    if kind == "obstacle":
        return (
            f"Obstacle or crane affects the {phase} airport environment; "
            "assess against expected runway and approach use."
        )
    return f"Operational airport restriction requires review during the applicable {phase} window."


def taxiway_operational_details(text: str, kind: str) -> list[str]:
    """Structure bounded visual-aid facts explicitly present in taxiway text."""

    if kind not in {"taxiway_closure", "taxiway_restriction"}:
        return []
    raw = " ".join(str(text or "").upper().split())
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<=[.!?])\s+", raw)
        if clause.strip()
    ]

    def clause_matches(*patterns: str) -> bool:
        closed_taxiway = (
            r"(?:\b(?:CLSD|CLOSED)\s+(?:TWY|TAXIWAY)\b|"
            r"\b(?:TWY|TAXIWAY)(?:\s+[A-Z0-9/-]+)?\s+"
            r"(?:CLSD|CLOSED)\b)"
        )
        return any(
            re.search(closed_taxiway, clause)
            and all(re.search(pattern, clause) for pattern in patterns)
            for clause in clauses
        )

    details: list[str] = []
    if clause_matches(
        r"\bMARKINGS?\b",
        r"\bLEAD(?:ING)?\b",
        r"\bINTO\b",
        r"\bREMOV(?:E|ED|AL)?\b",
    ):
        details.append("lead_in_markings_removed")
    if clause_matches(
        r"\bMARKERBOARDS?\b",
        r"\b(?:CLSD|CLOSED)\s+MARKINGS?\b",
        r"\bYELLOW\s+CROSS(?:ES)?\b",
        r"\bDEMARCATE\b",
    ):
        details.append("markerboards_yellow_cross")
    if clause_matches(
        r"\bUNSERVICEABILITY\s+MARKERS?\b",
        r"\bFIXED\s+RED\s+(?:LGT|LGTS|LIGHT|LIGHTS)\b",
        r"\b(?:LGTD|LIT|LIGHTED)\b",
        r"\b(?:NGT|NIGHT)\b",
        r"\bLOW\s+VIS(?:IBILITY|\s+COND(?:ITIONS?)?)?\b",
    ):
        details.append("marker_red_lights")
    if clause_matches(
        r"\b(?:TWY\s+CL\s+LGT|TAXIWAY\s+(?:CENTRELINE|CENTERLINE)\s+LIGHTS?)\b",
        r"\bLEAD(?:ING)?\b",
        r"\bINTO\b",
        r"\b(?:WI|WITHIN)\b",
        r"\bNOT\s+(?:BE\s+)?IN\s+USE\b",
    ):
        details.append("centreline_lights_out")
    return details


def _configured_window_minutes(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number of minutes.") from exc
    if not 0 <= minutes <= 720:
        raise ValueError(f"{name} must be between 0 and 720 minutes.")
    return minutes


def _weather_window_preference(flight: dict[str, Any]) -> dict[str, Any]:
    raw = flight.get("weather_window_preference")
    supplied = raw if isinstance(raw, dict) else {}

    def selected(key: str, environment_name: str) -> int:
        value = supplied.get(key)
        if value is None:
            return _configured_window_minutes(environment_name, 60)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"weather_window_preference.{key} must be whole minutes.")
        if not 0 <= value <= 720:
            raise ValueError(
                f"weather_window_preference.{key} must be between 0 and 720 minutes."
            )
        return value

    normalized = {
        "before_minutes": selected(
            "before_minutes",
            "ODSS_WEATHER_WINDOW_BEFORE_MINUTES",
        ),
        "after_minutes": selected(
            "after_minutes",
            "ODSS_WEATHER_WINDOW_AFTER_MINUTES",
        ),
        "basis": "scheduled_phase_reference",
    }
    flight["weather_window_preference"] = normalized
    return normalized


def _profile_applies_to_aircraft(
    profile: dict[str, Any],
    registration: str | None,
    aircraft_type: str | None,
) -> bool:
    effectivity = {
        re.sub(r"[^A-Z0-9]", "", str(value).upper())
        for value in profile.get("effectivity", [])
        if value
    }
    if not effectivity or "ALL" in effectivity:
        return True
    return bool(effectivity & aircraft_effectivity_tokens(registration, aircraft_type))


def terrain_event_identity(event: dict[str, Any]) -> str:
    """Return a stable, human-auditable identity for one MSA exposure window."""

    first = event.get("first_high") or {}
    last = event.get("last_high") or first

    def anchor(point: dict[str, Any]) -> str:
        name = str(point.get("name") or "UNKNOWN").lstrip("-").upper()
        actm = point.get("actm_minutes")
        return f"{name}@{actm if actm is not None else 'NA'}"

    return f"terrain:{anchor(first)}-{anchor(last)}"


def _terrain_event(
    *,
    preceding: dict[str, Any] | None,
    active: list[dict[str, Any]],
    drop: dict[str, Any] | None,
) -> dict[str, Any]:
    event = {
        "preceding": preceding,
        "first_high": active[0],
        "last_high": active[-1],
        "drop": drop,
        "maximum": max(active, key=lambda w: w.get("msa_hundreds_ft") or -1),
    }
    event["terrain_event_id"] = terrain_event_identity(event)
    return event


def detect_terrain_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    preceding = None
    last_msa = None
    for waypoint in waypoints:
        msa = waypoint.get("msa_hundreds_ft")
        if msa is None:
            continue
        # Strict v1.3 trigger: only MSA strictly above 10,000 ft qualifies.
        # An exact 100* value is a boundary row - it terminates an active
        # exposure (becoming its drop point) and never starts one.
        if msa > 100:
            if not active:
                preceding = last_msa
            active.append(waypoint)
        elif active:
            events.append(
                _terrain_event(
                    preceding=preceding,
                    active=active,
                    drop=waypoint,
                )
            )
            active = []
            preceding = None
        last_msa = waypoint
    if active:
        events.append(
            _terrain_event(
                preceding=preceding,
                active=active,
                drop=None,
            )
        )
    return events


def detect_vws_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for waypoint in waypoints:
        vws = waypoint.get("vws")
        if vws is None:
            if active and not waypoint.get("fir_boundary"):
                events.append({
                    "first_high": active[0],
                    "last_high": active[-1],
                    "drop": waypoint,
                    "maximum": max(active, key=lambda w: w.get("vws") or -1),
                })
                active = []
            continue
        if vws > 4:
            active.append(waypoint)
        elif active:
            events.append({
                "first_high": active[0],
                "last_high": active[-1],
                "drop": waypoint,
                "maximum": max(active, key=lambda w: w.get("vws") or -1),
            })
            active = []
    if active:
        events.append({
            "first_high": active[0],
            "last_high": active[-1],
            "drop": None,
            "maximum": max(active, key=lambda w: w.get("vws") or -1),
        })
    return events


def _subsequence(sequence: list[str], candidate: list[str]) -> bool:
    if not candidate:
        return True

    def aliases(value: str) -> set[str]:
        values: set[str] = set()
        for part in str(value or "").upper().replace(" ", "").split("/"):
            if not part:
                continue
            values.add(part)
            if re.fullmatch(r"U[A-Z]{1,2}\d+", part):
                values.add(part[1:])
        return values

    position = 0
    for item in sequence:
        if aliases(item) & aliases(candidate[position]):
            position += 1
            if position == len(candidate):
                return True
    return False


def _route_waypoint_name(waypoint: dict[str, Any]) -> str:
    return str(waypoint.get("name") or "").lstrip("-").upper()


def _profile_aliases(profile: dict[str, Any], field: str) -> set[str]:
    fallback = str(profile.get(field) or "").upper()
    return {
        str(value).lstrip("-").upper()
        for value in profile.get(f"{field}_aliases", [fallback])
        if value
    }


def _route_airways_between(
    waypoints: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> list[str]:
    return [
        str(waypoints[index].get("airway_in") or "").upper()
        for index in range(start_index + 1, end_index + 1)
        if waypoints[index].get("airway_in")
    ]


def _profile_route_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    published_airways = [str(value).upper() for value in profile.get("airways", [])]
    spans: list[dict[str, Any]] = []
    for from_index, name in enumerate(names):
        if name not in from_aliases:
            continue
        for to_index, to_name in enumerate(names):
            if to_name not in to_aliases or to_index == from_index:
                continue
            if from_index < to_index:
                start_index, end_index = from_index, to_index
                expected_airways = published_airways
                direction = "forward"
            else:
                start_index, end_index = to_index, from_index
                expected_airways = list(reversed(published_airways))
                direction = "reverse"
            route_airways = _route_airways_between(waypoints, start_index, end_index)
            if expected_airways:
                candidate_orders = [
                    expected_airways,
                    list(reversed(expected_airways)),
                ]
                matched_order = next(
                    (
                        order
                        for order in candidate_orders
                        if _subsequence(route_airways, order)
                    ),
                    None,
                )
                if matched_order is None:
                    continue
                expected_airways = matched_order
            spans.append(
                {
                    "start_index": start_index,
                    "end_index": end_index,
                    "route_start": names[start_index],
                    "route_end": names[end_index],
                    "airways": expected_airways,
                    "route_airways": route_airways,
                    "direction": direction,
                    "match_class": "published-route",
                }
            )
    return spans


def _airway_alias_tokens(values: list[Any]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for part in str(value or "").upper().replace(" ", "").split("/"):
            if not part:
                continue
            tokens.add(part)
            if re.fullmatch(r"U[A-Z]{1,2}\d+", part):
                tokens.add(part[1:])
    return tokens


def _corridor_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Single-endpoint subsegment coverage along the chart's published corridor.

    A chart whose route shares only one endpoint with the filed route still
    protects the filed legs that run between the chart's own published points
    (from, critical point, to) on the chart's published airways. The span is
    bounded by the outermost chart points that are filed waypoints, so a chart
    never extends past its own corridor onto same-named airway legs elsewhere
    (the approved v1.3 example: chart 8-5 covers MATAL-TEMEL on SQ352 but must
    not reach the separate ALUVO exposure east of its critical point, and
    chart 8-7 is not promoted because its published leg adjacent to the shared
    endpoint is a different airway than the filed leg).
    """
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    critical_aliases = _profile_aliases(profile, "critical")
    has_from = any(name in from_aliases for name in names)
    has_to = any(name in to_aliases for name in names)
    if has_from and has_to:
        # Both endpoints filed: the published-route span logic owns this chart.
        return []
    airway_tokens = _airway_alias_tokens(profile.get("airways", []))
    if not airway_tokens:
        return []
    ordered_groups: list[set[str]] = [from_aliases, critical_aliases, to_aliases]
    filed_points: list[tuple[int, int]] = []
    for chart_position, aliases in enumerate(ordered_groups):
        for index, name in enumerate(names):
            if name and name in aliases:
                filed_points.append((index, chart_position))
    if len({position for _, position in filed_points}) < 2:
        return []
    filed_points.sort()
    chart_positions = [position for _, position in filed_points]
    ascending = all(a <= b for a, b in zip(chart_positions, chart_positions[1:]))
    descending = all(a >= b for a, b in zip(chart_positions, chart_positions[1:]))
    if not ascending and not descending:
        return []
    start_index = filed_points[0][0]
    end_index = filed_points[-1][0]
    if end_index <= start_index:
        return []
    route_airways: list[str] = []
    for index in range(start_index + 1, end_index + 1):
        airway = waypoints[index].get("airway_in")
        if not airway:
            # FIR-boundary annotation rows carry no leg of their own.
            continue
        if not (_airway_alias_tokens([airway]) & airway_tokens):
            return []
        route_airways.append(str(airway).upper())
    if not route_airways:
        return []
    return [
        {
            "start_index": start_index,
            "end_index": end_index,
            "route_start": names[start_index],
            "route_end": names[end_index],
            "airways": [str(value).upper() for value in profile.get("airways", [])],
            "route_airways": route_airways,
            "direction": "forward" if ascending else "reverse",
            "match_class": "corridor-subsegment",
        }
    ]


def match_profiles(
    flight: dict[str, Any],
    terrain_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waypoints = flight["route_waypoints"]
    matches: list[dict[str, Any]] = []
    for event in terrain_events:
        # Coverage is judged against the actual exposure legs (first to last
        # high waypoint); the preceding point is route context only (v1.3).
        event_start_index = waypoints.index(event["first_high"])
        event_end_index = waypoints.index(event["last_high"])
        required_edges = set(range(event_start_index, event_end_index))
        if not required_edges:
            required_edges = {event_start_index}

        candidate_by_chart: dict[str, dict[str, Any]] = {}
        for profile in DEPRESS_PROFILES:
            if not _profile_applies_to_aircraft(
                profile,
                flight.get("registration"),
                flight.get("aircraft_type"),
            ):
                continue
            for span in (
                _profile_route_spans(profile, waypoints)
                + _corridor_spans(profile, waypoints)
            ):
                if event_end_index == event_start_index:
                    covered = (
                        {event_start_index}
                        if span["start_index"] <= event_start_index <= span["end_index"]
                        else set()
                    )
                else:
                    covered = set(
                        range(
                            max(span["start_index"], event_start_index),
                            min(span["end_index"], event_end_index),
                        )
                    )
                if not covered:
                    continue
                candidate = {
                    **span,
                    "event": event,
                    "profile": profile,
                    "covered_edges": covered,
                }
                chart = str(profile.get("chart") or "")
                current = candidate_by_chart.get(chart)

                def _score(item: dict[str, Any]) -> tuple[int, int, int]:
                    class_rank = (
                        1 if item.get("match_class") == "published-route" else 0
                    )
                    return (
                        class_rank,
                        len(item["covered_edges"]),
                        -(item["end_index"] - item["start_index"]),
                    )

                if current is None or _score(candidate) > _score(current):
                    candidate_by_chart[chart] = candidate

        uncovered = set(required_edges)
        available = list(candidate_by_chart.values())
        selected: list[dict[str, Any]] = []
        while uncovered:
            useful = [
                (len(item["covered_edges"] & uncovered), item)
                for item in available
            ]
            useful = [entry for entry in useful if entry[0] > 0]
            if not useful:
                break
            _, best = max(
                useful,
                key=lambda entry: (
                    entry[0],
                    1 if entry[1].get("match_class") == "published-route" else 0,
                    len(entry[1]["covered_edges"]),
                    entry[1]["end_index"] - entry[1]["start_index"],
                    str(entry[1]["profile"].get("chart") or ""),
                ),
            )
            selected.append(best)
            uncovered -= best["covered_edges"]
            available = [item for item in available if item is not best]

        coverage_complete = not uncovered
        selected.sort(key=lambda item: (item["start_index"], item["end_index"]))
        for item in selected:
            matches.append(
                {
                    "event": event,
                    "terrain_event_id": event["terrain_event_id"],
                    "profile": item["profile"],
                    "names": [
                        _route_waypoint_name(value)
                        for value in waypoints[item["start_index"] : item["end_index"] + 1]
                    ],
                    "airways": item["airways"],
                    "route_start": item["route_start"],
                    "route_end": item["route_end"],
                    "direction": item["direction"],
                    "match_class": item.get("match_class", "published-route"),
                    "coverage_complete": coverage_complete,
                    "uncovered_edge_count": len(uncovered),
                    "start_index": item["start_index"],
                    "end_index": item["end_index"],
                }
            )

    deduplicated: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for match in matches:
        key = (
            match["terrain_event_id"],
            str(match["profile"]["chart"]),
            match["start_index"],
            match["end_index"],
        )
        current = deduplicated.get(key)
        if current is None or match["event"]["first_high"]["actm_minutes"] < current["event"]["first_high"]["actm_minutes"]:
            deduplicated[key] = match

    candidates = list(deduplicated.values())
    pruned = [
        candidate
        for candidate in candidates
        if not any(
            other is not candidate
            and other["terrain_event_id"] == candidate["terrain_event_id"]
            and other["start_index"] <= candidate["start_index"]
            and other["end_index"] >= candidate["end_index"]
            and (
                other["start_index"] < candidate["start_index"]
                or other["end_index"] > candidate["end_index"]
            )
            for other in candidates
        )
    ]
    return sorted(
        pruned,
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )



def analyse(flight: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    fuel = flight["fuel"]
    masses = flight["masses"]
    performance = flight["performance"]
    _weather_window_preference(flight)

    findings.append(finding(
        "page1",
        "information",
        "CFP Page 1 organised control summary",
        f"{flight['flight_number']} {flight['departure']}-{flight['destination']}",
        [
            f"{flight['departure']}/{flight.get('departure_runway') or '-'} to "
            f"{flight['destination']}/{flight.get('destination_runway') or '-' }.",
            f"Scheduled departure {flight['scheduled_departure_utc']}; "
            f"arrival {flight['scheduled_arrival_utc']}.",
            f"Level profile: {flight.get('planned_level_profile') or 'not parsed'}.",
            f"Fuel required {format_kg(fuel['flight_plan_required_fuel_kg'])}; "
            f"tanks {format_kg(fuel['fuel_in_tanks_kg'])}; "
            f"trip {format_kg(fuel['trip_fuel_kg'])}.",
            f"PZFW {format_kg(masses['planned_zfw_kg'])}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; "
            f"PLWT {format_kg(masses['planned_landing_weight_kg'])}.",
        ],
        {
            "source_references": [
                _cfp_source_reference(
                    flight,
                    [flight.get("source_evidence", {}).get("page1")],
                    "Flight summary",
                )
            ],
        },
    ))

    if flight.get("bobcat"):
        allocation = flight["bobcat"]
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"].upper() == allocation["waypoint"].upper()),
            None,
        )
        ctot = datetime.fromisoformat(allocation["ctot_utc"])
        cto = datetime.fromisoformat(allocation["cto_utc"])
        if cto < ctot:
            cto += timedelta(days=1)
        predicted = ctot + timedelta(minutes=waypoint["actm_minutes"]) if waypoint else None
        difference = round((predicted - cto).total_seconds() / 60) if predicted else None
        # The allocation itself belongs in the summary, not only in the evidence
        # list: the reports render a finding's summary line, so a bare delta left
        # the crossing time, level and CTOT out of the printed brief entirely.
        # Every value here is read from the CFP or computed from it.
        findings.append(finding(
            "bobcat",
            "critical" if difference not in (None, 0) else "warning" if difference is None else "information",
            "BOBCAT timing reconciliation",
            (
                f"{allocation['waypoint']} FL{allocation['flight_level']}: "
                f"CTOT {ctot:%H%MZ} + ACTM {format_actm(waypoint['actm_minutes'])} "
                f"= {predicted:%H%MZ} against allocated CTO {cto:%H%MZ} "
                f"({difference:+d} min)."
                if difference is not None
                else (
                    f"{allocation['waypoint']} FL{allocation['flight_level']}: "
                    f"allocated CTOT {ctot:%H%MZ}, CTO {cto:%H%MZ}; "
                    "CFP waypoint ACTM not found, so no crossing time is computed."
                )
            ),
            [
                f"Allocation CTOT {ctot:%H%MZ}; CTO {cto:%H%MZ}; FL{allocation['flight_level']}.",
                f"CFP waypoint ACTM {format_actm(waypoint['actm_minutes']) if waypoint else 'not found'}.",
                "Treat the allocated CTO as controlling and recheck if take-off, route, level or speed changes.",
            ],
            {
                "difference_minutes": difference,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            flight.get("source_evidence", {}).get("page1"),
                            (waypoint or {}).get("source_page"),
                        ],
                        "BOBCAT allocation and route timing",
                    )
                ],
            },
        ))

    for item in flight["deferred_items"]:
        if item["item_type"] == "UNCLASSIFIED":
            declaration = str(item.get("source_declaration") or "UNCLASSIFIED DEFERRED DECLARATION")
            details = [item.get("description") or "No following CFP text parsed."]
            if item.get("company_remark"):
                details.append(item["company_remark"])
            findings.append(finding(
                "deferred_declaration",
                "unknown",
                declaration,
                (
                    "Unclassified CFP deferred declaration; acronym meaning is not inferred "
                    "and it is not classified as MEL, CDL or CDDL."
                ),
                details,
                {
                    "classification": "unclassified",
                    "source_references": [
                        _cfp_source_reference(
                            flight,
                            [flight.get("source_evidence", {}).get("page1")],
                            "Deferred declaration",
                        )
                    ],
                },
            ))
        elif item["item_type"] == "MEL":
            reference = MEL_REFERENCES.get(item["reference"])
            if reference and _reference_library_is_approved():
                details = [
                    f"Repair interval {reference.get('repair_interval')}; "
                    f"installed {reference.get('installed')}; required {reference.get('required')}.",
                    f"Placard {'required' if reference.get('placard_required') else 'not required/none stated'}; "
                    f"operational procedure {'required' if reference.get('operational_procedure_required') else 'not stated'}.",
                    *reference.get("terms", []),
                ]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "warning",
                    f"MEL {item['reference']} - {item['description']}",
                    "Candidate local-library match; verify the current approved MEL before use.",
                    details,
                    {
                        "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                    },
                ))
            else:
                details = [item["description"]]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "unknown",
                    f"MEL {item['reference']} requires approved source review",
                    "Current approved MEL evidence is unavailable.",
                    details,
                    {
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                        "source_references": [
                            _cfp_source_reference(
                                flight,
                                [flight.get("source_evidence", {}).get("page1")],
                                "Deferred item declaration",
                            )
                        ],
                    },
                ))
        elif item["item_type"] == "CDL":
            reference_key = str(item.get("reference") or "").upper()
            record = CDL_REFERENCES.get(reference_key)
            if record is None:
                mounted = CDL_LIBRARY_METADATA.get("status") != "controlled-source-not-mounted"
                findings.append(finding(
                    "cdl",
                    "unknown",
                    f"CDL {reference_key} not resolved",
                    (
                        "Reference not found in the mounted controlled CDL index."
                        if mounted
                        else "The private controlled CDL index is not mounted."
                    ),
                    [
                        item.get("description") or "No Page 1 description parsed.",
                        item.get("company_remark") or "No Page 1 company remark parsed.",
                    ],
                    {
                        "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                        "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    },
                ))
                continue

            variants = select_cdl_variants(record, flight.get("registration"))
            if not variants:
                findings.append(finding(
                    "cdl",
                    "critical",
                    f"CDL {reference_key} effectivity conflict",
                    f"No controlled variant applies to registration {flight.get('registration') or 'not parsed'}.",
                    [record.get("title") or "Title not available."],
                    {
                        "source_pages": record.get("source_pages", []),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    },
                ))
                continue

            details = [
                f"Page 1: {item.get('description') or 'description not parsed'}.",
            ]
            if item.get("company_remark"):
                details.append(f"Company remark: {item['company_remark']}.")
            takeoff_penalties: list[int] = []
            enroute_penalties: list[int] = []
            fuel_penalties: list[float] = []
            for number, variant in enumerate(variants, start=1):
                label = variant.get("component") or record.get("title") or reference_key
                quantity = variant.get("quantity_installed")
                details.append(
                    f"Applicable variant {number}: {label}"
                    + (f"; quantity installed {quantity}." if quantity is not None else ".")
                )
                for field, prefix in (
                    ("dispatch_conditions", "Dispatch"),
                    ("limitations", "Limitation"),
                ):
                    if variant.get(field):
                        details.append(f"{prefix}: {variant[field]}")
                details.extend(f"Note: {value}" for value in variant.get("notes", []) if value)
                if variant.get("maintenance_references"):
                    details.append(
                        "Maintenance reference: "
                        + ", ".join(variant["maintenance_references"])
                        + "."
                    )
                if variant.get("mel_references"):
                    details.append(
                        "MEL interface: " + ", ".join(variant["mel_references"]) + "."
                    )
                takeoff_penalties.extend(variant.get("takeoff_approach_penalty_kg_values", []))
                enroute_penalties.extend(variant.get("enroute_penalty_kg_values", []))
                fuel_penalties.extend(variant.get("fuel_penalty_percent_values", []))

            takeoff_penalties = list(dict.fromkeys(takeoff_penalties))
            enroute_penalties = list(dict.fromkeys(enroute_penalties))
            fuel_penalties = list(dict.fromkeys(fuel_penalties))
            if takeoff_penalties:
                details.append(
                    "Published take-off/approach penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in takeoff_penalties)
                    + "."
                )
            if enroute_penalties:
                details.append(
                    "Published enroute penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in enroute_penalties)
                    + "."
                )
            if fuel_penalties:
                details.append(
                    "Published fuel increase value(s): "
                    + ", ".join(f"{value:g}%" for value in fuel_penalties)
                    + "."
                )
            details.append(
                f"Controlled source issue {CDL_LIBRARY_METADATA.get('issue_date')}; "
                f"page(s) {', '.join(str(value) for value in record.get('source_pages', [])) or 'not indexed'}."
            )
            findings.append(finding(
                "cdl",
                "warning",
                f"CDL {reference_key} - {record.get('title') or item.get('description') or 'item'}",
                "Controlled registration-specific CDL match.",
                details,
                {
                    "reference": reference_key,
                    "source_pages": record.get("source_pages", []),
                    "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                    "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    "takeoff_approach_penalty_kg_values": takeoff_penalties,
                    "enroute_penalty_kg_values": enroute_penalties,
                    "fuel_penalty_percent_values": fuel_penalties,
                    "applicable_variant_count": len(variants),
                },
            ))
        else:
            findings.append(finding(
                "cddl",
                "unknown",
                f"{item['item_type']} {item['reference']} not verified",
                "The approved configuration-deviation reference is missing.",
                [item["description"], item.get("company_remark") or "No company remark parsed."],
            ))

    candidates = [
        x for x in (
            performance.get("obstacle_rtow_kg"),
            performance.get("landing_rtow_kg"),
            performance.get("structural_rtow_kg"),
        )
        if x is not None
    ]
    controlling = performance.get("controlling_rtow_kg") or (min(candidates) if candidates else None)
    margin = controlling - masses["planned_takeoff_weight_kg"] if controlling is not None else None
    findings.append(finding(
        "performance",
        "warning" if margin is not None and margin < 5000 else "information",
        "Take-off performance summary",
        f"Conditional RTOW margin {format_kg(margin)}.",
        [
            f"Runway {performance.get('runway') or 'not parsed'}; "
            f"condition {performance.get('runway_condition') or 'not parsed'}; "
            f"thrust {performance.get('thrust_setting') or 'not parsed'}; "
            f"flaps {performance.get('flap_setting') if performance.get('flap_setting') is not None else 'not parsed'}.",
            f"Temperature {performance.get('temperature_c')} C; QNH {performance.get('qnh_hpa')} hPa; "
            f"wind {performance.get('wind')}.",
            f"Packs {_switch_state(performance.get('packs_on'))}; "
            f"anti-ice {_switch_state(performance.get('anti_ice_on'))}; "
            f"EOSID {performance.get('eosid') or 'not parsed'}.",
            f"Obstacle RTOW {format_kg(performance.get('obstacle_rtow_kg'))}; "
            f"landing RTOW {format_kg(performance.get('landing_rtow_kg'))}; "
            f"structural RTOW {format_kg(performance.get('structural_rtow_kg'))}.",
            f"Controlling RTOW {format_kg(controlling)}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; margin {format_kg(margin)}.",
            "The margin is conditional on every stated input and applicable MEL/CDL effect.",
        ],
        {
            "controlling_rtow_kg": controlling,
            "margin_kg": margin,
            "source_references": [
                _cfp_source_reference(
                    flight,
                    list(
                        flight.get("source_evidence", {}).get(
                            "performance_pages",
                            [],
                        )
                    ),
                    "Performance and mass data",
                )
            ],
        },
    ))

    for hazard in _HAZARD_REVIEWS:
        hazard_findings, hazard_warnings = _hazard_review_findings(
            flight.get(hazard["review_key"]) or {},
            hazard,
        )
        findings.extend(hazard_findings)
        warnings.extend(hazard_warnings)

    official_weather_gap = (
        _official_weather_review_finding(flight["official_weather_review"])
        if isinstance(flight.get("official_weather_review"), dict)
        else None
    )
    if official_weather_gap is not None:
        findings.append(official_weather_gap)
        warnings.append(
            "Official public METAR/TAF coverage is incomplete; review current operational weather."
        )

    alternate_airports = {a["airport"] for a in flight["alternates"]}
    edto_airports = {a["airport"] for a in flight["edto"]["airports"]}
    edto_periods: dict[str, tuple[datetime, datetime]] = {}
    for airport in flight["edto"]["airports"]:
        starts_at = datetime.fromisoformat(airport["period_start_utc"])
        ends_at = datetime.fromisoformat(airport["period_end_utc"])
        current = edto_periods.get(airport["airport"])
        edto_periods[airport["airport"]] = (
            min(starts_at, current[0]) if current else starts_at,
            max(ends_at, current[1]) if current else ends_at,
        )
    audit_evidence = flight.setdefault("audit_evidence", {})

    weather_audit_records: list[dict[str, Any]] = []
    weather_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in flight["weather"]:
        location = record["location"]
        phase, window_start, window_end = _weather_role_window(
            flight,
            location,
            alternate_airports,
            edto_periods,
        )
        raw_text = str(record["text"])
        upper = raw_text.upper()
        significant = bool(
            record.get("record_type") == "SIGMET"
            or re.search(
                r"\b(?:TS|TSRA|VCTS|CB|BKN00\d|OVC00\d|G\d{2,3}KT|"
                r"LLWS|WS|FZRA|FZDZ|SN|BLSN|SEV\s+TURB|SEV\s+ICE)\b",
                upper,
            )
        )
        record_type = str(record.get("record_type") or "weather")
        taf_summary = (
            summarize_taf_for_window(raw_text, window_start, window_end)
            if record_type == "TAF"
            else None
        )
        observed_at = None
        if record.get("observed_at_utc"):
            try:
                observed_at = datetime.fromisoformat(
                    str(record["observed_at_utc"]).replace("Z", "+00:00")
                )
            except ValueError:
                observed_at = None
        metar_summary = (
            summarize_metar_for_window(
                raw_text,
                window_start,
                window_end,
                observed_at=observed_at,
            )
            if record_type == "METAR"
            else None
        )
        evidence_ref = f"weather:{len(weather_audit_records)}"
        weather_audit_records.append({
            "evidence_ref": evidence_ref,
            "source": record.get("source") or "uploaded_cfp",
            "provider": record.get("provider"),
            "location": location,
            "record_type": record_type,
            "raw_text": raw_text,
            "raw_sha256": record.get("raw_sha256"),
            "observed_at_utc": record.get("observed_at_utc"),
            "issue_time_utc": record.get("issue_time_utc"),
            "valid_from_utc": record.get("valid_from_utc"),
            "valid_to_utc": record.get("valid_to_utc"),
            "retrieved_at_utc": record.get("retrieved_at_utc"),
            "source_page": record.get("source_page"),
            "phase": phase,
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": window_end.isoformat(),
            "selected_for_pilot": (
                phase != "Enroute"
                or significant
                or bool(taf_summary and taf_summary["status"] != "no_significant_overlap")
                or bool(
                    metar_summary
                    and metar_summary["status"] not in {
                        "outside_window",
                        "no_significant_observation",
                    }
                )
            ),
            **(
                {"window_status": taf_summary["status"]}
                if taf_summary
                else {"window_status": metar_summary["status"]}
                if metar_summary
                else {}
            ),
        })
        if (
            phase == "Enroute"
            and not significant
            and taf_summary is None
            and (
                metar_summary is None
                or metar_summary["status"] == "outside_window"
            )
        ):
            continue

        window_label = _utc_window_label(window_start, window_end)
        key = (phase, location, window_label)
        group = weather_groups.setdefault(key, {
            "phase": phase,
            "location": location,
            "utc_window": window_label,
            "mechanisms": [],
            "taf_summaries": [],
            "taf_evidence_refs": [],
            "metar_summaries": [],
            "metar_evidence_refs": [],
            "fallback_evidence_refs": [],
            "record_types": [],
            "audit_evidence_refs": [],
            "source_references": [],
            "warning": False,
        })
        source_reference = _weather_source_reference(flight, record)
        if source_reference not in group["source_references"]:
            group["source_references"].append(source_reference)
        if taf_summary:
            group["taf_summaries"].append(taf_summary)
            group["taf_evidence_refs"].append(evidence_ref)
        elif metar_summary:
            group["metar_summaries"].append(metar_summary)
            group["metar_evidence_refs"].append(evidence_ref)
        else:
            group["fallback_evidence_refs"].append(evidence_ref)
            prepared = concise_weather_finding(finding(
                "weather",
                "warning" if significant else "information",
                f"{phase} weather - {location}",
                "",
                data={
                    "phase": phase,
                    "utc_window": window_label,
                    "raw_text": raw_text,
                },
            ))
            mechanism = str(prepared["data"]["mechanism"])
            for mechanism_part in (
                part.strip()
                for part in mechanism.split(",")
                if part.strip()
            ):
                if mechanism_part not in group["mechanisms"]:
                    group["mechanisms"].append(mechanism_part)
        if record_type not in group["record_types"]:
            group["record_types"].append(record_type)
        group["audit_evidence_refs"].append(evidence_ref)
        group["warning"] = bool(
            group["warning"]
            or significant
            or bool(taf_summary and taf_summary["status"] != "no_significant_overlap")
            or bool(metar_summary and metar_summary["status"] == "pertinent")
        )

    for group in weather_groups.values():
        taf_summary = group["taf_summaries"][-1] if group["taf_summaries"] else None
        if taf_summary:
            status = taf_summary["status"]
            data = {
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": taf_summary["mechanism"],
                "applicable_conditions": taf_summary["applicable_conditions"],
                "timing": taf_summary["timing"],
                "window_status": status,
                "window_status_text": taf_summary["window_status_text"],
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
            }
            nearby_observation = next(
                (
                    item
                    for item in reversed(group["metar_summaries"])
                    if item["status"] != "outside_window"
                ),
                None,
            )
            if nearby_observation:
                data.update({
                    "observed_conditions": nearby_observation["applicable_conditions"],
                    "observation_time_utc": nearby_observation["observed_at_utc"],
                    "observation_status": nearby_observation["status"],
                })
            if status == "no_significant_overlap":
                data["flight_effect"] = (
                    "No adverse flight effect is indicated for this window by the "
                    "CFP TAF; confirm the latest operational weather."
                )
            elif status == "review_required":
                data["flight_effect"] = (
                    "Forecast coverage is incomplete; review the latest operational "
                    "weather for this flight phase."
                )
            severity = "information" if status == "no_significant_overlap" else "warning"
        elif group["metar_summaries"]:
            metar_summary = group["metar_summaries"][-1]
            data = {
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": metar_summary["mechanism"],
                "applicable_conditions": metar_summary["applicable_conditions"],
                "timing": metar_summary["timing"],
                "window_status": metar_summary["status"],
                "window_status_text": metar_summary["window_status_text"],
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
                "observation_time_utc": metar_summary["observed_at_utc"],
            }
            if metar_summary["status"] == "outside_window":
                data["flight_effect"] = (
                    "This observation is not used to characterize the later flight "
                    "window; review the applicable forecast and latest observation."
                )
                severity = "unknown"
            elif metar_summary["status"] == "no_significant_observation":
                data["flight_effect"] = (
                    "No adverse effect is indicated by this nearby observation; "
                    "confirm the applicable forecast and latest operational weather."
                )
                severity = "information"
            else:
                severity = "warning"
        else:
            mechanisms = list(group["mechanisms"])
            if len(mechanisms) > 1:
                mechanisms = [
                    item
                    for item in mechanisms
                    if item != "no adverse mechanism identified in the parsed station record"
                ]
            data = {
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": ", ".join(mechanisms),
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
            }
            severity = "warning" if group["warning"] else "information"
        prepared = concise_weather_finding(finding(
            "weather",
            severity,
            f"{group['phase']} weather - {group['location']}",
            "",
            data=data,
        ))
        findings.append(prepared)

    pilot_weather_evidence_refs = {
        evidence_ref
        for group in weather_groups.values()
        for evidence_ref in (
            group["taf_evidence_refs"]
            if group["taf_summaries"]
            else group["metar_evidence_refs"]
            if group["metar_summaries"]
            else group["fallback_evidence_refs"]
        )
    }
    for audit_record in weather_audit_records:
        audit_record["selected_for_pilot"] = (
            audit_record["evidence_ref"] in pilot_weather_evidence_refs
        )

    audit_evidence["weather"] = {
        "source_record_count": len(flight["weather"]),
        "pilot_facing_group_count": len(weather_groups),
        "records": weather_audit_records,
    }

    notam_audit_records: list[dict[str, Any]] = []
    applicable_notams: list[dict[str, Any]] = []
    for record in flight["notams"]:
        location = record["location"]
        role, window_start, window_end = _notam_role_window(
            flight,
            location,
            alternate_airports,
            edto_periods,
        )
        valid_from = datetime.fromisoformat(record["valid_from_utc"])
        valid_to = (
            datetime.fromisoformat(record["valid_to_utc"])
            if record.get("valid_to_utc")
            else datetime.max.replace(tzinfo=timezone.utc)
        )
        evidence_ref = f"notam:{len(notam_audit_records)}"
        reference_at = _notam_reference_at(flight, role, window_start)
        state_at_reference, minutes_delta = _notam_reference_state(
            record,
            reference_at,
            valid_from,
            valid_to,
        )
        audit_record = {
            "evidence_ref": evidence_ref,
            "source": "uploaded_cfp",
            "notam_id": record["notam_id"],
            "location": location,
            "category": record["category"],
            "raw_text": record["text"],
            "valid_from_utc": record["valid_from_utc"],
            "valid_to_utc": record.get("valid_to_utc"),
            "schedule": record.get("schedule"),
            "source_page": record.get("source_page"),
            "role": role,
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": window_end.isoformat(),
            "stateAtReference": state_at_reference,
            "referenceAt": reference_at.isoformat(),
            "minutesDelta": minutes_delta,
            "pilot_status": "pending",
        }
        notam_audit_records.append(audit_record)
        applicability = "active"
        validity_status = "overlaps_flight_window"
        if record.get("validity_review"):
            applicability = "review"
            validity_status = "review_required"
            warnings.append(f"{record['notam_id']}: B/C validity could not be parsed; manual review required.")
        elif not _intervals_overlap(valid_from, valid_to, window_start, window_end):
            audit_record["pilot_status"] = "outside_time_window"
            continue
        schedule = record.get("schedule")
        schedule_status = "not_applicable"
        if schedule:
            schedule_active = _schedule_overlaps(schedule, window_start, window_end)
            if schedule_active is False:
                audit_record["pilot_status"] = "outside_schedule"
                continue
            if schedule_active is None:
                applicability = "review"
                schedule_status = "review_required"
                warnings.append(f"{record['notam_id']}: D schedule could not be evaluated; manual review required.")
            else:
                schedule_status = "overlaps_flight_window"
        elif record.get("schedule_review"):
            applicability = "review"
            schedule_status = "review_required"
            warnings.append(f"{record['notam_id']}: schedule language could not be structured; manual review required.")
        audit_record["validity_status"] = validity_status
        audit_record["schedule_status"] = schedule_status
        pertinence_rank, pertinence_kind = notam_pertinence(
            str(record["text"]),
            str(record["category"]),
        )
        severity = (
            "critical"
            if role in {"departure", "destination"} and pertinence_rank <= 2
            else "warning"
        )
        operational_details = taxiway_operational_details(
            str(record["text"]),
            pertinence_kind,
        )
        reviewed_publication = (
            reviewed_publication_for_notam(location, record["notam_id"])
            if operational_details
            else None
        )
        details = [
            *([f"Schedule: {schedule}."] if schedule else []),
            f"Applicable {role} UTC window: {_utc_window_label(window_start, window_end)}.",
            *(["Applicability requires manual review."] if applicability == "review" else []),
        ]
        applicable_notams.append(finding(
            "notam",
            severity,
            f"{role.title()} NOTAM {record['notam_id']}",
            _notam_operational_summary(
                str(record["text"]),
                pertinence_kind,
                role,
                applicability,
            ),
            details,
            {
                "role": role,
                "location": location,
                "notam_id": record["notam_id"],
                "category": record["category"],
                "priority_score": record.get("priority_score", 0),
                "pertinence_rank": pertinence_rank,
                "pertinence_kind": pertinence_kind,
                "applicability": applicability,
                "validity_status": validity_status,
                "schedule_status": schedule_status,
                "schedule": schedule,
                "valid_from_utc": record["valid_from_utc"],
                "valid_to_utc": record.get("valid_to_utc"),
                "window_start_utc": window_start.isoformat(),
                "window_end_utc": window_end.isoformat(),
                "stateAtReference": state_at_reference,
                "referenceAt": reference_at.isoformat(),
                "minutesDelta": minutes_delta,
                "raw_text": record["text"],
                "operational_details": operational_details,
                **(
                    {"reviewed_publication": reviewed_publication}
                    if reviewed_publication
                    else {}
                ),
                "audit_evidence_ref": evidence_ref,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [record.get("source_page")],
                        "NOTAM package",
                    )
                ],
            },
        ))

    unique_applicable_notams: list[dict[str, Any]] = []
    priority_view_notams: list[dict[str, Any]] = []
    seen_notams: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in sorted(applicable_notams, key=notam_sort_key):
        data = item.get("data") or {}
        audit_index = int(str(data["audit_evidence_ref"]).split(":", 1)[1])
        audit_record = notam_audit_records[audit_index]
        semantic_key = pilot_notam_key(item)
        if semantic_key is not None and semantic_key in seen_notams:
            original = seen_notams[semantic_key]
            audit_record["pilot_status"] = "semantic_duplicate"
            audit_record["duplicate_of_notam_id"] = original["data"]["notam_id"]
            continue
        if semantic_key is not None:
            seen_notams[semantic_key] = item
        unique_applicable_notams.append(item)
        if len(priority_view_notams) < 24:
            audit_record["pilot_status"] = "selected"
            priority_view_notams.append(item)
        else:
            # Keep the complete deterministic result available to Level 2 and
            # the API.  Level 1 remains deliberately bounded through
            # prepare_pilot_findings(); "level2_only" is not hidden audit data.
            audit_record["pilot_status"] = "level2_only"
    findings.extend(unique_applicable_notams)
    audit_evidence["notam"] = {
        "source_record_count": len(flight["notams"]),
        "time_applicable_count": len(applicable_notams),
        "pilot_facing_count": len(unique_applicable_notams),
        "priority_view_count": len(priority_view_notams),
        "level2_only_count": sum(
            item["pilot_status"] == "level2_only"
            for item in notam_audit_records
        ),
        "semantic_duplicate_count": sum(
            item["pilot_status"] == "semantic_duplicate"
            for item in notam_audit_records
        ),
        "audit_only_count": sum(
            item["pilot_status"] in {
                "outside_time_window",
                "outside_schedule",
                "semantic_duplicate",
            }
            for item in notam_audit_records
        ),
        "records": notam_audit_records,
    }

    waypoint_by_boundary = {
        w["fir_boundary"]: w
        for w in flight["route_waypoints"]
        if w.get("fir_boundary")
    }
    if _reference_library_is_approved():
        for rule in COMMUNICATION_RULES:
            waypoint = waypoint_by_boundary.get(rule["boundary"])
            if not waypoint:
                continue
            action_time = waypoint["actm_minutes"] - rule["lead"]
            details = [
                f"Boundary ACTM {format_actm(waypoint['actm_minutes'])}; lead {rule['lead']} min.",
                f"Action: {rule['action']}.",
            ]
            if rule.get("frequency"):
                details.append(
                    f"Frequency {rule['frequency']} MHz"
                    + (f"; backup {rule['backup']} MHz." if rule.get("backup") else ".")
                )
            if rule.get("notes"):
                details.append(rule["notes"])
            findings.append(finding(
                "communications",
                "warning",
                f"Early ATC/FIR action before {rule['boundary']}",
                f"ACTM {format_actm(action_time)} - {rule['agency']}.",
                details,
                {
                    "action_actm_minutes": action_time,
                    "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                    "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                },
            ))
    elif waypoint_by_boundary:
        boundary_names = sorted(waypoint_by_boundary)
        findings.append(finding(
            "communications",
            "unknown",
            "FIR communication review required",
            "Current approved communication procedures are unavailable.",
            [
                f"CFP route crosses {len(boundary_names)} FIR boundary or boundaries.",
                "Review current early-contact, frequency and reporting requirements.",
            ],
            {
                "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in waypoint_by_boundary.values()
                        ],
                        "Route FIR boundaries",
                    )
                ],
            },
        ))

    terrain_events = detect_terrain_events(flight["route_waypoints"])
    for index, event in enumerate(terrain_events, start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        max_msa = maximum["msa_hundreds_ft"]
        findings.append(finding(
            "terrain",
            "warning",
            f"High-MSA event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, max {max_msa}*.",
            [
                f"First high-MSA waypoint {event['first_high']['name']}; "
                f"last high-MSA waypoint {event['last_high']['name']}.",
                f"Threshold drop at {event['drop']['name'] if event['drop'] else 'end of route data'}.",
                f"Maximum {max_msa}* ({max_msa * 100:,} ft) at {maximum['name']}, "
                f"ACTM {format_actm(maximum['actm_minutes'])}.",
                *(
                    [f"Profile matching context begins at {event['preceding']['name']}."]
                    if event.get("preceding") else []
                ),
            ],
            {
                "terrain_event_id": event["terrain_event_id"],
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "end_actm_minutes": end_wp["actm_minutes"],
                "maximum_msa_hundreds_ft": max_msa,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    )
                ],
            },
        ))

    for index, event in enumerate(detect_vws_events(flight["route_waypoints"]), start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        findings.append(finding(
            "vws",
            "warning",
            f"VWS event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, maximum {maximum['vws']:03d}.",
            [
                f"First qualifying waypoint {event['first_high']['name']}.",
                f"Last qualifying waypoint {event['last_high']['name']}.",
                f"Maximum at {maximum['name']}, ACTM {format_actm(maximum['actm_minutes'])}.",
                "Threshold is strictly greater than 4.",
            ],
            {
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route wind data",
                    )
                ],
            },
        ))

    matches = sorted(
        match_profiles(flight, terrain_events),
        key=lambda x: (x["event"]["first_high"]["actm_minutes"], x["start_index"]),
    )
    depress_source_loaded = (
        DEPRESS_LIBRARY_METADATA.get("status") == "controlled-index-loaded"
    )
    for index, match in enumerate(matches, start=1):
        event = match["event"]
        profile = match["profile"]
        route_start = match["route_start"]
        route_end = match["route_end"]
        critical = profile["critical"]
        critical_aliases = _profile_aliases(profile, "critical")
        critical_wp = next(
            (
                waypoint
                for waypoint in flight["route_waypoints"]
                if _route_waypoint_name(waypoint) in critical_aliases
            ),
            None,
        )
        maximum = event["maximum"]
        end_wp = event["drop"] or event["last_high"]
        details = [
            f"High-MSA event ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}.",
            f"Maximum MSA {maximum['msa_hundreds_ft']}* "
            f"({maximum['msa_hundreds_ft'] * 100:,} ft) at {maximum['name']}.",
            f"Published chart route {profile['from']}-{profile['to']}; "
            f"airways {', '.join(profile['airways']) or 'none listed'}.",
            f"Critical point {critical}"
            + (
                f", CFP ACTM {format_actm(critical_wp['actm_minutes'])}."
                if critical_wp
                else "; ACTM not found."
            ),
            f"Controlled profile issue {DEPRESS_LIBRARY_METADATA.get('issue_date')}; "
            f"effective {profile.get('effective_date') or 'not indexed'}.",
        ]
        if profile.get("chart_page"):
            details.append(f"Controlled chart page {profile['chart_page']}.")
        if not match["coverage_complete"]:
            details.append(
                f"Coverage incomplete: {match['uncovered_edge_count']} event route leg(s) remain unmatched."
            )
        if not depress_source_loaded:
            details.append(
                "Controlled profile index is not mounted; this repository-safe "
                "candidate requires review against the approved current source."
            )
        findings.append(finding(
            "depressurisation",
            (
                "warning"
                if match["coverage_complete"] and depress_source_loaded
                else "unknown"
            ),
            f"Profile {index} - {route_start} to {route_end} "
            f"({' / '.join(match['airways']) or 'airway review required'})",
            (
                f"Proposed depressurisation chart {profile['chart']}; "
                f"critical point {critical}."
                if depress_source_loaded
                else (
                    f"Candidate chart {profile['chart']}; controlled profile "
                    "index unavailable - review required."
                )
            ),
            details,
            {
                "chart_number": profile["chart"],
                "critical_point": critical,
                "terrain_event_id": match["terrain_event_id"],
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "route_start": route_start,
                "route_end": route_end,
                "coverage_complete": match["coverage_complete"],
                "controlled_issue_date": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "chart_page": profile.get("chart_page"),
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    ),
                    {
                        "source_type": "controlled_document",
                        "document_title": DEPRESS_LIBRARY_METADATA.get("title"),
                        "revision": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                        "pages": (
                            [profile.get("chart_page")]
                            if profile.get("chart_page")
                            else []
                        ),
                        "section": f"Profile {profile['chart']}",
                        "availability_status": DEPRESS_LIBRARY_METADATA.get("status"),
                    },
                ],
            },
        ))

    matches_by_event: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        matches_by_event.setdefault(match["terrain_event_id"], []).append(match)
    coverage_scope = str(
        DEPRESS_LIBRARY_METADATA.get("coverage_scope") or "not stated"
    )
    for event in terrain_events:
        event_id = event["terrain_event_id"]
        event_matches = matches_by_event.get(event_id, [])
        exact_profile_confirmed = bool(
            depress_source_loaded
            and any(match["coverage_complete"] for match in event_matches)
        )
        if exact_profile_confirmed:
            continue

        first_high = event["first_high"]
        last_high = event["last_high"]
        threshold_drop = event.get("drop")
        context_start = event.get("preceding") or first_high
        event_end = threshold_drop or last_high
        candidate_charts = sorted(
            {
                str(match["profile"].get("chart") or "")
                for match in event_matches
                if match["profile"].get("chart")
            }
        )
        reference_status = "partial" if depress_source_loaded else "unavailable"
        summary = (
            "No exact profile confirmed from controlled partial issue - "
            "manual review required."
            if depress_source_loaded and coverage_scope == "partial_issue"
            else (
                "No exact profile confirmed from controlled index - "
                "manual review required."
                if depress_source_loaded
                else (
                    "No exact profile confirmed because the controlled profile "
                    "index is unavailable - manual review required."
                )
            )
        )
        details = [
            f"High-MSA event ACTM {format_actm(first_high['actm_minutes'])}-"
            f"{format_actm(event_end['actm_minutes'])}.",
            f"Validated exposure boundary {first_high['name']}-{last_high['name']}; "
            f"profile matching context begins at {context_start['name']}.",
        ]
        if candidate_charts:
            details.append(
                "Candidate chart coverage is incomplete: "
                f"{', '.join(candidate_charts)}."
            )
        details.append(
            (
                f"Controlled profile coverage scope is {coverage_scope}; no "
                "complete endpoint, airway and effectivity match was found."
                if depress_source_loaded
                else "The approved controlled profile index is not mounted."
            )
        )
        findings.append(finding(
            "depressurisation",
            "unknown",
            f"Profile unresolved - {first_high['name']} to {last_high['name']}",
            summary,
            details,
            {
                "terrain_event_id": event_id,
                "confirmed": False,
                "coverage_complete": False,
                "reference_status": reference_status,
                "controlled_library_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "controlled_index_loaded": depress_source_loaded,
                "coverage_scope": coverage_scope,
                "candidate_chart_numbers": candidate_charts,
                "start_actm_minutes": first_high["actm_minutes"],
                "end_actm_minutes": event_end["actm_minutes"],
                "profile_context_start_waypoint": context_start["name"],
                "first_high_waypoint": first_high["name"],
                "last_high_waypoint": last_high["name"],
                "threshold_drop_waypoint": (
                    threshold_drop["name"] if threshold_drop else None
                ),
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                first_high,
                                last_high,
                                event.get("maximum"),
                                threshold_drop,
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    ),
                    {
                        "source_type": "controlled_document",
                        "document_title": DEPRESS_LIBRARY_METADATA.get("title"),
                        "revision": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                        "pages": [],
                        "section": "Depressurisation profile index",
                        "availability_status": DEPRESS_LIBRARY_METADATA.get("status"),
                        "coverage_scope": coverage_scope,
                    },
                ],
            },
        ))

    if terrain_events and not matches:
        findings.append(finding(
            "depressurisation",
            "unknown",
            "High terrain detected but no profile matched",
            "No controlled profile is confirmed; manual chart-index review is required.",
            [
                (
                    "The approved controlled profile index is loaded, but no "
                    "complete applicable match was found."
                    if depress_source_loaded
                    else "The approved controlled profile index is not mounted."
                )
            ],
            {
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "controlled_index_loaded": depress_source_loaded,
                "terrain_event_ids": [
                    event["terrain_event_id"]
                    for event in terrain_events
                ],
            },
        ))

    edto = flight["edto"]
    sectors = edto_sectors(edto)
    if sectors:
        sector_summary = "; ".join(
            f"S{sector.get('number', index)} "
            f"{format_actm(sector.get('entry_actm_minutes'))}-"
            f"{format_actm(sector.get('exit_actm_minutes'))}"
            for index, sector in enumerate(sectors, start=1)
        )
        details = []
        for index, sector in enumerate(sectors, start=1):
            number = sector.get("number", index)
            line = (
                f"Sector {number}: entry ACTM "
                f"{format_actm(sector.get('entry_actm_minutes'))}; exit ACTM "
                f"{format_actm(sector.get('exit_actm_minutes'))}."
            )
            if sector.get("etp_actm_minutes"):
                line += (
                    " ETP ACTM "
                    + ", ".join(
                        format_actm(value)
                        for value in sector["etp_actm_minutes"]
                    )
                    + "."
                )
            details.append(line)
        details.extend(
            f"{a['airport']} checked {datetime.fromisoformat(a['period_start_utc']):%H%MZ}-"
            f"{datetime.fromisoformat(a['period_end_utc']):%H%MZ}, RWY {a['runway']} "
            f"{a['approach']}, minima {a['minima']}."
            for a in edto["airports"]
        )
        findings.append(finding(
            "edto",
            "information",
            "EDTO checked-period summary",
            f"ACTM {sector_summary}.",
            details,
            {
                "start_actm_minutes": sectors[0]["entry_actm_minutes"],
                "sectors": [
                    {
                        "number": sector.get("number", index),
                        "entry_actm_minutes": sector.get("entry_actm_minutes"),
                        "exit_actm_minutes": sector.get("exit_actm_minutes"),
                        "etp_actm_minutes": list(
                            sector.get("etp_actm_minutes") or []
                        ),
                    }
                    for index, sector in enumerate(sectors, start=1)
                ],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [flight.get("source_evidence", {}).get("edto_page")],
                        "EDTO information",
                    )
                ],
            },
        ))

    timeline_items: list[tuple[int, str, str]] = []
    for item in findings:
        if item["engine"] in {"vaa", "communications", "terrain", "vws", "depressurisation", "edto"}:
            data = item.get("data", {})
            actm = data.get("action_actm_minutes")
            if actm is None:
                actm = data.get("start_actm_minutes")
            if actm is not None:
                timeline_items.append((actm, item["title"], item["summary"]))
    if flight.get("bobcat"):
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"] == flight["bobcat"]["waypoint"]),
            None,
        )
        if waypoint:
            timeline_items.append((
                waypoint["actm_minutes"],
                f"BOBCAT {waypoint['name']}",
                f"FL{flight['bobcat']['flight_level']} CTO "
                f"{datetime.fromisoformat(flight['bobcat']['cto_utc']):%H%MZ}.",
            ))
    timeline_items.sort(key=lambda x: x[0])
    findings.append(finding(
        "timeline",
        "information",
        "Route-critical ACTM timeline",
        f"{len(timeline_items)} ordered operational events.",
        [f"ACTM {format_actm(a)} - {b}: {c}" for a, b, c in timeline_items[:24]],
    ))

    calculated_destination = (
        fuel["fuel_in_tanks_kg"] - fuel["taxi_fuel_kg"] - fuel["trip_fuel_kg"]
    )
    difference = calculated_destination - fuel["planned_destination_fuel_kg"]
    findings.append(finding(
        "qa",
        "information" if difference == 0 else "warning",
        "Destination fuel reconciliation",
        f"Calculated {format_kg(calculated_destination)}; "
        f"stated {format_kg(fuel['planned_destination_fuel_kg'])}; "
        f"difference {difference:+,} kg.",
    ))
    findings.append(finding(
        "qa",
        "information",
        "MSA 100* threshold handling",
        "A starred MSA qualifies; without an asterisk only numeric values strictly above 100 qualify.",
    ))
    return findings, warnings
