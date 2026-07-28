from __future__ import annotations

from collections import defaultdict
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
from .constants import edto_sectors, format_actm
from .engines import detect_terrain_events
from .pilot_briefing import prepare_pilot_findings
from .report_facts import (
    actm_utc_label,
    build_route_gate_rows,
    select_route_gate_rows,
)


PAGE_SIZE = landscape(A4)

# Information-category colours. Urgency is communicated separately.
CATEGORY_COLOURS = {
    "departure": "#2F80ED",
    "destination": "#7C4DFF",
    "edto": "#2EAD74",
    "weather": "#D99116",
    "communications": "#0F8B8D",
    "terrain": "#D97706",
    "critical": "#C62828",
    "neutral": "#64748B",
}

_DARK = colors.HexColor("#07111F")
_PANEL = colors.HexColor("#0D1B2C")
_PANEL_2 = colors.HexColor("#13283E")
_LINE = colors.HexColor("#28425F")
_TEXT = colors.HexColor("#E8F2FF")
_MUTED = colors.HexColor("#93A4B8")
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


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "dark": ParagraphStyle(
            "Pertinent dark",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=10.0,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "dark_small": ParagraphStyle(
            "Pertinent dark small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.9,
            leading=8.0,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light": ParagraphStyle(
            "Pertinent light",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.0,
            leading=9.2,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light_small": ParagraphStyle(
            "Pertinent light small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=6.4,
            leading=8.5,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=0,
            spaceBefore=0,
        ),
        "metric": ParagraphStyle(
            "Pertinent metric",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.2,
            leading=6.2,
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
    canvas.setFont("Helvetica-Bold", 5.8 if len(title) > 28 else 6.9)
    canvas.drawString(x + 3 * mm, y + height - 4.9 * mm, title)

    body_x = x + 3 * mm
    body_y = y + 2.6 * mm
    body_width = width - 6 * mm
    body_height = max(1.0, height - title_height - 4.8 * mm)
    fitted = _fit_lines(lines, style, body_width, body_height)
    paragraph = _paragraph(fitted, style)
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
    canvas.setFont("Helvetica-Bold", 4.8)
    canvas.drawCentredString(x + width / 2, centre_y + 1.6 * mm, str(label))
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 6.5)
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
        canvas.setFont("Helvetica-Bold", 5.2)
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
            fitted = _fit_lines(
                [str(value)],
                _STYLES["dark_small"],
                body_width,
                body_height,
            )
            paragraph = _paragraph(fitted, _STYLES["dark_small"])
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
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.drawString(x + 3 * mm, y + height - 5.3 * mm, title[:58])
    note = (
        "Validated CFP MSA points only - no terrain interpolation"
        if mode == "terrain"
        else "CFP route coordinates and EDTO times"
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 4.5)
    canvas.drawRightString(x + width - 3 * mm, y + height - 5.2 * mm, note)

    plot_x = x + 3 * mm
    plot_y = y + 4 * mm
    plot_width = width - 6 * mm
    plot_height = height - 12 * mm
    projection = project_route_map(
        {"points": points},
        plot_width,
        plot_height,
        10.0,
    )
    projected = projection.get("points") or []
    if len(projected) < 2:
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawCentredString(
            x + width / 2,
            y + height / 2,
            "Verified route coordinates unavailable",
        )
        return

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

    canvas.setStrokeColor(_TEXT)
    canvas.setLineWidth(1.4)
    route_sequence = [
        point
        for point in projected
        if point.get("role") != "edto_etp"
    ]
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
        canvas.setFont("Helvetica-Bold", 4.4)
        label_width = pdfmetrics.stringWidth(label[:22], "Helvetica-Bold", 4.4)
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
) -> None:
    canvas.setFillColor(_PANEL_2)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 3.5, fill=1, stroke=1)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica-Bold", 5.2)
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
        canvas.setFont("Helvetica-Bold", 4.6)
        canvas.drawCentredString(
            (sx + ex) / 2,
            line_y + 3.3 * mm,
            f"EDTO {index}",
        )
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 4.2)
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
        canvas.setFont("Helvetica-Bold", 4.1)
        label = str(item.get("title") or "ATC").rsplit(" ", 1)[-1]
        canvas.drawCentredString(
            px,
            line_y + (6.8 if int(actm) % 2 else 9.3) * mm,
            label[:15],
        )


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
        mapped = overlay.get("mapped") or []
        review_required = overlay.get("reviewRequired") or []
        window = overlay.get("window") or {}
        if window.get("startsAt") and window.get("endsAt"):
            lines.append(
                "CFP NOTAM window: "
                f"{str(window['startsAt'])[11:16]}Z-"
                f"{str(window['endsAt'])[11:16]}Z"
            )
        if mapped:
            lines.append(
                f"Surface overlay: {len(mapped)} exact closure "
                f"mark{'s' if len(mapped) != 1 else ''}."
            )
            lines.extend(
                "Closed: "
                + " ".join(
                    value
                    for value in (
                        str(item.get("entityType") or "").upper(),
                        str(item.get("entityRef") or ""),
                    )
                    if value
                )
                for item in mapped[:3]
            )
        elif review_required:
            lines.append(
                "Surface overlay: no exact mark; "
                f"{len(review_required)} item"
                f"{'s' if len(review_required) != 1 else ''} require chart review."
            )
        else:
            lines.append(
                "Surface overlay: no exact surface closure match in the checked window."
            )
        if review_required:
            lines.extend(
                f"Review required: {item.get('plainEnglish') or 'surface location unresolved'}"
                for item in review_required[:1]
            )
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
        canvas.setFont("Helvetica", 5.2)
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
                canvas.setFont("Helvetica-Bold", 4.1)
                canvas.drawCentredString(midpoint_x, midpoint_y + 1.5 * mm, label[:12])
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 4.0)
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
        canvas.setFont("Helvetica", 5.1)
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
        canvas.setFillColor(colors.Color(0, 0, 0, alpha=0.72))
        canvas.rect(x, y, width, 5 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 4.0)
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
    canvas.setFont("Helvetica-Bold", 6.4)
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
        else:
            summary = str(item.get("summary") or "")
        actions.append(
            {
                "title": str(item.get("title") or "Operational item"),
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
    canvas.setFont("Helvetica-Bold", 5.1)
    canvas.drawString(x + 3 * mm, y + height - 5 * mm, "DECISION GATES")

    body_y = y + 2.5 * mm
    body_h = height - 9 * mm
    cell = width / len(actions)
    for index, action in enumerate(actions):
        cx = x + index * cell
        accent = _CRITICAL if action["severity"] == "critical" else _WEATHER
        if index:
            canvas.setStrokeColor(_LINE)
            canvas.line(cx, body_y, cx, y + height - 8 * mm)
        canvas.setFillColor(accent)
        canvas.setFont("Helvetica-Bold", 4.9)
        title = action["title"]
        available_title_width = cell - 7 * mm
        while (
            title
            and pdfmetrics.stringWidth(
                title + "...",
                "Helvetica-Bold",
                4.9,
            )
            > available_title_width
        ):
            title = title[:-1]
        if title != action["title"]:
            title = title.rstrip() + "..."
        canvas.drawString(cx + 3.5 * mm, y + height - 10.5 * mm, title)
        body_width = cell - 7 * mm
        body_height = body_h - 5 * mm
        summary_words = action["summary"].split()
        summary = action["summary"]
        paragraph = _paragraph([summary], _STYLES["dark_small"])
        _, required = paragraph.wrap(body_width, body_height)
        while required > body_height and len(summary_words) > 4:
            summary_words = summary_words[:-2]
            summary = " ".join(summary_words) + "..."
            paragraph = _paragraph([summary], _STYLES["dark_small"])
            _, required = paragraph.wrap(body_width, body_height)
        paragraph.drawOn(
            canvas,
            cx + 3.5 * mm,
            body_y + max(0.0, body_height - required),
        )


def _draw_header(canvas, briefing: dict[str, Any], width: float, height: float) -> float:
    header_height = 24 * mm
    margin = 7 * mm
    canvas.setFillColor(_DARK)
    canvas.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(margin, height - 10 * mm, "PILOT")
    pilot_width = pdfmetrics.stringWidth("PILOT", "Helvetica-Bold", 12)
    canvas.setFillColor(_DEPARTURE)
    canvas.drawString(margin + pilot_width, height - 10 * mm, "DRIVEN")

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(62 * mm, height - 8.7 * mm, briefing["flight_number"])
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(62 * mm, height - 16.1 * mm, briefing["route_label"])

    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(
        160 * mm,
        height - 7.8 * mm,
        (
            f"{briefing['flight_date']} UTC · {briefing['metrics']['clock_basis']}"
            if briefing["metrics"].get("atot")
            else f"{briefing['flight_date']} UTC"
        ),
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 5.4)
    canvas.drawString(
        160 * mm,
        height - 13.2 * mm,
        f"DEP {briefing['metrics']['etd']}  ->  ARR {briefing['metrics']['eta']}",
    )
    canvas.drawString(
        160 * mm,
        height - 18.3 * mm,
        (
            f"Aircraft {briefing['metrics']['aircraft']} · "
            f"ATOT {briefing['metrics']['atot']}"
            if briefing["metrics"].get("atot")
            else f"Aircraft {briefing['metrics']['aircraft']}"
        ),
    )

    badge_w = 57 * mm
    badge_h = 8 * mm
    badge_x = width - margin - badge_w
    badge_y = height - 13.5 * mm
    canvas.setStrokeColor(colors.HexColor("#1DB9FF"))
    canvas.setFillColor(_DARK)
    canvas.roundRect(
        badge_x,
        badge_y,
        badge_w,
        badge_h,
        badge_h / 2,
        fill=1,
        stroke=1,
    )
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica", 6.0)
    canvas.drawCentredString(
        badge_x + badge_w / 2,
        badge_y + 2.8 * mm,
        "LEVEL 1 - PERTINENT BRIEF",
    )
    canvas.setStrokeColor(_LINE)
    canvas.line(margin, height - header_height, width - margin, height - header_height)
    return height - header_height - 5 * mm


def _draw_cover_airport_panel(
    canvas,
    *,
    panel: dict[str, Any],
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
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.drawString(
        x + 3 * mm,
        y + height - 4.6 * mm,
        f"{role} - {panel['icao']}",
    )

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(
        x + 3 * mm,
        y + height - 14.2 * mm,
        f"RWY {panel['runway']}",
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica-Bold", 4.6)
    canvas.drawString(x + 3 * mm, y + height - 20 * mm, "SCHEDULE")
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 5.6)
    canvas.drawRightString(x + width - 3 * mm, y + height - 20 * mm, schedule)

    overlay_lines = [
        "Surface overlay: no validated surface overlay attached; chart review required."
    ]
    if overlay:
        mapped = overlay.get("mapped") or []
        mapped_count = len(mapped)
        review_count = len(overlay.get("reviewRequired") or [])
        if mapped_count:
            overlay_lines = [
                f"Surface overlay: {mapped_count} exact closure "
                f"mark{'s' if mapped_count != 1 else ''}."
            ]
            overlay_lines.extend(
                "Closed: "
                + " ".join(
                    part
                    for part in (
                        str(item.get("entityType") or "").upper(),
                        str(item.get("entityRef") or ""),
                    )
                    if part
                )
                for item in mapped[:2]
            )
        elif review_count:
            overlay_lines = [
                f"Surface overlay: {review_count} surface item"
                f"{'s' if review_count != 1 else ''} require chart review."
            ]
        else:
            overlay_lines = [
                "Surface overlay: no exact surface closure matched the checked window."
            ]

    lines = [
        f"WEATHER: {panel['weather']['primary']}",
        *(
            f"{item['kind'].upper()}: {item['text']}"
            for item in panel.get("considerations", [])[:3]
        ),
        *overlay_lines,
        *personal_lines,
    ]
    body_x = x + 3 * mm
    body_y = y + 3 * mm
    body_w = width - 6 * mm
    body_h = height - 26 * mm
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
    canvas.setFont("Helvetica-Bold", 5.8)
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
        canvas.setFont("Helvetica-Bold", 4.7)
        canvas.drawString(card_x + 2.5 * mm, y + height - 5.5 * mm, label)
        canvas.setFillColor(_TEXT)
        canvas.setFont("Helvetica-Bold", 9.2)
        canvas.drawString(card_x + 2.5 * mm, y + height - 12.3 * mm, value)
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 4.3)
        canvas.drawString(
            card_x + 2.5 * mm,
            y + 3 * mm,
            note[:52],
        )


def _draw_cover_footer(
    canvas,
    *,
    briefing: dict[str, Any],
    width: float,
) -> None:
    margin = 7 * mm
    canvas.setStrokeColor(_LINE)
    canvas.line(margin, 8 * mm, width - margin, 8 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 4.4)
    canvas.drawString(
        margin,
        4.8 * mm,
        (
            f"PILOTDRIVEN | {briefing['flight_number']} | "
            f"{briefing['flight_date']} | Not for operational use."
        ),
    )
    canvas.drawRightString(width - margin, 4.8 * mm, "Page 1 of 3")


def _draw_page_title(
    canvas,
    briefing: dict[str, Any],
    width: float,
    height: float,
    title: str,
    page_number: int,
) -> float:
    header_height = 13 * mm
    canvas.setFillColor(_DARK)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#102A46"))
    canvas.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 11.5)
    canvas.drawString(6 * mm, height - 8.4 * mm, title)
    canvas.setFont("Helvetica", 6)
    canvas.drawRightString(
        width - 6 * mm,
        height - 8.3 * mm,
        f"{briefing['flight_number']} | Page {page_number}",
    )
    return height - header_height - 3 * mm


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
    canvas.setFont("Helvetica-Bold", 5.4)
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
        performance_note = "Performance margin not fully parsed"

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
        else "NONE PARSED"
    )
    metric_h = 18 * mm
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
                f"{len(sectors)} sector{'s' if len(sectors) != 1 else ''}",
                " / ".join(dict.fromkeys(sector_airports)) or "No sector airports parsed",
                _EDTO,
            ),
            (
                "OCEANIC",
                (oceanic or {}).get("gate", "NO TRACK"),
                (oceanic or {}).get("basis", "No named track parsed"),
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
    decision_h = 24 * mm
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
    bottom = 5 * mm
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
            else "ACTM from scheduled-departure anchor"
        ),
        final_actm=final_actm,
        x=margin,
        y=timeline_y,
        width=width - 2 * margin,
        height=timeline_h,
    )
    content_top = timeline_y - gap
    cards_h = 23 * mm
    cards_y = bottom
    content_bottom = cards_y + cards_h + gap
    left_width = 167 * mm
    right_x = margin + left_width + gap
    right_width = width - margin - right_x
    edto_view = briefing.get("edto") or {}

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
            ["No EDTO sector was parsed from the uploaded CFP."],
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
        empty_text="No EDTO airport suitability period was parsed.",
    )

    route_gate_rows = [
        [
            row["time"],
            f"{row['gate']} / {row['basis']}",
            f"{row['result']} {row['evidence']}",
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
            ("ACTM / UTC", 0.29),
            ("ROUTE GATE", 0.24),
            ("PERTINENT RESULT", 0.47),
        ],
        rows=route_gate_rows,
        accent=_COMMUNICATIONS,
        empty_text="No CFP route gate was resolved.",
    )

    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    takeoff_lines = [
        f"Planned takeoff weight: {briefing['masses']['ptow']}.",
        (
            f"Structural RTOW: {int(performance['structural_rtow_kg']):,} kg."
            if performance.get("structural_rtow_kg") is not None
            else "Structural RTOW not parsed - review required."
        ),
        (
            f"Obstacle RTOW: {int(performance['obstacle_rtow_kg']):,} kg."
            if performance.get("obstacle_rtow_kg") is not None
            else "Obstacle RTOW not parsed - review required."
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
    advisory_labels = [
        (
            "SIGMET"
            if item.get("engine") == "sigmet"
            else "VAA" if item.get("engine") == "vaa" else "tropical-cyclone"
        )
        for item in advisory_items
        if (item.get("data") or {}).get("status") == "review_required"
    ]
    affected_advisories = [
        item
        for item in advisory_items
        if (item.get("data") or {}).get("status") == "affected"
    ]
    coverage_lines = [
        f"Route: {len(route_points)} CFP points; {len(route_gate_rows)} representative gates shown.",
        (
            f"Weather: {len(weather_items)} flight windows; "
            f"{incomplete_weather} require current-source review."
        ),
        (
            "VAAC / TC: "
            + (
                " and ".join(dict.fromkeys(advisory_labels))
                + " review required"
                if advisory_labels
                else (
                    "route impact identified - review Level 2"
                    if affected_advisories
                    else (
                        "current coverage recorded"
                        if advisory_items
                        else "coverage unavailable - review required"
                    )
                )
            )
            + "."
        ),
    ]
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
    bottom = 5 * mm
    depress_findings = grouped.get("depressurisation", [])
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
            (
                "PROFILE FINDINGS",
                str(len(depress_findings)),
            ),
            ("SOURCE", "CFP MSA POINTS"),
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
        last = event.get("last_high") or first
        maximum_point = event.get("maximum") or {}
        start_actm = first.get("actm_minutes")
        end_actm = last.get("actm_minutes")
        start_clock = actm_utc_label(flight, start_actm)
        end_clock = actm_utc_label(flight, end_actm)
        utc_range = " - ".join(
            item.split("/", 1)[-1].strip()
            for item in (start_clock, end_clock)
        )
        max_msa = maximum_point.get("msa_hundreds_ft")
        maximum_label = (
            f"{int(max_msa):03d}{'*' if maximum_point.get('msa_asterisk') else ''} "
            f"{maximum_point.get('name') or ''}"
            if max_msa is not None
            else "Not resolved"
        )
        if index - 1 < len(depress_findings):
            profile = str(
                depress_findings[index - 1].get("summary")
                or "Approved profile result available in Level 2."
            )
        else:
            profile = "Not confirmed."
        source_page = (
            maximum_point.get("source_page")
            or first.get("source_page")
            or last.get("source_page")
        )
        if source_page:
            profile += f" CFP p. {source_page}."
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
            ("UTC", 0.20),
            ("ACTUAL EXPOSURE", 0.20),
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
                "Only validated CFP MSA points are shown. A starred MSA or value "
                "above 10,000 ft starts an exposure window; missing approved "
                "profile coverage remains review required."
            )
        ],
        _TERRAIN,
        dark=True,
        style=_STYLES["dark_small"],
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
    briefing = build_briefing_view(
        flight,
        findings,
        warnings,
        flight.get("timing_view"),
    )
    if map_image_path:
        briefing["route_map"]["snapshot_path"] = str(map_image_path)
        briefing["route_map"]["snapshot_label"] = map_label or "Realistic route map"

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
        _FullPageFlowable(lambda canvas, width, height: _draw_route_detail(canvas, flight, findings, briefing, width, height)),
    ]
    document.build(story)


__all__ = ["CATEGORY_COLOURS", "PAGE_SIZE", "render_level1_visual"]
