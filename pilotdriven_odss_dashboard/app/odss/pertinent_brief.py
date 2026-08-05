from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.utils import ImageReader
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph

from .briefing import (
    build_briefing_view,
    draw_route_map_pdf,
    project_route_map,
)
from . import brief_theme as theme
from .constants import edto_sectors, format_actm
from .controlled_library import DEPRESS_LIBRARY_METADATA
from .depress_analysis_page import draw_depressurisation_analysis
from .depress_matrix_page import load_matched_chart_images
from .engines import detect_terrain_events
from .pilot_briefing import (
    normalize_notam_references,
    pilot_notam_condition,
    prepare_pilot_findings,
)
from .report_facts import (
    actm_utc_clock,
    actual_timing_anchor,
    build_route_gate_rows,
    deferred_item_report_rows,
    is_confirmed_profile_finding,
    profile_coverage_label,
    profile_finding_label,
    profile_findings_for_terrain_event,
    select_route_gate_rows,
)
from .surface_overlays import (
    surface_conflict_publication_label,
    surface_mark_presentation,
)
from .profile_chart_gate import (
    build_profile_chart_artifact_contracts,
    validate_depressurisation_profile_charts,
)


PAGE_SIZE = landscape(A4)
LEVEL1_DEPRESSURISATION_REPORT_PAGE = 3

# Information-category colours. Urgency is communicated separately.
CATEGORY_COLOURS = {
    "departure": "#2DB4F0",
    "destination": "#8B5CF6",
    "edto": "#38C18C",
    "weather": "#F4A91D",
    "communications": "#35C0BC",
    "terrain": "#FFB21A",
    "critical": "#FF5B68",
    "neutral": "#6D8798",
}

_DARK = theme.PAGE_BG
_PANEL = theme.PANEL_DEEP
_PANEL_2 = theme.PANEL
_LINE = theme.LINE
_TEXT = theme.TEXT
_MUTED = theme.MUTED
_WHITE_BG = colors.HexColor("#F4F7FA")
_NAVY = colors.HexColor("#173B65")

_DEPARTURE = colors.HexColor(CATEGORY_COLOURS["departure"])
_DESTINATION = colors.HexColor(CATEGORY_COLOURS["destination"])
_EDTO = colors.HexColor(CATEGORY_COLOURS["edto"])
_WEATHER = colors.HexColor(CATEGORY_COLOURS["weather"])
_COMMUNICATIONS = colors.HexColor(CATEGORY_COLOURS["communications"])
_TERRAIN = colors.HexColor(CATEGORY_COLOURS["terrain"])
_CRITICAL = colors.HexColor(CATEGORY_COLOURS["critical"])
_NEUTRAL = colors.HexColor(CATEGORY_COLOURS["neutral"])

REPORT_TYPOGRAPHY = {
    # Pilot-facing report content targets normal 10pt print readability.
    # Dense chart annotations, navigation labels and legal/footer metadata are
    # intentionally smaller because they identify the visual rather than carry
    # an operational finding.
    "body": 10.5,
    "body_small": 10.0,
    "body_light": 10.5,
    "body_light_small": 10.0,
    "metric": 10.0,
    "panel_title": 9.0,
    "table_header": 9.0,
}
_MIN_BODY_FONT_SIZE = 6.8


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "dark": ParagraphStyle(
            "Pertinent dark",
            parent=base["BodyText"],
            fontName=theme.SANS,
            fontSize=REPORT_TYPOGRAPHY["body"],
            leading=12.6,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "dark_small": ParagraphStyle(
            "Pertinent dark small",
            parent=base["BodyText"],
            fontName=theme.SANS,
            fontSize=REPORT_TYPOGRAPHY["body_small"],
            leading=12.0,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light": ParagraphStyle(
            "Pertinent light",
            parent=base["BodyText"],
            fontName=theme.SANS,
            fontSize=REPORT_TYPOGRAPHY["body_light"],
            leading=12.6,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light_small": ParagraphStyle(
            "Pertinent light small",
            parent=base["BodyText"],
            fontName=theme.SANS,
            fontSize=REPORT_TYPOGRAPHY["body_light_small"],
            leading=12.0,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=0,
            spaceBefore=0,
        ),
        "metric": ParagraphStyle(
            "Pertinent metric",
            parent=base["BodyText"],
            fontName=theme.SANS,
            fontSize=REPORT_TYPOGRAPHY["metric"],
            leading=12.0,
            alignment=TA_CENTER,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
    }


_STYLES = _styles()
_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}


def _clean_lines(lines: list[str]) -> list[str]:
    return [" ".join(str(line).split()) for line in lines if str(line).strip()]


def _paragraph(lines: list[str], style: ParagraphStyle) -> Paragraph:
    prepared = _clean_lines(lines)
    text = "<br/>".join(escape(line) for line in prepared)
    return Paragraph(text or " ", style)


def _paragraph_height(lines: list[str], style: ParagraphStyle, width: float) -> float:
    paragraph = _paragraph(lines, style)
    _, height = paragraph.wrap(max(1.0, width), 10_000)
    return height


def _scaled_style(style: ParagraphStyle, font_size: float) -> ParagraphStyle:
    return ParagraphStyle(
        f"{style.name} {font_size:.1f}pt",
        parent=style,
        fontSize=font_size,
        leading=font_size * 1.2,
    )


def _largest_fitting_style(
    lines: list[str],
    style: ParagraphStyle,
    width: float,
    height: float,
) -> ParagraphStyle:
    """Keep pilot text at its 10pt target unless fixed geometry requires less."""
    target = float(style.fontSize)
    size = target
    while size >= _MIN_BODY_FONT_SIZE:
        candidate = style if size == target else _scaled_style(style, size)
        if _paragraph_height(lines, candidate, width) <= height:
            return candidate
        size = round(size - 0.5, 1)
    return _scaled_style(style, _MIN_BODY_FONT_SIZE)


def _panel_height(
    lines: list[str],
    width: float,
    style: ParagraphStyle,
    *,
    min_height: float = 15 * mm,
) -> float:
    if not _clean_lines(lines):
        return 0.0
    title_height = 7.5 * mm
    body_width = max(1.0, width - 6 * mm)
    body_height = _paragraph_height(lines, style, body_width)
    return max(min_height, title_height + body_height + 5.5 * mm)


def _fit_lines(
    lines: list[str],
    style: ParagraphStyle,
    width: float,
    available_height: float,
) -> list[str]:
    original = _clean_lines(lines)
    prepared = list(original)
    if not prepared:
        return []
    while prepared and _paragraph_height(prepared, style, width) > available_height:
        prepared = prepared[:-1]
    if len(prepared) < len(original) and prepared:
        marker = "Further detail in expanded briefing."
        while prepared and _paragraph_height(prepared + [marker], style, width) > available_height:
            prepared = prepared[:-1]
        prepared.append(marker)
    return prepared


def _draw_panel(
    canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    lines: list[str],
    accent: colors.Color,
    *,
    dark: bool,
    style: ParagraphStyle,
) -> None:
    if height <= 0:
        return
    background = _PANEL if dark else colors.white
    border = _LINE if dark else colors.HexColor("#D9E1E8")
    canvas.setFillColor(background)
    canvas.setStrokeColor(border)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)

    title_height = 7.5 * mm
    canvas.setFillColor(accent)
    canvas.roundRect(x, y + height - title_height, width, title_height, 3.5, fill=1, stroke=0)
    canvas.rect(x, y + height - title_height, width, title_height / 2, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont(
        theme.SANS_BOLD,
        6.4 if len(title) > 28 else REPORT_TYPOGRAPHY["panel_title"],
    )
    canvas.drawString(x + 3 * mm, y + height - 4.9 * mm, title)

    body_x = x + 3 * mm
    body_y = y + 2.6 * mm
    body_width = width - 6 * mm
    body_height = max(1.0, height - title_height - 4.8 * mm)
    fitted_style = _largest_fitting_style(
        lines,
        style,
        body_width,
        body_height,
    )
    fitted = _fit_lines(lines, fitted_style, body_width, body_height)
    paragraph = _paragraph(fitted, fitted_style)
    _, required = paragraph.wrap(body_width, body_height)
    paragraph.drawOn(canvas, body_x, body_y + max(0.0, body_height - required))


def _draw_column_stack(
    canvas,
    x: float,
    top: float,
    bottom: float,
    width: float,
    panels: list[dict[str, Any]],
    *,
    gap: float = 2.5 * mm,
) -> None:
    visible = [panel for panel in panels if _clean_lines(panel.get("lines") or [])]
    if not visible:
        return

    natural = [
        _panel_height(
            panel["lines"],
            width,
            panel.get("style") or _STYLES["light_small"],
            min_height=panel.get("min_height", 15 * mm),
        )
        for panel in visible
    ]
    available = max(1.0, top - bottom - gap * (len(visible) - 1))
    total = sum(natural)
    if total > available:
        scale = available / total
        heights = [max(13 * mm, value * scale) for value in natural]
        overflow = sum(heights) - available
        if overflow > 0:
            adjustable = [max(0.0, height - 13 * mm) for height in heights]
            adjustable_total = sum(adjustable)
            if adjustable_total > 0:
                heights = [
                    height - overflow * room / adjustable_total
                    for height, room in zip(heights, adjustable)
                ]
    else:
        heights = natural

    cursor = top
    for panel, height in zip(visible, heights):
        y = cursor - height
        _draw_panel(
            canvas,
            x,
            y,
            width,
            height,
            panel["title"],
            panel["lines"],
            panel["accent"],
            dark=bool(panel.get("dark", False)),
            style=panel.get("style") or _STYLES["light_small"],
        )
        cursor = y - gap


def _draw_balanced_columns(
    canvas,
    left_x: float,
    right_x: float,
    top: float,
    bottom: float,
    width: float,
    panels: list[dict[str, Any]],
    *,
    gap: float = 2.5 * mm,
) -> None:
    """Lay out content-driven detail panels without reserving empty card space."""
    columns: list[list[dict[str, Any]]] = [[], []]
    column_heights = [0.0, 0.0]
    for panel in panels:
        lines = panel.get("lines") or []
        if not _clean_lines(lines):
            continue
        prepared = dict(panel)
        prepared["style"] = panel.get("style") or _STYLES["light"]
        height = _panel_height(
            lines,
            width,
            prepared["style"],
            min_height=panel.get("min_height", 15 * mm),
        )
        index = 0 if column_heights[0] <= column_heights[1] else 1
        if columns[index]:
            column_heights[index] += gap
        columns[index].append(prepared)
        column_heights[index] += height

    _draw_column_stack(canvas, left_x, top, bottom, width, columns[0], gap=gap)
    _draw_column_stack(canvas, right_x, top, bottom, width, columns[1], gap=gap)


def _draw_centered_metric_cell(
    canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    background: colors.Color,
) -> None:
    canvas.setFillColor(background)
    canvas.setStrokeColor(_LINE)
    canvas.rect(x, y, width, height, fill=1, stroke=1)
    centre_y = y + height / 2
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS_BOLD, theme.readable(4.8))
    canvas.drawCentredString(x + width / 2, centre_y + 1.6 * mm, str(label))
    canvas.setFillColor(_TEXT)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.5))
    canvas.drawCentredString(x + width / 2, centre_y - 2.6 * mm, str(value))


def _draw_metric_strip(
    canvas,
    items: list[tuple[str, str]],
    x: float,
    y: float,
    width: float,
    height: float,
    background: colors.Color,
) -> None:
    cell = width / max(1, len(items))
    for index, (label, value) in enumerate(items):
        _draw_centered_metric_cell(
            canvas,
            x + index * cell,
            y,
            cell,
            height,
            label,
            value,
            background,
        )


def _draw_compact_table(
    canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    columns: list[tuple[str, float]],
    rows: list[list[str]],
    accent: colors.Color,
    empty_text: str,
) -> None:
    data = rows or [[empty_text] + [""] * (len(columns) - 1)]
    header_h = 7.5 * mm
    row_h = max(7 * mm, (height - header_h) / max(1, len(data)))
    if header_h + row_h * len(data) > height:
        visible = max(1, int((height - header_h) // (7 * mm)))
        data = data[:visible]
        row_h = (height - header_h) / len(data)

    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)
    canvas.setFillColor(accent)
    canvas.roundRect(
        x,
        y + height - header_h,
        width,
        header_h,
        3.5,
        fill=1,
        stroke=0,
    )
    canvas.rect(
        x,
        y + height - header_h,
        width,
        header_h / 2,
        fill=1,
        stroke=0,
    )

    widths = [width * fraction for _, fraction in columns]
    column_x = x
    for index, ((label, _), column_width) in enumerate(zip(columns, widths)):
        canvas.setFillColor(colors.white)
        canvas.setFont(theme.SANS_BOLD, REPORT_TYPOGRAPHY["table_header"])
        canvas.drawString(
            column_x + 2 * mm,
            y + height - 4.8 * mm,
            str(label)[:32],
        )
        if index:
            canvas.setStrokeColor(_LINE)
            canvas.line(column_x, y, column_x, y + height)
        column_x += column_width

    top = y + height - header_h
    for row_index, row in enumerate(data):
        row_top = top - row_index * row_h
        row_bottom = row_top - row_h
        if row_index % 2:
            canvas.setFillColor(_PANEL_2)
            canvas.rect(x, row_bottom, width, row_h, fill=1, stroke=0)
        canvas.setStrokeColor(_LINE)
        canvas.line(x, row_bottom, x + width, row_bottom)
        column_x = x
        for column_index, column_width in enumerate(widths):
            value = row[column_index] if column_index < len(row) else ""
            body_width = max(1.0, column_width - 4 * mm)
            body_height = max(1.0, row_h - 2.6 * mm)
            fitted_style = _largest_fitting_style(
                [str(value)],
                _STYLES["dark_small"],
                body_width,
                body_height,
            )
            fitted = _fit_lines(
                [str(value)],
                fitted_style,
                body_width,
                body_height,
            )
            paragraph = _paragraph(fitted, fitted_style)
            _, required = paragraph.wrap(body_width, body_height)
            paragraph.drawOn(
                canvas,
                column_x + 2 * mm,
                row_bottom + max(1.2 * mm, (row_h - required) / 2),
            )
            column_x += column_width


def _interpolate_route_point(
    points: list[dict[str, Any]],
    actm_minutes: int,
    *,
    name: str,
    role: str,
) -> dict[str, Any] | None:
    timed = [
        point
        for point in points
        if point.get("actm_minutes") is not None
    ]
    if not timed:
        return None
    for point in timed:
        if int(point["actm_minutes"]) == int(actm_minutes):
            return {
                **point,
                "name": name,
                "display_name": name,
                "role": role,
            }
    before = None
    after = None
    for point in timed:
        point_actm = int(point["actm_minutes"])
        if point_actm < actm_minutes:
            before = point
        elif point_actm > actm_minutes:
            after = point
            break
    if before is None or after is None:
        return None
    span = int(after["actm_minutes"]) - int(before["actm_minutes"])
    if span <= 0:
        return None
    ratio = (actm_minutes - int(before["actm_minutes"])) / span
    return {
        "name": name,
        "display_name": name,
        "latitude": float(before["latitude"])
        + (float(after["latitude"]) - float(before["latitude"])) * ratio,
        "longitude": float(before["longitude"])
        + (float(after["longitude"]) - float(before["longitude"])) * ratio,
        "plot_longitude": float(before["plot_longitude"])
        + (
            float(after["plot_longitude"])
            - float(before["plot_longitude"])
        )
        * ratio,
        "actm_minutes": actm_minutes,
        "msa_hundreds_ft": None,
        "vws": None,
        "role": role,
    }


def _route_window_points(
    route_points: list[dict[str, Any]],
    start_actm: int,
    end_actm: int,
    *,
    markers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    timed_indices = [
        index
        for index, point in enumerate(route_points)
        if point.get("actm_minutes") is not None
        and start_actm <= int(point["actm_minutes"]) <= end_actm
    ]
    if not timed_indices:
        return []
    first = max(0, timed_indices[0] - 1)
    last = min(len(route_points) - 1, timed_indices[-1] + 1)
    selected = [dict(point) for point in route_points[first:last + 1]]
    selected.extend(markers or [])
    selected.sort(
        key=lambda point: (
            int(point.get("actm_minutes") or -1),
            0 if point.get("role") == "route" else 1,
        )
    )
    return selected


def _sector_etp_markers(
    route_points: list[dict[str, Any]],
    sector: dict[str, Any],
    sector_number: int,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for item in sorted(
        (
            item
            for item in (sector.get("etps") or [])
            if isinstance(item, dict) and item.get("actm_minutes") is not None
        ),
        key=lambda item: int(item["actm_minutes"]),
    ):
        actm = int(item["actm_minutes"])
        latitude = float(item.get("latitude") or 0.0)
        longitude = float(item.get("longitude") or 0.0)
        cluster = next(
            (
                candidate
                for candidate in clusters
                if abs(int(candidate["actm"]) - actm) <= 1
                and abs(float(candidate["latitude"]) - latitude) <= 0.5
                and abs(float(candidate["longitude"]) - longitude) <= 0.5
            ),
            None,
        )
        if cluster is None:
            cluster = {
                "actm": actm,
                "latitude": latitude,
                "longitude": longitude,
                "labels": [],
                "airports": item.get("airports") or [],
            }
            clusters.append(cluster)
        cluster["labels"].append(str(item.get("label") or "ETP"))

    markers: list[dict[str, Any]] = []
    for cluster in clusters:
        actm = int(cluster["actm"])
        latitude = float(cluster["latitude"])
        longitude = float(cluster["longitude"])
        interpolated = _interpolate_route_point(
            route_points,
            actm,
            name="ETP",
            role="edto_etp",
        )
        if interpolated is None:
            continue
        plot_longitude = longitude
        while plot_longitude - float(interpolated["plot_longitude"]) > 180:
            plot_longitude -= 360
        while float(interpolated["plot_longitude"]) - plot_longitude > 180:
            plot_longitude += 360
        unique_labels = list(dict.fromkeys(cluster["labels"]))
        label = " / ".join(unique_labels)
        markers.append({
            **interpolated,
            "name": f"S{sector_number} ETP {label}",
            "display_name": f"S{sector_number} ETP {label}",
            "latitude": latitude,
            "longitude": longitude,
            "plot_longitude": plot_longitude,
            "etp_labels": unique_labels,
            "airports": cluster["airports"],
        })
    return markers


def _draw_route_evidence_chart(
    canvas,
    points: list[dict[str, Any]],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    title: str,
    mode: str,
) -> None:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.2))
    canvas.drawString(x + 3 * mm, y + height - 5.3 * mm, title[:58])
    note = (
        "Geographic route strip - validated CFP MSA points only"
        if mode == "terrain"
        else "CFP route coordinates and EDTO times"
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS, theme.readable(4.5))
    canvas.drawRightString(x + width - 3 * mm, y + height - 5.2 * mm, note)

    plot_x = x + 3 * mm
    plot_y = y + 4 * mm
    plot_width = width - 6 * mm
    plot_height = height - 12 * mm
    projection_padding = 18.0 if mode == "terrain" else 10.0
    projection = project_route_map(
        {"points": points},
        plot_width,
        plot_height,
        projection_padding,
    )
    projected = projection.get("points") or []
    if len(projected) < 2:
        canvas.setFillColor(_MUTED)
        canvas.setFont(theme.SANS_BOLD, 7)
        canvas.drawCentredString(
            x + width / 2,
            y + height / 2,
            "Verified route coordinates unavailable",
        )
        return

    if mode == "terrain":
        draw_route_map_pdf(
            canvas,
            {
                "points": points,
                "label_indices": [],
                "hazard_features": [],
                "note": "",
            },
            plot_x,
            plot_y,
            plot_width,
            plot_height,
        )
    else:
        canvas.setStrokeColor(colors.HexColor("#203C57"))
        canvas.setLineWidth(0.35)
        for fraction in (0.25, 0.5, 0.75):
            canvas.line(
                plot_x,
                plot_y + plot_height * fraction,
                plot_x + plot_width,
                plot_y + plot_height * fraction,
            )
            canvas.line(
                plot_x + plot_width * fraction,
                plot_y,
                plot_x + plot_width * fraction,
                plot_y + plot_height,
            )

    route_sequence = [
        point
        for point in projected
        if point.get("role") != "edto_etp"
    ]
    if mode != "terrain":
        canvas.setStrokeColor(_TEXT)
        canvas.setLineWidth(1.4)
        route_path = canvas.beginPath()
        route_path.moveTo(
            plot_x + route_sequence[0]["x"],
            plot_y + route_sequence[0]["y"],
        )
        for point in route_sequence[1:]:
            route_path.lineTo(plot_x + point["x"], plot_y + point["y"])
        canvas.drawPath(route_path, stroke=1, fill=0)

    label_count = 0
    for index, point in enumerate(projected):
        role = str(point.get("role") or "route")
        msa = point.get("msa_hundreds_ft")
        is_high = bool(point.get("msa_asterisk")) or (
            msa is not None and int(msa) > 100
        )
        if role == "edto_etp":
            colour = _EDTO
        elif role in {"edto_entry", "edto_exit"}:
            colour = _DEPARTURE
        elif is_high:
            colour = _CRITICAL if int(msa or 0) >= 150 else _WEATHER
        else:
            colour = _TEXT
        radius = 2.1 if role != "route" or is_high else 1.3
        px = plot_x + point["x"]
        py = plot_y + point["y"]
        canvas.setFillColor(colour)
        canvas.circle(px, py, radius, fill=1, stroke=0)

        important = (
            index in {0, len(projected) - 1}
            or role in {"edto_entry", "edto_exit", "edto_etp"}
            or (mode == "terrain" and role == "terrain")
        )
        if not important:
            continue
        label_count += 1
        label = str(point.get("display_name") or point.get("name") or "")
        if mode == "terrain" and msa is not None:
            label += f" {int(msa):03d}{'*' if point.get('msa_asterisk') else ''}"
        canvas.setFillColor(colour)
        canvas.setFont(theme.SANS_BOLD, theme.readable(4.4))
        label_width = pdfmetrics.stringWidth(label[:22], theme.SANS_BOLD, 4.4)
        dx = (
            -label_width - 3
            if px > plot_x + plot_width * 0.76
            else 3
        )
        canvas.drawString(
            px + dx,
            py + (4 if label_count % 2 else -7),
            label[:22],
        )


def _slot_allocation_line(flight: dict[str, Any]) -> str:
    """One-line slot allocation from the CFP, or empty when none is held."""
    allocation = flight.get("bobcat") or {}
    waypoint = str(allocation.get("waypoint") or "")
    if not waypoint:
        return ""
    ctot = theme.utc_hhmm(allocation.get("ctot_utc"))
    cto = theme.utc_hhmm(allocation.get("cto_utc"))
    level = allocation.get("flight_level")
    parts = [f"SLOT {waypoint}"]
    if level:
        parts.append(f"FL{level}")
    return f"{' '.join(parts)} · CTOT {ctot} · CTO {cto}"


def _draw_phase_timeline(
    canvas,
    *,
    sectors: list[dict[str, Any]],
    communications: list[dict[str, Any]],
    clock_basis: str,
    final_actm: int,
    x: float,
    y: float,
    width: float,
    height: float,
    slot_line: str = "",
) -> None:
    canvas.setFillColor(_PANEL_2)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS_BOLD, theme.readable(5.2))
    canvas.drawString(x + 3 * mm, y + height - 4.8 * mm, "FLIGHT PHASE WINDOWS")
    canvas.drawRightString(
        x + width - 3 * mm,
        y + height - 4.8 * mm,
        clock_basis,
    )
    line_y = y + height / 2
    line_start = x + 6 * mm
    line_width = width - 12 * mm
    canvas.setStrokeColor(colors.HexColor("#42647B"))
    canvas.setLineWidth(0.8)
    canvas.line(line_start, line_y, line_start + line_width, line_y)
    scale = max(1, final_actm)

    for index, sector in enumerate(sectors, start=1):
        start = int(sector.get("entry_actm_minutes") or 0)
        end = int(sector.get("exit_actm_minutes") or start)
        sx = line_start + line_width * min(1.0, start / scale)
        ex = line_start + line_width * min(1.0, end / scale)
        canvas.setStrokeColor(_EDTO)
        canvas.setLineWidth(3.2)
        canvas.line(sx, line_y, max(sx + 2, ex), line_y)
        canvas.setFillColor(_EDTO)
        canvas.setFont(theme.SANS_BOLD, theme.readable(4.6))
        canvas.drawCentredString(
            (sx + ex) / 2,
            line_y + 3.3 * mm,
            f"EDTO {index}",
        )
        canvas.setFillColor(_MUTED)
        canvas.setFont(theme.SANS, theme.readable(4.2))
        canvas.drawCentredString(
            (sx + ex) / 2,
            line_y - 4.4 * mm,
            f"{format_actm(start)}-{format_actm(end)}",
        )

    for item in communications[:4]:
        actm = (item.get("data") or {}).get("action_actm_minutes")
        if actm is None:
            continue
        px = line_start + line_width * min(1.0, int(actm) / scale)
        canvas.setFillColor(_WEATHER)
        canvas.circle(px, line_y, 2.0, fill=1, stroke=0)
        canvas.setFillColor(_WEATHER)
        canvas.setFont(theme.SANS_BOLD, theme.readable(4.1))
        label = str(item.get("title") or "ATC").rsplit(" ", 1)[-1]
        canvas.drawCentredString(
            px,
            line_y + (6.8 if int(actm) % 2 else 9.3) * mm,
            label[:15],
        )

    # The slot allocation is a timing constraint and belongs on the timing page.
    # It reached Level 2 only, so the pertinent brief a captain carries showed a
    # BOBCAT waypoint on the route map with none of its clocks.
    if slot_line:
        canvas.setFillColor(_WEATHER)
        canvas.setFont(theme.SANS_BOLD, theme.readable(5.2))
        canvas.drawRightString(x + width - 3 * mm, y + 2.6 * mm, slot_line)


def _surface_overlay(
    flight: dict[str, Any],
    *,
    role: str,
    icao: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in (flight.get("surface_overlays") or [])
            if item.get("role") == role and item.get("icao") == icao
        ),
        None,
    )


def _surface_entity_label(item: dict[str, Any]) -> str:
    return " ".join(
        value
        for value in (
            str(item.get("entityType") or "").upper(),
            str(item.get("entityRef") or ""),
        )
        if value
    ) or str(item.get("notamNumber") or "surface item")


def _surface_clock(value: Any, reference: Any = None) -> str | None:
    text = str(value or "")
    if len(text) < 16 or text[4] != "-":
        return None
    clock = text[11:16].replace(":", "") + "Z"
    reference_text = str(reference or "")
    if len(reference_text) >= 10 and text[:10] != reference_text[:10]:
        # A bare clock lies about multi-day windows ("0900Z-0900Z" reading as
        # zero-length); endpoints outside the reference day carry their day.
        return f"{text[8:10]} {clock}"
    return clock


def _surface_period(item: dict[str, Any]) -> str | None:
    reference = item.get("referenceAt")
    interval = item.get("referenceInterval") or item.get("validityInterval") or {}
    start = _surface_clock(interval.get("startsAt"), reference)
    end = _surface_clock(interval.get("endsAt"), reference)
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"from {start}"
    if end:
        return f"until {end}"
    return None


def _surface_source_conflict_line(item: dict[str, Any]) -> str | None:
    conflict = item.get("sourceConflict") or {}
    if not isinstance(conflict, dict) or not conflict:
        return None

    def full_time(value: Any) -> str:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text or "unavailable"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%d %b %y %H%MZ").upper()

    publication = surface_conflict_publication_label(conflict)
    uploaded = conflict.get("uploaded") or {}
    reviewed = conflict.get("reviewed") or {}
    field_labels = {"startsAt": "start", "endsAt": "end"}
    comparisons = [
        (
            f"{field_labels[field]} uploaded {full_time(uploaded.get(field))}, "
            f"reviewed {full_time(reviewed.get(field))}"
        )
        for field in conflict.get("conflictingFields") or []
        if field in field_labels
    ]
    detail = "; ".join(comparisons) or str(item.get("evidence") or "").strip()
    return (
        f"Source conflict: {publication}"
        + (f"; {detail}" if detail else "")
        + "; pilot review required."
    )


def _surface_detail_line(prefix: str, item: dict[str, Any]) -> str:
    # "There has to be a period": every stated restriction carries its NOTAM id
    # and window; a missing window states itself instead of hiding.
    parts = [f"{prefix}: {_surface_entity_label(item)}"]
    notam = str(item.get("notamNumber") or "").strip()
    if notam:
        parts.append(notam)
    parts.append(_surface_period(item) or "period unresolved - review")
    return " | ".join(parts)


def _surface_overlay_lines(
    overlay: dict[str, Any],
    *,
    detail_limit: int,
) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in overlay.get("mapped") or []:
        presentation = surface_mark_presentation(item)
        if presentation is not None:
            grouped[presentation].append(item)

    # Stable ordering keeps the producer's order within each class while
    # guaranteeing that a governed-source disagreement cannot be clipped by a
    # compact panel's review-row limit.
    review_required = sorted(
        overlay.get("reviewRequired") or [],
        key=lambda item: 0 if item.get("sourceConflict") else 1,
    )
    ordered = (
        ("closure", "exact closure", "Closed"),
        ("scheduled", "scheduled restriction", "Scheduled"),
        ("equipment", "equipment-unavailable", "Equipment"),
        ("locator", "locator/review", "Review locator"),
    )
    counts = [
        f"{len(grouped[key])} {description} "
        f"mark{'s' if len(grouped[key]) != 1 else ''}"
        for key, description, _ in ordered
        if grouped[key]
    ]
    if counts:
        lines = ["Surface overlay: " + "; ".join(counts) + "."]
        details = [
            _surface_detail_line(prefix, item)
            for key, _, prefix in ordered
            for item in grouped[key]
        ]
    elif review_required:
        lines = [
            "Surface overlay: no validated mark; "
            f"{len(review_required)} item"
            f"{'s' if len(review_required) != 1 else ''} require chart review."
        ]
        details = []
    else:
        lines = [
            "Surface overlay: no applicable surface mark at the selected time."
        ]
        details = []
    # Review lines name their subject — "doesn't say what" is not a state a
    # pilot can act on. Safety-significant source conflicts precede lower-risk
    # mapped detail so compact report panels cannot silently clip them.
    for row in review_required[:2]:
        notam = str(row.get("notamNumber") or "").strip()
        entity = " ".join(
            value
            for value in (
                str(row.get("entityType") or "").upper(),
                str(row.get("entityRef") or ""),
            )
            if value
        )
        subject = " ".join(part for part in (notam, entity) if part)
        plain = str(row.get("plainEnglish") or "surface location unresolved")
        conflict_line = _surface_source_conflict_line(row)
        if conflict_line:
            lines.append(
                f"Review required: {subject + ' - ' if subject else ''}"
                f"{conflict_line}"
            )
        else:
            lines.append(
                f"Review required: {subject + ' - ' if subject else ''}{plain}"
            )
    lines.extend(details[:detail_limit])
    return lines


def _airport_lines(
    panel: dict[str, Any],
    overlay: dict[str, Any] | None,
    personal_lines: list[str] | None = None,
) -> list[str]:
    lines = [
        f"{panel['icao']} | Planned runway {panel['runway']}",
        f"WX: {panel['weather']['primary']}",
    ]
    if overlay:
        window = overlay.get("window") or {}
        if window.get("startsAt") and window.get("endsAt"):
            lines.append(
                "CFP NOTAM window: "
                f"{str(window['startsAt'])[11:16]}Z-"
                f"{str(window['endsAt'])[11:16]}Z"
            )
        lines.extend(_surface_overlay_lines(overlay, detail_limit=3))
    else:
        lines.append("Surface overlay unavailable - review the current official chart.")
    lines.extend(personal_lines or [])
    lines.extend(
        f"{item['kind']}: {item['text']}"
        for item in panel.get("considerations", [])[:2]
    )
    return lines


def _airport_accent(panel: dict[str, Any]) -> colors.Color:
    return _DESTINATION if panel.get("role") == "destination" else _DEPARTURE


def _surface_points(value: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []

    def visit(item: Any) -> None:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            points.append((float(item[0]), float(item[1])))
            return
        if isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return points


def _draw_surface_schematic(
    canvas,
    overlay: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas.setFillColor(colors.HexColor("#071725"))
    canvas.rect(x, y, width, height, fill=1, stroke=0)
    bounds = overlay.get("bounds") or {}
    west = bounds.get("west")
    south = bounds.get("south")
    east = bounds.get("east")
    north = bounds.get("north")
    if not all(isinstance(value, (int, float)) for value in (west, south, east, north)):
        canvas.setFillColor(_MUTED)
        canvas.setFont(theme.SANS, theme.readable(5.2))
        canvas.drawCentredString(
            x + width / 2,
            y + height / 2,
            "Surface geometry unavailable",
        )
        return
    longitude_span = max(1e-9, float(east) - float(west))
    latitude_span = max(1e-9, float(north) - float(south))

    def projected(point: tuple[float, float]) -> tuple[float, float]:
        longitude, latitude = point
        return (
            x + 2 * mm + (longitude - float(west)) / longitude_span * (width - 4 * mm),
            y + 2 * mm + (latitude - float(south)) / latitude_span * (height - 4 * mm),
        )

    mapped_ids = {
        str(feature_id)
        for item in (overlay.get("mapped") or [])
        for feature_id in (item.get("featureIds") or [])
    }
    for feature in (overlay.get("featureCollection") or {}).get("features") or []:
        properties = feature.get("properties") or {}
        feature_id = str(properties.get("featureId") or feature.get("id") or "")
        aeroway = str(properties.get("aeroway") or "")
        is_closed = feature_id in mapped_ids
        points = _surface_points((feature.get("geometry") or {}).get("coordinates"))
        if len(points) < 2:
            continue
        canvas.setStrokeColor(_CRITICAL if is_closed else _TEXT)
        canvas.setLineWidth(
            2.8 if is_closed else (1.7 if aeroway == "runway" else 0.7)
        )
        path = canvas.beginPath()
        first_x, first_y = projected(points[0])
        path.moveTo(first_x, first_y)
        for point in points[1:]:
            point_x, point_y = projected(point)
            path.lineTo(point_x, point_y)
        canvas.drawPath(path, stroke=1, fill=0)
        if aeroway == "runway" or is_closed:
            midpoint_x, midpoint_y = projected(points[len(points) // 2])
            label = str(properties.get("ref") or "")
            if label:
                canvas.setFillColor(_CRITICAL if is_closed else _MUTED)
                canvas.setFont(theme.SANS_BOLD, theme.readable(4.1))
                canvas.drawCentredString(midpoint_x, midpoint_y + 1.5 * mm, label[:12])
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS, theme.readable(4.0))
    canvas.drawString(x + 1.5 * mm, y + 1.2 * mm, "Validated OSM surface schematic")


def _draw_surface_map(
    canvas,
    overlay: dict[str, Any] | None,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#071725"))
    canvas.rect(x, y, width, height, fill=1, stroke=0)
    image_path = ((overlay or {}).get("report_map") or {}).get("image_path")
    if image_path and Path(str(image_path)).is_file():
        try:
            canvas.drawImage(
                ImageReader(str(image_path)),
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        except (OSError, ValueError):
            if overlay:
                _draw_surface_schematic(canvas, overlay, x, y, width, height)
    elif overlay:
        _draw_surface_schematic(canvas, overlay, x, y, width, height)
    else:
        canvas.setFillColor(_MUTED)
        canvas.setFont(theme.SANS, theme.readable(5.1))
        canvas.drawCentredString(
            x + width / 2,
            y + height / 2,
            "Surface overlay unavailable",
        )
    if overlay:
        report_map = overlay.get("report_map") or {}
        label = str(
            report_map.get("label")
            or "Validated OSM surface schematic"
        )
        conflict = next(
            (
                item.get("sourceConflict") or {}
                for item in overlay.get("reviewRequired") or []
                if item.get("sourceConflict")
            ),
            {},
        )
        if conflict:
            publication = surface_conflict_publication_label(conflict)
            label = f"{publication} TIMING CONFLICT - REVIEW"
        canvas.setFillColor(colors.Color(0, 0, 0, alpha=0.72))
        canvas.rect(x, y, width, 5 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(theme.SANS, theme.readable(4.0))
        canvas.drawString(x + 1.5 * mm, y + 1.7 * mm, label[:58])
    canvas.restoreState()


def _draw_airport_panel(
    canvas,
    panel: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    overlay: dict[str, Any] | None = None,
    personal_lines: list[str] | None = None,
) -> None:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)
    title_height = 7.5 * mm
    canvas.setFillColor(_airport_accent(panel))
    canvas.roundRect(
        x,
        y + height - title_height,
        width,
        title_height,
        3.5,
        fill=1,
        stroke=0,
    )
    canvas.rect(
        x,
        y + height - title_height,
        width,
        title_height / 2,
        fill=1,
        stroke=0,
    )
    canvas.setFillColor(colors.white)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.4))
    canvas.drawString(x + 3 * mm, y + height - 4.9 * mm, title)

    map_height = min(49 * mm, max(34 * mm, height * 0.47))
    map_y = y + height - title_height - map_height
    _draw_surface_map(
        canvas,
        overlay,
        x + 1.5 * mm,
        map_y + 1 * mm,
        width - 3 * mm,
        map_height - 2 * mm,
    )
    body_x = x + 3 * mm
    body_y = y + 2.3 * mm
    body_width = width - 6 * mm
    body_height = max(1.0, map_y - body_y - 1.2 * mm)
    lines = _fit_lines(
        _airport_lines(panel, overlay, personal_lines),
        _STYLES["dark_small"],
        body_width,
        body_height,
    )
    paragraph = _paragraph(lines, _STYLES["dark_small"])
    _, required = paragraph.wrap(body_width, body_height)
    paragraph.drawOn(
        canvas,
        body_x,
        body_y + max(0.0, body_height - required),
    )


def _finding_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    return (
        -_SEVERITY_RANK.get(str(item.get("severity") or "information"), 0),
        -int((item.get("data") or {}).get("priority_score") or 0),
        str(item.get("title") or ""),
    )


def _finding_lines(
    findings: list[dict[str, Any]],
    *,
    finding_limit: int,
    detail_limit: int,
) -> list[str]:
    lines: list[str] = []
    for item in sorted(findings, key=_finding_sort_key)[:finding_limit]:
        title = str(item.get("title") or "Finding")
        summary = str(item.get("summary") or "")
        lines.append(f"{title}: {summary}".strip())
        lines.extend(
            str(detail)
            for detail in (item.get("details") or [])[:detail_limit]
            if str(detail).strip()
        )
    return lines


def _pilot_weather_lines(
    findings: list[dict[str, Any]],
    *,
    finding_limit: int,
    non_weather_detail_limit: int = 2,
) -> list[str]:
    """Render only the operational weather fields needed in Level 1.

    Full observations, forecasts, record identifiers and source payloads stay
    in the analysis audit.  The pertinent report keeps the flight phase,
    station, checked UTC window, mechanism, timing and resulting flight effect.
    """

    lines: list[str] = []
    incomplete_windows: list[str] = []
    incomplete_advisories: list[str] = []
    rendered_findings = 0

    for item in sorted(findings, key=_finding_sort_key):
        data = item.get("data") or {}
        engine = str(item.get("engine") or "")
        if engine == "weather" and data.get("window_status") == "review_required":
            phase = str(data.get("phase") or "Enroute").strip()
            location = str(data.get("location") or "station").strip()
            utc_window = str(
                data.get("utc_window") or "UTC window not resolved"
            ).strip()
            incomplete_windows.append(f"{phase} | {location} | {utc_window}")
            continue

        if (
            engine in {"sigmet", "vaa", "tropical_cyclone"}
            and data.get("status") == "review_required"
        ):
            incomplete_advisories.append(
                (
                    "SIGMET"
                    if engine == "sigmet"
                    else "VAA" if engine == "vaa" else "tropical-cyclone"
                )
            )
            continue

        if rendered_findings >= finding_limit:
            continue
        rendered_findings += 1

        if engine != "weather":
            lines.append(
                f"{item.get('title') or 'Weather advisory'}: "
                f"{item.get('summary') or ''}".strip()
            )
            lines.extend(
                str(detail)
                for detail in (item.get("details") or [])[:non_weather_detail_limit]
                if str(detail).strip()
            )
            continue

        phase = str(data.get("phase") or "Enroute").strip()
        location = str(data.get("location") or "station").strip()
        utc_window = str(data.get("utc_window") or "UTC window not resolved").strip()
        mechanism = str(data.get("mechanism") or "Not safely classified").strip()
        if mechanism.lower() == "none safely classified":
            mechanism = "Not safely classified from the available forecast"
        timing = str(data.get("timing") or "Timing not safely resolved.").strip()
        flight_effect = str(
            data.get("flight_effect")
            or "Review the latest operational weather for this flight phase."
        ).strip()
        lines.extend(
            [
                (
                    f"{item.get('title') or 'Weather'}: "
                    f"{phase} | {location} | {utc_window}"
                ),
                (
                    f"Mechanism: {mechanism.rstrip('.')}; "
                    f"timing: {timing[0].lower() + timing[1:] if timing else timing}"
                ),
                f"Flight effect: {flight_effect}",
            ]
        )

    if incomplete_windows:
        lines.extend(
            [
                (
                    "Forecast coverage incomplete — review required: "
                    + "; ".join(dict.fromkeys(incomplete_windows))
                    + "."
                ),
                (
                    "Flight effect: confirm the latest operational forecast "
                    "for these checked windows."
                ),
            ]
        )
    if incomplete_advisories:
        labels = " and ".join(
            label
            for label in ("VAA", "tropical-cyclone")
            if label in incomplete_advisories
        )
        lines.append(
            "Official advisory coverage incomplete — "
            f"{labels} review required."
        )
    return lines


def _group_findings(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[str(finding.get("engine") or "other")].append(finding)
    return grouped


def _top_actions(findings: list[dict[str, Any]], limit: int = 5) -> list[dict[str, str]]:
    incomplete_weather = [
        item
        for item in findings
        if item.get("engine") == "weather"
        and (item.get("data") or {}).get("window_status") == "review_required"
        and item.get("severity") in {"critical", "warning"}
    ]
    operational = [
        item
        for item in findings
        if item.get("severity") in {"critical", "warning"}
        and item.get("engine") not in {"qa", "page1", "timeline"}
        and item not in incomplete_weather
    ]
    actions: list[dict[str, str]] = []
    if incomplete_weather:
        windows = [
            " / ".join(
                part
                for part in (
                    str((item.get("data") or {}).get("phase") or "").strip(),
                    str((item.get("data") or {}).get("location") or "").strip(),
                    str((item.get("data") or {}).get("utc_window") or "").strip(),
                )
                if part
            )
            for item in incomplete_weather
        ]
        actions.append(
            {
                "title": "Weather coverage incomplete",
                "summary": (
                    "; ".join(dict.fromkeys(windows))
                    + ". Confirm the latest operational forecast for these windows."
                ),
                "severity": "warning",
            }
        )

    selected = sorted(
        operational,
        key=_finding_sort_key,
    )[: max(0, limit - len(actions))]
    for item in selected:
        data = item.get("data") or {}
        if item.get("engine") == "weather":
            summary = " | ".join(
                part
                for part in (
                    str(data.get("phase") or "").strip(),
                    str(data.get("location") or "").strip(),
                    str(data.get("utc_window") or "").strip(),
                    str(data.get("mechanism") or "").strip(),
                    str(data.get("timing") or "").strip(),
                    str(data.get("flight_effect") or "").strip(),
                )
                if part
            )
        elif item.get("engine") == "notam":
            summary = pilot_notam_condition(item.get("summary"))
        else:
            summary = str(item.get("summary") or "")
        actions.append(
            {
                "title": normalize_notam_references(
                    item.get("title") or "Operational item"
                ),
                "summary": summary,
                "severity": str(item.get("severity") or "warning"),
            }
        )
    return sorted(
        actions,
        key=lambda action: (
            -_SEVERITY_RANK.get(action["severity"], 0),
            action["title"],
        ),
    )[:limit]


def _severity_accent(items: list[dict[str, Any]], normal: colors.Color) -> colors.Color:
    return _CRITICAL if any(item.get("severity") == "critical" for item in items) else normal


def _draw_action_strip(
    canvas,
    findings: list[dict[str, Any]],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    actions = _top_actions(findings, limit=4)
    if not actions:
        actions = [{
            "title": "No principal exception selected",
            "summary": "Detailed airport, route and weather information remains on Pages 2 and 3.",
            "severity": "information",
        }]
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 4, fill=1, stroke=1)
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.0))
    canvas.drawString(x + 3 * mm, y + height - 5 * mm, "DECISION GATES")

    body_y = y + 2.5 * mm
    body_h = height - 9 * mm
    cell = width / len(actions)
    title_style = ParagraphStyle(
        "Decision gate title",
        fontName=theme.SANS_BOLD,
        fontSize=6.0,
        leading=7.0,
        textColor=_WEATHER,
        spaceAfter=0,
        spaceBefore=0,
    )
    summary_style = ParagraphStyle(
        "Decision gate summary",
        fontName=theme.SANS,
        fontSize=7.0,
        leading=8.4,
        textColor=_TEXT,
        spaceAfter=0,
        spaceBefore=0,
    )
    for index, action in enumerate(actions):
        cx = x + index * cell
        accent = _CRITICAL if action["severity"] == "critical" else _WEATHER
        if index:
            canvas.setStrokeColor(_LINE)
            canvas.line(cx, body_y, cx, y + height - 8 * mm)
        body_width = cell - 7 * mm
        action_title_style = ParagraphStyle(
            f"Decision gate title {index}",
            parent=title_style,
            textColor=accent,
        )
        title = _paragraph([action["title"]], action_title_style)
        _, title_height = title.wrap(body_width, body_h)
        title.drawOn(
            canvas,
            cx + 3.5 * mm,
            body_y + max(0.0, body_h - title_height),
        )
        summary_height = max(1.0, body_h - title_height - 1.2 * mm)
        fitted_summary_style = _largest_fitting_style(
            [action["summary"]],
            summary_style,
            body_width,
            summary_height,
        )
        summary = _paragraph([action["summary"]], fitted_summary_style)
        _, required = summary.wrap(body_width, summary_height)
        summary.drawOn(canvas, cx + 3.5 * mm, body_y + max(0.0, summary_height - required))


def _draw_header(
    canvas,
    briefing: dict[str, Any],
    width: float,
    height: float,
    *,
    section_title: str = "LEVEL 1 - PERTINENT BRIEF",
    page_number: int = 1,
) -> float:
    flight = briefing.get("_flight") or {}
    metrics = briefing.get("metrics") or {}
    atot = metrics.get("atot")
    atot_note = None
    if atot:
        # The full ATOT + CFP ACTM explanation remains in the timing panel.
        # Keep the repeated page header concise enough to clear its section
        # pill, matching the Level 2 header contract.
        atot_note = f"ATOT {atot} | CALC UTC"
    top = theme.draw_header(
        canvas,
        flight,
        width=width,
        height=height,
        pill_text=section_title,
        extra_utc_note=atot_note,
    )
    theme.draw_footer(
        canvas,
        flight,
        width=width,
        page_number=page_number,
        page_count=3,
    )
    theme.draw_source_chips(
        canvas,
        _page_source_chips(flight, page_number),
        width=width,
    )
    return top


def _page_source_chips(flight: dict[str, Any], page_number: int) -> list[str]:
    if page_number == 1:
        chips = ["CFP P1", "CFP PERF"]
        for value in (flight.get("departure"), flight.get("destination")):
            if value:
                chips.append(str(value))
        if flight.get("bobcat"):
            chips.append("BOBCAT")
        return chips
    if page_number == 2:
        chips = ["CFP EDTO"]
        if flight.get("deferred_items"):
            chips.append("DEFERRED DECLARATIONS")
        chips.append("CFP WX")
        return chips
    return []


def _draw_cover_airport_panel(
    canvas,
    *,
    panel: dict[str, Any],
    findings: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
    personal_lines: list[str],
    schedule: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    accent = _airport_accent(panel)
    role = "DEPARTURE" if panel.get("role") == "departure" else "DESTINATION"
    canvas.setFillColor(_PANEL_2)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 4, fill=1, stroke=1)
    title_h = 7 * mm
    canvas.setFillColor(accent)
    canvas.roundRect(
        x,
        y + height - title_h,
        width,
        title_h,
        4,
        fill=1,
        stroke=0,
    )
    canvas.rect(x, y + height - title_h, width, title_h / 2, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont(theme.SANS_BOLD, 7.0)
    canvas.drawString(
        x + 3 * mm,
        y + height - 4.6 * mm,
        f"{role} - {panel['icao']}",
    )

    canvas.setFillColor(_TEXT)
    canvas.setFont(theme.SANS_BOLD, 10)
    canvas.drawString(
        x + 3 * mm,
        y + height - 14.2 * mm,
        f"RWY {panel['runway']}",
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS_BOLD, theme.readable(5.6))
    canvas.drawString(x + 3 * mm, y + height - 20 * mm, "SCHEDULE")
    canvas.setFillColor(_TEXT)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.6))
    canvas.drawRightString(x + width - 3 * mm, y + height - 20 * mm, schedule)

    # The active three-page renderer uses this cover panel, so the governed
    # surface artifact must be drawn here rather than only in the retired
    # `_draw_airport_panel`. Missing or incomplete overlays remain visibly
    # unavailable through `_draw_surface_map`; they are never replaced with an
    # invented airport diagram.
    map_h = min(34 * mm, max(27 * mm, height * 0.32))
    map_y = y + height - 23 * mm - map_h
    _draw_surface_map(
        canvas,
        overlay,
        x + 2 * mm,
        map_y,
        width - 4 * mm,
        map_h,
    )

    overlay_lines = [
        "Surface overlay: no validated surface overlay attached; chart review required."
    ]
    if overlay:
        overlay_lines = _surface_overlay_lines(overlay, detail_limit=2)

    location = str(panel.get("icao") or "").upper()
    role = str(panel.get("role") or "")
    weather_findings = sorted(
        [
            item
            for item in findings
            if item.get("engine") == "weather"
            and (
                str((item.get("data") or {}).get("location") or "").upper()
                == location
            )
        ],
        key=_finding_sort_key,
    )
    if weather_findings:
        weather = weather_findings[0]
        weather_data = weather.get("data") or {}
        weather_window = str(weather_data.get("utc_window") or "the operating window")
        weather_status = str(weather_data.get("window_status") or "")
        if weather_status == "no_significant_overlap":
            weather_line = (
                f"WEATHER: No significant forecast overlap during {weather_window}."
            )
        elif weather_status == "review_required":
            weather_line = f"WEATHER: Coverage incomplete for {weather_window}."
        else:
            weather_line = "WEATHER: " + "; ".join(
                part.rstrip(".")
                for part in (
                    str(weather_data.get("mechanism") or "").strip(),
                    str(weather_data.get("flight_effect") or "").strip(),
                )
                if part
            )
            if weather_line == "WEATHER: ":
                weather_line += str(weather.get("summary") or "Review required.")
    else:
        fallback_weather = str(
            (panel.get("weather") or {}).get("primary") or ""
        ).strip()
        weather_line = (
            "WEATHER: Review the operating-window forecast."
            if fallback_weather.endswith("…")
            else f"WEATHER: {fallback_weather}"
        )

    notam_lines = []
    for item in sorted(
        [
            finding
            for finding in findings
            if finding.get("engine") == "notam"
            and str((finding.get("data") or {}).get("role") or "") == role
        ],
        key=_finding_sort_key,
    )[:2]:
        data = item.get("data") or {}
        reference = str(data.get("notam_id") or item.get("title") or "NOTAM")
        notam_lines.append(
            f"NOTAM {normalize_notam_references(reference)}: "
            f"{pilot_notam_condition(item.get('summary'))}"
        )

    lines = [
        *(overlay_lines if overlay else []),
        *personal_lines,
        weather_line,
        *notam_lines,
        *([] if overlay else overlay_lines),
    ]
    body_x = x + 3 * mm
    body_y = y + 3 * mm
    body_w = width - 6 * mm
    body_h = max(1.0, map_y - body_y - 2 * mm)
    fitted = _fit_lines(lines, _STYLES["dark_small"], body_w, body_h)
    paragraph = _paragraph(fitted, _STYLES["dark_small"])
    _, required = paragraph.wrap(body_w, body_h)
    paragraph.drawOn(
        canvas,
        body_x,
        body_y + max(0.0, body_h - required),
    )


def _draw_cover_route_panel(
    canvas,
    *,
    briefing: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 4, fill=1, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.6))
    canvas.drawString(
        x + 2.5 * mm,
        y + height - 5.5 * mm,
        f"{briefing['flight_number']} CFP ROUTE - DECISION GATES",
    )
    draw_route_map_pdf(
        canvas,
        briefing["route_map"],
        x + 1.5 * mm,
        y + 1.5 * mm,
        width - 3 * mm,
        height - 9 * mm,
    )


def _draw_cover_metric_cards(
    canvas,
    *,
    items: list[tuple[str, str, str, colors.Color]],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    gap = 2 * mm
    card_w = (width - gap * (len(items) - 1)) / max(1, len(items))
    for index, (label, value, note, accent) in enumerate(items):
        card_x = x + index * (card_w + gap)
        canvas.setFillColor(_PANEL_2)
        canvas.setStrokeColor(_LINE)
        canvas.roundRect(card_x, y, card_w, height, 4, fill=1, stroke=1)
        canvas.setFillColor(accent)
        canvas.rect(card_x, y + height - 1.2 * mm, card_w, 1.2 * mm, fill=1, stroke=0)
        canvas.setFillColor(_MUTED)
        canvas.setFont(theme.SANS_BOLD, theme.readable(5.5))
        canvas.drawString(card_x + 2.5 * mm, y + height - 5.5 * mm, label)
        canvas.setFillColor(_TEXT)
        canvas.setFont(theme.SANS_BOLD, REPORT_TYPOGRAPHY["metric"])
        canvas.drawString(card_x + 2.5 * mm, y + height - 12.3 * mm, value)
        canvas.setFillColor(_MUTED)
        note_style = ParagraphStyle(
            "Cover metric note",
            fontName=theme.SANS,
            fontSize=5.1,
            leading=5.8,
            textColor=_MUTED,
            spaceAfter=0,
            spaceBefore=0,
        )
        note_paragraph = _paragraph([note], note_style)
        note_width = card_w - 5 * mm
        _, note_height = note_paragraph.wrap(note_width, 6.4 * mm)
        note_paragraph.drawOn(
            canvas,
            card_x + 2.5 * mm,
            y + 1.6 * mm + max(0.0, 6.4 * mm - note_height),
        )


def _draw_footer(
    canvas,
    *,
    briefing: dict[str, Any],
    width: float,
    page_number: int,
) -> None:
    # The shared v1.3 footer is drawn by _draw_header for every page.
    return None


def _draw_cover_footer(
    canvas,
    *,
    briefing: dict[str, Any],
    width: float,
) -> None:
    _draw_footer(
        canvas,
        briefing=briefing,
        width=width,
        page_number=1,
    )


def _draw_page_title(
    canvas,
    briefing: dict[str, Any],
    width: float,
    height: float,
    title: str,
    page_number: int,
) -> float:
    canvas.setFillColor(_DARK)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    return _draw_header(
        canvas,
        briefing,
        width,
        height,
        section_title=title,
        page_number=page_number,
    )


def _draw_cover(
    canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    width: float,
    height: float,
) -> None:
    canvas.bookmarkPage("visual_briefing")
    canvas.setFillColor(_DARK)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    top = _draw_header(canvas, briefing, width, height)
    margin = 7 * mm
    gap = 3 * mm
    section_label_h = 5 * mm
    main_h = 105 * mm
    main_top = top - section_label_h
    main_y = main_top - main_h
    left_w = 52 * mm
    right_w = 52 * mm
    centre_x = margin + left_w + gap
    centre_w = width - 2 * margin - left_w - right_w - 2 * gap

    canvas.setFillColor(_MUTED)
    canvas.setFont(theme.SANS_BOLD, theme.readable(6.1))
    canvas.drawCentredString(
        width / 2,
        top - 3.5 * mm,
        "APPLICABLE NOTAMS WITHIN STD / STA ±2 HOURS",
    )

    departure_overlay = _surface_overlay(
        flight,
        role="departure",
        icao=str(briefing["departure"]["icao"]),
    )
    destination_overlay = _surface_overlay(
        flight,
        role="destination",
        icao=str(briefing["destination"]["icao"]),
    )
    _draw_cover_airport_panel(
        canvas,
        panel=briefing["departure"],
        findings=findings,
        overlay=departure_overlay,
        personal_lines=_note_lines(flight, {"departure"}),
        schedule=briefing["metrics"]["etd"],
        x=margin,
        y=main_y,
        width=left_w,
        height=main_h,
    )
    _draw_cover_route_panel(
        canvas,
        briefing=briefing,
        x=centre_x,
        y=main_y,
        width=centre_w,
        height=main_h,
    )
    _draw_cover_airport_panel(
        canvas,
        panel=briefing["destination"],
        findings=findings,
        overlay=destination_overlay,
        personal_lines=_note_lines(flight, {"destination"}),
        schedule=briefing["metrics"]["eta"],
        x=centre_x + centre_w + gap,
        y=main_y,
        width=right_w,
        height=main_h,
    )

    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    fuel = flight.get("fuel") or {}
    planned_takeoff = masses.get("planned_takeoff_weight_kg")
    performance_limit = performance.get("obstacle_rtow_kg")
    if performance_limit is None:
        performance_limit = performance.get("structural_rtow_kg")
    if performance_limit is not None and planned_takeoff is not None:
        performance_margin = int(performance_limit) - int(planned_takeoff)
        performance_value = f"{performance_margin / 1000:+.1f} T"
        performance_note = "RTOW margin to planned takeoff weight"
    else:
        performance_value = "REVIEW"
        performance_note = "Performance margin unavailable"

    excess_fuel = fuel.get("excess_fuel_kg")
    fuel_value = (
        f"{int(excess_fuel):,} kg"
        if excess_fuel is not None
        else "REVIEW"
    )
    sectors = edto_sectors(flight.get("edto") or {})
    sector_airports = [
        str(airport)
        for sector in sectors
        for etp in (sector.get("etps") or [])
        for airport in (etp.get("airports") or [])
        if airport
    ]
    sector_airports.extend(
        str(item.get("airport"))
        for item in ((flight.get("edto") or {}).get("airports") or [])
        if isinstance(item, dict) and item.get("airport")
    )
    edto_assessment_status = str(
        ((briefing.get("edto") or {}).get("assessment") or {}).get("status")
        or "review_required"
    )
    if edto_assessment_status == "verified_not_applicable":
        edto_metric_value = "ASSESSED"
        edto_metric_note = "Governed status compiled once on page 2"
    elif edto_assessment_status == "affected":
        edto_metric_value = f"{len(sectors)} sector{'s' if len(sectors) != 1 else ''}"
        edto_metric_note = (
            " / ".join(dict.fromkeys(sector_airports))
            or "EDTO applies; airport detail requires review"
        )
    else:
        edto_metric_value = "REVIEW"
        edto_metric_note = "Applicability is not explicitly verified"
    oceanic = next(
        (
            row
            for row in build_route_gate_rows(flight)
            if row.get("kind") == "oceanic"
        ),
        None,
    )
    events = detect_terrain_events(flight.get("route_waypoints") or [])
    maximum = max(
        (
            event.get("maximum") or {}
            for event in events
        ),
        key=lambda point: int(point.get("msa_hundreds_ft") or -1),
        default={},
    )
    maximum_value = maximum.get("msa_hundreds_ft")
    terrain_value = (
        f"{int(maximum_value):03d}"
        f"{'*' if maximum.get('msa_asterisk') else ''} "
        f"{maximum.get('name') or ''}".strip()
        if maximum_value is not None
        else "NONE IDENTIFIED"
    )
    metric_h = 22 * mm
    metric_y = main_y - gap - metric_h
    _draw_cover_metric_cards(
        canvas,
        items=[
            (
                "PERFORMANCE",
                performance_value,
                performance_note,
                _CRITICAL if performance_value == "REVIEW" else _EDTO,
            ),
            (
                "EXCESS FUEL",
                fuel_value,
                "CFP excess above required fuel",
                _WEATHER,
            ),
            (
                "EDTO",
                edto_metric_value,
                edto_metric_note,
                _EDTO,
            ),
            (
                "OCEANIC",
                (oceanic or {}).get("gate", "NO TRACK"),
                (oceanic or {}).get("basis", "No named track identified"),
                _COMMUNICATIONS,
            ),
            (
                "HIGH TERRAIN",
                terrain_value,
                f"{len(events)} exposure window{'s' if len(events) != 1 else ''}",
                _TERRAIN,
            ),
        ],
        x=margin,
        y=metric_y,
        width=width - 2 * margin,
        height=metric_h,
    )
    decision_h = 27 * mm
    decision_y = metric_y - gap - decision_h
    _draw_action_strip(
        canvas,
        findings,
        margin,
        decision_y,
        width - 2 * margin,
        decision_h,
    )
    _draw_cover_footer(canvas, briefing=briefing, width=width)


def _note_lines(flight: dict[str, Any], placements: set[str]) -> list[str]:
    lines = [
        f"Personal note: {' '.join(str(note.get('note_text') or '').split())}"
        for note in (flight.get("personal_notes") or [])
        if note.get("placement") in placements and note.get("include_level1")
    ]
    if lines:
        lines.append("Pilot-entered note.")
    return lines


def _draw_operational_detail(
    canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    width: float,
    height: float,
) -> None:
    for destination in ("operational_detail", "departure_detail", "destination_detail"):
        canvas.bookmarkPage(destination)
    top = _draw_page_title(
        canvas,
        briefing,
        width,
        height,
        f"{briefing['flight_number']} - OPERATIONAL TIMING",
        2,
    )
    grouped = _group_findings(findings)
    margin = 6 * mm
    gap = 3 * mm
    bottom = 13 * mm
    route_points = list((briefing.get("route_map") or {}).get("points") or [])
    sectors = edto_sectors(flight.get("edto") or {})
    final_actm = max(
        (
            int(point["actm_minutes"])
            for point in route_points
            if point.get("actm_minutes") is not None
        ),
        default=1,
    )

    timeline_h = 25 * mm
    timeline_y = top - timeline_h - gap
    _draw_phase_timeline(
        canvas,
        sectors=sectors,
        communications=grouped.get("communications", []),
        clock_basis=(
            f"{briefing['metrics']['clock_basis']} · "
            f"ATOT {briefing['metrics']['atot']}"
            if briefing["metrics"].get("atot")
            else "CFP ACTM only · ATOT/ATA required for UTC clocks"
        ),
        final_actm=final_actm,
        x=margin,
        y=timeline_y,
        width=width - 2 * margin,
        height=timeline_h,
        slot_line=_slot_allocation_line(flight),
    )
    content_top = timeline_y - gap
    deferred_rows = deferred_item_report_rows(flight, findings, limit=1)
    cards_h = (34 if deferred_rows else 26) * mm
    cards_y = bottom
    content_bottom = cards_y + cards_h + gap
    left_width = 167 * mm
    right_x = margin + left_width + gap
    right_width = width - margin - right_x
    edto_view = briefing.get("edto") or {}
    edto_assessment_status = str(
        (edto_view.get("assessment") or {}).get("status") or "review_required"
    )
    if edto_assessment_status == "verified_not_applicable":
        edto_sector_empty_text = (
            "Complete company CFP checked; the single governed status is stated "
            "in DATA COVERAGE."
        )
        edto_airport_empty_text = (
            "Airport details are shown only when an EDTO sector is present."
        )
    elif edto_assessment_status == "affected":
        edto_sector_empty_text = (
            "EDTO applies, but no sector timeline was published - review required."
        )
        edto_airport_empty_text = (
            "EDTO applies, but no airport checked-period row was published - review required."
        )
    else:
        edto_sector_empty_text = (
            "EDTO applicability is not explicitly verified - review required."
        )
        edto_airport_empty_text = edto_sector_empty_text

    chart_height = 52 * mm
    chart_y = content_top - chart_height
    if sectors:
        chart_gap = 2.5 * mm
        chart_width = (
            left_width - chart_gap * (min(2, len(sectors)) - 1)
        ) / min(2, len(sectors))
        for index, sector in enumerate(sectors[:2], start=1):
            start = int(sector.get("entry_actm_minutes") or 0)
            end = int(sector.get("exit_actm_minutes") or start)
            markers = _sector_etp_markers(route_points, sector, index)
            points = _route_window_points(
                route_points,
                start,
                end,
                markers=markers,
            )
            _draw_route_evidence_chart(
                canvas,
                points,
                margin + (index - 1) * (chart_width + chart_gap),
                chart_y,
                chart_width,
                chart_height,
                title=(
                    f"EDTO {index} | ENTRY {format_actm(start)} | "
                    f"EXIT {format_actm(end)}"
                ),
                mode="edto",
            )
    else:
        _draw_panel(
            canvas,
            margin,
            chart_y,
            left_width,
            chart_height,
            "EDTO ROUTE EVIDENCE",
            [edto_sector_empty_text],
            _EDTO,
            dark=True,
            style=_STYLES["dark"],
        )

    weather_by_location = {
        str((item.get("data") or {}).get("location") or "").upper(): item
        for item in grouped.get("weather", [])
    }
    airport_rows: list[list[str]] = []
    for item in (edto_view.get("airports") or [])[:4]:
        weather = weather_by_location.get(str(item.get("airport") or "").upper())
        weather_data = (weather or {}).get("data") or {}
        status = str(weather_data.get("window_status") or "")
        if status == "pertinent":
            weather_result = (
                f"{weather_data.get('mechanism') or 'Pertinent weather'}; "
                f"{weather_data.get('flight_effect') or 'pilot review required'}"
            )
        elif status == "no_significant_overlap":
            weather_result = "No significant CFP forecast group overlaps the checked period."
        else:
            weather_result = "Weather coverage incomplete - review required."
        airport_rows.append(
            [
                str(item.get("airport") or "Airport"),
                str(item.get("period") or "Period unresolved"),
                f"RWY {item.get('runway') or '--'} / {item.get('approach') or 'approach review'}",
                weather_result,
            ]
        )
    table_height = max(22 * mm, chart_y - content_bottom - gap)
    _draw_compact_table(
        canvas,
        x=margin,
        y=content_bottom,
        width=left_width,
        height=table_height,
        columns=[
            ("AIRPORT", 0.12),
            ("CHECKED PERIOD", 0.23),
            ("RUNWAY / APPROACH", 0.24),
            ("WEATHER RESULT", 0.41),
        ],
        rows=airport_rows,
        accent=_EDTO,
        empty_text=edto_airport_empty_text,
    )

    route_gate_rows = [
        [
            row["time"],
            f"{row['gate']} / {row['basis']}",
            row["result"],
        ]
        for row in select_route_gate_rows(
            build_route_gate_rows(flight),
            limit=7,
        )
    ]
    _draw_compact_table(
        canvas,
        x=right_x,
        y=content_bottom,
        width=right_width,
        height=content_top - content_bottom,
        columns=[
            ("ACTM / UTC" if actual_timing_anchor(flight) else "ACTM", 0.29),
            ("ROUTE GATE", 0.24),
            ("PERTINENT RESULT", 0.47),
        ],
        rows=route_gate_rows,
        accent=_COMMUNICATIONS,
        empty_text="Route-gate timing unavailable.",
    )

    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    takeoff_lines = [
        f"Planned takeoff weight: {briefing['masses']['ptow']}.",
        (
            f"Structural RTOW: {int(performance['structural_rtow_kg']):,} kg."
            if performance.get("structural_rtow_kg") is not None
            else "Structural RTOW unavailable - review required."
        ),
        (
            f"Obstacle RTOW: {int(performance['obstacle_rtow_kg']):,} kg."
            if performance.get("obstacle_rtow_kg") is not None
            else "Obstacle RTOW unavailable - review required."
        ),
    ]
    if (
        masses.get("planned_takeoff_weight_kg") is not None
        and performance.get("structural_rtow_kg") is not None
    ):
        margin_kg = int(performance["structural_rtow_kg"]) - int(
            masses["planned_takeoff_weight_kg"]
        )
        takeoff_lines.append(f"Structural margin: {margin_kg:+,} kg.")
    if deferred_rows:
        card_gap = 2.5 * mm
        takeoff_width = (left_width - card_gap) * 0.45
        deferred_width = left_width - card_gap - takeoff_width
        _draw_panel(
            canvas,
            margin,
            cards_y,
            takeoff_width,
            cards_h,
            "TAKEOFF WEIGHT",
            takeoff_lines,
            _DEPARTURE,
            dark=True,
            style=_STYLES["dark_small"],
        )
        deferred = deferred_rows[0]
        deferred_lines = [
            f"{deferred['label']}: {deferred['description']}",
            f"CFP restriction: {deferred['restriction']}",
            deferred["source_status"],
        ]
        remaining = len(flight.get("deferred_items") or []) - 1
        if remaining > 0:
            deferred_lines.append(f"+{remaining} further deferred item(s) in Level 2.")
        _draw_panel(
            canvas,
            margin + takeoff_width + card_gap,
            cards_y,
            deferred_width,
            cards_h,
            "DEFERRED DECLARATIONS",
            deferred_lines,
            _CRITICAL,
            dark=True,
            style=_STYLES["dark_small"],
        )
    else:
        _draw_panel(
            canvas,
            margin,
            cards_y,
            left_width,
            cards_h,
            "TAKEOFF WEIGHT",
            takeoff_lines,
            _DEPARTURE,
            dark=True,
            style=_STYLES["dark_small"],
        )

    weather_items = grouped.get("weather", [])
    incomplete_weather = sum(
        (item.get("data") or {}).get("window_status") == "review_required"
        for item in weather_items
    )
    advisory_items = (
        grouped.get("sigmet", [])
        + grouped.get("vaa", [])
        + grouped.get("tropical_cyclone", [])
    )
    # Boss rule (01 Aug 2026): domains that were EVALUATED AND CLEAN compile
    # into one NIL line — "NIL EDTO / VAA / SIGMET… provided it is really NIL".
    # Could-not-evaluate NEVER compiles: absent coverage stays a loud line.
    def _advisory_state(review_key: str, label: str) -> tuple[str, str]:
        review = flight.get(review_key)
        if not isinstance(review, dict) or not review:
            return label, "unavailable"
        status = str(review.get("status") or "review_required")
        if status == "affected":
            return label, "affected"
        # An empty findings group does not prove a clean assessment: the
        # engine deliberately emits no finding for both verified no-match and
        # several unavailable paths. Only the producer's explicit governed
        # result may join the compiled NIL line.
        if status == "not_applicable":
            return label, "nil"
        return label, "review"

    edto_state = {
        "verified_not_applicable": "nil",
        "affected": "affected",
    }.get(edto_assessment_status, "review")
    advisory_states = [
        ("EDTO", edto_state),
        _advisory_state("sigmet_review", "SIGMET"),
        _advisory_state("vaa_review", "VAA"),
        _advisory_state("tropical_cyclone_review", "TROPICAL CYCLONE"),
    ]
    nil_labels = [label for label, state in advisory_states if state == "nil"]
    review_labels = [label for label, state in advisory_states if state == "review"]
    affected_labels = [label for label, state in advisory_states if state == "affected"]
    unavailable_labels = [
        label for label, state in advisory_states if state == "unavailable"
    ]
    coverage_lines = [
        (
            "Weather: current-source review required for incomplete flight windows."
            if incomplete_weather
            else "Weather: checked flight windows complete."
        ),
    ]
    if nil_labels:
        nil_result = "NIL " + " / ".join(nil_labels)
        if nil_labels == ["EDTO"]:
            nil_result += (
                " - verified not applicable from the complete uploaded CFP"
            )
        elif "EDTO" in nil_labels:
            nil_result += " - each explicitly verified from its governed source"
        coverage_lines.append(nil_result + ".")
    # SIGMET is the hazard product a captain acts on and is stated on its own
    # line rather than folded into "SIGMET and VAA and TROPICAL CYCLONE", which
    # gave three distinct products one shared verdict. VAA and tropical cyclone
    # keep their own grouping; none of the three is ever relabelled as another.
    def _coverage_line(labels: list[str], verdict: str) -> None:
        rest = [label for label in labels if label != "SIGMET"]
        if "SIGMET" in labels:
            coverage_lines.append(f"SIGMET: {verdict}")
        if rest:
            coverage_lines.append(" and ".join(rest) + f": {verdict}")

    _coverage_line(affected_labels, "route impact identified - review Level 2.")
    _coverage_line(review_labels, "review required.")
    _coverage_line(unavailable_labels, "coverage unavailable - review required.")
    _draw_panel(
        canvas,
        right_x,
        cards_y,
        right_width,
        cards_h,
        "DATA COVERAGE",
        coverage_lines,
        _NEUTRAL,
        dark=True,
        style=_STYLES["dark_small"],
    )
    _draw_footer(
        canvas,
        briefing=briefing,
        width=width,
        page_number=2,
    )


def _draw_route_detail(
    canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    width: float,
    height: float,
) -> None:
    for destination in ("route_contingency", "communications_detail", "edto_detail"):
        canvas.bookmarkPage(destination)
    top = _draw_page_title(
        canvas,
        briefing,
        width,
        height,
        f"{briefing['flight_number']} - HIGH TERRAIN EXPOSURE",
        3,
    )
    grouped = _group_findings(findings)
    margin = 6 * mm
    gap = 3 * mm
    bottom = 13 * mm
    depress_findings = grouped.get("depressurisation", [])
    confirmed_profiles = [
        finding
        for finding in depress_findings
        if is_confirmed_profile_finding(finding)
    ]
    unique_confirmed_profiles = list(
        {
            profile_finding_label(finding): finding
            for finding in confirmed_profiles
        }.values()
    )
    controlled_profile_index_loaded = any(
        (finding.get("data") or {}).get("reference_status")
        == "controlled-index-loaded"
        for finding in depress_findings
    )
    events = detect_terrain_events(flight.get("route_waypoints") or [])
    route_points = list((briefing.get("route_map") or {}).get("points") or [])
    maximum = max(
        (
            event.get("maximum") or {}
            for event in events
        ),
        key=lambda point: int(point.get("msa_hundreds_ft") or -1),
        default={},
    )
    metrics_h = 16 * mm
    metrics_y = top - metrics_h - gap
    profile_metrics = [
        (
            f"PROFILE {index}",
            profile_finding_label(finding),
        )
        for index, finding in enumerate(unique_confirmed_profiles[:2], start=1)
    ]
    while len(profile_metrics) < 2:
        profile_metrics.append(
            (
                "PROFILE COVERAGE",
                (
                    "REVIEW REQUIRED"
                    if events
                    else "NO EXPOSURE"
                ),
            )
        )
    _draw_metric_strip(
        canvas,
        [
            ("EXPOSURE WINDOWS", str(len(events))),
            (
                "MAX MSA",
                (
                    f"{int(maximum.get('msa_hundreds_ft')):03d}"
                    f"{'*' if maximum.get('msa_asterisk') else ''} "
                    f"{maximum.get('name') or ''}"
                    if maximum.get("msa_hundreds_ft") is not None
                    else "NOT RESOLVED"
                ),
            ),
            *profile_metrics,
        ],
        margin,
        metrics_y,
        width - 2 * margin,
        metrics_h,
        _PANEL_2,
    )

    boundary_h = 18 * mm
    table_y = bottom + boundary_h + gap
    table_h = 44 * mm
    chart_y = table_y + table_h + gap
    chart_height = max(30 * mm, metrics_y - chart_y - gap)
    if events:
        if len(events) == 1:
            grouped_events = [events]
        else:
            gaps = []
            for index in range(len(events) - 1):
                current_end = (
                    (events[index].get("drop") or events[index].get("last_high") or {})
                    .get("actm_minutes")
                )
                next_start = (
                    (events[index + 1].get("preceding") or events[index + 1].get("first_high") or {})
                    .get("actm_minutes")
                )
                gaps.append(
                    max(
                        0,
                        int(next_start or 0) - int(current_end or 0),
                    )
                )
            split_at = gaps.index(max(gaps)) + 1
            grouped_events = [events[:split_at], events[split_at:]]

        chart_gap = 3 * mm
        chart_width = (
            width - 2 * margin - chart_gap * (len(grouped_events) - 1)
        ) / len(grouped_events)
        for index, event_group in enumerate(grouped_events):
            start_point = (
                event_group[0].get("preceding")
                or event_group[0].get("first_high")
                or {}
            )
            end_point = (
                event_group[-1].get("drop")
                or event_group[-1].get("last_high")
                or {}
            )
            start_actm = int(start_point.get("actm_minutes") or 0)
            end_actm = int(end_point.get("actm_minutes") or start_actm)
            points = _route_window_points(
                route_points,
                start_actm,
                end_actm,
            )
            _draw_route_evidence_chart(
                canvas,
                points,
                margin + index * (chart_width + chart_gap),
                chart_y,
                chart_width,
                chart_height,
                title=(
                    f"{chr(65 + index)}  "
                    f"{str(start_point.get('name') or 'START').lstrip('-')} - "
                    f"{str(end_point.get('name') or 'END').lstrip('-')}"
                ),
                mode="terrain",
            )
    else:
        _draw_panel(
            canvas,
            margin,
            chart_y,
            width - 2 * margin,
            chart_height,
            "VALIDATED CFP MSA POINTS",
            ["No high-terrain exposure window was extracted."],
            _TERRAIN,
            dark=True,
            style=_STYLES["dark"],
        )

    terrain_rows: list[list[str]] = []
    for index, event in enumerate(events, start=1):
        first = event.get("first_high") or {}
        last = event.get("drop") or event.get("last_high") or first
        maximum_point = event.get("maximum") or {}
        start_actm = first.get("actm_minutes")
        end_actm = last.get("actm_minutes")
        utc_values = [
            actm_utc_clock(flight, start_actm),
            actm_utc_clock(flight, end_actm),
        ]
        utc_range = " - ".join(item for item in utc_values if item) or "—"
        max_msa = maximum_point.get("msa_hundreds_ft")
        maximum_label = (
            f"{int(max_msa):03d}{'*' if maximum_point.get('msa_asterisk') else ''} "
            f"{maximum_point.get('name') or ''}"
            if max_msa is not None
            else "Not resolved"
        )
        event_profiles = profile_findings_for_terrain_event(
            event,
            depress_findings,
        )
        profile = profile_coverage_label(event_profiles)
        terrain_rows.append(
            [
                chr(64 + index),
                f"{format_actm(start_actm)}-{format_actm(end_actm)}",
                utc_range,
                (
                    f"{first.get('name') or 'START'} - "
                    f"{last.get('name') or 'END'}"
                ),
                maximum_label,
                profile,
            ]
        )

    _draw_compact_table(
        canvas,
        x=margin,
        y=table_y,
        width=width - 2 * margin,
        height=table_h,
        columns=[
            ("REF", 0.06),
            ("ACTM", 0.12),
            ("UTC" if actual_timing_anchor(flight) else "UTC — NO ANCHOR", 0.20),
            ("CFP ROUTE EXPOSURE", 0.20),
            ("MAX MSA", 0.14),
            ("PROFILE / COVERAGE", 0.28),
        ],
        rows=terrain_rows,
        accent=_TERRAIN,
        empty_text="No high-terrain exposure was extracted from CFP MSA points.",
    )
    _draw_panel(
        canvas,
        margin,
        bottom,
        width - 2 * margin,
        boundary_h,
        "BOUNDARY LOGIC",
        [
            (
                (
                    "Each window begins at the first validated CFP high-MSA trigger "
                    "and ends at the first subsequent point where that trigger "
                    "clears. The geographic strip includes one preceding point for "
                    "route context. Any incomplete profile coverage remains review required."
                    if controlled_profile_index_loaded
                    else (
                        "Each window begins at the first validated CFP high-MSA trigger "
                        "and ends at the first subsequent point where that trigger "
                        "clears. The approved controlled profile index is not mounted, "
                        "so manual chart-index review is required."
                    )
                )
            )
        ],
        _TERRAIN,
        dark=True,
        style=_STYLES["dark_small"],
    )
    _draw_footer(
        canvas,
        briefing=briefing,
        width=width,
        page_number=3,
    )


class _FullPageFlowable(Flowable):
    def __init__(self, drawer: Callable[[Any, float, float], None]):
        super().__init__()
        self._drawer = drawer
        self._available_width = 0.0
        self._available_height = 0.0

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        self._available_width = available_width
        self._available_height = available_height
        return available_width, available_height

    def draw(self) -> None:
        self._drawer(self.canv, self._available_width, self._available_height)


def render_level1_visual(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    path: Path,
    *,
    map_image_path: Path | None = None,
    map_label: str | None = None,
) -> None:
    findings = prepare_pilot_findings(findings, notam_limit=16)
    chart_images = load_matched_chart_images(findings)
    flight["depressurisation_profile_charts"] = (
        build_profile_chart_artifact_contracts(
            chart_images,
            level1_report_page=LEVEL1_DEPRESSURISATION_REPORT_PAGE,
        )
    )
    validate_depressurisation_profile_charts(flight, findings, 1)
    briefing = build_briefing_view(
        flight,
        findings,
        warnings,
        flight.get("timing_view"),
    )
    if map_image_path:
        briefing["route_map"]["snapshot_path"] = str(map_image_path)
        briefing["route_map"]["snapshot_label"] = map_label or "Realistic route map"
    briefing["_flight"] = flight

    document = BaseDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=0,
        rightMargin=0,
        topMargin=0,
        bottomMargin=0,
    )
    frame = Frame(
        0,
        0,
        PAGE_SIZE[0],
        PAGE_SIZE[1],
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="pertinent",
    )
    document.addPageTemplates([PageTemplate(id="pertinent", frames=[frame])])
    story = [
        _FullPageFlowable(lambda canvas, width, height: _draw_cover(canvas, flight, findings, briefing, width, height)),
        PageBreak(),
        _FullPageFlowable(lambda canvas, width, height: _draw_operational_detail(canvas, flight, findings, briefing, width, height)),
        PageBreak(),
        _FullPageFlowable(
            lambda canvas, width, height: draw_depressurisation_analysis(
                canvas,
                flight,
                findings,
                width,
                height,
                issue_date=DEPRESS_LIBRARY_METADATA.get("issue_date"),
            )
        ),
    ]
    document.build(story)


__all__ = ["CATEGORY_COLOURS", "PAGE_SIZE", "render_level1_visual"]
