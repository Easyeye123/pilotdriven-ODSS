from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .constants import MONTHS, OPERATIONAL_KEYWORDS

_NOTAM_START = re.compile(r"^(?P<id>[A-Z0-9]+/\d{2})\s+VALID:\s+(?P<validity>.+)$")


def _weather_section(pages: list[str]) -> str:
    start = next((i for i, text in enumerate(pages) if "AIRPORT WX LIST" in text.upper()), None)
    if start is None:
        return ""
    end = next(
        (i for i in range(start, len(pages)) if "AIRPORTLIST ENDED" in pages[i].upper()),
        min(start + 12, len(pages) - 1),
    )
    return "\n".join(pages[start:end + 1])


def _extract_station_block(weather_text: str, icao: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(icao)}/[A-Z0-9]{{3}}\s+.*?\n(?P<body>.*?)"
        rf"(?=^[A-Z]{{4}}/[A-Z0-9]{{3}}\s+|^[A-Z][A-Za-z ()/-]+:\s*$|^AIRPORTLIST ENDED|\Z)"
    )
    match = pattern.search(weather_text)
    return match.group("body").strip() if match else ""


def _parse_station_weather(icao: str, block: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current_type: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_type, current_lines
        if current_type and current_lines:
            records.append({
                "location": icao,
                "record_type": current_type,
                "text": " ".join(x.strip() for x in current_lines if x.strip()),
            })
        current_type, current_lines = None, []

    for raw in block.splitlines():
        line = raw.strip()
        if re.match(r"^(SA|FT|FC)\s+", line):
            flush()
            token = line[:2]
            current_type = {"SA": "METAR", "FT": "TAF", "FC": "TAF"}[token]
            current_lines = [line]
        elif current_type and line and not line.startswith(("SIA ", "Page ")):
            current_lines.append(line)
    flush()
    return records


def enrich_weather(flight: dict[str, Any], pages: list[str]) -> None:
    text = _weather_section(pages)
    if not text:
        return
    locations = [flight["departure"], flight["destination"]]
    locations.extend(a["airport"] for a in flight["alternates"])
    locations.extend(a["airport"] for a in flight["edto"]["airports"])
    if "EDDM/MUC" in text:
        locations.append("EDDM")
    for icao in dict.fromkeys(locations):
        flight["weather"].extend(_parse_station_weather(icao, _extract_station_block(text, icao)))

    sigmet = re.search(r"(?ms)^SIGMETs:\s*(?P<body>.*?)(?=^Tropical Cyclone SIGMETs:)", text)
    if sigmet:
        body = " ".join(sigmet.group("body").split())
        if body and "NO WX DATA" not in body.upper():
            fir = re.search(r"\b([A-Z]{4})\s+[A-Z ]+FIR\b", body)
            flight["weather"].append({
                "location": fir.group(1) if fir else "FIR",
                "record_type": "SIGMET",
                "text": body,
            })


def _notam_section(pages: list[str]) -> str:
    start = next(
        (i for i, text in enumerate(pages) if any(line.strip().upper() == "NOTAM" for line in text.splitlines()[:12])),
        None,
    )
    if start is None:
        return ""
    end = next(
        (i for i in range(start + 1, len(pages)) if any(line.strip().upper() == "INTAM" for line in pages[i].splitlines()[:12])),
        len(pages),
    )
    return "\n".join(pages[start:end])


def _parse_notam_datetime(value: str) -> datetime | None:
    value = value.strip().upper().replace(" EST", "")
    match = re.match(r"^(\d{2})-([A-Z]{3})-(\d{2})\s+(\d{4})", value)
    if not match:
        return None
    day, month, year, hhmm = match.groups()
    return datetime(
        2000 + int(year), MONTHS[month], int(day),
        int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc,
    )


def _parse_validity(value: str, fallback: datetime) -> tuple[datetime, datetime | None]:
    parts = re.split(r"\s+-\s+", value, maxsplit=1)
    start = _parse_notam_datetime(parts[0]) or fallback
    if len(parts) == 1 or parts[1].strip().upper().startswith(("UFN", "PERM")):
        return start, None
    return start, _parse_notam_datetime(parts[1])


def _extract_airport_notam_block(notam_text: str, icao: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(icao)}\s*/[A-Z0-9]{{3}}\s+.*?\n[-]+\n(?P<body>.*?)"
        rf"(?=^[A-Z]{{4}}\s*/[A-Z0-9]{{3}}\s+.*?\n[-]+|\Z)"
    )
    match = pattern.search(notam_text)
    return match.group("body") if match else ""


def _notice_score(text: str, category: str) -> int:
    upper = f"{category} {text}".upper()
    return sum(weight for token, weight in OPERATIONAL_KEYWORDS.items() if token in upper)


def _parse_airport_notams(
    icao: str,
    block: str,
    fallback: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    notices: list[tuple[int, dict[str, Any]]] = []
    category = "AIRPORT"
    current_id: str | None = None
    current_validity = ""
    current_category = category
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_id, current_validity, current_category, current_lines
        if not current_id:
            return
        text = " ".join(line.strip() for line in current_lines if line.strip())
        valid_from, valid_to = _parse_validity(current_validity, fallback)
        schedule = next(
            (
                line.strip()
                for line in current_lines[:3]
                if line.strip().upper().startswith(
                    ("DAILY ", "MON-", "TUE-", "WED-", "THU-", "FRI-", "SAT-", "SUN-", "JUL ", "AUG ", "SEP ")
                )
            ),
            None,
        )
        record = {
            "notam_id": current_id,
            "location": icao,
            "category": current_category,
            "text": text,
            "valid_from_utc": valid_from.isoformat(),
            "valid_to_utc": valid_to.isoformat() if valid_to else None,
            "schedule": schedule,
        }
        score = _notice_score(text, current_category)
        if score > 0:
            notices.append((score, record))
        current_id, current_validity, current_lines = None, "", []

    for raw in block.splitlines():
        stripped = raw.strip()
        if stripped.startswith("+") and stripped.endswith("+"):
            flush()
            category = stripped.strip("+ ") or "AIRPORT"
            continue
        match = _NOTAM_START.match(stripped)
        if match:
            flush()
            current_id = match.group("id")
            current_validity = match.group("validity")
            current_category = category
            continue
        if current_id and not stripped.startswith(("SIA ", "Page ")):
            current_lines.append(raw)
    flush()
    notices.sort(key=lambda item: (-item[0], item[1]["notam_id"]))
    return [record for _, record in notices[:limit]]


def enrich_notams(flight: dict[str, Any], pages: list[str]) -> None:
    text = _notam_section(pages)
    if not text:
        return
    limits = {flight["departure"]: 8, flight["destination"]: 10}
    limits.update({a["airport"]: 7 for a in flight["alternates"]})
    limits.update({a["airport"]: 5 for a in flight["edto"]["airports"]})
    if "EDDM /MUC" in text:
        limits["EDDM"] = 5
    fallback = datetime.fromisoformat(flight["scheduled_departure_utc"])
    for icao, limit in limits.items():
        block = _extract_airport_notam_block(text, icao)
        flight["notams"].extend(_parse_airport_notams(icao, block, fallback, limit))
