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

from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics

from . import brief_theme as theme
from .brief_theme import MONO, MONO_BOLD, SANS, SANS_BOLD, register_fonts
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
T_CARD_HEAD = 8.6     # panel title bars
T_BODY = 8.4
T_VALUE = 12.5        # stat values
T_SMALL = 7.2
T_MICRO = 6.5


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    """Largest size <= requested that keeps text inside max_width (rule 8:
    nothing may overlap or overrun its box)."""
    width = pdfmetrics.stringWidth(text, font, size)
    if width <= max_width or width <= 0:
        return size
    return max(4.5, size * max_width / width)


def _draw_string_fitted(canvas, x, y, text, font, size, max_width, colour):
    fitted = _fit(text, font, size, max_width)
    canvas.setFillColor(colour)
    canvas.setFont(font, fitted)
    canvas.drawString(x, y, text)
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
    canvas.setFont(SANS_BOLD, T_FLIGHT)
    canvas.drawString(identity_x, top - 18, flight_number)
    canvas.setFont(SANS_BOLD, 10.5)
    canvas.drawString(
        identity_x,
        top - 31,
        f"{flight.get('departure') or '----'} -> {flight.get('destination') or '----'}",
    )
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, 7.4)
    canvas.drawString(
        identity_x,
        top - 41,
        f"{flight.get('aircraft_type') or ''} | "
        f"{theme.normalized_registration(flight.get('registration'))}",
    )

    # Centre schedule block.
    centre_x = width * 0.50
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 9.6)
    canvas.drawString(centre_x, top - 16, theme.header_date_label(flight))
    utc_line, local_line = _header_times(flight)
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(MONO, 7.0)
    canvas.drawString(centre_x, top - 27, utc_line)
    canvas.setFillColor(TEXT)
    canvas.setFont(MONO_BOLD, 7.0)
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
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, 6.6)
    canvas.drawRightString(width - MARGIN, top - 34, f"Page {page_number} of {page_count}")

    # Header rule.
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, top - 48, width - MARGIN, top - 48)

    # Footer.
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, 6.4)
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
    canvas.setFont(SANS_BOLD, 6.4)
    canvas.drawString(MARGIN, 21, "SOURCE")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont(SANS, 6.4)
    canvas.drawString(MARGIN + 34, 21, source_line[:180])
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
    canvas.setFillColor(title_colour)
    canvas.setFont(SANS_BOLD, T_CARD_HEAD)
    canvas.drawString(x + 8, y + h - bar_h + 4.4, str(title).upper())
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
    canvas.drawString(x + 8, y + h - 15, str(label).upper())
    _draw_string_fitted(
        canvas, x + 8, y + h - 32, str(value),
        MONO_BOLD if mono else SANS_BOLD, T_VALUE, w - 16, TEXT,
    )
    if caption:
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont(SANS, T_MICRO)
        canvas.drawString(x + 8, y + 6, str(caption)[:60])


def open_link(canvas, x, y, *, label="OPEN", accent=ACCENT, destination: str | None) -> None:
    """The spec's OPEN> jump chip; a real internal link when a destination
    bookmark is supplied."""
    w = pdfmetrics.stringWidth(label, SANS_BOLD, 6.8) + 18
    canvas.setFillColor(accent)
    canvas.roundRect(x - w, y, w, 12, 6, stroke=0, fill=1)
    canvas.setFillColor(BG)
    canvas.setFont(SANS_BOLD, 6.8)
    canvas.drawCentredString(x - w / 2, y + 3.6, label)
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
    ("edto", "NON-EDTO", EDTO_GREEN, "sec_alternates"),
    ("terrain", "TERRAIN", TERRAIN_ORANGE, "sec_terrain"),
    ("va_wx", "VA / WX", WEATHER_AMBER, "sec_hazard"),
    ("airports", "AIRPORTS", DESTINATION, "sec_airports"),
    ("kabul_fir", "KABUL / FIR", COMMS_TEAL, "sec_comms"),
)


def _first_title(findings: list[dict[str, Any]], engines: set[str]) -> str | None:
    for finding in findings:
        if str(finding.get("engine")) in engines:
            title = str(finding.get("summary") or finding.get("title") or "").strip()
            if title:
                return title
    return None


def _gate_lines(
    briefing: dict[str, Any], flight: dict[str, Any], findings: list[dict[str, Any]]
) -> dict[str, str]:
    deferred = flight.get("deferred_items") or []
    deferred_line = (
        "; ".join(
            f"{item.get('item_type')} {item.get('reference')}".strip()
            for item in deferred[:2]
        )
        if deferred
        else "No deferred item on CFP page 1"
    )
    classification = ((flight.get("fuel_summary") or {}).get("classification")) or (
        "EDTO" if (flight.get("edto") or {}).get("sectors") else None
    )
    edto_line = (
        f"CFP classified {classification} CFP"
        if classification
        else "CFP classification requires review"
    )
    terrain_events = (briefing.get("terrain") or {}).get("events") or []
    strict = [event for event in terrain_events if event]
    terrain_line = (
        f"{len(strict)} MSA >100* window{'s' if len(strict) != 1 else ''}; profile match on the terrain page"
        if strict
        else "No strict MSA >100* window detected"
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
    canvas.drawString(ix, y + h - 32, str(headline)[:52])
    canvas.setFillColor(TEXT_SECONDARY)
    canvas.setFont(SANS, T_SMALL)
    text = canvas.beginText(ix, y + h - 45)
    text.setLeading(9.4)
    line = ""
    words = str(body).split()
    lines = []
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdfmetrics.stringWidth(candidate, SANS, T_SMALL) > iw:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    for out_line in lines[:4]:
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
    card_h = 64.0
    gap = 8.0
    departure_panel = briefing.get("departure") or {}
    destination_panel = briefing.get("destination") or {}
    alternates = flight.get("alternates") or []
    fuel_summary = flight.get("fuel_summary") or {}

    def weather_line(panel_data: dict[str, Any]) -> str:
        weather = panel_data.get("weather") or {}
        return str(
            weather.get("summary")
            or weather.get("detail")
            or "Weather review on the hazard assessment page."
        )

    top_y = y - card_h
    _airport_card(
        canvas, MARGIN, top_y, left_w, card_h,
        title=f"DEPARTURE - {departure_panel.get('icao') or flight.get('departure') or '----'}",
        accent=DEPARTURE,
        headline=str(departure_panel.get("runway") or "Runway review"),
        body=weather_line(departure_panel),
        tag="DEP",
    )
    mid_y = top_y - gap - card_h
    _airport_card(
        canvas, MARGIN, mid_y, left_w, card_h,
        title=f"DESTINATION - {destination_panel.get('icao') or flight.get('destination') or '----'}",
        accent=DESTINATION,
        headline=str(destination_panel.get("runway") or "Runway review"),
        body=weather_line(destination_panel),
        tag="DEST",
    )
    primary_alternate = alternates[0] if alternates else {}
    summary_alternate = fuel_summary.get("alternate") or {}
    altn_headline = (
        f"{primary_alternate.get('airport') or summary_alternate.get('icao') or '----'}"
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
        title=f"ALTERNATE - {primary_alternate.get('airport') or summary_alternate.get('icao') or 'REVIEW'}",
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
        chip_w = pdfmetrics.stringWidth(label, SANS_BOLD, 6.6) + 14
        canvas.setFillColor(accent)
        canvas.roundRect(ix, row_y - 3.4, chip_w, 11, 5.5, stroke=0, fill=1)
        canvas.setFillColor(BG)
        canvas.setFont(SANS_BOLD, 6.6)
        canvas.drawCentredString(ix + chip_w / 2, row_y, label)
        _draw_string_fitted(
            canvas, ix + chip_w + 6, row_y, lines.get(key) or "",
            SANS, T_MICRO, iw - chip_w - 6 - 44, TEXT_SECONDARY,
        )
        open_link(canvas, ix + iw, row_y - 3.4, label="OPEN >", accent=colors.transparent if False else ELEVATED, destination=bookmark)
        canvas.setFillColor(ACCENT)
        canvas.setFont(SANS_BOLD, 6.8)
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
        title=f"{theme.display_flight_number(flight)} {flight.get('departure') or ''}-{flight.get('destination') or ''} | OPERATIONAL ROUTE / DECISION GATES",
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
    if state != "verified":
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
