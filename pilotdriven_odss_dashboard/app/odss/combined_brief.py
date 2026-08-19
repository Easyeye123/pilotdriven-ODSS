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
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import brief_theme as theme
from .brief_theme import register_fonts
from .briefing import (
    _edto_classification,
    _edto_gate_sentence,
    _edto_operational_rows,
)
from .constants import format_actm

PAGE_SIZE = landscape(A4)

# ---------------------------------------------------------------------------
# Faces — measured off the boss's REV3 file (20 Aug, "this look").  His
# analysis pages set every title and body line in base-14 Helvetica with
# Courier utility lines (header schedule, footer) — those are font objects,
# not files, so using the same names reproduces his glyphs exactly.  His
# dashboard prints data values in DejaVu Sans Mono; the cut is vendored
# beside the other faces.  Inter/JetBrains are retired from this surface by
# that same file.
# ---------------------------------------------------------------------------
SANS = "Helvetica"
SANS_BOLD = "Helvetica-Bold"
UTIL_MONO = "Courier"
UTIL_MONO_BOLD = "Courier-Bold"

_FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _data_mono_faces() -> tuple[str, str]:
    regular = _FONT_DIR / "DejaVuSansMono.ttf"
    bold = _FONT_DIR / "DejaVuSansMono-Bold.ttf"
    if regular.is_file() and bold.is_file():
        if "BriefDataMono" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("BriefDataMono", str(regular)))
            pdfmetrics.registerFont(TTFont("BriefDataMono-Bold", str(bold)))
        return "BriefDataMono", "BriefDataMono-Bold"
    return UTIL_MONO, UTIL_MONO_BOLD  # pragma: no cover - fonts are vendored


MONO, MONO_BOLD = _data_mono_faces()

# ---------------------------------------------------------------------------
# Palette — REV3 analysis-page vector fills, measured (his page 1 re-renders
# our dashboard with the web tokens; pages 2-7 are his own design and carry
# these values, so they govern the document).
# ---------------------------------------------------------------------------
BG = colors.HexColor("#07131f")
PANEL = colors.HexColor("#0f2336")
ELEVATED = colors.HexColor("#142e45")
BORDER = colors.HexColor("#26445b")
ACCENT = colors.HexColor("#2f80ed")
SECTION_BLUE = colors.HexColor("#35a6dc")
DEPARTURE = colors.HexColor("#34a5db")
DESTINATION = colors.HexColor("#974fe6")
EDTO_GREEN = colors.HexColor("#2dcf82")
WEATHER_AMBER = colors.HexColor("#f2c84b")
COMMS_TEAL = colors.HexColor("#2dcecf")
TERRAIN_ORANGE = colors.HexColor("#f29a49")
CRITICAL = colors.HexColor("#eb5757")
TEXT = colors.HexColor("#f3f7fa")
TEXT_SECONDARY = colors.HexColor("#9ab0c1")
TEXT_MUTED = colors.HexColor("#6f8095")

MARGIN = 20.0
HEADER_H = 64.0
FOOTER_H = 26.0

# Type scale: the old brief sizes +20% per instruction 3 ("especially for
# detailed content words and numerics"), raised again per the 18 Aug 1:31
# instruction ("make the font sizes larger") - content and numerics only,
# headings unchanged. The geometric overlap scan gates every page at the
# larger sizes across the whole corpus.
T_TITLE = 19.0        # page section title
T_FLIGHT = 27.0       # header flight number (REV3 measured: Helvetica-Bold 27)
T_CARD_HEAD = 9.3     # panel titles (REV3 measured)
T_BODY = 9.8
T_VALUE = 13.2        # stat values
T_SMALL = 8.6
T_MICRO = 7.6

# Keep MEL/CDL cards at the cockpit-readable type scale.  More governing
# references create continuation pages instead of being dropped or squeezed.
MEL_CDL_GROUPS_PER_PAGE = 4

# Part of the cached-report identity. Bump whenever the publication contract
# changes so an analysis created before a deployment cannot keep serving an
# older PDF from persistent report storage.
COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-20-rev3-measured-skin-v4"


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


REV3_TABS = (
    ("DASHBOARD", "sec_overview"),
    ("PERF / FUEL", "sec_analysis"),
    ("TECH STATUS", "sec_mel_cdl"),
    ("EDTO", "sec_alternates"),
    ("AIRPORTS", "sec_airports"),
    ("WEATHER", "sec_hazard"),
    ("TERRAIN", "sec_terrain"),
)


def rev3_card(canvas, x, y, w, h, *, title: str, accent, title_colour=None) -> tuple[float, float, float, float]:
    """REV3 canon card, measured: #0F2336 rounded panel with a 0.8pt #26445B
    border, a square 3pt accent TOP bar, and a white 9.3 bold title 10pt in
    from the left edge."""
    canvas.setFillColor(PANEL)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    canvas.setFillColor(accent)
    canvas.rect(x, y + h - 3, w, 3, stroke=0, fill=1)
    canvas.setFillColor(title_colour or TEXT)
    canvas.setFont(SANS_BOLD, T_CARD_HEAD)
    canvas.drawString(x + 10, y + h - 16.3, str(title)[:64])
    return (x + 10, y + 10, w - 20, h - 30)


def draw_page_chrome(
    canvas,
    flight: dict[str, Any],
    *,
    page_number: int,
    page_count: int,
    source_line: str,
    section_label: str | None = None,
    section_colour=None,
    show_tabs: bool = False,
) -> float:
    """Background, header band, footer, SOURCE line. Returns content top y."""
    register_fonts()
    width, height = PAGE_SIZE
    canvas.setFillColor(BG)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    top = height - 16
    flight_number = theme.display_flight_number(flight)
    utc_line, local_line = _header_times(flight)
    block_label = theme.block_time_label(flight)
    if page_number == 1:
        draw_logo(canvas, MARGIN, top - 26, height=13.0)
        # REV3 page 1 header - geometry measured from the boss's REV3 file
        # (20 Aug): mono flight number at x137, route at x223, date block at
        # x370, aircraft block at x548; the captain moves to FLIGHT BASIS.
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, 20)
        canvas.drawString(137, top - 15, flight_number)
        canvas.setFont(SANS_BOLD, 12.5)
        canvas.drawString(
            223,
            top - 12,
            f"{str(flight.get('departure') or '----').upper()}  ->  "
            f"{str(flight.get('destination') or '----').upper()}",
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 6.6)
        canvas.drawString(
            223,
            top - 24,
            f"{flight.get('aircraft_type') or ''} | "
            f"{theme.normalized_registration(flight.get('registration'))}",
        )
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 8.6)
        canvas.drawString(370, top - 13, theme.header_date_label(flight))
        # REV3 page 1: one compact mono schedule line.
        etd_eta = utc_line.replace("UTC DEP", "ETD").replace("-> ARR", "|  ETA")
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, 6.5)
        canvas.drawString(370, top - 25, f"{etd_eta}  |  {block_label or ''}".strip(" |"))
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, 5.8)
        canvas.drawString(548, top - 11, "AIRCRAFT / REG")
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, 7.4)
        canvas.drawString(548, top - 22, f"{flight.get('aircraft_type') or '--'} / {theme.normalized_registration(flight.get('registration')) or '--'}")
        meta_bits = " | ".join(part for part in (
            f"CI{flight.get('cost_index')}" if flight.get("cost_index") is not None else None,
            str(flight.get("captain") or "") or None,
        ) if part)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, 5.8)
        canvas.drawString(548, top - 33, meta_bits)
    else:
        # REV3 analysis-page header, every coordinate measured off his file:
        # stacked identity block at x178 (number 27 / route 14 / aircraft
        # 8.5), schedule column at x454 (date 10 / UTC 8.5 / LT 7.9 in
        # Courier), BLK at x690, section label and page number right-aligned.
        draw_logo(canvas, MARGIN, height - 52, height=11.0)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_FLIGHT)
        canvas.drawString(178, height - 33, flight_number)
        canvas.setFont(SANS_BOLD, 14)
        canvas.drawString(
            178,
            height - 55.3,
            f"{str(flight.get('departure') or '----').upper()} -> "
            f"{str(flight.get('destination') or '----').upper()}",
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 8.5)
        canvas.drawString(
            178,
            height - 72.3,
            f"{flight.get('aircraft_type') or ''} | "
            f"{theme.normalized_registration(flight.get('registration'))}",
        )
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 10)
        canvas.drawString(454, height - 37.8, theme.header_date_label(flight))
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(UTIL_MONO, 8.5)
        canvas.drawString(454, height - 58.5, utc_line)
        canvas.setFont(UTIL_MONO, 7.9)
        canvas.drawString(454, height - 73.5, local_line)
        if block_label:
            canvas.setFillColor(TEXT)
            canvas.setFont(SANS_BOLD, 10)
            canvas.drawString(690, height - 37.8, block_label)
    if page_number == 1:
        pill_text = "SOURCE CHECKS OPEN"
        pill_sub = "Current products controlling"
        pill_w = max(
            pdfmetrics.stringWidth(pill_text, SANS_BOLD, 7.4),
            pdfmetrics.stringWidth(pill_sub, SANS, 6.4),
        ) + 30
        pill_x = width - MARGIN - pill_w
        canvas.setStrokeColor(WEATHER_AMBER)
        canvas.setLineWidth(1.1)
        canvas.setFillColor(BG)
        canvas.roundRect(pill_x, top - 30, pill_w, 24, 12, stroke=1, fill=1)
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, 7.4)
        canvas.drawCentredString(pill_x + pill_w / 2, top - 15.5, pill_text)
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, 6.4)
        canvas.drawCentredString(pill_x + pill_w / 2, top - 24.5, pill_sub)
    else:
        label = section_label or "FLIGHT BRIEFING"
        canvas.setFillColor(section_colour or SECTION_BLUE)
        canvas.setFont(SANS_BOLD, 9.3)
        canvas.drawRightString(width - MARGIN, height - 57.9, label.upper())
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 7.4)
        canvas.drawRightString(width - MARGIN, height - 74.5, f"Page {page_number} of {page_count}")
        # Boss, 19 Aug video: "back to overview must be on top, nice and
        # big". REV3's header leaves the band between the schedule column
        # and BLK empty, so the pill lives there - on top, inside the
        # measured header, without pushing content below his content line.
        back_text = "BACK TO OVERVIEW"
        back_w = pdfmetrics.stringWidth(back_text, SANS_BOLD, T_SMALL) + 28
        back_x = 680 - back_w
        back_y = height - 50
        canvas.setFillColor(ELEVATED)
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.1)
        canvas.roundRect(back_x, back_y, back_w, 22, 11, stroke=1, fill=1)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_SMALL)
        canvas.drawCentredString(back_x + back_w / 2, back_y + 7.5, back_text)
        canvas.linkRect(
            "",
            "sec_overview",
            (back_x, back_y, back_x + back_w, back_y + 22),
            relative=0,
            thickness=0,
        )

    # Header rule - REV3 measured: 88pt below the page top on analysis pages.
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.8)
    rule_y = (top - 48) if page_number == 1 else (height - 88)
    canvas.line(MARGIN, rule_y, width - MARGIN, rule_y)

    tabs_offset = 0.0
    if show_tabs:
        tabs_offset = 20.0
        tab_y = top - 64
        tab_x = MARGIN
        for label, bookmark in REV3_TABS:
            tab_w = pdfmetrics.stringWidth(label, SANS_BOLD, T_MICRO)
            active = bookmark == "sec_overview" and page_number == 1
            canvas.setFillColor(TEXT if active else TEXT_MUTED)
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawString(tab_x, tab_y, label)
            if active:
                canvas.setStrokeColor(ACCENT)
                canvas.setLineWidth(1.6)
                canvas.line(tab_x, tab_y - 4, tab_x + tab_w, tab_y - 4)
            canvas.linkRect("", bookmark, (tab_x - 4, tab_y - 6, tab_x + tab_w + 4, tab_y + 10), relative=0, thickness=0)
            tab_x += tab_w + 26
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawRightString(width - MARGIN, tab_y, f"FLIGHT BRIEFING | PAGE {page_number} OF {page_count}")

    # Footer - REV3 measured: hairline over one Courier 6.7 line in the body
    # grey. The SOURCE and derivation lines keep their content, restyled to
    # the same utility mono.
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN, 28, width - MARGIN, 28)
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(UTIL_MONO, 6.7)
    canvas.drawString(
        MARGIN,
        9,
        " | ".join(
            value
            for value in (
                "FLIGHT BRIEFING",
                theme.display_flight_number(flight),
                f"OFP {theme.ofp_label(flight)}",
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
    canvas.setFont(UTIL_MONO_BOLD, 6.7)
    canvas.drawString(MARGIN, 18.5, "SOURCE")
    _draw_string_fitted(
        canvas, MARGIN + 34, 18.5, source_line[:180], UTIL_MONO, 6.7,
        width - 2 * MARGIN - 34, TEXT_SECONDARY,
    )
    # Analysis pages start where his content line sits: 94pt from the top.
    return top - 56 - tabs_offset if page_number == 1 else height - 94


def draw_section_title(canvas, y: float, text: str, accent=WEATHER_AMBER) -> float:
    """REV3 p3 banner vocabulary: a filled accent bar with dark bold caps
    inside - the giant white headings are retired (boss, 20 Aug REV3)."""
    width = PAGE_SIZE[0]
    bar_h = 20.0
    canvas.setFillColor(accent)
    canvas.roundRect(MARGIN, y - bar_h, width - 2 * MARGIN, bar_h, 4, stroke=0, fill=1)
    canvas.setFillColor(BG)
    canvas.setFont(SANS_BOLD, T_CARD_HEAD)
    canvas.drawString(MARGIN + 12, y - bar_h + 6.6, text.upper())
    return y - bar_h - 10


def panel(canvas, x, y, w, h, *, title, accent, title_colour=colors.white) -> tuple[float, float, float, float]:
    """REV3 canon card (boss, 20 Aug: "this look"): panel fill with a thin
    accent TOP border and the title inside as coloured text - the full-width
    coloured title bands are retired. Measured from the boss's REV3 file:
    #0E1B2A card, ~4pt accent bar, title text in the accent colour.
    Returns the inner content box (x, y, w, h)."""
    canvas.setFillColor(PANEL)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    canvas.setFillColor(accent)
    canvas.rect(x, y + h - 3, w, 3, stroke=0, fill=1)
    title_text_colour = accent if accent not in (PANEL, ELEVATED) else TEXT
    _draw_string_fitted(
        canvas, x + 10, y + h - 16.3, str(title).upper(),
        SANS_BOLD, T_CARD_HEAD, w - 20, title_text_colour,
    )
    return (x + 10, y + 6, w - 20, h - 24)


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
    va_advisories = (briefing.get("vaa") or {}).get("cfp_advisories") or []
    va_line = (
        f"{va_advisories[0]['name']} - see the hazard page"
        if va_advisories
        else _first_title(findings, {"weather"}) or "Weather review on the hazard page"
    )
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
    # Leading tracks T_SMALL at the REV3-measured 1.2 pitch.
    leading = round(T_SMALL * 1.2, 1)
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
        ("FPL REQ", timed("flt_plan_reqmt")),
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
    """REV3 canon dashboard (boss, 20 Aug: "this format, this content, this
    look"): airport cards flanking the CFP P1 route/levels panel with the
    analysis overlay, then FLIGHT BASIS | MASS/FUEL | TECHNICAL STATUS, and
    the PRIORITY strip across the bottom."""
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line="CFP P1 master context + deterministic analysis",
        show_tabs=True,
    )
    canvas.bookmarkPage("sec_overview")
    # REV3: the tab strip is the page label - no separate big title row.
    y = content_top - 2

    full_w = width - 2 * MARGIN
    departure_panel = briefing.get("departure") or {}
    destination_panel = briefing.get("destination") or {}
    alternates = flight.get("alternates") or []
    fuel_summary = flight.get("fuel_summary") or {}
    hazards = briefing.get("hazards") or {}
    cards = hazards.get("sigmet_cards") or []
    edto_view = briefing.get("edto") or {}

    priority_h = 24.0
    row_gap = 10.0
    bottom = 30 + priority_h + row_gap
    row2_h = 158.0
    row1_h = y - bottom - row2_h - row_gap
    side_w = full_w * 0.215
    centre_x = MARGIN + side_w + 10
    centre_w = full_w - 2 * (side_w + 10)
    right_x = MARGIN + full_w - side_w

    def kv_rows(ix, top, iw, rows, *, mono_value=True, row_h=13.0):
        row_y = top
        for label, value in rows:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, T_MICRO)
            canvas.drawString(ix, row_y, str(label))
            canvas.setFillColor(TEXT)
            canvas.setFont(MONO_BOLD if mono_value else SANS_BOLD, T_MICRO)
            _draw_string_fitted(canvas, ix + 78, row_y, str(value), MONO_BOLD if mono_value else SANS_BOLD, T_MICRO, iw - 82, TEXT)
            row_y -= row_h
        return row_y

    def bulletin_first_line(panel_data, kind):
        weather = panel_data.get("weather") or {}
        return str(weather.get(kind) or "").strip()

    def weather_fallback(panel_data):
        weather = panel_data.get("weather") or {}
        text = str(
            weather.get("primary")
            or weather.get("secondary")
            or weather.get("summary")
            or weather.get("detail")
            or "Weather review on the hazard assessment page."
        )
        # First sentence, drawn as one fitted line: a mid-sentence wrap breaks
        # the exact-text contract the 16 Aug fallback test pins.
        head, _, _ = text.partition(". ")
        return head + "." if not head.endswith(".") else head

    # --- Row 1: DEPARTURE | CFP P1 ROUTE / LEVELS + ANALYSIS OVERLAY | DESTINATION
    row1_top = y
    dep_inner = panel(canvas, MARGIN, row1_top - row1_h, side_w, row1_h,
                      title=f"DEPARTURE  {theme.airport_code_label(departure_panel.get('icao') or flight.get('departure'))}",
                      accent=DEPARTURE, title_colour=None)
    ix = dep_inner[0]
    row_y = row1_top - 30
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, T_BODY)
    canvas.drawString(ix, row_y, str(departure_panel.get("runway") or "Runway review"))
    row_y -= 15
    row_y = kv_rows(ix, row_y, side_w - 28, (
        ("SCHEDULE", f"{_clock_at(flight, 0)}"),
    ))
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawString(ix, row_y, "FORECAST AT ETD")
    row_y -= 10
    metar = bulletin_first_line(departure_panel, "metar")
    taf = bulletin_first_line(departure_panel, "taf")
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    dep_lines = ([f"METAR {metar}"] if metar else []) + ([f"TAF {taf}"] if taf else [])
    if dep_lines:
        for line in dep_lines:
            for wrapped in _wrap(line, MONO, T_MICRO, side_w - 28)[:2]:
                canvas.drawString(ix, row_y, wrapped)
                row_y -= 9.4
    else:
        _draw_string_fitted(canvas, ix, row_y, weather_fallback(departure_panel), SANS, T_MICRO, side_w - 28, TEXT_SECONDARY)
        row_y -= 9.4
    primary_alternate = alternates[0] if alternates else {}
    dest_inner = panel(canvas, right_x, row1_top - row1_h, side_w, row1_h,
                       title=f"DESTINATION  {theme.airport_code_label(destination_panel.get('icao') or flight.get('destination'))}",
                       accent=DESTINATION, title_colour=None)
    ix2 = dest_inner[0]
    row_y2 = row1_top - 30
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, T_BODY)
    canvas.drawString(ix2, row_y2, str(destination_panel.get("runway") or "Runway review"))
    row_y2 -= 15
    arrival_minutes = None
    for waypoint in reversed(flight.get("route_waypoints") or []):
        if waypoint.get("actm_minutes") is not None:
            arrival_minutes = waypoint.get("actm_minutes")
            break
    row_y2 = kv_rows(ix2, row_y2, side_w - 28, (
        ("SCHEDULE", _clock_at(flight, arrival_minutes) if arrival_minutes is not None else "--"),
    ))
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawString(ix2, row_y2, "FORECAST AT ETA")
    row_y2 -= 10
    metar2 = bulletin_first_line(destination_panel, "metar")
    taf2 = bulletin_first_line(destination_panel, "taf")
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    dest_lines = ([f"METAR {metar2}"] if metar2 else []) + ([f"TAF {taf2}"] if taf2 else [])
    if dest_lines:
        for line in dest_lines:
            for wrapped in _wrap(line, MONO, T_MICRO, side_w - 28)[:2]:
                canvas.drawString(ix2, row_y2, wrapped)
                row_y2 -= 9.4
    else:
        _draw_string_fitted(canvas, ix2, row_y2, weather_fallback(destination_panel), SANS, T_MICRO, side_w - 28, TEXT_SECONDARY)
        row_y2 -= 9.4
    row_y2 -= 4
    canvas.setFillColor(WEATHER_AMBER)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix2, row_y2, "PREFERRED ALTERNATE")
    row_y2 -= 10
    summary_alternate = fuel_summary.get("alternate") or {}
    altn_rows_data = fuel_summary.get("rows") or {}
    altn_fuel = (altn_rows_data.get("altn_fuel") or {}).get("fuel_kg")
    altn_time = (altn_rows_data.get("altn_fuel") or {}).get("time_minutes")
    altn_line = " | ".join(part for part in (
        f"{theme.airport_code_label(primary_alternate.get('airport') or summary_alternate.get('icao'))}"
        f"{'/' + str(primary_alternate.get('runway')) if primary_alternate.get('runway') else ''}",
        str(primary_alternate.get("approach") or "") or None,
        f"{primary_alternate.get('distance_nm')} NM" if primary_alternate.get("distance_nm") else None,
        format_actm(altn_time).replace(".", ":") if altn_time is not None else None,
        f"{altn_fuel:,} kg" if altn_fuel is not None else None,
    ) if part)
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    for wrapped in _wrap(altn_line or "Alternate planning data requires review.", MONO, T_MICRO, side_w - 28)[:2]:
        canvas.drawString(ix2, row_y2, wrapped)
        row_y2 -= 9.4

    centre_inner = panel(canvas, centre_x, row1_top - row1_h, centre_w, row1_h,
                         title="CFP P1 - ROUTE / LEVELS + ANALYSIS OVERLAY",
                         accent=ACCENT, title_colour=None)
    cx0 = centre_inner[0]
    text_w = centre_w * 0.55
    map_w = centre_w - text_w - 34
    row_y3 = row1_top - 28
    chips = [chip for chip in (
        "EDTO / RVSM" if "EDTO" in str(fuel_summary.get("source_classification") or "").upper() else None,
        f"CI {flight.get('cost_index')}" if flight.get("cost_index") is not None else None,
        f"CRZ COMP {fuel_summary.get('cruise_wind_component_kt')}" if fuel_summary.get("cruise_wind_component_kt") is not None else None,
    ) if chip]
    chip_x = cx0
    for chip in chips:
        chip_w = pdfmetrics.stringWidth(chip, SANS_BOLD, T_MICRO) + 14
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.8)
        canvas.roundRect(chip_x, row_y3 - 4, chip_w, 12.5, 6.2, stroke=1, fill=0)
        canvas.setFillColor(ACCENT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawCentredString(chip_x + chip_w / 2, row_y3, chip)
        chip_x += chip_w + 6
    row_y3 -= 16
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawString(cx0, row_y3, "CFP ROUTE")
    row_y3 -= 10
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    for wrapped in _wrap(str(flight.get("route_text") or "Route text not held."), MONO, T_MICRO, text_w)[:3]:
        canvas.drawString(cx0, row_y3, wrapped)
        row_y3 -= 9.4
    row_y3 -= 3
    profile = str(flight.get("planned_level_profile") or "").strip()
    if profile:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(cx0, row_y3, "PLANNED LEVEL PROFILE")
        row_y3 -= 10
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        # The profile is one unbroken FIX/LEVEL token chain - word wrapping
        # cannot split it (SQ322's ran under the map), so break on slashes.
        profile_lines: list[str] = []
        current = ""
        for segment in profile.split("/"):
            candidate = f"{current}/{segment}" if current else segment
            if pdfmetrics.stringWidth(candidate + "/", MONO, T_MICRO) > text_w and current:
                profile_lines.append(current + "/")
                current = segment
            else:
                current = candidate
        if current:
            profile_lines.append(current)
        for line in profile_lines[:2]:
            canvas.drawString(cx0, row_y3, line)
            row_y3 -= 9.4
    ground = fuel_summary.get("ground_miles_nm")
    air = fuel_summary.get("air_miles_nm")
    dist_line = " | ".join(part for part in (
        f"GND {ground:,} NM" if ground else None,
        f"AIR {air:,} NM" if air else None,
    ) if part)
    if dist_line:
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(cx0, row_y3, dist_line)
        row_y3 -= 11
    airports_view = edto_view.get("airports") or []
    if airports_view:
        airport = airports_view[0]
        canvas.setFillColor(EDTO_GREEN)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(cx0, row_y3, "EDTO")
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        edto_line = " ".join(part for part in (
            f"{airport.get('airport')} RWY{airport.get('runway')}",
            str(airport.get("approach") or ""),
            str(airport.get("minima") or ""),
            "| TOP-UP 0 KG" if not (edto_view.get("fuel") or {}).get("top_up_kg") else None,
        ) if part)
        _draw_string_fitted(canvas, cx0 + 34, row_y3, edto_line, MONO, T_MICRO, text_w - 34, TEXT_SECONDARY)
        row_y3 -= 11
    wx_bits = []
    for card in cards[:3]:
        sid = str(card.get("sigmet_id") or "")
        screening = str(card.get("screening") or "")
        if "does not intersect" in screening:
            wx_bits.append(f"{sid} OFF ROUTE")
        elif "expires" in screening:
            wx_bits.append(f"{sid} EXPIRED BEFORE ENTRY")
        elif card.get("disposition") == "PROMOTED":
            wx_bits.append(f"{sid} PROMOTED")
    if not wx_bits and not dest_lines:
        # No bulletin and no SIGMET cards: the operating-window fallback
        # sentence prints here in full - the wide row keeps it on one line,
        # which the 16 Aug exact-text contract requires.
        wx_bits = [weather_fallback(destination_panel)]
    if wx_bits:
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(cx0, row_y3, "WX")
        wx_font = MONO if len(wx_bits) > 1 or "|" in wx_bits[0] else SANS
        _draw_string_fitted(canvas, cx0 + 34, row_y3, " | ".join(wx_bits), wx_font, T_MICRO, text_w - 34, TEXT_SECONDARY)
        row_y3 -= 11

    map_x = cx0 + text_w + 14
    map_h = row1_h - 72
    from .briefing import draw_route_map_pdf  # local import; briefing pulls widely

    canvas.setFillColor(PANEL)
    canvas.roundRect(map_x, row1_top - 24 - map_h, map_w, map_h, 4, stroke=0, fill=1)
    draw_route_map_pdf(canvas, briefing.get("route_map") or {}, map_x, row1_top - 24 - map_h, map_w, map_h)
    strip_entries = [entry for entry in _route_anchor_entries(flight, briefing)]
    if len(strip_entries) > 5:
        keep = {0, len(strip_entries) - 1}
        keep.update(index for index, entry in enumerate(strip_entries) if entry.get("label", "").startswith("EDTO") or "*" in str(entry.get("sub") or ""))
        strip_entries = [entry for index, entry in enumerate(strip_entries) if index in keep][:5]
    _timeline(canvas, cx0, row1_top - row1_h + 14, centre_w - 28, strip_entries)

    # --- Row 2: FLIGHT BASIS | MASS / FUEL | TECHNICAL STATUS
    row2_top = row1_top - row1_h - row_gap
    col_w = (full_w - 2 * 10) / 3
    basis_inner = panel(canvas, MARGIN, row2_top - row2_h, col_w, row2_h,
                        title="CFP P1 - FLIGHT BASIS", accent=COMMS_TEAL, title_colour=None)
    ix = basis_inner[0]
    kv_rows(ix, row2_top - 28, col_w - 28, (
        ("AIRCRAFT/REG", f"{flight.get('aircraft_type') or '--'} / {theme.normalized_registration(flight.get('registration')) or '--'}"),
        ("CAPTAIN", str(flight.get("captain") or "--")),
        ("EET", str((briefing.get("metrics") or {}).get("eet") or "--").replace(".", ":")),
        ("CI", str(flight.get("cost_index") if flight.get("cost_index") is not None else "--")),
        ("GND / AIR NM", f"{ground or '--'} / {air or '--'}"),
        ("CRZ COMP", f"M{abs(fuel_summary.get('cruise_wind_component_kt'))}" if (fuel_summary.get("cruise_wind_component_kt") or 0) < 0 else f"P{fuel_summary.get('cruise_wind_component_kt')}" if fuel_summary.get("cruise_wind_component_kt") is not None else "--"),
        ("CLASSIFICATION", (
            f"{fuel_summary.get('source_classification')} (NON-EDTO)"
            if str(fuel_summary.get("source_classification") or "").upper() == "STANDARD"
            else str(fuel_summary.get("source_classification") or "--")
        )),
    ))

    fuel_inner = panel(canvas, MARGIN + col_w + 10, row2_top - row2_h, col_w, row2_h,
                       title="CFP P1 - MASS / FUEL", accent=EDTO_GREEN, title_colour=None)
    ix = fuel_inner[0]
    masses = fuel_summary.get("masses_kg") or {}
    performance = flight.get("performance") or {}
    controlling = performance.get("controlling_rtow_kg")
    ptow = masses.get("ptow")
    margin_kg = (controlling - ptow) if controlling and ptow else None
    half_col = (col_w - 28) / 2
    mass_rows = [
        ("PZFW", f"{masses.get('pzfw'):,}" if masses.get("pzfw") else "--"),
        ("PTOW", f"{masses.get('ptow'):,}" if masses.get("ptow") else "--"),
        ("PLWT", f"{masses.get('plwt'):,}" if masses.get("plwt") else "--"),
        ("RTOW", f"{controlling:,}" if controlling else "--"),
        ("MARGIN", f"+{margin_kg:,}" if margin_kg and margin_kg > 0 else f"{margin_kg:,}" if margin_kg is not None else "--"),
        ("ZFW +1000", f"+{flight.get('zfw_change_burn_kg_per_1000')} BURN" if flight.get("zfw_change_burn_kg_per_1000") else "--"),
    ]
    def _value_right(x_right, y_row, value, colour, label_end):
        # Numbers shrink to fit but never truncate - a fuel figure with a
        # missing digit is worse than a small one (SQ322 A380 masses).
        size = T_MICRO
        # Floor at the legibility gate (boss, 18 Aug type ruling): make
        # room with format, never with unreadable digits.
        while size > 7.2 and pdfmetrics.stringWidth(str(value), MONO_BOLD, size) > (x_right - label_end):
            size -= 0.2
        canvas.setFillColor(colour)
        canvas.setFont(MONO_BOLD, size)
        canvas.drawRightString(x_right, y_row, str(value))

    row_y = row2_top - 28
    for label, value in mass_rows:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix, row_y, label)
        _value_right(ix + half_col - 8, row_y, value,
                     ACCENT if label == "MARGIN" else TEXT,
                     ix + pdfmetrics.stringWidth(label, SANS, T_MICRO) + 4)
        row_y -= 13
    rows_data = fuel_summary.get("rows") or {}
    def timed(key):
        row = rows_data.get(key) or {}
        fuel_kg = row.get("fuel_kg")
        minutes = row.get("time_minutes")
        if fuel_kg is None:
            return "--"
        clock = f"{int(minutes) // 60}:{int(minutes) % 60:02d}" if minutes is not None else "-"
        return f"{fuel_kg:,}/{clock}"
    fuel_rows = [
        ("BURNOFF", timed("burnoff")),
        ("STAT CONT", timed("stat_cont")),
        ("ALTN", timed("altn_fuel")),
        ("TAXI", f"{fuel_summary.get('taxi_fuel_kg'):,}" if fuel_summary.get("taxi_fuel_kg") else "--"),
        ("FPL REQMT", timed("flt_plan_reqmt")),
        ("TANKS", f"{(rows_data.get('fuel_in_tanks') or {}).get('fuel_kg') or 0:,}/{(rows_data.get('excess_fuel') or {}).get('fuel_kg') or 0:,}"),
    ]
    row_y = row2_top - 28
    for label, value in fuel_rows:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix + half_col + 8, row_y, label)
        _value_right(ix + col_w - 28, row_y, value, TEXT,
                     ix + half_col + 8 + pdfmetrics.stringWidth(label, SANS, T_MICRO) + 4)
        row_y -= 13
    if str(fuel_summary.get("state") or "") != "verified":
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, row2_top - row2_h + 10, "Page-1 fuel arithmetic did not verify - review the source CFP page.")

    tech_inner = panel(canvas, MARGIN + 2 * (col_w + 10), row2_top - row2_h, col_w, row2_h,
                       title="CFP P1 - TECHNICAL STATUS", accent=CRITICAL, title_colour=None)
    ix = tech_inner[0]
    row_y = row2_top - 28
    deferred = flight.get("deferred_items") or []
    seen_refs: set[tuple[str, str]] = set()
    listed = []
    for item in deferred:
        reference = str(item.get("reference") or "").strip()
        item_type = str(item.get("item_type") or "").strip()
        if reference and reference != "UNSPECIFIED":
            key = (item_type, reference)
            if key in seen_refs:
                # One governing reference, one row - repeated instances keep
                # their own detail groups on the MEL/CDL page (16 Jul rule).
                continue
            seen_refs.add(key)
        listed.append(item)
    for item in listed[:6]:
        reference = str(item.get("reference") or "").strip()
        item_type = str(item.get("item_type") or "").strip()
        label = f"{item_type} {reference}" if reference and reference != "UNSPECIFIED" else item_type or "ITEM"
        note = str(item.get("company_remark") or item.get("description") or "")
        canvas.setFillColor(WEATHER_AMBER if item_type in {"CDL", "CDDL"} else CRITICAL)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, label[:16])
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        _draw_string_fitted(canvas, ix + 76, row_y, note, SANS, T_MICRO, col_w - 108, TEXT_SECONDARY)
        row_y -= 11.5
    if not deferred:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix, row_y, "No deferred item is printed on CFP page 1.")
        row_y -= 11.5
    row_y -= 4
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix, row_y, "ANALYSIS / RELEASE INPUTS")
    row_y -= 11
    ledger_rows = hazards.get("coverage_ledger") or []
    gaps = [row.get("label") for row in ledger_rows if str(row.get("status")) == "unavailable"]
    release_lines = []
    if any(str(item.get("item_type")) in {"CDL", "CDDL"} for item in deferred):
        release_lines.append(("OPEN", "CDL/CDDL seal inputs - no guessed penalties."))
    if gaps:
        release_lines.append(("GAP", f"{'/'.join(gaps)} unavailable - coverage gap, not NIL."))
    for tag, line in release_lines[:3]:
        canvas.setFillColor(CRITICAL if tag == "OPEN" else WEATHER_AMBER)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, tag)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        _draw_string_fitted(canvas, ix + 34, row_y, line, SANS, T_MICRO, col_w - 66, TEXT_SECONDARY)
        row_y -= 11

    # --- PRIORITY strip
    strip_inner = panel(canvas, MARGIN, 30, full_w, priority_h + 12, title="", accent=PANEL)
    px0 = MARGIN + 12
    canvas.setFillColor(CRITICAL)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(px0, 30 + 12, "PRIORITY")
    px0 += 64
    priority_bits = []
    if any(str(item.get("item_type")) in {"CDL", "CDDL"} for item in deferred):
        priority_bits.append("CDL SEAL DATA")
    entry_clock = None
    for sector in (flight.get("edto") or {}).get("sectors") or []:
        entry_actm = (sector.get("entry") or {}).get("actm_minutes")
        if entry_actm is not None:
            entry_clock = _clock_at(flight, entry_actm)
            break
    if entry_clock:
        priority_bits.append(f"EDTO {entry_clock}")
    events = (briefing.get("terrain") or {}).get("events") or []
    if events:
        first = events[0].get("first_high") or {}
        last = events[0].get("last_high") or {}
        priority_bits.append(f"TERRAIN {first.get('msa_hundreds_ft')}*-{last.get('msa_hundreds_ft')}*")
    promoted = [card for card in cards if card.get("disposition") == "PROMOTED"]
    priority_bits.append(
        f"{len(promoted)} SIGMET PROMOTED" if promoted else "NO SIGMET PROMOTED"
    )
    for bit in priority_bits:
        bit_w = pdfmetrics.stringWidth(bit, SANS_BOLD, T_MICRO)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(px0, 30 + 12, bit)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.8)
        canvas.line(px0 + bit_w + 12, 30 + 8, px0 + bit_w + 12, 30 + 22)
        px0 += bit_w + 24


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
    canvas.setLineWidth(1.0)
    canvas.line(x, rail_y, x + w, rail_y)
    for index, entry in enumerate(entries):
        cx = x + (index * step if len(entries) > 1 else w / 2)
        accent = entry.get("accent") or accent_default
        canvas.setFillColor(accent)
        canvas.circle(cx, rail_y, 3.4, stroke=0, fill=1)
        # REV3 measured strip: white Courier-Bold times above the rail,
        # accent-coloured labels below it - his file inverts our old colours.
        canvas.setFillColor(TEXT)
        canvas.setFont(UTIL_MONO_BOLD, 7.6)
        time_text = str(entry.get("time") or "--")
        tw = pdfmetrics.stringWidth(time_text, UTIL_MONO_BOLD, 7.6)
        canvas.drawString(min(max(x, cx - tw / 2), x + w - tw), rail_y + 8, time_text)
        canvas.setFillColor(accent)
        canvas.setFont(SANS_BOLD, 7.0)
        label = str(entry.get("label") or "")[:14]
        lw = pdfmetrics.stringWidth(label, SANS_BOLD, 7.0)
        canvas.drawString(min(max(x, cx - lw / 2), x + w - lw), rail_y - 15, label)
        sub = str(entry.get("sub") or "")[:20]
        if sub:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, 7.0)
            sw = pdfmetrics.stringWidth(sub, SANS, 7.0)
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
            "actm": w.get("actm_minutes"),
        })
    # EDTO anchors from the parsed sectors join the strip; a boundary graze
    # collapses to one anchor, matching the canon's single "EDTO" dot.
    for sector in (flight.get("edto") or {}).get("sectors") or []:
        entry_actm = (sector.get("entry") or {}).get("actm_minutes")
        exit_actm = (sector.get("exit") or {}).get("actm_minutes")
        if entry_actm is not None and entry_actm == exit_actm:
            entries.append({
                "time": _clock_at(flight, entry_actm),
                "label": "EDTO",
                "sub": f"E/X {format_actm(entry_actm)}",
                "accent": EDTO_GREEN,
                "actm": entry_actm,
            })
            continue
        for actm, label in ((entry_actm, "EDTO ENTRY"), (exit_actm, "EDTO EXIT")):
            if actm is not None:
                entries.append({
                    "time": _clock_at(flight, actm),
                    "label": label,
                    "sub": format_actm(actm),
                    "accent": EDTO_GREEN,
                    "actm": actm,
                })
    entries.sort(key=lambda item: item.get("actm") if item.get("actm") is not None else 0)
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
    inner = panel(canvas, MARGIN, hazard_y - strip_h, full_w, strip_h, title="HAZARD AND COMMUNICATION GATES", accent=WEATHER_AMBER, title_colour=None)
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
    # The one composed terrain sentence prints verbatim here - the parity
    # gate requires it in both directions (a no-window flight must SAY so).
    summary_line = str((briefing.get("terrain") or {}).get("summary") or "")
    if summary_line:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        _draw_string_fitted(canvas, MARGIN, y - 2, summary_line, SANS, T_SMALL, full_w, TEXT_SECONDARY)
        y -= T_SMALL + 8
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

    # Strict MSA >100* point table - the canon names every point with its
    # ACTM/UTC, MSA and VWS instead of an anonymous "event 1".
    events = (briefing.get("terrain") or {}).get("events") or []
    point_rows: list[tuple[str, str, str, str]] = []
    for event in events[:2]:
        seen_points: set[str] = set()
        for key in ("preceding", "first_high", "maximum", "last_high", "drop"):
            point = event.get(key) or {}
            name = str(point.get("name") or "").lstrip("-")
            if not name or name in seen_points:
                continue
            seen_points.add(name)
            actm = point.get("actm_minutes")
            clock = _clock_at(flight, actm) if actm is not None else None
            msa = point.get("msa_hundreds_ft")
            point_rows.append((
                name,
                (format_actm(actm) if actm is not None else "--")
                + (f" / {clock}" if clock else ""),
                f"{msa:03d}{'*' if point.get('msa_asterisk') else ''}" if msa is not None else "--",
                f"{point.get('vws'):03d}" if point.get("vws") is not None else "--",
            ))
    point_table_h = (26 + len(point_rows) * 12 + 8) if point_rows else 0.0
    if point_rows:
        table_top = cards_y - 10
        inner = panel(canvas, MARGIN, table_top - point_table_h, full_w, point_table_h,
                      title="STRICT MSA >100* EVENT", accent=TERRAIN_ORANGE, title_colour=None)
        ix = inner[0]
        row_y = table_top - 26
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        for label, offset in (("POINT", 0), ("ACTM / UTC", 110), ("MSA", 250), ("VWS", 320)):
            canvas.drawString(ix + offset, row_y, label)
        row_y -= 12
        for name, actm, msa, vws in point_rows:
            starred = msa.endswith("*")
            canvas.setFillColor(TEXT)
            canvas.setFont(MONO_BOLD if starred else MONO, T_SMALL)
            canvas.drawString(ix, row_y, name)
            canvas.setFont(MONO, T_SMALL)
            canvas.drawString(ix + 110, row_y, actm)
            canvas.setFillColor(TERRAIN_ORANGE if starred else TEXT)
            canvas.setFont(MONO_BOLD if starred else MONO, T_SMALL)
            canvas.drawString(ix + 250, row_y, msa)
            canvas.setFillColor(CRITICAL if vws not in ("--",) and int(vws) > 4 else TEXT_SECONDARY)
            canvas.setFont(MONO, T_SMALL)
            canvas.drawString(ix + 320, row_y, vws)
            row_y -= 12
        cards_y = table_top - point_table_h

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
        inner = panel(canvas, px, profiles_top - profiles_h, profile_w, profiles_h, title=title, accent=accents[index % 2], title_colour=None)
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
        inner = panel(canvas, MARGIN, profiles_top - profiles_h, full_w, profiles_h, title="APPROVED PROFILE SET", accent=EDTO_GREEN, title_colour=None)
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
                label = str(finding.get("title") or "")
                for event in events:
                    first = event.get("first_high") or {}
                    if first.get("actm_minutes") == start:
                        last = event.get("last_high") or {}
                        airway = str(first.get("airway_in") or "").strip()
                        label = (
                            f"{str(first.get('name') or '').lstrip('-')}"
                            f"-{str(last.get('name') or '').lstrip('-')}"
                            + (f" on {airway}" if airway else "")
                        )
                        break
                canvas.setFillColor(TEXT)
                canvas.setFont(SANS, T_SMALL)
                canvas.drawString(ix, row_y, label[:34])
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
    half_w = (full_w - 22) / 2
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

    right_x = MARGIN + half_w + 22
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
    inner = panel(canvas, MARGIN, 30, full_w, sens_h, title="FLIGHT-PLANNING SENSITIVITIES", accent=WEATHER_AMBER, title_colour=None)
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
    half_w = (full_w - 22) / 2
    accents = (DEPARTURE, EDTO_GREEN, DESTINATION, COMMS_TEAL)
    cards = deferred if deferred else [None]
    if len(cards) > MEL_CDL_GROUPS_PER_PAGE:
        raise ValueError(
            "MEL/CDL page received more than its readable card capacity; "
            "paginate the grouped items before drawing."
        )
    row_count = 1 if len(cards) <= 2 else 2
    row_gap = 10.0
    card_h = 92.0 if row_count == 1 else 88.0
    cards_h = card_h * row_count + row_gap * (row_count - 1)
    for index, item in enumerate(cards):
        row = index // 2
        column = index % 2
        is_single_in_row = index == len(cards) - 1 and len(cards) % 2 == 1
        card_w = full_w if is_single_in_row else half_w
        cx = MARGIN if is_single_in_row else MARGIN + column * (half_w + 22)
        card_top = y - row * (card_h + row_gap)
        card_bottom = card_top - card_h
        if item is None:
            inner = panel(canvas, cx, card_bottom, full_w, card_h, title="DEFERRED ITEMS", accent=EDTO_GREEN, title_colour=None)
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
        # Body lines stop where the bottom-anchored penalty line begins -
        # the count comes from the card geometry so no width or wording can
        # push a line into it (the full remark is always in the crop below).
        body_step = round(T_SMALL * 1.2, 2)
        body_lines = max(1, min(3, 1 + int((card_h - 48 - 18.7) // body_step)))
        row_y = card_top - 48
        for line in _wrap(body, SANS, T_SMALL, iw)[:body_lines]:
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_SMALL)
            canvas.drawString(ix, row_y, line)
            row_y -= body_step
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
    half_w = (full_w - 22) / 2
    table_h = 92.0
    crops_h = y - 30 - table_h - 10

    # Left: the parsed entry/exit/alternate facts stay readable above the exact
    # airline EDTO source crop. This is the operational data the earlier report
    # lost even after the parser had successfully extracted it.
    inner = panel(canvas, MARGIN, y - crops_h, half_w, crops_h, title=f"{classification_label} SOURCE / STATUS", accent=EDTO_GREEN, title_colour=None)
    ix, iy, iw, ih = inner
    edto_rows = _edto_operational_rows(
        classification,
        briefing.get("edto") or {},
        flight.get("fuel_summary") or {},
    )
    # Every operational row prints here now that the old time-gates page is
    # folded away - the parity gate checks each one verbatim.
    summary_rows = edto_rows
    # Rows wrap instead of truncating: a fitted-and-elided ETPS row breaks
    # the parity gate's verbatim requirement (SQ34's 15 equal-time points).
    row_value_width = half_w - 28 - 82
    row_line_counts = [
        max(1, len(_wrap(str(value), SANS, T_SMALL, row_value_width)[:3]))
        for _, value in summary_rows
    ]
    summary_h = min(190.0, 18.0 + sum(count * 11.0 + 1.0 for count in row_line_counts))
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
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS, T_SMALL)
        for line in _wrap(str(value), SANS, T_SMALL, iw - 82)[:3]:
            canvas.drawString(ix + 78, row_y, line)
            row_y -= 11
        row_y -= 1

    inner = panel(canvas, MARGIN + half_w + 22, y - crops_h, half_w, crops_h, title="ALTERNATE PLANNING SOURCE", accent=DESTINATION)
    ix2, iy2, iw2, ih2 = inner
    crop2 = crop_source_region(source_pdf_path, needle="FLT PLANNING ALTN SUMMARY", page_hint=0, full_width=True) or crop_source_region(source_pdf_path, needle="ALTN/RWY", page_hint=0, full_width=True)
    _draw_crop(canvas, crop2, ix2, iy2 + 6, iw2, ih2 - 10, missing_text="Alternate planning section not found for cropping - review the CFP weather pages.")

    # Alternates table.
    inner = panel(canvas, MARGIN, 30, full_w, table_h, title="ALTERNATES AND PLANNING BASIS", accent=WEATHER_AMBER, title_colour=None)
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
    half_w = (full_w - 22) / 2
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
        px = MARGIN + index * (half_w + 22)
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

    # Named volcanic-ash advisories lead the page: the label, the derived
    # closest-approach screening, then everything else (boss, 18 Aug).
    for advisory in ((briefing.get("vaa") or {}).get("cfp_advisories") or [])[:2]:
        canvas.setFillColor(TERRAIN_ORANGE)
        canvas.setFont(SANS_BOLD, T_BODY)
        canvas.drawString(MARGIN, y - 4, str(advisory.get("name") or ""))
        y -= T_BODY + 6
        if advisory.get("derived"):
            canvas.setFillColor(TEXT)
            canvas.setFont(SANS, T_SMALL)
            for line in _wrap(str(advisory["derived"]), SANS, T_SMALL, width - 2 * MARGIN)[:3]:
                canvas.drawString(MARGIN, y - 2, line)
                y -= T_SMALL + 3.5
        y -= 4

    full_w = width - 2 * MARGIN
    half_w = (full_w - 22) / 2

    # REV3 canon (boss, 20 Aug): one verdict card per enroute SIGMET, each
    # carrying its deterministic reason, then the coverage ledger; the CFP's
    # own weather page rides alongside as the printed source.
    strip_h = 150.0
    columns_bottom = 30 + strip_h + 10
    cards = (briefing.get("hazards") or {}).get("sigmet_cards") or []
    ledger_rows = (briefing.get("hazards") or {}).get("coverage_ledger") or []

    card_accents = {
        "PROMOTED": CRITICAL,
        "NOT PROMOTED": WEATHER_AMBER,
        "REVIEW REQUIRED": COMMS_TEAL,
    }
    card_y = y
    for card in cards[:4]:
        screen_lines = _wrap(str(card.get("screening") or ""), SANS, T_MICRO, half_w - 28)[:4]
        card_h = 34 + 12 + len(screen_lines) * 9.6
        if card_y - card_h < columns_bottom + 96:
            break
        accent = card_accents.get(str(card.get("disposition") or ""), WEATHER_AMBER)
        panel(canvas, MARGIN, card_y - card_h, half_w, card_h,
              title=str(card.get("name") or "SIGMET")[:52].upper(), accent=accent, title_colour=None)
        meta = " | ".join(part for part in (
            f"VALID {card.get('valid_from')}/{card.get('valid_to')}"
            if card.get("valid_from") else None,
            str(card.get("layer") or "") or None,
            str(card.get("movement") or "") or None,
        ) if part)
        row_y = card_y - 30
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO, T_MICRO)
        _draw_string_fitted(canvas, MARGIN + 14, row_y, meta, MONO, T_MICRO, half_w - 28, TEXT)
        row_y -= 12
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        for line in screen_lines:
            canvas.drawString(MARGIN + 14, row_y, line)
            row_y -= 9.6
        card_y -= card_h + 8
    if not cards:
        none_h = 40.0
        panel(canvas, MARGIN, card_y - none_h, half_w, none_h,
              title="ENROUTE SIGMETS", accent=COMMS_TEAL, title_colour=None)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(MARGIN + 14, card_y - 30,
                          "No enroute SIGMET is printed in this CFP's weather pages.")
        card_y -= none_h + 8

    # Coverage ledger: the CFP's section availability, the governed review
    # statuses, and every VAAC centre - gaps stay visible, never assumed clear.
    ledger_h = max(96.0, card_y - columns_bottom)
    ledger_top = card_y
    panel(canvas, MARGIN, ledger_top - ledger_h, half_w, ledger_h,
          title="COVERAGE LEDGER", accent=ELEVATED)
    row_y = ledger_top - 28
    ledger_line = " | ".join(
        f"{row.get('label')}: {row.get('status')}" for row in ledger_rows
    ) or "AIRMET: unavailable | TC SIGMET: unavailable | VA SIGMET: unavailable"
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO, T_MICRO)
    _draw_string_fitted(canvas, MARGIN + 14, row_y, ledger_line, MONO, T_MICRO, half_w - 28, TEXT)
    row_y -= 11
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    _draw_string_fitted(
        canvas, MARGIN + 14, row_y,
        "These are source-coverage gaps, not NIL findings.",
        SANS, T_MICRO, half_w - 28, TEXT_MUTED,
    )
    row_y -= 13
    vaa_review = flight.get("vaa_review") or {}
    vaac_ledger = vaa_review.get("vaac_centre_ledger") or []
    vaac_total = len(vaac_ledger) or 9
    vaac_reached = sum(
        1 for item in vaac_ledger
        if item.get("status") in {"available", "partial"}
    )
    for label, status in (
        ("SIGMET REVIEW", str(((flight.get("sigmet_review") or {}).get("status")) or "no data in CFP")),
        ("VA REVIEW", str(vaa_review.get("status") or "no data in CFP")),
        ("TC REVIEW", str(((flight.get("tropical_cyclone_review") or {}).get("status")) or "no data in CFP")),
        ("VAAC CENTRES", f"{vaac_reached}/{vaac_total} reached"),
    ):
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(MARGIN + 14, row_y, label)
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        _draw_string_fitted(canvas, MARGIN + 110, row_y, status.replace("_", " "), SANS_BOLD, T_MICRO, half_w - 140, WEATHER_AMBER)
        row_y -= 11
    status_copy = {
        "available": "reached",
        "partial": "partial",
        "unavailable": "unavailable",
        "not_mounted": "not mounted",
    }
    for start_index in range(0, len(vaac_ledger), 3):
        centre_line = " | ".join(
            f"{str(item.get('centre') or 'UNKNOWN').upper()}: "
            f"{status_copy.get(str(item.get('status') or '').lower(), 'unavailable')}"
            for item in vaac_ledger[start_index:start_index + 3]
        )
        if row_y < ledger_top - ledger_h + 12:
            break
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        _draw_string_fitted(canvas, MARGIN + 14, row_y, centre_line, MONO, T_MICRO, half_w - 28, TEXT_SECONDARY)
        row_y -= 10

    # The CFP's own weather page, cropped as printed - the source beside the
    # verdicts, exactly as the canon lays it out.
    right_x = MARGIN + half_w + 22
    right_h = y - columns_bottom
    panel(canvas, right_x, y - right_h, half_w, right_h,
          title="CFP SIGMET / WEATHER SOURCE", accent=WEATHER_AMBER, title_colour=None)
    wx_crop = crop_source_region(
        source_pdf_path,
        needle="Airport WX List",
        end_needle="DESTINATION ALTERNATE",
        page_hint=13, max_pages=54, pad_y=10,
    ) or crop_source_region(
        source_pdf_path,
        needle="SIGMETs:",
        page_hint=13, max_pages=54, pad_y=14,
    )
    if wx_crop:
        from io import BytesIO as _BytesIO

        from reportlab.lib.utils import ImageReader as _ImageReader

        pad = 10
        image = _ImageReader(_BytesIO(wx_crop["png"]))
        aspect = wx_crop["width"] / max(1, wx_crop["height"])
        draw_w = half_w - 2 * pad
        draw_h = min(right_h - 34, draw_w / aspect)
        draw_w = min(draw_w, draw_h * aspect)
        canvas.setFillColor(colors.white)
        canvas.roundRect(right_x + pad, y - 24 - draw_h - 4, draw_w + 8, draw_h + 8, 3, stroke=0, fill=1)
        canvas.drawImage(image, right_x + pad + 4, y - 24 - draw_h,
                         width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
    else:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        canvas.drawString(right_x + 14, y - right_h / 2,
                          "Source weather page unavailable for cropping - see the uploaded CFP.")

    y = columns_bottom - 10

    # WAFC fixed-time products strip.
    strip_top = 30 + strip_h
    strip_h = strip_top - 30
    inner = panel(canvas, MARGIN, 30, full_w, strip_h, title="PACKAGE WAFC FIXED-TIME PRODUCTS", accent=WEATHER_AMBER, title_colour=None)
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
    inner = panel(canvas, MARGIN, 30, seq_w, seq_h, title="COMMUNICATION SEQUENCE", accent=COMMS_TEAL, title_colour=None)
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


def draw_analysis_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
) -> None:
    """REV3 page 2 - CRITICAL ANALYSIS: the decision timeline over six prose
    verdict cards, every sentence composed from the same view the other
    surfaces print."""
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP-derived deterministic verdicts | no unsupported hazard inference",
        section_label="CRITICAL ANALYSIS",
    )
    canvas.bookmarkPage("sec_analysis")
    canvas.bookmarkPage("sec_time")
    y = content_top - 4

    # FLIGHT-PHASE DECISION TIMELINE band - REV3 measured: a slim strip
    # hugging the header rule.
    strip_h = 56.0
    inner = panel(canvas, MARGIN, y - strip_h, width - 2 * MARGIN, strip_h,
                  title="FLIGHT-PHASE DECISION TIMELINE", accent=PANEL, title_colour=TEXT)
    _timeline(canvas, MARGIN + 25, y - strip_h + 11, width - 2 * MARGIN - 50,
              _route_anchor_entries(flight, briefing))
    y -= strip_h + 16

    fuel_summary = flight.get("fuel_summary") or {}
    masses = fuel_summary.get("masses_kg") or {}
    performance = flight.get("performance") or {}
    rows_data = fuel_summary.get("rows") or {}
    edto_view = briefing.get("edto") or {}
    hazards = briefing.get("hazards") or {}
    cards = hazards.get("sigmet_cards") or []
    ledger_rows = hazards.get("coverage_ledger") or []
    deferred = flight.get("deferred_items") or []
    departure_panel = briefing.get("departure") or {}
    destination_panel = briefing.get("destination") or {}
    alternates = flight.get("alternates") or []

    controlling = performance.get("controlling_rtow_kg")
    ptow = masses.get("ptow")
    margin_kg = (controlling - ptow) if controlling and ptow else None
    tanks = (rows_data.get("fuel_in_tanks") or {}).get("fuel_kg")
    reqmt = (rows_data.get("flt_plan_reqmt") or {}).get("fuel_kg")
    excess = (rows_data.get("excess_fuel") or {}).get("fuel_kg")
    perf_text = " ".join(part for part in (
        f"RTOW {controlling:,} kg." if controlling else "RTOW not derived - review CFP performance page.",
        f"PTOW {ptow:,} kg gives {margin_kg:,} kg margin." if margin_kg is not None else None,
        (
            f"Fuel in tanks {'equals' if tanks == reqmt else 'exceeds'} the {reqmt:,} kg flight-plan requirement; "
            f"excess fuel is {excess or 0:,} kg."
            if tanks is not None and reqmt is not None else None
        ),
        f"A 1,000 kg ZFW change moves burn {flight.get('zfw_change_burn_kg_per_1000')} kg." if flight.get("zfw_change_burn_kg_per_1000") else None,
        (
            "Excess composition: "
            + "; ".join(
                f"{item['label']} {item['fuel_kg']:,} kg"
                for item in fuel_summary.get("excess_breakdown") or []
                if item.get("fuel_kg")
            ) + "."
            if any(item.get("fuel_kg") for item in fuel_summary.get("excess_breakdown") or [])
            else None
        ),
    ) if part)

    refs = [
        f"{item.get('item_type')} {item.get('reference')}"
        if str(item.get('reference') or '').strip() not in ('', 'UNSPECIFIED')
        else str(item.get('item_type') or '')
        for item in deferred
    ]
    seen_refs: list[str] = []
    for ref in refs:
        if ref and ref not in seen_refs:
            seen_refs.append(ref)
    cddl_text = (
        f"CFP page 1 carries {len(deferred)} technical item{'s' if len(deferred) != 1 else ''}: "
        f"{', '.join(seen_refs[:6])}. Execution remarks stay with the printed source; missing "
        "seal dimensions or identity are never guessed when determining any penalty."
        if deferred else "No deferred technical item is printed on CFP page 1."
    )

    edto_rows = {row.get("label"): row.get("value") for row in edto_view.get("operational_rows") or []}
    edto_text = " · ".join(part for part in (
        str(edto_rows.get("SECTOR 1") or edto_rows.get("ENTRY / EXIT") or ""),
        str(edto_rows.get("EDTO ALTN") or ""),
        str(edto_rows.get("FUEL") or ""),
    ) if part) or "No EDTO facts were derived from this CFP - review page 1 directly."

    hazard_bits = []
    for card in cards[:3]:
        hazard_bits.append(f"{card.get('name')}: {card.get('screening')}")
    gaps = [row.get("label") for row in ledger_rows if str(row.get("status")) == "unavailable"]
    if gaps:
        hazard_bits.append(f"{'/'.join(gaps)} carry no data in this CFP - coverage gaps, not NIL findings.")
    hazards_text = " ".join(hazard_bits) or "No enroute SIGMET is printed in this CFP."

    primary_alternate = alternates[0] if alternates else {}
    airports_text = " ".join(part for part in (
        f"{theme.airport_code_label(departure_panel.get('icao') or flight.get('departure'))}: RWY {departure_panel.get('runway')}." if departure_panel.get("runway") else None,
        f"{theme.airport_code_label(destination_panel.get('icao') or flight.get('destination'))}: RWY {destination_panel.get('runway')}." if destination_panel.get("runway") else None,
        (
            f"{primary_alternate.get('airport')} is the CFP preferred alternate"
            + (f" on RWY {primary_alternate.get('runway')}" if primary_alternate.get("runway") else "")
            + (f" ({primary_alternate.get('approach')})." if primary_alternate.get("approach") else ".")
            if primary_alternate else None
        ),
    ) if part) or "Airport basis requires review - see the airports page."

    terrain_text = str((briefing.get("terrain") or {}).get("summary") or "")
    depress_findings = [f for f in findings if f.get("engine") == "depressurisation"]
    if depress_findings:
        terrain_text += ". " + str(depress_findings[0].get("summary") or "")

    cells = (
        ("PERFORMANCE / FUEL", DEPARTURE, perf_text),
        ("CDDL / CDL", WEATHER_AMBER, cddl_text),
        ("EDTO / ENROUTE AIRPORT", EDTO_GREEN, edto_text),
        ("OPERATIONAL HAZARDS", WEATHER_AMBER, hazards_text),
        ("AIRPORTS / ALTERNATE", DESTINATION, airports_text),
        ("HIGH TERRAIN / VWS", TERRAIN_ORANGE, terrain_text),
    )
    # REV3 measured grid: 22pt gutter, 16pt row gaps, body on a 1.2 pitch.
    col_w = (width - 2 * MARGIN - 22) / 2
    card_h = (y - 34 - 2 * 16) / 3
    body_step = round(T_SMALL * 1.2, 2)
    for index, (title, accent, text) in enumerate(cells):
        col = index % 2
        row = index // 2
        cx = MARGIN + col * (col_w + 22)
        cy = y - (row + 1) * card_h - row * 16
        inner = rev3_card(canvas, cx, cy, col_w, card_h, title=title, accent=accent)
        ix, iy, iw, ih = inner
        line_y = cy + card_h - 34
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        for line in _wrap(text, SANS, T_SMALL, iw)[:6]:
            canvas.drawString(ix, line_y, line)
            line_y -= body_step


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
    # REV3 canon order (boss, 20 Aug): dashboard, critical analysis, CDDL/CDL,
    # EDTO, airports, weather, terrain - the tab strip's seven sections. The
    # old time-gates, performance and comms pages fold into pages 1, 2 and 4;
    # profile chart annexes follow the terrain page when charts are served.
    page_count = 6 + mel_page_count + len(chart_images)
    profile_page_numbers = {
        str(image.get("chart_number")): 7 + mel_page_count + index
        for index, image in enumerate(chart_images)
    }

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(str(output_path), pagesize=PAGE_SIZE)
    canvas.setTitle(f"Flight Briefing {theme.display_flight_number(flight)} {theme.header_date_label(flight)}")

    draw_overview_page(canvas, flight, briefing, findings, page_number=1, page_count=page_count)
    canvas.showPage()
    draw_analysis_page(canvas, flight, briefing, findings, page_number=2, page_count=page_count)
    canvas.showPage()
    for index, deferred_page in enumerate(deferred_pages):
        draw_mel_cdl_page(
            canvas, flight, briefing, findings,
            page_number=3 + index,
            page_count=page_count,
            source_pdf_path=source_pdf_path,
            deferred_items=deferred_page,
            section_page_number=index + 1,
            section_page_count=mel_page_count,
        )
        canvas.showPage()
    alternates_page_number = 3 + mel_page_count
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
    draw_terrain_page(
        canvas, flight, briefing, findings, chart_images,
        page_number=alternates_page_number + 3,
        page_count=page_count, profile_page_numbers=profile_page_numbers,
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
