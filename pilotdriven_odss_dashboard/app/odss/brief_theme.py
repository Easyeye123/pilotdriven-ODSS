"""Shared PilotDriven v1.3 brief theme: fonts, palette, header and footer.

The visual contract is the approved v1.3 reference brief set: condensed
sans typography, deep-navy pages, a three-line flight header (date + BLOCK,
UTC schedule, local times), per-page SOURCE chips and the
``PILOTDRIVEN ODSS | <flight> | CFP OFP <id> | <type> <reg> | <date>``
footer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import airportsdata
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .controlled_library import normalized_registration

SANS = "BriefSans"
SANS_BOLD = "BriefSans-Bold"

_FONT_DIR = Path(__file__).resolve().parent / "fonts"


def register_fonts() -> None:
    """Register the condensed brief faces once per process.

    Falls back silently to Helvetica metrics only if the vendored files are
    missing (development safety; the shipped image always contains them).
    """
    if SANS in pdfmetrics.getRegisteredFontNames():
        return
    regular = _FONT_DIR / "DejaVuSansCondensed.ttf"
    bold = _FONT_DIR / "DejaVuSansCondensed-Bold.ttf"
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont(SANS, str(regular)))
        pdfmetrics.registerFont(TTFont(SANS_BOLD, str(bold)))
    else:  # pragma: no cover - vendored fonts are part of the tree
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        pdfmetrics.registerFont(TTFont(SANS, "Helvetica"))
        registerFontFamily(SANS, normal="Helvetica", bold="Helvetica-Bold")


# Palette lifted from the approved v1.3 reference PDFs (vector fills).
PAGE_BG = colors.HexColor("#071724")
PANEL = colors.HexColor("#10283A")
PANEL_DEEP = colors.HexColor("#0C2435")
PANEL_DARK = colors.HexColor("#061522")
LINE = colors.HexColor("#1E3A50")
TEXT = colors.HexColor("#EEF5FA")
MUTED = colors.HexColor("#9CB1C1")
MUTED_DEEP = colors.HexColor("#6D8798")
BLUE = colors.HexColor("#2DB4F0")
BLUE_SOFT = colors.HexColor("#3AAEE6")
PURPLE = colors.HexColor("#8B5CF6")
RED = colors.HexColor("#FF5B68")
GREEN = colors.HexColor("#38C18C")
AMBER = colors.HexColor("#F4A91D")
TEAL = colors.HexColor("#35C0BC")

@lru_cache(maxsize=1)
def _airport_local_registry() -> dict[str, airportsdata.Airport]:
    """Load the pinned offline ICAO-to-IANA registry once per process."""
    return airportsdata.load("ICAO")


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_time_segment(icao: Any, utc_value: Any) -> str | None:
    """``SIN 30 JUL 0005 UTC+8`` for a known airport, else None.

    The airport-to-zone relationship comes from a pinned offline dataset; the
    offset itself always comes from IANA rules for the flight instant. No GPT,
    browser lookup, fixed UTC offset, or longitude guess participates.
    """
    code = str(icao or "").upper()
    entry = _airport_local_registry().get(code)
    moment = _parse_utc(utc_value)
    if not entry or moment is None:
        return None
    label = str(entry.get("iata") or code)
    zone = str(entry.get("tz") or "")
    if not zone:
        return None
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except ZoneInfoNotFoundError:
        return None
    offset = local.utcoffset()
    total_minutes = int(offset.total_seconds() // 60) if offset else 0
    hours, minutes = divmod(abs(total_minutes), 60)
    sign = "+" if total_minutes >= 0 else "-"
    offset_text = f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
    return f"{label} {local.strftime('%d %b %H%M').upper()} {offset_text}"


def block_time_label(flight: dict[str, Any]) -> str | None:
    """Scheduled ``BLOCK 13:05`` from the CFP departure/arrival times."""
    dep = _parse_utc(flight.get("scheduled_departure_utc"))
    arr = _parse_utc(flight.get("scheduled_arrival_utc"))
    if dep is None or arr is None or arr <= dep:
        return None
    minutes = int((arr - dep).total_seconds() // 60)
    return f"BLOCK {minutes // 60}:{minutes % 60:02d}"


def utc_hhmm(value: Any) -> str:
    moment = _parse_utc(value)
    return moment.strftime("%H%M") + "Z" if moment else "-"


def header_date_label(flight: dict[str, Any]) -> str:
    moment = _parse_utc(flight.get("scheduled_departure_utc"))
    if moment:
        return moment.strftime("%d %b %Y").upper()
    return str(flight.get("flight_date") or "").upper()


def month_tag(flight: dict[str, Any]) -> str:
    moment = _parse_utc(flight.get("scheduled_departure_utc"))
    return moment.strftime("%b %Y").upper() if moment else ""


def ofp_label(flight: dict[str, Any]) -> str:
    value = str(flight.get("ofp_identifier") or "").strip()
    return value or "not stated"


def display_flight_number(flight: dict[str, Any]) -> str:
    """Prefer the CFP-declared operating designator (e.g. SQ352 over SIA352)."""
    operating = str(flight.get("operating_flight_number") or "").strip()
    return operating or str(flight.get("flight_number") or "")


def draw_header(
    canvas: Any,
    flight: dict[str, Any],
    *,
    width: float,
    height: float,
    pill_text: str,
    pill_color: colors.Color = BLUE,
    extra_utc_note: str | None = None,
) -> float:
    """Draw the standard v1.3 header band; returns the content top y."""
    register_fonts()
    margin = 24.0
    top = height - 22.0

    # Wordmark: PILOT in white, DRIVEN in blue.
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 13.5)
    canvas.drawString(margin, top - 10, "PILOT")
    pilot_width = pdfmetrics.stringWidth("PILOT", SANS_BOLD, 13.5)
    canvas.setFillColor(BLUE)
    canvas.drawString(margin + pilot_width, top - 10, "DRIVEN")

    # Flight identity block.
    identity_x = width * 0.205
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 21)
    flight_number = display_flight_number(flight)
    canvas.drawString(identity_x, top - 6, flight_number)
    tag = month_tag(flight)
    if tag:
        number_width = pdfmetrics.stringWidth(flight_number, SANS_BOLD, 21)
        canvas.setFillColor(BLUE)
        canvas.setFont(SANS_BOLD, 7.2)
        canvas.drawString(identity_x + number_width + 6, top - 4, tag)
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 11.5)
    canvas.drawString(
        identity_x,
        top - 20,
        f"{flight.get('departure') or ''} -> {flight.get('destination') or ''}",
    )
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS, 7.0)
    canvas.drawString(
        identity_x,
        top - 31,
        f"{flight.get('aircraft_type') or ''} | "
        f"{normalized_registration(flight.get('registration'))}",
    )

    # Right-hand schedule block.
    schedule_x = width * 0.50
    date_label = header_date_label(flight)
    block_label = block_time_label(flight)
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS_BOLD, 8.2)
    canvas.drawString(schedule_x, top - 6, date_label)
    if block_label:
        date_width = pdfmetrics.stringWidth(date_label, SANS_BOLD, 8.2)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 10.8)
        canvas.drawString(schedule_x + date_width + 12, top - 6, block_label)
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS, 7.2)
    utc_line = (
        "UTC  DEP "
        + utc_hhmm(flight.get("scheduled_departure_utc"))
        + "  ->  ARR "
        + utc_hhmm(flight.get("scheduled_arrival_utc"))
    )
    if extra_utc_note:
        utc_line += f"  |  {extra_utc_note}"
    canvas.drawString(schedule_x, top - 17, utc_line)
    departure_segment = local_time_segment(
        flight.get("departure"), flight.get("scheduled_departure_utc")
    )
    arrival_segment = local_time_segment(
        flight.get("destination"), flight.get("scheduled_arrival_utc")
    )
    if departure_segment or arrival_segment:
        departure_local = departure_segment or (
            f"{str(flight.get('departure') or '').upper()} LOCAL UNAVAILABLE"
        )
        arrival_local = arrival_segment or (
            f"{str(flight.get('destination') or '').upper()} LOCAL UNAVAILABLE"
        )
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 7.2)
        canvas.drawString(
            schedule_x,
            top - 27,
            f"LOCAL  {departure_local}  ->  {arrival_local}",
        )

    # Level pill.
    pill_width = max(
        150.0,
        pdfmetrics.stringWidth(pill_text, SANS_BOLD, 6.6) + 34,
    )
    pill_x = width - margin - pill_width
    canvas.setStrokeColor(pill_color)
    canvas.setLineWidth(1.1)
    canvas.setFillColor(PAGE_BG)
    canvas.roundRect(pill_x, top - 16, pill_width, 15, 7.5, stroke=1, fill=1)
    canvas.setFillColor(TEXT)
    canvas.setFont(SANS_BOLD, 6.6)
    canvas.drawCentredString(pill_x + pill_width / 2, top - 11, pill_text)

    # Divider under the header.
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.8)
    canvas.line(margin, top - 40, width - margin, top - 40)
    return top - 48


def draw_footer(
    canvas: Any,
    flight: dict[str, Any],
    *,
    width: float,
    page_number: int,
    page_count: int,
) -> None:
    register_fonts()
    margin = 24.0
    canvas.setFillColor(PANEL_DARK)
    canvas.rect(0, 0, width, 16, stroke=0, fill=1)
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS, 6.0)
    canvas.drawString(
        margin,
        5.4,
        " | ".join(
            value
            for value in (
                "PILOTDRIVEN ODSS",
                display_flight_number(flight),
                f"CFP OFP {ofp_label(flight)}",
                (
                    f"{flight.get('aircraft_type') or ''} "
                    f"{normalized_registration(flight.get('registration'))}"
                ).strip(),
                header_date_label(flight),
            )
            if value
        ),
    )
    canvas.drawRightString(
        width - margin,
        5.4,
        f"Page {page_number} of {page_count}",
    )


def draw_source_chips(
    canvas: Any,
    chips: list[str],
    *,
    width: float,
    y: float = 20.0,
) -> None:
    """SOURCE chip row + the deterministic-derivation tag, above the footer."""
    register_fonts()
    margin = 24.0
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS_BOLD, 6.0)
    canvas.drawString(margin, y + 4.5, "SOURCE")
    x = margin + 40
    for chip in chips[:8]:
        label = str(chip).upper()
        chip_width = pdfmetrics.stringWidth(label, SANS_BOLD, 5.8) + 16
        canvas.setStrokeColor(BLUE_SOFT)
        canvas.setLineWidth(0.7)
        canvas.setFillColor(PAGE_BG)
        canvas.rect(x, y, chip_width, 13, stroke=1, fill=1)
        canvas.setFillColor(TEXT)
        canvas.setFont(SANS_BOLD, 5.8)
        canvas.drawCentredString(x + chip_width / 2, y + 4.2, label)
        x += chip_width + 8
    canvas.setFillColor(MUTED)
    canvas.setFont(SANS, 5.6)
    canvas.drawRightString(
        canvas._pagesize[0] - margin if hasattr(canvas, "_pagesize") else width - margin,
        y + 4.5,
        "DIRECT SOURCES + DETERMINISTIC DERIVATION | AI AUTHORITY: NONE",
    )
