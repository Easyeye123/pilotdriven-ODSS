"""The combined Flight Briefing — one PDF, the boss's 11-page 07 Aug spec.

Replaces the pilot-facing Level 1 / Level 2 pair. The layout, section order,
palette and chrome follow SQ365_07AUG2026_Flight_Briefing.pdf line by line;
that spec was generated against this product's own web design tokens, so the
theme below IS the web token sheet, not a new palette. Naming rule from the
same instruction list: no "Level 1", "Level 2", "Pertinent" or "Evidence
level" anywhere on a page.

Every figure printed here comes from the parsed CFP, a held governed source,
or a deterministic derivation of those — anything unverified renders as a
review flag, never as a number. AI authority: none.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlencode

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics

from . import brief_theme as theme
from .brief_theme import MONO, MONO_BOLD, SANS, SANS_BOLD, register_fonts
from .briefing import (
    _edto_classification,
    _edto_gate_sentence,
    _edto_operational_rows,
)
from .constants import format_actm

PAGE_SIZE = landscape(A4)

# ---------------------------------------------------------------------------
# Palette — the web token sheet, verbatim (--pd-* values).
# ---------------------------------------------------------------------------
BG = colors.HexColor("#08111c")
PANEL = colors.HexColor("#0e1b2a")
ELEVATED = colors.HexColor("#13263a")
BORDER = colors.HexColor("#23374d")
ACCENT = colors.HexColor("#2f80ed")
DEPARTURE = colors.HexColor("#2d9cdb")
DESTINATION = colors.HexColor("#9b51e0")
EDTO_GREEN = colors.HexColor("#27ae60")
WEATHER_AMBER = colors.HexColor("#f2c94c")
COMMS_TEAL = colors.HexColor("#2dcecf")
TERRAIN_ORANGE = colors.HexColor("#f2994a")
CRITICAL = colors.HexColor("#eb5757")
TEXT = colors.HexColor("#f5f7fa")
TEXT_SECONDARY = colors.HexColor("#a9b6c5")
TEXT_MUTED = colors.HexColor("#6f8095")

MARGIN = 26.0
HEADER_H = 64.0
FOOTER_H = 26.0

# Type scale: the old brief sizes +20% per instruction 3 ("especially for
# detailed content words and numerics").
T_TITLE = 19.0        # page section title
T_FLIGHT = 25.0       # header flight number
T_CARD_HEAD = 9.2     # panel title bars
T_BODY = 9.2
T_VALUE = 12.5        # stat values
T_SMALL = 8.0
T_MICRO = 7.2

# Keep MEL/CDL cards at the cockpit-readable type scale.  More governing
# references create continuation pages instead of being dropped or squeezed.
MEL_CDL_GROUPS_PER_PAGE = 4

# Part of the cached-report identity. Bump whenever the publication contract
# changes so an analysis created before a deployment cannot keep serving an
# older PDF from persistent report storage.
COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-17-responsive-deferred-source-v3"


_FIT_FLOOR = T_MICRO


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    """Largest size <= requested that keeps text inside max_width (rule 8:
    nothing may overlap or overrun its box)."""
    width = pdfmetrics.stringWidth(text, font, size)
    if width <= max_width or width <= 0:
        return size
    return max(_FIT_FLOOR, size * max_width / width)


def _draw_string_fitted(canvas, x, y, text, font, size, max_width, colour):
    """Draw text inside max_width, shrinking to the floor and then
    TRUNCATING — a string may lose its tail but may never run under a
    neighbouring element (08 Aug audit: floor-clamped copy crossed columns)."""
    value = str(text)
    fitted = _fit(value, font, size, max_width)
    if pdfmetrics.stringWidth(value, font, fitted) > max_width:
        ellipsis = "…"
        while value and pdfmetrics.stringWidth(value + ellipsis, font, fitted) > max_width:
            value = value[:-1]
        value = (value + ellipsis) if value else ""
    canvas.setFillColor(colour)
    canvas.setFont(font, fitted)
    canvas.drawString(x, y, value)
    return fitted


# ---------------------------------------------------------------------------
# Logo — vector geometry lifted from the spec header (pd-logo-vectors), four
# polygons in token colours. Never a raster, never the letter X.
# ---------------------------------------------------------------------------
_LOGO_SHAPES = (
    # (fill, points) in a 34.7 x 20.3 local box, origin bottom-left.
    (colors.HexColor("#f4f6f9"), ((0.0, 0.0), (26.9, 6.2), (18.7, 9.4), (0.0, 5.4))),
    (ACCENT, ((0.0, 8.2), (29.6, 9.8), (20.3, 13.3), (0.0, 11.6))),
    (colors.HexColor("#f4f6f9"), ((0.0, 20.3), (26.9, 13.7), (18.7, 10.9), (0.0, 15.2))),
    (COMMS_TEAL, ((25.0, 6.2), (34.7, 10.1), (25.0, 14.4), (27.9, 10.1))),
)


def draw_logo(canvas, x: float, y: float, height: float = 14.0, wordmark: bool = True) -> float:
    """Draw the swoosh at (x, y) bottom-left; returns total width used."""
    scale = height / 20.3
    canvas.saveState()
    canvas.translate(x, y)
    canvas.scale(scale, scale)
    for fill, points in _LOGO_SHAPES:
        path = canvas.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        canvas.setFillColor(fill)
        canvas.drawPath(path, stroke=0, fill=1)
    canvas.restoreState()
    width = 34.7 * scale
    if wordmark:
        size = height * 0.52
        canvas.setFont(SANS_BOLD, size)
        canvas.setFillColor(TEXT)
        canvas.drawString(x + width + 5, y + height * 0.28, "PILOT")
        pilot_w = pdfmetrics.stringWidth("PILOT", SANS_BOLD, size)
        canvas.setFillColor(ACCENT)
        canvas.drawString(x + width + 5 + pilot_w + 2, y + height * 0.28, "DRIVEN")
        width += 5 + pilot_w + 2 + pdfmetrics.stringWidth("DRIVEN", SANS_BOLD, size)
    return width


# ---------------------------------------------------------------------------
# Page chrome.
# ---------------------------------------------------------------------------


def _header_times(flight: dict[str, Any]) -> tuple[str, str]:
    utc_line = (
        "UTC DEP "
        + theme.utc_hhmm(flight.get("scheduled_departure_utc"))
        + " -> ARR "
        + theme.utc_hhmm(flight.get("scheduled_arrival_utc"))
    )
    departure_segment = theme.local_time_segment(
        flight.get("departure"), flight.get("scheduled_departure_utc")
    )
    arrival_segment = theme.local_time_segment(
        flight.get("destination"), flight.get("scheduled_arrival_utc")
    )
    local_line = (
        f"LT {departure_segment}  ->  {arrival_segment}"
        if departure_segment and arrival_segment
        else "LT UNAVAILABLE - REVIEW"
    )
    return utc_line, local_line


def draw_page_chrome(
    canvas,
    flight: dict[str, Any],
    *,
    page_number: int,
    page_count: int,
    source_line: str,
) -> float:
    """Background, header band, footer, SOURCE line. Returns content top y."""
    register_fonts()
    width, height = PAGE_SIZE
    canvas.setFillColor(BG)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    top = height - 16
    draw_logo(canvas, MARGIN, top - 26, height=13.0)

    # Flight identity block.
    identity_x = width * 0.19
    flight_number = theme.display_flight_number(flight)
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 23)
    canvas.drawString(identity_x, top - 17, flight_number)
    canvas.setFont(SANS_BOLD, 10.5)
    canvas.drawString(
        identity_x,
        top - 33,
        f"{theme.airport_code_label(flight.get('departure'))} -> "
        f"{theme.airport_code_label(flight.get('destination'))}",
    )
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 7.4)
    canvas.drawString(
        identity_x,
        top - 44,
        f"{flight.get('aircraft_type') or ''} | "
        f"{theme.normalized_registration(flight.get('registration'))}"
        + (f" | CAPT {flight.get('captain')}" if flight.get("captain") else ""),
    )

    # Centre schedule block.
    centre_x = width * 0.50
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 9.6)
    canvas.drawString(centre_x, top - 16, theme.header_date_label(flight))
    utc_line, local_line = _header_times(flight)
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    canvas.drawString(centre_x, top - 27, utc_line)
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, T_MICRO)
    canvas.drawString(centre_x, top - 37, local_line)

    # Right: block time + product pill.
    block_label = theme.block_time_label(flight)
    if block_label:
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 10.5)
        canvas.drawRightString(width * 0.80, top - 16, block_label)
    pill_text = "FLIGHT BRIEFING"
    pill_w = pdfmetrics.stringWidth(pill_text, SANS_BOLD, 7.4) + 26
    pill_x = width - MARGIN - pill_w
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.1)
    canvas.setFillColor(BG)
    canvas.roundRect(pill_x, top - 24, pill_w, 16, 8, stroke=1, fill=1)
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 7.4)
    canvas.drawCentredString(pill_x + pill_w / 2, top - 18.6, pill_text)
    if page_number > 1:
        back_text = "BACK TO OVERVIEW"
        back_w = pdfmetrics.stringWidth(back_text, SANS_BOLD, T_MICRO) + 20
        back_x = width - MARGIN - back_w
        back_y = top - 80
        canvas.setFillColor(ELEVATED)
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.8)
        canvas.roundRect(back_x, back_y, back_w, 16, 8, stroke=1, fill=1)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawCentredString(back_x + back_w / 2, back_y + 5.5, back_text)
        canvas.linkRect(
            "",
            "sec_overview",
            (back_x, back_y, back_x + back_w, back_y + 16),
            relative=0,
            thickness=0,
        )
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawRightString(width - MARGIN, top - 34, f"Page {page_number} of {page_count}")

    # Header rule.
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, top - 48, width - MARGIN, top - 48)

    # Footer.
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawString(
        MARGIN,
        9,
        " | ".join(
            value
            for value in (
                "FLIGHT BRIEFING",
                theme.display_flight_number(flight),
                (
                    f"{flight.get('aircraft_type') or ''} "
                    f"{theme.normalized_registration(flight.get('registration'))}"
                ).strip(),
                theme.header_date_label(flight),
            )
            if value
        ),
    )
    canvas.drawRightString(
        width - MARGIN,
        9,
        "DIRECT SOURCES + DETERMINISTIC DERIVATION | AI AUTHORITY: NONE",
    )
    # SOURCE line above the footer.
    canvas.setFillColor(ACCENT)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(MARGIN, 21, "SOURCE")
    _draw_string_fitted(
        canvas, MARGIN + 34, 21, source_line[:180], SANS, T_MICRO,
        width - 2 * MARGIN - 34, TEXT_MUTED,
    )
    return top - 56


def draw_section_title(canvas, y: float, text: str) -> float:
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, T_TITLE)
    canvas.drawString(MARGIN, y - T_TITLE, text.upper())
    return y - T_TITLE - 8


def panel(canvas, x, y, w, h, *, title, accent, title_colour=colors.white) -> tuple[float, float, float, float]:
    """Spec panel: elevated card with a colored full-width title bar on top.
    Returns the inner content box (x, y, w, h)."""
    bar_h = 15.0
    canvas.setFillColor(ELEVATED)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.7)
    canvas.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    canvas.setFillColor(accent)
    canvas.roundRect(x, y + h - bar_h, w, bar_h, 6, stroke=0, fill=1)
    canvas.rect(x, y + h - bar_h, w, bar_h / 2, stroke=0, fill=1)
    _draw_string_fitted(
        canvas, x + 8, y + h - bar_h + 4.4, str(title).upper(),
        SANS_BOLD, T_CARD_HEAD, w - 16, title_colour,
    )
    return (x + 8, y + 6, w - 16, h - bar_h - 12)


def stat_card(canvas, x, y, w, h, *, label, value, caption, accent, mono=True) -> None:
    """Spec stat card: thin accent strip on top, label, big value, caption."""
    canvas.setFillColor(ELEVATED)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.7)
    canvas.roundRect(x, y, w, h, 5, stroke=1, fill=1)
    canvas.setFillColor(accent)
    canvas.rect(x + 1, y + h - 2.6, w - 2, 2.6, stroke=0, fill=1)
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, T_SMALL)
    canvas.drawString(x + 8, y + h - 13, str(label).upper())
    _draw_string_fitted(
        canvas, x + 8, y + h / 2 - 4, str(value),
        MONO_BOLD if mono else SANS_BOLD, T_VALUE, w - 16, TEXT,
    )
    if caption:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(x + 8, y + 5, str(caption)[:60])


def open_link(canvas, x, y, *, label="OPEN", accent=ACCENT, destination: str | None) -> None:
    """The spec's OPEN> jump chip; a real internal link when a destination
    bookmark is supplied."""
    w = pdfmetrics.stringWidth(label, SANS_BOLD, T_MICRO) + 18
    canvas.setFillColor(accent)
    canvas.roundRect(x - w, y, w, 12, 6, stroke=0, fill=1)
    canvas.setFillColor(BG)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawCentredString(x - w / 2, y + 3.4, label)
    if destination:
        canvas.linkRect("", destination, (x - w, y, x, y + 12), relative=0, thickness=0)


def review_line(canvas, x, y, text) -> None:
    canvas.setFillColor(WEATHER_AMBER)
    canvas.setFont(SANS_BOLD, T_SMALL)
    canvas.drawString(x, y, str(text))


# ---------------------------------------------------------------------------
# Page 1 — FLIGHT OVERVIEW.
# ---------------------------------------------------------------------------

_GATES = (
    # (key, label, accent, bookmark) — order per the spec's decision-gate list.
    ("mel_cdl", "MEL/CDL", DEPARTURE, "sec_mel_cdl"),
    ("edto", "EDTO", EDTO_GREEN, "sec_alternates"),
    ("terrain", "TERRAIN", TERRAIN_ORANGE, "sec_terrain"),
    ("va_wx", "VA / WX", WEATHER_AMBER, "sec_hazard"),
    ("airports", "AIRPORTS", DESTINATION, "sec_airports"),
    ("kabul_fir", "KABUL / FIR", COMMS_TEAL, "sec_comms"),
)


def _edto_source_classification(flight: dict[str, Any]) -> str:
    fuel_summary = flight.get("fuel_summary") or {}
    source = str(fuel_summary.get("source_classification") or "").strip().upper()
    return source or _edto_classification(flight)


def _edto_gate_label(flight: dict[str, Any]) -> str:
    classification = _edto_classification(flight)
    if classification.startswith("NON"):
        return "NON-EDTO"
    if classification == "EDTO":
        return "EDTO"
    return "EDTO REVIEW"


def _first_title(findings: list[dict[str, Any]], engines: set[str]) -> str | None:
    for finding in findings:
        if str(finding.get("engine")) in engines:
            title = str(finding.get("summary") or finding.get("title") or "").strip()
            if title:
                return title
    return None


def _unique_text(values: list[Any]) -> list[str]:
    """Keep first-seen display text while collapsing repeated CFP wording."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = " ".join(text.upper().split())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def governed_deferred_source_target(
    flight: dict[str, Any],
    item: dict[str, Any],
    *,
    public_origin: str | None = None,
) -> str | None:
    """Durable signed-in app target for the exact current governed source.

    The PDF never embeds a presigned S3 URL: that would work during QA and
    expire minutes later. The landing route repeats only facts already printed
    in the report, then the signed-in app resolves the current approved source
    and opens its cited page.
    """
    item_type = str(item.get("item_type") or "").strip().upper()
    reference = str(item.get("reference") or "").strip().upper()
    if item_type not in {"MEL", "CDL", "CDDL"} or not re.fullmatch(
        r"[A-Z0-9][A-Z0-9._/-]{0,79}", reference
    ):
        return None
    origin = str(
        public_origin
        or os.environ.get("PILOTDRIVEN_PUBLIC_ORIGIN")
        or "https://www.pilotdriven.com"
    ).strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d{1,5})?", origin):
        return None
    values = {
        "type": item_type,
        "reference": reference,
        "flightNumber": str(flight.get("flight_number") or "").strip().upper(),
        "registration": str(flight.get("registration") or "").strip().upper(),
        "aircraftType": str(flight.get("aircraft_type") or "").strip().upper(),
        "departure": str(flight.get("departure") or "").strip().upper(),
        "destination": str(flight.get("destination") or "").strip().upper(),
        "sourcePage": "1",
    }
    query = urlencode({key: value for key, value in values.items() if value})
    return f"{origin}/#/governed-deferred-reference?{query}"


def _group_deferred_items(flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Group separate defect lines governed by the same MEL/CDL reference.

    A CFP can list two cabin defects under one MEL reference.  They remain two
    source facts, but repeating the same reference in the decision gate makes
    the report look as though the parser duplicated a row.  This display view
    keeps both descriptions/remarks while presenting the governing reference
    once.  The raw parser payload is left unchanged for audit use.
    """
    grouped: dict[tuple[str, str] | tuple[str, int], list[dict[str, Any]]] = {}
    order: list[tuple[str, str] | tuple[str, int]] = []
    for index, source in enumerate(flight.get("deferred_items") or []):
        item = dict(source)
        item_type = str(item.get("item_type") or "ITEM").strip().upper()
        reference = str(item.get("reference") or "").strip().upper()
        key: tuple[str, str] | tuple[str, int] = (
            (item_type, reference) if reference else ("__ROW__", index)
        )
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    result: list[dict[str, Any]] = []
    for key in order:
        source_items = grouped[key]
        merged = dict(source_items[0])
        descriptions = _unique_text([item.get("description") for item in source_items])
        remarks = _unique_text([item.get("company_remark") for item in source_items])
        penalties = _unique_text([item.get("penalty") for item in source_items])
        merged["description"] = descriptions[0] if descriptions else ""
        merged["company_remark"] = " | ".join([
            *remarks,
            *descriptions[1:],
        ]) or None
        merged["penalty"] = " | ".join(penalties) or None
        merged["source_item_count"] = len(source_items)
        result.append(merged)
    return result


def _gate_lines(
    briefing: dict[str, Any], flight: dict[str, Any], findings: list[dict[str, Any]]
) -> dict[str, str]:
    deferred = _group_deferred_items(flight)
    deferred_line = (
        "; ".join(
            f"{item.get('item_type')} {item.get('reference')}".strip()
            for item in deferred[:2]
        )
        if deferred
        else "No deferred item on CFP page 1"
    )
    classification = _edto_classification(flight)
    source = _edto_source_classification(flight)
    edto_line = (
        "CFP page 1: SUMMARY STANDARD CFP (non-EDTO)"
        if source == "STANDARD" and classification.startswith("NON")
        else f"CFP classified {classification} CFP"
        if classification
        else "CFP classification requires review"
    )
    # Verbatim from the briefing view - the one terrain sentence composed in
    # build_briefing_view. Recomposing it here is how the overview once
    # contradicted the terrain page.
    terrain_line = str(
        (briefing.get("terrain") or {}).get("summary")
        or "Terrain review required"
    )
    va_line = _first_title(findings, {"weather"}) or "Weather review on the hazard page"
    airports_line = _first_title(findings, {"notam"}) or "Airport restrictions reviewed"
    comms_line = _first_title(findings, {"communications"}) or "No early FIR contact requirement"
    return {
        "mel_cdl": deferred_line,
        "edto": edto_line,
        "terrain": terrain_line,
        "va_wx": va_line,
        "airports": airports_line,
        "kabul_fir": comms_line,
    }


def _airport_card(canvas, x, y, w, h, *, title, accent, headline, body, tag):
    inner = panel(canvas, x, y, w, h, title=title, accent=accent)
    ix, iy, iw, ih = inner
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 10.6)
    _draw_string_fitted(canvas, ix, y + h - 32, str(headline)[:64], SANS_BOLD, 10.6, iw, TEXT)
    # The tag band at the card foot is RESERVED: the body may take only as
    # many wrapped lines as fit above it, however long the airport copy runs
    # (08 Aug audit: four fixed lines could reach the DEP/DEST tag).
    leading = 9.4
    tag_band = 14.0
    body_top = y + h - 45
    max_lines = max(1, int((body_top - (y + tag_band)) // leading))
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, T_SMALL)
    text = canvas.beginText(ix, body_top)
    text.setLeading(leading)
    wrapped: list[str] = []
    for paragraph in str(body).split("\n"):
        wrapped.extend(_wrap(paragraph, SANS, T_SMALL, iw))
    if len(wrapped) > max_lines:
        wrapped = wrapped[:max_lines]
        wrapped[-1] = wrapped[-1].rstrip(" .") + " ..."
    for out_line in wrapped:
        text.textLine(out_line)
    canvas.drawText(text)
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawRightString(x + w - 8, y + 6, str(tag).upper())


def _fuel_panel_rows(fuel_summary: dict[str, Any]) -> list[tuple[str, str]]:
    rows = fuel_summary.get("rows") or {}
    masses = fuel_summary.get("masses_kg") or {}

    def timed(name: str) -> str:
        row = rows.get(name) or {}
        minutes = row.get("time_minutes")
        fuel_kg = row.get("fuel_kg")
        if minutes is None or fuel_kg is None:
            return "--"
        return f"{format_actm(minutes).replace('.', ':')} | {fuel_kg:,} kg"

    def mass(name: str) -> str:
        value = masses.get(name)
        return f"{value:,} kg" if value is not None else "--"

    ground = fuel_summary.get("ground_miles_nm")
    return [
        ("GROUND", f"{ground:,} NM" if ground else "--"),
        ("BURNOFF", timed("burnoff")),
        ("FPL REQMT", timed("flt_plan_reqmt")),
        ("FUEL IN TANKS", timed("fuel_in_tanks")),
        ("PZFW", mass("pzfw")),
        ("PTOW", mass("ptow")),
        ("PLWT", mass("plwt")),
        ("EXCESS", timed("excess_fuel")),
    ]


def draw_overview_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line="CFP p.1 fuel summary, route log and NOTAM bulletin | controlled deferred-item sources",
    )
    canvas.bookmarkPage("sec_overview")
    y = draw_section_title(canvas, content_top, "Flight Overview")

    # Left column: three EQUAL airport cards + decision gates (instruction 1:
    # same size, same dimensions, aligned text).
    left_w = (width - 2 * MARGIN) * 0.385
    # Tall enough for a wrapped METAR plus the TAF's opening line - the raw
    # bulletins are the card content now, and a card that silently swallowed
    # the TAF is exactly the drift the parity gate flags.
    card_h = 100.0
    gap = 8.0
    departure_panel = briefing.get("departure") or {}
    destination_panel = briefing.get("destination") or {}
    alternates = flight.get("alternates") or []
    fuel_summary = flight.get("fuel_summary") or {}

    def weather_line(panel_data: dict[str, Any]) -> str:
        # The actual CFP bulletins, METAR and TAF each starting their own
        # line (16 Aug instruction). The overlap narrative is a fallback for
        # stations whose bulletins the CFP does not carry.
        weather = panel_data.get("weather") or {}
        metar = str(weather.get("metar") or "").strip()
        taf = str(weather.get("taf") or "").strip()
        if metar or taf:
            return "\n".join(
                part
                for part in (
                    f"METAR {metar}" if metar else None,
                    f"TAF {taf}" if taf else None,
                )
                if part
            )
        return str(
            weather.get("primary")
            or weather.get("secondary")
            or weather.get("summary")
            or weather.get("detail")
            or "Weather review on the hazard assessment page."
        )

    top_y = y - card_h
    _airport_card(
        canvas, MARGIN, top_y, left_w, card_h,
        title=f"DEPARTURE - {theme.airport_code_label(departure_panel.get('icao') or flight.get('departure'))}",
        accent=DEPARTURE,
        headline=str(departure_panel.get("runway") or "Runway review"),
        body=weather_line(departure_panel),
        tag="DEP",
    )
    mid_y = top_y - gap - card_h
    _airport_card(
        canvas, MARGIN, mid_y, left_w, card_h,
        title=f"DESTINATION - {theme.airport_code_label(destination_panel.get('icao') or flight.get('destination'))}",
        accent=DESTINATION,
        headline=str(destination_panel.get("runway") or "Runway review"),
        body=weather_line(destination_panel),
        tag="DEST",
    )
    primary_alternate = alternates[0] if alternates else {}
    summary_alternate = fuel_summary.get("alternate") or {}
    altn_headline = (
        f"{theme.airport_code_label(primary_alternate.get('airport') or summary_alternate.get('icao'))}"
        f"{'/' + str(primary_alternate.get('runway')) if primary_alternate.get('runway') else ''}"
        f" | {primary_alternate.get('approach') or 'approach review'}"
    )
    altn_rows = fuel_summary.get("rows") or {}
    altn_fuel = (altn_rows.get("altn_fuel") or {}).get("fuel_kg")
    altn_time = (altn_rows.get("altn_fuel") or {}).get("time_minutes")
    hold_fuel = (altn_rows.get("altn_hold") or {}).get("fuel_kg")
    altn_body = " | ".join(
        part
        for part in (
            f"{primary_alternate.get('distance_nm')} NM" if primary_alternate.get("distance_nm") else None,
            f"{format_actm(altn_time).replace('.', ':')}" if altn_time is not None else None,
            f"{altn_fuel:,} kg" if altn_fuel is not None else None,
            f"hold {hold_fuel:,} kg" if hold_fuel is not None else None,
        )
        if part
    ) or "Alternate planning data requires review."
    low_y = mid_y - gap - card_h
    _airport_card(
        canvas, MARGIN, low_y, left_w, card_h,
        title=f"ALTERNATE - {theme.airport_code_label(primary_alternate.get('airport') or summary_alternate.get('icao')) if primary_alternate or summary_alternate else 'REVIEW'}",
        accent=WEATHER_AMBER,
        headline=altn_headline[:52],
        body=altn_body,
        tag="ALTN",
    )

    # Decision gates panel sized to its rows — the spec's list is compact and
    # a panel padded with dead space reads as missing content.
    gates_top = low_y - gap
    row_h = 19.0
    gates_h = min(gates_top - 34, row_h * len(_GATES) + 26)
    inner = panel(
        canvas, MARGIN, gates_top - gates_h, left_w, gates_h,
        title="DECISION GATES", accent=ACCENT,
    )
    ix, iy, iw, ih = inner
    lines = _gate_lines(briefing, flight, findings)
    row_h = (gates_h - 24) / max(1, len(_GATES))
    row_y = gates_top - 24
    for key, label, accent, bookmark in _GATES:
        if key == "edto":
            label = _edto_gate_label(flight)
        chip_w = pdfmetrics.stringWidth(label, SANS_BOLD, T_MICRO) + 14
        canvas.setFillColor(accent)
        canvas.roundRect(ix, row_y - 3.8, chip_w, 12.5, 6.25, stroke=0, fill=1)
        canvas.setFillColor(BG)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawCentredString(ix + chip_w / 2, row_y, label)
        _draw_string_fitted(
            canvas, ix + chip_w + 6, row_y, lines.get(key) or "",
            SANS, T_MICRO, iw - chip_w - 6 - 44, TEXT_SECONDARY,
        )
        canvas.setFillColor(ACCENT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawRightString(ix + iw - 6, row_y, "OPEN >")
        canvas.linkRect("", bookmark, (ix + iw - 40, row_y - 3.4, ix + iw, row_y + 8), relative=0, thickness=0)
        row_y -= row_h

    # Right column: route map panel + CFP PAGE 1 panel.
    right_x = MARGIN + left_w + 12
    right_w = width - MARGIN - right_x
    fuel_h = 92.0
    map_h = y - 30 - fuel_h - 10
    map_inner = panel(
        canvas, right_x, y - map_h, right_w, map_h,
        title=(
            f"{theme.display_flight_number(flight)} "
            f"{theme.airport_code_label(flight.get('departure'))}-"
            f"{theme.airport_code_label(flight.get('destination'))} | "
            "OPERATIONAL ROUTE / DECISION GATES"
        ),
        accent=PANEL, title_colour=TEXT,
    )
    mx, my, mw, mh = map_inner
    from .briefing import draw_route_map_pdf  # local import; briefing pulls widely

    draw_route_map_pdf(canvas, briefing.get("route_map") or {}, mx, my, mw, mh)

    # CFP PAGE 1 - FLIGHT PLAN panel.
    fuel_inner = panel(
        canvas, right_x, y - map_h - 10 - fuel_h, right_w, fuel_h,
        title="CFP PAGE 1 - FLIGHT PLAN", accent=COMMS_TEAL, title_colour=BG,
    )
    fx, fy, fw, fh = fuel_inner
    state = str(fuel_summary.get("state") or "")
    if not fuel_summary:
        review_line(
            canvas, fx, fy + fh / 2,
            "Page-1 fuel summary is not held for this analysis - review CFP page 1 directly.",
        )
    elif state != "verified":
        review_line(
            canvas, fx, fy + fh / 2,
            "Page-1 fuel summary did not verify against its own arithmetic - review the source CFP page.",
        )
        if fuel_summary.get("discrepancies"):
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawString(fx, fy + fh / 2 - 10, "; ".join(fuel_summary["discrepancies"])[:150])
    else:
        rows = _fuel_panel_rows(fuel_summary)
        cell_w = (fw - 3 * 8) / 4
        cell_h = (fh - 6) / 2
        for index, (label, value) in enumerate(rows):
            col = index % 4
            row = index // 4
            cx = fx + col * (cell_w + 8)
            cy = fy + fh - (row + 1) * cell_h - row * 4
            canvas.setFillColor(PANEL)
            canvas.roundRect(cx, cy, cell_w, cell_h - 3, 4, stroke=0, fill=1)
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawString(cx + 6, cy + cell_h - 12, label)
            _draw_string_fitted(
                canvas, cx + 6, cy + 6, value, MONO_BOLD, 8.8, cell_w - 12, TEXT,
            )


# ---------------------------------------------------------------------------
# Shared timeline strip.
# ---------------------------------------------------------------------------


def _timeline(canvas, x, y, w, entries, *, accent_default=COMMS_TEAL) -> None:
    """Horizontal dot timeline: entries are dicts with time, label, sub,
    accent. Times sit above the rail, labels below — the spec's strip."""
    if not entries:
        review_line(canvas, x, y + 10, "No timeline events derived from the CFP - review required.")
        return
    step = w / max(1, len(entries) - 1) if len(entries) > 1 else 0
    rail_y = y + 13
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(1.2)
    canvas.line(x, rail_y, x + w, rail_y)
    for index, entry in enumerate(entries):
        cx = x + (index * step if len(entries) > 1 else w / 2)
        accent = entry.get("accent") or accent_default
        canvas.setFillColor(accent)
        canvas.circle(cx, rail_y, 3.4, stroke=0, fill=1)
        canvas.setFont(MONO_BOLD, 7.4)
        time_text = str(entry.get("time") or "--")
        tw = pdfmetrics.stringWidth(time_text, MONO_BOLD, 7.4)
        canvas.drawString(min(max(x, cx - tw / 2), x + w - tw), rail_y + 8, time_text)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        label = str(entry.get("label") or "")[:14]
        lw = pdfmetrics.stringWidth(label, SANS_BOLD, T_MICRO)
        canvas.drawString(min(max(x, cx - lw / 2), x + w - lw), rail_y - 15, label)
        sub = str(entry.get("sub") or "")[:20]
        if sub:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, T_MICRO)
            sw = pdfmetrics.stringWidth(sub, SANS, T_MICRO)
            canvas.drawString(min(max(x, cx - sw / 2), x + w - sw), rail_y - 24, sub)


def _clock_at(flight: dict[str, Any], actm_minutes_value: int | None) -> str:
    from datetime import datetime, timedelta, timezone

    if actm_minutes_value is None:
        return "--"
    raw = flight.get("actual_takeoff_utc") or flight.get("scheduled_departure_utc")
    if not raw:
        return "--"
    try:
        moment = datetime.fromisoformat(str(raw))
    except ValueError:
        return "--"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment + timedelta(minutes=int(actm_minutes_value))).strftime("%H%MZ")


def _route_anchor_entries(flight: dict[str, Any], briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Six-anchor plan timeline: departure, notable events, arrival."""
    waypoints = [w for w in (flight.get("route_waypoints") or []) if w.get("actm_minutes") is not None]
    if not waypoints:
        return []
    first = waypoints[0]
    last = waypoints[-1]
    # Interesting anchors: FIR boundaries and high-MSA points, spread by time.
    interesting = [
        w for w in waypoints[1:-1]
        if w.get("fir_boundary") or (w.get("msa_hundreds_ft") or 0) > 100
    ] or waypoints[1:-1]
    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in sorted(interesting, key=lambda w: w.get("actm_minutes") or 0):
        name = str(candidate.get("name") or "").lstrip("-")
        if name and name not in seen:
            picks.append(candidate)
            seen.add(name)
    if len(picks) > 4:
        stride = len(picks) / 4
        picks = [picks[int(i * stride)] for i in range(4)]
    entries = []
    for w, sub in ((first, "DEP"), *((p, p.get("fir_boundary") or (f"MSA {p.get('msa_hundreds_ft')}*" if (p.get("msa_hundreds_ft") or 0) > 100 else "")) for p in picks), (last, "ARR")):
        entries.append({
            "time": _clock_at(flight, w.get("actm_minutes")),
            "label": str(w.get("name") or "").lstrip("-"),
            "sub": str(sub or ""),
            "accent": TERRAIN_ORANGE if (w.get("msa_hundreds_ft") or 0) > 100 else COMMS_TEAL if w.get("fir_boundary") else ACCENT,
        })
    return entries


def _hazard_gate_entries(flight: dict[str, Any], briefing: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for item in (briefing.get("communications") or [])[:5]:
        entries.append({
            "time": str(item.get("time") or "--").split(" ")[-1],
            "label": str(item.get("event") or "")[:16],
            "sub": str(item.get("detail") or "")[:22],
            "accent": WEATHER_AMBER,
        })
    return entries


def _kv_card_required_height(rows, width: float) -> float:
    """Return a readable content-led height for a time/gate card.

    Sparse cards used to be stretched from the timeline to the footer, which
    made three short operational summaries look like three mostly empty pages.
    The same wrapping calculation used while drawing now owns their height.
    """
    wrapped_rows = [
        (_wrap(str(value), SANS, T_SMALL, width - 84) or [""])[:2]
        for _, value in rows
    ]
    natural_height = sum(max(2, len(lines)) * 9.6 + 4 for lines in wrapped_rows)
    return max(90.0, 54.0 + natural_height)


def _time_gate_card_layout(
    *,
    full_width: float,
    cards_top: float,
    cards_bottom: float = 30.0,
    gap: float = 10.0,
) -> dict[str, tuple[float, float, float, float]]:
    """Lay out time/gate facts as one wide card plus a compact right stack.

    The previous three-column grid forced the one-row FIR summary to be as
    tall as the multi-row EDTO status and still left a large unused band below
    all three cards.  The mosaic lets the operationally dense EDTO block use
    the wide column while the two shorter summaries share the right column.
    Coordinates are relative to the page content margin.
    """
    usable_height = max(0.0, cards_top - cards_bottom)
    left_width = (full_width - gap) * 0.58
    right_width = full_width - left_width - gap
    stacked_height = max(0.0, (usable_height - gap) / 2)
    right_x = left_width + gap
    return {
        "edto": (0.0, cards_bottom, left_width, usable_height),
        "communications": (
            right_x,
            cards_bottom + stacked_height + gap,
            right_width,
            stacked_height,
        ),
        "operating": (
            right_x,
            cards_bottom,
            right_width,
            stacked_height,
        ),
    }


def _kv_card(canvas, x, y, w, h, *, title, accent, rows, open_target=None):
    """Spec card: label column + value text rows, optional OPEN link."""
    panel(canvas, x, y, w, h, title=title, accent=accent, title_colour=BG if accent in (COMMS_TEAL, WEATHER_AMBER, EDTO_GREEN) else colors.white)
    wrapped_rows = [
        (label, (_wrap(str(value), SANS, T_SMALL, w - 84) or [""])[:2])
        for label, value in rows
    ]
    natural_height = _kv_card_required_height(rows, w) - 54.0
    available_height = max(0.0, h - 54.0)
    compact = natural_height > available_height
    line_height = 9.6
    row_gap = 4.0
    if compact and wrapped_rows:
        line_count = sum(len(lines) for _, lines in wrapped_rows)
        row_gap = 2.0
        line_height = max(
            T_SMALL,
            min(9.6, (available_height - row_gap * len(wrapped_rows)) / max(1, line_count)),
        )
    elif len(wrapped_rows) > 1:
        reserved_text_height = sum(max(2, len(lines)) * line_height for _, lines in wrapped_rows)
        spare_height = max(0.0, available_height - reserved_text_height)
        row_gap = min(14.0, max(row_gap, spare_height / len(wrapped_rows)))
    row_y = y + h - 30
    for label, lines in wrapped_rows:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(x + 10, row_y, str(label).upper())
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS, T_SMALL)
        for line in lines:
            canvas.drawString(x + 72, row_y, line)
            row_y -= line_height
        if not compact and len(lines) < 2:
            row_y -= line_height
        row_y -= row_gap
    if open_target:
        open_link(canvas, x + w - 10, y + 8, label="OPEN", accent=accent, destination=open_target)


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Page 2 — TIME, EDTO STATUS, FIR AND OPERATING GATES.
# ---------------------------------------------------------------------------


def draw_time_gates_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP route log and timing anchors | FIR procedure extracts held in governed sources",
    )
    canvas.bookmarkPage("sec_time")
    classification = _edto_classification(flight)
    classification_label = classification or "EDTO REVIEW"
    y = draw_section_title(canvas, content_top, f"Time, {classification_label}, FIR and Operating Gates")

    full_w = width - 2 * MARGIN
    anchor_label = "FLIGHT-PLAN ANCHOR - ACTUAL TAKE-OFF" if flight.get("actual_takeoff_utc") else "FLIGHT-PLAN ANCHOR - SCHEDULED DEPARTURE"
    strip_h = 64.0
    inner = panel(canvas, MARGIN, y - strip_h, full_w, strip_h, title=anchor_label, accent=DEPARTURE)
    _timeline(canvas, inner[0] + 14, y - strip_h + 12, full_w - 44, _route_anchor_entries(flight, briefing))

    hazard_y = y - strip_h - 10
    hazard_entries = _hazard_gate_entries(flight, briefing)
    inner = panel(canvas, MARGIN, hazard_y - strip_h, full_w, strip_h, title="HAZARD AND COMMUNICATION GATES", accent=WEATHER_AMBER, title_colour=BG)
    _timeline(canvas, inner[0] + 14, hazard_y - strip_h + 12, full_w - 44, hazard_entries, accent_default=WEATHER_AMBER)

    # One wide EDTO card plus two compact cards. This uses the printable height
    # without forcing the sparse FIR summary into a mostly empty third column.
    cards_top = hazard_y - strip_h - 10
    edto_view = briefing.get("edto") or {}
    fuel_summary = flight.get("fuel_summary") or {}
    edto_rows = _edto_operational_rows(classification, edto_view, fuel_summary)

    comm_rows = []
    for item in (briefing.get("communications") or [])[:3]:
        comm_rows.append((str(item.get("event") or "")[:12], f"{item.get('time')} - {item.get('detail')}"))
    if not comm_rows:
        comm_rows = [("FIR", "No early FIR contact requirement derived from this CFP.")]

    deferred = _group_deferred_items(flight)
    operating_rows = [
        ("MEL/CDL", "; ".join(f"{i.get('item_type')} {i.get('reference')}" for i in deferred[:2]) or "No deferred item on CFP page 1."),
        ("DEP", str((briefing.get("departure") or {}).get("runway") or "Runway review.")),
        ("DEST", str((briefing.get("destination") or {}).get("runway") or "Runway review.")),
    ]
    layout = _time_gate_card_layout(full_width=full_w, cards_top=cards_top)
    edto_x, edto_y, edto_w, edto_h = layout["edto"]
    comm_x, comm_y, comm_w, comm_h = layout["communications"]
    gate_x, gate_y, gate_w, gate_h = layout["operating"]
    _kv_card(canvas, MARGIN + edto_x, edto_y, edto_w, edto_h, title=f"{classification_label} STATUS", accent=EDTO_GREEN, rows=edto_rows, open_target="sec_alternates")
    _kv_card(canvas, MARGIN + comm_x, comm_y, comm_w, comm_h, title="FIR / NEXT CONTACT", accent=COMMS_TEAL, rows=comm_rows, open_target="sec_comms")
    _kv_card(canvas, MARGIN + gate_x, gate_y, gate_w, gate_h, title="OPERATING GATES", accent=DEPARTURE, rows=operating_rows, open_target="sec_airports")


# ---------------------------------------------------------------------------
# Pages 3 + full-page profiles — HIGH TERRAIN AND DEPRESSURISATION.
# ---------------------------------------------------------------------------


def _terrain_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("engine") == "terrain"]


def _matched_profiles(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        f for f in findings
        if f.get("engine") == "depressurisation" and (f.get("data") or {}).get("chart_number")
    ]


def _terrain_profile_width(full_width: float, *, image_count: int) -> float:
    """Use all available width when only one governed profile is served."""
    return full_width if image_count == 1 else (full_width - 10.0) / 2


def _terrain_table_height(*, has_charts: bool, unmatched_count: int) -> float:
    """Reserve an unmatched table only when it carries non-redundant facts."""
    if has_charts and unmatched_count == 0:
        return 0.0
    if has_charts:
        return 74.0
    return max(96.0, 58.0 + min(3, unmatched_count) * 16.0)


def draw_terrain_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    chart_images: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    profile_page_numbers: dict[str, int],
) -> None:
    from io import BytesIO

    from reportlab.lib.utils import ImageReader

    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP route log MSA windows | A350 Depressurisation Profiles controlled attachments | strict MSA >100*",
    )
    canvas.bookmarkPage("sec_terrain")
    y = draw_section_title(canvas, content_top, "High Terrain Exposure and Depressurisation")

    full_w = width - 2 * MARGIN
    terrain = _terrain_findings(findings)
    matched = _matched_profiles(findings)
    unmatched = [f for f in terrain if not any(
        (m.get("data") or {}).get("start_actm_minutes") == (f.get("data") or {}).get("start_actm_minutes")
        for m in matched
    )]

    # Stat cards row.
    card_w = (full_w - 3 * 10) / 4
    card_h = 44.0
    cards_y = y - card_h
    stat_card(canvas, MARGIN, cards_y, card_w, card_h, label="STRICT >100*", value=str(len(terrain)), caption="MSA windows", accent=TERRAIN_ORANGE)
    stat_card(canvas, MARGIN + card_w + 10, cards_y, card_w, card_h, label="PROFILE MATCH", value=str(len(matched)), caption="approved", accent=EDTO_GREEN)
    stat_card(canvas, MARGIN + 2 * (card_w + 10), cards_y, card_w, card_h, label="UNRESOLVED", value=str(len(unmatched)), caption="manual review" if unmatched else "none", accent=CRITICAL if unmatched else EDTO_GREEN)
    stat_card(canvas, MARGIN + 3 * (card_w + 10), cards_y, card_w, card_h, label="EFFECTIVITY", value=theme.normalized_registration(flight.get("registration")) or "--", caption=str(flight.get("aircraft_type") or ""), accent=DEPARTURE, mono=True)

    # Profile cards with embedded cropped charts.
    table_h = _terrain_table_height(
        has_charts=bool(chart_images),
        unmatched_count=len(unmatched),
    )
    profiles_top = cards_y - 10
    profiles_h = (
        profiles_top - 30 - table_h - (10 if table_h else 0)
        if chart_images
        else 62.0
    )
    served_images = chart_images[:2]
    profile_w = _terrain_profile_width(full_w, image_count=len(served_images))
    accents = (EDTO_GREEN, WEATHER_AMBER)
    for index, image in enumerate(served_images):
        px = MARGIN + index * (profile_w + 10)
        chart_number = image.get("chart_number") or "--"
        finding = next((m for m in matched if (m.get("data") or {}).get("chart_number") == chart_number), {})
        data = finding.get("data") or {}
        title = f"PROFILE {chart_number}" + (f" - CP {data.get('critical_point')}" if data.get("critical_point") else "")
        inner = panel(canvas, px, profiles_top - profiles_h, profile_w, profiles_h, title=title, accent=accents[index % 2], title_colour=BG)
        ix, iy, iw, ih = inner
        # White sheet behind the chart raster, preserving aspect.
        pad = 4
        sheet_h = ih - 22
        canvas.setFillColor(colors.white)
        canvas.roundRect(ix, iy + 18, iw, sheet_h, 3, stroke=0, fill=1)
        img = ImageReader(BytesIO(image["png"]))
        aspect = image["width"] / max(1, image["height"])
        draw_h = sheet_h - 2 * pad
        draw_w = min(iw - 2 * pad, draw_h * aspect)
        draw_h = draw_w / aspect
        canvas.drawImage(
            img,
            ix + (iw - draw_w) / 2,
            iy + 18 + (sheet_h - draw_h) / 2,
            width=draw_w, height=draw_h,
            preserveAspectRatio=True, mask="auto",
        )
        _draw_string_fitted(
            canvas, ix, iy + 4,
            str(finding.get("summary") or finding.get("title") or "Approved profile match."),
            SANS, T_MICRO, iw - 52, TEXT_SECONDARY,
        )
        target = profile_page_numbers.get(chart_number)
        if target:
            canvas.setFillColor(accents[index % 2])
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawRightString(ix + iw, iy + 4, "OPEN >")
            canvas.linkRect("", f"sec_profile_{chart_number}", (ix + iw - 40, iy, ix + iw, iy + 12), relative=0, thickness=0)
    if not chart_images:
        inner = panel(canvas, MARGIN, profiles_top - profiles_h, full_w, profiles_h, title="APPROVED PROFILE SET", accent=EDTO_GREEN, title_colour=BG)
        if matched:
            review_line(canvas, inner[0], inner[1] + inner[3] / 2, "Matched profile charts could not be served from the controlled library - publication review required.")
        else:
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS_BOLD, T_SMALL)
            canvas.drawCentredString(MARGIN + full_w / 2, inner[1] + inner[3] / 2, "No approved profile match in the mounted controlled index.")

    # Unmatched exposures table. When a served chart already covers every
    # detected window, the zero-unresolved stat card is sufficient and the
    # redundant table gives its height back to the critical profile image.
    if table_h:
        table_y = 30.0 if chart_images else profiles_top - profiles_h - 10 - table_h
        table_top = table_y + table_h
        inner = panel(canvas, MARGIN, table_y, full_w, table_h, title="UNMATCHED EXPOSURES - NO PROFILE SUBSTITUTED", accent=CRITICAL)
        ix = inner[0]
        row_y = table_top - 26
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_SMALL)
        canvas.drawString(ix, row_y, "EVENT")
        canvas.drawString(ix + 150, row_y, "ACTM")
        canvas.drawString(ix + 260, row_y, "STATUS")
        row_y -= 11
        if unmatched:
            for finding in unmatched[:3]:
                data = finding.get("data") or {}
                start = data.get("start_actm_minutes")
                canvas.setFillColor(TEXT)
                canvas.setFont(SANS, T_SMALL)
                canvas.drawString(ix, row_y, str(finding.get("title") or "")[:34])
                canvas.setFont(MONO, T_SMALL)
                canvas.drawString(ix + 150, row_y, format_actm(start) if start is not None else "--")
                canvas.setFont(SANS, T_SMALL)
                _draw_string_fitted(canvas, ix + 260, row_y, str(finding.get("summary") or "Exact endpoint/airway profile unresolved."), SANS, T_SMALL, full_w - 290, TEXT_SECONDARY)
                row_y -= 14
        else:
            canvas.setFillColor(EDTO_GREEN)
            canvas.setFont(SANS_BOLD, T_SMALL)
            canvas.drawString(ix, row_y, "All detected windows covered by the approved profile set; no nearby or generic chart substituted.")


def draw_profile_page(
    canvas,
    flight: dict[str, Any],
    image: dict[str, Any],
    *,
    page_number: int,
    page_count: int,
) -> None:
    from io import BytesIO

    from reportlab.lib.utils import ImageReader

    width, height = PAGE_SIZE
    chart_number = image.get("chart_number") or "--"
    profile = image.get("profile") or {}
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line=f"A350 Depressurisation Profiles | Attachment {chart_number} | cropped authoritative chart; original content retained",
    )
    canvas.bookmarkPage(f"sec_profile_{chart_number}")
    y = draw_section_title(canvas, content_top, f"Depressurisation Profile {chart_number}")

    full_w = width - 2 * MARGIN
    footer_h = 26.0
    sheet_h = y - 30 - footer_h - 8
    canvas.setFillColor(colors.white)
    canvas.roundRect(MARGIN, 30 + footer_h + 8, full_w, sheet_h, 6, stroke=0, fill=1)
    img = ImageReader(BytesIO(image["png"]))
    aspect = image["width"] / max(1, image["height"])
    pad = 8
    draw_h = sheet_h - 2 * pad
    draw_w = min(full_w - 2 * pad, draw_h * aspect)
    draw_h = draw_w / aspect
    canvas.drawImage(
        img,
        MARGIN + (full_w - draw_w) / 2,
        30 + footer_h + 8 + (sheet_h - draw_h) / 2,
        width=draw_w, height=draw_h,
        preserveAspectRatio=True, mask="auto",
    )
    # Applicability footer + back link.
    canvas.setFillColor(ELEVATED)
    canvas.roundRect(MARGIN, 30, full_w, footer_h, 6, stroke=0, fill=1)
    canvas.setFillColor(EDTO_GREEN)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(MARGIN + 10, 30 + 9, "APPLICABILITY")
    applicability = str(profile.get("applicability") or profile.get("match_basis") or f"{theme.normalized_registration(flight.get('registration'))} effectivity confirmed.")
    _draw_string_fitted(canvas, MARGIN + 78, 30 + 9, applicability, SANS, T_SMALL, full_w - 200, TEXT_SECONDARY)
    back_w = pdfmetrics.stringWidth("BACK TO TERRAIN", SANS_BOLD, T_MICRO) + 24
    bx = MARGIN + full_w - back_w - 8
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1)
    canvas.setFillColor(BG)
    canvas.roundRect(bx, 30 + 5, back_w, 16, 8, stroke=1, fill=1)
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawCentredString(bx + back_w / 2, 30 + 10.4, "BACK TO TERRAIN")
    canvas.linkRect("", "sec_terrain", (bx, 30 + 5, bx + back_w, 30 + 21), relative=0, thickness=0)


# ---------------------------------------------------------------------------
# Source cropping — instruction 7: references show the cropped relevant
# section of the authoritative document, not a citation string alone.
# ---------------------------------------------------------------------------


def crop_source_region(
    source_pdf_path: str | None,
    *,
    needle: str,
    end_needle: str | None = None,
    page_hint: int = 0,
    pad_x: float = 26.0,
    pad_y: float = 16.0,
    max_pages: int = 6,
    dpi: int = 220,
    full_width: bool = False,
) -> dict[str, Any] | None:
    """Rasterise the region of the source PDF around the first hit for
    `needle`. Returns {png, width, height, page_number} or None. The crop is
    the printed original — never re-typeset."""
    if not source_pdf_path:
        return None
    import fitz

    try:
        with fitz.open(str(source_pdf_path)) as document:
            indexes = [page_hint] + [i for i in range(min(len(document), max_pages)) if i != page_hint]
            for index in indexes:
                if index >= len(document):
                    continue
                page = document[index]
                hits = page.search_for(needle)
                if not hits:
                    continue
                rect = hits[0]
                for extra in hits[1:]:
                    rect |= extra
                bottom = min(page.rect.y1, rect.y1 + pad_y * 5)
                if end_needle:
                    following_end_hits = [
                        hit for hit in page.search_for(end_needle)
                        if hit.y0 > rect.y1
                    ]
                    if following_end_hits:
                        # Stop immediately before the next printed section.
                        # This preserves every line in variable-length source
                        # blocks without pulling the route body into the crop.
                        bottom = min(
                            page.rect.y1,
                            max(
                                rect.y1 + pad_y,
                                min(hit.y0 for hit in following_end_hits) - 2,
                            ),
                        )
                if full_width:
                    # A monospace text block reads as a column; crop the whole
                    # printed column so lines are never cut mid-word.
                    clip = fitz.Rect(
                        page.rect.x0 + 24,
                        max(0, rect.y0 - pad_y),
                        page.rect.x1 - 24,
                        bottom,
                    )
                else:
                    clip = fitz.Rect(
                        max(0, rect.x0 - pad_x),
                        max(0, rect.y0 - pad_y),
                        min(page.rect.x1, rect.x1 + pad_x * 3.5),
                        bottom,
                    )
                pixmap = page.get_pixmap(clip=clip, dpi=dpi)
                return {
                    "png": pixmap.tobytes("png"),
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "page_number": index + 1,
                }
    except Exception:
        return None
    return None


_CROP_PAD = 5.0
_CROP_PANEL_MIN_HEIGHT = 72.0
_CROP_PANEL_CHROME_HEIGHT = 47.0


def _crop_image_dimensions(
    crop: dict[str, Any],
    width: float,
    height: float,
    *,
    dpi: int = 220,
) -> tuple[float, float]:
    """Return a crop's bounded display size without changing its scale rule."""
    aspect = crop["width"] / max(1, crop["height"])
    natural_w_pt = crop["width"] * 72.0 / dpi
    draw_h = max(1.0, height - 2 * _CROP_PAD)
    draw_w = min(
        max(1.0, width - 2 * _CROP_PAD),
        draw_h * aspect,
        natural_w_pt * 1.15,
    )
    return draw_w, draw_w / aspect


def _crop_panel_required_height(
    crop: dict[str, Any] | None,
    panel_width: float,
    max_height: float,
    *,
    dpi: int = 220,
) -> float:
    """Fit the source card to its evidence while retaining readable bounds.

    The 47-point chrome allowance is the existing panel title/insets plus the
    padding used by ``_draw_crop``.  Width and source-DPI determine the natural
    height; unusually tall evidence still uses all available space and scales
    down exactly as it did before.
    """
    bounded_max = max(1.0, max_height)
    if bounded_max <= _CROP_PANEL_MIN_HEIGHT:
        return bounded_max
    if not crop:
        return _CROP_PANEL_MIN_HEIGHT
    inner_width = max(1.0, panel_width - 16.0)
    natural_width = crop["width"] * 72.0 / dpi * 1.15
    draw_width = min(max(1.0, inner_width - 2 * _CROP_PAD), natural_width)
    aspect = crop["width"] / max(1, crop["height"])
    required = draw_width / aspect + _CROP_PANEL_CHROME_HEIGHT
    return min(bounded_max, max(_CROP_PANEL_MIN_HEIGHT, required))


def _draw_crop(canvas, crop: dict[str, Any] | None, x, y, w, h, *, missing_text: str, dpi: int = 220) -> None:
    from io import BytesIO

    from reportlab.lib.utils import ImageReader

    if not crop:
        review_line(canvas, x + 8, y + h / 2, missing_text)
        return
    # A crop is evidence: render at up to its printed size, never enlarged
    # into a poster.
    draw_w, draw_h = _crop_image_dimensions(crop, w, h, dpi=dpi)
    sheet_w = draw_w + 2 * _CROP_PAD
    sheet_h = draw_h + 2 * _CROP_PAD
    sheet_x = x + (w - sheet_w) / 2
    sheet_y = y + h - sheet_h
    canvas.setFillColor(colors.white)
    canvas.roundRect(sheet_x, sheet_y, sheet_w, sheet_h, 3, stroke=0, fill=1)
    canvas.drawImage(
        ImageReader(BytesIO(crop["png"])),
        sheet_x + _CROP_PAD, sheet_y + _CROP_PAD,
        width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto",
    )


# ---------------------------------------------------------------------------
# Page 4 — PERFORMANCE AND PLANNING SENSITIVITY.
# ---------------------------------------------------------------------------


def draw_performance_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP p.1 remarks and performance basis | deterministic RTOW and fuel arithmetic",
    )
    canvas.bookmarkPage("sec_performance")
    y = draw_section_title(canvas, content_top, "Performance and Planning Sensitivity")

    full_w = width - 2 * MARGIN
    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    fuel_summary = flight.get("fuel_summary") or {}
    ptow = masses.get("planned_takeoff_weight_kg")
    structural = performance.get("structural_rtow_kg")
    perf_rtow = performance.get("obstacle_rtow_kg")
    landing_rtow = performance.get("landing_rtow_kg")
    controlling = performance.get("controlling_rtow_kg")
    candidates = [v for v in (structural, perf_rtow, landing_rtow, controlling) if v]
    selected = min(candidates) if candidates else None
    margin_kg = selected - ptow if (selected and ptow) else None

    def kg_label(value):
        return f"{value:,} kg" if value else "--"

    card_w = (full_w - 4 * 10) / 5
    card_h = 44.0
    cards_y = y - card_h
    stat_card(canvas, MARGIN, cards_y, card_w, card_h, label="PTOW", value=kg_label(ptow), caption="planned mass", accent=DEPARTURE)
    stat_card(canvas, MARGIN + (card_w + 10), cards_y, card_w, card_h, label="SELECTED RTOW", value=kg_label(selected), caption="most limiting" if selected else "review required", accent=EDTO_GREEN if selected else WEATHER_AMBER)
    stat_card(canvas, MARGIN + 2 * (card_w + 10), cards_y, card_w, card_h, label="MARGIN", value=(f"+{margin_kg:,} kg" if margin_kg is not None and margin_kg >= 0 else f"{margin_kg:,} kg" if margin_kg is not None else "--"), caption="to selected RTOW", accent=EDTO_GREEN if (margin_kg or 0) >= 0 else CRITICAL)
    stat_card(canvas, MARGIN + 3 * (card_w + 10), cards_y, card_w, card_h, label="RTOW STRUCT", value=kg_label(structural), caption=(f"+{structural - ptow:,} kg" if structural and ptow else ""), accent=CRITICAL)
    stat_card(canvas, MARGIN + 4 * (card_w + 10), cards_y, card_w, card_h, label="RTOW PERF", value=kg_label(perf_rtow), caption=(f"+{perf_rtow - ptow:,} kg" if perf_rtow and ptow else ""), accent=DEPARTURE)

    # RTOW limit stack (left) + runway performance basis (right).
    body_top = cards_y - 10
    sens_h = 84.0
    body_h = body_top - 30 - sens_h - 10
    half_w = (full_w - 12) / 2
    inner = panel(canvas, MARGIN, body_top - body_h, half_w, body_h, title="RTOW LIMIT STACK - kg", accent=DEPARTURE)
    ix, iy, iw, ih = inner
    bars = [
        ("PTOW", ptow, DEPARTURE),
        ("SELECTED", selected, EDTO_GREEN),
        ("STRUCTURAL", structural, CRITICAL),
        ("PERFORMANCE", perf_rtow, COMMS_TEAL),
    ]
    plotted = [(label, value, accent) for label, value, accent in bars if value]
    if plotted:
        low = min(value for _, value, _ in plotted) * 0.96
        high = max(value for _, value, _ in plotted) * 1.02
        bar_h = min(16.0, (ih - 16) / len(plotted) - 6)
        bar_y = iy + ih - 24
        label_w = 62
        for label, value, accent in plotted:
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawRightString(ix + label_w - 6, bar_y + bar_h / 2 - 2, label)
            track_w = iw - label_w - 64
            canvas.setFillColor(PANEL)
            canvas.roundRect(ix + label_w, bar_y, track_w, bar_h, 2.5, stroke=0, fill=1)
            frac = (value - low) / max(1.0, high - low)
            canvas.setFillColor(accent)
            canvas.roundRect(ix + label_w, bar_y, max(6, track_w * frac), bar_h, 2.5, stroke=0, fill=1)
            canvas.setFillColor(TEXT)
            canvas.setFont(MONO_BOLD, 7.4)
            canvas.drawString(ix + label_w + track_w + 6, bar_y + bar_h / 2 - 2.6, f"{value:,}")
            bar_y -= bar_h + 8
    else:
        review_line(canvas, ix, iy + ih / 2, "No RTOW figures parsed from the CFP - performance review required.")

    right_x = MARGIN + half_w + 12
    inner = panel(canvas, right_x, body_top - body_h, half_w, body_h, title=f"{flight.get('departure') or '----'} RWY {performance.get('runway') or '--'} PERFORMANCE BASIS", accent=DEPARTURE)
    ix2 = inner[0]
    rows = [
        ("RUNWAY / CONDITION", f"{performance.get('runway') or '--'} / {performance.get('runway_condition') or '--'}"),
        ("THRUST / CONFIG", f"{performance.get('thrust_setting') or '--'} / {('FLAPS ' + str(performance.get('flap_setting'))) if performance.get('flap_setting') is not None else 'OPT CONF'}"),
        ("PACKS / ANTI-ICE", f"{'ON' if performance.get('packs_on') else '--'} / {'ON' if performance.get('anti_ice_on') else 'OFF' if performance.get('anti_ice_on') is False else '--'}"),
        ("PLAN TEMP / QNH", f"{performance.get('temperature_c') or '--'} C / {performance.get('qnh_hpa') or '--'} hPa"),
        ("PLAN WIND", str(performance.get("wind") or "--")),
        ("EOSID", str(performance.get("eosid") or "Not stated on the performance basis.")),
    ]
    row_y = body_top - 30
    for label, value in rows:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix2, row_y, label)
        _draw_string_fitted(canvas, ix2 + 120, row_y, value, MONO, T_SMALL, half_w - 150, TEXT)
        row_y -= (body_h - 34) / len(rows)

    # Sensitivities strip.
    inner = panel(canvas, MARGIN, 30, full_w, sens_h, title="FLIGHT-PLANNING SENSITIVITIES", accent=WEATHER_AMBER, title_colour=BG)
    ix3 = inner[0]
    zfw_burn = flight.get("zfw_change_burn_kg_per_1000")
    breakdown = fuel_summary.get("excess_breakdown") or []
    excess_parts = " + ".join(f"{item['label']} {item['fuel_kg']:,} kg" for item in breakdown if item.get("fuel_kg")) or None
    sens_rows = [
        ("ZFW +/-1,000 kg", f"BURN +/-{zfw_burn:,} kg" if zfw_burn else "Sensitivity line not printed on this CFP.", "Update burn and arrival fuel"),
        ("EXCESS ALLOCATION", excess_parts or "No itemised excess on CFP page 1.", "Purpose of carried excess fuel"),
        ("CRUISE BASIS", f"CI {flight.get('cost_index')}" if flight.get("cost_index") else str(flight.get("cruise") or "Cruise basis on CFP page 1."), "Level-change fuel sensitivity"),
    ]
    header_y = 30 + sens_h - 26
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix3, header_y, "VARIABLE")
    canvas.drawString(ix3 + 130, header_y, "CFP EFFECT")
    canvas.drawString(ix3 + 420, header_y, "DECISION USE")
    row_y = header_y - 13
    for variable, effect, use in sens_rows:
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix3, row_y, variable)
        _draw_string_fitted(canvas, ix3 + 130, row_y, effect, MONO, T_MICRO, 280, TEXT_SECONDARY)
        _draw_string_fitted(canvas, ix3 + 420, row_y, use, SANS, T_MICRO, full_w - 460, TEXT_MUTED)
        row_y -= 13


# ---------------------------------------------------------------------------
# Page 5 — MEL/CDL AND CDDL (instruction 6: never "TECH").
# ---------------------------------------------------------------------------


def draw_mel_cdl_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    source_pdf_path: str | None,
    deferred_items: list[dict[str, Any]] | None = None,
    section_page_number: int = 1,
    section_page_count: int = 1,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP page 1 declarations | exact governed MEL/CDL item links",
    )
    if section_page_number == 1:
        canvas.bookmarkPage("sec_mel_cdl")
    section_suffix = (
        f" ({section_page_number}/{section_page_count})"
        if section_page_count > 1
        else ""
    )
    y = draw_section_title(canvas, content_top, f"MEL/CDL and CDDL{section_suffix}")

    full_w = width - 2 * MARGIN
    deferred = (
        list(deferred_items)
        if deferred_items is not None
        else _group_deferred_items(flight)
    )
    half_w = (full_w - 12) / 2
    accents = (DEPARTURE, EDTO_GREEN, DESTINATION, COMMS_TEAL)
    cards = deferred if deferred else [None]
    if len(cards) > MEL_CDL_GROUPS_PER_PAGE:
        raise ValueError(
            "MEL/CDL page received more than its readable card capacity; "
            "paginate the grouped items before drawing."
        )
    row_count = 1 if len(cards) <= 2 else 2
    row_gap = 10.0
    card_h = 92.0 if row_count == 1 else 82.0
    cards_h = card_h * row_count + row_gap * (row_count - 1)
    for index, item in enumerate(cards):
        row = index // 2
        column = index % 2
        is_single_in_row = index == len(cards) - 1 and len(cards) % 2 == 1
        card_w = full_w if is_single_in_row else half_w
        cx = MARGIN if is_single_in_row else MARGIN + column * (half_w + 12)
        card_top = y - row * (card_h + row_gap)
        card_bottom = card_top - card_h
        if item is None:
            inner = panel(canvas, cx, card_bottom, full_w, card_h, title="DEFERRED ITEMS", accent=EDTO_GREEN, title_colour=BG)
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS_BOLD, T_SMALL)
            canvas.drawString(inner[0], card_top - card_h / 2 - 8, "No MEL, CDL or CDDL item is listed on CFP page 1.")
            break
        item_type = str(item.get("item_type") or "ITEM")
        reference = str(item.get("reference") or "")
        title = f"{item_type} {reference}".strip()
        inner = panel(canvas, cx, card_bottom, card_w, card_h, title=title, accent=accents[index % 4], title_colour=BG if accents[index % 4] in (EDTO_GREEN, COMMS_TEAL, WEATHER_AMBER) else colors.white)
        ix, iy, iw, ih = inner
        headline = str(item.get("description") or "").strip().upper() or "SEE CROPPED SOURCE BELOW"
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, 9.0)
        _draw_string_fitted(canvas, ix, card_top - 34, headline[:64], MONO_BOLD, 9.0, iw, TEXT)
        remark = str(item.get("company_remark") or "").strip()
        body = (
            f"CFP REMARK - NOT THE APPROVED {item_type} REMEDY: {remark}"
            if remark
            else (
                f"CFP declaration only. The approved {item_type} remedy must be read "
                "from the exact governed item."
            )
        )
        row_y = card_top - 48
        for line in _wrap(body, SANS, T_SMALL, iw)[:3]:
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_SMALL)
            canvas.drawString(ix, row_y, line)
            row_y -= 9.6
        penalty = str(item.get("penalty") or "").strip()
        source_target = governed_deferred_source_target(flight, item)
        source_label = f"OPEN EXACT {item_type} ITEM / REMEDY >" if source_target else ""
        source_width = (
            pdfmetrics.stringWidth(source_label, SANS_BOLD, T_MICRO)
            if source_label
            else 0
        )
        penalty_width = iw - source_width - (14 if source_label else 0)
        _draw_string_fitted(
            canvas,
            ix,
            iy + 4,
            penalty or "No take-off, enroute or fuel penalty stated in the mounted source.",
            SANS_BOLD,
            T_MICRO,
            max(40, penalty_width),
            EDTO_GREEN if not penalty else WEATHER_AMBER,
        )
        if source_target:
            source_x = ix + iw - source_width
            source_y = iy + 4
            canvas.setFillColor(ACCENT)
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawString(source_x, source_y, source_label)
            canvas.linkURL(
                source_target,
                (source_x - 2, source_y - 2, source_x + source_width + 2, source_y + T_MICRO + 2),
                relative=0,
                thickness=0,
            )

    # Cropped CFP declaration. It remains useful source evidence, but it is
    # never labelled as the approved MEL/CDL/CDDL remedy. The card keeps the
    # original evidence scale and only removes unused container height.
    crops_top = y - cards_h - 10
    max_crops_h = crops_top - 30
    crop = None
    if deferred:
        first_reference = str(deferred[0].get("reference") or "").strip()
        crop = (
            crop_source_region(
                source_pdf_path,
                needle="ATTN ALL CONCERN",
                end_needle="RTE NO",
                page_hint=0,
                pad_y=8,
                full_width=True,
            )
            or (crop_source_region(source_pdf_path, needle=first_reference, page_hint=0, pad_y=10, full_width=True) if first_reference and first_reference != "UNSPECIFIED" else None)
        )
    crops_h = _crop_panel_required_height(crop, full_w, max_crops_h)
    crops_bottom = crops_top - crops_h
    inner = panel(
        canvas,
        MARGIN,
        crops_bottom,
        full_w,
        crops_h,
        title="CROPPED CFP DECLARATION - NOT THE APPROVED REMEDY",
        accent=DESTINATION,
    )
    ix, iy, iw, ih = inner
    if deferred:
        _draw_crop(
            canvas, crop, ix, iy + 6, iw, ih - 10,
            missing_text="The deferred-item block could not be located for cropping - review CFP page 1 directly.",
        )
        if crop:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawRightString(ix + iw, iy - 1, f"Cropped from CFP page {crop['page_number']} - original content retained")
    else:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS_BOLD, T_SMALL)
        canvas.drawCentredString(ix + iw / 2, iy + ih / 2, "No deferred item on CFP page 1 - there is no source section to crop.")


# ---------------------------------------------------------------------------
# Page 6 — CLASSIFICATION AND DESTINATION ALTERNATES.
# ---------------------------------------------------------------------------


def draw_alternates_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    source_pdf_path: str | None,
) -> None:
    width, height = PAGE_SIZE
    classification = _edto_classification(flight)
    classification_label = classification or "EDTO REVIEW"
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line=f"CFP p.1 and alternate planning pages | {classification_label} classification and alternate planning",
    )
    canvas.bookmarkPage("sec_alternates")
    y = draw_section_title(canvas, content_top, f"{classification_label} and Destination Alternates")

    full_w = width - 2 * MARGIN
    half_w = (full_w - 12) / 2
    table_h = 92.0
    crops_h = y - 30 - table_h - 10

    # Left: the parsed entry/exit/alternate facts stay readable above the exact
    # airline EDTO source crop. This is the operational data the earlier report
    # lost even after the parser had successfully extracted it.
    inner = panel(canvas, MARGIN, y - crops_h, half_w, crops_h, title=f"{classification_label} SOURCE / STATUS", accent=EDTO_GREEN, title_colour=BG)
    ix, iy, iw, ih = inner
    edto_rows = _edto_operational_rows(
        classification,
        briefing.get("edto") or {},
        flight.get("fuel_summary") or {},
    )
    summary_rows = edto_rows[:-1]
    summary_h = min(150.0, 18.0 + len(summary_rows) * 12.0)
    source_classification = _edto_source_classification(flight)
    crop = crop_source_region(
        source_pdf_path,
        needle="EDTO INFORMATION",
        page_hint=0,
        pad_y=18,
        max_pages=30,
        full_width=True,
    ) or crop_source_region(
        source_pdf_path,
        needle=(
            f"SUMMARY {source_classification} CFP"
            if source_classification
            else "SUMMARY EDTO CFP"
        ),
        page_hint=0,
        pad_y=8,
        max_pages=6,
        full_width=True,
    )
    _draw_crop(
        canvas, crop, ix, iy + summary_h + 4, iw, ih - summary_h - 6,
        missing_text="EDTO source section unavailable for cropping - review the uploaded CFP.",
    )
    row_y = iy + summary_h - 10
    for label, value in summary_rows:
        canvas.setFillColor(EDTO_GREEN if label == "CLASSIFICATION" else TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, label)
        _draw_string_fitted(
            canvas, ix + 78, row_y, value, SANS, T_SMALL,
            iw - 82, TEXT,
        )
        row_y -= 12

    inner = panel(canvas, MARGIN + half_w + 12, y - crops_h, half_w, crops_h, title="ALTERNATE PLANNING SOURCE", accent=DESTINATION)
    ix2, iy2, iw2, ih2 = inner
    crop2 = crop_source_region(source_pdf_path, needle="FLT PLANNING ALTN SUMMARY", page_hint=0, full_width=True) or crop_source_region(source_pdf_path, needle="ALTN/RWY", page_hint=0, full_width=True)
    _draw_crop(canvas, crop2, ix2, iy2 + 6, iw2, ih2 - 10, missing_text="Alternate planning section not found for cropping - review the CFP weather pages.")

    # Alternates table.
    inner = panel(canvas, MARGIN, 30, full_w, table_h, title="ALTERNATES AND PLANNING BASIS", accent=WEATHER_AMBER, title_colour=BG)
    ix3 = inner[0]
    header_y = 30 + table_h - 26
    for label, off in (("APT/RWY", 0), ("APPROACH", 90), ("MINIMA", 200), ("DIST", 330), ("TIME / FUEL", 390), ("ROUTE BASIS", 500)):
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix3 + off, header_y, label)
    row_y = header_y - 12
    alternates = flight.get("alternates") or []
    if not alternates:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        canvas.drawString(ix3, row_y, "No alternate table parsed from this CFP - planning review required.")
    for item in alternates[:4]:
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(ix3, row_y, f"{item.get('airport') or '----'}/{item.get('runway') or '--'}")
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix3 + 90, row_y, str(item.get("approach") or "--")[:16])
        canvas.setFont(MONO, T_MICRO)
        canvas.drawString(ix3 + 200, row_y, str(item.get("minima") or "--")[:18])
        canvas.drawString(ix3 + 330, row_y, f"{item.get('distance_nm') or '--'}")
        time_min = item.get("time_minutes")
        canvas.drawString(ix3 + 390, row_y, f"{format_actm(time_min) if time_min is not None else '--'} / {item.get('fuel_kg'):,} kg" if item.get("fuel_kg") else "--")
        _draw_string_fitted(canvas, ix3 + 500, row_y, str(item.get("route") or "Route basis on CFP alternate pages."), SANS, T_MICRO, full_w - 540, TEXT_MUTED)
        row_y -= 12


# ---------------------------------------------------------------------------
# Page 7 — AIRPORT AND NOTAM APPLICABILITY.
# ---------------------------------------------------------------------------


def _notam_rows(panel_data: dict[str, Any], flight: dict[str, Any], role: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    runway = str(panel_data.get("runway") or "")
    if runway:
        rows.append((f"RWY {runway.split('/')[0].strip()[:8]}", "PLANNED", "Planned CFP basis."))
    for consideration in (panel_data.get("considerations") or [])[:5]:
        kind = str(consideration.get("kind") or "NOTAM")
        text = str(consideration.get("text") or "")
        severity = str(consideration.get("severity") or "information")
        condition = {"critical": "CRITICAL", "warning": "ACTIVE", "information": "REVIEWED"}.get(severity, severity.upper())
        rows.append((kind[:22], condition, text))
    if len(rows) == 1:
        rows.append(("NOTAM", "NONE PROMOTED", "No restriction intersecting the flight window was promoted."))
    return rows[:6]


def _airport_table_required_height(
    rows: list[tuple[str, str, str]],
    width: float,
) -> float:
    """Keep an airport table only as tall as its bounded six-row content."""
    effect_width = max(36.0, width - 230.0)
    row_height = 0.0
    for _, _, effect in rows:
        lines = (_wrap(effect, SANS, T_MICRO, effect_width) or [""])[:2]
        # The table reserves two cockpit-readable lines per row so its columns
        # stay aligned even when one airport has shorter wording.
        row_height += max(2, len(lines)) * 9.4 + 3.4
    return max(120.0, 59.0 + row_height)


def draw_airports_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP NOTAM bulletin within the operating window | promoted restrictions only",
    )
    canvas.bookmarkPage("sec_airports")
    y = draw_section_title(canvas, content_top, "Airport and NOTAM Applicability")

    full_w = width - 2 * MARGIN
    half_w = (full_w - 12) / 2
    rule_h = 24.0
    airport_tables = [
        (role, panel_data, accent, _notam_rows(panel_data, flight, role))
        for role, panel_data, accent in (
            ("DEPARTURE", briefing.get("departure") or {}, DEPARTURE),
            ("DESTINATION", briefing.get("destination") or {}, DESTINATION),
        )
    ]
    table_h = min(
        y - 30 - rule_h - 10,
        max(_airport_table_required_height(rows, half_w) for _, _, _, rows in airport_tables),
    )
    table_y = y - table_h

    for index, (role, panel_data, accent, rows) in enumerate(airport_tables):
        px = MARGIN + index * (half_w + 12)
        icao = panel_data.get("icao") or (flight.get("departure") if index == 0 else flight.get("destination")) or "----"
        inner = panel(
            canvas, px, table_y, half_w, table_h,
            title=f"{theme.airport_code_label(icao)} - {role}", accent=accent,
        )
        ix, iy, iw, ih = inner
        header_y = y - 28
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, header_y, "ITEM")
        canvas.drawString(ix + 118, header_y, "CONDITION")
        canvas.drawString(ix + 210, header_y, "OPERATIONAL EFFECT")
        row_y = header_y - 13
        for item, condition, effect in rows:
            canvas.setFillColor(TEXT)
            canvas.setFont(SANS_BOLD, T_MICRO)
            _draw_string_fitted(canvas, ix, row_y, item, SANS_BOLD, T_MICRO, 112, TEXT)
            canvas.setFont(MONO, T_MICRO)
            _draw_string_fitted(canvas, ix + 118, row_y, condition, MONO, T_MICRO, 86, TEXT_SECONDARY)
            lines = _wrap(effect, SANS, T_MICRO, iw - 214)
            for line in lines[:2]:
                canvas.setFillColor(TEXT_SECONDARY)
                canvas.setFont(SANS, T_MICRO)
                canvas.drawString(ix + 210, row_y, line)
                row_y -= 9.4
            if len(lines) < 2:
                row_y -= 9.4
            row_y -= 3.4
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix, iy + 2, "BOUNDARY: assigned runway/stand, clearance and current charting remain controlling.")

    # Applicability rule bar.
    rule_y = table_y - rule_h - 10
    canvas.setFillColor(ELEVATED)
    canvas.roundRect(MARGIN, rule_y, full_w, rule_h, 6, stroke=0, fill=1)
    canvas.setFillColor(ACCENT)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(MARGIN + 10, rule_y + 9, "APPLICABILITY RULE")
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, T_SMALL)
    canvas.drawString(MARGIN + 110, rule_y + 9, "Promote only restrictions intersecting the flight window, planned procedure, assigned stand or cleared taxi route.")


# ---------------------------------------------------------------------------
# Page 8 — OPERATIONAL HAZARD ASSESSMENT.
# ---------------------------------------------------------------------------


def draw_hazard_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    weather_charts: dict[str, Any] | None,
    *,
    page_number: int,
    page_count: int,
    source_pdf_path: str | None,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP weather snapshot | held SIGMET/VAA reviews | package WAFC fixed-time charts",
    )
    canvas.bookmarkPage("sec_hazard")
    y = draw_section_title(canvas, content_top, "Operational Hazard Assessment")

    full_w = width - 2 * MARGIN
    half_w = (full_w - 12) / 2
    # The manifest names every VAAC centre as well as the aggregate receipt.
    # Reserve three compact centre rows so unavailable coverage cannot vanish
    # behind a truthful-but-opaque "2/9 reached" count.
    top_h = 128.0

    hazard = next(
        (f for f in findings if f.get("engine") in {"sigmet", "vaa", "tropical_cyclone"}),
        None,
    ) or next((f for f in findings if f.get("engine") == "weather"), None)
    inner = panel(canvas, MARGIN, y - top_h, half_w, top_h, title=(str(hazard.get("title"))[:44].upper() if hazard else "ENROUTE HAZARD REVIEW"), accent=WEATHER_AMBER, title_colour=BG)
    ix, iy, iw, ih = inner
    if hazard:
        rows = [("FINDING", str(hazard.get("summary") or ""))]
        for line in (hazard.get("details") or [])[:3]:
            rows.append(("DETAIL", str(line)))
        row_y = y - 30
        for label, value in rows:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawString(ix, row_y, label)
            lines = _wrap(value, SANS, T_MICRO, iw - 64)
            for line in lines[:2]:
                canvas.setFillColor(TEXT_SECONDARY)
                canvas.setFont(SANS, T_MICRO)
                canvas.drawString(ix + 58, row_y, line)
                row_y -= 9.2
            if len(lines) < 2:
                row_y -= 9.2
            row_y -= 3
    else:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS_BOLD, T_SMALL)
        canvas.drawString(ix, y - top_h / 2 - 10, "No enroute hazard finding was promoted for this package.")

    # Coverage manifest from the governed reviews.
    inner = panel(canvas, MARGIN + half_w + 12, y - top_h, half_w, top_h, title="COVERAGE MANIFEST", accent=CRITICAL)
    ix2 = inner[0]
    row_y = y - 30
    vaa_review = flight.get("vaa_review") or {}
    vaac_ledger = vaa_review.get("vaac_centre_ledger") or []
    vaac_total = len(vaac_ledger) or 9
    vaac_reached = sum(
        1 for item in vaac_ledger
        if item.get("status") in {"available", "partial"}
    )
    vaac_partial = sum(1 for item in vaac_ledger if item.get("status") == "partial")
    vaac_receipt = f"{vaac_reached}/{vaac_total} reached"
    if vaac_partial:
        vaac_receipt += f" | {vaac_partial} partial"
    entries = (
        ("SIGMET", str(((flight.get("sigmet_review") or {}).get("status")) or "no data in CFP")),
        ("VA SIGMET", str(vaa_review.get("status") or "no data in CFP")),
        ("VAAC CENTRES", vaac_receipt),
        ("TROPICAL CYCLONE", str(((flight.get("tropical_cyclone_review") or {}).get("status")) or "no data in CFP")),
    )
    for label, status in entries:
        ok = status.lower() in {"ok", "complete", "reviewed", "verified", "9/9 reached"}
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix2, row_y, label)
        canvas.setFillColor(EDTO_GREEN if ok else WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        _draw_string_fitted(canvas, ix2 + 96, row_y, status.replace("_", " "), SANS_BOLD, T_MICRO, half_w - 130, EDTO_GREEN if ok else WEATHER_AMBER)
        row_y -= 12
    status_copy = {
        "available": "reached",
        "partial": "partial",
        "unavailable": "unavailable",
        "not_mounted": "not mounted",
    }
    for start in range(0, len(vaac_ledger), 3):
        centre_line = " | ".join(
            f"{str(item.get('centre') or 'UNKNOWN').upper()}: "
            f"{status_copy.get(str(item.get('status') or '').lower(), 'unavailable')}"
            for item in vaac_ledger[start:start + 3]
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        _draw_string_fitted(
            canvas, ix2, row_y, centre_line,
            MONO, T_MICRO, half_w - 34, TEXT_SECONDARY,
        )
        row_y -= 10
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    _draw_string_fitted(
        canvas, ix2, row_y,
        "Absent data is reported, never assumed clear - current SIGMET/radar remain controlling.",
        SANS, T_MICRO, half_w - 34, TEXT_MUTED,
    )

    # WAFC fixed-time products strip.
    strip_top = y - top_h - 10
    strip_h = strip_top - 30
    inner = panel(canvas, MARGIN, 30, full_w, strip_h, title="PACKAGE WAFC FIXED-TIME PRODUCTS", accent=WEATHER_AMBER, title_colour=BG)
    ix3, iy3, iw3, ih3 = inner
    charts = ((weather_charts or {}).get("charts") or [])[:3]
    if charts and source_pdf_path:
        from io import BytesIO

        from reportlab.lib.utils import ImageReader

        from .weather_charts import extract_chart_image

        tile_w = (iw3 - 2 * 10) / 3
        tile_h = ih3 - 22
        for index, chart in enumerate(charts):
            tx = ix3 + index * (tile_w + 10)
            try:
                raw = extract_chart_image(source_pdf_path, int(chart.get("page_number")))
            except Exception:
                raw = None
            if raw:
                image = ImageReader(BytesIO(raw))
                canvas.setFillColor(colors.white)
                canvas.roundRect(tx, iy3 + 16, tile_w, tile_h, 3, stroke=0, fill=1)
                canvas.drawImage(image, tx + 3, iy3 + 19, width=tile_w - 6, height=tile_h - 6, preserveAspectRatio=True, mask="auto")
            label = str(chart.get("kind") or "chart").replace("_", " ").upper()
            valid = str(chart.get("valid_time") or chart.get("issued_time") or "")
            canvas.setFillColor(WEATHER_AMBER)
            canvas.setFont(MONO_BOLD, T_MICRO)
            canvas.drawCentredString(tx + tile_w / 2, iy3 + 6, f"{valid} {label}"[:44].strip())
    else:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS_BOLD, T_SMALL)
        canvas.drawCentredString(MARGIN + full_w / 2, 30 + strip_h / 2, "No classified WAFC chart appendix held for this package.")


# ---------------------------------------------------------------------------
# Page 9 — FIR COMMUNICATION AND TIME RECONCILIATION.
# ---------------------------------------------------------------------------


def draw_comms_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP route log and early-call requirements | timings remain subject to current AIP/NOTAM and ATC",
    )
    canvas.bookmarkPage("sec_comms")
    y = draw_section_title(canvas, content_top, "FIR Communication and Time Reconciliation")

    full_w = width - 2 * MARGIN
    comms = briefing.get("communications") or []

    # Stat cards from the first calls.
    card_h = 40.0
    if comms:
        card_w = (full_w - (len(comms[:5]) - 1) * 10) / max(1, len(comms[:5]))
        accents = (COMMS_TEAL, EDTO_GREEN, DESTINATION, WEATHER_AMBER, DEPARTURE)
        for index, item in enumerate(comms[:5]):
            stat_card(
                canvas, MARGIN + index * (card_w + 10), y - card_h, card_w, card_h,
                label=str(item.get("event") or "CALL")[:20],
                value=str(item.get("time") or "--").split(" ")[-1],
                caption=str(item.get("actm") and f"ACTM {item.get('actm')}" or ""),
                accent=accents[index % 5],
            )
    seq_top = y - card_h - 10
    right_w = 190.0
    seq_w = full_w - right_w - 12
    seq_h = seq_top - 30
    inner = panel(canvas, MARGIN, 30, seq_w, seq_h, title="COMMUNICATION SEQUENCE", accent=COMMS_TEAL, title_colour=BG)
    ix, iy, iw, ih = inner
    header_y = seq_top - 26
    for label, off in (("UTC / ACTM", 0), ("EVENT", 110), ("RULE / DETAIL", 260)):
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix + off, header_y, label)
    row_y = header_y - 13
    if not comms:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        canvas.drawString(ix, row_y, "No early FIR contact requirement was derived from this CFP.")
    for item in comms[:6]:
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, f"{str(item.get('time') or '--').split(' ')[-1]} / {item.get('actm') or '--'}")
        canvas.setFont(SANS_BOLD, T_MICRO)
        _draw_string_fitted(canvas, ix + 110, row_y, str(item.get("event") or ""), SANS_BOLD, T_MICRO, 144, TEXT)
        _draw_string_fitted(canvas, ix + 260, row_y, str(item.get("detail") or ""), SANS, T_MICRO, iw - 270, TEXT_SECONDARY)
        row_y -= 14

    inner = panel(canvas, MARGIN + seq_w + 12, 30, right_w, seq_h, title="DIRECTION / STATUS", accent=CRITICAL)
    ix2 = inner[0]
    row_y = seq_top - 28
    cruise = str(flight.get("cruise") or "").strip()
    bobcat = flight.get("bobcat")
    rows = [
        ("ROUTE / LEVEL", cruise or "Cruise basis on CFP page 1."),
        ("BOBCAT", (
            f"WPT {bobcat.get('waypoint')} FL{bobcat.get('flight_level')}" if bobcat else "No Page 1 allocation; all UTC derived from the take-off anchor."
        )),
        ("SOURCE LIMIT", "Frequencies and timings remain subject to current AIP/NOTAM and ATC."),
    ]
    for label, value in rows:
        canvas.setFillColor(CRITICAL if label == "BOBCAT" and bobcat else TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix2, row_y, label)
        row_y -= 10
        for line in _wrap(value, SANS, T_MICRO, right_w - 20)[:3]:
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawString(ix2, row_y, line)
            row_y -= 9.2
        row_y -= 5


# ---------------------------------------------------------------------------
# Render entry.
# ---------------------------------------------------------------------------


def render_combined_briefing(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    path,
    *,
    source_pdf_path: str | None = None,
    weather_charts: dict[str, Any] | None = None,
) -> None:
    """Render the one-PDF Flight Briefing to `path`.

    The depressurisation publication gate runs exactly as it does for the
    legacy pair: an approved profile whose chart cannot be published fails the
    render, never degrades it.
    """
    from pathlib import Path

    from reportlab.pdfgen import canvas as pdf_canvas

    from .briefing import build_briefing_view
    from .depress_matrix_page import load_matched_chart_images
    from .profile_chart_gate import (
        DepressurisationProfileChartPublicationError,
        validate_depressurisation_profile_charts,
    )

    register_fonts()
    violations = validate_depressurisation_profile_charts(flight, findings, 2)
    if violations:
        raise DepressurisationProfileChartPublicationError(violations)
    chart_images = load_matched_chart_images(findings)
    briefing = build_briefing_view(flight, findings, warnings)

    deferred_groups = _group_deferred_items(flight)
    deferred_pages = [
        deferred_groups[index:index + MEL_CDL_GROUPS_PER_PAGE]
        for index in range(0, len(deferred_groups), MEL_CDL_GROUPS_PER_PAGE)
    ] or [[]]
    mel_page_count = len(deferred_pages)
    page_count = 8 + mel_page_count + len(chart_images)
    profile_page_numbers = {
        str(image.get("chart_number")): 9 + mel_page_count + index
        for index, image in enumerate(chart_images)
    }

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(str(output_path), pagesize=PAGE_SIZE)
    canvas.setTitle(f"Flight Briefing {theme.display_flight_number(flight)} {theme.header_date_label(flight)}")

    draw_overview_page(canvas, flight, briefing, findings, page_number=1, page_count=page_count)
    canvas.showPage()
    draw_time_gates_page(canvas, flight, briefing, findings, page_number=2, page_count=page_count)
    canvas.showPage()
    draw_terrain_page(
        canvas, flight, briefing, findings, chart_images,
        page_number=3, page_count=page_count, profile_page_numbers=profile_page_numbers,
    )
    canvas.showPage()
    draw_performance_page(canvas, flight, briefing, findings, page_number=4, page_count=page_count)
    canvas.showPage()
    for index, deferred_page in enumerate(deferred_pages):
        draw_mel_cdl_page(
            canvas, flight, briefing, findings,
            page_number=5 + index,
            page_count=page_count,
            source_pdf_path=source_pdf_path,
            deferred_items=deferred_page,
            section_page_number=index + 1,
            section_page_count=mel_page_count,
        )
        canvas.showPage()
    alternates_page_number = 5 + mel_page_count
    draw_alternates_page(
        canvas, flight, briefing, findings,
        page_number=alternates_page_number,
        page_count=page_count,
        source_pdf_path=source_pdf_path,
    )
    canvas.showPage()
    draw_airports_page(
        canvas,
        flight,
        briefing,
        findings,
        page_number=alternates_page_number + 1,
        page_count=page_count,
    )
    canvas.showPage()
    draw_hazard_page(
        canvas, flight, briefing, findings, weather_charts,
        page_number=alternates_page_number + 2,
        page_count=page_count,
        source_pdf_path=source_pdf_path,
    )
    canvas.showPage()
    draw_comms_page(
        canvas,
        flight,
        briefing,
        findings,
        page_number=alternates_page_number + 3,
        page_count=page_count,
    )
    canvas.showPage()
    for index, image in enumerate(chart_images):
        draw_profile_page(
            canvas, flight, image,
            page_number=alternates_page_number + 4 + index,
            page_count=page_count,
        )
        canvas.showPage()
    canvas.save()
    from .report_quality import assert_combined_briefing_quality

    assert_combined_briefing_quality(output_path)


def combined_briefing_filename(flight_number: Any, flight_date: Any) -> str:
    """`<FLIGHT>_<DDMMMYYYY>_Flight_Briefing.pdf` — the boss's naming
    instruction ('label the file as SQ366, date and Flight Briefing'), also
    codified in publication protocol v1.3. Lido prints compact dates
    (07AUG26); expand the century rather than echo it."""
    flight = re.sub(r"[^A-Z0-9]", "", str(flight_number or "").upper()) or "FLIGHT"
    raw_date = str(flight_date or "").strip().upper()
    match = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2}|\d{4})", raw_date)
    if match:
        day, month, year = match.groups()
        date_part = f"{day}{month}{year if len(year) == 4 else '20' + year}"
        return f"{flight}_{date_part}_Flight_Briefing.pdf"
    return f"{flight}_Flight_Briefing.pdf"
