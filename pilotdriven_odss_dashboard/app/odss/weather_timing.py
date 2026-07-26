from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


_TAF_MARKER = re.compile(
    r"\b(?:PROB(?:30|40)(?:\s+TEMPO)?\s+\d{4}/\d{4}|"
    r"TEMPO\s+\d{4}/\d{4}|BECMG\s+\d{4}/\d{4}|FM\d{6})\b"
)


def _date_candidates(
    day: int,
    hour: int,
    minute: int,
    reference: datetime,
) -> list[datetime]:
    if day < 1 or day > 31 or hour < 0 or hour > 24 or minute < 0 or minute > 59:
        return []
    normalized_hour = 0 if hour == 24 else hour
    add_day = 1 if hour == 24 else 0
    candidates: list[datetime] = []
    for month_offset in (-1, 0, 1):
        month_index = reference.month - 1 + month_offset
        year = reference.year + month_index // 12
        month = month_index % 12 + 1
        try:
            candidate = datetime(
                year,
                month,
                day,
                normalized_hour,
                minute,
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
        if add_day:
            candidate = candidate.replace(day=day) + _ONE_DAY
        candidates.append(candidate)
    return candidates


_ONE_DAY = timedelta(days=1)


def _closest_day_hour(token: str, reference: datetime) -> datetime | None:
    match = re.fullmatch(r"(\d{2})(\d{2})", token)
    if not match:
        return None
    candidates = _date_candidates(
        int(match.group(1)),
        int(match.group(2)),
        0,
        reference,
    )
    return min(candidates, key=lambda value: abs(value - reference), default=None)


def _closest_day_time(token: str, reference: datetime) -> datetime | None:
    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", token)
    if not match:
        return None
    candidates = _date_candidates(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        reference,
    )
    return min(candidates, key=lambda value: abs(value - reference), default=None)


def _day_hour_period(
    token: str,
    reference: datetime,
) -> tuple[datetime, datetime] | None:
    match = re.fullmatch(r"(\d{4})/(\d{4})", token)
    if not match:
        return None
    starts_at = _closest_day_hour(match.group(1), reference)
    end_match = re.fullmatch(r"(\d{2})(\d{2})", match.group(2))
    if starts_at is None or end_match is None:
        return None
    candidates = [
        value
        for value in _date_candidates(
            int(end_match.group(1)),
            int(end_match.group(2)),
            0,
            starts_at,
        )
        if starts_at < value <= starts_at + timedelta(hours=72)
    ]
    ends_at = min(candidates, default=None)
    return (starts_at, ends_at) if ends_at else None


def _overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return left_start < right_end and right_start < left_end


def significant_mechanisms(value: str) -> list[str]:
    text = str(value or "").upper()
    mechanisms: list[str] = []

    def add(label: str) -> None:
        if label not in mechanisms:
            mechanisms.append(label)

    # TCU alone is an observation, not a thunderstorm forecast. Treat an
    # explicit TS/VCTS or CB as the significant convective mechanism.
    if re.search(r"(?:^|\s)(?:[+-]?TS[A-Z]*|VCTS)(?=\s|=|$)|\bCB\b", text):
        add("convection / thunderstorms")
    if re.search(r"(?:^|\s)(?:FZRA|FZDZ|SN|SG|PL)(?=\s|=|$)", text):
        add("freezing or frozen precipitation")
    if re.search(r"(?:^|\s)(?:[+-]?(?:SH)?(?:RA|DZ))(?=\s|=|$)", text):
        add("rain / showers")
    if re.search(r"(?:^|\s)(?:BR|FG|HZ)(?=\s|=|$)", text):
        add("reduced visibility")
    if re.search(r"(?:BKN|OVC)0[0-2]\d|(?:^|\s)VV\d{3}", text):
        add("low cloud / ceiling")
    if re.search(r"\b(?:\d{3}|VRB)\d{2,3}G\d{2,3}KT\b", text):
        add("gusty surface wind")
    if re.search(r"(?:^|\s)WS(?:\s|=|$)|WIND\s*SHEAR", text):
        add("wind shear")
    return mechanisms[:4]


def _describe_conditions(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").upper()).strip().rstrip("=")
    parts: list[str] = []
    wind = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", text)
    if wind:
        direction = "variable" if wind.group(1) == "VRB" else f"{int(wind.group(1))}°"
        label = f"wind {direction} {int(wind.group(2))} kt"
        if wind.group(3):
            label += f", gusting {int(wind.group(3))} kt"
        parts.append(label)
    visibility = re.search(r"(?:^|\s)(\d{4})(?=\s|$)", text)
    if visibility:
        metres = int(visibility.group(1))
        parts.append(
            "visibility 10 km or more"
            if metres == 9999
            else f"visibility {metres / 1000:g} km"
            if metres >= 1000
            else f"visibility {metres} m"
        )
    cloud_labels = {
        "FEW": "few",
        "SCT": "scattered",
        "BKN": "broken",
        "OVC": "overcast",
        "VV": "vertical visibility",
    }
    clouds = [
        f"{cloud_labels.get(match.group(1), match.group(1))} {int(match.group(2)) * 100} ft"
        for match in re.finditer(r"\b(FEW|SCT|BKN|OVC|VV)(\d{3})(?:CB|TCU)?\b", text)
    ]
    parts.extend(clouds[:3])
    mechanisms = significant_mechanisms(text)
    if mechanisms:
        parts.append("; ".join(mechanisms))
    return "; ".join(parts) or "conditions could not be safely decoded"


def _short_range(starts_at: datetime, ends_at: datetime) -> str:
    starts_at = starts_at.astimezone(timezone.utc)
    ends_at = ends_at.astimezone(timezone.utc)
    if starts_at.date() == ends_at.date():
        return f"{starts_at:%H:%MZ}-{ends_at:%H:%MZ}"
    return f"{starts_at:%Y-%m-%d %H:%MZ}-{ends_at:%Y-%m-%d %H:%MZ}"


def _parse_taf(text: str, reference: datetime) -> dict[str, Any] | None:
    normalized = re.sub(r"\s+", " ", str(text or "").upper()).strip()
    validity_match = re.search(r"\b(\d{4}/\d{4})\b", normalized)
    if not validity_match:
        return None
    validity = _day_hour_period(validity_match.group(1), reference)
    if validity is None:
        return None
    validity_start, validity_end = validity
    body = normalized[validity_match.end():].split("=", 1)[0].strip()
    markers = [
        {
            "marker": match.group(0),
            "start": match.start(),
            "end": match.end(),
        }
        for match in _TAF_MARKER.finditer(body)
    ]
    initial_text = body[: markers[0]["start"] if markers else len(body)].strip()
    sections = [
        {
            **marker,
            "text": body[
                marker["end"]:
                markers[index + 1]["start"] if index + 1 < len(markers) else len(body)
            ].strip(),
        }
        for index, marker in enumerate(markers)
    ]

    fm_sections: list[dict[str, Any]] = []
    for section in sections:
        if not section["marker"].startswith("FM"):
            continue
        starts_at = _closest_day_time(section["marker"][2:], reference)
        if starts_at:
            fm_sections.append({**section, "starts_at": starts_at})

    groups: list[dict[str, Any]] = []
    first_fm = fm_sections[0]["starts_at"] if fm_sections else validity_end
    if initial_text and validity_start < first_fm:
        groups.append({
            "kind": "base",
            "text": initial_text,
            "starts_at": validity_start,
            "ends_at": first_fm,
        })
    for index, section in enumerate(fm_sections):
        ends_at = (
            fm_sections[index + 1]["starts_at"]
            if index + 1 < len(fm_sections)
            else validity_end
        )
        if section["text"] and section["starts_at"] < ends_at:
            groups.append({
                "kind": "fm",
                "text": section["text"],
                "starts_at": section["starts_at"],
                "ends_at": ends_at,
            })
    for section in sections:
        marker = section["marker"]
        if marker.startswith("FM"):
            continue
        period_match = re.search(r"(\d{4}/\d{4})$", marker)
        period = _day_hour_period(period_match.group(1), reference) if period_match else None
        if period is None or not section["text"]:
            continue
        kind = (
            "becmg"
            if marker.startswith("BECMG")
            else "tempo"
            if marker.startswith("TEMPO")
            else "probability"
        )
        groups.append({
            "kind": kind,
            "text": section["text"],
            "starts_at": period[0],
            "ends_at": period[1],
        })
    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "groups": groups,
    }


def summarize_taf_for_window(
    text: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, str] | None:
    parsed = _parse_taf(text, window_start)
    if parsed is None:
        return None
    groups = parsed["groups"]
    coverage_complete = (
        parsed["validity_start"] <= window_start
        and window_end <= parsed["validity_end"]
    )
    base_groups = [
        group
        for group in groups
        if group["kind"] in {"base", "fm"}
        and _overlaps(
            group["starts_at"],
            group["ends_at"],
            window_start,
            window_end,
        )
    ]
    changing_groups = [
        group
        for group in groups
        if group["kind"] not in {"base", "fm"}
        and _overlaps(
            group["starts_at"],
            group["ends_at"],
            window_start,
            window_end,
        )
    ]
    active_base_start = min(
        (group["starts_at"] for group in base_groups),
        default=datetime.min.replace(tzinfo=timezone.utc),
    )
    prior_becmg = sorted(
        (
            group
            for group in groups
            if group["kind"] == "becmg"
            and group["ends_at"] <= window_start
            and group["ends_at"] > active_base_start
        ),
        key=lambda group: group["ends_at"],
        reverse=True,
    )
    applicable_groups = [
        *base_groups,
        *([prior_becmg[0]] if prior_becmg else []),
        *changing_groups,
    ]
    mechanisms = significant_mechanisms(
        " ".join(group["text"] for group in applicable_groups)
    )
    applicable_conditions = " · ".join(
        dict.fromkeys(_describe_conditions(group["text"]) for group in applicable_groups)
    )
    applicable_conditions = applicable_conditions or "conditions could not be safely decoded"

    if not coverage_complete or not base_groups:
        return {
            "status": "review_required",
            "applicable_conditions": applicable_conditions,
            "timing": (
                f"The CFP TAF does not fully cover "
                f"{_short_range(window_start, window_end)}."
            ),
            "mechanism": "; ".join(mechanisms) or "None safely classified",
            "window_status_text": "Forecast coverage is incomplete — review required.",
        }

    if mechanisms:
        timed_groups = [
            group
            for group in changing_groups
            if significant_mechanisms(group["text"])
        ]
        if timed_groups:
            overlap_start = max(
                window_start,
                min(group["starts_at"] for group in timed_groups),
            )
            overlap_end = min(
                window_end,
                max(group["ends_at"] for group in timed_groups),
            )
            timing = (
                f"{'; '.join(mechanisms)} overlaps "
                f"{_short_range(overlap_start, overlap_end)}."
            )
        else:
            timing = (
                f"Significant conditions are present in the applicable base forecast "
                f"for {_short_range(window_start, window_end)}."
            )
        return {
            "status": "pertinent",
            "applicable_conditions": applicable_conditions,
            "timing": timing,
            "mechanism": "; ".join(mechanisms),
            "window_status_text": (
                f"Forecast weather overlapping this window: {'; '.join(mechanisms)}."
            ),
        }

    outside_groups = [
        group
        for group in groups
        if group["kind"] in {"tempo", "probability"}
        and not _overlaps(
            group["starts_at"],
            group["ends_at"],
            window_start,
            window_end,
        )
        and significant_mechanisms(group["text"])
    ]
    if outside_groups:
        first_outside = sorted(outside_groups, key=lambda group: group["starts_at"])[0]
        outside_mechanisms = significant_mechanisms(first_outside["text"])
        timing = (
            f"{'; '.join(outside_mechanisms)} is forecast "
            f"{_short_range(first_outside['starts_at'], first_outside['ends_at'])}, "
            "outside this window."
        )
    else:
        timing = (
            f"No significant forecast-weather group overlaps "
            f"{_short_range(window_start, window_end)}."
        )
    return {
        "status": "no_significant_overlap",
        "applicable_conditions": applicable_conditions,
        "timing": timing,
        "mechanism": "None in time-overlapping forecast groups",
        "window_status_text": (
            "No significant weather group overlaps this window in the CFP forecast."
        ),
    }


def _metar_observation_time(text: str, reference: datetime) -> datetime | None:
    match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", str(text or "").upper())
    if not match:
        return None
    candidates = _date_candidates(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        reference,
    )
    return min(candidates, key=lambda value: abs(value - reference), default=None)


def summarize_metar_for_window(
    text: str,
    window_start: datetime,
    window_end: datetime,
    *,
    observed_at: datetime | None = None,
) -> dict[str, str] | None:
    """Describe a nearby observation without presenting it as a forecast."""
    observation = observed_at or _metar_observation_time(text, window_start)
    if observation is None:
        return None
    if observation.tzinfo is None:
        observation = observation.replace(tzinfo=timezone.utc)
    observation = observation.astimezone(timezone.utc)
    near_window = (
        window_start - timedelta(hours=2)
        <= observation
        <= window_end + timedelta(minutes=30)
    )
    mechanisms = significant_mechanisms(text)
    conditions = _describe_conditions(text)
    if not near_window:
        return {
            "status": "outside_window",
            "observed_at_utc": observation.isoformat(),
            "applicable_conditions": conditions,
            "mechanism": "; ".join(mechanisms) or "None safely classified",
            "timing": (
                f"Observation at {observation:%H:%MZ} is outside "
                f"{_short_range(window_start, window_end)}."
            ),
            "window_status_text": "Observation retained in audit only.",
        }
    if mechanisms:
        return {
            "status": "pertinent",
            "observed_at_utc": observation.isoformat(),
            "applicable_conditions": conditions,
            "mechanism": "; ".join(mechanisms),
            "timing": f"Observed at {observation:%H:%MZ}.",
            "window_status_text": (
                f"Observed weather near this window: {'; '.join(mechanisms)}."
            ),
        }
    return {
        "status": "no_significant_observation",
        "observed_at_utc": observation.isoformat(),
        "applicable_conditions": conditions,
        "mechanism": "No significant mechanism in the nearby observation",
        "timing": f"Observed at {observation:%H:%MZ}.",
        "window_status_text": (
            "No significant weather mechanism appears in the nearby observation."
        ),
    }


__all__ = [
    "significant_mechanisms",
    "summarize_metar_for_window",
    "summarize_taf_for_window",
]
