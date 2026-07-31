"""Level 2: DEPRESSURISATION PROFILE MATCH MATRIX and embedded source charts.

v1.3 publication rules drawn here:

- one matrix row per strict >100* window with MATCH / UNRESOLVED result,
- the SOURCE ASSURANCE / PUBLICATION GATE panel, and
- one appended page per approved profile carrying the complete authoritative
  source chart (rasterised from the governed single-page artifact whose
  sha256 is pinned in the approved index).
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics

from . import brief_theme as theme
from .constants import format_actm
from .controlled_library import (
    aircraft_effectivity_tokens,
    load_profile_chart_bytes,
    normalized_registration,
)
from .depress_analysis_page import (
    _actm_utc,
    _event_for_id,
    _filed_segment,
    _matched_event_findings,
    _matched_findings,
    _profile_by_chart,
    _terr_ref,
    _unresolved_findings,
)
from .engines import detect_terrain_events


def matched_profile_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _matched_findings(findings)


def load_matched_chart_images(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch + rasterise every matched profile's governed chart artifact.

    Raises ProfileChartUnavailableError when any matched chart cannot be
    served; callers must treat that as a publication failure (fail closed).
    """
    import fitz

    images: list[dict[str, Any]] = []
    for finding in matched_profile_findings(findings):
        data = finding.get("data") or {}
        chart_number = str(data.get("chart_number") or "")
        profile = _profile_by_chart(chart_number) or {}
        raw = load_profile_chart_bytes(profile)
        with fitz.open(stream=raw, filetype="pdf") as chart_doc:
            pixmap = chart_doc[0].get_pixmap(dpi=200)
            png = pixmap.tobytes("png")
        images.append(
            {
                "chart_number": chart_number,
                "profile": profile,
                "png": png,
                "width": pixmap.width,
                "height": pixmap.height,
            }
        )
    return images


def _effectivity_series(flight: dict[str, Any]) -> str:
    tokens = aircraft_effectivity_tokens(
        flight.get("registration"), flight.get("aircraft_type")
    )
    for series in ("LH", "ULR", "MH"):
        if series in tokens:
            return series
    return "-"


def draw_match_matrix_page(
    canvas: Any,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    width: float,
    height: float,
    *,
    page_number: int,
    page_count: int,
    chart_page_numbers: dict[str, int],
) -> None:
    theme.register_fonts()
    canvas.setFillColor(theme.PAGE_BG)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    margin = 24.0
    top = theme.draw_header(
        canvas,
        flight,
        width=width,
        height=height,
        pill_text="LEVEL 2 - PROFILE MATCH",
    )
    canvas.setFillColor(theme.TEXT)
    canvas.setFont(theme.SANS_BOLD, 16)
    canvas.drawString(margin, top - 14, "DEPRESSURISATION PROFILE MATCH MATRIX")
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.8)
    canvas.drawRightString(
        width - margin,
        top - 12,
        "Deterministic route/airway/effectivity comparison | "
        "full authoritative charts on the source-chart pages",
    )

    # METHOD strip.
    strip_y = top - 46
    canvas.setFillColor(theme.PANEL)
    canvas.roundRect(margin, strip_y, width - 2 * margin, 20, 4, stroke=0, fill=1)
    canvas.setFillColor(theme.BLUE)
    canvas.setFont(theme.SANS_BOLD, 6.0)
    canvas.drawString(margin + 10, strip_y + 7, "METHOD")
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 6.0)
    canvas.drawString(
        margin + 58,
        strip_y + 7,
        "Identify >10,000 ft region; use preceding/last high waypoint; "
        "verify airway(s) and aircraft effectivity.",
    )
    canvas.setFillColor(theme.GREEN)
    canvas.setFont(theme.SANS_BOLD, 6.0)
    canvas.drawRightString(
        width - margin - 10,
        strip_y + 7,
        f"{normalized_registration(flight.get('registration'))} = "
        f"{_effectivity_series(flight)}",
    )

    events = detect_terrain_events(flight.get("route_waypoints") or [])
    ordered_events = sorted(
        events, key=lambda item: item["first_high"].get("actm_minutes") or 0
    )
    matched_by_event = {
        (finding.get("data") or {}).get("terrain_event_id"): finding
        for finding in _matched_event_findings(findings)
    }

    columns = [
        ("REF", 0.055),
        ("ACTUAL EXPOSURE", 0.155),
        ("FILED SEGMENT", 0.24),
        ("PROFILE / SOURCE", 0.24),
        ("CP / EFFECTIVITY", 0.16),
        ("RESULT", 0.15),
    ]
    table_x = margin
    table_width = width - 2 * margin
    header_y = strip_y - 24
    canvas.setFillColor(theme.AMBER)
    canvas.rect(table_x, header_y, table_width, 15, stroke=0, fill=1)
    canvas.setFillColor(theme.PANEL_DARK)
    canvas.setFont(theme.SANS_BOLD, 6.2)
    x = table_x
    for label, fraction in columns:
        canvas.drawString(x + 6, header_y + 4.5, label)
        x += table_width * fraction

    row_height = 46.0
    row_y = header_y
    for index, event in enumerate(ordered_events, start=1):
        row_y -= row_height
        canvas.setFillColor(theme.PANEL if index % 2 else theme.PANEL_DEEP)
        canvas.rect(table_x, row_y, table_width, row_height, stroke=0, fill=1)
        finding = matched_by_event.get(event.get("terrain_event_id"))
        data = (finding or {}).get("data") or {}
        chart_number = str(data.get("chart_number") or "")
        profile = _profile_by_chart(chart_number) or {}

        first = event["first_high"]
        end = event.get("drop") or event["last_high"]
        maximum = event.get("maximum") or {}
        cells: list[list[str]] = []
        cells.append([f"TERR-{index:02d}"])
        cells.append(
            [
                f"{format_actm(first.get('actm_minutes'))}-"
                f"{format_actm(end.get('actm_minutes'))}",
                f"Max {int(maximum.get('msa_hundreds_ft') or 0)}* "
                f"{maximum.get('name') or ''}",
            ]
        )
        filed = _filed_segment(flight, event)
        drop = event.get("drop")
        filed_lines = [filed]
        if drop is not None and (drop.get("msa_hundreds_ft") or 0) == 100:
            filed_lines.append(
                f"Drop {drop.get('name')} 100*"
            )
        cells.append(filed_lines)
        if finding is not None:
            cells.append(
                [
                    f"{chart_number} {profile.get('from')}-{profile.get('to')}",
                    ", ".join(profile.get("airways") or [])
                    + (
                        f" | p{profile.get('chart_page')}"
                        if profile.get("chart_page")
                        else ""
                    ),
                ]
            )
            critical_wp = next(
                (
                    waypoint
                    for waypoint in flight.get("route_waypoints") or []
                    if str(waypoint.get("name") or "").upper()
                    == str(profile.get("critical") or "").upper()
                ),
                None,
            )
            cells.append(
                [
                    f"{profile.get('critical')} "
                    + (
                        format_actm(critical_wp.get("actm_minutes"))
                        if critical_wp
                        else ""
                    ),
                    "/".join(profile.get("effectivity") or []),
                ]
            )
            chart_page_number = chart_page_numbers.get(chart_number)
            cells.append(
                [
                    "MATCH",
                    (
                        f"Full chart p{chart_page_number}"
                        if chart_page_number
                        else "Full chart embedded"
                    ),
                ]
            )
        else:
            cells.append(
                [
                    "No exact approved profile",
                    "in mounted index",
                ]
            )
            cells.append(
                [
                    f"{normalized_registration(flight.get('registration'))} "
                    f"{_effectivity_series(flight)}",
                    "effectivity not limiting",
                ]
            )
            cells.append(["UNRESOLVED"])

        x = table_x
        for column_index, (label, fraction) in enumerate(columns):
            lines = cells[column_index]
            if column_index == 5:
                colour = theme.GREEN if lines[0] == "MATCH" else theme.RED
                canvas.setFillColor(colour)
                canvas.setFont(theme.SANS_BOLD, 6.4)
            elif column_index == 0:
                canvas.setFillColor(theme.TEXT)
                canvas.setFont(theme.SANS_BOLD, 6.4)
            else:
                canvas.setFillColor(theme.TEXT)
                canvas.setFont(theme.SANS, 6.0)
            line_y = row_y + row_height - 14
            for line in lines[:3]:
                canvas.drawString(x + 6, line_y, str(line)[:46])
                line_y -= 9
            x += table_width * fraction

    # Source assurance / publication gate panel.
    panel_top = row_y - 10
    panel_height = 88.0
    canvas.setFillColor(theme.PANEL)
    canvas.roundRect(
        margin,
        panel_top - panel_height,
        width - 2 * margin,
        panel_height,
        5,
        stroke=0,
        fill=1,
    )
    canvas.setFillColor(theme.BLUE)
    canvas.setFont(theme.SANS_BOLD, 7.6)
    canvas.drawString(
        margin + 12, panel_top - 18, "SOURCE ASSURANCE / PUBLICATION GATE"
    )
    rules = [
        "1. Profile charts are embedded on the following pages; profile "
        "identifiers alone are not a compliant release.",
        "2. Actual MSA exposure is not replaced by chart altitude. The CFP "
        "window and approved chart coverage are presented separately.",
        "3. Exact 100* rows terminate an active event. FIR-boundary rows "
        "without a parsed MSA do not terminate an active event.",
        "4. Unmatched events remain unresolved; no nearby or generic profile "
        "is substituted.",
    ]
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.8)
    line_y = panel_top - 32
    for rule in rules:
        canvas.drawString(margin + 12, line_y, rule)
        line_y -= 11
    button_x = width - margin - 12
    for finding in reversed(_matched_findings(findings)[:2]):
        chart_number = str((finding.get("data") or {}).get("chart_number") or "")
        label = f"OPEN PROFILE {chart_number}"
        button_width = pdfmetrics.stringWidth(label, theme.SANS_BOLD, 6.2) + 26
        button_x -= button_width
        button_y = panel_top - panel_height + 10
        canvas.setStrokeColor(theme.BLUE)
        canvas.setLineWidth(0.9)
        canvas.setFillColor(theme.PAGE_BG)
        canvas.roundRect(button_x, button_y, button_width, 16, 8, stroke=1, fill=1)
        canvas.setFillColor(theme.TEXT)
        canvas.setFont(theme.SANS_BOLD, 6.2)
        canvas.drawCentredString(
            button_x + button_width / 2, button_y + 5.5, label
        )
        destination = f"profile-chart-{chart_number}"
        canvas.linkRect(
            label,
            destination,
            (button_x, button_y, button_x + button_width, button_y + 16),
            relative=0,
        )
        button_x -= 10

    chips = []
    pages = sorted(
        {
            waypoint.get("source_page")
            for event in events
            for waypoint in (event.get("first_high"), event.get("last_high"))
            if waypoint and waypoint.get("source_page")
        }
    )
    if pages:
        chips.append(
            "CFP P" + "-".join(str(page) for page in (pages[0], pages[-1]))
            if len(pages) > 1
            else f"CFP P{pages[0]}"
        )
    for finding in _matched_findings(findings)[:2]:
        chart_number = str((finding.get("data") or {}).get("chart_number") or "")
        chips.append(f"PROFILE {chart_number}")
    if _unresolved_findings(findings):
        chips.append("UNRESOLVED")
    theme.draw_source_chips(canvas, chips, width=width)
    theme.draw_footer(
        canvas,
        flight,
        width=width,
        page_number=page_number,
        page_count=page_count,
    )


def draw_source_chart_page(
    canvas: Any,
    flight: dict[str, Any],
    image: dict[str, Any],
    width: float,
    height: float,
    *,
    page_number: int,
    page_count: int,
) -> None:
    """One appended page: the complete authoritative source chart."""
    theme.register_fonts()
    chart_number = image["chart_number"]
    canvas.bookmarkPage(f"profile-chart-{chart_number}")
    canvas.setFillColor(theme.PANEL_DARK)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    bar_height = 18.0
    canvas.setFillColor(theme.PAGE_BG)
    canvas.rect(0, height - bar_height, width, bar_height, stroke=0, fill=1)
    canvas.setFillColor(theme.TEXT)
    canvas.setFont(theme.SANS_BOLD, 7.0)
    canvas.drawString(
        16,
        height - bar_height + 6,
        " | ".join(
            (
                "PILOTDRIVEN ODSS",
                theme.display_flight_number(flight),
                (
                    f"{flight.get('aircraft_type') or ''} "
                    f"{normalized_registration(flight.get('registration'))}"
                ).strip(),
                f"LEVEL 2 SOURCE CHART - PROFILE {chart_number}",
            )
        ),
    )
    canvas.setFont(theme.SANS, 6.4)
    canvas.drawRightString(
        width - 16,
        height - bar_height + 6,
        f"Page {page_number} of {page_count}",
    )

    # Fit the complete chart page below the bar on a white sheet.
    available_width = width - 24
    available_height = height - bar_height - 20
    scale = min(
        available_width / image["width"],
        available_height / image["height"],
    )
    draw_width = image["width"] * scale
    draw_height = image["height"] * scale
    x = (width - draw_width) / 2
    y = (height - bar_height - 8 - draw_height)
    canvas.setFillColor(theme.TEXT)
    canvas.rect(x - 4, y - 4, draw_width + 8, draw_height + 8, stroke=0, fill=1)
    canvas.drawImage(
        ImageReader(io.BytesIO(image["png"])),
        x,
        y,
        width=draw_width,
        height=draw_height,
    )
