from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import fitz

from .constants import actm_minutes, date_ddmmmyy, utc_on_date
from .enrichment import enrich_notams, enrich_weather

MAX_PDF_PAGES = 180


def extract_pages(path: Path) -> list[str]:
    document = fitz.open(str(path))
    try:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if document.page_count < 1:
            raise ValueError("PDF has no pages")
        if document.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page OFP limit")
        return [page.get_text("text") for page in document]
    finally:
        document.close()


def validate_pdf(path: Path) -> None:
    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise ValueError("File is not a readable PDF") from exc
    try:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if document.page_count < 1:
            raise ValueError("PDF has no pages")
        if document.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page OFP limit")
        document.load_page(0)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("File is not a readable PDF") from exc
    finally:
        document.close()


def _int_group(text: str, pattern: str, default: int | None = None) -> int | None:
    match = re.search(pattern, text, re.MULTILINE)
    return int(match.group(1)) if match else default


def _first_group(text: str, *patterns: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def _weight_group_kg(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    value = float(match.group("value"))
    unit = (match.groupdict().get("unit") or "").upper()
    kilograms = round(value * 1000) if unit == "T" else round(value)
    return kilograms if 50_000 <= kilograms <= 500_000 else None


def _line_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    value = match.group("value").strip().rstrip(".") if match else ""
    return value or None


def _parse_performance(perf_text: str) -> dict[str, Any]:
    runway_line = re.search(
        r"^\s*RWY\s*:\s*(?P<runway>[0-9]{2}[LCR]?)"
        r"(?:\s+(?P<condition>DRY|WET|CONTAMINATED))?\b",
        perf_text,
        re.MULTILINE | re.IGNORECASE,
    )
    runway_table = re.search(
        r"^\s*[A-Z]{4}\s+RWY\s+(?P<runway>[0-9]{2}[LCR]?)\b",
        perf_text,
        re.MULTILINE,
    )
    condition = _line_value(
        perf_text,
        r"^\s*RWY\s+COND\s*:[ \t]*(?P<value>[^\n]*)$",
    )
    if not condition and runway_line:
        condition = runway_line.group("condition")
    return {
        "runway": (
            runway_line.group("runway").upper()
            if runway_line
            else runway_table.group("runway").upper()
            if runway_table
            else None
        ),
        "runway_condition": condition.upper() if condition else None,
        "thrust_setting": _line_value(
            perf_text,
            r"\bT/O\s+THR\s*:[ \t]*(?P<value>\S+)",
        )
        or ("FULL" if "STD RATING: FULL" in perf_text else None),
        "flap_setting": _int_group(perf_text, r"FLAPS\s+(\d+)"),
        "temperature_c": _int_group(
            perf_text,
            r"(?:PLAN\s+TEMP\s+P|^\s*OAT\s*:[ \t]*)(\d+)\s*C?\b",
        ),
        "qnh_hpa": _int_group(
            perf_text,
            r"(?:PLAN\s+QNH|^\s*QNH\s*:[ \t]*)(\d+)\s*(?:HPA)?\b",
        ),
        "wind": _line_value(
            perf_text,
            r"^\s*(?:PLAN\s+)?WIND\s*:[ \t]*(?P<value>\S+)",
        ),
        "packs_on": (
            True
            if re.search(r"\b(?:PACKS|A/C)\s*(?::\s*)?ON\b", perf_text)
            else None
        ),
        "anti_ice_on": (
            False
            if re.search(r"\b(?:ANTI-ICE|A/ICE)\s*(?::\s*)?OFF\b", perf_text)
            else True
            if re.search(r"\b(?:ANTI-ICE|A/ICE)\s*(?::\s*)?ON\b", perf_text)
            else None
        ),
        "eosid": _line_value(
            perf_text,
            r"^\s*EOSID\s*:[ \t]*(?P<value>[^\n]*)$",
        ),
        "obstacle_rtow_kg": _weight_group_kg(
            perf_text,
            r"RTOW\(PERF\)\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>T)?\b",
        ),
        "landing_rtow_kg": _weight_group_kg(
            perf_text,
            r"RTOW\(LAND\)\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>T)?\b",
        ),
        "maximum_landing_weight_kg": _weight_group_kg(
            perf_text,
            r"\bMLGW\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>T)?\b",
        ),
        "structural_rtow_kg": _weight_group_kg(
            perf_text,
            r"RTOW\(STRUC\)\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>T)?\b",
        ),
        "controlling_rtow_kg": _weight_group_kg(
            perf_text,
            r"^\s*RTOW\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>T)?\s*$",
        ),
        "maximum_fuel_available_kg": _int_group(
            perf_text,
            r"MAX FUEL AVAIL:\s*0*(\d+)",
        ),
    }


def _detect_sections(pages: list[str]) -> dict[str, tuple[int, int]]:
    starts: list[tuple[str, int]] = []
    for index, text in enumerate(pages):
        top = "\n".join(text.splitlines()[:10]).upper()
        if "ATC FLIGHT PLAN" in top:
            starts.append(("atc", index))
        elif "AIRPORT WX LIST" in top:
            starts.append(("weather", index))
        elif any(line.strip() == "NOTAM" for line in top.splitlines()):
            starts.append(("notam", index))
        elif any(line.strip() == "INTAM" for line in top.splitlines()):
            starts.append(("intam", index))
        elif index == 0 or "SUMMARY EDTO CFP" in top or "SUMMARY CFP" in top:
            if not any(name == "cfp" for name, _ in starts):
                starts.append(("cfp", index))
    starts.sort(key=lambda item: item[1])
    return {
        name: (start, starts[i + 1][1] if i + 1 < len(starts) else len(pages))
        for i, (name, start) in enumerate(starts)
    }


_INTAM_HEADER = re.compile(
    r"^\s*(?P<priority>\d+)\.\s*(?P<category>[A-Z]+)\s+"
    r"(?P<identity>.+?)\s+(?P<date>\d{6,8})\s*$"
)


def _parse_intam_records(
    pages: list[str],
    bounds: tuple[int, int] | None,
) -> list[dict[str, Any]]:
    """Hold bounded INTAM records without relevance inference.

    The company-bulletin appendix is source evidence, not a clearance engine.
    Each printed record retains its complete header, headline, body text and
    physical CFP page.  Body continuation across physical pages is preserved;
    no renderer has to invent an action from a headline alone.
    """
    if bounds is None:
        return []
    start, end = bounds
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    headline_lines: list[str] = []
    body_lines: list[str] = []
    headline_complete = False

    def flush() -> None:
        nonlocal current, headline_lines, body_lines, headline_complete
        if current is not None:
            records.append({
                **current,
                "headline": " ".join(headline_lines),
                "body_text": " ".join(body_lines),
            })
        current = None
        headline_lines = []
        body_lines = []
        headline_complete = False

    for page_index in range(start, end):
        lines = pages[page_index].splitlines()
        for line in lines:
            match = _INTAM_HEADER.match(line)
            if match:
                flush()
                current = {
                    "priority": int(match.group("priority")),
                    "category": match.group("category"),
                    "identity": match.group("identity").strip(),
                    "date_token": match.group("date"),
                    "header": " ".join(line.split()),
                    "source_page": page_index + 1,
                }
                continue
            if current is None:
                continue
            stripped = line.strip()
            if not stripped:
                if headline_lines:
                    headline_complete = True
                continue
            if (
                re.fullmatch(r"[-=]{3,}", stripped)
                or stripped.startswith(("SIA ", "Page "))
            ):
                continue
            normalized = " ".join(stripped.split())
            if not headline_complete and len(headline_lines) < 4:
                headline_lines.append(normalized)
            else:
                headline_complete = True
                body_lines.append(normalized)
    flush()
    return records


_NOTAM_PROCEDURE_HEADER = re.compile(
    r"^\s*(?P<identity>[A-Z0-9]+/\d{2})\s+VALID:\s*(?P<validity>.+?)\s*$",
    re.IGNORECASE,
)
_NOTAM_FIR_HEADING = re.compile(
    r"^(?P<icao>[A-Z]{4})\s+(?P<name>[A-Z][A-Z0-9 /().,'-]*\bFIR)\s*$",
    re.IGNORECASE,
)


def _parse_notam_procedure_records(
    pages: list[str],
    bounds: tuple[int, int] | None,
) -> list[dict[str, Any]]:
    """Retain source NOTAM records that explicitly print datalink procedure.

    Selection requires both a named FIR heading and printed
    ``CPDLC``/``ADS-C`` tokens.  The record is not claimed route-applicable;
    it is held for pilot review with its identity, section heading, physical
    page and complete source prose.  Airport or generic section records never
    inherit a previous FIR heading.
    """
    if bounds is None:
        return []
    start, end = bounds
    records: list[dict[str, Any]] = []
    heading: str | None = None
    current: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            body = " ".join(body_lines).strip()
            if re.search(r"\b(?:CPDLC|ADS-C)\b", body, re.IGNORECASE):
                records.append({
                    **current,
                    "text": body,
                    "applicability": "not_inferred",
                })
        current = None
        body_lines = []

    for page_index in range(start, end):
        lines = pages[page_index].splitlines()
        for line_index, line in enumerate(lines):
            stripped = line.strip()
            underlined_heading = (
                stripped
                and line_index + 1 < len(lines)
                and re.fullmatch(r"[-=]{3,}", lines[line_index + 1].strip())
                and not _NOTAM_PROCEDURE_HEADER.match(stripped)
            )
            if underlined_heading:
                flush()
                heading = (
                    " ".join(stripped.split())
                    if _NOTAM_FIR_HEADING.fullmatch(stripped)
                    else None
                )
                continue
            declaration = _NOTAM_PROCEDURE_HEADER.match(stripped)
            if declaration:
                flush()
                if heading is not None:
                    current = {
                        "notam_id": declaration.group("identity").upper(),
                        "validity": " ".join(declaration.group("validity").split()),
                        "heading": heading,
                        "source_page": page_index + 1,
                    }
                continue
            if (
                current is not None
                and stripped
                and not re.fullmatch(r"[-=]{3,}", stripped)
                and not stripped.startswith(("SIA ", "Page "))
            ):
                body_lines.append(" ".join(stripped.split()))
    flush()
    return records


def _parse_deferred_items(page1: str) -> list[dict[str, Any]]:
    # Boss's 21 Aug 2026 SQ910 CFP printed four declaration shapes on one
    # block: "CC MEL 25-20-50A", bare "BB CDDL" (no reference), "AA IFEDDL"
    # and "DD IN SIA/00-017 R1" (engineering information notice). Every
    # prefixed declaration is a first-class item under the CFP's own word —
    # never "UNCLASSIFIED"/"UNSPECIFIED", and never folded into the previous
    # item's remark (that is how the ENG 2 fan-cowl notice vanished).
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in page1.splitlines():
        stripped = line.strip()
        match = re.match(
            # Reference and trailing description are both optional, and the
            # description may follow with or without a dash ("CC MEL PREAMBLE
            # SECTION MEL AND CMS REV 18NOV 25" — SQ366 4 Aug shape).
            r"^(AA|BB|CC|DD|EE)\s+(CDDL|CDL|MEL)"
            r"(?:\s+([0-9A-Z-]+))?(?:\s*-\s*(.*\S)|\s+(\S.*\S|\S))?\s*$",
            stripped,
        )
        ifeddl = re.fullmatch(r"(AA|BB|CC|DD|EE)\s+IFEDDL", stripped)
        notice = re.fullmatch(r"(AA|BB|CC|DD|EE)\s+IN\s+([0-9A-Z/-]+(?:\s+R\d+)?)", stripped)
        if match:
            if current:
                items.append(current)
            current = {
                "reference": match.group(3) or None,
                "description": (match.group(4) or match.group(5) or "").strip(),
                "item_type": match.group(2),
                "source_declaration": stripped,
                "company_remark": None,
            }
            continue
        if ifeddl:
            if current:
                items.append(current)
            current = {
                "reference": None,
                "description": "",
                "item_type": "IFEDDL",
                "source_declaration": stripped,
                "company_remark": None,
            }
            continue
        if notice:
            if current:
                items.append(current)
            current = {
                "reference": notice.group(2),
                "description": "",
                "item_type": "IN",
                "source_declaration": stripped,
                "company_remark": None,
            }
            continue
        if current:
            if stripped.startswith("PLAN ") or stripped.startswith("RTE NO"):
                items.append(current)
                current = None
                break
            if stripped:
                if not current["description"]:
                    current["description"] = stripped
                else:
                    current["company_remark"] = f"{current['company_remark'] or ''} {stripped}".strip()
    if current:
        items.append(current)
    return items


def _parse_route_text(page1: str) -> str:
    route_lines: list[str] = []
    collecting = False
    for line in page1.splitlines():
        stripped = line.strip()
        if re.match(r"^[A-Z]{4}/[0-9A-Z]{2,3}\b", stripped):
            collecting = True
        if collecting:
            if re.match(r"^[A-Z]{3}/\d{3}(?:/|$)", stripped):
                break
            route_lines.append(stripped)
    return " ".join(route_lines)


def _parse_named_procedure(
    cfp_pages: list[str],
    label: str,
) -> tuple[str | None, int | None]:
    """Return the CFP-declared SID/STAR name and its one-based source page.

    Lido prints the procedure after an airport/runway token, for example
    ``SID: WSSS/20C VMR9B``.  The airport and runway are evidence for the
    procedure, not the procedure name itself, so the report must retain the
    final token rather than substituting WSSS or VTBS.
    """

    line_pattern = re.compile(
        rf"^\s*{re.escape(label)}\s*:\s*(?P<body>[^\r\n]*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    airport_runway = re.compile(
        r"^[A-Z]{4}/[0-9]{2}[LCR]?\b(?P<remainder>.*)$",
        re.IGNORECASE,
    )
    bare_procedure = re.compile(
        r"^(?P<procedure>[A-Z0-9][A-Z0-9-]*)\b",
        re.IGNORECASE,
    )
    unavailable_values = {
        "NIL",
        "NONE",
        "N/A",
        "NA",
        "NOT APPLICABLE",
        "NOT AVAILABLE",
        "NOT STATED",
    }

    def is_unavailable(value: str) -> bool:
        normalized = " ".join(value.upper().split())
        return any(
            normalized == placeholder or normalized.startswith(f"{placeholder} ")
            for placeholder in unavailable_values
        )

    for page_number, page in enumerate(cfp_pages, start=1):
        for match in line_pattern.finditer(page):
            body = match.group("body").strip()
            if not body or is_unavailable(body):
                continue

            airport_match = airport_runway.match(body)
            if airport_match:
                # An airport/runway token is context, never a procedure name.
                body = airport_match.group("remainder").strip()
                if not body or is_unavailable(body):
                    continue

            bare_match = bare_procedure.match(body)
            if not bare_match:
                continue
            procedure = bare_match.group("procedure")

            procedure = procedure.upper()
            if is_unavailable(procedure):
                continue
            return procedure, page_number
    return None, None


def _parse_alternates(cfp_pages: list[str]) -> list[dict[str, Any]]:
    # The alternate table spills past the first page on long-haul plans, so the
    # whole CFP section is scanned. The scan stays inside that section, never
    # the NOTAM or weather sections, so unrelated rows cannot match.
    section_text = "\n".join(cfp_pages)
    pattern = re.compile(
        r"^(?P<apt>[A-Z]{4})/(?P<rwy>[0-9A-Z]{2,3})[ \t]+"
        r"(?P<approach>[A-Z0-9][A-Z0-9+./-]*(?:[ \t]+[A-Z0-9][A-Z0-9+./-]*)*?)[ \t]+"
        r"(?P<minima>\S+)[ \t]+(?P<dist>\d{4})[ \t]+\d{3}[ \t]+[MP]\d{3}[ \t]+"
        r"(?P<time>\d{4})[ \t]+(?P<fuel>\d{5})$",
        re.MULTILINE,
    )
    alternates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for match in pattern.finditer(section_text):
        # A summary page can restate the same row; keep the first occurrence.
        key = (match.group("apt"), match.group("rwy"), match.group("approach"))
        if key in seen:
            continue
        seen.add(key)
        alternates.append({
            "airport": match.group("apt"),
            "runway": match.group("rwy"),
            "approach": " ".join(match.group("approach").split()),
            "minima": match.group("minima"),
            "distance_nm": int(match.group("dist")),
            "time_minutes": int(match.group("time")[:2]) * 60 + int(match.group("time")[2:]),
            "fuel_kg": int(match.group("fuel")),
        })
    return alternates


def _decimal_coordinate(hemisphere: str, degrees: str, minutes: str) -> float:
    value = int(degrees) + float(minutes) / 60
    return -value if hemisphere in {"S", "W"} else value


def _parse_edto_sectors(edto_text: str) -> list[dict[str, Any]]:
    boundary_pattern = re.compile(
        r"^\s*(?P<actm>\d{1,2}\.\d{2})\s+"
        r"(?P<lat_h>[NS])(?P<lat_deg>\d{2})(?P<lat_min>\d{2}(?:\.\d+)?)\b[^\n]*\n"
        # Lido prints either numbered boundaries (ENTRY1/EXIT1) or an
        # unnumbered dotted form (ENTRY...../EXIT .....), depending on the
        # route and CFP revision. Both are the same operational declaration.
        r"\s*(?P<kind>ENTRY|EXIT)(?P<number>\d+)?\s*\.*\s+"
        r"(?P<lon_h>[EW])(?P<lon_deg>\d{3})(?P<lon_min>\d{2}(?:\.\d+)?)\b",
        re.MULTILINE,
    )
    sectors_by_number: dict[int, dict[str, Any]] = {}
    next_implicit_number = 1
    open_implicit_number: int | None = None
    for match in boundary_pattern.finditer(edto_text):
        kind = match.group("kind").lower()
        printed_number = match.group("number")
        if printed_number:
            number = int(printed_number)
        elif kind == "entry":
            while next_implicit_number in sectors_by_number:
                next_implicit_number += 1
            number = next_implicit_number
            open_implicit_number = number
        else:
            unmatched = [
                number
                for number, sector in sectors_by_number.items()
                if sector.get("entry") and not sector.get("exit")
            ]
            number = (
                open_implicit_number
                if open_implicit_number in unmatched
                else unmatched[-1]
                if unmatched
                else next_implicit_number
            )
            open_implicit_number = None
            next_implicit_number = max(next_implicit_number, number + 1)
        point = {
            "name": f"{match.group('kind')}{number}",
            "actm_minutes": actm_minutes(match.group("actm")),
            "latitude": _decimal_coordinate(
                match.group("lat_h"),
                match.group("lat_deg"),
                match.group("lat_min"),
            ),
            "longitude": _decimal_coordinate(
                match.group("lon_h"),
                match.group("lon_deg"),
                match.group("lon_min"),
            ),
        }
        sector = sectors_by_number.setdefault(number, {
            "number": number,
            "entry": None,
            "exit": None,
            "etps": [],
        })
        sector[kind] = point

    etp_pattern = re.compile(
        r"^\s*(?P<actm>\d{1,2}\.\d{2})\s+"
        r"(?P<lat_h>[NS])(?P<lat_deg>\d{2})(?P<lat_min>\d{2}(?:\.\d+)?)\s+"
        r"(?P<airport_one>[A-Z]{4})\b[^\n]*\n"
        r"\s*(?P<label>\d+[A-Z])\s+\.*\s*"
        r"(?P<lon_h>[EW])(?P<lon_deg>\d{3})(?P<lon_min>\d{2}(?:\.\d+)?)"
        r"(?:\s+(?P<airport_two>[A-Z]{4}))?",
        re.MULTILINE,
    )
    for match in etp_pattern.finditer(edto_text):
        actm = actm_minutes(match.group("actm"))
        point = {
            "label": match.group("label"),
            "actm_minutes": actm,
            "latitude": _decimal_coordinate(
                match.group("lat_h"),
                match.group("lat_deg"),
                match.group("lat_min"),
            ),
            "longitude": _decimal_coordinate(
                match.group("lon_h"),
                match.group("lon_deg"),
                match.group("lon_min"),
            ),
            "airports": [
                airport
                for airport in (
                    match.group("airport_one"),
                    match.group("airport_two"),
                )
                if airport
            ],
        }
        containing = next(
            (
                sector
                for sector in sectors_by_number.values()
                if sector.get("entry")
                and sector.get("exit")
                and sector["entry"]["actm_minutes"] <= actm <= sector["exit"]["actm_minutes"]
            ),
            None,
        )
        if containing is not None:
            containing["etps"].append(point)

    sectors: list[dict[str, Any]] = []
    for number, sector in sorted(sectors_by_number.items()):
        entry = sector.get("entry")
        exit_point = sector.get("exit")
        if not entry or not exit_point:
            continue
        etps = sorted(
            sector.get("etps") or [],
            key=lambda item: (
                item["actm_minutes"],
                item["label"],
                item["latitude"],
                item["longitude"],
            ),
        )
        sectors.append({
            "number": number,
            "entry_actm_minutes": entry["actm_minutes"],
            "exit_actm_minutes": exit_point["actm_minutes"],
            "etp_actm_minutes": sorted({item["actm_minutes"] for item in etps}),
            "entry": entry,
            "exit": exit_point,
            "etps": etps,
        })
    return sectors


_WAYPOINT_LINE = re.compile(
    r"^(?P<name>\*\*ETP\S*|-[A-Z0-9]+|\d{1,2}[NS]\d{2,3}|[A-Z][A-Z0-9]{1,8}|TOC|TOD|ENTRY\d|EXIT\d)"
    r"(?:\s+\d{3}(?:\.\d+)?)?\s+(?P<actm>\d{2}\.\d{2})\b"
)
_COORDINATE_LINE = re.compile(
    r"^(?P<lat_hem>[NS])(?P<lat_deg>\d{2})\s+(?P<lat_min>\d{2}\.\d+)\s+"
    r"(?P<lon_hem>[EW])(?P<lon_deg>\d{3})\s+(?P<lon_min>\d{2}\.\d+)\s+"
    r"(?P<msa>\d{3})(?P<star>\*)?"
)
# Sensitivity and command lines on CFP page 1. LIDO prints the ZFW line in two
# shapes — "ZFW CHANGE / M1000KG BURN LESS 454 KG" and the dual-direction
# "ZFW CHANGE P1000KG BURN ADD 96KG / M1000KG BURN LESS 96 KG" — both carry
# the same per-1000kg figure, so the first burn value wins.
_ZFW_BURN_RE = re.compile(
    r"ZFW\s+CHANGE\s+(?:/\s*)?[PM]?1000KG\s+BURN\s+(?:ADD|LESS|MORE)\s+0*(?P<kg>\d+)\s*KG"
)
_ZFW_DUAL_SENSITIVITY_RE = re.compile(
    r"ZFW\s+CHANGE\s+P1000KG\s+BURN\s+ADD\s+0*(?P<add_kg>\d+)\s*KG"
    r"\s*/\s*M1000KG\s+BURN\s+LESS\s+0*(?P<less_kg>\d+)\s*KG",
    re.IGNORECASE,
)
_LOWER_CRUISE_SENSITIVITY_RE = re.compile(
    r"(?P<offset_ft>\d+)\s*FT\s+BELOW\s+AT\s+CI(?P<cost_index>\d+)"
    r"\s+BURN\s+ADD\s+0*(?P<burn_add_kg>\d+)\s*KG"
    r"\s*/\s*TIME\s+(?P<time>\d{1,2}\.\d{2})",
    re.IGNORECASE,
)
_FLIGHT_PLANNING_ETP_RE = re.compile(
    r"\bETP\s*(?P<label>[A-Z0-9]+)\s+"
    r"(?P<from>[A-Z]{3})\s*/\s*(?P<to>[A-Z]{3})\s+"
    r"DIST\s+(?P<distance_nm>\d+)\s*NM\s+"
    r"EET\s+(?P<eet>\d{1,2}\.\d{2})\b",
    re.IGNORECASE,
)
# "CAPT CHAN K B DAVID" at end of the plan line; the signature placeholder
# "CAPT(SIGN) ..." never matches because no whitespace follows CAPT.
_CAPTAIN_RE = re.compile(r"\bCAPT\s+(?P<name>[A-Z][A-Z .'-]*[A-Z])\s*$", re.MULTILINE)

_LEGACY_WAYPOINT_LOG_OFFSET = 6


def _parse_flight_planning_etps(
    cfp_pages: list[str],
    *,
    start_page_number: int,
) -> list[dict[str, Any]]:
    """Retain non-EDTO flight-planning ETP rows as source facts.

    A standard CFP may print an ``ETPA ... DIST ... EET`` planning row even
    when its EDTO assessment is correctly not applicable.  Keep that row
    separate from the EDTO model so a renderer can show the source milestone
    without changing the flight's EDTO classification.
    """
    rows: list[dict[str, Any]] = []
    for page_offset, text in enumerate(cfp_pages):
        for match in _FLIGHT_PLANNING_ETP_RE.finditer(text):
            eet_token = match.group("eet")
            rows.append({
                "label": f"ETP {match.group('label').upper()}",
                "from": match.group("from").upper(),
                "to": match.group("to").upper(),
                "distance_nm": int(match.group("distance_nm")),
                "eet_token": eet_token,
                "eet_minutes": actm_minutes(eet_token),
                "source_page": start_page_number + page_offset,
            })
    return rows


def _waypoint_log_start(cfp_pages: list[str]) -> int:
    """Index of the first CFP page carrying the waypoint log.

    LIDO variants shift where the log begins — front-matter length varies by
    route and OFP revision — so a fixed offset silently drops leading log
    pages (and every high-MSA or FIR row on them). A log page is recognised
    by waypoint rows immediately followed by their coordinate rows; the
    legacy offset survives only as the fallback for documents where no log
    page is recognisable.
    """
    for index, text in enumerate(cfp_pages):
        pairs = 0
        armed = False
        for line in text.splitlines():
            stripped = line.strip()
            if _WAYPOINT_LINE.match(stripped):
                armed = True
            elif armed and _COORDINATE_LINE.match(stripped):
                pairs += 1
                armed = False
                if pairs >= 2:
                    return index
    return _LEGACY_WAYPOINT_LOG_OFFSET


def _parse_waypoints(
    route_pages: list[str],
    route_text: str,
    *,
    start_page_number: int = 1,
) -> list[dict[str, Any]]:
    pending: dict[str, Any] | None = None
    waypoints: list[dict[str, Any]] = []
    waypoint_line = _WAYPOINT_LINE
    coordinate_line = _COORDINATE_LINE
    vws_line = re.compile(r"\s(?P<tas>\d{3})\s+(?P<vws>\d{3})\s+\d{2}\.\d\s")
    for page_number, text in enumerate(route_pages, start=start_page_number):
        for line in text.splitlines():
            match = waypoint_line.match(line.strip())
            if match:
                if pending:
                    waypoints.append(pending)
                name = match.group("name")
                pending = {
                    "name": name,
                    "actm_minutes": actm_minutes(match.group("actm")),
                    "fir_boundary": name[1:] if name.startswith("-") else None,
                    "source_page": page_number,
                    "latitude": None,
                    "longitude": None,
                    "msa_hundreds_ft": None,
                    "msa_asterisk": False,
                    "vws": None,
                    "airway_in": None,
                }
                vws_match = vws_line.search(line)
                if vws_match:
                    pending["vws"] = int(vws_match.group("vws"))
                continue
            if pending:
                coordinate = coordinate_line.match(line.strip())
                if coordinate:
                    pending["latitude"] = _decimal_coordinate(
                        coordinate.group("lat_hem"),
                        coordinate.group("lat_deg"),
                        coordinate.group("lat_min"),
                    )
                    pending["longitude"] = _decimal_coordinate(
                        coordinate.group("lon_hem"),
                        coordinate.group("lon_deg"),
                        coordinate.group("lon_min"),
                    )
                    name = str(pending["name"])
                    computed = name.startswith("-") or name.startswith(("ENTRY", "EXIT", "**ETP")) or name in {"TOC", "TOD"}
                    if not computed:
                        pending["msa_hundreds_ft"] = int(coordinate.group("msa"))
                        pending["msa_asterisk"] = bool(coordinate.group("star"))
    if pending:
        waypoints.append(pending)

    names = {w["name"].lstrip("-").upper() for w in waypoints}
    current_airway: str | None = None
    airway_re = re.compile(r"^(?:DCT|[A-Z]{1,3}\d{1,4}[A-Z]?)$")
    anchors: list[tuple[str, str]] = []
    for token in route_text.replace("/", " ").split():
        upper = token.upper()
        if airway_re.fullmatch(upper):
            current_airway = upper
        elif upper in names and current_airway:
            anchors.append((upper, current_airway))
    search_from = -1
    for anchor_name, airway in anchors:
        anchor_index = next(
            (i for i in range(search_from + 1, len(waypoints)) if waypoints[i]["name"].lstrip("-").upper() == anchor_name),
            None,
        )
        if anchor_index is None:
            continue
        for i in range(search_from + 1, anchor_index + 1):
            if not waypoints[i]["fir_boundary"]:
                waypoints[i]["airway_in"] = airway
        search_from = anchor_index
    return waypoints


def _edto_period(
    start_hhmm: str,
    end_hhmm: str,
    departure_utc: datetime,
    arrival_utc: datetime,
) -> tuple[datetime, datetime]:
    flight_days = (arrival_utc.date() - departure_utc.date()).days
    candidates = [
        utc_on_date(departure_utc + timedelta(days=offset), start_hhmm)
        for offset in range(-1, flight_days + 2)
    ]

    def distance_from_flight(value: datetime) -> float:
        if value < departure_utc:
            return (departure_utc - value).total_seconds()
        if value > arrival_utc:
            return (value - arrival_utc).total_seconds()
        return 0

    period_start = min(candidates, key=lambda value: (distance_from_flight(value), value))
    period_end = utc_on_date(period_start, end_hhmm)
    if period_end <= period_start:
        period_end += timedelta(days=1)
    return period_start, period_end


def _parse_edto_airports(
    edto_text: str,
    departure_utc: datetime,
    arrival_utc: datetime,
) -> list[dict[str, Any]]:
    """Parse every checked-period row without joining a blank approach row.

    Some Lido rows intentionally leave APCH blank. Parsing the whole section
    with ``\\s+`` can then cross the newline and consume the next airport as the
    missing approach. Read one physical table row at a time and split the
    trailing minima from the optional approach instead.
    """
    row_pattern = re.compile(
        r"^(?P<airport>[A-Z]{4})[ \t]+"
        r"(?P<start>\d{4})-(?P<end>\d{4})[ \t]+"
        r"(?P<runway>[0-9A-Z]{2,3})[ \t]+(?P<tail>\S.*)$"
    )
    airports: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for line in edto_text.splitlines():
        match = row_pattern.match(line)
        if not match:
            continue
        tail_parts = match.group("tail").rsplit(maxsplit=1)
        approach, minima = (
            (tail_parts[0], tail_parts[1])
            if len(tail_parts) == 2
            else ("", tail_parts[0])
        )
        key = (
            match.group("airport"),
            match.group("start"),
            match.group("end"),
            match.group("runway"),
            approach,
            minima,
        )
        if key in seen:
            continue
        seen.add(key)
        period_start, period_end = _edto_period(
            match.group("start"),
            match.group("end"),
            departure_utc,
            arrival_utc,
        )
        airports.append({
            "airport": match.group("airport"),
            "period_start_utc": period_start.isoformat(),
            "period_end_utc": period_end.isoformat(),
            "runway": match.group("runway"),
            "approach": approach,
            "minima": minima,
        })
    return airports


def _utc_nearest(reference: datetime, hhmm: str) -> datetime:
    candidates = [
        utc_on_date(reference + timedelta(days=offset), hhmm)
        for offset in (-1, 0, 1)
    ]
    return min(candidates, key=lambda value: abs((value - reference).total_seconds()))


_EXPLICIT_NIL_EDTO = re.compile(
    r"\b(?:EDTO|ETOPS)(?:\s+(?:STATUS|APPLICABILITY))?\s*[:=-]?\s*"
    r"(?:NIL|N/?A|NOT\s+APPLICABLE)\b|"
    r"\b(?:NIL|NOT\s+APPLICABLE)\s+(?:EDTO|ETOPS)\b",
    re.IGNORECASE,
)


def _complete_standard_lido_cfp_page_span(
    cfp_pages: list[str],
) -> tuple[int, int] | None:
    """Return the declared CFP page span only for a complete standard Lido CFP.

    Lido prints ``PAGE n OF total`` on every CFP page. Requiring the standard
    (non-EDTO) title plus a contiguous 1..total sequence prevents a truncated
    upload or an arbitrary text blob from turning absence of EDTO rows into
    verified NIL evidence.
    """
    if not cfp_pages:
        return None
    first_page_header = "\n".join(cfp_pages[0].splitlines()[:12])
    if not re.search(
        r"\bSUMMARY(?:\s+STANDARD)?\s+CFP\b",
        first_page_header,
        re.IGNORECASE,
    ):
        return None

    page_headers: list[tuple[int, int]] = []
    for page in cfp_pages:
        header = re.search(
            r"^\s*PAGE\s+(\d+)\s+OF\s+(\d+)\b",
            page,
            re.MULTILINE | re.IGNORECASE,
        )
        if not header:
            return None
        page_headers.append((int(header.group(1)), int(header.group(2))))

    declared_total = page_headers[0][1]
    if (
        declared_total != len(cfp_pages)
        or any(total != declared_total for _, total in page_headers)
        or [number for number, _ in page_headers]
        != list(range(1, declared_total + 1))
    ):
        return None
    return 1, declared_total


def _build_edto_assessment(
    *,
    cfp_pages: list[str],
    cfp_start: int,
    source_name: str,
    edto_page_index: int | None,
    sectors: list[dict[str, Any]],
    airports: list[dict[str, Any]],
    has_timing_data: bool,
) -> dict[str, Any]:
    """Build a fail-closed, evidence-bearing EDTO applicability result.

    Empty parsed collections alone are not proof that EDTO is inapplicable.
    NIL is accepted only for an explicit EDTO/ETOPS declaration, or when the
    complete standard Lido CFP page sequence is proven and contains no EDTO
    section. Parsed sector, airport or timing data is positive applicability
    evidence. Everything else requires review.
    """
    operational_data_present = bool(sectors or airports or has_timing_data)
    edto_page = (
        cfp_start + edto_page_index + 1
        if edto_page_index is not None
        else None
    )
    nil_declaration = next(
        (
            (cfp_start + index + 1, match)
            for index, page in enumerate(cfp_pages)
            if (match := _EXPLICIT_NIL_EDTO.search(page))
        ),
        None,
    )
    complete_standard_span = (
        _complete_standard_lido_cfp_page_span(cfp_pages)
        if edto_page_index is None and not operational_data_present
        else None
    )

    evidence: list[dict[str, Any]] = []
    if operational_data_present:
        evidence.append({
            "source": "uploaded_company_cfp",
            "document_id": source_name,
            "source_page": edto_page,
            "reason_code": "parsed_edto_operational_data",
            "sector_count": len(sectors),
            "airport_count": len(airports),
        })
    if nil_declaration:
        evidence.append({
            "source": "uploaded_company_cfp",
            "document_id": source_name,
            "source_page": nil_declaration[0],
            "reason_code": "explicit_edto_not_applicable_declaration",
        })
    if complete_standard_span:
        first_page, last_page = complete_standard_span
        evidence.append({
            "source": "uploaded_company_cfp",
            "document_id": source_name,
            "source_page": cfp_start + first_page,
            "source_page_start": cfp_start + first_page,
            "source_page_end": cfp_start + last_page,
            "source_page_count": last_page - first_page + 1,
            "reason_code": "complete_lido_cfp_no_edto_section",
        })

    if operational_data_present and not nil_declaration:
        status = "affected"
    elif (nil_declaration or complete_standard_span) and not operational_data_present:
        status = "verified_not_applicable"
    else:
        status = "review_required"
        evidence.append({
            "source": "uploaded_company_cfp",
            "document_id": source_name,
            "source_page": edto_page or cfp_start + 1,
            "reason_code": (
                "conflicting_edto_applicability_evidence"
                if operational_data_present and nil_declaration
                else "explicit_edto_assessment_missing"
            ),
        })

    return {"status": status, "evidence": evidence}


# The page-1 summary block, one named line each. Lido prints label columns
# with variable interior spacing, so every literal space in these patterns is
# \s+ and values may be zero-padded. The dest-hold line's "TOP UP TO 60 MINS"
# prefix is part of the printed label and anchors the match.
_PAGE1_TIMED_ROWS: tuple[tuple[str, str], ...] = (
    ("burnoff", r"BURNOFF"),
    ("stat_cont", r"STAT\s+CONT"),
    ("altn_fuel", r"ALTN\s+FUEL"),
    ("altn_hold", r"ALTN\s+HOLD"),
    ("dest_hold_top_up", r"TOP\s+UP\s+TO\s+60\s+MINS\s+DEST\s+HOLD\s+FUEL"),
    ("edto_top_up", r"EDTO\s+TOP\s+UP"),
    ("flt_plan_reqmt", r"FLT\s+PLAN\s+REQMT"),
    ("excess_fuel", r"EXCESS\s+FUEL"),
    ("fuel_in_tanks", r"FUEL\s+IN\s+TANKS"),
)


def parse_page1_fuel_summary(page1: str) -> dict[str, Any] | None:
    """Read the whole page-1 fuel/weight summary and prove its arithmetic.

    Boss, 07 Aug: "this part has to be in. Page 1 of the CFP has to be given
    more attention." The block is machine-printed with exact internal
    arithmetic — requirement is the sum of its lines, tanks is requirement
    plus excess, landing weight is take-off weight minus burnoff — so those
    identities are the verification: state "verified" only when every check
    passes on both the fuel and the time column. Anything else is
    "review_required", which display layers must render as a review flag,
    never as figures. A page without the block returns None.
    """
    text = str(page1 or "")
    if not re.search(r"BURNOFF", text) or not re.search(r"FUEL\s+IN\s+TANKS", text):
        return None

    rows: dict[str, dict[str, int] | None] = {}
    for name, label in _PAGE1_TIMED_ROWS:
        match = re.search(rf"{label}\s+(\d{{1,2}}\.\d{{2}})\s+0*(\d+)", text)
        rows[name] = (
            {"time_minutes": actm_minutes(match.group(1)), "fuel_kg": int(match.group(2))}
            if match
            else None
        )

    taxi_match = re.search(r"TAXI\s+FUEL\s+0*(\d+)", text)
    masses = {
        "pzfw": _int_group(text, r"PZFW\s+(\d+)"),
        "ptow": _int_group(text, r"PTOW\s+(\d+)"),
        "plwt": _int_group(text, r"PLWT\s+(\d+)"),
    }

    classification_match = re.search(
        r"SUMMARY\s+(STANDARD|NON\s+EDTO|EDTO)\s+CFP",
        text,
    )
    source_classification = (
        re.sub(r"\s+", " ", classification_match.group(1)).strip().upper()
        if classification_match
        else None
    )
    wind_match = re.search(r"CRZ\s+COMP\s+([PM])\s*0*(\d+)", text)
    alternate_match = re.search(r"ALTN\s+([A-Z]{3})\s+\(([A-Z]{4})\)", text)

    breakdown: list[dict[str, Any]] = []
    for item in re.finditer(r"^\s*\d\.\s*([A-Z]+)\s+0*(\d+)KG", text, re.MULTILINE):
        breakdown.append({"label": item.group(1), "fuel_kg": int(item.group(2))})

    discrepancies: list[str] = []
    # The two top-up lines are conditional print: a NON EDTO plan omits
    # "EDTO TOP UP" entirely (SIA365's filed CFP does), and either top-up may
    # be absent on other revisions. Absence means zero contribution - it is
    # not a defect. Everything else is mandatory.
    optional_rows = {"dest_hold_top_up", "edto_top_up"}
    missing = [
        name for name, value in rows.items()
        if value is None and name not in optional_rows
    ]
    if taxi_match is None:
        missing.append("taxi_fuel")
    missing.extend(name for name, value in masses.items() if value is None)
    for name in missing:
        discrepancies.append(f"missing line: {name}")

    checks: list[dict[str, Any]] = []

    def check(name: str, lhs: int | None, rhs: int | None, tolerance: int = 0) -> None:
        # Fuel figures are exact integers and must match exactly. TIME figures
        # are printed to the whole minute per line, each rounded from its own
        # fuel-derived value, so a sum of n printed addends may drift from the
        # printed total by up to half a minute per addend — observed live on
        # SIA365, whose FUEL IN TANKS prints 14.17 against a 13.13 + 01.05 sum
        # of 14.18. The tolerance is that printing precision and nothing more.
        if lhs is None or rhs is None:
            return
        passed = abs(lhs - rhs) <= tolerance
        checks.append({"name": name, "passed": passed, "lhs": lhs, "rhs": rhs})
        if not passed:
            discrepancies.append(f"{name}: {lhs} != {rhs}")

    def kg(name: str) -> int | None:
        row = rows.get(name)
        return None if row is None else row["fuel_kg"]

    def minutes(name: str) -> int | None:
        row = rows.get(name)
        return None if row is None else row["time_minutes"]

    taxi_kg = int(taxi_match.group(1)) if taxi_match else None
    requirement_parts_kg = [
        kg("burnoff"), kg("stat_cont"), kg("altn_fuel"), kg("altn_hold"),
        kg("dest_hold_top_up") or 0, kg("edto_top_up") or 0, taxi_kg,
    ]
    if all(part is not None for part in requirement_parts_kg):
        check("fuel_requirement_sum", sum(requirement_parts_kg), kg("flt_plan_reqmt"))
    if kg("flt_plan_reqmt") is not None and kg("excess_fuel") is not None:
        check("fuel_tanks_sum", kg("flt_plan_reqmt") + kg("excess_fuel"), kg("fuel_in_tanks"))
    if masses["ptow"] is not None and kg("burnoff") is not None:
        check("mass_landing_identity", masses["ptow"] - kg("burnoff"), masses["plwt"])
    # Fuel at brake release is tanks minus taxi: PZFW + (tanks - taxi) = PTOW.
    if masses["pzfw"] is not None and kg("fuel_in_tanks") is not None and taxi_kg is not None:
        check("mass_takeoff_identity", masses["pzfw"] + kg("fuel_in_tanks") - taxi_kg, masses["ptow"])
    requirement_parts_min = [
        minutes("burnoff"), minutes("stat_cont"), minutes("altn_fuel"), minutes("altn_hold"),
        minutes("dest_hold_top_up") or 0, minutes("edto_top_up") or 0,
    ]
    if all(part is not None for part in requirement_parts_min):
        check(
            "time_requirement_sum",
            sum(requirement_parts_min),
            minutes("flt_plan_reqmt"),
            tolerance=(len(requirement_parts_min) + 1) // 2,
        )
    if minutes("flt_plan_reqmt") is not None and minutes("excess_fuel") is not None:
        check(
            "time_tanks_sum",
            minutes("flt_plan_reqmt") + minutes("excess_fuel"),
            minutes("fuel_in_tanks"),
            tolerance=1,
        )

    takeoff_fuel_kg = (
        kg("fuel_in_tanks") - taxi_kg
        if kg("fuel_in_tanks") is not None and taxi_kg is not None
        else None
    )
    landing_fuel_kg = (
        takeoff_fuel_kg - kg("burnoff")
        if takeoff_fuel_kg is not None and kg("burnoff") is not None
        else None
    )

    return {
        "state": "verified" if not discrepancies else "review_required",
        # Lido prints both "SUMMARY NON EDTO CFP" and "SUMMARY STANDARD
        # CFP" for plans where EDTO does not apply. Keep a normalized value
        # for decision gates while retaining the exact printed label so the
        # report never rewrites STANDARD as though the source said otherwise.
        "classification": (
            "NON EDTO" if source_classification == "STANDARD" else source_classification
        ),
        "source_classification": source_classification,
        "ground_miles_nm": _int_group(text, r"GND\s+MILES\s+(\d+)"),
        "air_miles_nm": _int_group(text, r"AIR\s+MILES\s+(\d+)"),
        "cruise_wind_component_kt": (
            (1 if wind_match.group(1) == "P" else -1) * int(wind_match.group(2))
            if wind_match
            else None
        ),
        "alternate": (
            {"designator": alternate_match.group(1), "icao": alternate_match.group(2)}
            if alternate_match
            else None
        ),
        "rows": rows,
        "taxi_fuel_kg": taxi_kg,
        # Direct arithmetic from the printed page-1 rows. These are labelled
        # as derived on every publishing surface; they are not extra source
        # lines and cannot be mistaken for a revised fuel plan.
        "derived_fuel_kg": {
            "takeoff": takeoff_fuel_kg,
            "landing": landing_fuel_kg,
        },
        "masses_kg": masses,
        "excess_breakdown": breakdown,
        # "4.TANKER 18847KG RTN SECTOR REQ 23324KG" — the CFP names the
        # tankering purpose and the return-sector requirement; the report
        # writes it in those words (boss, 21 Aug 2026 fuel video).
        "tanker_return_sector_req_kg": _int_group(
            text, r"TANKER\s+0*\d+KG\s+RTN\s+SECTOR\s+REQ\s+0*(\d+)KG"
        ),
        "checks": checks,
        "discrepancies": discrepancies,
    }


def parse_lido(pages: list[str], source_name: str) -> dict[str, Any]:
    sections = _detect_sections(pages)
    if "cfp" not in sections:
        raise ValueError("OFP section not detected")
    cfp_start, cfp_end = sections["cfp"]
    cfp_pages = pages[cfp_start:cfp_end]
    page1 = cfp_pages[0]
    flight_rules_match = re.search(
        r"\bFLT\s+RULES\s*:\s*(?P<rules>[A-Z0-9]+(?:\s*/\s*[A-Z0-9]+)*)",
        page1,
        re.IGNORECASE,
    )
    printed_flight_rules = (
        re.sub(r"\s*/\s*", "/", flight_rules_match.group("rules")).upper()
        if flight_rules_match
        else ""
    )
    identity = re.search(
        r"(?P<reg>[A-Z0-9-]{4,10})\s+(?P<flight>[A-Z]{2,3}\d{2,4})\s+"
        r"(?P<dep_iata>[A-Z]{3})/(?P<dest_iata>[A-Z]{3})\s+ETD\s+"
        r"(?P<etd>\d{4})\s+(?P<date>\d{2}[A-Z]{3}\d{2})",
        page1,
    )
    if not identity:
        raise ValueError("Unable to parse Lido flight identity")
    day = date_ddmmmyy(identity.group("date"))
    sched = re.search(r"SCHED DEP\s+(\d{4})\s+UTC\s+SCHED ARR\s+(\d{4})\s+UTC", page1)
    if not sched:
        raise ValueError("Unable to parse scheduled times")
    departure_utc = utc_on_date(day, sched.group(1))
    arrival_utc = utc_on_date(day, sched.group(2))
    if arrival_utc <= departure_utc:
        arrival_utc += timedelta(days=1)
    route_line = re.search(r"^(?P<departure>[A-Z]{4})/(?P<dep_rwy>[0-9A-Z]{2,3})\b", page1, re.MULTILINE)
    destination_candidates = list(
        re.finditer(r"\b(?P<destination>[A-Z]{4})/(?P<dest_rwy>[0-9A-Z]{2,3})\s*$", page1, re.MULTILINE)
    )
    destination_line = next(
        (
            candidate
            for candidate in reversed(destination_candidates)
            if route_line is None or candidate.start() != route_line.start()
        ),
        None,
    )
    departure = route_line.group("departure") if route_line else identity.group("dep_iata")
    destination = destination_line.group("destination") if destination_line else identity.group("dest_iata")
    route_text = _parse_route_text(page1)
    sid, sid_source_page = _parse_named_procedure(cfp_pages, "SID")
    star, star_source_page = _parse_named_procedure(cfp_pages, "STAR")
    log_start = _waypoint_log_start(cfp_pages)
    waypoints = _parse_waypoints(
        cfp_pages[log_start:],
        route_text,
        start_page_number=cfp_start + log_start + 1,
    )

    bobcat = None
    match = re.search(
        r"BOBCAT\s+ALLOCATION\s*:\s*WPT\s+([A-Z0-9]+)\s*,?\s*"
        r"FL\s*(\d+)\s*,?\s*CTO\s*(\d{4})\s*,?\s*CTOT\s*(\d{4})",
        page1,
        re.IGNORECASE,
    )
    if match:
        waypoint = next(
            (
                item
                for item in waypoints
                if str(item.get("name") or "").lstrip("-").upper() == match.group(1).upper()
            ),
            None,
        )
        predicted_crossing = departure_utc + timedelta(
            minutes=int((waypoint or {}).get("actm_minutes") or 0)
        )
        bobcat = {
            "waypoint": match.group(1).upper(),
            "flight_level": int(match.group(2)),
            "cto_utc": _utc_nearest(predicted_crossing, match.group(3)).isoformat(),
            "ctot_utc": _utc_nearest(departure_utc, match.group(4)).isoformat(),
        }

    fuel = {
        "trip_fuel_kg": _int_group(page1, r"BURNOFF\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "contingency_fuel_kg": _int_group(page1, r"STAT CONT\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "alternate_fuel_kg": _int_group(page1, r"ALTN FUEL\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "alternate_holding_fuel_kg": _int_group(page1, r"ALTN HOLD\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "taxi_fuel_kg": _int_group(page1, r"TAXI FUEL\s+0*(\d+)"),
        "flight_plan_required_fuel_kg": _int_group(page1, r"FLT PLAN REQMT\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "excess_fuel_kg": _int_group(page1, r"EXCESS FUEL\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "fuel_in_tanks_kg": _int_group(page1, r"FUEL IN TANKS\s+\d{2}\.\d{2}\s+0*(\d+)"),
    }
    masses = {
        "planned_zfw_kg": _int_group(page1, r"PZFW\s+(\d+)"),
        "planned_takeoff_weight_kg": _int_group(page1, r"PTOW\s+(\d+)"),
        "planned_landing_weight_kg": _int_group(page1, r"PLWT\s+(\d+)"),
    }
    required = {
        "departure ICAO/runway": route_line,
        "destination ICAO/runway": destination_line,
        "route waypoints": waypoints,
        "trip fuel": fuel["trip_fuel_kg"],
        "taxi fuel": fuel["taxi_fuel_kg"],
        "flight-plan required fuel": fuel["flight_plan_required_fuel_kg"],
        "fuel in tanks": fuel["fuel_in_tanks_kg"],
        "planned zero-fuel weight": masses["planned_zfw_kg"],
        "planned take-off weight": masses["planned_takeoff_weight_kg"],
        "planned landing weight": masses["planned_landing_weight_kg"],
    }
    missing = [name for name, value in required.items() if value is None or value == []]
    if missing:
        raise ValueError(f"Incomplete or unsupported Lido OFP; missing {', '.join(missing)}")
    fuel["planned_destination_fuel_kg"] = (
        masses["planned_landing_weight_kg"] - masses["planned_zfw_kg"]
    )
    perf_text = "\n".join(cfp_pages[:5])
    performance = _parse_performance(perf_text)
    edto_page_index = next(
        (
            index
            for index, text in enumerate(cfp_pages)
            if "EDTO INFORMATION" in text
        ),
        None,
    )
    # Long-haul EDTO tables can continue onto the following CFP page (SQ24's
    # third sector and alternate-airport table are one real example). The CFP
    # section is already bounded by _detect_sections, and the EDTO patterns are
    # anchored to their printed row shapes, so retain all continuation pages.
    edto_text = (
        "\n".join(cfp_pages[edto_page_index:])
        if edto_page_index is not None
        else ""
    )
    edto_sectors = _parse_edto_sectors(edto_text)
    entry_match = re.search(
        r"\n\s*(\d{1,2}\.\d{2})\s+[NS].*\n\s*ENTRY(?:\d+|\s*\.*)",
        edto_text,
    )
    exit_match = re.search(
        r"\n\s*(\d{1,2}\.\d{2})\s+[NS].*\n\s*EXIT(?:\d+|\s*\.*)",
        edto_text,
    )
    legacy_etp_actm = [
        actm_minutes(match.group(1))
        for match in re.finditer(
            r"\*\*ETP\S*(?:\s+\S+)?\s+(\d{1,2}\.\d{2})",
            "\n".join(cfp_pages),
        )
    ]
    primary_edto_sector = edto_sectors[0] if edto_sectors else None
    edto_airports = _parse_edto_airports(
        edto_text,
        departure_utc,
        arrival_utc,
    )
    edto_assessment = _build_edto_assessment(
        cfp_pages=cfp_pages,
        cfp_start=cfp_start,
        source_name=source_name,
        edto_page_index=edto_page_index,
        sectors=edto_sectors,
        airports=edto_airports,
        # A loose ETP token elsewhere in a CFP is not enough to prove EDTO.
        # Require the paired EDTO entry/exit declaration when no structured
        # sector or checked-period airport was parsed.
        has_timing_data=bool(entry_match and exit_match),
    )
    level_match = re.search(r"^[A-Z]{3}/\d{3}(?:/.*)$", page1, re.MULTILINE)
    route_identifier_match = re.search(
        r"\bRTE\s+NO\s+(?P<route_identifier>\S+)",
        page1,
    )
    aircraft_match = re.search(r"RTE NO\s+\S+\s+(?P<aircraft>[A-Z0-9-]+)", page1)
    captain_match = _CAPTAIN_RE.search(page1)
    zfw_burn_match = _ZFW_BURN_RE.search(page1)
    zfw_dual_match = _ZFW_DUAL_SENSITIVITY_RE.search(page1)
    lower_cruise_match = _LOWER_CRUISE_SENSITIVITY_RE.search(page1)
    flight_planning_etps = _parse_flight_planning_etps(
        cfp_pages,
        start_page_number=cfp_start + 1,
    )
    intam_records = _parse_intam_records(pages, sections.get("intam"))
    notam_procedure_records = _parse_notam_procedure_records(
        pages,
        sections.get("notam"),
    )
    intam_source_pages = sorted({
        int(record["source_page"])
        for record in intam_records
        if isinstance(record.get("source_page"), int)
    })
    flight = {
        "document_id": source_name,
        "source_evidence": {
            "page1": cfp_start + 1,
            "performance_pages": list(
                range(cfp_start + 1, cfp_start + min(5, len(cfp_pages)) + 1)
            ),
            "edto_page": (
                cfp_start + edto_page_index + 1
                if edto_page_index is not None
                else None
            ),
            "intam_pages": intam_source_pages,
        },
        "flight_number": identity.group("flight"),
        "flight_date": identity.group("date"),
        "ofp_identifier": _first_group(
            page1,
            r"\bOFP\s*:?\s*(\d+/\d+/\d+)\b",
            r"\bPLAN\s+(\d+/\d+/\d+)\b",
        ),
        # The commercial (operating) designator the CFP itself declares,
        # e.g. "OPTG SQ352" alongside an ICAO identity line "SIA352".
        "operating_flight_number": _first_group(
            page1,
            r"\bOPTG\s+([A-Z]{2,3}\d{2,4})\b",
        ),
        "aircraft_type": aircraft_match.group("aircraft") if aircraft_match else "UNKNOWN",
        "registration": identity.group("reg"),
        "captain": captain_match.group("name").strip() if captain_match else None,
        "departure": departure,
        "destination": destination,
        "departure_iata": identity.group("dep_iata"),
        "destination_iata": identity.group("dest_iata"),
        "departure_runway": route_line.group("dep_rwy") if route_line else None,
        "destination_runway": destination_line.group("dest_rwy") if destination_line else None,
        "sid": sid,
        "sid_source_page": (
            cfp_start + sid_source_page if sid_source_page is not None else None
        ),
        "star": star,
        "star_source_page": (
            cfp_start + star_source_page if star_source_page is not None else None
        ),
        "scheduled_departure_utc": departure_utc.isoformat(),
        "scheduled_arrival_utc": arrival_utc.isoformat(),
        "ground_distance_nm": _int_group(page1, r"GND\s+MILES\s+(\d+)"),
        "air_distance_nm": _int_group(page1, r"AIR\s+MILES\s+(\d+)"),
        "route_text": route_text,
        "route_waypoints": waypoints,
        "planned_level_profile": level_match.group(0).strip() if level_match else None,
        "route_identifier": (
            route_identifier_match.group("route_identifier")
            if route_identifier_match
            else None
        ),
        # "PLAN 3" — the route/plan version the boss asked for by name
        # (21 Aug: "important is the route ID and the route version").
        "plan_number": _first_group(page1, r"^\s*PLAN\s+(\d+)\s*$"),
        "cost_index": _int_group(page1, r"CRUISE CI\s+(\d+)"),
        "apd_percent": (
            float(apd_match.group(1))
            if (apd_match := re.search(
                r"\bAPD\s+(\d+(?:\.\d+)?)\s*PCT\b",
                page1,
            ))
            else None
        ),
        # The printed planning sensitivity, carried for the report's
        # sensitivities table; _ZFW_BURN_RE covers both LIDO line shapes.
        "zfw_change_burn_kg_per_1000": (
            int(zfw_burn_match.group("kg")) if zfw_burn_match else None
        ),
        "zfw_change_burn_add_kg_per_1000": (
            int(zfw_dual_match.group("add_kg"))
            if zfw_dual_match
            else int(zfw_burn_match.group("kg"))
            if zfw_burn_match
            else None
        ),
        "zfw_change_burn_less_kg_per_1000": (
            int(zfw_dual_match.group("less_kg")) if zfw_dual_match else None
        ),
        "lower_cruise_sensitivity": (
            {
                "offset_ft": int(lower_cruise_match.group("offset_ft")),
                "cost_index": int(lower_cruise_match.group("cost_index")),
                "burn_add_kg": int(lower_cruise_match.group("burn_add_kg")),
                # Preserve the CFP's printed sensitivity token instead of
                # interpreting it as an ACTM clock.  LIDO's public material
                # does not define this field's unit, and the briefing only
                # needs to reproduce the source-backed delta faithfully.
                "time_token": lower_cruise_match.group("time"),
                "time_display": (
                    f"{int(lower_cruise_match.group('time').split('.')[0])}:"
                    f"{lower_cruise_match.group('time').split('.')[1]}"
                ),
            }
            if lower_cruise_match
            else None
        ),
        # Non-EDTO planning ETP rows are source-held milestones, not proof of
        # an EDTO sector.  Keep them independent of ``flight.edto``.
        "flight_planning_etps": flight_planning_etps,
        # Preserve the complete printed FLT RULES token. Real CFPs can print a
        # single RVSM token as well as EDTO/RVSM or EDTO/MNPS/RVSM. The legacy
        # key is retained for API compatibility, but no rule is inferred or
        # discarded based on the route's EDTO classification.
        "edto_rvsm": printed_flight_rules or None,
        "bobcat": bobcat,
        "deferred_items": _parse_deferred_items(page1),
        # Lossless bounded company-bulletin identities. No route relevance,
        # applicability or operational conclusion is inferred here.
        "intam_records": intam_records,
        # Source-held CPDLC/ADS-C procedure records. Presence does not prove
        # route applicability; publishing surfaces retain that explicit gate.
        "notam_procedure_records": notam_procedure_records,
        "alternates": _parse_alternates(cfp_pages),
        "performance": performance,
        "fuel": fuel,
        # The complete page-1 summary with its arithmetic proved; display
        # layers key off its state and must show a review flag, not figures,
        # when it is anything but "verified".
        "fuel_summary": parse_page1_fuel_summary(page1),
        "masses": masses,
        "edto": {
            "assessment": edto_assessment,
            "entry_actm_minutes": (
                primary_edto_sector["entry_actm_minutes"]
                if primary_edto_sector
                else actm_minutes(entry_match.group(1))
                if entry_match
                else None
            ),
            "exit_actm_minutes": (
                primary_edto_sector["exit_actm_minutes"]
                if primary_edto_sector
                else actm_minutes(exit_match.group(1))
                if exit_match
                else None
            ),
            "etp_actm_minutes": (
                primary_edto_sector["etp_actm_minutes"]
                if primary_edto_sector
                else legacy_etp_actm
            ),
            "sectors": edto_sectors,
            "airports": edto_airports,
        },
        "fuel_enroute_airports": [],
        "notams": [],
        "weather": [],
        # Named VAA notice blocks are source-held separately from VA SIGMET
        # weather products; enrichment fills this without conflating them.
        "volcanic_advisories": [],
    }
    enrich_weather(flight, pages)
    enrich_notams(flight, pages)
    return flight
