from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .constants import MONTHS, OPERATIONAL_KEYWORDS

_NOTAM_START = re.compile(r"^(?P<id>[A-Z0-9]+/\d{2})\s+VALID:\s+(?P<validity>.+)$")
_SCHEDULE_LINE = re.compile(
    r"^(?:DAILY|DLY|MON|TUE|WED|THU|FRI|SAT|SUN|"
    r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b"
)
_FUEL_ENROUTE_HEADING = re.compile(
    r"^FUEL\s+ENROUTE\s+AIRPORT(?:\(S\)|S)?\s*:?\s*$",
    re.IGNORECASE,
)
_AIRPORT_SECTION_HEADING = re.compile(
    r"^(?:(?:DEPARTURE|DESTINATION|ALTERNATE|DESTINATION\s+ALTERNATE|"
    r"FUEL\s+ENROUTE|ENROUTE|EDTO\s+SUITABLE\s+ENROUTE)\s+)"
    r"AIRPORT(?:\(S\)|S)?\s*:?\s*$",
    re.IGNORECASE,
)
_STATION_HEADER = re.compile(
    r"^(?P<icao>[A-Z]{4})\s*/\s*(?P<iata>[A-Z0-9]{3})"
    r"(?:\s+(?P<name>.+?))?\s*$",
    re.IGNORECASE,
)


def _record_source_page(pages: list[str], value: str) -> int | None:
    """Locate a parsed source record without relying on flight-specific text."""
    tokens = " ".join(str(value or "").split()).upper().split()
    if not tokens:
        return None
    # A bounded leading fragment survives PDF whitespace normalization while
    # remaining specific enough for METAR, TAF, SIGMET and NOTAM records.
    needle = " ".join(tokens[:12])
    for page_number, page in enumerate(pages, start=1):
        if needle in " ".join(page.split()).upper():
            return page_number
    return None


def _weather_section_bounds(pages: list[str]) -> tuple[int, int] | None:
    start = next((i for i, text in enumerate(pages) if "AIRPORT WX LIST" in text.upper()), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start, len(pages)) if "AIRPORTLIST ENDED" in pages[i].upper()),
        min(start + 12, len(pages) - 1),
    )
    return start, end + 1


def _weather_section(pages: list[str]) -> str:
    bounds = _weather_section_bounds(pages)
    if bounds is None:
        return ""
    start, end = bounds
    return "\n".join(pages[start:end])


def _fuel_enroute_stations(section_text: str) -> list[dict[str, str]]:
    """Read station identities only from a dedicated fuel-enroute section.

    An ICAO-like token elsewhere in a bulletin is not enough.  The section
    heading opens the scope and the next airport-section heading closes it,
    which keeps the discovery generic without promoting route or FIR text.
    """
    stations: list[dict[str, str]] = []
    seen: set[str] = set()
    in_fuel_section = False
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if _FUEL_ENROUTE_HEADING.fullmatch(line):
            in_fuel_section = True
            continue
        if in_fuel_section and _AIRPORT_SECTION_HEADING.fullmatch(line):
            in_fuel_section = False
            continue
        if not in_fuel_section:
            continue
        match = _STATION_HEADER.fullmatch(line)
        if not match:
            continue
        icao = match.group("icao").upper()
        if icao in seen:
            continue
        seen.add(icao)
        name = re.sub(
            r"\s*/\s*ADEQ\s*$",
            "",
            str(match.group("name") or "").strip(),
            flags=re.IGNORECASE,
        )
        stations.append({
            "airport": icao,
            "iata": match.group("iata").upper(),
            "name": name,
            "role": "fuel_enroute_airport",
        })
    return stations


def _station_header_source_pages(
    pages: list[str],
    bounds: tuple[int, int] | None,
    station: dict[str, str],
) -> list[int]:
    if bounds is None:
        return []
    start, end = bounds
    pattern = re.compile(
        rf"(?m)^\s*{re.escape(station['airport'])}\s*/\s*"
        rf"{re.escape(station['iata'])}\b",
        re.IGNORECASE,
    )
    return [
        page_index + 1
        for page_index in range(start, end)
        if pattern.search(pages[page_index])
    ]


def _register_fuel_enroute_station(
    flight: dict[str, Any],
    station: dict[str, str],
    source_kind: str,
    source_pages: list[int],
) -> None:
    airports = flight.setdefault("fuel_enroute_airports", [])
    existing = next(
        (
            item
            for item in airports
            if str(item.get("airport") or "").upper() == station["airport"]
        ),
        None,
    )
    if existing is None:
        existing = dict(station)
        airports.append(existing)
    else:
        for key in ("iata", "name", "role"):
            if station.get(key) and not existing.get(key):
                existing[key] = station[key]
    page_key = f"{source_kind}_source_pages"
    existing[page_key] = sorted({
        *(
            page
            for page in existing.get(page_key, [])
            if isinstance(page, int)
        ),
        *source_pages,
    })
    existing["source_pages"] = sorted({
        *(
            page
            for page in existing.get("source_pages", [])
            if isinstance(page, int)
        ),
        *source_pages,
    })


def _extract_station_block(weather_text: str, icao: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(icao)}\s*/\s*[A-Z0-9]{{3}}\s+.*?\n(?P<body>.*?)"
        rf"(?=^[A-Z]{{4}}\s*/\s*[A-Z0-9]{{3}}\s+|^[A-Z][A-Za-z ()/-]+:\s*$|^AIRPORTLIST ENDED|\Z)"
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
    fuel_stations = _discover_fuel_enroute_stations(flight, pages)
    fuel_icaos = {station["airport"] for station in fuel_stations}
    locations = [flight["departure"], flight["destination"]]
    locations.extend(a["airport"] for a in flight["alternates"])
    locations.extend(a["airport"] for a in flight["edto"]["airports"])
    locations.extend(station["airport"] for station in fuel_stations)
    if "EDDM/MUC" in text:
        locations.append("EDDM")
    for icao in dict.fromkeys(locations):
        records = _parse_station_weather(icao, _extract_station_block(text, icao))
        for record in records:
            record["source_page"] = _record_source_page(pages, record["text"])
            if icao in fuel_icaos:
                record["source_role"] = "fuel_enroute_airport"
        flight["weather"].extend(records)

    # The CFP's dedicated volcanic-ash section. Captured verbatim so the
    # briefing can NAME the hazard ("VOLCANIC ASH - MT KRAKATAU - WV SIGMET
    # 08") instead of a generic advisory line - the 18 Aug label defect.
    volcanic = re.search(
        r"(?ms)^Volcanic Ash SIGMETs:\s*(?P<body>.*?)(?=^(?:[A-Z][A-Za-z ]+ SIGMETs:|DESTINATION AIRPORT:|[A-Z]{4}/))",
        text,
    )
    if volcanic:
        body = " ".join(volcanic.group("body").split())
        if body and "NO WX DATA" not in body.upper():
            fir = re.search(r"\b([A-Z]{4})\s+[A-Z ]+FIR\b", body)
            flight["weather"].append({
                "location": fir.group(1) if fir else "FIR",
                "record_type": "VA_SIGMET",
                "text": body,
                "source_page": _record_source_page(pages, body),
            })

    sigmet = re.search(r"(?ms)^SIGMETs:\s*(?P<body>.*?)(?=^Tropical Cyclone SIGMETs:)", text)
    if sigmet:
        body = " ".join(sigmet.group("body").split())
        if body and "NO WX DATA" not in body.upper():
            fir = re.search(r"\b([A-Z]{4})\s+[A-Z ]+FIR\b", body)
            flight["weather"].append({
                "location": fir.group(1) if fir else "FIR",
                "record_type": "SIGMET",
                "text": body,
                "source_page": _record_source_page(pages, body),
            })


def _notam_section_bounds(pages: list[str]) -> tuple[int, int] | None:
    start = next(
        (i for i, text in enumerate(pages) if any(line.strip().upper() == "NOTAM" for line in text.splitlines()[:12])),
        None,
    )
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(pages)) if any(line.strip().upper() == "INTAM" for line in pages[i].splitlines()[:12])),
        len(pages),
    )
    return start, end


def _notam_section(pages: list[str]) -> str:
    bounds = _notam_section_bounds(pages)
    if bounds is None:
        return ""
    start, end = bounds
    return "\n".join(pages[start:end])


def _discover_fuel_enroute_stations(
    flight: dict[str, Any],
    pages: list[str],
) -> list[dict[str, Any]]:
    """Union fuel-enroute identities across weather and NOTAM appendices.

    LIDO may print the dedicated role heading in only one appendix. Once an
    identity is established there, a same-ICAO station block in the other
    appendix remains part of that role and cannot be silently dropped.
    """
    sources = (
        ("weather", _weather_section_bounds(pages), _weather_section(pages)),
        ("notam", _notam_section_bounds(pages), _notam_section(pages)),
    )
    for source_kind, bounds, section_text in sources:
        for station in _fuel_enroute_stations(section_text):
            _register_fuel_enroute_station(
                flight,
                station,
                source_kind,
                _station_header_source_pages(pages, bounds, station),
            )

    # Re-scan both appendices with the now-unioned identities. This captures
    # the counterpart block even when that appendix labels it only ENROUTE.
    for station in list(flight.get("fuel_enroute_airports") or []):
        if not station.get("iata"):
            continue
        for source_kind, bounds, _ in sources:
            source_pages = _station_header_source_pages(pages, bounds, station)
            if source_pages:
                _register_fuel_enroute_station(
                    flight,
                    station,
                    source_kind,
                    source_pages,
                )
    return list(flight.get("fuel_enroute_airports") or [])


def _parse_notam_datetime(value: str) -> datetime | None:
    value = value.strip().upper().replace(" EST", "")
    match = re.match(r"^(\d{2})-([A-Z]{3})-(\d{2})\s+(\d{4})", value)
    if not match:
        return None
    day, month, year, hhmm = match.groups()
    month_number = MONTHS.get(month)
    if month_number is None:
        return None
    try:
        return datetime(
            2000 + int(year), month_number, int(day),
            int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _parse_validity(value: str, fallback: datetime) -> tuple[datetime, datetime | None, bool]:
    parts = re.split(r"\s+-\s+", value, maxsplit=1)
    parsed_start = _parse_notam_datetime(parts[0])
    start = parsed_start or fallback
    if len(parts) == 1 or parts[1].strip().upper().startswith(("UFN", "PERM")):
        return start, None, parsed_start is not None
    parsed_end = _parse_notam_datetime(parts[1])
    return start, parsed_end, parsed_start is not None and parsed_end is not None


def _extract_airport_notam_block(notam_text: str, icao: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(icao)}\s*/[A-Z0-9]{{3}}\s+.*?\n[-]+\n(?P<body>.*?)"
        rf"(?=^[A-Z]{{4}}\s*/[A-Z0-9]{{3}}\s+.*?\n[-]+|\Z)"
    )
    match = pattern.search(notam_text)
    return match.group("body") if match else ""


def _notice_score(text: str, category: str) -> int:
    upper = f"{category} {text}".upper()
    return sum(
        weight
        for token, weight in OPERATIONAL_KEYWORDS.items()
        if re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", upper)
    )


def _has_schedule_language(text: str) -> bool:
    return bool(
        re.search(r"\b(?:DAILY|DLY|EV|EVERY|MON|TUE|WED|THU|FRI|SAT|SUN)\b", text, re.IGNORECASE)
        and re.search(r"\b\d{4}(?:UTC|Z)?\s*(?:-|TO)\s*\d{4}(?:UTC|Z)?\b", text, re.IGNORECASE)
    )


def _parse_airport_notams(
    icao: str,
    block: str,
    fallback: datetime,
    *,
    include_all: bool = False,
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
        valid_from, valid_to, validity_parsed = _parse_validity(current_validity, fallback)
        schedule_lines = [
            line.strip().rstrip(".")
            for line in current_lines
            if _SCHEDULE_LINE.match(line.strip().upper())
            and re.search(r"\b\d{4}(?:UTC|Z)?\s*-\s*\d{4}(?:UTC|Z)?\b", line, re.IGNORECASE)
        ]
        schedule = "; ".join(schedule_lines) or None
        schedule_review = schedule is None and _has_schedule_language(text)
        score = _notice_score(text, current_category)
        record = {
            "notam_id": current_id,
            "location": icao,
            "category": current_category,
            "text": text,
            "valid_from_utc": valid_from.isoformat(),
            "valid_to_utc": valid_to.isoformat() if valid_to else None,
            "schedule": schedule,
            "schedule_review": schedule_review,
            "validity_review": not validity_parsed,
            "priority_score": score,
        }
        if include_all or score > 0:
            notices.append((score, record))
        current_id, current_validity, current_lines = None, "", []

    for raw in block.splitlines():
        stripped = raw.strip()
        if _AIRPORT_SECTION_HEADING.fullmatch(stripped):
            flush()
            break
        if re.fullmatch(r"[=-]{3,}", stripped):
            continue
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
    return [record for _, record in notices]


def enrich_notams(flight: dict[str, Any], pages: list[str]) -> None:
    text = _notam_section(pages)
    if not text:
        return
    fuel_stations = _discover_fuel_enroute_stations(flight, pages)
    fuel_icaos = {station["airport"] for station in fuel_stations}
    locations = [flight["departure"], flight["destination"]]
    locations.extend(a["airport"] for a in flight["alternates"])
    locations.extend(a["airport"] for a in flight["edto"]["airports"])
    locations.extend(station["airport"] for station in fuel_stations)
    if "EDDM /MUC" in text:
        locations.append("EDDM")
    fallback = datetime.fromisoformat(flight["scheduled_departure_utc"])
    for icao in dict.fromkeys(locations):
        block = _extract_airport_notam_block(text, icao)
        records = _parse_airport_notams(
            icao,
            block,
            fallback,
            include_all=icao in fuel_icaos,
        )
        for record in records:
            record["source_page"] = _record_source_page(pages, record["notam_id"])
            if icao in fuel_icaos:
                record["source_role"] = "fuel_enroute_airport"
        flight["notams"].extend(records)
