from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .extraction_rules import EXTRACTION_RULES
from .fuel_rows import CONTINGENCY_LABEL

import fitz

from .constants import actm_minutes, date_ddmmmyy, utc_on_date
from .enrichment import enrich_notams, enrich_weather

# One ceiling with the app (cfp-limits.mjs MAX_CFP_PAGES). David, 23 Sep 2026
# 08:15: his SIN-LGW OFP of 22 Sep was refused at 180. The app's 12 MB byte cap
# admits ~327 pages at the thinnest LIDO density held, so 400 keeps bytes as
# the binding limit for genuine OFPs and still bounds a low-density file;
# measured cost at 400 pages is in the round's evidence folder.
MAX_PDF_PAGES = 400


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
            r"(?:PLAN\s+QNH\s*|^\s*QNH\s*:[ \t]*)(\d+)\s*(?:HPA)?\b",
        ),
        "wind": _line_value(
            perf_text,
            r"^\s*(?:PLAN\s+)?WIND\s*:[ \t]*(?P<value>\S+)",
        ) or _line_value(
            perf_text,
            r"\bPLAN\s+WIND\s+(?P<value>(?:VRB/?|\d{2,3}/|\d{3})\d{2,3}(?:G\d{2,3})?(?:KT)?)\b",
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
# An airway-segment heading: "ENRON/RANAHL750", "ZB    /BIROSL750" - two
# waypoints (2-5 letters) and the airway they share (1-2 letters + 1-3 digits).
_NOTAM_SEGMENT_HEADING = re.compile(r"^(?P<from>[A-Z]{2,5})\s*/(?P<rest>[A-Z]{3,7}\d{1,3})$")
_AIRWAY_SPLIT = re.compile(r"^(?P<to>[A-Z]{2,5})(?P<airway>[A-Z]{1,2}\d{1,3})$")
# A NOTAM-series label printed above a record ("UT O0287/26", "WS A2306/26", and with a location prefix
# "KZLA A1657/26"). A compatible prefix continues a proved owner; changed
# prefixes stay literal and unresolved. Keep the label/page separately.
_NOTAM_SERIES_LABEL = re.compile(r"^[A-Z]{1,4}\s+[A-Z]\d{3,5}/\d{2}$")
# AIRSPACE-HEADINGS-436 (independent QA of release 436, 27 Sep 2026): a FIR heading may print the airspace part after its
# designator - "RJJJ FUKUOKA FIR OCEANIC", "UBBA BAKU FIR LOWER", "LFFF FRANCE UIR" - or name the part without the word
# FIR - "KZNY NEW YORK DOMESTIC LOWER". Each ended the held scope, so the communication notices under it were never held
# (genuine SQ34 / SQ38 / SQ24: Fukuoka-oceanic ATS data-link notices SX75/24, SX90/23 on a route crossing RJJJ; SQ24:
# KZNY 1A487/26). The heading owns its notices for that FIR; the printed part is kept on each record ("airspace").
_NOTAM_AIRSPACE_HEADING = re.compile(
    r"^(?P<icao>[A-Z]{4})\s+(?P<name>[A-Z][A-Z0-9 /().,'-]*?)\s+"
    r"(?P<airspace>(?:FIR/UIR|FIR|UIR)(?:\s+(?:LOWER|UPPER|OCEANIC|DOMESTIC))*|(?:DOMESTIC|OCEANIC)(?:\s+(?:LOWER|UPPER))?)$",
    re.IGNORECASE,
)
# An airport section's heading: the ICAO location, the IATA code after a slash, the name ("WSSS /SIN SINGAPORE/CHANGI").
_NOTAM_AIRPORT_HEADING = re.compile(r"^[A-Z]{4}\s+/[A-Z]{3}\b")
# The enroute parts of a LIDO bulletin are titled "AREA ENROUTE ..." / "EXTENDED AREA AROUND ..."; the others are airports.
_NOTAM_AREA_TITLE = re.compile(r"^(?:EXTENDED\s+)?AREA\b", re.IGNORECASE)


def _airspace_heading(compact: str) -> re.Match[str] | None:
    """A FIR heading that names its airspace part (not the plain "ICAO NAME FIR" form, which _NOTAM_FIR_HEADING reads)."""
    if _NOTAM_FIR_HEADING.fullmatch(compact):
        return None
    return _NOTAM_AIRSPACE_HEADING.fullmatch(compact)


def _split_segment_heading(stripped: str, route_names: set[str] | None = None) -> dict[str, str] | None:
    """The waypoints and airway of a segment heading; when the tail splits two
    ways, the split whose waypoint the parsed route names wins."""
    match = _NOTAM_SEGMENT_HEADING.match(" ".join(stripped.upper().split()))
    if not match:
        return None
    rest = match.group("rest")
    candidates = []
    for cut in range(len(rest) - 2, 1, -1):
        to, airway = rest[:cut], rest[cut:]
        if 2 <= len(to) <= 5 and _AIRWAY_SPLIT.match(to + airway) and re.fullmatch(r"[A-Z]{1,2}\d{1,3}", airway):
            candidates.append((to, airway))
    if not candidates:
        return None
    chosen = next((c for c in candidates if route_names and c[0] in route_names), candidates[0])
    return {"from": match.group("from"), "to": chosen[0], "airway": chosen[1]}


# A LIDO NOTAM page is framed by the briefing's running header ("SIA 322/16Aug26/WSSS-EGLL Reg:9VSKS OFP:77/0/0",
# "SIA 304/12Jul26/SIN-BRU") and the package footer ("Page 70 of 112"); the text extraction prints both after the
# page's own lines. They are furniture, not NOTAM text - the header in its full shape, or any line opening with the
# operator prefix the notice readers below already treat as furniture ("SIA ").
_NOTAM_PAGE_FURNITURE = re.compile(r"^(?:[A-Z]{2,3}\s*\d{1,4}/\d{1,2}[A-Za-z]{3}\d{2}/\S.*|SIA\s.*|Page\s+\d+\s+of\s+\d+)$")
# A heading is underlined with a hyphen rule; a title is printed between two "=" bars.
_NOTAM_RULE = re.compile(r"-{3,}")
_NOTAM_TITLE_BAR = re.compile(r"={3,}")


def _notam_section_lines(pages: list[str], bounds: tuple[int, int]) -> list[tuple[int, str]]:
    """The NOTAM section as one stream of (physical page, stripped line) in which a page break reads as a line break.

    HEADING-CONTINUITY-432 (release-432 independent production QA, F2, 26 Sep 2026): genuine SQ322 prints
    'OAKX  KABUL FIR' as the last line of p70 and its underline as the first line of p71, and both heading readers looked
    for the underline on the next line of the same page. A page's furniture and the blank lines at its edges are
    therefore removed once, here, for every NOTAM heading reader. Blank lines inside a page are kept: in the airport
    sections a blank line before a rule marks a paragraph separator, not a heading.
    """
    start, end = bounds
    stream: list[tuple[int, str]] = []
    for page_index in range(start, end):
        lines = [line.strip() for line in pages[page_index].splitlines()]
        while lines and (not lines[0] or _NOTAM_PAGE_FURNITURE.fullmatch(lines[0])):
            lines.pop(0)
        while lines and (not lines[-1] or _NOTAM_PAGE_FURNITURE.fullmatch(lines[-1])):
            lines.pop()
        stream.extend((page_index + 1, line) for line in lines)
    return stream


def _notam_section_events(pages: list[str], bounds: tuple[int, int]) -> Iterator[dict[str, Any]]:
    """The NOTAM section's structure, read across page breaks: headings, titles, rules and text lines.

    A heading is a line whose hyphen rule follows it; a line in the FIR, segment or series-label grammar may have blank
    lines before its rule. A title is a line between two "=" bars. Two layouts are ambiguous and reported as such, so a
    reader never lets the previous heading own what follows: a FIR or segment heading printed without its rule directly
    above a notice ("unconfirmed_heading"), and a rule with a blank line and no heading above it ("rule",
    after_blank=True). Each event names the physical page it was printed on.
    """
    lines = _notam_section_lines(pages, bounds)
    count = len(lines)

    def substantive(index: int) -> int:
        while index < count and not lines[index][1]:
            index += 1
        return index

    index = 0
    while index < count:
        page_number, text = lines[index]
        if not text:
            index += 1
            continue
        if _NOTAM_TITLE_BAR.fullmatch(text):
            title_at = substantive(index + 1)
            closing_at = substantive(title_at + 1)
            if (
                closing_at < count
                and _NOTAM_TITLE_BAR.fullmatch(lines[closing_at][1])
                and not _NOTAM_RULE.fullmatch(lines[title_at][1])
                and not _NOTAM_TITLE_BAR.fullmatch(lines[title_at][1])
            ):
                yield {"event": "title", "text": " ".join(lines[title_at][1].split()), "page": lines[title_at][0]}
                index = closing_at + 1
            else:
                index += 1  # a bar that opens no title
            continue
        if _NOTAM_RULE.fullmatch(text):
            yield {"event": "rule", "page": page_number, "after_blank": index == 0 or not lines[index - 1][1]}
            index += 1
            continue
        compact = " ".join(text.split())
        if not _NOTAM_PROCEDURE_HEADER.match(text):
            underline_at = index + 1 if index + 1 < count and _NOTAM_RULE.fullmatch(lines[index + 1][1]) else None
            fir_or_segment = bool(_NOTAM_FIR_HEADING.fullmatch(compact) or _airspace_heading(compact) or _split_segment_heading(compact))
            if underline_at is None and (fir_or_segment or _NOTAM_SERIES_LABEL.fullmatch(compact.upper())):
                candidate = substantive(index + 1)
                if candidate < count and _NOTAM_RULE.fullmatch(lines[candidate][1]):
                    underline_at = candidate
            if underline_at is not None:
                following = substantive(underline_at + 1)
                established_kind = fir_or_segment or bool(_NOTAM_AIRPORT_HEADING.match(compact))
                fresh_declaration = following < count and _NOTAM_PROCEDURE_HEADER.match(lines[following][1])
                # Unknown underlined body titles do not change source owner.
                # A literal bulletin topic/series label owns a fresh notice,
                # including a declaration continuing on the next page.
                if established_kind or fresh_declaration:
                    yield {"event": "heading", "text": compact, "page": page_number, "underline_page": lines[underline_at][0]}
                    index = underline_at + 1
                    continue
            following = substantive(index + 1)
            if fir_or_segment and following < count and _NOTAM_PROCEDURE_HEADER.match(lines[following][1]):
                yield {"event": "unconfirmed_heading", "text": compact, "page": page_number}
                index += 1
                continue
        yield {"event": "line", "text": text, "page": page_number}
        index += 1


def _parse_notam_fir_names(pages: list[str], bounds: tuple[int, int] | None) -> dict[str, str]:
    """ICAO -> FIR name from the NOTAM section's own underlined FIR headings, wherever a page break falls. A heading that
    names the FIR's airspace part ("UBBA BAKU FIR LOWER") names a FIR no plain "ICAO NAME FIR" heading named."""
    names: dict[str, str] = {}
    if bounds is None:
        return names
    part_names: dict[str, str] = {}
    for event in _notam_section_events(pages, bounds):
        if event["event"] != "heading":
            continue
        match = _NOTAM_FIR_HEADING.fullmatch(event["text"])
        if match:
            name = " ".join(match.group("name").upper().split())
            names.setdefault(match.group("icao").upper(), name[:-4].strip() if name.endswith(" FIR") else name)
            continue
        part = _airspace_heading(event["text"])
        if part:
            part_names.setdefault(part.group("icao").upper(), " ".join(part.group("name").upper().split()))
    for icao, name in part_names.items():
        names.setdefault(icao, name)
    return names


def _parse_notam_procedure_records(
    pages: list[str],
    bounds: tuple[int, int] | None,
    route_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Retain source NOTAM records that print an enroute communication instruction.

    ATC-RADIO-SOURCE-418 (24 Sep 2026): the rule admitted only records under a
    named FIR heading that print CPDLC / ADS-C, so the genuine SQ366 and SQ23
    OFPs' voice, TIBA and contact instructions (some under airway-segment
    headings) never reached the briefing. Now a record is held when it sits
    under a FIR heading ("OAKX  KABUL FIR") or an airway-segment heading
    ("ENRON/RANAHL750") and its body prints a communication instruction of any
    kind - contact / call / report / monitor with a unit or frequency, TIBA /
    broadcast / transmission, logon, CPDLC / ADS-C (enroute_contact.
    procedure_kind; OCR-split words are joined for the test only).
    ATC-CLEARANCE-FAMILY (1 Oct 2026, extraction v7): a request, clarification
    or confirmation addressed to a unit, and the refusal or acceptance of an
    ATC clearance or ATC-qualified instruction, are such instructions too. A NOTAM-
    series label under a heading is a continuation of that section. Airport
    and other sections are never inherited. The record is not claimed route-
    applicable here: it is held with its identity, validity, heading, heading
    kind, FIR or segment, physical page and complete source prose; the
    composition evaluates its printed conditions against the OFP's own facts.

    HEADING-CONTINUITY-432 (26 Sep 2026): headings are read across page
    breaks (_notam_section_events), so a heading printed at the foot of a page
    owns the notices under its underline on the next; every record names the
    page its heading is printed on (heading_page). Where the source layout
    does not establish the owner - a FIR or segment heading without its rule
    directly above a notice, or a rule with no heading above it inside a FIR
    or segment section - the notices that follow are held with heading_kind
    "unresolved" until the next heading, never under the previous owner.
    """
    from .enroute_contact import procedure_kind

    if bounds is None:
        return []
    records: list[dict[str, Any]] = []
    heading: dict[str, Any] | None = None
    source_label: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            body = " ".join(body_lines).strip()
            if procedure_kind(body, f"{current.get('heading') or ''} {body}"):
                records.append({
                    **current,
                    "text": body,
                    "applicability": "not_inferred",
                })
        current = None
        body_lines = []

    def unresolved(text: str, page_number: int) -> dict[str, Any]:
        return {"heading": text, "heading_kind": "unresolved", "fir": None, "segment": None, "heading_page": page_number}

    # AIRSPACE-HEADINGS-436: inside an enroute ("AREA ...") part, a heading that is neither a FIR, an airspace part, a
    # segment, a series label nor an airport is a topic ("UAV 401614N 0250927E", "VAA GREAT SITKIN", a restricted area):
    # its notices are held with no owning FIR - never under the FIR printed before it (LIDO does not nest topics under
    # the FIR above: "LAT LATINA" prints before "LIRR ROME FIR"). In the airport parts nothing is held, as before.
    area_part = False
    for event in _notam_section_events(pages, bounds):
        kind = event["event"]
        if kind == "heading":
            flush()
            compact = event["text"]
            if _NOTAM_SERIES_LABEL.fullmatch(compact.upper()):
                prefix = compact.upper().split()[0]
                source_label = {"source_label": compact, "source_label_page": event["page"]}
                owner = heading.get("fir") if heading else None
                # Preserve a proved matching owner or literal route/topic
                # context. A short incompatible prefix is not FIR evidence;
                # a parentless series label remains its own literal topic.
                if (owner and owner.startswith(prefix)) or (
                    heading and not owner and not _NOTAM_SERIES_LABEL.fullmatch(heading["heading"].upper())
                ):
                    continue
            else:
                source_label = {}
            fir_match = _NOTAM_FIR_HEADING.fullmatch(compact)
            part_match = _airspace_heading(compact)
            segment = _split_segment_heading(compact, route_names)
            if fir_match:
                heading = {"heading": compact, "heading_kind": "fir", "fir": fir_match.group("icao").upper(), "segment": None,
                           "heading_page": event["page"]}
            elif part_match:
                heading = {"heading": compact, "heading_kind": "fir", "fir": part_match.group("icao").upper(), "segment": None,
                           "airspace": " ".join(part_match.group("airspace").upper().split()), "heading_page": event["page"]}
            elif segment:
                heading = {"heading": compact.replace(" ", ""), "heading_kind": "segment", "fir": None, "segment": segment,
                           "heading_page": event["page"]}
            elif area_part and not _NOTAM_AIRPORT_HEADING.match(compact):
                heading = {"heading": compact, "heading_kind": "topic", "fir": None, "segment": None, "heading_page": event["page"]}
            else:
                heading = None
            continue
        if kind == "title":
            flush()
            heading = None
            source_label = {}
            area_part = bool(_NOTAM_AREA_TITLE.match(event["text"]))
            continue
        if kind == "unconfirmed_heading" or (kind == "rule" and event["after_blank"]):
            # The source does not establish who owns what follows: hold it with its owner unresolved rather than let
            # the heading before it own it. Outside a held section nothing is inherited, so nothing changes.
            if heading is not None:
                flush()
                heading = unresolved(event.get("text", ""), event["page"])
                source_label = {}
            continue
        if kind != "line":
            continue
        stripped = event["text"]
        declaration = _NOTAM_PROCEDURE_HEADER.match(stripped)
        if declaration:
            flush()
            if heading is not None:
                current = {
                    "notam_id": declaration.group("identity").upper(),
                    "validity": " ".join(declaration.group("validity").split()),
                    **heading,
                    **source_label,
                    "source_page": event["page"],
                }
            continue
        if current is not None and not stripped.startswith(("SIA ", "Page ")):
            body_lines.append(" ".join(stripped.split()))
    flush()
    return records


# A page-1 declaration opens with Lido's sequence label: one capital letter
# printed twice (AA, BB, CC ...). The OFP decides how many there are, so the
# label is recognised by its shape and its order, never from a fixed list.
# A closed AA-EE list is how SQ882's FF and GG declarations (10 Sep 2026)
# became part of EE's remark.
_DECLARATION_LABEL = r"(?P<token>(?P<letter>[A-Z])(?P=letter))"
_OPAQUE_DEFERRED_HEADER = re.compile(
    rf"^{_DECLARATION_LABEL}\s+(?P<description>\S.*\S|\S)\s*$"
)
_DECLARATION_HEADER = re.compile(rf"^{_DECLARATION_LABEL}\s+(?P<rest>\S.*\S|\S)\s*$")
# Lido's own plan-block header ("PLAN 8", "PLAN 27/0/1") or "RTE NO". A
# dispatcher remark that merely begins with the word - SQ38 29 Aug prints "PLAN
# VIA PACOTS TRK 2" and "PLAN WITH PACKS OFF" above its declarations - is not it.
_PLAN_BLOCK_HEADER = re.compile(r"^(?:PLAN\s+\d+(?:/\d+)*\s*$|RTE\s+NO\b)")
_GOVERNED_DECLARATION = re.compile(
    # Reference and trailing description are both optional, and the
    # description may follow with or without a dash ("CC MEL PREAMBLE
    # SECTION MEL AND CMS REV 18NOV 25" — SQ366 4 Aug shape).
    r"^(?P<kind>CDDL|CDL|MEL)"
    r"(?:\s+(?P<reference>[0-9A-Z-]+))?"
    r"(?:\s*-\s*(?P<dashed>.*\S)|\s+(?P<undashed>\S.*\S|\S))?\s*$"
)
_NOTICE_DECLARATION = re.compile(
    # "DD IN SIA/00-017 R1" (information notice) and "GG EN A35MEN-21-28871"
    # (engineering notice), with an optional revision and an optional request
    # printed on the same line ("EE EN A35MEN-21-27688 R1 TO UPLIFT DRY ICE
    # FOR ALL CHILLERS", SQ606 6 Sep). A notice number carries a digit, so
    # prose that merely begins with the word IN is not a notice.
    r"^(?P<kind>IN|EN)\s+(?P<reference>(?=[0-9A-Z/-]*\d)[0-9A-Z/-]+(?:\s+R\d+)?)"
    r"(?:\s+(?P<description>\S.*\S|\S))?\s*$"
)
_OPAQUE_DEFERRED_IDENTIFIER = re.compile(
    r"\b(?P<identifier>ECDL[0-9A-Z][0-9A-Z._/-]{2,79})\b"
)
_OPAQUE_DEFERRED_CLASS = re.compile(r"\bX\s+CLASS\s+(?P<class>[A-Z])\b")
_KNOWN_DEFERRED_HEADER = re.compile(r"^(?:CDDL|CDL|MEL|IFEDDL|IN|EN)(?:\s|$)")


def _opaque_deferred_source_groups(
    page1: str,
    *,
    source_page: int,
) -> list[tuple[int, int, dict[str, Any]]]:
    """Return source-bounded opaque ECDL groups without guessing their class.

    Some Lido Page-1 blocks do not print a ``MEL``/``CDL``/``CDDL`` label.
    SQ481 instead prints the same seat defect under AA and BB, followed by an
    opaque ``ECDL`` identifier and class marker.  The identifier is evidence,
    not a governed manual reference: it cannot safely select a MEL/CDL item.

    This deliberately narrow recogniser requires both the opaque ECDL token
    and a printed ``X CLASS`` line.  Unrelated AA/BB prose therefore remains
    untouched.  Adjacent declarations with the same description are retained
    as one audit group, including their original physical line numbers.
    """

    lines = page1.splitlines()
    groups: list[tuple[int, int, dict[str, Any]]] = []
    cursor = 0
    while cursor < len(lines):
        header = _OPAQUE_DEFERRED_HEADER.fullmatch(lines[cursor].strip())
        if (
            header is None
            or _KNOWN_DEFERRED_HEADER.match(header.group("description").upper())
        ):
            cursor += 1
            continue

        group_start = cursor
        description = " ".join(header.group("description").split())
        group_tokens: list[str] = []
        audit_lines: list[dict[str, Any]] = []
        search_lines: list[str] = []
        group_end = cursor

        while cursor < len(lines):
            current_header = _OPAQUE_DEFERRED_HEADER.fullmatch(
                lines[cursor].strip()
            )
            if current_header is None:
                break
            current_description = " ".join(
                current_header.group("description").split()
            )
            if (
                current_description.upper() != description.upper()
                or _KNOWN_DEFERRED_HEADER.match(current_description.upper())
            ):
                break

            group_tokens.append(current_header.group("token"))
            header_text = " ".join(lines[cursor].split())
            audit_lines.append({
                "line_number": cursor + 1,
                "text": header_text,
            })
            search_lines.append(header_text)
            group_end = cursor
            cursor += 1

            header_margin = len(lines[group_start]) - len(lines[group_start].lstrip())
            gap = False
            while cursor < len(lines):
                stripped = lines[cursor].strip()
                if _PLAN_BLOCK_HEADER.match(stripped):
                    break
                if _OPAQUE_DEFERRED_HEADER.fullmatch(stripped):
                    break
                if not stripped:
                    gap = True
                elif gap and len(lines[cursor]) - len(lines[cursor].lstrip()) <= header_margin:
                    # A paragraph break and a line back at the margin: the
                    # dispatcher has moved on; this is not the group's text.
                    break
                if stripped:
                    gap = False
                    line_text = " ".join(stripped.split())
                    audit_lines.append({
                        "line_number": cursor + 1,
                        "text": line_text,
                    })
                    search_lines.append(line_text)
                    group_end = cursor
                cursor += 1

            next_header = (
                _OPAQUE_DEFERRED_HEADER.fullmatch(lines[cursor].strip())
                if cursor < len(lines)
                else None
            )
            if next_header is None:
                break
            next_description = " ".join(next_header.group("description").split())
            if next_description.upper() != description.upper():
                break

        source_text = "\n".join(search_lines)
        identifiers = list(dict.fromkeys(
            match.group("identifier").upper()
            for match in _OPAQUE_DEFERRED_IDENTIFIER.finditer(source_text.upper())
        ))
        class_lines = list(dict.fromkeys(
            line["text"]
            for line in audit_lines
            if _OPAQUE_DEFERRED_CLASS.search(line["text"].upper())
        ))
        if not identifiers or not class_lines:
            # This looked like generic AA/BB prose, not the exact opaque ECDL
            # shape. Resume after the first line so another candidate remains
            # discoverable without consuming source text.
            cursor = group_start + 1
            continue

        identity_basis = "\n".join((
            f"PAGE {source_page} LINES {group_start + 1}-{group_end + 1}",
            *(
                " ".join(line["text"].upper().split())
                for line in audit_lines
            ),
        ))
        deferred_entry_id = (
            "ofp-deferred-"
            + hashlib.sha256(identity_basis.encode("utf-8")).hexdigest()[:20]
        )
        groups.append((
            group_start,
            group_end,
            {
                "reference": identifiers[0] if len(identifiers) == 1 else None,
                "source_identifier": (
                    identifiers[0] if len(identifiers) == 1 else None
                ),
                "source_identifiers": identifiers,
                "description": description,
                # Keep the parser's existing safe engine path. This value is
                # hidden from pilot surfaces by deferred_item_type_for_display.
                "item_type": "UNCLASSIFIED",
                "source_declaration": audit_lines[0]["text"],
                "company_remark": " | ".join(class_lines),
                "deferred_entry_id": deferred_entry_id,
                "classification_status": "unresolved",
                "classification_reason": (
                    "The OFP prints an opaque ECDL identifier without an "
                    "explicit MEL, CDL or CDDL mapping."
                ),
                "governed_match_status": "manual_review_required",
                "source_group_tokens": list(dict.fromkeys(group_tokens)),
                "source_page": source_page,
                "source_line_start": group_start + 1,
                "source_line_end": group_end + 1,
                "source_lines": audit_lines,
            },
        ))
    return groups


def _parse_deferred_items(
    page1: str,
    *,
    source_page: int = 1,
) -> list[dict[str, Any]]:
    return _walk_page1_declarations(page1, source_page=source_page)[0]


_REMARKS_HEADING = re.compile(r"^REMARKS\s*:?\s*$", re.IGNORECASE)
_DECLARATION_BLOCK_HEADING = re.compile(r"\bMAINTROL\b", re.IGNORECASE)


def _parse_page1_remarks(page1: str) -> list[dict[str, Any]]:
    """The dispatcher's general page-1 remarks: every remarks-block line that
    no declaration owns.

    SQ24 15 Aug prints a ZFW restriction, an EDTO top-up note, take-off
    performance inputs and the excess-fuel table under its one CDL. They are
    not the door seal's conditions, and they are not nothing either: they are
    held here, in their own domain, in the OFP's order.
    """
    lines = page1.splitlines()
    heading = next(
        (index for index, line in enumerate(lines) if _REMARKS_HEADING.match(line.strip())),
        None,
    )
    unowned = _walk_page1_declarations(page1)[1]
    first_declaration = _walk_page1_declarations(page1)[2]
    start = heading if heading is not None else first_declaration
    if start is None:
        return []
    return [
        {"text": text, "source_line": number}
        for number, text in unowned
        if number - 1 > start
        and not _DECLARATION_BLOCK_HEADING.search(text)
        and not re.fullmatch(r"[-=+*_ ]{3,}", text)
    ]


def _walk_page1_declarations(
    page1: str,
    *,
    source_page: int = 1,
) -> tuple[list[dict[str, Any]], list[tuple[int, str]], int | None]:
    """Walk page 1 once: the declarations, the lines none of them owns, and
    the index of the first declaration line."""
    # Boss's 21 Aug 2026 SQ910 CFP printed four declaration shapes on one
    # block: "CC MEL 25-20-50A", bare "BB CDDL" (no reference), "AA IFEDDL"
    # and "DD IN SIA/00-017 R1" (engineering information notice). Every
    # prefixed declaration is a first-class item under the CFP's own word —
    # never "UNCLASSIFIED"/"UNSPECIFIED", and never folded into the previous
    # item's remark (that is how the ENG 2 fan-cowl notice vanished).
    #
    # 19 Sep 2026 production audit: the boundary is the sequence label, and
    # only the label. What follows it decides how the item is classified,
    # never whether it exists — a declaration whose kind is not recognised is
    # held under its printed words as unresolved, so it can neither vanish nor
    # hand its conditions to the declaration above it.
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    lines = page1.splitlines()
    # Labels only ascend within a block, and headers share the block's margin.
    # Together these keep a wrapped body line that merely begins with two
    # equal letters inside the declaration it continues.
    last_label = ""
    header_indent: int | None = None
    # Where a declaration ENDS. Its body is the lines under its label; a
    # paragraph break followed by a line back at the block's margin is the
    # dispatcher moving on to something else (SQ24 15 Aug: the ZFW, EDTO and
    # take-off remarks under its one CDL). A wrapped body line that lands at
    # the margin WITHOUT a break (SQ882's chiller list) is still body text,
    # and so is an indented line after a break.
    gap_since_owned = False
    unowned: list[tuple[int, str]] = []
    first_declaration: int | None = None
    opaque_groups = _opaque_deferred_source_groups(
        page1,
        source_page=source_page,
    )
    opaque_starts = {
        start: (end, item)
        for start, end, item in opaque_groups
    }
    opaque_consumed = {
        index
        for start, end, _ in opaque_groups
        for index in range(start, end + 1)
    }
    for line_index, line in enumerate(lines):
        indent = len(line) - len(line.lstrip())
        if line_index in opaque_consumed:
            held = opaque_starts.get(line_index)
            if held is not None:
                if current:
                    items.append(_held_declaration(current))
                    current = None
                items.append(held[1])
                last_label = max([last_label, *held[1]["source_group_tokens"]])
                if header_indent is None:
                    header_indent = indent
                if first_declaration is None:
                    first_declaration = line_index
            gap_since_owned = False
            continue
        stripped = line.strip()
        if not stripped:
            gap_since_owned = True
            continue
        if _PLAN_BLOCK_HEADER.match(stripped):
            # The declarations belong to the remarks block; the plan block
            # that follows it is never part of one.
            break
        header = _DECLARATION_HEADER.match(stripped)
        if (
            header
            and header.group("token") > last_label
            and header_indent in (None, indent)
        ):
            if current:
                items.append(_held_declaration(current))
            last_label = header.group("token")
            header_indent = indent
            current = _classified_declaration(stripped, header.group("rest"))
            gap_since_owned = False
            if first_declaration is None:
                first_declaration = line_index
            continue
        if current and gap_since_owned and indent <= (header_indent or 0):
            items.append(_held_declaration(current))
            current = None
        if current:
            gap_since_owned = False
            if not current["description"]:
                current["description"] = stripped
            else:
                current["company_remark"] = f"{current['company_remark'] or ''} {stripped}".strip()
        else:
            unowned.append((line_index + 1, stripped))
    if current:
        items.append(_held_declaration(current))
    return items, unowned, first_declaration


def _held_declaration(item: dict[str, Any]) -> dict[str, Any]:
    """Close a declaration. One of unrecognised kind printed on a single line
    has no body to name its defect, so its own printed words are the defect."""
    printed = item.pop("_printed_words", None)
    if printed and not item["description"]:
        item["description"] = printed
    return item


def _classified_declaration(source_declaration: str, rest: str) -> dict[str, Any]:
    """Classify one declaration from the words printed after its label."""
    governed = _GOVERNED_DECLARATION.match(rest)
    if governed:
        return {
            "reference": governed.group("reference") or None,
            "description": (
                governed.group("dashed") or governed.group("undashed") or ""
            ).strip(),
            "item_type": governed.group("kind"),
            "source_declaration": source_declaration,
            "company_remark": None,
        }
    if rest == "IFEDDL":
        return {
            "reference": None,
            "description": "",
            "item_type": "IFEDDL",
            "source_declaration": source_declaration,
            "company_remark": None,
        }
    notice = _NOTICE_DECLARATION.match(rest)
    if notice:
        return {
            "reference": " ".join(notice.group("reference").split()),
            "description": (notice.group("description") or "").strip(),
            "item_type": notice.group("kind"),
            "source_declaration": source_declaration,
            "company_remark": None,
        }
    # The OFP printed a declaration whose kind this parser does not know
    # ("AA WEIGHT AND BALANCE MANUAL CHAPTER 8", "BB INFO IN"). It is still a
    # declaration: hold its printed words and say its class is unresolved.
    # Those words stand where "MEL 30-81-01A" would, so - as for any
    # block-shaped declaration - the defect is the line printed beneath them.
    return {
        "reference": None,
        "description": "",
        "_printed_words": rest,
        "item_type": "UNCLASSIFIED",
        "source_declaration": source_declaration,
        "company_remark": None,
        "classification_status": "unresolved",
        "classification_reason": (
            "The OFP prints this declaration without an explicit MEL, CDL or "
            "CDDL class."
        ),
        "governed_match_status": "manual_review_required",
    }


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


# The planned alternates: LIDO's "FLT PLANNING ALTN SUMMARY" table, ALTN/RWY  APPROACH  MINIMA  DIST  FL  COMP
# TIME  FUEL. APPROACH and MINIMA are optional columns; the genuine forms of the 30 held originals are
#   "EGKK/26L    CAT1DME   200FT/550M   0085   060 P003   0021 04014"   both printed (SQ322)
#   "YSSY/16R               1479FT/7000M 0705    350 P013   0142 09186"  APPROACH blank (SQ279)
#   "RJBB/06R                   0M       0519   330 P004   0122 07729"   APPROACH blank, minima "0M" (SQ606)
#   "WIDD/22                           0085  140 M003  0020 01802"     APPROACH and MINIMA blank (SQ303)
# (ALTERNATES-PARSE, 15 Oct 2026: the reader required a word in each column and skipped the other rows without a
# word - 16 alternates in 9 originals, SQ279's three among them, were never analysed.) The columns are told apart by
# word shape, never by position: a minima is digits with FT and/or M, an approach word holds a letter and is never
# minima-shaped. A blank column stays blank ("") and is never filled from a neighbouring column. A runway is a
# designator (two digits and an optional L, C or R), as on all 156 rows the corpus prints in both tables.
_ALTERNATE_MINIMA = r"(?:\d{1,5}FT/\d{1,5}M|\d{1,5}FT|\d{1,5}M)"
_ALTERNATE_APPROACH_WORD = rf"(?!{_ALTERNATE_MINIMA}(?![^ \t]))(?=[^ \t]*[A-Z])[A-Z0-9][A-Z0-9+./@-]*"
_ALTERNATE_RUNWAY = r"\d{2}[LCR]?"
_ALTERNATE_ROW = re.compile(
    rf"[ \t]*(?P<apt>[A-Z]{{4}})/(?P<rwy>{_ALTERNATE_RUNWAY})"
    rf"(?:[ \t]+(?P<approach>{_ALTERNATE_APPROACH_WORD}(?:[ \t]+{_ALTERNATE_APPROACH_WORD})*))?"
    rf"(?:[ \t]+(?P<minima>{_ALTERNATE_MINIMA}))?"
    r"[ \t]+(?P<dist>\d{4})[ \t]+\d{3}[ \t]+[MP]\d{3}[ \t]+(?P<time>\d{4})[ \t]+(?P<fuel>\d{5})[ \t]*"
)
# The destination table opens at its section heading as well as at its column header (59 of the 60 printings print the
# heading and its rule directly over the header; SQ606's page 1 puts a page break between them), so the table is still
# bounded if its column header is damaged or missing.
_ALTERNATE_TABLE_OPENER = re.compile(
    r"^[ \t]*(?:FLT[ \t]+PLANNING[ \t]+ALTN[ \t]+SUMMARY:|ALTN/RWY[ \t]+APPROACH[ \t]+MINIMA\b)"
)
# The EDTO table, "EDTO ENROUTE ALTN AIRPORTS:" / APT  PERIOD CHKD  RWY  APCH  MINIMA; APCH is printed blank too
# (SQ34 "PASY     2155-0140           28                                400FT/2409M"). APCH and MINIMA are read by the
# same word shapes as the destination table, so a word that is neither (a damaged cell, a stray line) is never taken
# for an approach.
_EDTO_ALTERNATE_ROW = re.compile(
    rf"[ \t]*(?P<airport>[A-Z]{{4}})[ \t]+(?P<start>\d{{4}})-(?P<end>\d{{4}})[ \t]+(?P<runway>{_ALTERNATE_RUNWAY})"
    rf"(?:[ \t]+(?P<approach>{_ALTERNATE_APPROACH_WORD}(?:[ \t]+{_ALTERNATE_APPROACH_WORD})*))?"
    rf"(?:[ \t]+(?P<minima>{_ALTERNATE_MINIMA}))?[ \t]*"
)
# The EDTO table opens at its section heading as well as at its column header (all 20 EDTO originals print the heading
# directly over the header), so the table is still bounded if its column header is damaged.
_EDTO_ALTERNATE_TABLE_OPENER = re.compile(
    r"^[ \t]*(?:EDTO[ \t]+ENROUTE[ \t]+ALTN[ \t]+AIRPORTS:|APT[ \t]+PERIOD[ \t]+CHKD[ \t]+RWY[ \t]+APCH[ \t]+MINIMA\b)"
)
# Row identity (QA504-01). A destination row opens with "<ICAO>/" and a runway cell, readable or not ("YMML/34",
# "YMML/??", "YMML/"); an EDTO row opens with its airport standing alone and then its period cell, readable or not, or
# - the period blank - its runway. A period or runway cell never holds a letter (a runway's final L, C or R aside), so a
# line that opens with a four-letter word and then any other word with letters - "RNAV GPS LNAV/VNAV 700FT/3109M",
# "CIRC VORDME@21R ..." - is an approach continuing the row before it, never a new row (found by the mutation test: an
# EDTO row wrapped after its runway).
_ALTERNATE_ROW_IDENTITY = re.compile(r"[ \t]*(?P<airport>[A-Z]{4})/(?P<runway>[^ \t]*)")
_EDTO_ALTERNATE_ROW_IDENTITY = re.compile(
    r"[ \t]*(?P<airport>[A-Z]{4})(?![^ \t])(?:[ \t]+(?P<period>[^ \t]+))?(?:[ \t]+(?P<runway>[^ \t]+))?"
)


def _destination_row_identity(line: str) -> tuple[str, str | None] | None:
    """The airport and the printed runway cell ("" when blank) of a line that opens a destination row, else None."""
    match = _ALTERNATE_ROW_IDENTITY.match(line)
    if match is None or re.search(r"[A-Z]", re.sub(r"[LCR]$", "", match.group("runway"))):
        return None
    return match.group("airport"), match.group("runway")


def _edto_row_identity(line: str) -> tuple[str, str | None] | None:
    """The airport and the printed runway cell of a line that opens an EDTO row, else None. The runway cell is the
    word after a readable period ("" when none); with the period itself unreadable there is no runway cell to judge."""
    match = _EDTO_ALTERNATE_ROW_IDENTITY.match(line)
    period = match.group("period") if match else None
    if match is None or (
        period is not None
        and re.search(r"[A-Z]", period)
        and not re.fullmatch(_ALTERNATE_RUNWAY, period)  # the runway, its period cell blank
    ):
        return None
    readable_period = period is not None and re.fullmatch(r"\d{4}-\d{4}", period) is not None
    return match.group("airport"), (match.group("runway") or "") if readable_period else None


# QA504-01 (Codex QA of release 504, 15 Oct 2026): the accounting ended a table at the first line that did not open as
# a readable row, and "readable" required a runway. "YMML/??" (or "YMML/", or a fuel value wrapped onto its own line)
# therefore closed the table and every row after it disappeared without a review. A table is now bounded by the LIDO
# layout itself, never by the readability of its rows:
#   - it opens at its section heading or its column header (a heading's rule and the header under it open nothing);
#   - the destination table closes at its own trailer, the "<ICAO> RTE:" lines LIDO prints after every printing (all
#     60 printings in the 30 originals), and the EDTO table at the next section heading ("STATION WEATHER REPORTS",
#     in all 20); either closes at any section heading - a label ending in ":" or "!", a labelled field ("SID: ..."),
#     a line underlined by a rule, a rule, a dot-leader form line ("ARR ATIS ......"), the package's own mixed-case
#     text ("Airport WX List") - at another table's header, or at the end of the CFP section;
#   - page furniture (package footer, running header, LIDO page header) and blank lines inside are skipped.
# Every other line inside is accounted: a row start (its identity is readable), a continuation of that row (a line
# without an identity that, appended, makes the row read whole - a row wrapped onto the next line), or an unread line
# held with its raw text. A damaged cell or a continuation never closes a table, and nothing is inferred: a row is read
# only when its own printed text reads whole under the row grammar.
_ALTERNATE_ROUTE_LINE = re.compile(r"[ \t]*(?P<airport>[A-Z]{4})[ \t]+RTE:")
_ALTERNATE_SECTION_LABEL = re.compile(r"[ \t]*[A-Z][A-Z0-9 /&().,'-]*[:!][ \t]*")
# A labelled field of the next block ("SID: WSSS/20C ...", "DISP BY: ..."): a label of words, then a colon. No alternate
# row holds a colon after words alone.
_ALTERNATE_FIELD_LABEL = re.compile(r"[ \t]*[A-Z][A-Z ()/.&'-]*[A-Z)]:(?:[ \t]|$)")
_ALTERNATE_SECTION_RULE = re.compile(r"[ \t]*(?:-{3,}|={3,})[ \t]*")
_ALTERNATE_FORM_LEADER = re.compile(r"\.{5,}")
_ALTERNATE_TABLES = {
    "destination_alternates": {
        "header": _ALTERNATE_TABLE_OPENER,
        "identity": _destination_row_identity,
        "row": _ALTERNATE_ROW,
        "name": "FLT PLANNING ALTN SUMMARY table",
        "columns": "ALTN/RWY [APPROACH] [MINIMA] DIST FL COMP TIME FUEL",
    },
    "edto_alternates": {
        "header": _EDTO_ALTERNATE_TABLE_OPENER,
        "identity": _edto_row_identity,
        "row": _EDTO_ALTERNATE_ROW,
        "name": "EDTO ENROUTE ALTN AIRPORTS table",
        "columns": "APT PERIOD RWY [APCH] [MINIMA]",
    },
}
_ALTERNATE_ROW_NOT_READ = (
    "the row is printed in the {table} but the row grammar ({columns}) does not read it; the alternate is not "
    "analysed here"
)
_ALTERNATE_RUNWAY_NOT_READ = (
    "the row is printed in the {table} but its runway is not readable (\"{runway}\"); the alternate is not analysed "
    "here and no runway is assumed"
)
_ALTERNATE_LINE_NOT_READ = (
    "a line is printed inside the {table} that neither opens a row nor completes the row before it; it is held as "
    "printed and nothing in it is analysed"
)
_ALTERNATE_PRINTINGS_DIFFER = (
    "the OFP prints the {table} more than once and its printings give this alternate different rows (both are "
    "quoted); neither is analysed here"
)
_ALTERNATE_DECLARED_NOT_READ = (
    "the OFP declares this planned alternate in its route line, but no row for it was read from the {table}; the "
    "alternate is not analysed here"
)


def _alternate_table_ends(stream: list[tuple[int, str]], index: int) -> bool:
    """Whether the line at ``index`` is past the alternate table it would belong to (see QA504-01 above)."""
    line = stream[index][1]
    if (
        _ALTERNATE_ROUTE_LINE.match(line)
        or _ALTERNATE_SECTION_LABEL.fullmatch(line)
        or _ALTERNATE_FIELD_LABEL.match(line)
        # The LIDO OFP prints in capitals; a line in mixed case is the briefing package's own text ("Airport WX List").
        or re.search(r"[a-z]", line)
        or _ALTERNATE_SECTION_RULE.fullmatch(line)
        or _ALTERNATE_FORM_LEADER.search(line)
        or any(spec["header"].match(line) for spec in _ALTERNATE_TABLES.values())
    ):
        return True
    following = next((text for _, text in stream[index + 1:] if text.strip()), "")
    return bool(_ALTERNATE_SECTION_RULE.fullmatch(following))


def _alternate_table_entries(table: str, lines: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """One printing of a table, line by line: every line becomes a read row, an unread row or an unread line."""
    spec = _ALTERNATE_TABLES[table]
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        page_number, line = lines[index]
        identity = spec["identity"](line)
        if identity is None:
            entries.append({"kind": "line", "airport": None, "runway": None, "text": " ".join(line.split()),
                            "source_page": page_number, "position": len(entries)})
            index += 1
            continue
        following = index + 1
        while following < len(lines) and spec["identity"](lines[following][1]) is None:
            following += 1
        tails = lines[index + 1:following]
        # A row wrapped onto the next line(s) reads whole only with them; the longest such reading is the row. A row
        # that reads by itself and is followed by a line that does not complete it keeps that line as its own entry.
        match, consumed = None, 0
        for count in range(len(tails), -1, -1):
            candidate = spec["row"].fullmatch(" ".join([line.rstrip(), *(text.strip() for _, text in tails[:count])]))
            if candidate is not None:
                match, consumed = candidate, count
                break
        printed = " ".join(" ".join([line, *(text for _, text in tails[:consumed])]).split())
        # The runway cell as printed: "" when blank, None when the row gives no runway cell to judge.
        airport, runway_token = identity
        runway = runway_token if runway_token and re.fullmatch(_ALTERNATE_RUNWAY, runway_token) else None
        entries.append({
            "kind": "row" if match is not None else "unread",
            "airport": airport,
            "runway": runway,
            "runway_token": runway_token,
            "match": match,
            "text": printed,
            "source_page": page_number,
            "position": len(entries),
        })
        for tail_page, tail in tails[consumed:]:
            entries.append({"kind": "line", "airport": None, "runway": None, "text": " ".join(tail.split()),
                            "source_page": tail_page, "position": len(entries)})
        index = following
    return entries


def _destination_alternate_row(match: re.Match[str]) -> dict[str, Any]:
    return {
        "airport": match.group("apt"),
        "runway": match.group("rwy"),
        "approach": " ".join((match.group("approach") or "").split()),
        "minima": match.group("minima") or "",
        "distance_nm": int(match.group("dist")),
        "time_minutes": int(match.group("time")[:2]) * 60 + int(match.group("time")[2:]),
        "fuel_kg": int(match.group("fuel")),
    }


def _unread_alternate(table: str, entry: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "table": table,
        "airport": entry["airport"],
        "runway": entry["runway"],
        "text": entry["text"],
        "source_page": entry["source_page"],
        "position": entry["position"],
        "reason": reason,
    }


def _entry_reason(table: str, entry: dict[str, Any]) -> str:
    spec = _ALTERNATE_TABLES[table]
    if entry["kind"] == "line":
        return _ALTERNATE_LINE_NOT_READ.format(table=spec["name"])
    if entry["runway"] is None and entry.get("runway_token") is not None:
        return _ALTERNATE_RUNWAY_NOT_READ.format(table=spec["name"], runway=entry["runway_token"])
    return _ALTERNATE_ROW_NOT_READ.format(table=spec["name"], columns=spec["columns"])


def _read_alternate_tables(cfp_pages: list[str], start_page_number: int = 1) -> dict[str, list[dict[str, Any]]]:
    """Read both alternate tables inside their printed bounds and account for every line in them.

    Returns the destination alternates read (``alternates``), the EDTO rows read (``edto_rows``, regex matches) and
    every row or line not read (``unread``: its table, airport when the identity is readable, runway when readable,
    raw text, page, place in the table and the reason).

    The destination table is printed twice in a LIDO OFP (the summary page and the full CFP); the printings are
    reconciled by printed identity, never by inference: an alternate read in one printing is read, and its damaged copy
    in the other is not a second review; an alternate whose printings give different rows is not analysed from either;
    an alternate unread in every printing is held once. A line with no readable identity cannot be matched to an
    alternate without guessing, so it is held as printed. Last, every alternate the OFP declares in a "<ICAO> RTE:"
    route line that is neither read nor held is held too, so an alternate whose identity is damaged in every printing
    is still named.
    """
    stream = [
        (start_page_number + index, line)
        for index, page in enumerate(cfp_pages)
        for line in page.splitlines()
    ]
    printings: list[dict[str, Any]] = []
    declared: list[tuple[str, str, int]] = []
    current: dict[str, Any] | None = None
    for index, (page_number, line) in enumerate(stream):
        route = _ALTERNATE_ROUTE_LINE.match(line)
        if route:
            declared.append((route.group("airport"), " ".join(line.split()), page_number))
        table = next((name for name, spec in _ALTERNATE_TABLES.items() if spec["header"].match(line)), None)
        if table is not None:
            if current is not None and current["table"] == table and not current["lines"]:
                continue  # the column header under the table's section heading
            current = {"table": table, "lines": []}
            printings.append(current)
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped or _NOTAM_PAGE_FURNITURE.fullmatch(stripped) or _LIDO_PAGE_HEADER_RE.match(line):
            continue
        if not current["lines"] and _ALTERNATE_SECTION_RULE.fullmatch(line):
            continue  # the rule under the table's section heading
        if _alternate_table_ends(stream, index):
            current = None
            continue
        current["lines"].append((page_number, line))

    unread: list[dict[str, Any]] = []
    held_lines: set[tuple[str, str]] = set()

    # Destination alternates: every printing, reconciled by printed identity.
    destination = [
        (printing_index, entry)
        for printing_index, printing in enumerate(p for p in printings if p["table"] == "destination_alternates")
        for entry in _alternate_table_entries("destination_alternates", printing["lines"])
    ]
    read_rows: dict[str, list[tuple[tuple[int, int], dict[str, Any], dict[str, Any]]]] = {}
    for printing_index, entry in destination:
        if entry["kind"] == "row":
            read_rows.setdefault(entry["airport"], []).append(
                ((entry["position"], printing_index), _destination_alternate_row(entry["match"]), entry))
    alternates_by_place: list[tuple[tuple[int, int], dict[str, Any]]] = []
    differing: dict[str, dict[str, Any]] = {}
    for airport, occurrences in read_rows.items():
        distinct = list(dict.fromkeys(tuple(sorted(row.items())) for _, row, _ in occurrences))
        if len(distinct) == 1:
            alternates_by_place.append((occurrences[0][0], occurrences[0][1]))
        else:
            first = {**occurrences[0][2], "text": " / ".join(dict.fromkeys(entry["text"] for _, _, entry in occurrences))}
            differing[airport] = _unread_alternate("destination_alternates", first, _ALTERNATE_PRINTINGS_DIFFER.format(
                table=_ALTERNATE_TABLES["destination_alternates"]["name"]))
    alternates = [row for _, row in sorted(alternates_by_place, key=lambda item: item[0])]
    read_airports = {row["airport"] for row in alternates}
    held_airports: set[str] = set()
    for _, entry in destination:
        airport = entry["airport"]
        if entry["kind"] == "row":
            if airport in differing and airport not in held_airports:
                held_airports.add(airport)
                unread.append(differing[airport])
            continue
        if entry["kind"] == "unread":
            if airport in read_airports or airport in held_airports:
                continue
            if airport in differing:
                held_airports.add(airport)
                unread.append(differing[airport])
                continue
            held_airports.add(airport)
            unread.append(_unread_alternate("destination_alternates", entry, _entry_reason("destination_alternates", entry)))
            continue
        if ("destination_alternates", entry["text"]) in held_lines:
            continue
        held_lines.add(("destination_alternates", entry["text"]))
        unread.append(_unread_alternate("destination_alternates", entry, _entry_reason("destination_alternates", entry)))
    declared_order = list(dict.fromkeys(airport for airport, _, _ in declared))
    for airport, text, page_number in declared:
        if airport in read_airports or airport in held_airports:
            continue
        held_airports.add(airport)
        unread.append({
            "table": "destination_alternates",
            "airport": airport,
            "runway": None,
            "text": text,
            "source_page": page_number,
            "position": declared_order.index(airport),
            "reason": _ALTERNATE_DECLARED_NOT_READ.format(table=_ALTERNATE_TABLES["destination_alternates"]["name"]),
        })

    # EDTO alternates: printed once; one airport can be checked in more than one period, so each row stands alone.
    edto_rows: list[re.Match[str]] = []
    for printing in (p for p in printings if p["table"] == "edto_alternates"):
        for entry in _alternate_table_entries("edto_alternates", printing["lines"]):
            if entry["kind"] == "row":
                edto_rows.append(entry["match"])
                continue
            if ("edto_alternates", entry["text"]) in held_lines:
                continue
            held_lines.add(("edto_alternates", entry["text"]))
            unread.append(_unread_alternate("edto_alternates", entry, _entry_reason("edto_alternates", entry)))
    return {"alternates": alternates, "edto_rows": edto_rows, "unread": unread}


def _parse_alternates(cfp_pages: list[str]) -> list[dict[str, Any]]:
    """The destination alternates read inside the bounds of every printing of their table (QA504-01)."""
    return _read_alternate_tables(cfp_pages)["alternates"]


def _alternate_rows_not_read(cfp_pages: list[str], start_page_number: int) -> list[dict[str, Any]]:
    """Every row or line printed inside an alternate table that is not read, held verbatim (QA504-01)."""
    return _read_alternate_tables(cfp_pages, start_page_number)["unread"]


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


# Codex QA of release 468 (10 Oct 2026, F1): ARINC 424 latitude/longitude fix names are waypoints too - "5350N" (53N
# 050W; letter last when the longitude is below 100) and "18E30" (18N 130E; letter in the middle when it is 100 or more).
# Unread, each left the row before it (a FIR boundary or ENTRY point) open to take its coordinates: SQ34's -KZAK sat
# 706 NM from its printed position and SQ023's 5350N VWS 005 event was missing.
_WAYPOINT_LINE = re.compile(
    r"^(?P<name>\*\*ETP\S*|-[A-Z0-9]+|\d{4}[NESW]|\d{1,2}[NESW]\d{2,3}|[A-Z][A-Z0-9]{1,8}|TOC|TOD|ENTRY\d|EXIT\d)"
    r"(?:\s+\d{3}(?:\.\d+)?)?\s+(?P<actm>\d{2}\.\d{2})\b"
)
# 10 Oct 2026 (genuine SQ437 MLE-SIN, David: "Look at OBDAL and see 114?"): LIDO prints an equal-time point with its
# scenario ("**ETP1 -1D   02.03 0.10 ..."). The row was not recognised, so the waypoint before it stayed open and took
# the ETP's coordinate line - the ETP's position, and the first three digits of its leg distance as its MSA (OBDAL
# 020 -> 007; SQ24's 62N20 111 -> 000). 28 such rows in 14 of the 30 originals. An ETP row closes the waypoint before it
# and is not itself a route waypoint, as no ETP row ever was.
_ETP_SCENARIO_LINE = re.compile(r"^\*\*ETP\S*\s+-\d[A-Z]\s+\d{2}\.\d{2}\b")
# F4 (Codex QA of release 468): the MSA column holds exactly three digits (or three and an asterisk). A row that prints
# none - each destination, ENTRY/EXIT and ETP point - goes straight to its four-digit distance, whose first three digits
# were read as the MSA (SQ024's KJFK "0069" became MSA 006). No MSA is printed there, so none is read.
_COORDINATE_LINE = re.compile(
    r"^(?P<lat_hem>[NS])(?P<lat_deg>\d{2})\s+(?P<lat_min>\d{2}\.\d+)\s+"
    r"(?P<lon_hem>[EW])(?P<lon_deg>\d{3})\s+(?P<lon_min>\d{2}\.\d+)\s+"
    r"(?:(?P<msa>\d{3})(?:(?P<star>\*)|(?![0-9])))?"
)
_NAVLOG_HEADER = re.compile(r"^POSN\s+FREQ\s+ACTM\b")
_COMPUTED_POINT = re.compile(r"(?:ENTRY|EXIT)\d+")
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
        # F2 (Codex QA of release 468): the log's own column header marks its first page even when only one row fits
        # under it (SQ365 SOSAK, SQ297/SQ304 IBIXU were dropped when the search waited for a page with two).
        headed = False
        for line in text.splitlines():
            stripped = line.strip()
            if _NAVLOG_HEADER.match(stripped):
                headed = True
            elif _WAYPOINT_LINE.match(stripped):
                armed = True
            elif armed and _COORDINATE_LINE.match(stripped):
                pairs += 1
                armed = False
                if pairs >= 2 or headed:
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
            if _ETP_SCENARIO_LINE.match(line.strip()):
                if pending:
                    waypoints.append(pending)
                pending = None
                continue
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
                    # F3 (Codex QA of release 468): only ENTRYn/EXITn are computed EDTO points; "EXITI" (SQ304) is a fix.
                    computed = name.startswith(("-", "**ETP")) or _COMPUTED_POINT.fullmatch(name) is not None or name in {"TOC", "TOD"}
                    if not computed and coordinate.group("msa") is not None:
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
    airports: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    # The rows are read inside the bounds of the EDTO ENROUTE ALTN AIRPORTS table, one printed row at a time, by the
    # word-shape grammar that keeps a blank APCH or MINIMA blank (ALTERNATES-PARSE and QA504-01, 15 Oct 2026).
    for match in _read_alternate_tables([edto_text])["edto_rows"]:
        approach = match.group("approach") or ""
        minima = match.group("minima") or ""
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


# SLOT-ALLOCATION-434 (independent QA of release 434, F3). The slot-control allocation a dispatcher prints: the fields
# WPT, FL, CTO, CTOT in that order, after an optional "<SYSTEM> ALLOCATION" label. Genuine packs print them spaced
# ("WPT BIROS FL 380 CTO 2328 CTOT 1752"), comma-separated on the line after the label, hyphenated between pipes
# ("WPT-BIROS | FL-360 | CTO-2100 | CTOT-1527") and colon-joined ("WPT DOBAT FL:360 CTO:2202 CTOT:1627"); the grammar
# fixes the field order, not the separators. The same grammar, token for token, is parseSlotAllocation in the app's
# cfp.mjs (tests/test_slot_allocation_grammar_20260927.py replays every case through both).
_ALLOCATION_KEY_SEPARATOR = r"\s*[:\-=–]?\s*"
_ALLOCATION_FIELD_SEPARATOR = r"(?:\s*[,|;/]\s*|\s+)"
_ALLOCATION_CLOCK = r"[0-9]{2}:?[0-9]{2}(?![0-9:])Z?"
_SLOT_ALLOCATION = re.compile(
    r"(?:\b(?P<system>[A-Z][A-Z0-9]{1,11})\s*ALLOCATION\b\s*[:\-–]?\s*)?"
    r"\bWPT(?:\s*[:\-=–]\s*|\s+)(?P<waypoint>(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,7})"
    + _ALLOCATION_FIELD_SEPARATOR + r"FL" + _ALLOCATION_KEY_SEPARATOR + r"(?P<level>[0-9]{2,3})(?![0-9])"
    + _ALLOCATION_FIELD_SEPARATOR + r"CTO" + _ALLOCATION_KEY_SEPARATOR + r"(?P<cto>" + _ALLOCATION_CLOCK + r")"
    + _ALLOCATION_FIELD_SEPARATOR + r"CTOT" + _ALLOCATION_KEY_SEPARATOR + r"(?P<ctot>" + _ALLOCATION_CLOCK + r")"
    + r"(?P<note>[^\n]*)",
    re.IGNORECASE,
)
_SLOT_ALLOCATION_LABEL = re.compile(r"\b(?P<system>[A-Z][A-Z0-9]{1,11})\s*ALLOCATION\b\s*[:\-–]?", re.IGNORECASE)
_SLOT_ALLOCATION_WPT = re.compile(r"\bWPT\b", re.IGNORECASE)
_SLOT_ALLOCATION_TIME_KEY = re.compile(r"\bCTOT?\b", re.IGNORECASE)
_SLOT_FLOW_SYSTEMS = {"BOBCAT", "ATFM", "CFMU", "SLOT", "FLOW"}
_SLOT_SYSTEM_MENTION = re.compile(r"\b(BOBCAT|ATFM|CFMU)\b", re.IGNORECASE)
_SLOT_ALLOCATION_FORM = "not in the WPT / FL / CTO / CTOT form"
_SLOT_ALLOCATION_WINDOW = 3  # the anchor line and the two lines after it: a wrapped label or field sequence
_SLOT_ALLOCATION_QUOTE = 120


def _allocation_clock(printed: str) -> str | None:
    digits = printed.upper().rstrip("Z").replace(":", "")
    return digits if int(digits[:2]) <= 23 and int(digits[2:]) <= 59 else None


def parse_slot_allocation(pages: list[tuple[int, str]]) -> dict[str, Any]:
    """The first readable slot-control allocation in ``pages`` (in search order), else the first printed one that does
    not read - never absence for an allocation the OFP prints.

    Returns ``{"allocation": {system, waypoint, level, cto, ctot, note, page} | None,
    "unread": {text, page, reason} | None}``; ``cto`` / ``ctot`` are the printed HHMM clocks. Evidence that an
    allocation is printed is a label of a flow system ("BOBCAT ALLOCATION") or a line printing WPT with CTO or CTOT;
    another kind of allocation ("GATE ALLOCATION") or a CTOT mentioned alone is not.
    """
    unread: dict[str, Any] | None = None
    for page_number, text in pages:
        lines = [" ".join(line.split()) for line in str(text or "").split("\n")]
        lines = [line for line in lines if line]
        for index, line in enumerate(lines):
            label = _SLOT_ALLOCATION_LABEL.search(line)
            if not label and not _SLOT_ALLOCATION_WPT.search(line):
                continue
            window = "\n".join(lines[index:index + _SLOT_ALLOCATION_WINDOW])
            match = next((m for m in _SLOT_ALLOCATION.finditer(window) if m.start() <= len(line)), None)
            reason = _SLOT_ALLOCATION_FORM
            if match:
                level = int(match.group("level"))
                cto = _allocation_clock(match.group("cto"))
                ctot = _allocation_clock(match.group("ctot"))
                if not 10 <= level <= 600:
                    reason = f"FL{match.group('level')} is not a flight level"
                elif cto is None:
                    reason = f"CTO {match.group('cto')} is not a UTC clock time"
                elif ctot is None:
                    reason = f"CTOT {match.group('ctot')} is not a UTC clock time"
                else:
                    named = match.group("system")
                    mentioned = _SLOT_SYSTEM_MENTION.search(line)
                    system = named.upper() if named else (mentioned.group(1).upper() if mentioned else "SLOT")
                    return {
                        "allocation": {
                            "system": system,
                            "waypoint": match.group("waypoint").upper(),
                            "level": level,
                            "cto": cto,
                            "ctot": ctot,
                            "note": match.group("note").strip().strip("*").strip(),
                            "page": page_number,
                        },
                        "unread": None,
                    }
            printed = bool(label and label.group("system").upper() in _SLOT_FLOW_SYSTEMS) or bool(
                _SLOT_ALLOCATION_WPT.search(line) and _SLOT_ALLOCATION_TIME_KEY.search(line)
            )
            if unread is None and (printed or match):
                quote = line
                if label and not line[label.end():].strip() and index + 1 < len(lines):
                    quote = f"{line} {lines[index + 1]}"
                if len(quote) > _SLOT_ALLOCATION_QUOTE:
                    quote = quote[:_SLOT_ALLOCATION_QUOTE - 1].rstrip() + "…"
                unread = {"text": quote, "page": page_number, "reason": reason}
    return {"allocation": None, "unread": unread}


def _slot_allocation_search_pages(pages: list[str], sections: dict[str, tuple[int, int]], cfp_start: int,
                                  summary_group: list[int]) -> list[tuple[int, str]]:
    """The summary (logical page 1) first, then every other page before the NOTAM bulletin - the app searches the same."""
    end = sections["notam"][0] if "notam" in sections else len(pages)
    summary = [cfp_start + index for index in summary_group]
    order = summary + [index for index in range(end) if index not in summary]
    return [(index + 1, pages[index]) for index in order]


_EXPLICIT_NIL_EDTO = re.compile(
    r"\b(?:EDTO|ETOPS)(?:\s+(?:STATUS|APPLICABILITY))?\s*[:=-]?\s*"
    r"(?:NIL|N/?A|NOT\s+APPLICABLE)\b|"
    r"\b(?:NIL|NOT\s+APPLICABLE)\s+(?:EDTO|ETOPS)\b|"
    r"\bSUMMARY\s+NON[ -]+(?:EDTO|ETOPS)\s+CFP\b",
    re.IGNORECASE,
)


# The Lido header line continues with the flight identity ("PAGE  1 OF 11
# SIA882 SIN/HKG 10SEP26"); the briefing-package footer ("Page 2 of 75") ends
# the line, so the negative lookahead keeps footers from posing as headers.
_LIDO_PAGE_HEADER_RE = re.compile(
    r"^\s*PAGE\s+(\d+)\s+OF\s+(\d+)\b(?![ \t]*$)",
    re.MULTILINE | re.IGNORECASE,
)
_LIDO_PACKAGE_FOOTER_RE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.MULTILINE)


def _lido_logical_page_groups(cfp_pages: list[str]) -> list[list[int]]:
    """Group physical CFP pages into the Lido logical pages they print.

    Lido prints ``PAGE n OF total`` once per logical page. When the page-1
    remarks block is long (David's SQ882 OFP of 10 Sep 2026 carried three
    MEL/CDL entries) the briefing package overflows that logical page onto a
    second physical PDF page that carries only the package footer
    (``Page k of N``). Such a footer-bearing, header-less page continues the
    preceding logical page; the fuel ladder lives there. Any other header-less
    page keeps its own group, so physical page numbering and the fail-closed
    sequence proof are unchanged for every other layout.
    """
    groups: list[list[int]] = []
    for index, text in enumerate(cfp_pages):
        if (
            groups
            and not _LIDO_PAGE_HEADER_RE.search(text)
            and _LIDO_PAGE_HEADER_RE.search(cfp_pages[groups[-1][0]])
            and _LIDO_PACKAGE_FOOTER_RE.search(text)
        ):
            groups[-1].append(index)
            continue
        groups.append([index])
    return groups


def _lido_logical_page_text(cfp_pages: list[str], group: list[int]) -> str:
    return "\n".join(cfp_pages[index] for index in group)


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

    # One logical Lido page may span two physical pages (page-1 overflow);
    # the sequence proof counts logical pages, each led by its printed header.
    logical_pages = _lido_logical_page_groups(cfp_pages)
    page_headers: list[tuple[int, int]] = []
    for group in logical_pages:
        header = _LIDO_PAGE_HEADER_RE.search(cfp_pages[group[0]])
        if not header:
            return None
        page_headers.append((int(header.group(1)), int(header.group(2))))

    declared_total = page_headers[0][1]
    if (
        declared_total != len(logical_pages)
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
    # The contingency line: "STAT CONT" or "<n>% CONT" (app/odss/fuel_rows.py); its printed label is held on the row.
    ("stat_cont", CONTINGENCY_LABEL),
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
        match = re.search(rf"({label})\s+(\d{{1,2}}\.\d{{2}})\s+0*(\d+)", text)
        rows[name] = (
            {"time_minutes": actm_minutes(match.group(2)), "fuel_kg": int(match.group(3))}
            if match
            else None
        )
        if match and name == "stat_cont":
            rows[name]["label"] = " ".join(match.group(1).split())

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
    # Logical page 1 may overflow onto a footer-only physical page; the fuel
    # ladder and masses are read from the whole logical page.
    page1 = _lido_logical_page_text(cfp_pages, _lido_logical_page_groups(cfp_pages)[0])
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
    slot_allocation_unread = None
    slot_allocation = parse_slot_allocation(
        _slot_allocation_search_pages(pages, sections, cfp_start, _lido_logical_page_groups(cfp_pages)[0])
    )
    allocation = slot_allocation["allocation"]
    if allocation:
        waypoint = next(
            (
                item
                for item in waypoints
                if str(item.get("name") or "").lstrip("-").upper() == allocation["waypoint"]
            ),
            None,
        )
        predicted_crossing = departure_utc + timedelta(
            minutes=int((waypoint or {}).get("actm_minutes") or 0)
        )
        bobcat = {
            "waypoint": allocation["waypoint"],
            "flight_level": allocation["level"],
            "cto_utc": _utc_nearest(predicted_crossing, allocation["cto"]).isoformat(),
            "ctot_utc": _utc_nearest(departure_utc, allocation["ctot"]).isoformat(),
            "system": allocation["system"],
            "source_page": allocation["page"],
        }
    elif slot_allocation["unread"]:
        unread = slot_allocation["unread"]
        # Printed but not read: held verbatim so no surface can publish it as absent.
        slot_allocation_unread = {"text": unread["text"], "source_page": unread["page"], "reason": unread["reason"]}

    fuel = {
        "trip_fuel_kg": _int_group(page1, r"BURNOFF\s+\d{2}\.\d{2}\s+0*(\d+)"),
        "contingency_fuel_kg": _int_group(page1, rf"{CONTINGENCY_LABEL}\s+\d{{2}}\.\d{{2}}\s+0*(\d+)"),
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
    fuel_summary = parse_page1_fuel_summary(page1)
    alternate_tables = _read_alternate_tables(cfp_pages, cfp_start + 1)
    alternates = alternate_tables["alternates"]
    alternates_unread = alternate_tables["unread"]
    # Page 1 names the planned first alternate ("ALTN SYD (YSSY)"); an OFP whose table does not yield it has an
    # alternate this reader did not see, which is a review too.
    page_one_alternate = ((fuel_summary or {}).get("alternate") or {}).get("icao")
    if (
        page_one_alternate
        and page_one_alternate not in {row["airport"] for row in alternates}
        and page_one_alternate not in {
            row["airport"] for row in alternates_unread if row["table"] == "destination_alternates"
        }
    ):
        page_one_line = re.search(rf"^.*ALTN\s+[A-Z]{{3}}\s+\({page_one_alternate}\).*$", page1, re.MULTILINE)
        alternates_unread.append({
            "table": "destination_alternates",
            "airport": page_one_alternate,
            "runway": None,
            "text": " ".join((page_one_line.group(0) if page_one_line else page_one_alternate).split()),
            "source_page": cfp_start + 1,
            "position": 0,
            "reason": (
                "page 1 names this alternate, but no row for it was read from the FLT PLANNING ALTN SUMMARY table; "
                "the alternate is not analysed here"
            ),
        })
    level_match = re.search(r"^[A-Z]{3}/\d{3}(?:/.*)?$", page1, re.MULTILINE)
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
        {str(w.get("name") or "").upper().lstrip("-") for w in waypoints if isinstance(w, dict)},
    )
    notam_fir_names = _parse_notam_fir_names(pages, sections.get("notam"))
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
        "slot_allocation_unread": slot_allocation_unread,
        "deferred_items": _parse_deferred_items(page1),
        "page1_remarks": _parse_page1_remarks(page1),
        # Lossless bounded company-bulletin identities. No route relevance,
        # applicability or operational conclusion is inferred here.
        "intam_records": intam_records,
        # Source-held CPDLC/ADS-C procedure records. Presence does not prove
        # route applicability; publishing surfaces retain that explicit gate.
        "notam_procedure_records": notam_procedure_records,
        "notam_fir_names": notam_fir_names,
        # The extraction rules this parse applied (extraction_rules.py); a
        # composition over an analysis without the value in service says so.
        "extraction_rules": EXTRACTION_RULES,
        "alternates": alternates,
        # Rows printed inside an alternate table that were not read (normally none): each one is a stated review on
        # the findings and in the alternate matrix, never a silent absence.
        "alternates_unread": alternates_unread,
        "performance": performance,
        "fuel": fuel,
        # The complete page-1 summary with its arithmetic proved; display
        # layers key off its state and must show a review flag, not figures,
        # when it is anything but "verified".
        "fuel_summary": fuel_summary,
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
