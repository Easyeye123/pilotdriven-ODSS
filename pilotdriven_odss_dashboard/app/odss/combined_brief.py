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

import hashlib
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
)
from .constants import format_actm
from .deferred_dispatch import (
    deferred_item_type_for_display,
    deferred_reference_for_display,
    deferred_source_declaration_for_display,
)

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
# Palette — measured directly from the REV3 vector fills.  Dashboard, deep
# analysis and standard analysis page families each use their own published
# tokens; page chrome selects the family, while the drawing helpers stay
# content-agnostic.
# ---------------------------------------------------------------------------
BG = colors.HexColor("#07131f")
PANEL = colors.HexColor("#102336")
ELEVATED = colors.HexColor("#142e45")
BORDER = colors.HexColor("#27445c")
DEEP_BG = colors.HexColor("#08111c")
DEEP_PANEL = colors.HexColor("#0e1b2a")
DEEP_ELEVATED = colors.HexColor("#13263a")
DEEP_BORDER = colors.HexColor("#23374d")
ACCENT = colors.HexColor("#2f80ed")
SECTION_BLUE = colors.HexColor("#35a6dc")
DEPARTURE = colors.HexColor("#35a6dc")
DESTINATION = colors.HexColor("#9850e6")
EDTO_GREEN = colors.HexColor("#2ecf83")
WEATHER_AMBER = colors.HexColor("#f3c94c")
COMMS_TEAL = colors.HexColor("#2dcecf")
TERRAIN_ORANGE = colors.HexColor("#f29a4a")
CRITICAL = colors.HexColor("#eb5757")
DASH_BLUE = colors.HexColor("#2d9cdb")
DASH_GREEN = colors.HexColor("#27ae60")
DASH_ORANGE = colors.HexColor("#f2994a")
DASH_PURPLE = colors.HexColor("#9b51e0")
DASH_RED = colors.HexColor("#eb5757")
TEXT = colors.HexColor("#f3f7fa")
TEXT_SECONDARY = colors.HexColor("#9ab0c1")
TEXT_MUTED = colors.HexColor("#6f8095")


def _page_colour(canvas, name: str, fallback):
    return getattr(canvas, f"_brief_{name}_colour", fallback)

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

# Canonical cardinalities preserve the primary-page geometry. Anything above
# them gets a deterministic continuation page in the same section.
EDTO_CARDS_PER_PAGE = 3
EDTO_CARD_HEIGHT = 178.0
NON_EDTO_CLASSIFICATION_CARD_HEIGHT = 78.0
AIRPORT_OPERATIONAL_PANELS_PER_PAGE = 5
AIRPORT_ROUTE_PROFILE_ROWS_PER_PAGE = 38
STATION_CARD_LINE_HEIGHT = 9.5
ANALYSIS_COMMUNICATION_LINE_HEIGHT = 10.5
ANALYSIS_COMMUNICATION_ROW_GAP = 8.0
# Conservative usable height inside a DECISION ANALYSIS continuation panel.
# Pagination measures wrapped text against this budget; it never assumes a
# fixed number of communication rows.
ANALYSIS_COMMUNICATION_HEIGHT_BUDGET = 420.0
DETAIL_LINE_HEIGHT = 9.6
DETAIL_ROW_GAP = 2.2
DETAIL_PAGE_LINE_BUDGET = 39
SIGMET_CARDS_PER_PAGE = 2
VAA_ADVISORIES_PER_PAGE = 2
WAFC_CHARTS_PER_PAGE = 3

# Part of the cached-report identity. Bump whenever the publication contract
# changes so an analysis created before a deployment cannot keep serving an
# older PDF from persistent report storage.
COMBINED_BRIEFING_SCHEMA_VERSION = "2026-08-23-flow-round-v8"


_FIT_FLOOR = T_MICRO


def _fit(
    text: str,
    font: str,
    size: float,
    max_width: float,
    *,
    floor: float = _FIT_FLOOR,
) -> float:
    """Largest size <= requested that keeps text inside max_width (rule 8:
    nothing may overlap or overrun its box)."""
    width = pdfmetrics.stringWidth(text, font, size)
    if width <= max_width or width <= 0:
        return size
    return max(floor, size * max_width / width)


def _draw_string_fitted(
    canvas,
    x,
    y,
    text,
    font,
    size,
    max_width,
    colour,
    *,
    floor: float = _FIT_FLOOR,
):
    """Draw text inside max_width, shrinking to the floor and then
    TRUNCATING — a string may lose its tail but may never run under a
    neighbouring element (08 Aug audit: floor-clamped copy crossed columns)."""
    value = str(text)
    fitted = _fit(value, font, size, max_width, floor=floor)
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
    # "STATUS", not "TECH STATUS" (boss, 20 Aug video: "just put status").
    ("STATUS", "sec_mel_cdl"),
    ("EDTO", "sec_alternates"),
    ("AIRPORTS", "sec_airports"),
    ("WEATHER", "sec_hazard"),
    ("TERRAIN", "sec_terrain"),
)


def rev3_card(canvas, x, y, w, h, *, title: str, accent, title_colour=None) -> tuple[float, float, float, float]:
    """Draw a family-coloured card with the measured REV3 geometry."""
    canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
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
    page_family: str = "standard",
) -> float:
    """Background, header band, footer, SOURCE line. Returns content top y."""
    register_fonts()
    width, height = PAGE_SIZE
    deep_family = page_number == 1 or page_family == "deep"
    canvas._brief_dashboard_palette = page_number == 1
    canvas._brief_bg_colour = DEEP_BG if deep_family else BG
    canvas._brief_panel_colour = DEEP_PANEL if deep_family else PANEL
    canvas._brief_elevated_colour = (
        DEEP_ELEVATED if deep_family else ELEVATED
    )
    canvas._brief_border_colour = DEEP_BORDER if deep_family else BORDER
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
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
        header_section_label = (section_label or "FLIGHT BRIEFING").upper()
        section_label_left = (
            width
            - MARGIN
            - pdfmetrics.stringWidth(
                header_section_label,
                SANS_BOLD,
                9.3,
            )
        )
        utc_available_width = max(60.0, section_label_left - 454.0 - 10.0)
        utc_display = utc_line
        if (
            pdfmetrics.stringWidth(utc_display, UTIL_MONO, 8.5)
            > utc_available_width
        ):
            utc_display = (
                utc_line.replace("UTC DEP ", "")
                .replace("-> ARR ", " -> ")
            )
        utc_size = 8.5
        while (
            utc_size > 7.2
            and pdfmetrics.stringWidth(
                utc_display,
                UTIL_MONO,
                utc_size,
            ) > utc_available_width
        ):
            utc_size -= 0.2
        if (
            pdfmetrics.stringWidth(utc_display, UTIL_MONO, utc_size)
            > utc_available_width
        ):
            raise ValueError(
                "UTC header schedule cannot fit beside the section label "
                "without truncation"
            )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(UTIL_MONO, utc_size)
        canvas.drawString(454, height - 58.5, utc_display)
        page_label = f"Page {page_number} of {page_count}"
        page_label_left = (
            width
            - MARGIN
            - pdfmetrics.stringWidth(page_label, SANS, 7.4)
        )
        local_available_width = max(60.0, page_label_left - 454.0 - 10.0)
        local_display = local_line
        if (
            pdfmetrics.stringWidth(local_display, UTIL_MONO, 7.9)
            > local_available_width
        ):
            local_display = (
                local_line.replace("LT ", "")
                .replace("  ->  ", " -> ")
            )
        local_size = 7.9
        while (
            local_size > 7.2
            and pdfmetrics.stringWidth(
                local_display,
                UTIL_MONO,
                local_size,
            ) > local_available_width
        ):
            local_size -= 0.2
        if (
            pdfmetrics.stringWidth(local_display, UTIL_MONO, local_size)
            > local_available_width
        ):
            raise ValueError(
                "Local-time header schedule cannot fit beside the page label "
                "without truncation"
            )
        canvas.setFont(UTIL_MONO, local_size)
        canvas.drawString(454, height - 73.5, local_display)
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
        canvas.setFillColor(_page_colour(canvas, "bg", BG))
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
        # Keep the approved return affordance visible but compact (boss,
        # 21 Aug: "back to overview is good"; "button [is] a bit too big").
        # It sits below the logo, clear of the BLOCK / identity columns.
        return_text = "BACK TO OVERVIEW"
        return_text_size = 7.2
        return_h = 16.0
        return_w = (
            pdfmetrics.stringWidth(
                return_text,
                SANS_BOLD,
                return_text_size,
            )
            + 18.0
        )
        return_x = MARGIN
        return_y = height - 82.0
        canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
        canvas.setLineWidth(0.7)
        canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
        canvas.roundRect(
            return_x,
            return_y,
            return_w,
            return_h,
            return_h / 2,
            stroke=1,
            fill=1,
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS_BOLD, return_text_size)
        canvas.drawCentredString(
            return_x + return_w / 2,
            return_y + 5.2,
            return_text,
        )
        canvas.linkRect(
            "",
            "sec_overview",
            (
                return_x,
                return_y,
                return_x + return_w,
                return_y + return_h,
            ),
            relative=0,
            thickness=0,
        )

    # Header rule - REV3 measured: 88pt below the page top on analysis pages.
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.setLineWidth(0.8)
    rule_y = (top - 48) if page_number == 1 else (height - 88)
    canvas.line(MARGIN, rule_y, width - MARGIN, rule_y)

    tabs_offset = 0.0
    if show_tabs:
        tabs_offset = 20.0
        tab_y = top - 64
        tab_x = MARGIN
        # A NON-EDTO flight carries no EDTO tab (boss, 21 Aug: "there's no
        # EDTO for this flight; that should not be [there]"). Review states
        # keep the tab - an unresolved classification stays visible.
        non_edto = _edto_classification(flight).startswith("NON")
        tabs = tuple(
            (label, bookmark)
            for label, bookmark in REV3_TABS
            if not (non_edto and label == "EDTO")
        )
        for label, bookmark in tabs:
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
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
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
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
    canvas.setFont(SANS_BOLD, T_CARD_HEAD)
    canvas.drawString(MARGIN + 12, y - bar_h + 6.6, text.upper())
    return y - bar_h - 10


def panel(canvas, x, y, w, h, *, title, accent, title_colour=colors.white) -> tuple[float, float, float, float]:
    """REV3 canon card (boss, 20 Aug: "this look"): panel fill with a thin
    accent TOP border and the title inside as coloured text - the full-width
    coloured title bands are retired. Measured from the boss's REV3 file:
    #0E1B2A card, ~4pt accent bar, title text in the accent colour.
    Returns the inner content box (x, y, w, h)."""
    panel_colour = _page_colour(canvas, "panel", PANEL)
    elevated_colour = _page_colour(canvas, "elevated", ELEVATED)
    if accent == PANEL:
        accent = panel_colour
    elif accent == ELEVATED:
        accent = elevated_colour
    canvas.setFillColor(panel_colour)
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    canvas.setFillColor(accent)
    canvas.rect(x, y + h - 3, w, 3, stroke=0, fill=1)
    title_text_colour = (
        accent
        if accent not in (panel_colour, elevated_colour)
        else TEXT
    )
    _draw_string_fitted(
        canvas, x + 10, y + h - 16.3, str(title).upper(),
        SANS_BOLD, T_CARD_HEAD, w - 20, title_text_colour,
    )
    return (x + 10, y + 6, w - 20, h - 24)


def stat_card(canvas, x, y, w, h, *, label, value, caption, accent, mono=True) -> None:
    """Spec stat card: thin accent strip on top, label, big value, caption."""
    canvas.setFillColor(_page_colour(canvas, "elevated", ELEVATED))
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
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
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawCentredString(x - w / 2, y + 3.4, label)
    if destination:
        canvas.linkRect("", destination, (x - w, y, x, y + 12), relative=0, thickness=0)


def review_line(canvas, x, y, text) -> None:
    canvas.setFillColor(DASH_ORANGE)
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
    reference = deferred_reference_for_display(item.get("reference"))
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
        reference = deferred_reference_for_display(item.get("reference"))
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
    # The chip says what is held, not bare labels (boss, 21 Aug: "I click, it
    # should come to MEL... not search my eyes down"), and a bare declaration
    # never prints None/UNSPECIFIED in place of its missing reference.
    deferred_line = (
        "; ".join(
            " · ".join(part for part in (
                " ".join(p for p in (
                    deferred_item_type_for_display(item.get("item_type")),
                    deferred_reference_for_display(item.get("reference")),
                ) if p),
                str(item.get("description") or "").strip() or None,
            ) if part)
            for item in deferred[:2]
        )
        + (f"; +{len(deferred) - 2} more" if len(deferred) > 2 else "")
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
    # When CFP page 1 itemises the whole excess as TANKER, the row carries
    # the CFP's own word (boss, 21 Aug: excess here IS tankering).
    nonzero_excess = [
        item for item in fuel_summary.get("excess_breakdown") or []
        if item.get("fuel_kg")
    ]
    excess_label = (
        "TANKER"
        if nonzero_excess and all(item.get("label") == "TANKER" for item in nonzero_excess)
        else "EXCESS"
    )
    return [
        ("GROUND", f"{ground:,} NM" if ground else "--"),
        ("BURNOFF", timed("burnoff")),
        ("FPL REQ", timed("flt_plan_reqmt")),
        ("FUEL IN TANKS", timed("fuel_in_tanks")),
        ("PZFW", mass("pzfw")),
        ("PTOW", mass("ptow")),
        ("PLWT", mass("plwt")),
        (excess_label, timed("excess_fuel")),
    ]


def _pertinent_notam_lines(
    panel: dict[str, Any] | None,
    *,
    skip_notam_id: str | None,
    limit: int,
) -> list[str]:
    """The airport panel's pertinent NOTAM summary lines (id + wording with
    its times), skipping the one already printed as the card highlight."""
    lines: list[str] = []
    for entry in (panel or {}).get("card_summary_lines") or []:
        if str(entry.get("kind") or "") != "notam":
            continue
        notam_id = str(entry.get("notam_id") or entry.get("label") or "").strip()
        if skip_notam_id and notam_id == skip_notam_id:
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{notam_id} {text}".strip())
        if len(lines) >= limit:
            break
    return lines


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
    """
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
    # The p2 PERFORMANCE / FUEL decision card returns to the page-1 summary
    # rather than linking to its own page. Keep a distinct destination name
    # so the physical navigation contract remains explicit and testable.
    canvas.bookmarkPage("sec_performance_summary")
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
    overview = briefing.get("overview") or {}
    overview_departure = overview.get("departure") or {}
    overview_destination = overview.get("destination") or {}
    identity = briefing.get("flight_identity") or {}
    airport_panels = briefing.get("airport_operational_panels") or []

    def panel_for(role: str, icao: str) -> dict[str, Any]:
        for candidate in airport_panels:
            if role in (candidate.get("role_keys") or [candidate.get("role_key"), candidate.get("role")]):
                return candidate
        for candidate in airport_panels:
            if str(candidate.get("icao") or "").upper() == icao.upper():
                return candidate
        return {}

    def draw_pertinent(x: float, row_y: float, width: float, floor_y: float, lines: list[str]) -> float:
        # Pertinent NOTAMs with their times fill the card's empty space
        # (boss, 21 Aug R2-9); each line stops at the card floor, never over it.
        # Needs the label plus at least one wrapped line above the floor;
        # a label with nothing under it is worse than the empty space.
        if not lines or row_y - 24 < floor_y:
            return row_y
        row_y -= 5
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(x, row_y, "PERTINENT")
        row_y -= 9
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 7.2)
        for line in lines:
            for wrapped in _wrap(line, SANS, 7.2, width)[:2]:
                if row_y - 8.6 < floor_y:
                    return row_y
                canvas.drawString(x, row_y, wrapped)
                row_y -= 8.6
            row_y -= 1.5
        return row_y

    # The PRIORITY strip is gone (boss, 21 Aug: "don't waste words like this
    # — remove all this"); the reclaimed band goes to the content cards.
    row_gap = 10.0
    bottom = 30.0
    row2_h = 207.0
    row1_h = y - bottom - row2_h - row_gap
    # REV3 keeps the airport cards compact and gives the filed route the
    # majority of the row. Destination is slightly wider because alternate
    # planning is printed there as well.
    departure_w = full_w * 0.18
    destination_w = full_w * 0.20
    centre_x = MARGIN + departure_w + 10
    centre_w = full_w - departure_w - destination_w - 20
    right_x = MARGIN + full_w - destination_w

    def kv_rows(
        ix,
        top,
        iw,
        rows,
        *,
        mono_value=True,
        row_h=13.0,
        value_offset=78.0,
        font_size=T_MICRO,
        fit_floor=_FIT_FLOOR,
        dynamic_value_offset=False,
    ):
        row_y = top
        for label, value in rows:
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS, font_size)
            canvas.drawString(ix, row_y, str(label))
            canvas.setFillColor(TEXT)
            canvas.setFont(MONO_BOLD if mono_value else SANS_BOLD, font_size)
            row_value_offset = (
                max(
                    value_offset,
                    pdfmetrics.stringWidth(str(label), SANS, font_size) + 4,
                )
                if dynamic_value_offset
                else value_offset
            )
            _draw_string_fitted(
                canvas,
                ix + row_value_offset,
                row_y,
                str(value),
                MONO_BOLD if mono_value else SANS_BOLD,
                font_size,
                iw - row_value_offset - 4,
                TEXT,
                floor=fit_floor,
            )
            row_y -= row_h
        return row_y

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

    def schedule_display(station: dict[str, Any], fallback_utc: str) -> str:
        schedule = station.get("schedule") or {}
        utc_display = str(schedule.get("display_utc") or fallback_utc or "--")
        utc_match = re.search(r"(\d{4}Z)$", utc_display)
        if utc_match:
            utc_display = utc_match.group(1)
        local_segment = theme.local_time_segment(
            station.get("icao"), schedule.get("scheduled_utc")
        )
        local_match = re.search(r"\b\d{2} [A-Z]{3} (\d{4}) UTC", local_segment or "")
        return (
            f"{utc_display} / {local_match.group(1)} LT"
            if local_match
            else utc_display
        )

    def compact_forecast(station: dict[str, Any]) -> str:
        forecast = station.get("forecast_at_reference") or {}
        return str(forecast.get("applicable_conditions") or "").strip()

    def draw_card_bulletins(panel_data: dict[str, Any], x: float, row_y: float, width: float, floor_y: float) -> tuple[float, bool]:
        # The actual CFP bulletins ride on the card (18 Aug ruling; his GPT's
        # p1 reference prints PLAN / SCHEDULE / METAR / TAF / PERTINENT) —
        # they also fill the space he flagged empty on 21 Aug.
        weather = panel_data.get("weather") or {}
        drew_any = False
        for label in ("metar", "taf"):
            value = str(weather.get(label) or "").strip().splitlines()[0] if weather.get(label) else ""
            if not value or row_y < floor_y + 22:
                continue
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawString(x, row_y, label.upper())
            row_y -= 11
            canvas.setFillColor(TEXT)
            canvas.setFont(MONO, T_MICRO)
            for wrapped in _wrap(value, MONO, T_MICRO, width)[:2]:
                if row_y < floor_y + 10:
                    break
                canvas.drawString(x, row_y, wrapped)
                row_y -= 9.4
            row_y -= 5
            drew_any = True
        return row_y, drew_any

    def operational_highlight(station: dict[str, Any]) -> tuple[str, str]:
        highlight = station.get("primary_operational_highlight") or {}
        family = str(highlight.get("signal_family") or "")
        label = (
            "RETURN APPROACH"
            if family == "approach_navaid"
            else "RUNWAY STATUS"
            if family in {"runway_closure", "runway_restriction"}
            else "OPERATIONAL NOTE"
        )
        return label, str(highlight.get("text") or "").strip()

    # --- Row 1: DEPARTURE | CFP P1 ROUTE / LEVELS + ANALYSIS OVERLAY | DESTINATION
    row1_top = y
    dep_inner = panel(
        canvas,
        MARGIN,
        row1_top - row1_h,
        departure_w,
        row1_h,
        title="DEPARTURE",
        accent=DASH_BLUE,
        title_colour=None,
    )
    ix = dep_inner[0]
    row_y = row1_top - 30
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 14.0)
    departure_icao = str(
        overview_departure.get("icao")
        or departure_panel.get("icao")
        or flight.get("departure")
        or "----"
    )
    canvas.drawString(ix, row_y, departure_icao)
    departure_identity = theme.airport_code_label(departure_icao)
    if departure_identity != departure_icao:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix, row_y - 12, departure_identity)
    row_y -= 30
    departure_plan = overview_departure.get("plan") or {}
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix, row_y, "PLAN")
    row_y -= 11
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, T_MICRO)
    _draw_string_fitted(
        canvas,
        ix,
        row_y,
        str(
            departure_plan.get("display")
            or departure_panel.get("runway")
            or "Runway review"
        ),
        MONO_BOLD,
        T_MICRO,
        departure_w - 28,
        TEXT,
    )
    row_y -= 15
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix, row_y, "SCHEDULE")
    row_y -= 11
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, T_MICRO)
    canvas.drawString(
        ix,
        row_y,
        schedule_display(overview_departure, _clock_at(flight, 0)),
    )
    row_y -= 16
    row_y, dep_bulletins_drawn = draw_card_bulletins(departure_panel, ix, row_y, departure_w - 28, row1_top - row1_h)
    forecast = compact_forecast(overview_departure)
    # A held METAR/TAF states the weather in its own words; the decoded
    # forecast block and synthesised window prose print only when no
    # bulletin is held (18 Aug raw-bulletin ruling; his GPT card layout).
    if not dep_bulletins_drawn:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, "FORECAST AT ETD")
        row_y -= 11
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        if forecast:
            for wrapped in _wrap(forecast, SANS, T_MICRO, departure_w - 28)[:3]:
                canvas.drawString(ix, row_y, wrapped)
                row_y -= 9.4
        else:
            _draw_string_fitted(
                canvas,
                ix,
                row_y,
                weather_fallback(departure_panel),
                SANS,
                T_MICRO,
                departure_w - 28,
                TEXT_SECONDARY,
            )
            row_y -= 9.4
    highlight_label, highlight_text = operational_highlight(overview_departure)
    if highlight_text and row_y > row1_top - row1_h + 32:
        row_y -= 7
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, highlight_label)
        row_y -= 11
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        for wrapped in _wrap(
            highlight_text, SANS, T_MICRO, departure_w - 28
        )[:4]:
            canvas.drawString(ix, row_y, wrapped)
            row_y -= 9.4
    row_y = draw_pertinent(
        ix,
        row_y,
        departure_w - 28,
        row1_top - row1_h + 6,
        _pertinent_notam_lines(
            panel_for("departure", str(overview_departure.get("icao") or departure_panel.get("icao") or "")),
            skip_notam_id=str((overview_departure.get("primary_operational_highlight") or {}).get("notam_id") or "") or None,
            limit=2,
        ),
    )
    primary_alternate = alternates[0] if alternates else {}
    dest_inner = panel(
        canvas,
        right_x,
        row1_top - row1_h,
        destination_w,
        row1_h,
        title="DESTINATION",
        accent=DASH_PURPLE,
        title_colour=None,
    )
    ix2 = dest_inner[0]
    row_y2 = row1_top - 30
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 14.0)
    destination_icao = str(
        overview_destination.get("icao")
        or destination_panel.get("icao")
        or flight.get("destination")
        or "----"
    )
    canvas.drawString(ix2, row_y2, destination_icao)
    destination_identity = theme.airport_code_label(destination_icao)
    if destination_identity != destination_icao:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix2, row_y2 - 12, destination_identity)
    row_y2 -= 30
    destination_plan = overview_destination.get("plan") or {}
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS_BOLD, T_MICRO)
    canvas.drawString(ix2, row_y2, "PLAN / SCHEDULE")
    row_y2 -= 11
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, T_MICRO)
    _draw_string_fitted(
        canvas,
        ix2,
        row_y2,
        str(
            destination_plan.get("display")
            or destination_panel.get("runway")
            or "Runway review"
        ),
        MONO_BOLD,
        T_MICRO,
        destination_w - 28,
        TEXT,
    )
    row_y2 -= 11
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    canvas.drawString(
        ix2,
        row_y2,
        schedule_display(
            overview_destination,
            theme.utc_hhmm(flight.get("scheduled_arrival_utc")) or "--",
        ),
    )
    # The arrival line states its basis and reads larger (boss, 21 Aug
    # R2-14: "is it based on the flight time?... too small").
    row_y2 -= 14
    eta_label = str(identity.get("eta_hhmm") or "").strip()
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, 9.6)
    canvas.drawString(ix2, row_y2, f"ETA {eta_label}Z" if eta_label else "ETA --")
    row_y2 -= 10
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 7.2)
    for wrapped in _wrap(str(identity.get("arrival_basis") or ""), SANS, 7.2, destination_w - 28)[:2]:
        canvas.drawString(ix2, row_y2, wrapped)
        row_y2 -= 9.0
    row_y2 -= 6
    row_y2, dest_bulletins_drawn = draw_card_bulletins(destination_panel, ix2, row_y2, destination_w - 28, row1_top - row1_h)
    forecast2 = compact_forecast(overview_destination)
    if not dest_bulletins_drawn:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix2, row_y2, "FORECAST AT ETA")
        row_y2 -= 11
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        if forecast2:
            for wrapped in _wrap(forecast2, SANS, T_MICRO, destination_w - 28)[:3]:
                canvas.drawString(ix2, row_y2, wrapped)
                row_y2 -= 9.4
        else:
            _draw_string_fitted(
                canvas,
                ix2,
                row_y2,
                weather_fallback(destination_panel),
                SANS,
                T_MICRO,
                destination_w - 28,
                TEXT_SECONDARY,
            )
            row_y2 -= 9.4
    dest_highlight_label, dest_highlight_text = operational_highlight(
        overview_destination
    )
    if dest_highlight_text:
        row_y2 -= 5
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix2, row_y2, dest_highlight_label)
        row_y2 -= 11
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        for wrapped in _wrap(
            dest_highlight_text, SANS, T_MICRO, destination_w - 28
        )[:3]:
            canvas.drawString(ix2, row_y2, wrapped)
            row_y2 -= 9.4
    row_y2 = draw_pertinent(
        ix2,
        row_y2,
        destination_w - 28,
        row1_top - row1_h + 40,
        _pertinent_notam_lines(
            panel_for("destination", destination_icao),
            skip_notam_id=str((overview_destination.get("primary_operational_highlight") or {}).get("notam_id") or "") or None,
            limit=2,
        ),
    )
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
    for wrapped in _wrap(altn_line or "Alternate planning data requires review.", MONO, T_MICRO, destination_w - 28)[:2]:
        canvas.drawString(ix2, row_y2, wrapped)
        row_y2 -= 9.4

    centre_inner = panel(canvas, centre_x, row1_top - row1_h, centre_w, row1_h,
                         title="CFP P1 - ROUTE / LEVELS + ANALYSIS OVERLAY",
                         accent=ACCENT, title_colour=None)
    cx0 = centre_inner[0]
    text_w = centre_w * 0.69
    map_w = centre_w - text_w - 34
    row_y3 = row1_top - 28
    shared_chips = list(overview.get("chips") or [])
    chips = (
        [
            {
                "key": str(chip.get("key") or ""),
                "label": str(chip.get("label") or ""),
            }
            for chip in shared_chips
            if str(chip.get("label") or "").strip()
        ]
        if shared_chips
        else [
            {"key": key, "label": label}
            for key, label in (
                (
                    "edto_rvsm",
                    "EDTO / RVSM"
                    if "EDTO"
                    in str(fuel_summary.get("source_classification") or "").upper()
                    else None,
                ),
                (
                    "cost_index",
                    f"CI {flight.get('cost_index')}"
                    if flight.get("cost_index") is not None
                    else None,
                ),
            )
            if label
        ]
    )
    chip_x = cx0
    for chip in chips:
        chip_label = chip["label"]
        chip_colour = {
            "route_identifier": ACCENT,
            "edto_rvsm": DASH_GREEN,
            "cost_index": COMMS_TEAL,
            "apd_percent": DASH_ORANGE,
        }.get(chip.get("key"), ACCENT)
        chip_w = pdfmetrics.stringWidth(chip_label, SANS_BOLD, T_MICRO) + 14
        canvas.setStrokeColor(chip_colour)
        canvas.setLineWidth(0.8)
        canvas.roundRect(chip_x, row_y3 - 4, chip_w, 12.5, 6.2, stroke=1, fill=0)
        canvas.setFillColor(chip_colour)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawCentredString(chip_x + chip_w / 2, row_y3, chip_label)
        chip_x += chip_w + 6
    row_y3 -= 16
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, T_MICRO)
    canvas.drawString(cx0, row_y3, "CFP ROUTE")
    row_y3 -= 10
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, T_MICRO)
    route_lines, profile_lines, route_overflows = _overview_route_layout(flight)
    for wrapped in route_lines[:2]:
        canvas.drawString(cx0, row_y3, wrapped)
        row_y3 -= 9.4
    if len(route_lines) == 3:
        canvas.drawString(cx0, row_y3, route_lines[2])
        row_y3 -= 9.4
    elif len(route_lines) > 3:
        # Never cut the route silently: the compact row keeps whole tokens
        # and points at the verbatim block on the airports page.
        pointer = "» FULL ROUTE: AIRPORTS PAGE"
        pointer_w = pdfmetrics.stringWidth(pointer, SANS_BOLD, T_MICRO)
        remainder = " ".join(route_lines[2:])
        shown = _wrap(remainder, MONO, T_MICRO, text_w - pointer_w - 8)[0]
        canvas.drawString(cx0, row_y3, shown)
        canvas.setFillColor(ACCENT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(cx0 + text_w - pointer_w, row_y3, pointer)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        row_y3 -= 9.4
    row_y3 -= 3
    if profile_lines:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(cx0, row_y3, "PLANNED LEVEL PROFILE")
        row_y3 -= 10
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        for line in profile_lines[:1]:
            canvas.drawString(cx0, row_y3, line)
            row_y3 -= 9.4
        if len(profile_lines) == 2:
            canvas.drawString(cx0, row_y3, profile_lines[1])
            row_y3 -= 9.4
        elif len(profile_lines) > 2:
            pointer = "» FULL: AIRPORTS PAGE"
            pointer_w = pdfmetrics.stringWidth(pointer, SANS_BOLD, T_MICRO)
            # The chain has no spaces, so trim at slash boundaries to fit.
            shown = "".join(profile_lines[1:])
            while "/" in shown and pdfmetrics.stringWidth(shown, MONO, T_MICRO) > text_w - pointer_w - 8:
                shown = shown[:-1].rsplit("/", 1)[0] + "/"
            canvas.drawString(cx0, row_y3, shown)
            canvas.setFillColor(ACCENT)
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawString(cx0 + text_w - pointer_w, row_y3, pointer)
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(MONO, T_MICRO)
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
        canvas.setFillColor(DASH_GREEN)
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
    dest_has_bulletins = any(
        str((destination_panel.get("weather") or {}).get(key) or "").strip()
        for key in ("metar", "taf")
    )
    if not wx_bits and not forecast2 and not dest_has_bulletins:
        # No bulletin, no decoded forecast and no SIGMET cards: only then
        # does the operating-window fallback sentence print here in full -
        # a held METAR/TAF on the destination card already states the
        # weather in its own words (18 Aug raw-bulletin ruling).
        wx_bits = [weather_fallback(destination_panel)]
    if wx_bits:
        canvas.setFillColor(DASH_ORANGE)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(cx0, row_y3, "WX")
        wx_font = MONO if len(wx_bits) > 1 or "|" in wx_bits[0] else SANS
        _draw_string_fitted(canvas, cx0 + 34, row_y3, " | ".join(wx_bits), wx_font, T_MICRO, text_w - 34, TEXT_SECONDARY)
        row_y3 -= 11

    map_x = cx0 + text_w + 14
    map_h = row1_h - 72
    from .briefing import draw_route_map_pdf  # local import; briefing pulls widely

    canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
    canvas.roundRect(map_x, row1_top - 24 - map_h, map_w, map_h, 4, stroke=0, fill=1)
    route_map = dict(briefing.get("route_map") or {})
    map_points = list(route_map.get("points") or [])
    compact_label_indices: set[int] = (
        {0, len(map_points) - 1} if map_points else set()
    )
    first_edto_index = next(
        (
            index
            for index, point in enumerate(map_points)
            if point.get("role") == "edto"
        ),
        None,
    )
    if first_edto_index is not None:
        compact_label_indices.add(first_edto_index)
    compact_label_indices.update(
        index
        for index, point in enumerate(map_points)
        if point.get("role") == "terrain"
        or (
            isinstance(point.get("vws"), (int, float))
            and not isinstance(point.get("vws"), bool)
            and point.get("vws") > 4
        )
    )
    route_map["label_indices"] = sorted(compact_label_indices)
    draw_route_map_pdf(
        canvas,
        route_map,
        map_x,
        row1_top - 24 - map_h,
        map_w,
        map_h,
    )
    shared_timeline = list(overview.get("timeline") or [])
    timeline_colours = {
        "departure": DEPARTURE,
        "edto": EDTO_GREEN,
        "vws": WEATHER_AMBER,
        "terrain": TERRAIN_ORANGE,
        "arrival": DESTINATION,
    }
    strip_entries = (
        [
            {
                "time": str(item.get("utc_display") or "--"),
                "label": str(item.get("label") or ""),
                "sub": str(item.get("detail") or ""),
                "accent": timeline_colours.get(
                    str(item.get("kind") or ""), COMMS_TEAL
                ),
                "actm": item.get("actm_minutes"),
            }
            for item in shared_timeline
        ]
        if shared_timeline
        else [entry for entry in _route_anchor_entries(flight, briefing)]
    )
    if len(strip_entries) > 5:
        keep = {0, len(strip_entries) - 1}
        keep.update(index for index, entry in enumerate(strip_entries) if entry.get("label", "").startswith("EDTO") or "*" in str(entry.get("sub") or ""))
        strip_entries = [entry for index, entry in enumerate(strip_entries) if index in keep][:5]
    _timeline(canvas, cx0, row1_top - row1_h + 14, centre_w - 28, strip_entries)

    # --- Row 2: FLIGHT BASIS | MASS / FUEL | TECHNICAL STATUS
    row2_top = row1_top - row1_h - row_gap
    basis_w = full_w * 0.215
    fuel_w = full_w * 0.325
    tech_w = full_w - basis_w - fuel_w - 20
    fuel_x = MARGIN + basis_w + 10
    tech_x = fuel_x + fuel_w + 10
    # PERFORMANCE replaces the FLIGHT BASIS card (boss, 21 Aug R2-9: "add
    # PERFORMANCE card to p1"); the basis facts already ride in the header,
    # the route chips and the footer. Every figure is the shared publication.
    performance_publication = _shared_performance_publication(briefing)
    performance_inputs = performance_publication.get("inputs") or {}
    perf_inner = panel(canvas, MARGIN, row2_top - row2_h, basis_w, row2_h,
                       title="CFP P1 - PERFORMANCE", accent=DASH_BLUE, title_colour=None)
    ix = perf_inner[0]
    selected_keys = [str(key) for key in performance_publication.get("selected_candidate_keys") or []]
    limit_names = {
        "landing": "LANDING",
        "performance": "PERF / OBSTACLE",
        "structural": "STRUCTURAL",
        "cfp_controlling": "CFP RTOW",
    }
    limit_label = next(
        (limit_names[key] for key in selected_keys if key != "cfp_controlling" and key in limit_names),
        next((limit_names[key] for key in selected_keys if key in limit_names), "--"),
    )
    perf_ptow = performance_publication.get("ptow_kg")
    perf_rtow = performance_publication.get("selected_rtow_kg")
    perf_margin = performance_publication.get("margin_kg")
    flap_setting = performance_inputs.get("flap_setting")
    switch = lambda value: "ON" if value is True else "OFF" if value is False else "--"
    max_fuel = performance_inputs.get("maximum_fuel_available_kg")
    perf_rows = [
        ("PTOW", f"{perf_ptow:,} KG" if perf_ptow is not None else "--"),
        ("RTOW", f"{perf_rtow:,} KG" if perf_rtow is not None else "--"),
        ("MARGIN", (f"+{perf_margin:,} KG" if perf_margin >= 0 else f"{perf_margin:,} KG") if perf_margin is not None else "--"),
        ("LIMIT", limit_label),
        ("RWY / COND", f"{performance_inputs.get('runway') or '--'} / {performance_inputs.get('runway_condition') or '--'}"),
        ("CONFIG", " / ".join(part for part in (
            "OPT CONF" if flap_setting is None else f"FLAPS {flap_setting}",
            str(performance_inputs.get("thrust_setting") or ""),
        ) if part)),
        ("PACKS / A-ICE", f"{switch(performance_inputs.get('packs_on'))} / {switch(performance_inputs.get('anti_ice_on'))}"),
        ("TEMP / QNH", " / ".join((
            f"{performance_inputs.get('temperature_c')} C" if performance_inputs.get("temperature_c") is not None else "--",
            f"{performance_inputs.get('qnh_hpa')} HPA" if performance_inputs.get("qnh_hpa") is not None else "--",
        ))),
        ("EOSID", str(performance_inputs.get("eosid") or "--")),
    ]
    if max_fuel is not None:
        perf_rows.append(("MAX FUEL", f"{max_fuel:,} KG"))
    kv_rows(ix, row2_top - 28, basis_w - 28, perf_rows, mono_value=False,
            value_offset=58.0, font_size=7.4, fit_floor=7.15,
            dynamic_value_offset=True)
    perf_status = str(performance_publication.get("status") or "")
    canvas.setFillColor(DASH_GREEN if perf_status == "within-limit" else DASH_ORANGE)
    canvas.setFont(SANS_BOLD, 7.2)
    _draw_string_fitted(
        canvas,
        ix,
        row2_top - row2_h + 10,
        (
            f"RTOW within limit - {limit_label} controls."
            if perf_status == "within-limit"
            else "RTOW review - " + perf_status.replace("-", " ") + "."
        ),
        SANS_BOLD,
        7.2,
        basis_w - 28,
        DASH_GREEN if perf_status == "within-limit" else DASH_ORANGE,
        floor=7.15,
    )

    fuel_inner = panel(canvas, fuel_x, row2_top - row2_h, fuel_w, row2_h,
                       title="CFP P1 - MASS / FUEL", accent=DASH_GREEN, title_colour=None)
    ix = fuel_inner[0]
    masses = fuel_summary.get("masses_kg") or {}
    performance_publication = _shared_performance_publication(briefing)
    selected_rtow = performance_publication.get("selected_rtow_kg")
    ptow = performance_publication.get("ptow_kg")
    margin_kg = performance_publication.get("margin_kg")
    _, _, margin_accent = _performance_margin_presentation(
        performance_publication
    )
    margin_accent = {
        EDTO_GREEN: DASH_GREEN,
        WEATHER_AMBER: DASH_ORANGE,
        CRITICAL: DASH_RED,
    }.get(margin_accent, margin_accent)
    half_col = (fuel_w - 28) / 2
    mass_rows = [
        ("PZFW", f"{masses.get('pzfw'):,}" if masses.get("pzfw") else "--"),
        ("PTOW", f"{ptow:,}" if ptow is not None else "--"),
        ("PLWT", f"{masses.get('plwt'):,}" if masses.get("plwt") else "--"),
        ("RTOW", f"{selected_rtow:,}" if selected_rtow is not None else "--"),
        ("MARGIN", f"+{margin_kg:,}" if margin_kg and margin_kg > 0 else f"{margin_kg:,}" if margin_kg is not None else "--"),
        ("ZFW +1000", f"+{flight.get('zfw_change_burn_add_kg_per_1000')} BURN" if flight.get("zfw_change_burn_add_kg_per_1000") else "--"),
        ("ZFW -1000", f"-{flight.get('zfw_change_burn_less_kg_per_1000')} BURN" if flight.get("zfw_change_burn_less_kg_per_1000") else "--"),
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
                     margin_accent if label == "MARGIN" else TEXT,
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
    destination_top_up = (rows_data.get("dest_hold_top_up") or {}).get("fuel_kg") or 0
    edto_top_up = (rows_data.get("edto_top_up") or {}).get("fuel_kg") or 0
    top_up_row = (
        ("DEST HOLD TOP-UP", f"{destination_top_up:,}")
        if _edto_classification(flight).startswith("NON")
        else ("DEST/EDTO TOP-UP", f"{destination_top_up:,} / {edto_top_up:,}")
    )
    fuel_rows = [
        ("BURNOFF", timed("burnoff")),
        ("STAT CONT", timed("stat_cont")),
        ("ALTN", timed("altn_fuel")),
        ("ALTN HOLD", timed("altn_hold")),
        ("TAXI", f"{fuel_summary.get('taxi_fuel_kg'):,}" if fuel_summary.get("taxi_fuel_kg") else "--"),
        top_up_row,
        ("FPL REQMT", timed("flt_plan_reqmt")),
        ("TANKS", f"{(rows_data.get('fuel_in_tanks') or {}).get('fuel_kg') or 0:,}/{(rows_data.get('excess_fuel') or {}).get('fuel_kg') or 0:,}"),
    ]
    # When CFP page 1 itemises the whole excess as TANKER, it gets its own
    # row in the CFP's own word (boss, 21 Aug: this excess IS tankering).
    tanker_items = [
        item for item in fuel_summary.get("excess_breakdown") or []
        if item.get("fuel_kg")
    ]
    if tanker_items and all(item.get("label") == "TANKER" for item in tanker_items):
        fuel_rows.append(("TANKER", f"+{tanker_items[0]['fuel_kg']:,}"))
    lower_cruise = flight.get("lower_cruise_sensitivity") or {}
    if lower_cruise:
        offset_ft = lower_cruise.get("offset_ft")
        cost_index = lower_cruise.get("cost_index")
        burn_add_kg = lower_cruise.get("burn_add_kg")
        time_display = lower_cruise.get("time_display")
        # Compact forms so label and value share the narrow column without
        # ever colliding (the physical-PDF gate rejects visible overlaps).
        fuel_rows.append((
            f"-{offset_ft}FT CI{cost_index}",
            (
                f"+{burn_add_kg:,}/{time_display}"
                if burn_add_kg is not None and time_display
                else "--"
            ),
        ))
    row_y = row2_top - 28
    for label, value in fuel_rows:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(ix + half_col + 8, row_y, label)
        _value_right(ix + fuel_w - 28, row_y, value, TEXT,
                     ix + half_col + 8 + pdfmetrics.stringWidth(label, SANS, T_MICRO) + 4)
        row_y -= 13
    if str(fuel_summary.get("state") or "") != "verified":
        canvas.setFillColor(DASH_ORANGE)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawString(ix, row2_top - row2_h + 10, "Page-1 fuel arithmetic did not verify - review the source CFP page.")

    tech_inner = panel(canvas, tech_x, row2_top - row2_h, tech_w, row2_h,
                       title="CFP P1 - TECHNICAL STATUS", accent=DASH_RED, title_colour=None)
    ix = tech_inner[0]
    row_y = row2_top - 28
    deferred = flight.get("deferred_items") or []
    deferred_gates = list(briefing.get("deferred_dispatch_gates") or [])
    publication_rows = [
        row
        for gate in deferred_gates
        for row in gate.get("publication_rows") or []
    ]
    listed = publication_rows or deferred_gates or [
        {
            "title": deferred_item_type_for_display(item.get("item_type")),
            "references": [
                deferred_reference_for_display(item.get("reference"))
            ]
            if deferred_reference_for_display(item.get("reference"))
            else [],
            "summary": str(
                item.get("company_remark") or item.get("description") or ""
            ),
            "category": str(item.get("item_type") or "").lower(),
        }
        for item in deferred
    ]
    for item in listed[:6]:
        references = [
            str(reference).strip()
            for reference in item.get("references") or []
            if str(reference or "").strip()
        ]
        title = str(item.get("title") or "ITEM")
        label = (
            " / ".join(references)
            if str(item.get("category") or "") == "operational-restriction"
            and references
            else title
        )
        note = str(item.get("summary") or "")
        category = str(item.get("category") or "")
        label_colour = (
            ACCENT
            if category == "cddl"
            else CRITICAL
            if category == "operational-restriction"
            else WEATHER_AMBER
        )
        canvas.setFillColor(label_colour)
        canvas.setFont(MONO_BOLD, T_MICRO)
        _draw_string_fitted(
            canvas,
            ix,
            row_y,
            label,
            MONO_BOLD,
            T_MICRO,
            84,
            label_colour,
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        _draw_string_fitted(
            canvas,
            ix + 86,
            row_y,
            note,
            SANS,
            7.2,
            tech_w - 108,
            TEXT_SECONDARY,
            floor=6.4,
        )
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
    weather_sources = {
        str(record.get("source") or "uploaded_cfp")
        for record in flight.get("weather") or []
    }
    weather_refresh_open = bool(weather_sources) and not any(
        source == "noaa_awc_live" for source in weather_sources
    )
    if weather_refresh_open:
        release_lines.append(("OPEN", "CFP-held weather source - dispatch refresh."))
    cdl_references = list(dict.fromkeys(
        str(reference).strip()
        for gate in deferred_gates
        if str(gate.get("category") or "") == "cdl"
        for reference in gate.get("references") or []
        if str(reference or "").strip()
    ))
    if cdl_references:
        release_lines.append((
            "OPEN",
            f"CDL {'/'.join(cdl_references)} inputs - no guessed penalties.",
        ))
    operational_references = list(dict.fromkeys(
        str(reference).strip()
        for gate in deferred_gates
        if str(gate.get("category") or "") == "operational-restriction"
        for reference in gate.get("references") or []
        if str(reference or "").strip()
    ))
    for reference in operational_references:
        release_lines.append((
            "OPEN",
            f"{reference} not mounted - confirm instruction.",
        ))
    if gaps:
        release_lines.append(("GAP", f"{'/'.join(gaps)} unavailable - coverage gap, not NIL."))
    for tag, line in release_lines[:4]:
        canvas.setFillColor(CRITICAL if tag == "OPEN" else WEATHER_AMBER)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(ix, row_y, tag)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        _draw_string_fitted(canvas, ix + 34, row_y, line, SANS, T_MICRO, tech_w - 66, TEXT_SECONDARY)
        row_y -= 11



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
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.setLineWidth(1.0)
    canvas.line(x, rail_y, x + w, rail_y)
    for index, entry in enumerate(entries):
        cx = x + (index * step if len(entries) > 1 else w / 2)
        accent = entry.get("accent") or accent_default
        if getattr(canvas, "_brief_dashboard_palette", False):
            accent = {
                DEPARTURE: DASH_BLUE,
                DESTINATION: DASH_PURPLE,
                EDTO_GREEN: DASH_GREEN,
                WEATHER_AMBER: DASH_ORANGE,
                TERRAIN_ORANGE: DASH_ORANGE,
                CRITICAL: DASH_RED,
            }.get(accent, accent)
        canvas.setFillColor(accent)
        canvas.circle(cx, rail_y, 3.4, stroke=0, fill=1)
        # REV3 measured strip: white Courier-Bold times above the rail,
        # accent-coloured labels below it - his file inverts our old colours.
        canvas.setFillColor(TEXT)
        canvas.setFont(UTIL_MONO_BOLD, 7.6)
        time_text = str(entry.get("time") or "--")
        tw = pdfmetrics.stringWidth(time_text, UTIL_MONO_BOLD, 7.6)
        canvas.drawString(min(max(x, cx - tw / 2), x + w - tw), rail_y + 8, time_text)
        # Labels hold at T_MICRO: REV3 prints 7.0 here, but the boss's own
        # readable floor (>= 7.15 in content) outranks his generator's size.
        canvas.setFillColor(accent)
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


def _ddhhmm_actm(
    flight: dict[str, Any], value: str | None
) -> int | None:
    """Resolve a governed DDHHMM product time against the CFP departure."""
    from datetime import datetime, timezone

    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", str(value or ""))
    raw = str(flight.get("scheduled_departure_utc") or "").replace("Z", "+00:00")
    if not match or not raw:
        return None
    try:
        departure = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    day, hour, minute = (int(part) for part in match.groups())
    candidates = []
    for month_offset in (-1, 0, 1):
        month_index = departure.month - 1 + month_offset
        year = departure.year + month_index // 12
        month = month_index % 12 + 1
        try:
            candidates.append(
                datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=departure.tzinfo,
                )
            )
        except ValueError:
            continue
    if not candidates:
        return None
    resolved = min(candidates, key=lambda item: abs(item - departure))
    return round((resolved - departure).total_seconds() / 60.0)


def _route_anchor_entries(flight: dict[str, Any], briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Select governed anchor roles; detail pages preserve every raw event."""
    waypoints = [
        waypoint
        for waypoint in (flight.get("route_waypoints") or [])
        if waypoint.get("actm_minutes") is not None
    ]
    if not waypoints:
        return []
    entries: list[dict[str, Any]] = []

    # One product-expiry gate at or before departure: the closest governed
    # expiry is the actionable preflight boundary, not an arbitrary waypoint.
    preflight_candidates = []
    for card in (briefing.get("hazards") or {}).get("sigmet_cards") or []:
        actm = _ddhhmm_actm(flight, card.get("valid_to"))
        if actm is not None and actm <= 0:
            preflight_candidates.append((actm, card))
    if preflight_candidates:
        actm, card = max(preflight_candidates, key=lambda item: item[0])
        entries.append({
            "time": _clock_at(flight, actm),
            "label": f"{card.get('sigmet_id') or 'WX'} EXP",
            "sub": "",
            "accent": WEATHER_AMBER,
            "actm": actm,
        })

    entries.append({
        "time": _clock_at(flight, 0),
        "label": "DEP",
        "sub": "",
        "accent": DEPARTURE,
        "actm": 0,
    })

    edto_entries = [
        (sector.get("entry") or {}).get("actm_minutes")
        for sector in (flight.get("edto") or {}).get("sectors") or []
    ]
    edto_entries = [value for value in edto_entries if value is not None]
    if edto_entries:
        actm = min(edto_entries)
        entries.append({
            "time": _clock_at(flight, actm),
            "label": "EDTO",
            "sub": "",
            "accent": EDTO_GREEN,
            "actm": actm,
        })

    terrain_events = list((briefing.get("terrain") or {}).get("events") or [])
    if terrain_events:
        critical_event = max(
            terrain_events,
            key=lambda event: (
                ((event.get("maximum") or {}).get("msa_hundreds_ft") or 0),
                -((event.get("first_high") or {}).get("actm_minutes") or 0),
            ),
        )
        seen_terrain: set[tuple[str, Any]] = set()
        for key in ("first_high", "maximum", "last_high"):
            waypoint = critical_event.get(key) or {}
            identity = (
                str(waypoint.get("name") or "").lstrip("-"),
                waypoint.get("actm_minutes"),
            )
            if not identity[0] or identity in seen_terrain:
                continue
            seen_terrain.add(identity)
            msa = waypoint.get("msa_hundreds_ft")
            entries.append({
                "time": _clock_at(flight, waypoint.get("actm_minutes")),
                "label": f"{identity[0]} {msa}*" if msa is not None else identity[0],
                "sub": "",
                "accent": TERRAIN_ORANGE,
                "actm": waypoint.get("actm_minutes"),
            })

    last = waypoints[-1]
    arrival_time = theme.utc_hhmm(flight.get("scheduled_arrival_utc"))
    if arrival_time == "-":
        arrival_time = _clock_at(flight, last.get("actm_minutes"))
    entries.append({
        "time": arrival_time,
        "label": str(
            last.get("name") or flight.get("destination") or "ARR"
        ).lstrip("-"),
        "sub": "",
        "accent": DESTINATION,
        "actm": last.get("actm_minutes"),
    })
    entries.sort(key=lambda item: item.get("actm") if item.get("actm") is not None else 0)
    return entries


def _terrain_table_points(
    flight: dict[str, Any],
    briefing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return source route context around each strict terrain window.

    The terrain engine owns the exposure boundaries. The compact table also
    shows one filed waypoint after the threshold-drop point when available,
    so the pilot can see that the route remains below the strict threshold.
    This display-only lookup does not extend or validate a profile match.
    """
    route_points = list(flight.get("route_waypoints") or [])
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()

    def add(point: dict[str, Any] | None) -> None:
        if not point:
            return
        identity = (
            str(point.get("name") or "").lstrip("-"),
            point.get("actm_minutes"),
        )
        if not identity[0] or identity in seen:
            return
        seen.add(identity)
        selected.append(point)

    for event in list((briefing.get("terrain") or {}).get("events") or [])[:2]:
        for key in ("preceding", "first_high", "maximum", "last_high", "drop"):
            add(event.get(key) or {})
        drop = event.get("drop") or {}
        drop_identity = (
            str(drop.get("name") or "").lstrip("-"),
            drop.get("actm_minutes"),
        )
        for index, waypoint in enumerate(route_points):
            identity = (
                str(waypoint.get("name") or "").lstrip("-"),
                waypoint.get("actm_minutes"),
            )
            if identity != drop_identity:
                continue
            for following in route_points[index + 1 :]:
                if following.get("msa_hundreds_ft") is not None:
                    add(following)
                    break
            break
    return selected


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


def _profile_lines_for_width(profile: Any, max_width: float) -> list[str]:
    """Split the slash-delimited CFP level chain without losing a token."""
    profile_lines: list[str] = []
    current = ""
    for segment in str(profile or "").strip().split("/"):
        candidate = f"{current}/{segment}" if current else segment
        if pdfmetrics.stringWidth(candidate + "/", MONO, T_MICRO) > max_width and current:
            profile_lines.append(current + "/")
            current = segment
        else:
            current = candidate
    if current:
        profile_lines.append(current)
    return profile_lines


def _overview_route_layout(flight: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    """Route/profile lines exactly as the dashboard column wraps them.

    The dashboard page and the airports page both derive from this one
    layout, so the dashboard's continuation pointer and the airports-page
    verbatim block can never disagree about whether the compact row held
    the whole route. Routes were silently cut at three lines before this
    (SQ23's 545-character route printed 28%)."""
    width, _ = PAGE_SIZE
    full_w = width - 2 * MARGIN
    side_w = full_w * 0.215
    centre_w = full_w - 2 * (side_w + 10)
    text_w = centre_w * 0.55
    route_lines = _wrap(
        str(flight.get("route_text") or "Route text not held."), MONO, T_MICRO, text_w
    )
    # The profile is one unbroken FIX/LEVEL token chain - word wrapping
    # cannot split it (SQ322's ran under the map), so break on slashes.
    profile_lines = _profile_lines_for_width(
        flight.get("planned_level_profile"), text_w
    )
    return route_lines, profile_lines, len(route_lines) > 3 or len(profile_lines) > 2


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


def _chunked(values: list[Any], size: int) -> list[list[Any]]:
    """Return stable first-seen chunks; an empty collection still has a page."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [values[index:index + size] for index in range(0, len(values), size)] or [[]]


def _continuation_suffix(page_number: int, page_count: int) -> str:
    return (
        f" - CONTINUED ({page_number}/{page_count})"
        if page_count > 1 and page_number > 1
        else ""
    )


def _flatten_detail_rows(
    prefix: str,
    value: Any,
) -> list[tuple[str, str]]:
    """Flatten a held shared projection without changing any leaf value."""
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_detail_rows(child_prefix, child))
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            rows.extend(_flatten_detail_rows(f"{prefix}[{index}]", child))
    elif value is not None:
        rendered = str(value)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) == int(value)
            and ("time_minutes" in prefix.lower() or "actm" in prefix.lower())
        ):
            minutes = int(value)
            rendered = f"{minutes} min ({minutes // 60:02d}:{minutes % 60:02d})"
        rows.append((prefix.upper(), rendered))
    return rows


def _detail_page_plans(
    title: str,
    rows: list[tuple[str, str]],
    *,
    value_width: float | None = None,
) -> list[dict[str, Any]]:
    """Wrap shared detail rows into deterministic, lossless page plans."""
    if not rows:
        return []
    if value_width is None:
        value_width = PAGE_SIZE[0] - 2 * MARGIN - 178.0
    fragments: list[tuple[str, list[str], int]] = []
    for label, value in rows:
        lines = _wrap(str(value), SANS, T_SMALL, value_width) or [""]
        max_lines = max(1, DETAIL_PAGE_LINE_BUDGET - 1)
        for index in range(0, len(lines), max_lines):
            selected = lines[index:index + max_lines]
            fragments.append((
                str(label) if index == 0 else f"{label} CONT.",
                selected,
                len(selected) + 1,
            ))

    pages: list[dict[str, Any]] = []
    current: list[tuple[str, list[str]]] = []
    used = 0
    for label, lines, cost in fragments:
        if current and used + cost > DETAIL_PAGE_LINE_BUDGET:
            pages.append({"title": title, "rows": current})
            current = []
            used = 0
        current.append((label, lines))
        used += cost
    if current:
        pages.append({"title": title, "rows": current})
    return pages


def _performance_fuel_detail_pages(
    briefing: dict[str, Any],
    flight: dict[str, Any],
) -> list[dict[str, Any]]:
    parsed_performance = flight.get("performance") or {}
    packs_on = parsed_performance.get("packs_on")
    anti_ice_on = parsed_performance.get("anti_ice_on")
    switch_rows: list[tuple[str, str]] = []
    if isinstance(packs_on, bool) or isinstance(anti_ice_on, bool):
        packs_value = "ON" if packs_on is True else "OFF" if packs_on is False else "--"
        anti_ice_value = (
            "ON" if anti_ice_on is True else "OFF" if anti_ice_on is False else "--"
        )
        switch_rows.append(("PACKS / ANTI-ICE", f"{packs_value} / {anti_ice_value}"))
    rows = [
        *_flatten_detail_rows(
            "PERFORMANCE",
            _shared_performance_publication(briefing),
        ),
        *_flatten_detail_rows("CFP PERFORMANCE INPUTS", parsed_performance),
        *switch_rows,
        *_flatten_detail_rows("MASSES", briefing.get("masses") or {}),
        *_flatten_detail_rows("FUEL", briefing.get("fuel") or {}),
        *_flatten_detail_rows(
            "FUEL SUMMARY",
            briefing.get("fuel_summary") or {},
        ),
    ]
    return _detail_page_plans("FULL SHARED PERFORMANCE / FUEL DETAILS", rows)


def _deferred_detail_pages(
    flight: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[tuple[str, str]] = []
    for index, item in enumerate(flight.get("deferred_items") or [], start=1):
        source_declaration = deferred_source_declaration_for_display(
            item.get("source_declaration")
        )
        item_type = deferred_item_type_for_display(item.get("item_type"))
        reference = deferred_reference_for_display(item.get("reference"))
        identity = " | ".join(
            part
            for part in (
                (
                    source_declaration
                    if item_type == "DEFERRED ITEM" and source_declaration
                    else item_type
                ),
                # A bare declaration ("BB CDDL") has no printed reference;
                # say so instead of the internal "UNSPECIFIED" word
                # (boss, 21 Aug: "UNCLASSIFIED; CDDL UNSPECIFIED").
                reference or "no printed reference",
            )
            if part
        )
        rows.append((f"ITEM {index}", identity))
        for label, key in (
            ("DESCRIPTION", "description"),
            ("COMPANY REMARK", "company_remark"),
            ("PENALTY", "penalty"),
            ("SOURCE PAGE", "source_page"),
        ):
            value = item.get(key)
            rows.append((
                f"{index} {label}",
                str(value) if value not in (None, "") else "NOT STATED IN THE PARSED CFP DECLARATION",
            ))
        known = {
            "item_type",
            "reference",
            "description",
            "company_remark",
            "penalty",
            "source_page",
            "source_declaration",
        }
        for key, value in item.items():
            if key == "source_declaration":
                if source_declaration:
                    rows.extend(
                        _flatten_detail_rows(
                            f"ITEM {index}.{key}",
                            source_declaration,
                        )
                    )
                continue
            if key not in known:
                rows.extend(
                    _flatten_detail_rows(f"ITEM {index}.{key}", value)
                )
    return _detail_page_plans("FULL CFP DEFERRED DECLARATIONS", rows)


def _airport_notam_detail_pages(
    briefing: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[tuple[str, str]] = []
    for panel_data in briefing.get("airport_operational_panels") or []:
        icao = str(panel_data.get("icao") or "----").upper()
        for index, item in enumerate(panel_data.get("selected_notams") or [], start=1):
            notam_id = str(item.get("notam_id") or "UNSPECIFIED")
            prefix = f"{icao} {index}"
            rows.extend((
                (f"{prefix} NOTAM ID", notam_id),
                (
                    f"{prefix} VALIDITY",
                    " - ".join(
                        str(value or "NOT STATED")
                        for value in (
                            item.get("valid_from_utc"),
                            item.get("valid_to_utc"),
                        )
                    ),
                ),
                (
                    f"{prefix} SCHEDULE",
                    str(item.get("schedule") or "NOT SEPARATELY STATED"),
                ),
                (
                    f"{prefix} APPLICABILITY",
                    " | ".join(
                        str(value)
                        for value in (
                            item.get("applicability") or "REVIEW REQUIRED",
                            item.get("window_start_utc"),
                            item.get("window_end_utc"),
                        )
                        if value not in (None, "")
                    ),
                ),
                (
                    f"{prefix} SUMMARY",
                    str(item.get("summary") or "NO SEPARATE SUMMARY HELD"),
                ),
                (
                    f"{prefix} ITEM E",
                    str(item.get("item_e_text") or "ITEM-E TEXT NOT HELD - REVIEW SOURCE"),
                ),
                (
                    f"{prefix} SOURCE",
                    f"CFP page {item.get('source_page')}"
                    if item.get("source_page") is not None
                    else "SOURCE PAGE NOT HELD",
                ),
            ))
    return _detail_page_plans("ALL SELECTED NOTAM DETAILS", rows)


def _vaa_detail_pages(
    briefing: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[tuple[str, str]] = []
    for index, advisory in enumerate(
        (briefing.get("vaa") or {}).get("cfp_advisories") or [],
        start=1,
    ):
        prefix = f"VAA {index}"
        rows.extend((
            (f"{prefix} NAME", str(advisory.get("name") or "VOLCANIC ASH ADVISORY")),
            (
                f"{prefix} VALIDITY",
                " - ".join(
                    str(value or "NOT STATED")
                    for value in (
                        advisory.get("valid_from"),
                        advisory.get("valid_to"),
                    )
                ),
            ),
            (f"{prefix} FIR", str(advisory.get("fir") or "NOT STATED")),
            (f"{prefix} DERIVED", str(advisory.get("derived") or "NO DERIVED SCREENING HELD")),
            (f"{prefix} SOURCE TEXT", str(advisory.get("text") or "SOURCE TEXT NOT HELD")),
            (
                f"{prefix} SOURCE PAGE",
                str(advisory.get("source_page") or "NOT HELD"),
            ),
        ))
    return _detail_page_plans("FULL VOLCANIC-ASH SOURCE DETAILS", rows)


def _terrain_detail_pages(
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events = list((briefing.get("terrain") or {}).get("events") or [])
    if not events:
        return []
    matched_ids: set[str] = set()
    for finding in _matched_profiles(findings):
        data = finding.get("data") or {}
        matched_ids.update(
            str(value)
            for value in data.get("terrain_event_ids") or []
            if value
        )
        if data.get("terrain_event_id"):
            matched_ids.add(str(data["terrain_event_id"]))
    rows: list[tuple[str, str]] = []
    for index, event in enumerate(events, start=1):
        event_id = str(event.get("terrain_event_id") or f"EVENT-{index}")
        rows.append((
            f"EVENT {index} STATUS",
            "PROFILE MATCHED"
            if event_id in matched_ids
            else "UNMATCHED EXPOSURE - MANUAL REVIEW REQUIRED",
        ))
        rows.extend(_flatten_detail_rows(f"EVENT {index}", event))
    return _detail_page_plans("ALL TERRAIN EVENTS / UNMATCHED EXPOSURES", rows)


def draw_shared_detail_page(
    canvas,
    flight: dict[str, Any],
    *,
    page_number: int,
    page_count: int,
    section_label: str,
    section_colour,
    section_page_number: int,
    section_page_count: int,
    title: str,
    rows: list[tuple[str, list[str]]],
    source_line: str,
    page_family: str = "standard",
) -> None:
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line=source_line,
        section_label=(
            section_label
            + _continuation_suffix(section_page_number, section_page_count)
        ),
        section_colour=section_colour,
        page_family=page_family,
    )
    full_w = PAGE_SIZE[0] - 2 * MARGIN
    inner = panel(
        canvas,
        MARGIN,
        30,
        full_w,
        content_top - 36,
        title=title,
        accent=section_colour,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    label_width = 158.0
    row_y = content_top - 31.0
    for label, lines in rows:
        required = len(lines) * DETAIL_LINE_HEIGHT + DETAIL_ROW_GAP
        if row_y - required < iy + 2:
            raise ValueError(
                f"{section_label} shared-detail continuation exceeds "
                "its measured page capacity"
            )
        _draw_string_fitted(
            canvas,
            ix,
            row_y,
            label,
            MONO_BOLD,
            T_MICRO,
            label_width - 8,
            TEXT_MUTED,
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        for line in lines:
            canvas.drawString(ix + label_width, row_y, line)
            row_y -= DETAIL_LINE_HEIGHT
        row_y -= DETAIL_ROW_GAP


def _route_profile_continuation_pages(
    flight: dict[str, Any],
) -> list[list[tuple[str, str]]]:
    """Build complete AIRPORT-section route/profile overflow pages.

    Page 1 intentionally keeps the compact route-map composition. When that
    composition points pilots to the AIRPORTS page, every route and planned
    level-profile token is printed here. Rows are wrapped to the exact drawing
    width and then paginated; neither fitting nor ellipsis is allowed.
    """
    _, _, overflows = _overview_route_layout(flight)
    if not overflows:
        return []

    full_w = PAGE_SIZE[0] - 2 * MARGIN
    value_width = full_w - 98.0
    route_lines = _wrap(
        str(flight.get("route_text") or "Route text not held."),
        MONO,
        T_MICRO,
        value_width,
    )
    profile_lines = _profile_lines_for_width(
        flight.get("planned_level_profile"), value_width
    )
    # A label identifies each source block once. Repeating it on every
    # wrapped line inserts non-source words into the visible route/profile
    # sequence and prevents an exact ordered-fact audit.
    rows = [
        *(
            ("CFP ROUTE" if index == 0 else "", line)
            for index, line in enumerate(route_lines)
        ),
        *(
            ("LEVEL PROFILE" if index == 0 else "", line)
            for index, line in enumerate(profile_lines)
        ),
    ]
    for label, value in rows:
        if pdfmetrics.stringWidth(value, MONO, T_MICRO) > value_width + 0.1:
            raise ValueError(
                f"{label} contains a source token wider than the printable "
                "AIRPORT continuation area."
            )
    return [
        rows[index:index + AIRPORT_ROUTE_PROFILE_ROWS_PER_PAGE]
        for index in range(0, len(rows), AIRPORT_ROUTE_PROFILE_ROWS_PER_PAGE)
    ]


def _selected_airport_operational_panels(
    briefing: dict[str, Any],
) -> list[dict[str, Any]]:
    """REV3's selected airport-role cards from the shared briefing contract.

    The renderer does not re-score weather or NOTAMs.  It consumes the exact
    source-fact panels prepared by ``build_briefing_view``.  REV3 page 5 names
    the preferred destination alternate, not every planning alternate, so the
    first alternate panel is the selected one.  Every selected EDTO and fuel-
    enroute panel remains cardinality-preserving and may continue on later
    AIRPORT pages.
    """
    panels = [
        dict(panel)
        for panel in briefing.get("airport_operational_panels") or []
        if isinstance(panel, dict) and str(panel.get("icao") or "").strip()
    ]
    selected: list[dict[str, Any]] = []
    selected_icaos: set[str] = set()

    def role_keys(panel: dict[str, Any]) -> set[str]:
        values = panel.get("role_keys")
        if isinstance(values, list):
            return {str(value) for value in values if value}
        return {str(panel.get("role_key") or "")}

    def add(panel: dict[str, Any] | None) -> None:
        if not panel:
            return
        icao = str(panel.get("icao") or "").upper()
        if not icao or icao in selected_icaos:
            return
        selected.append(panel)
        selected_icaos.add(icao)

    for role_key in ("departure", "destination"):
        panel = next(
            (item for item in panels if role_key in role_keys(item)),
            None,
        )
        add(panel)
    alternate_panels = [
        item for item in panels if "alternate" in role_keys(item)
    ]
    if alternate_panels:
        add(alternate_panels[0])
    for item in panels:
        if role_keys(item) & {"edto", "fuel_enroute_airport"}:
            add(item)
    # Preserve the compact primary selection above, then carry every other
    # normal destination alternate onto deterministic continuation pages.
    for item in alternate_panels[1:]:
        add(item)
    return selected


def _shared_performance_publication(
    briefing: dict[str, Any],
) -> dict[str, Any]:
    publication = briefing.get("performance_publication")
    if not isinstance(publication, dict):
        raise ValueError(
            "Shared performance_publication is required; the PDF renderer "
            "must not independently select an RTOW limit or margin."
        )
    if not isinstance(publication.get("candidate_limits"), list):
        raise ValueError("Shared performance_publication candidates are malformed")
    return publication


def _performance_margin_presentation(
    publication: dict[str, Any],
) -> tuple[str, str, colors.Color]:
    """Return a fail-closed margin value, caption and state colour.

    The shared publication owns the arithmetic and status.  A missing or
    inconsistent margin is a review state; it must never inherit a green
    default merely because Python treats ``None`` as false.
    """
    status = str(publication.get("status") or "")
    margin_kg = publication.get("margin_kg")
    if status == "manual-review-required" or margin_kg is None:
        return "--", "review required", WEATHER_AMBER
    if status == "limit-exceeded" or margin_kg < 0:
        return f"{margin_kg:,} kg", "limit exceeded", CRITICAL
    if status == "within-limit" and margin_kg >= 0:
        return f"+{margin_kg:,} kg", "to selected RTOW", EDTO_GREEN
    return "--", "review required", WEATHER_AMBER


def _performance_selected_presentation(
    publication: dict[str, Any],
) -> tuple[str, colors.Color]:
    """Map the shared performance status to the selected-limit card state."""
    status = str(publication.get("status") or "")
    selected = publication.get("selected_rtow_kg")
    if status == "within-limit" and selected is not None:
        return "most limiting", EDTO_GREEN
    if status == "limit-exceeded" and selected is not None:
        return "limit exceeded", CRITICAL
    return "review required", WEATHER_AMBER


def _edto_and_fuel_panels(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    seen_icaos: set[str] = set()
    for raw_panel in briefing.get("airport_operational_panels") or []:
        if not isinstance(raw_panel, dict):
            continue
        role_keys = raw_panel.get("role_keys")
        keys = (
            {str(value) for value in role_keys if value}
            if isinstance(role_keys, list)
            else {str(raw_panel.get("role_key") or "")}
        )
        icao = str(raw_panel.get("icao") or "").strip().upper()
        if not icao or icao in seen_icaos:
            continue
        if not keys & {"edto", "fuel_enroute_airport"}:
            continue
        panels.append(dict(raw_panel))
        seen_icaos.add(icao)
    return panels


def _shared_edto_operational_rows(
    briefing: dict[str, Any],
) -> list[tuple[str, str]]:
    """Return the shared pilot-readable EDTO projection without deriving it."""
    raw_rows = (briefing.get("edto") or {}).get("operational_rows")
    if not isinstance(raw_rows, list):
        raise ValueError(
            "Shared briefing.edto.operational_rows is required; the PDF "
            "renderer must not independently compose EDTO facts."
        )
    rows: list[tuple[str, str]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise ValueError("Shared EDTO operational row is malformed")
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if not label or not value:
            raise ValueError("Shared EDTO operational row is missing label/value")
        rows.append((label, value))
    if not rows:
        raise ValueError("Shared EDTO operational rows are empty")
    return rows


def _edto_status_cards(
    briefing: dict[str, Any],
    *,
    inner_width: float,
    card_height: float,
    included_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Paginate every shared EDTO row by the card's measured text height."""
    available_height = card_height - 37.0
    inline_width = inner_width - 76.0
    line_height = 9.8
    row_gap = 1.2

    def row_height(lines: list[str]) -> float:
        inline = (
            len(lines) == 1
            and pdfmetrics.stringWidth(lines[0], SANS, T_SMALL)
            <= inline_width
        )
        baselines = 1 if inline else 1 + len(lines)
        return baselines * line_height + row_gap

    fragments: list[tuple[str, list[str], float]] = []
    for label, value in _shared_edto_operational_rows(briefing):
        if included_labels is not None and label.strip().upper() not in included_labels:
            continue
        lines = _wrap(value, SANS, T_SMALL, inner_width) or [""]
        required = row_height(lines)
        if required <= available_height:
            fragments.append((label, lines, required))
            continue

        # One pathological source row may be taller than an empty card. Keep
        # every wrapped line and repeat only its identity on continuation.
        max_value_lines = max(
            1,
            int((available_height - row_gap) // line_height) - 1,
        )
        for index in range(0, len(lines), max_value_lines):
            selected = lines[index:index + max_value_lines]
            fragments.append((
                label if index == 0 else f"{label} CONT.",
                selected,
                row_height(selected),
            ))

    if included_labels is not None and not fragments:
        raise ValueError("Shared non-EDTO classification rows are empty")

    cards: list[dict[str, Any]] = []
    current: list[tuple[str, list[str]]] = []
    used_height = 0.0
    for label, lines, required in fragments:
        if current and used_height + required > available_height + 0.01:
            cards.append({"kind": "status", "rows": current})
            current = []
            used_height = 0.0
        current.append((label, lines))
        used_height += required
    if current or not cards:
        cards.append({"kind": "status", "rows": current})
    return cards


def _station_card_lines(panel_data: dict[str, Any]) -> list[tuple[str, str]]:
    """Exact shared source facts, one bounded row per retained record."""
    rows: list[tuple[str, str]] = []
    for operational in panel_data.get("operational_rows") or []:
        basis = " | ".join(
            part
            for part in (
                f"RWY {operational.get('runway')}" if operational.get("runway") else None,
                str(operational.get("approach") or "").strip() or None,
                str(operational.get("minima") or "").strip() or None,
                f"{operational.get('distance_nm')} NM" if operational.get("distance_nm") else None,
                format_actm(operational.get("time_minutes"))
                if operational.get("time_minutes") is not None else None,
                f"{operational.get('fuel_kg'):,} kg" if operational.get("fuel_kg") else None,
                " - ".join(
                    value
                    for value in (
                        str(operational.get("period_start_utc") or "").strip(),
                        str(operational.get("period_end_utc") or "").strip(),
                    )
                    if value
                ) or None,
            )
            if part
        )
        if basis:
            rows.append(("PLAN", basis))
    shared_lines = panel_data.get("card_summary_lines")
    if not isinstance(shared_lines, list):
        raise ValueError(
            "Selected airport-role panel is missing shared card_summary_lines; "
            "the PDF renderer must not reselect or re-summarise source facts."
        )
    for item in shared_lines:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        kind = str(item.get("kind") or "").strip().lower()
        rows.append((
            # REV3 publishes the operational summary, not the NOTAM identity.
            # Full IDs, validity and item-E remain in selected_notams for the
            # dashboard/audit surface. Weather record labels are source facts
            # and remain visible exactly as supplied by the shared view.
            "NOTAM"
            if kind == "notam"
            else str(item.get("label") or item.get("kind") or "SOURCE").upper(),
            str(item["text"]).strip(),
        ))
    if not rows:
        rows.append(("SOURCE", "No selected CFP weather or NOTAM fact is held for this role."))
    return rows


def _station_card_line_capacity(card_height: float) -> int:
    """Number of readable text baselines inside a station card."""
    return max(
        1,
        int((card_height - 39.0) // STATION_CARD_LINE_HEIGHT) + 1,
    )


def _station_card_fragments(
    panel_data: dict[str, Any],
    *,
    card_width: float,
    card_height: float,
) -> list[dict[str, Any]]:
    """Paginate one shared airport-role panel by its wrapped-line budget.

    A source row may itself be taller than a card.  In that case its label is
    repeated on each fragment and every wrapped value line remains visible.
    The original shared panel stays intact; underscore fields only carry the
    renderer's deterministic layout plan.
    """
    inner_width = card_width - 20.0
    capacity = _station_card_line_capacity(card_height)
    wrapped_rows: list[tuple[str, list[str]]] = []
    for label, value in _station_card_lines(panel_data):
        label_width = min(
            56.0,
            max(
                34.0,
                pdfmetrics.stringWidth(
                    label,
                    MONO_BOLD,
                    T_MICRO,
                ) + 6,
            ),
        )
        wrapped_rows.append((
            label,
            _wrap(
                value,
                SANS,
                T_MICRO,
                inner_width - label_width,
            ) or [""],
        ))

    planned_pages: list[list[tuple[str, list[str]]]] = []
    current: list[tuple[str, list[str]]] = []
    used = 0
    for label, lines in wrapped_rows:
        cursor = 0
        while cursor < len(lines):
            if used >= capacity:
                planned_pages.append(current)
                current = []
                used = 0
            take = min(capacity - used, len(lines) - cursor)
            current.append((label, lines[cursor:cursor + take]))
            cursor += take
            used += take
            if cursor < len(lines):
                planned_pages.append(current)
                current = []
                used = 0
    if current or not planned_pages:
        planned_pages.append(current)

    fragments: list[dict[str, Any]] = []
    fragment_count = len(planned_pages)
    for index, rows in enumerate(planned_pages):
        fragment = dict(panel_data)
        fragment["_station_card_rows"] = rows
        fragment["_station_fragment_index"] = index + 1
        fragment["_station_fragment_count"] = fragment_count
        fragment["_continued"] = index > 0
        fragments.append(fragment)
    return fragments


def _airport_operational_pages(
    briefing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Plan the canonical mosaic plus lossless full-card continuations."""
    full_width = PAGE_SIZE[0] - 2 * MARGIN
    gap = 10.0
    content_y = PAGE_SIZE[1] - 94.0 - 6.0
    available_height = content_y - 30.0
    row_height = (available_height - gap) / 2.0
    first_row_width = (full_width - 2 * gap) / 3.0
    second_row_width = (full_width - gap) / 2.0
    selected = _selected_airport_operational_panels(briefing)
    pages: list[dict[str, Any]] = []
    for batch in _chunked(selected, AIRPORT_OPERATIONAL_PANELS_PER_PAGE):
        primary_fragments: list[dict[str, Any]] = []
        overflow_fragments: list[dict[str, Any]] = []
        for index, panel_data in enumerate(batch):
            card_width = (
                first_row_width if index < 3 else second_row_width
            )
            fragments = _station_card_fragments(
                panel_data,
                card_width=card_width,
                card_height=row_height,
            )
            primary_fragments.append(fragments[0])
            for fragment in fragments[1:]:
                fragment["_station_full_page"] = True
                overflow_fragments.append(fragment)
        pages.append({
            "panels": primary_fragments,
            "route_profile_rows": [],
        })
        pages.extend(
            {
                "panels": [fragment],
                "route_profile_rows": [],
            }
            for fragment in overflow_fragments
        )
    return pages


def _draw_station_card(
    canvas,
    panel_data: dict[str, Any],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    accent,
) -> None:
    role_keys = panel_data.get("role_keys")
    if isinstance(role_keys, list) and len(role_keys) > 1:
        short_roles = {
            "departure": "DEP",
            "destination": "DEST",
            "alternate": "ALTN",
            "edto": "EDTO",
            "fuel_enroute_airport": "FUEL ENROUTE",
        }
        role = " / ".join(
            short_roles.get(str(value), str(value).replace("_", " ").upper())
            for value in role_keys
            if value
        )
    else:
        roles = panel_data.get("roles")
        role = (
            " / ".join(str(value).upper() for value in roles if value)
            if isinstance(roles, list)
            else ""
        )
        role = role or str(panel_data.get("role") or "airport").upper()
    icao = str(panel_data.get("icao") or "----").upper()
    title = (
        f"{icao} - CONT. "
        f"({panel_data.get('_station_fragment_index')}/"
        f"{panel_data.get('_station_fragment_count')})"
        if panel_data.get("_continued")
        else f"{icao} - {role}"
    )
    inner = panel(canvas, x, y, w, h, title=title, accent=accent, title_colour=None)
    ix, iy, iw, ih = inner
    row_y = y + h - 31
    floor_y = iy + 2
    planned_rows = panel_data.get("_station_card_rows")
    rows = (
        list(planned_rows)
        if isinstance(planned_rows, list)
        else _station_card_lines(panel_data)
    )
    for label, value in rows:
        label_width = min(
            56.0,
            max(34.0, pdfmetrics.stringWidth(label, MONO_BOLD, T_MICRO) + 6),
        )
        lines = (
            list(value)
            if isinstance(value, list)
            else _wrap(value, SANS, T_MICRO, iw - label_width) or [""]
        )
        required_floor = row_y - (len(lines) - 1) * 9.5
        if required_floor < floor_y:
            raise ValueError(
                f"Airport-role card {icao}/{role} exceeds readable capacity; "
                "split the shared panel before drawing."
            )
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(MONO_BOLD, T_MICRO)
        _draw_string_fitted(canvas, ix, row_y, label, MONO_BOLD, T_MICRO, label_width - 4, TEXT_MUTED)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_MICRO)
        for line in lines:
            canvas.drawString(ix + label_width, row_y, line)
            row_y -= STATION_CARD_LINE_HEIGHT


def _sigmet_card_fragments(
    cards: list[dict[str, Any]],
    *,
    text_width: float,
    lines_per_fragment: int = 4,
) -> list[dict[str, Any]]:
    """Keep every screening sentence via same-section card continuations."""
    fragments: list[dict[str, Any]] = []
    for card in cards:
        lines = _wrap(
            str(card.get("screening") or ""),
            SANS,
            T_MICRO,
            text_width,
        ) or [""]
        for index in range(0, len(lines), lines_per_fragment):
            fragment = dict(card)
            fragment["_screen_lines"] = lines[index:index + lines_per_fragment]
            fragment["_continued"] = index > 0
            fragments.append(fragment)
    return fragments


def _vaac_ledger_lines(
    centres: list[dict[str, Any]],
    *,
    text_width: float,
) -> list[str]:
    """Wrap every shared VAAC centre/status row without fitting or elision."""
    lines: list[str] = []
    for start_index in range(0, len(centres), 3):
        row = " | ".join(
            f"{item.get('centre')}: {item.get('status')}"
            for item in centres[start_index:start_index + 3]
        )
        lines.extend(_wrap(row, MONO, T_MICRO, text_width) or [row])
    return lines


def _hazard_vaac_line_capacity(
    sigmet_cards: list[dict[str, Any]],
    vaa_advisories: list[dict[str, Any]],
) -> int:
    """Measure VAAC baselines left after this page's other hazard content."""
    y = PAGE_SIZE[1] - 94.0 - 6.0
    for advisory in vaa_advisories:
        y -= T_BODY + 6.0
        if advisory.get("derived"):
            advisory_lines = _wrap(
                str(advisory["derived"]),
                SANS,
                T_SMALL,
                PAGE_SIZE[0] - 2 * MARGIN,
            )[:3]
            y -= len(advisory_lines) * (T_SMALL + 3.5)
        y -= 4.0

    columns_bottom = 30.0 + 150.0 + 10.0
    card_y = y
    for card in sigmet_cards:
        screen_lines = card.get("_screen_lines") or []
        card_height = 34.0 + 12.0 + len(screen_lines) * 9.6
        card_y -= card_height + 8.0
    if not sigmet_cards:
        card_y -= 48.0
    ledger_height = max(96.0, card_y - columns_bottom)
    first_vaac_y = card_y - 28.0 - 11.0 - 13.0 - 4 * 11.0
    minimum_y = card_y - ledger_height + 12.0
    if first_vaac_y < minimum_y:
        return 0
    return int((first_vaac_y - minimum_y) // 10.0) + 1


def _hazard_page_plans(
    sigmet_pages: list[list[dict[str, Any]]],
    advisory_pages: list[list[dict[str, Any]]],
    wafc_pages: list[list[dict[str, Any]]],
    vaac_lines: list[str],
) -> list[dict[str, Any]]:
    """Assign measured VAAC lines across hazard pages and continuations."""
    base_page_count = max(
        len(sigmet_pages),
        len(advisory_pages),
        len(wafc_pages),
        1,
    )
    remaining = list(vaac_lines)
    plans: list[dict[str, Any]] = []
    page_index = 0
    while page_index < base_page_count or remaining:
        sigmets = (
            sigmet_pages[page_index]
            if page_index < len(sigmet_pages)
            else []
        )
        advisories = (
            advisory_pages[page_index]
            if page_index < len(advisory_pages)
            else []
        )
        wafc = (
            wafc_pages[page_index]
            if page_index < len(wafc_pages)
            else None
        )
        capacity = _hazard_vaac_line_capacity(sigmets, advisories)
        if remaining and capacity < 1 and page_index >= base_page_count:
            raise ValueError(
                "VAAC ledger cannot fit on an otherwise empty hazard page"
            )
        page_vaac_lines = remaining[:capacity]
        remaining = remaining[capacity:]
        plans.append({
            "sigmet_cards": sigmets,
            "vaa_advisories": advisories,
            "vaac_lines": page_vaac_lines,
            "wafc_charts": wafc,
        })
        page_index += 1
    return plans


def _analysis_hazard_summary(
    flight: dict[str, Any], briefing: dict[str, Any]
) -> str:
    hazards = briefing.get("hazards") or {}
    hazard_bits = [
        f"{card.get('name')}: {card.get('screening')}"
        for card in (hazards.get("sigmet_cards") or [])[:3]
    ]
    gaps = [
        row.get("label")
        for row in hazards.get("coverage_ledger") or []
        if str(row.get("status")) == "unavailable"
    ]
    if gaps:
        hazard_bits.append(
            f"{'/'.join(gaps)} carry no data in this CFP - coverage gaps, not NIL findings."
        )
    return " ".join(hazard_bits) or "No enroute SIGMET is printed in this CFP."


def _shared_communication_text(item: dict[str, Any]) -> str:
    """One exact shared communication row; no renderer shortening."""
    return " | ".join(
        value
        for value in (
            str(item.get("time") or "").strip(),
            str(item.get("actm") or "").strip(),
            str(item.get("event") or "").strip(),
            str(item.get("detail") or "").strip(),
        )
        if value
    ) or "Communication procedure requires review."


def _communication_continuation_fragments(
    item: dict[str, Any],
    *,
    text_width: float,
) -> list[dict[str, Any]]:
    """Split one shared row without dropping text or shrinking typography.

    Time and ACTM form the stable row identity.  If a row spans pages, that
    identity is repeated with ``CONT.`` while the event/detail text continues
    in order.  The derived underscore fields exist only for PDF pagination;
    the original shared fields remain untouched on every fragment.
    """
    identity = " | ".join(
        value
        for value in (
            str(item.get("time") or "").strip(),
            str(item.get("actm") or "").strip(),
        )
        if value
    ) or "FIR / CONTACT"
    content = " | ".join(
        value
        for value in (
            str(item.get("event") or "").strip(),
            str(item.get("detail") or "").strip(),
        )
        if value
    ) or "Communication procedure requires review."
    content_lines = _wrap(content, SANS, T_SMALL, text_width) or [content]
    max_lines = int(
        (ANALYSIS_COMMUNICATION_HEIGHT_BUDGET - ANALYSIS_COMMUNICATION_ROW_GAP)
        // ANALYSIS_COMMUNICATION_LINE_HEIGHT
    )
    fragments: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(content_lines):
        continued = bool(fragments)
        identity_text = f"{identity} | CONT." if continued else identity
        identity_lines = _wrap(
            identity_text,
            SANS_BOLD,
            T_SMALL,
            text_width,
        ) or [identity_text]
        content_capacity = max_lines - len(identity_lines)
        if content_capacity < 1:
            raise ValueError(
                "DECISION ANALYSIS communication identity exceeds readable "
                "continuation capacity"
            )
        content_chunk = content_lines[cursor:cursor + content_capacity]
        cursor += len(content_chunk)
        fragment = dict(item)
        fragment["_communication_lines"] = [
            *identity_lines,
            *content_chunk,
        ]
        fragment["_continued"] = continued
        fragment["_continues"] = cursor < len(content_lines)
        fragments.append(fragment)
    return fragments


def _analysis_communication_plan(
    flight: dict[str, Any], briefing: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Fit exact shared comms on page 2, then paginate deterministic overflow."""
    communications = [
        dict(item)
        for item in briefing.get("communications") or []
        if isinstance(item, dict)
    ]
    if not communications:
        return [], []

    full_w = PAGE_SIZE[0] - 2 * MARGIN
    card_width = (full_w - 22.0) / 2.0 - 20.0
    base = _analysis_hazard_summary(flight, briefing)
    primary: list[dict[str, Any]] = []
    for item in communications:
        candidate_rows = [*primary, item]
        candidate = (
            base
            + " FIR / NEXT CONTACT: "
            + " | ".join(_shared_communication_text(row) for row in candidate_rows)
        )
        # Eight lines fit the measured REV3 analysis card without reducing
        # type. Once the next exact row does not fit, preserve it on a
        # same-section continuation instead of eliding it.
        if len(_wrap(candidate, SANS, T_SMALL, card_width)) > 8:
            break
        primary.append(item)

    overflow = communications[len(primary):]
    continuation_text_width = (
        PAGE_SIZE[0] - 2 * MARGIN - 20.0 - 84.0
    )
    fragments = [
        fragment
        for item in overflow
        for fragment in _communication_continuation_fragments(
            item,
            text_width=continuation_text_width,
        )
    ]
    pages: list[list[dict[str, Any]]] = []
    current_page: list[dict[str, Any]] = []
    current_height = 0.0
    for fragment in fragments:
        fragment_height = (
            len(fragment["_communication_lines"])
            * ANALYSIS_COMMUNICATION_LINE_HEIGHT
            + ANALYSIS_COMMUNICATION_ROW_GAP
        )
        if current_page and (
            current_height + fragment_height
            > ANALYSIS_COMMUNICATION_HEIGHT_BUDGET
        ):
            pages.append(current_page)
            current_page = []
            current_height = 0.0
        if fragment_height > ANALYSIS_COMMUNICATION_HEIGHT_BUDGET:
            raise ValueError(
                "DECISION ANALYSIS communication fragment exceeds readable "
                "continuation capacity"
            )
        current_page.append(fragment)
        current_height += fragment_height
    if current_page:
        pages.append(current_page)
    return primary, pages


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
    edto_rows = _shared_edto_operational_rows(briefing)

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
    canvas.setFillColor(_page_colour(canvas, "elevated", ELEVATED))
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
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
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
    page_hint: int | None = 0,
    source_pages: list[int] | None = None,
    pad_x: float = 26.0,
    pad_y: float = 16.0,
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
            provenance_indexes = [
                page_number - 1
                for page_number in (source_pages or [])
                if isinstance(page_number, int) and page_number > 0
            ]
            if page_hint is not None and page_hint >= 0:
                provenance_indexes.append(page_hint)
            indexes: list[int] = []
            for index in [*provenance_indexes, *range(len(document))]:
                if 0 <= index < len(document) and index not in indexes:
                    indexes.append(index)
            for index in indexes:
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
                    # printed column so lines are never cut mid-word. Trim the
                    # source page's blank side margins from the raster; keeping
                    # them made a relevant EDTO table unreadably small inside
                    # an otherwise wide report panel.
                    vertical_clip = fitz.Rect(
                        page.rect.x0 + 24,
                        max(0, rect.y0 - pad_y),
                        page.rect.x1 - 24,
                        bottom,
                    )
                    words = page.get_text("words", clip=vertical_clip)
                    if words:
                        content_x0 = min(float(word[0]) for word in words)
                        content_x1 = max(float(word[2]) for word in words)
                        clip = fitz.Rect(
                            max(vertical_clip.x0, content_x0 - pad_x),
                            vertical_clip.y0,
                            min(vertical_clip.x1, content_x1 + pad_x),
                            vertical_clip.y1,
                        )
                    else:
                        clip = vertical_clip
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


def _draw_crop(
    canvas,
    crop: dict[str, Any] | None,
    x,
    y,
    w,
    h,
    *,
    missing_text: str,
    dpi: int = 220,
    fill_sheet: bool = False,
    fit_to_panel: bool = False,
) -> None:
    from io import BytesIO

    from reportlab.lib.utils import ImageReader

    if not crop:
        review_line(canvas, x + 8, y + h / 2, missing_text)
        return
    # A crop is evidence: render at up to its printed size, never enlarged
    # into a poster.
    if fit_to_panel:
        aspect = crop["width"] / max(1, crop["height"])
        draw_w = max(1.0, w - 2 * _CROP_PAD)
        draw_h = draw_w / aspect
        if draw_h > h - 2 * _CROP_PAD:
            draw_h = max(1.0, h - 2 * _CROP_PAD)
            draw_w = draw_h * aspect
    else:
        draw_w, draw_h = _crop_image_dimensions(crop, w, h, dpi=dpi)
    sheet_w = w if fill_sheet else draw_w + 2 * _CROP_PAD
    sheet_h = h if fill_sheet else draw_h + 2 * _CROP_PAD
    sheet_x = x + (w - sheet_w) / 2
    sheet_y = y + h - sheet_h
    canvas.setFillColor(colors.white)
    canvas.roundRect(sheet_x, sheet_y, sheet_w, sheet_h, 3, stroke=0, fill=1)
    image_x = sheet_x + (sheet_w - draw_w) / 2
    image_y = sheet_y + sheet_h - draw_h - _CROP_PAD
    canvas.drawImage(
        ImageReader(BytesIO(crop["png"])),
        image_x, image_y,
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
    fuel_summary = flight.get("fuel_summary") or {}
    performance_publication = _shared_performance_publication(briefing)
    ptow = performance_publication.get("ptow_kg")
    selected = performance_publication.get("selected_rtow_kg")
    margin_kg = performance_publication.get("margin_kg")
    margin_value, margin_caption, margin_accent = (
        _performance_margin_presentation(performance_publication)
    )
    selected_caption, selected_accent = _performance_selected_presentation(
        performance_publication
    )
    candidates_by_key = {
        item.get("key"): item.get("limit_kg")
        for item in performance_publication.get("candidate_limits") or []
    }
    structural = candidates_by_key.get("structural")
    perf_rtow = candidates_by_key.get("performance")

    def kg_label(value):
        return f"{value:,} kg" if value else "--"

    card_w = (full_w - 4 * 10) / 5
    card_h = 44.0
    cards_y = y - card_h
    stat_card(canvas, MARGIN, cards_y, card_w, card_h, label="PTOW", value=kg_label(ptow), caption="planned mass", accent=DEPARTURE)
    stat_card(canvas, MARGIN + (card_w + 10), cards_y, card_w, card_h, label="SELECTED RTOW", value=kg_label(selected), caption=selected_caption, accent=selected_accent)
    stat_card(canvas, MARGIN + 2 * (card_w + 10), cards_y, card_w, card_h, label="MARGIN", value=margin_value, caption=margin_caption, accent=margin_accent)
    stat_card(canvas, MARGIN + 3 * (card_w + 10), cards_y, card_w, card_h, label="RTOW STRUCT", value=kg_label(structural), caption=(f"+{structural - ptow:,} kg" if structural is not None and ptow is not None else ""), accent=CRITICAL)
    stat_card(canvas, MARGIN + 4 * (card_w + 10), cards_y, card_w, card_h, label="RTOW PERF", value=kg_label(perf_rtow), caption=(f"+{perf_rtow - ptow:,} kg" if perf_rtow is not None and ptow is not None else ""), accent=DEPARTURE)

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
            canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
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
        source_line="CFP page 1 declarations | source-bounded MEL/CDL crops",
        page_family="deep",
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
        raw_item_type = str(item.get("item_type") or "").strip().upper()
        item_type = deferred_item_type_for_display(raw_item_type)
        reference = deferred_reference_for_display(item.get("reference"))
        declaration = deferred_source_declaration_for_display(
            item.get("source_declaration")
        )
        title = (
            declaration
            if item_type == "DEFERRED ITEM" and declaration
            else " ".join(value for value in (item_type, reference) if value)
        ) or "DEFERRED ITEM - REVIEW REQUIRED"
        inner = panel(canvas, cx, card_bottom, card_w, card_h, title=title, accent=accents[index % 4], title_colour=BG if accents[index % 4] in (EDTO_GREEN, COMMS_TEAL, WEATHER_AMBER) else colors.white)
        ix, iy, iw, ih = inner
        headline = str(item.get("description") or "").strip().upper() or "SEE CROPPED SOURCE BELOW"
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO_BOLD, 9.0)
        _draw_string_fitted(canvas, ix, card_top - 34, headline[:64], MONO_BOLD, 9.0, iw, TEXT)
        remark = str(item.get("company_remark") or "").strip()
        if raw_item_type not in {"", "UNCLASSIFIED", "UNSPECIFIED", "UNKNOWN"}:
            body = (
                f"CFP REMARK - NOT THE APPROVED {raw_item_type} REMEDY: {remark}"
                if remark
                else (
                    f"CFP declaration only. The approved {raw_item_type} remedy must be read "
                    "from the exact governed item."
                )
            )
        else:
            body = (
                f"CFP DECLARATION - REVIEW REQUIRED: {remark}"
                if remark
                else (
                    "CFP declaration requires review; no MEL, CDL or CDDL "
                    "classification or remedy is inferred."
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
        source_label = f"OPEN EXACT {raw_item_type} ITEM / REMEDY >" if source_target else ""
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
        deferred_source_pages = [
            item.get("source_page")
            for item in deferred
            if isinstance(item.get("source_page"), int)
        ]
        crop = (
            crop_source_region(
                source_pdf_path,
                needle="ATTN ALL CONCERN",
                end_needle="RTE NO",
                page_hint=0,
                source_pages=deferred_source_pages,
                pad_y=8,
                full_width=True,
            )
            or (
                crop_source_region(
                    source_pdf_path,
                    needle=first_reference,
                    page_hint=0,
                    source_pages=deferred_source_pages,
                    pad_y=10,
                    full_width=True,
                )
                if first_reference and first_reference != "UNSPECIFIED"
                else None
            )
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
    cards: list[dict[str, Any]] | None = None,
    section_page_number: int = 1,
    section_page_count: int = 1,
    compact_overflow_note: str | None = None,
) -> None:
    width, height = PAGE_SIZE
    classification = _edto_classification(flight)
    non_edto = classification.startswith("NON")
    classification_label = classification or "EDTO REVIEW"
    section_label = (
        "DESTINATION ALTERNATES"
        if non_edto
        else "EDTO / ENROUTE AIRPORTS"
    )
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line=" | ".join(
            value
            for value in (
                (
                    "CFP alternate-planning summary"
                    if non_edto
                    else "CFP EDTO table"
                ),
                (
                    f"{classification_label} classification"
                    if non_edto
                    else f"{classification_label} status"
                ),
                (
                    "selected destination-alternate source facts"
                    if non_edto
                    else "selected enroute-airport source facts"
                ),
                compact_overflow_note,
            )
            if value
        ),
        section_label=(
            section_label
            + _continuation_suffix(section_page_number, section_page_count)
        ),
        section_colour=EDTO_GREEN,
    )
    if section_page_number == 1:
        canvas.bookmarkPage("sec_alternates")
    y = content_top - 6

    full_w = width - 2 * MARGIN
    card_gap = 10.0
    cards_per_page = 1 if non_edto else EDTO_CARDS_PER_PAGE
    card_w = (
        full_w
        if non_edto
        else (full_w - 2 * card_gap) / EDTO_CARDS_PER_PAGE
    )
    # Shared cards are already compact, source-derived publication summaries.
    # The canonical three-card row therefore keeps the measured shallow
    # geometry; higher-cardinality content continues instead of stretching
    # this primary page and shrinking the authoritative source crop.
    card_h = (
        NON_EDTO_CLASSIFICATION_CARD_HEIGHT
        if non_edto
        else EDTO_CARD_HEIGHT
    )
    card_bottom = y - card_h
    page_cards = list(cards or [])
    if len(page_cards) > cards_per_page:
        raise ValueError("Classification page received more cards than its readable capacity")
    accents = (EDTO_GREEN, DESTINATION, COMMS_TEAL)
    for index, card in enumerate(page_cards):
        card_x = MARGIN + index * (card_w + card_gap)
        if card.get("kind") != "status":
            _draw_station_card(
                canvas,
                card,
                card_x,
                card_bottom,
                card_w,
                card_h,
                accent=accents[index % len(accents)],
            )
            continue
        title = (
            (
                "CLASSIFICATION"
                if section_page_number == 1 and index == 0
                else "CLASSIFICATION CONTINUED"
            )
            if non_edto
            else (
                "EDTO BOUNDARY / STATUS"
                if section_page_number == 1 and index == 0
                else "EDTO STATUS CONTINUED"
            )
        )
        inner = panel(
            canvas,
            card_x,
            card_bottom,
            card_w,
            card_h,
            title=title,
            accent=EDTO_GREEN,
            title_colour=None,
        )
        ix, iy, iw, ih = inner
        row_y = y - 31
        for label, lines in card.get("rows") or []:
            label_text = str(label)
            inline_width = iw - 76.0
            inline = (
                len(lines) == 1
                and pdfmetrics.stringWidth(lines[0], SANS, T_SMALL) <= inline_width
            )
            required_height = (1 if inline else 1 + len(lines)) * 9.8 + 1.2
            if row_y - required_height < iy:
                raise ValueError(
                    "Classification card exceeds readable capacity; continue its "
                    "shared rows instead of drawing below the card."
                )
            canvas.setFillColor(EDTO_GREEN if label == "CLASSIFICATION" else TEXT_MUTED)
            canvas.setFont(SANS_BOLD, T_MICRO)
            canvas.drawString(ix, row_y, label_text)
            if inline:
                canvas.setFillColor(TEXT)
                canvas.setFont(SANS, T_SMALL)
                canvas.drawString(ix + 76.0, row_y, lines[0])
                row_y -= 9.8
                row_y -= 1.2
                continue
            row_y -= 9.8
            for line in lines:
                canvas.setFillColor(TEXT)
                canvas.setFont(SANS, T_SMALL)
                canvas.drawString(ix, row_y, line)
                row_y -= 9.8
            row_y -= 1.2

    if not page_cards:
        inner = panel(
            canvas,
            MARGIN,
            card_bottom,
            full_w,
            card_h,
            title=("CLASSIFICATION" if non_edto else f"{classification_label} STATUS"),
            accent=WEATHER_AMBER,
            title_colour=None,
        )
        review_line(
            canvas,
            inner[0],
            inner[1] + inner[3] / 2,
            (
                "No parsed classification or destination-alternate facts are held - review the CFP."
                if non_edto
                else "No parsed EDTO or selected enroute-airport facts are held - review the CFP."
            ),
        )

    # Put the exact airline source beneath the selected cards. Continuations
    # repeat the governed crop so no operational row is separated from its
    # controlling source context.
    source_top = card_bottom - 10
    source_h = source_top - 30
    if non_edto:
        crop = crop_source_region(
            source_pdf_path,
            needle="FLT PLANNING ALTN SUMMARY",
            end_needle="EXCESS FUEL REASON",
            page_hint=1,
            pad_y=8,
            full_width=True,
        ) or crop_source_region(
            source_pdf_path,
            needle="ALTN/RWY",
            page_hint=1,
            pad_y=14,
            full_width=True,
        )
        source_title = "CFP ALTERNATE PLANNING - CROPPED RELEVANT SECTION"
        missing_source = (
            "Alternate-planning source section unavailable for cropping - "
            "review the uploaded CFP."
        )
    else:
        source_classification = _edto_source_classification(flight)
        edto_source_pages = [
            item.get("source_page")
            for item in ((briefing.get("edto") or {}).get("assessment") or {}).get(
                "evidence", []
            )
            if isinstance(item, dict) and isinstance(item.get("source_page"), int)
        ]
        crop = crop_source_region(
            source_pdf_path,
            needle="EDTO INFORMATION",
            page_hint=0,
            source_pages=edto_source_pages,
            pad_y=90,
            full_width=True,
        ) or crop_source_region(
            source_pdf_path,
            needle=(
                f"SUMMARY {source_classification} CFP"
                if source_classification
                else "SUMMARY EDTO CFP"
            ),
            page_hint=0,
            source_pages=edto_source_pages,
            pad_y=8,
            full_width=True,
        )
        source_title = "CFP EDTO TABLE - CROPPED RELEVANT SECTION"
        missing_source = (
            "EDTO source section unavailable for cropping - review the uploaded CFP."
        )
    inner = panel(
        canvas,
        MARGIN,
        30,
        full_w,
        source_h,
        title=source_title,
        accent=EDTO_GREEN,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    _draw_crop(
        canvas,
        crop,
        ix,
        iy + 4,
        iw,
        ih - 8,
        missing_text=missing_source,
        fill_sheet=True,
        fit_to_panel=True,
    )


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
    panels: list[dict[str, Any]] | None = None,
    route_profile_rows: list[tuple[str, str]] | None = None,
    section_page_number: int = 1,
    section_page_count: int = 1,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="Selected CFP weather + time-applicable NOTAM source facts by operational airport role",
        section_label=(
            "AIRPORTS / NOTAM APPLICABILITY"
            + _continuation_suffix(section_page_number, section_page_count)
        ),
        section_colour=DESTINATION,
    )
    if section_page_number == 1:
        canvas.bookmarkPage("sec_airports")
    y = content_top - 6

    full_w = width - 2 * MARGIN
    page_panels = list(panels or [])
    page_route_profile_rows = list(route_profile_rows or [])
    if page_panels and page_route_profile_rows:
        raise ValueError(
            "An AIRPORT page cannot mix selected station cards with the "
            "verbatim route/profile continuation."
        )
    if len(page_panels) > AIRPORT_OPERATIONAL_PANELS_PER_PAGE:
        raise ValueError("Airport page received more selected panels than its capacity")
    if page_route_profile_rows:
        if len(page_route_profile_rows) > AIRPORT_ROUTE_PROFILE_ROWS_PER_PAGE:
            raise ValueError("AIRPORT route/profile continuation exceeds page capacity")
        inner = panel(
            canvas,
            MARGIN,
            30,
            full_w,
            y - 30,
            title="CFP ROUTE AND LEVEL PROFILE - VERBATIM CONTINUATION",
            accent=ACCENT,
            title_colour=None,
        )
        ix, iy, iw, ih = inner
        label_width = 82.0
        row_y = y - 31
        for label, value in page_route_profile_rows:
            if row_y < iy + 3:
                raise ValueError(
                    "AIRPORT route/profile continuation exceeds readable capacity"
                )
            canvas.setFillColor(TEXT_MUTED)
            canvas.setFont(MONO_BOLD, T_MICRO)
            canvas.drawString(ix, row_y, label)
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(MONO, T_MICRO)
            canvas.drawString(ix + label_width, row_y, value)
            row_y -= 10.5
        return
    if not page_panels:
        inner = panel(
            canvas,
            MARGIN,
            30,
            full_w,
            y - 30,
            title="SELECTED AIRPORT ROLES",
            accent=WEATHER_AMBER,
            title_colour=None,
        )
        review_line(
            canvas,
            inner[0],
            inner[1] + inner[3] / 2,
            "No selected airport-role source panel is held - review the uploaded CFP.",
        )
        return

    # REV3 page 5 is a 3 + 2 card mosaic.  The first row is DEP / DEST /
    # preferred alternate; EDTO and fuel-enroute use the wider lower row.
    # Continuations repeat the same deterministic geometry for their selected
    # panels rather than shrinking the text or silently dropping a station.
    gap = 10.0
    available_h = y - 30
    row_h = (available_h - gap) / 2
    first_row = page_panels[:3]
    second_row = page_panels[3:]
    accent_by_role = {
        "departure": DEPARTURE,
        "destination": DESTINATION,
        "alternate": WEATHER_AMBER,
        "edto": EDTO_GREEN,
        "fuel_enroute_airport": COMMS_TEAL,
    }

    def panel_accent(panel_data):
        panel_role_keys = set(panel_data.get("role_keys") or [])
        panel_role_keys.add(str(panel_data.get("role_key") or ""))
        if "fuel_enroute_airport" in panel_role_keys:
            return COMMS_TEAL
        if "edto" in panel_role_keys:
            return EDTO_GREEN
        return accent_by_role.get(
            str(panel_data.get("role_key") or ""), ACCENT
        )

    if len(page_panels) == 1 and page_panels[0].get("_station_full_page"):
        _draw_station_card(
            canvas,
            page_panels[0],
            MARGIN,
            30,
            full_w,
            available_h,
            accent=panel_accent(page_panels[0]),
        )
        return

    def draw_row(row_panels, row_y, column_count):
        if not row_panels:
            return
        card_w = (full_w - gap * (column_count - 1)) / column_count
        for index, panel_data in enumerate(row_panels):
            _draw_station_card(
                canvas,
                panel_data,
                MARGIN + index * (card_w + gap),
                row_y,
                card_w,
                row_h,
                accent=panel_accent(panel_data),
            )

    draw_row(first_row, y - row_h, 3)
    draw_row(second_row, 30, 2)


# ---------------------------------------------------------------------------
# Page 8 — OPERATIONAL HAZARD ASSESSMENT.
# ---------------------------------------------------------------------------


def draw_hazard_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    weather_chart_selection: dict[str, Any] | None,
    *,
    page_number: int,
    page_count: int,
    source_pdf_path: str | None,
    sigmet_cards: list[dict[str, Any]] | None = None,
    vaa_advisories: list[dict[str, Any]] | None = None,
    vaac_lines: list[str] | None = None,
    wafc_charts: list[dict[str, Any]] | None = None,
    section_page_number: int = 1,
    section_page_count: int = 1,
) -> None:
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line="CFP weather snapshot | held SIGMET/VAA reviews | package WAFC fixed-time charts",
        section_label=(
            "OPERATIONAL HAZARD ASSESSMENT"
            + _continuation_suffix(section_page_number, section_page_count)
        ),
        section_colour=WEATHER_AMBER,
        page_family="deep",
    )
    if section_page_number == 1:
        canvas.bookmarkPage("sec_hazard")
    y = content_top - 6

    # Named volcanic-ash advisories lead the page: the label, the derived
    # closest-approach screening, then everything else (boss, 18 Aug).
    selected_advisories = (
        list(vaa_advisories)
        if vaa_advisories is not None
        else list((briefing.get("vaa") or {}).get("cfp_advisories") or [])
    )
    for advisory in selected_advisories:
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
    cards = (
        list(sigmet_cards)
        if sigmet_cards is not None
        else list((briefing.get("hazards") or {}).get("sigmet_cards") or [])
    )
    if len(cards) > SIGMET_CARDS_PER_PAGE:
        raise ValueError("Hazard page received more SIGMET cards than its capacity")
    ledger_rows = (briefing.get("hazards") or {}).get("coverage_ledger") or []

    card_accents = {
        "PROMOTED": CRITICAL,
        "NOT PROMOTED": WEATHER_AMBER,
        "REVIEW REQUIRED": COMMS_TEAL,
    }
    card_y = y
    for card in cards:
        screen_lines = card.get("_screen_lines") or _wrap(
            str(card.get("screening") or ""), SANS, T_MICRO, half_w - 28
        )
        card_h = 34 + 12 + len(screen_lines) * 9.6
        if card_y - card_h < columns_bottom + 96:
            raise ValueError(
                "SIGMET verdict card exceeds readable hazard-page capacity; "
                "continue it on another page."
            )
        accent = card_accents.get(str(card.get("disposition") or ""), WEATHER_AMBER)
        card_title = str(card.get("name") or "SIGMET")[:52].upper()
        if card.get("_continued"):
            card_title += " - CONT."
        panel(canvas, MARGIN, card_y - card_h, half_w, card_h,
              title=card_title, accent=accent, title_colour=None)
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
    # Verbatim from the briefing view - the tally and centre strings are
    # composed once in build_briefing_view for every surface.
    vaac_reach = (briefing.get("hazards") or {}).get("vaac_reach") or {}
    # The Doc 9766 route-responsibility fact rides on the existing VAAC row
    # (boss, 21 Aug: "there's a VAAC ... in Manila?") - a separate row blew
    # the ledger's readable capacity on full hazard pages.
    responsible_rows = list(vaac_reach.get("responsible") or [])
    if responsible_rows:
        responsible_compact = "RESP " + "+".join(
            f"{row.get('centre')}{'' if row.get('reached') else '(GAP)'}"
            for row in responsible_rows
        )
    else:
        responsible_compact = "RESP UNRESOLVED"
    vaac_centres_status = " | ".join((
        str(vaac_reach.get("summary") or "0/9 reached"),
        responsible_compact,
    ))
    for label, status in (
        ("SIGMET REVIEW", str(((flight.get("sigmet_review") or {}).get("status")) or "no data in CFP")),
        ("VA REVIEW", str(vaa_review.get("status") or "no data in CFP")),
        ("TC REVIEW", str(((flight.get("tropical_cyclone_review") or {}).get("status")) or "no data in CFP")),
        ("VAAC CENTRES", vaac_centres_status),
    ):
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(MARGIN + 14, row_y, label)
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        _draw_string_fitted(canvas, MARGIN + 110, row_y, status.replace("_", " "), SANS_BOLD, T_MICRO, half_w - 140, WEATHER_AMBER)
        row_y -= 11
    selected_vaac_lines = (
        list(vaac_lines)
        if vaac_lines is not None
        else _vaac_ledger_lines(
            list(vaac_reach.get("centres") or []),
            text_width=half_w - 28.0,
        )
    )
    for centre_line in selected_vaac_lines:
        if row_y < ledger_top - ledger_h + 12:
            raise ValueError(
                "VAAC centre ledger exceeds readable hazard-page capacity; "
                "continue it on another page."
            )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(MONO, T_MICRO)
        canvas.drawString(MARGIN + 14, row_y, centre_line)
        row_y -= 10

    # The CFP's own weather page, cropped as printed - the source beside the
    # verdicts, exactly as the canon lays it out.
    right_x = MARGIN + half_w + 22
    right_h = y - columns_bottom
    panel(canvas, right_x, y - right_h, half_w, right_h,
          title="CFP SIGMET / WEATHER SOURCE", accent=WEATHER_AMBER, title_colour=None)
    weather_source_pages = [
        record.get("source_page")
        for record in flight.get("weather") or []
        if isinstance(record, dict) and isinstance(record.get("source_page"), int)
    ]
    wx_crop = crop_source_region(
        source_pdf_path,
        needle="Airport WX List",
        end_needle="DESTINATION ALTERNATE",
        page_hint=None,
        source_pages=weather_source_pages,
        pad_y=10,
    ) or crop_source_region(
        source_pdf_path,
        needle="SIGMETs:",
        page_hint=None,
        source_pages=weather_source_pages,
        pad_y=14,
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
    selection = weather_chart_selection or {}
    charts = list(wafc_charts or [])
    if len(charts) > WAFC_CHARTS_PER_PAGE:
        raise ValueError("Hazard page received more selected WAFC charts than its capacity")
    if charts:
        from io import BytesIO

        from reportlab.lib.utils import ImageReader

        from .weather_charts import extract_chart_image

        tile_w = (iw3 - 2 * 10) / 3
        tile_h = ih3 - 22
        for index, chart in enumerate(charts):
            tx = ix3 + index * (tile_w + 10)
            valid = str(
                chart.get("valid_time_utc")
                or chart.get("valid_time")
                or chart.get("issued_time")
                or ""
            )
            kind_label = str(
                chart.get("kind") or "chart"
            ).replace("_", " ").upper()
            shared_label = str(chart.get("label") or "").strip()
            chart_label = shared_label or " | ".join(
                part for part in (kind_label, valid) if part
            )
            label_lines = _wrap(
                chart_label,
                MONO_BOLD,
                T_MICRO,
                tile_w - 6,
            ) or [chart_label]
            if len(label_lines) > 4:
                raise ValueError(
                    "Selected WAFC chart label exceeds readable tile capacity"
                )
            extra_label_height = (len(label_lines) - 1) * 9.0
            image_y = iy3 + 16 + extra_label_height
            image_h = tile_h - extra_label_height
            raw = None
            if source_pdf_path:
                try:
                    raw = extract_chart_image(
                        source_pdf_path, int(chart.get("page_number"))
                    )
                except Exception:
                    raw = None
            if raw:
                expected_sha256 = str(
                    chart.get("image_sha256") or ""
                ).strip().lower()
                actual_sha256 = hashlib.sha256(raw).hexdigest()
                if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
                    raise ValueError(
                        "Selected WAFC chart is missing its shared source "
                        "image SHA-256"
                    )
                if actual_sha256 != expected_sha256:
                    raise ValueError(
                        "Selected WAFC chart source image SHA-256 mismatch; "
                        "publication stopped before drawing a swapped or "
                        "changed page"
                    )
                image = ImageReader(BytesIO(raw))
                canvas.setFillColor(colors.white)
                canvas.roundRect(tx, image_y, tile_w, image_h, 3, stroke=0, fill=1)
                canvas.drawImage(image, tx + 3, image_y + 3, width=tile_w - 6, height=image_h - 6, preserveAspectRatio=True, mask="auto")
            else:
                canvas.setFillColor(TEXT_SECONDARY)
                canvas.setFont(SANS_BOLD, T_MICRO)
                canvas.drawCentredString(
                    tx + tile_w / 2,
                    image_y + image_h / 2,
                    "Selected source image unavailable - review package.",
                )
            canvas.setFillColor(WEATHER_AMBER)
            canvas.setFont(MONO_BOLD, T_MICRO)
            label_y = iy3 + 6 + extra_label_height
            for line in label_lines:
                canvas.drawString(tx + 3, label_y, line)
                label_y -= 9.0
    else:
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS_BOLD, T_SMALL)
        raw_count = int(selection.get("raw_chart_count") or 0)
        if wafc_charts is None and selection.get("status") == "selected":
            lines = [
                "SELECTED ROUTE-CONTEXT WAFC CHARTS PRINTED ON AN EARLIER SECTION PAGE.",
                f"RAW CHARTS HELD: {raw_count}",
            ]
        else:
            status = str(selection.get("status") or "unavailable").replace("-", " ").upper()
            reason = str(
                selection.get("reason")
                or "No governed route-context weather chart selection is held."
            )
            lines = [
                f"{status} - {reason}",
                f"RAW CHARTS HELD: {raw_count} | NOT PUBLISHED WITHOUT GOVERNED ROUTE MATCH",
            ]
        row_y = 30 + strip_h / 2 + 5
        for value in lines:
            for line in _wrap(value, SANS_BOLD, T_SMALL, iw3 - 20):
                canvas.drawCentredString(MARGIN + full_w / 2, row_y, line)
                row_y -= 11


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
    communications: list[dict[str, Any]] | None = None,
    compact_overflow_note: str | None = None,
) -> None:
    """REV3 page 2 - DECISION ANALYSIS: the decision timeline over six prose
    verdict cards, every sentence composed from the same view the other
    surfaces print."""
    width, height = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas, flight,
        page_number=page_number, page_count=page_count,
        source_line=" | ".join(
            value
            for value in (
                "CFP-derived deterministic verdicts",
                "no unsupported hazard inference",
                compact_overflow_note,
            )
            if value
        ),
        section_label="DECISION ANALYSIS",
    )
    canvas.bookmarkPage("sec_analysis")
    canvas.bookmarkPage("sec_time")
    y = content_top - 4

    # FLIGHT-PHASE DECISION TIMELINE band - REV3 measured: a slim strip
    # hugging the header rule.
    strip_h = 66.0
    inner = panel(canvas, MARGIN, y - strip_h, width - 2 * MARGIN, strip_h,
                  title="FLIGHT-PHASE DECISION TIMELINE", accent=PANEL, title_colour=TEXT)
    _timeline(canvas, MARGIN + 25, y - strip_h + 21, width - 2 * MARGIN - 50,
              _route_anchor_entries(flight, briefing))
    # The timeline names its clock basis (boss, 21 Aug R2-14) — composed once
    # in the view so the dashboard and the PDF say the same sentence.
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, 7.2)
    canvas.drawString(
        inner[0],
        y - strip_h + 7,
        str((briefing.get("flight_identity") or {}).get("timeline_basis") or ""),
    )
    y -= strip_h + 16

    fuel_summary = flight.get("fuel_summary") or {}
    rows_data = fuel_summary.get("rows") or {}
    edto_view = briefing.get("edto") or {}
    deferred = flight.get("deferred_items") or []
    departure_panel = briefing.get("departure") or {}
    destination_panel = briefing.get("destination") or {}
    alternates = flight.get("alternates") or []

    performance_publication = _shared_performance_publication(briefing)
    selected_rtow = performance_publication.get("selected_rtow_kg")
    ptow = performance_publication.get("ptow_kg")
    margin_kg = performance_publication.get("margin_kg")
    tanks = (rows_data.get("fuel_in_tanks") or {}).get("fuel_kg")
    reqmt = (rows_data.get("flt_plan_reqmt") or {}).get("fuel_kg")
    excess = (rows_data.get("excess_fuel") or {}).get("fuel_kg")
    perf_text = " ".join(part for part in (
        f"RTOW {selected_rtow:,} kg."
        if selected_rtow is not None
        else "RTOW not derived - review CFP performance page.",
        (
            f"PTOW {ptow:,} kg gives {margin_kg:,} kg margin."
            if margin_kg is not None
            else "PTOW/RTOW margin unavailable - performance review required."
        ),
        (
            f"Fuel in tanks {'equals' if tanks == reqmt else 'exceeds'} the {reqmt:,} kg flight-plan requirement; "
            f"excess fuel is {excess or 0:,} kg."
            if tanks is not None and reqmt is not None else None
        ),
        f"A 1,000 kg ZFW change moves burn {flight.get('zfw_change_burn_kg_per_1000')} kg." if flight.get("zfw_change_burn_kg_per_1000") else None,
        (
            # In the CFP's own words: tankering carries return-sector fuel
            # (boss, 21 Aug fuel video — correct number, wrong wording).
            (
                "Excess is tankering: TANKER "
                + f"{next(item['fuel_kg'] for item in fuel_summary.get('excess_breakdown') or [] if item.get('label') == 'TANKER' and item.get('fuel_kg')):,} kg "
                + "carried for the return sector"
                + (
                    f" (requirement {fuel_summary.get('tanker_return_sector_req_kg'):,} kg per CFP page 1)."
                    if fuel_summary.get("tanker_return_sector_req_kg")
                    else " per CFP page 1."
                )
            )
            if any(
                item.get("label") == "TANKER" and item.get("fuel_kg")
                for item in fuel_summary.get("excess_breakdown") or []
            )
            else (
                "Excess composition: "
                + "; ".join(
                    f"{item['label']} {item['fuel_kg']:,} kg"
                    for item in fuel_summary.get("excess_breakdown") or []
                    if item.get("fuel_kg")
                ) + "."
                if any(item.get("fuel_kg") for item in fuel_summary.get("excess_breakdown") or [])
                else None
            )
        ),
    ) if part)

    refs = [
        " ".join(
            part
            for part in (
                deferred_item_type_for_display(item.get("item_type")),
                deferred_reference_for_display(item.get("reference")),
            )
            if part
        )
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

    hazards_text = _analysis_hazard_summary(flight, briefing)
    selected_communications = list(communications or [])
    if selected_communications:
        hazards_text += " FIR / NEXT CONTACT: " + " | ".join(
            _shared_communication_text(item)
            for item in selected_communications
        )

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

    # A NON-EDTO flight swaps the EDTO card for its one-line classification
    # instead of a panel of "--.--" placeholders (boss, 21 Aug: "this is not
    # EDTO information... useless information is repeated").
    non_edto = _edto_classification(flight).startswith("NON")
    source_classification = _edto_source_classification(flight)
    classification_sentence = (
        "CFP page 1: SUMMARY STANDARD CFP (non-EDTO). "
        if source_classification == "STANDARD"
        else f"CFP page 1: SUMMARY {source_classification or 'NON EDTO'} CFP. "
    ) + "Destination alternate and enroute suitability remain independent checks."
    edto_cell = (
        ("CLASSIFICATION", EDTO_GREEN, classification_sentence)
        if non_edto
        else ("EDTO / ENROUTE AIRPORT", EDTO_GREEN, edto_text)
    )
    cells = (
        ("PERFORMANCE / FUEL", DEPARTURE, perf_text),
        ("CDDL / CDL", WEATHER_AMBER, cddl_text),
        edto_cell,
        ("OPERATIONAL HAZARDS", WEATHER_AMBER, hazards_text),
        ("AIRPORTS / ALTERNATE", DESTINATION, airports_text),
        ("HIGH TERRAIN / VWS", TERRAIN_ORANGE, terrain_text),
    )
    # REV3 measured grid: 22pt gutter, 16pt row gaps, body on a 1.2 pitch.
    col_w = (width - 2 * MARGIN - 22) / 2
    card_h = (y - 34 - 2 * 16) / 3
    body_step = round(T_SMALL * 1.2, 2)
    # Each summary card is a link to its own section (boss, 21 Aug: "you can
    # click this — something to give more information... we can click all
    # this, that'll be good").
    cell_bookmarks = {
        "PERFORMANCE / FUEL": "sec_performance_summary",
        "CDDL / CDL": "sec_mel_cdl",
        "EDTO / ENROUTE AIRPORT": "sec_alternates",
        "CLASSIFICATION": "sec_alternates",
        "OPERATIONAL HAZARDS": "sec_hazard",
        "AIRPORTS / ALTERNATE": "sec_airports",
        "HIGH TERRAIN / VWS": "sec_terrain",
    }
    for index, (title, accent, text) in enumerate(cells):
        col = index % 2
        row = index // 2
        cx = MARGIN + col * (col_w + 22)
        cy = y - (row + 1) * card_h - row * 16
        inner = rev3_card(canvas, cx, cy, col_w, card_h, title=title, accent=accent)
        if cell_bookmarks.get(title):
            canvas.linkRect(
                "",
                cell_bookmarks[title],
                (cx, cy, cx + col_w, cy + card_h),
                relative=0,
                thickness=0,
            )
        ix, iy, iw, ih = inner
        line_y = cy + card_h - 34
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        lines = _wrap(text, SANS, T_SMALL, iw)
        if title == "OPERATIONAL HAZARDS" and len(lines) > 8:
            raise ValueError(
                "Primary DECISION ANALYSIS communications exceed the measured "
                "card capacity; plan a continuation page instead."
            )
        for line in lines[:8]:
            canvas.drawString(ix, line_y, line)
            line_y -= body_step


def draw_analysis_continuation_page(
    canvas,
    flight: dict[str, Any],
    communications: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    section_page_number: int,
    section_page_count: int,
) -> None:
    """DECISION ANALYSIS continuation containing every overflow comm row."""
    width, _ = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line="Shared FIR / next-contact facts | no renderer reselection or elision",
        section_label=(
            "DECISION ANALYSIS"
            + _continuation_suffix(section_page_number, section_page_count)
        ),
        section_colour=COMMS_TEAL,
    )
    y = content_top - 6
    full_w = width - 2 * MARGIN
    inner = panel(
        canvas,
        MARGIN,
        30,
        full_w,
        y - 30,
        title="FIR / NEXT CONTACT - SHARED COMMUNICATIONS",
        accent=COMMS_TEAL,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    row_y = y - 31
    for item in communications:
        planned_lines = item.get("_communication_lines")
        lines = (
            list(planned_lines)
            if isinstance(planned_lines, list) and planned_lines
            else _wrap(
                _shared_communication_text(item),
                SANS,
                T_SMALL,
                iw - 84.0,
            )
        )
        required_height = (
            max(1, len(lines)) * ANALYSIS_COMMUNICATION_LINE_HEIGHT
            + ANALYSIS_COMMUNICATION_ROW_GAP
        )
        if row_y - required_height < iy + 2:
            raise ValueError(
                "DECISION ANALYSIS communication continuation exceeds readable capacity"
            )
        canvas.setFillColor(COMMS_TEAL)
        canvas.setFont(MONO_BOLD, T_MICRO)
        canvas.drawString(
            ix,
            row_y,
            "CONTACT CONT." if item.get("_continued") else "FIR / CONTACT",
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        for line in lines:
            canvas.drawString(ix + 84.0, row_y, line)
            row_y -= ANALYSIS_COMMUNICATION_LINE_HEIGHT
        row_y -= ANALYSIS_COMMUNICATION_ROW_GAP


def _draw_operational_deferred_source_panel(
    canvas,
    flight: dict[str, Any],
    item: dict[str, Any],
    *,
    source_pdf_path: str | None,
    x: float,
    y: float,
    width: float,
    height: float,
    include_governed_link: bool = False,
) -> None:
    """Draw one data-driven source panel in the compact REV3 p3 mosaic."""
    item_type = deferred_item_type_for_display(item.get("item_type"))
    # A bare declaration has no printed reference; the title simply omits it
    # (boss, 21 Aug: no UNSPECIFIED placeholder words on the pilot surface).
    reference = deferred_reference_for_display(item.get("reference"))
    description = str(item.get("description") or "CFP DECLARATION").strip()
    title = " - ".join(part for part in (
        " ".join(p for p in (item_type, reference) if p),
        description,
    ) if part)
    inner = panel(
        canvas,
        x,
        y,
        width,
        height,
        title=title,
        accent=COMMS_TEAL,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    source_pages = [
        page
        for page in (item.get("source_page"),)
        if isinstance(page, int)
    ]
    # Crop from the declaration's own printed line to the next declaration —
    # a bare reference needle sliced neighbouring blocks mid-line (boss,
    # 21 Aug: "this is cropped out wrongly").
    declaration_line = str(item.get("source_declaration") or "").strip()
    needle = declaration_line or (reference if reference else description[:48])
    crop = crop_source_region(
        source_pdf_path,
        needle=needle,
        end_needle=str(item.get("crop_end_needle") or "").strip() or None,
        page_hint=0,
        source_pages=source_pages,
        pad_y=14,
        full_width=True,
    )
    target = (
        governed_deferred_source_target(flight, item)
        if include_governed_link
        else None
    )
    link_height = 14.0 if target else 0.0
    if crop:
        _draw_crop(
            canvas,
            crop,
            ix,
            iy + link_height,
            iw,
            max(1.0, ih - link_height),
            missing_text="",
            fill_sheet=False,
            fit_to_panel=True,
        )
    else:
        body = " ".join(
            part
            for part in (
                description,
                str(item.get("company_remark") or "").strip(),
                "Approved remedy source is not mounted - dispatch review required.",
            )
            if part
        )
        row_y = y + height - 37.0
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, T_SMALL)
        for line in _wrap(body, SANS, T_SMALL, iw)[: max(1, int((ih - link_height) // 11.0))]:
            canvas.drawString(ix, row_y, line)
            row_y -= 11.0
    if target:
        label = f"OPEN EXACT {item_type} ITEM / REMEDY >"
        label_width = pdfmetrics.stringWidth(label, SANS_BOLD, T_MICRO)
        canvas.setFillColor(ACCENT)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawRightString(ix + iw, iy + 3.0, label)
        canvas.linkURL(
            target,
            (ix + iw - label_width - 2, iy, ix + iw + 2, iy + 13),
            relative=0,
            thickness=0,
        )


def draw_operational_mel_cdl_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    source_pdf_path: str | None,
    deferred_items: list[dict[str, Any]],
) -> None:
    """Compact REV3 p3: four dispatch gates over three source panels."""
    width, _ = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line="CFP page 1 declarations | exact governed MEL/CDL item links",
        section_label="CDDL / CDL",
        section_colour=COMMS_TEAL,
        page_family="deep",
    )
    canvas.bookmarkPage("sec_mel_cdl")
    deferred = list(deferred_items or [])
    dispatch_gates = list(briefing.get("deferred_dispatch_gates") or [])
    gate_x = MARGIN + 10.0
    gate_w = width - 2 * gate_x
    gate_top = content_top - 12.0
    gate_h = 92.0
    gate_y = gate_top - gate_h
    canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.setLineWidth(0.8)
    canvas.roundRect(gate_x, gate_y, gate_w, gate_h, 9, stroke=1, fill=1)
    band_h = 22.0
    canvas.setFillColor(WEATHER_AMBER)
    canvas.roundRect(
        gate_x,
        gate_top - band_h,
        gate_w,
        band_h,
        9,
        stroke=0,
        fill=1,
    )
    canvas.rect(
        gate_x,
        gate_top - band_h,
        gate_w,
        band_h / 2,
        stroke=0,
        fill=1,
    )
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
    canvas.setFont(SANS_BOLD, 10.0)
    gate_overflow_count = max(0, len(dispatch_gates) - MEL_CDL_GROUPS_PER_PAGE)
    gate_heading = "MEL/CDL AND CDDL - DISPATCH CONFIRMATION GATES"
    if gate_overflow_count:
        gate_heading += f" | +{gate_overflow_count} IN DASHBOARD"
    _draw_string_fitted(
        canvas,
        gate_x + 12,
        gate_top - 15.0,
        gate_heading,
        SANS_BOLD,
        10.0,
        gate_w - 24,
        _page_colour(canvas, "bg", BG),
    )
    visible_gates = dispatch_gates[:MEL_CDL_GROUPS_PER_PAGE]
    if not visible_gates:
        visible_gates = deferred[:MEL_CDL_GROUPS_PER_PAGE]
    if not visible_gates:
        visible_gates = [{
            "title": "STATUS CLEAR",
            "summary": "No MEL, CDL or CDDL declaration is printed on CFP page 1.",
        }]
    column_w = gate_w / max(1, len(visible_gates))
    for index, item in enumerate(visible_gates):
        column_x = gate_x + index * column_w
        if index:
            canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
            canvas.line(column_x, gate_y + 9, column_x, gate_top - band_h - 8)
        gate_title = str(item.get("title") or "").strip().upper()
        if not gate_title:
            item_type = deferred_item_type_for_display(item.get("item_type"))
            reference = deferred_reference_for_display(item.get("reference"))
            declaration = deferred_source_declaration_for_display(
                item.get("source_declaration")
            ).upper()
            gate_title = declaration or " ".join(
                value for value in (item_type, reference) if value
            )
            if not gate_title:
                gate_title = "DEFERRED ITEM REVIEW REQUIRED"
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 8.8)
        _draw_string_fitted(
            canvas,
            column_x + 12,
            gate_top - band_h - 17,
            gate_title,
            SANS_BOLD,
            8.8,
            column_w - 24,
            TEXT,
        )
        body = str(item.get("summary") or "").strip()
        if not body:
            body = " ".join(
                part
                for part in (
                    str(item.get("description") or "").strip(),
                    str(item.get("company_remark") or "").strip(),
                )
                if part
            )
        body = body or "Dispatch review required."
        row_y = gate_top - band_h - 32.0
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 8.2)
        for line in _wrap(body, SANS, 8.2, column_w - 24)[:4]:
            canvas.drawString(column_x + 12, row_y, line)
            row_y -= 9.8

    source_items: list[dict[str, Any]] = []
    for gate in dispatch_gates:
        for segment in gate.get("source_segments") or []:
            reference = str(segment.get("reference") or "").strip().upper()
            item_type = str(segment.get("item_type") or "").strip().upper()
            # Every declaration on the block earns a source panel — the
            # 21 Aug CFP printed a bare CDDL, an IFEDDL and an engineering
            # IN notice alongside the MEL, and the boss's reference shows
            # all of them (only unparseable rows stay out).
            if item_type not in {"MEL", "CDL", "CDDL", "IFEDDL", "IN"}:
                continue
            source_index = segment.get("source_item_index")
            deferred_raw = flight.get("deferred_items") or []
            raw_source = (
                deferred_raw[source_index]
                if isinstance(source_index, int)
                and 0 <= source_index < len(deferred_raw)
                else {}
            )
            next_declaration = (
                str((deferred_raw[source_index + 1] or {}).get("source_declaration") or "").strip()
                if isinstance(source_index, int)
                and 0 <= source_index + 1 < len(deferred_raw)
                else ""
            )
            source_items.append({
                "item_type": item_type,
                "reference": reference,
                "description": segment.get("description"),
                "company_remark": segment.get("restriction"),
                "source_page": raw_source.get("source_page"),
                "source_declaration": raw_source.get("source_declaration"),
                "crop_end_needle": next_declaration or "PLAN",
            })
    source_overflow_count = max(0, len(source_items) - 3)
    source_items = source_items[:3]
    if not source_items:
        source_items = deferred[:3]
    if not source_items:
        source_items = visible_gates[:1]
    source_top = gate_y - (24.0 if source_overflow_count else 14.0)
    source_bottom = 46.0
    source_h = source_top - source_bottom
    if source_overflow_count:
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, T_MICRO)
        canvas.drawRightString(
            gate_x + gate_w,
            gate_y - 12.0,
            f"+{source_overflow_count} SOURCE DECLARATIONS REMAIN IN DASHBOARD",
        )
    gap = 12.0
    if len(source_items) == 1:
        positions = [(gate_x, source_bottom, gate_w, source_h)]
    elif len(source_items) == 2:
        card_w = (gate_w - gap) / 2.0
        positions = [
            (gate_x, source_bottom, card_w, source_h),
            (gate_x + card_w + gap, source_bottom, card_w, source_h),
        ]
    else:
        card_w = (gate_w - gap) / 2.0
        left_h = (source_h - gap) / 2.0
        positions = [
            (gate_x, source_bottom + left_h + gap, card_w, left_h),
            (gate_x, source_bottom, card_w, left_h),
            (gate_x + card_w + gap, source_bottom, card_w, source_h),
        ]
    for item, (x, y, card_w, card_h) in zip(source_items, positions):
        _draw_operational_deferred_source_panel(
            canvas,
            flight,
            item,
            source_pdf_path=source_pdf_path,
            x=x,
            y=y,
            width=card_w,
            height=card_h,
            include_governed_link=False,
        )


def _operational_airport_role(panel_data: dict[str, Any]) -> str:
    keys = set(panel_data.get("role_keys") or [])
    keys.add(str(panel_data.get("role_key") or ""))
    if "departure" in keys:
        return "DEPARTURE"
    if "destination" in keys:
        return "DESTINATION"
    if "alternate" in keys:
        return "PREFERRED ALTERNATE"
    if "edto" in keys:
        return "EDTO AIRPORT"
    if "fuel_enroute_airport" in keys:
        return "FUEL ENROUTE AIRPORT"
    return str(panel_data.get("role") or "AIRPORT").upper()


def _draw_operational_airport_card(
    canvas,
    panel_data: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    accent,
    filled_title: bool,
) -> None:
    panel_colour = _page_colour(canvas, "panel", PANEL)
    canvas.setFillColor(panel_colour)
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, width, height, 9, stroke=1, fill=1)
    title_h = 21.0
    if filled_title:
        canvas.setFillColor(accent)
        canvas.roundRect(x, y + height - title_h, width, title_h, 9, stroke=0, fill=1)
        canvas.rect(x, y + height - title_h, width, title_h / 2, stroke=0, fill=1)
        title_colour = _page_colour(canvas, "bg", BG)
    else:
        canvas.setFillColor(accent)
        canvas.rect(x, y + height - 3, width, 3, stroke=0, fill=1)
        title_colour = TEXT
    icao = str(panel_data.get("icao") or "----").upper()
    title = f"{icao} - {_operational_airport_role(panel_data)}"
    canvas.setFillColor(title_colour)
    canvas.setFont(SANS_BOLD, 9.4)
    _draw_string_fitted(
        canvas,
        x + 11,
        y + height - 14.5,
        title,
        SANS_BOLD,
        9.4,
        width - 22,
        title_colour,
    )
    rows = _station_card_lines(panel_data)
    row_y = y + height - title_h - 18.0
    inner_w = width - 24.0
    plan_row = rows[0] if rows and rows[0][0] == "PLAN" else None
    remaining = rows[1:] if plan_row else rows
    if plan_row:
        headline = str(plan_row[1]).replace(" | ", " / ")
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS, 12.0 if filled_title else 9.4)
        for line in _wrap(
            headline,
            SANS,
            12.0 if filled_title else 9.4,
            inner_w,
        )[:2]:
            canvas.drawString(x + 12, row_y, line)
            row_y -= 14.0 if filled_title else 11.5
        row_y -= 4.0
    floor_y = y + 12.0
    for label, value in remaining:
        label_text = f"{label}: " if label else ""
        lines = _wrap(
            label_text + str(value),
            SANS,
            T_SMALL,
            inner_w,
        )
        for line in lines:
            if row_y < floor_y:
                return
            canvas.setFillColor(TEXT_SECONDARY)
            canvas.setFont(SANS, T_SMALL)
            canvas.drawString(x + 12, row_y, line)
            row_y -= 11.0
        row_y -= 5.0


def draw_operational_airports_page(
    canvas,
    flight: dict[str, Any],
    *,
    page_number: int,
    page_count: int,
    panels: list[dict[str, Any]],
    compact_overflow_note: str | None = None,
) -> None:
    """Compact REV3 p5 with large 3-up primary and 2-up support cards."""
    width, _ = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line=" | ".join(
            value
            for value in (
                "Selected CFP weather + time-applicable NOTAM source facts by operational airport role",
                compact_overflow_note,
            )
            if value
        ),
        section_label="AIRPORTS / NOTAM APPLICABILITY",
        section_colour=SECTION_BLUE,
    )
    canvas.bookmarkPage("sec_airports")
    page_panels = list(panels or [])[:AIRPORT_OPERATIONAL_PANELS_PER_PAGE]
    if not page_panels:
        panel(
            canvas,
            MARGIN,
            86,
            width - 2 * MARGIN,
            content_top - 100,
            title="SELECTED AIRPORT ROLES - REVIEW REQUIRED",
            accent=WEATHER_AMBER,
        )
        return
    full_w = width - 2 * MARGIN
    gap = 26.0
    top_h = 260.0
    lower_h = 116.0
    top_y = content_top - top_h - 5.0
    lower_y = top_y - gap - lower_h
    top_w = (full_w - 2 * gap) / 3.0
    lower_w = (full_w - gap) / 2.0
    accents = (DEPARTURE, DESTINATION, WEATHER_AMBER, EDTO_GREEN, SECTION_BLUE)
    for index, panel_data in enumerate(page_panels):
        if index < 3:
            x = MARGIN + index * (top_w + gap)
            y = top_y
            card_w = top_w
            card_h = top_h
            filled = True
        else:
            lower_index = index - 3
            x = MARGIN + lower_index * (lower_w + gap)
            y = lower_y
            card_w = lower_w
            card_h = lower_h
            filled = False
        _draw_operational_airport_card(
            canvas,
            panel_data,
            x=x,
            y=y,
            width=card_w,
            height=card_h,
            accent=accents[index],
            filled_title=filled,
        )


def _draw_operational_text_panel(
    canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    accent,
    meta: str = "",
    body: str = "",
) -> None:
    inner = panel(
        canvas,
        x,
        y,
        width,
        height,
        title=title,
        accent=accent,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    row_y = y + height - 33.0
    if meta:
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO, 7.8)
        for line in _wrap(meta, MONO, 7.8, iw)[:2]:
            canvas.drawString(ix, row_y, line)
            row_y -= 10.0
        row_y -= 3.0
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 8.8)
    for line in _wrap(body, SANS, 8.8, iw)[: max(1, int((row_y - iy) // 11.2))]:
        canvas.drawString(ix, row_y, line)
        row_y -= 11.2


def _draw_operational_wafc_source(
    canvas,
    chart: dict[str, Any] | None,
    selection: dict[str, Any],
    *,
    source_pdf_path: str | None,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    title = str((chart or {}).get("label") or "WAFC ROUTE CHART - SOURCE CONTEXT")
    inner = panel(
        canvas,
        x,
        y,
        width,
        height,
        title=title,
        accent=COMMS_TEAL,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    raw = None
    if chart and source_pdf_path:
        from .weather_charts import extract_chart_image

        try:
            raw = extract_chart_image(
                source_pdf_path,
                int(chart.get("page_number")),
            )
        except Exception:
            raw = None
    if raw:
        expected_sha256 = str(chart.get("image_sha256") or "").lower()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("Selected WAFC chart is missing its shared source image SHA-256")
        if actual_sha256 != expected_sha256:
            raise ValueError("Selected WAFC chart source image SHA-256 mismatch")
        from io import BytesIO
        from reportlab.lib.utils import ImageReader

        image = ImageReader(BytesIO(raw))
        image_width, image_height = image.getSize()
        aspect = image_width / max(1, image_height)
        draw_h = ih - 8.0
        draw_w = min(iw - 8.0, draw_h * aspect)
        draw_h = draw_w / aspect
        canvas.setFillColor(colors.white)
        canvas.roundRect(ix, iy, iw, ih, 3, stroke=0, fill=1)
        canvas.drawImage(
            image,
            ix + (iw - draw_w) / 2,
            iy + (ih - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
        return
    review_line(
        canvas,
        ix + 8,
        iy + ih / 2,
        str(selection.get("reason") or "No governed route-context chart is available."),
    )


def draw_operational_hazard_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    *,
    weather_chart_selection: dict[str, Any],
    source_pdf_path: str | None,
    page_number: int,
    page_count: int,
    sigmet_cards: list[dict[str, Any]],
    vaac_lines: list[str],
    wafc_charts: list[dict[str, Any]],
    compact_overflow_note: str | None = None,
) -> None:
    """Compact REV3 p6: four decision cards left, two source panels right."""
    width, _ = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line=" | ".join(
            value
            for value in (
                "CFP weather snapshot",
                "held SIGMET/VAA reviews",
                "package WAFC fixed-time charts",
                compact_overflow_note,
            )
            if value
        ),
        section_label="OPERATIONAL HAZARD ASSESSMENT",
        section_colour=COMMS_TEAL,
        page_family="deep",
    )
    canvas.bookmarkPage("sec_hazard")
    x = MARGIN + 10.0
    full_w = width - 2 * x
    gap = 12.0
    left_w = 360.0
    right_w = full_w - left_w - gap
    top = content_top - 12.0
    bottom = 54.0
    available_h = top - bottom
    card_gap = 10.0
    sigmet_h = 92.0
    wafc_h = 78.0
    cards = list(sigmet_cards or [])[:2]
    sigmet_slot_count = max(1, len(cards))
    coverage_h = (
        available_h
        - sigmet_slot_count * sigmet_h
        - wafc_h
        - (sigmet_slot_count + 1) * card_gap
    )
    card_y = top - sigmet_h
    for index in range(sigmet_slot_count):
        if index < len(cards):
            card = cards[index]
            title = str(card.get("name") or "SIGMET")
            meta = " | ".join(
                part
                for part in (
                    (
                        f"VALID {card.get('valid_from')}-{card.get('valid_to')}"
                        if card.get("valid_from")
                        else None
                    ),
                    str(card.get("layer") or "") or None,
                    str(card.get("movement") or "") or None,
                )
                if part
            )
            disposition = str(card.get("disposition") or "")
            accent = CRITICAL if disposition == "PROMOTED" else WEATHER_AMBER
            _draw_operational_text_panel(
                canvas,
                x=x,
                y=card_y,
                width=left_w,
                height=sigmet_h,
                title=title,
                accent=accent,
                meta=meta,
                body=str(card.get("screening") or "Review required."),
            )
        else:
            _draw_operational_text_panel(
                canvas,
                x=x,
                y=card_y,
                width=left_w,
                height=sigmet_h,
                title="ENROUTE SIGMET",
                accent=EDTO_GREEN,
                body="No enroute SIGMET is printed in this CFP weather package.",
            )
        card_y -= sigmet_h + card_gap
    chart = (list(wafc_charts or []) or [None])[0]
    selection_status = str(weather_chart_selection.get("status") or "review required").replace("_", " ")
    selection_reason = str(weather_chart_selection.get("reason") or "")
    selected_label = str((chart or {}).get("label") or "")
    wafc_y = card_y + sigmet_h - wafc_h
    _draw_operational_text_panel(
        canvas,
        x=x,
        y=wafc_y,
        width=left_w,
        height=wafc_h,
        title="WAFC / CAT / CONVECTION / FRONTS",
        accent=COMMS_TEAL,
        meta=selected_label,
        body=f"{selection_status.upper()}. {selection_reason}".strip(),
    )
    hazards = briefing.get("hazards") or {}
    ledger_rows = hazards.get("coverage_ledger") or []
    ledger = " | ".join(
        f"{row.get('label')}: {row.get('status')}" for row in ledger_rows
    )
    vaac_summary = str((hazards.get("vaac_reach") or {}).get("summary") or "")
    vaac_detail = " | ".join(list(vaac_lines or [])[:2])
    # The Doc 9766 route-responsibility sentence leads the coverage story
    # (boss, 21 Aug: "there's a VAAC ... in Manila?") - the same composed
    # view fact the dashboard receipt prints.
    responsible_line = str((hazards.get("vaac_reach") or {}).get("responsible_line") or "")
    _draw_operational_text_panel(
        canvas,
        x=x,
        y=bottom,
        width=left_w,
        height=coverage_h,
        title="COVERAGE LEDGER",
        accent=TEXT_MUTED,
        meta=ledger,
        body=" ".join(
            part
            for part in (
                responsible_line,
                "These are source-coverage gaps, not NIL findings.",
                vaac_summary,
                vaac_detail,
            )
            if part
        ),
    )

    right_x = x + left_w + gap
    source_h = (available_h - card_gap) / 2.0
    weather_source_pages = [
        record.get("source_page")
        for record in flight.get("weather") or []
        if isinstance(record, dict) and isinstance(record.get("source_page"), int)
    ]
    weather_crop = crop_source_region(
        source_pdf_path,
        needle="Airport WX List",
        end_needle="DESTINATION ALTERNATE",
        source_pages=weather_source_pages,
        page_hint=None,
        pad_y=10,
        full_width=True,
    ) or crop_source_region(
        source_pdf_path,
        needle="SIGMETs:",
        source_pages=weather_source_pages,
        page_hint=None,
        pad_y=14,
        full_width=True,
    )
    inner = panel(
        canvas,
        right_x,
        top - source_h,
        right_w,
        source_h,
        title="CFP SIGMET / WEATHER SOURCE",
        accent=COMMS_TEAL,
        title_colour=None,
    )
    _draw_crop(
        canvas,
        weather_crop,
        inner[0],
        inner[1],
        inner[2],
        inner[3],
        missing_text="CFP weather source crop unavailable - review the uploaded CFP.",
        fill_sheet=False,
        fit_to_panel=True,
    )
    _draw_operational_wafc_source(
        canvas,
        chart,
        weather_chart_selection,
        source_pdf_path=source_pdf_path,
        x=right_x,
        y=bottom,
        width=right_w,
        height=source_h,
    )


def draw_operational_terrain_page(
    canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    findings: list[dict[str, Any]],
    chart_images: list[dict[str, Any]],
    *,
    page_number: int,
    page_count: int,
    compact_overflow_note: str | None = None,
) -> None:
    """Compact REV3 p7: event/status column plus a controlled-chart panel."""
    from io import BytesIO
    from reportlab.lib.utils import ImageReader

    width, _ = PAGE_SIZE
    content_top = draw_page_chrome(
        canvas,
        flight,
        page_number=page_number,
        page_count=page_count,
        source_line=" | ".join(
            value
            for value in (
                "CFP route log MSA windows",
                "A350 Depressurisation Profiles controlled attachments",
                "strict MSA >100*",
                compact_overflow_note,
            )
            if value
        ),
        section_label="HIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
        section_colour=SECTION_BLUE,
        page_family="deep",
    )
    canvas.bookmarkPage("sec_terrain")
    x = MARGIN
    top = content_top - 6.0
    bottom = 54.0
    gap = 14.0
    left_w = 312.0
    right_x = x + left_w + gap
    right_w = width - MARGIN - right_x
    event_h = 240.0
    status_h = top - bottom - event_h - gap
    event_y = top - event_h

    canvas.setFillColor(_page_colour(canvas, "panel", PANEL))
    canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
    canvas.roundRect(x, event_y, left_w, event_h, 9, stroke=1, fill=1)
    band_h = 21.0
    canvas.setFillColor(TERRAIN_ORANGE)
    canvas.roundRect(x, top - band_h, left_w, band_h, 9, stroke=0, fill=1)
    canvas.rect(x, top - band_h, left_w, band_h / 2, stroke=0, fill=1)
    canvas.setFillColor(_page_colour(canvas, "bg", BG))
    canvas.setFont(SANS_BOLD, 9.4)
    canvas.drawString(x + 12, top - 14.5, "STRICT MSA >100* EVENT")
    table_x = x + 12.0
    row_y = top - 43.0
    headers = (("POINT", 0), ("ACTM / UTC", 86), ("MSA", 177), ("VWS", 242))
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 8.2)
    for label, offset in headers:
        canvas.drawString(table_x + offset, row_y, label)
    row_y -= 16.0
    point_rows: list[tuple[str, str, str, str]] = []
    for point in _terrain_table_points(flight, briefing):
        name = str(point.get("name") or "").lstrip("-")
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
    for name, actm, msa, vws in point_rows[:7]:
        canvas.setStrokeColor(_page_colour(canvas, "border", BORDER))
        canvas.line(table_x, row_y - 5, x + left_w - 12, row_y - 5)
        canvas.setFillColor(TEXT)
        canvas.setFont(MONO, 8.0)
        canvas.drawString(table_x, row_y, name)
        canvas.drawString(table_x + 86, row_y, actm)
        canvas.setFillColor(TERRAIN_ORANGE if msa.endswith("*") else TEXT)
        canvas.setFont(MONO_BOLD if msa.endswith("*") else MONO, 8.0)
        canvas.drawString(table_x + 177, row_y, msa)
        canvas.setFillColor(WEATHER_AMBER if vws not in {"--", "001", "002", "003", "004"} else TEXT_SECONDARY)
        canvas.setFont(MONO, 8.0)
        canvas.drawString(table_x + 242, row_y, vws)
        row_y -= 34.0

    matched = _matched_profiles(findings)
    status_y = bottom
    inner = panel(
        canvas,
        x,
        status_y,
        left_w,
        status_h,
        title="PROFILE MATCH" if chart_images else "MANUAL REVIEW REQUIRED",
        accent=TERRAIN_ORANGE if chart_images else CRITICAL,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    if chart_images:
        chart_number = str(chart_images[0].get("chart_number") or "--")
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS, 13.0)
        canvas.drawString(ix, status_y + status_h - 46, f"ATTACHMENT {chart_number}")
        finding = next(
            (
                item for item in matched
                if str((item.get("data") or {}).get("chart_number")) == chart_number
            ),
            {},
        )
        body = str(finding.get("summary") or "Controlled profile match confirmed.")
    else:
        canvas.setFillColor(WEATHER_AMBER)
        canvas.setFont(SANS_BOLD, 12.0)
        canvas.drawString(ix, status_y + status_h - 47, "NO CONTROLLED PROFILE SERVED")
        body = str((briefing.get("terrain") or {}).get("summary") or "")
        body += " Exact endpoint/airway source validation remains required; no nearby chart is substituted."
    row_y = status_y + status_h - 68.0
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 8.8)
    for line in _wrap(body, SANS, 8.8, iw)[: max(1, int((row_y - iy) // 11.2))]:
        canvas.drawString(ix, row_y, line)
        row_y -= 11.2

    inner = panel(
        canvas,
        right_x,
        bottom,
        right_w,
        top - bottom,
        title=(
            "CROPPED AUTHORITATIVE PROFILE CHART"
            if chart_images
            else "CONTROLLED PROFILE CHART - NOT AVAILABLE"
        ),
        accent=TERRAIN_ORANGE,
        title_colour=None,
    )
    ix, iy, iw, ih = inner
    if chart_images:
        image = ImageReader(BytesIO(chart_images[0]["png"]))
        aspect = chart_images[0]["width"] / max(1, chart_images[0]["height"])
        draw_w = iw - 12.0
        draw_h = draw_w / aspect
        if draw_h > ih - 12.0:
            draw_h = ih - 12.0
            draw_w = draw_h * aspect
        canvas.setFillColor(colors.white)
        canvas.roundRect(ix, iy, iw, ih, 3, stroke=0, fill=1)
        canvas.drawImage(
            image,
            ix + (iw - draw_w) / 2,
            iy + (ih - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
    else:
        message = (
            "The controlled profile index is unavailable or no exact "
            "endpoint/airway match is confirmed. Manual review is required."
        )
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.setFont(SANS, 11.0)
        lines = _wrap(message, SANS, 11.0, iw - 80.0)
        row_y = iy + ih / 2 + len(lines) * 7.0
        for line in lines:
            canvas.drawCentredString(ix + iw / 2, row_y, line)
            row_y -= 14.0


def render_combined_briefing(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    path,
    *,
    source_pdf_path: str | None = None,
    weather_charts: dict[str, Any] | None = None,
    include_audit_appendix: bool = False,
) -> None:
    """Render the one-PDF Flight Briefing to `path`.

    The production default is the seven-page REV3 operational briefing.  A
    caller that needs the lossless audit publication can opt in to measured
    continuation pages with ``include_audit_appendix=True``.  Both modes are
    rendered from the same briefing view; the compact document never swaps in
    a flight-specific template, reference raster, or fixed source page.

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
    briefing = build_briefing_view(
        flight,
        findings,
        warnings,
        weather_charts=weather_charts,
    )
    analysis_primary_communications, analysis_communication_pages = (
        _analysis_communication_plan(flight, briefing)
    )
    analysis_detail_pages = _performance_fuel_detail_pages(briefing, flight)
    analysis_extra_page_count = (
        len(analysis_communication_pages) + len(analysis_detail_pages)
    )

    deferred_groups = _group_deferred_items(flight)
    deferred_pages = [
        deferred_groups[index:index + MEL_CDL_GROUPS_PER_PAGE]
        for index in range(0, len(deferred_groups), MEL_CDL_GROUPS_PER_PAGE)
    ] or [[]]
    deferred_detail_pages = _deferred_detail_pages(flight)
    mel_page_count = len(deferred_pages) + len(deferred_detail_pages)
    full_w = PAGE_SIZE[0] - 2 * MARGIN
    non_edto = _edto_classification(flight).startswith("NON")
    edto_cards_per_page = 1 if non_edto else EDTO_CARDS_PER_PAGE
    edto_card_w = (
        full_w
        if non_edto
        else (full_w - 2 * 10.0) / EDTO_CARDS_PER_PAGE
    )
    edto_card_h = (
        NON_EDTO_CLASSIFICATION_CARD_HEIGHT
        if non_edto
        else EDTO_CARD_HEIGHT
    )
    edto_cards = [
        *_edto_status_cards(
            briefing,
            inner_width=edto_card_w - 20,
            card_height=edto_card_h,
            included_labels=(
                {"CLASSIFICATION", "GATE"}
                if non_edto
                else None
            ),
        ),
        *([] if non_edto else (
            fragment
            for panel_data in _edto_and_fuel_panels(briefing)
            for fragment in _station_card_fragments(
                panel_data,
                card_width=edto_card_w,
                card_height=edto_card_h,
            )
        )),
    ]
    edto_pages = _chunked(edto_cards, edto_cards_per_page)
    airport_pages = _airport_operational_pages(briefing)
    airport_pages.extend(
        {"panels": [], "route_profile_rows": rows}
        for rows in _route_profile_continuation_pages(flight)
    )
    airport_notam_detail_pages = _airport_notam_detail_pages(briefing)
    airport_page_count = len(airport_pages) + len(airport_notam_detail_pages)
    hazards = briefing.get("hazards") or {}
    hazard_half_w = (full_w - 22.0) / 2.0
    sigmet_pages = _chunked(
        _sigmet_card_fragments(
            list(hazards.get("sigmet_cards") or []),
            text_width=hazard_half_w - 28.0,
        ),
        SIGMET_CARDS_PER_PAGE,
    )
    advisory_pages = _chunked(
        list((briefing.get("vaa") or {}).get("cfp_advisories") or []),
        VAA_ADVISORIES_PER_PAGE,
    )
    vaac_lines = _vaac_ledger_lines(
        list((hazards.get("vaac_reach") or {}).get("centres") or []),
        text_width=hazard_half_w - 28.0,
    )
    weather_chart_selection = hazards.get("weather_chart_selection") or {}
    selected_wafc_charts = list(
        weather_chart_selection.get("selected_charts") or []
    )
    wafc_pages = (
        _chunked(selected_wafc_charts, WAFC_CHARTS_PER_PAGE)
        if selected_wafc_charts
        else [[]]
    )
    hazard_pages = _hazard_page_plans(
        sigmet_pages,
        advisory_pages,
        wafc_pages,
        vaac_lines,
    )
    vaa_detail_pages = _vaa_detail_pages(briefing)
    hazard_page_count = len(hazard_pages) + len(vaa_detail_pages)
    terrain_detail_pages = _terrain_detail_pages(briefing, findings)
    # REV3 canon order (boss, 20 Aug): dashboard, critical analysis, CDDL/CDL,
    # EDTO, airports, weather, terrain - the tab strip's seven sections. The
    # old time-gates, performance and comms pages fold into pages 1, 2 and 4;
    # profile chart annexes follow the terrain page when charts are served.
    page_count = (
        3
        + analysis_extra_page_count
        + mel_page_count
        + len(edto_pages)
        + airport_page_count
        + hazard_page_count
        + len(terrain_detail_pages)
        + len(chart_images)
    )
    terrain_page_number = (
        3
        + analysis_extra_page_count
        + mel_page_count
        + len(edto_pages)
        + airport_page_count
        + hazard_page_count
    )
    profile_page_numbers = {
        str(image.get("chart_number")): (
            terrain_page_number + len(terrain_detail_pages) + 1 + index
        )
        for index, image in enumerate(chart_images)
    }

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(str(output_path), pagesize=PAGE_SIZE)
    canvas.setTitle(f"Flight Briefing {theme.display_flight_number(flight)} {theme.header_date_label(flight)}")

    if not include_audit_appendix:
        # REV3 is an operational seven-section briefing.  The high-cardinality
        # audit publication remains available through the explicit mode below;
        # it must not silently turn the pilot-facing download into tens of
        # continuation pages.
        operational_page_count = 7
        deferred_page = deferred_pages[0] if deferred_pages else []
        edto_page = edto_pages[0] if edto_pages else []
        airport_page = (
            airport_pages[0]
            if airport_pages
            else {"panels": [], "route_profile_rows": []}
        )
        hazard_page = (
            hazard_pages[0]
            if hazard_pages
            else {
                "sigmet_cards": [],
                "vaa_advisories": [],
                "vaac_lines": [],
                "wafc_charts": [],
            }
        )

        def compact_note(count: int, label: str) -> str | None:
            if count <= 0:
                return None
            suffix = "s" if count != 1 else ""
            return f"{count} additional {label}{suffix} remain in dashboard"

        analysis_overflow_count = sum(
            len(page) for page in analysis_communication_pages
        )
        edto_overflow_count = sum(len(page) for page in edto_pages[1:])
        airport_overflow_count = sum(
            len(page.get("panels") or [])
            + len(page.get("route_profile_rows") or [])
            for page in airport_pages[1:]
        ) + sum(
            len(page.get("rows") or [])
            for page in airport_notam_detail_pages
        )
        first_hazard_sigmet_overflow = max(
            0,
            len(hazard_page.get("sigmet_cards") or []) - 2,
        )
        first_hazard_wafc_overflow = max(
            0,
            len(hazard_page.get("wafc_charts") or []) - 1,
        )
        hazard_overflow_count = (
            first_hazard_sigmet_overflow
            + first_hazard_wafc_overflow
            + sum(
                len(page.get("vaa_advisories") or [])
                for page in hazard_pages
            )
            + sum(
                len(page.get("sigmet_cards") or [])
                + len(page.get("wafc_charts") or [])
                for page in hazard_pages[1:]
            )
            + sum(len(page.get("rows") or []) for page in vaa_detail_pages)
        )
        terrain_overflow_count = max(
            0,
            len((briefing.get("terrain") or {}).get("events") or []) - 2,
        ) + max(0, len(chart_images) - 1)

        draw_overview_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=1,
            page_count=operational_page_count,
        )
        canvas.addOutlineEntry("Flight Overview", "sec_overview", level=0)
        canvas.showPage()
        draw_analysis_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=2,
            page_count=operational_page_count,
            communications=analysis_primary_communications,
            compact_overflow_note=compact_note(
                analysis_overflow_count,
                "communication row",
            ),
        )
        canvas.addOutlineEntry("Decision Analysis", "sec_analysis", level=0)
        canvas.showPage()
        draw_operational_mel_cdl_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=3,
            page_count=operational_page_count,
            source_pdf_path=source_pdf_path,
            deferred_items=deferred_page,
        )
        canvas.addOutlineEntry("CDDL / CDL", "sec_mel_cdl", level=0)
        canvas.showPage()
        draw_alternates_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=4,
            page_count=operational_page_count,
            source_pdf_path=source_pdf_path,
            cards=edto_page,
            compact_overflow_note=compact_note(
                edto_overflow_count,
                "EDTO/enroute card",
            ),
        )
        canvas.addOutlineEntry(
            (
                "Destination Alternates"
                if _edto_classification(flight).startswith("NON")
                else "EDTO / Enroute Airports"
            ),
            "sec_alternates",
            level=0,
        )
        canvas.showPage()
        draw_operational_airports_page(
            canvas,
            flight,
            page_number=5,
            page_count=operational_page_count,
            panels=airport_page["panels"],
            compact_overflow_note=compact_note(
                airport_overflow_count,
                "airport/NOTAM audit row",
            ),
        )
        canvas.addOutlineEntry("Airports / NOTAM", "sec_airports", level=0)
        canvas.showPage()
        draw_operational_hazard_page(
            canvas,
            flight,
            briefing,
            weather_chart_selection=weather_chart_selection,
            page_number=6,
            page_count=operational_page_count,
            source_pdf_path=source_pdf_path,
            sigmet_cards=hazard_page["sigmet_cards"],
            vaac_lines=hazard_page["vaac_lines"],
            wafc_charts=hazard_page["wafc_charts"],
            compact_overflow_note=compact_note(
                hazard_overflow_count,
                "hazard audit row",
            ),
        )
        canvas.addOutlineEntry("Operational Hazards", "sec_hazard", level=0)
        canvas.showPage()
        draw_operational_terrain_page(
            canvas,
            flight,
            briefing,
            findings,
            chart_images,
            page_number=7,
            page_count=operational_page_count,
            compact_overflow_note=compact_note(
                terrain_overflow_count,
                "terrain/profile record",
            ),
        )
        canvas.addOutlineEntry("Terrain / Depressurisation", "sec_terrain", level=0)
        canvas.showPage()
        canvas.save()
        from .report_quality import assert_combined_briefing_quality

        assert_combined_briefing_quality(output_path)
        return

    draw_overview_page(canvas, flight, briefing, findings, page_number=1, page_count=page_count)
    canvas.showPage()
    draw_analysis_page(
        canvas,
        flight,
        briefing,
        findings,
        page_number=2,
        page_count=page_count,
        communications=analysis_primary_communications,
    )
    canvas.showPage()
    for index, communication_page in enumerate(analysis_communication_pages):
        draw_analysis_continuation_page(
            canvas,
            flight,
            communication_page,
            page_number=3 + index,
            page_count=page_count,
            section_page_number=2 + index,
            section_page_count=1 + analysis_extra_page_count,
        )
        canvas.showPage()
    analysis_detail_first_page = 3 + len(analysis_communication_pages)
    for index, detail_page in enumerate(analysis_detail_pages):
        draw_shared_detail_page(
            canvas,
            flight,
            page_number=analysis_detail_first_page + index,
            page_count=page_count,
            section_label="DECISION ANALYSIS",
            section_colour=DEPARTURE,
            section_page_number=(
                2 + len(analysis_communication_pages) + index
            ),
            section_page_count=1 + analysis_extra_page_count,
            title=detail_page["title"],
            rows=detail_page["rows"],
            source_line=(
                "Shared performance publication, mass and complete parsed "
                "fuel-summary projection"
            ),
        )
        canvas.showPage()
    mel_first_page_number = 3 + analysis_extra_page_count
    for index, deferred_page in enumerate(deferred_pages):
        draw_mel_cdl_page(
            canvas, flight, briefing, findings,
            page_number=mel_first_page_number + index,
            page_count=page_count,
            source_pdf_path=source_pdf_path,
            deferred_items=deferred_page,
            section_page_number=index + 1,
            section_page_count=mel_page_count,
        )
        canvas.showPage()
    mel_detail_first_page = mel_first_page_number + len(deferred_pages)
    for index, detail_page in enumerate(deferred_detail_pages):
        draw_shared_detail_page(
            canvas,
            flight,
            page_number=mel_detail_first_page + index,
            page_count=page_count,
            section_label="MEL/CDL AND CDDL",
            section_colour=DEPARTURE,
            section_page_number=len(deferred_pages) + index + 1,
            section_page_count=mel_page_count,
            title=detail_page["title"],
            rows=detail_page["rows"],
            source_line=(
                "Complete parsed CFP deferred declarations and company remarks"
            ),
            page_family="deep",
        )
        canvas.showPage()
    next_page_number = mel_first_page_number + mel_page_count
    for index, edto_page in enumerate(edto_pages):
        draw_alternates_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=next_page_number,
            page_count=page_count,
            source_pdf_path=source_pdf_path,
            cards=edto_page,
            section_page_number=index + 1,
            section_page_count=len(edto_pages),
        )
        canvas.showPage()
        next_page_number += 1
    for index, airport_page in enumerate(airport_pages):
        draw_airports_page(
            canvas,
            flight,
            briefing,
            findings,
            page_number=next_page_number,
            page_count=page_count,
            panels=airport_page["panels"],
            route_profile_rows=airport_page["route_profile_rows"],
            section_page_number=index + 1,
            section_page_count=airport_page_count,
        )
        canvas.showPage()
        next_page_number += 1
    for index, detail_page in enumerate(airport_notam_detail_pages):
        draw_shared_detail_page(
            canvas,
            flight,
            page_number=next_page_number,
            page_count=page_count,
            section_label="AIRPORTS / NOTAM APPLICABILITY",
            section_colour=DESTINATION,
            section_page_number=len(airport_pages) + index + 1,
            section_page_count=airport_page_count,
            title=detail_page["title"],
            rows=detail_page["rows"],
            source_line=(
                "All shared selected NOTAM identities, validity, schedules, "
                "applicability and item-E text"
            ),
        )
        canvas.showPage()
        next_page_number += 1
    for index, hazard_page in enumerate(hazard_pages):
        draw_hazard_page(
            canvas,
            flight,
            briefing,
            findings,
            weather_chart_selection,
            page_number=next_page_number,
            page_count=page_count,
            source_pdf_path=source_pdf_path,
            sigmet_cards=hazard_page["sigmet_cards"],
            vaa_advisories=hazard_page["vaa_advisories"],
            vaac_lines=hazard_page["vaac_lines"],
            wafc_charts=hazard_page["wafc_charts"],
            section_page_number=index + 1,
            section_page_count=hazard_page_count,
        )
        canvas.showPage()
        next_page_number += 1
    for index, detail_page in enumerate(vaa_detail_pages):
        draw_shared_detail_page(
            canvas,
            flight,
            page_number=next_page_number,
            page_count=page_count,
            section_label="OPERATIONAL HAZARD ASSESSMENT",
            section_colour=WEATHER_AMBER,
            section_page_number=len(hazard_pages) + index + 1,
            section_page_count=hazard_page_count,
            title=detail_page["title"],
            rows=detail_page["rows"],
            source_line="Complete shared CFP volcanic-ash source records",
            page_family="deep",
        )
        canvas.showPage()
        next_page_number += 1
    draw_terrain_page(
        canvas, flight, briefing, findings, chart_images,
        page_number=terrain_page_number,
        page_count=page_count, profile_page_numbers=profile_page_numbers,
    )
    canvas.showPage()
    for index, detail_page in enumerate(terrain_detail_pages):
        draw_shared_detail_page(
            canvas,
            flight,
            page_number=terrain_page_number + index + 1,
            page_count=page_count,
            section_label="TERRAIN",
            section_colour=TERRAIN_ORANGE,
            section_page_number=index + 2,
            section_page_count=1 + len(terrain_detail_pages),
            title=(
                "HIGH TERRAIN EXPOSURE AND DEPRESSURISATION "
                f"- CONTINUED ({index + 2}/{1 + len(terrain_detail_pages)}) "
                f"| {detail_page['title']}"
            ),
            rows=detail_page["rows"],
            source_line=(
                "Every shared strict-MSA terrain event and profile-match status"
            ),
            page_family="deep",
        )
        canvas.showPage()
    for index, image in enumerate(chart_images):
        draw_profile_page(
            canvas, flight, image,
            page_number=(
                terrain_page_number + len(terrain_detail_pages) + 1 + index
            ),
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
