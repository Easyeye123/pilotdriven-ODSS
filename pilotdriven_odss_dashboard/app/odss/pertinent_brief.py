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
        "ACTM from scheduled-departure anchor",
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
    for item in sorted(findings, key=_finding_sort_key)[:finding_limit]:
        if item.get("engine") != "weather":
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

        data = item.get("data") or {}
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
                f"Mechanism: {mechanism.rstrip('.')}.",
                f"Timing: {timing}",
                f"Flight effect: {flight_effect}",
            ]
        )
    return lines


def _group_findings(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[str(finding.get("engine") or "other")].append(finding)
    return grouped


def _top_actions(findings: list[dict[str, Any]], limit: int = 5) -> list[dict[str, str]]:
    operational = [
        item
        for item in findings
        if item.get("severity") in {"critical", "warning"}
        and item.get("engine") not in {"qa", "page1", "timeline"}
    ]
    selected = sorted(operational, key=_finding_sort_key)[:limit]
    actions: list[dict[str, str]] = []
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
    return actions


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
    actions = _top_actions(findings)
    if not actions:
        actions = [{
            "title": "No principal exception selected",
            "summary": "Detailed airport, route and weather information remains on Pages 2 and 3.",
            "severity": "information",
        }]
    cell = width / len(actions)
    for index, action in enumerate(actions):
        cx = x + index * cell
        accent = _CRITICAL if action["severity"] == "critical" else _WEATHER
        canvas.setFillColor(_PANEL)
        canvas.setStrokeColor(accent)
        canvas.roundRect(cx + 1.2 * mm, y, cell - 2.4 * mm, height, 3, fill=1, stroke=1)
        canvas.setFillColor(accent)
        canvas.setFont("Helvetica-Bold", 5.4)
        canvas.drawString(cx + 3.4 * mm, y + height - 4.4 * mm, action["title"][:42])
        paragraph = _paragraph([action["summary"]], _STYLES["dark_small"])
        body_width = cell - 6.8 * mm
        body_height = height - 7.2 * mm
        _, required = paragraph.wrap(body_width, body_height)
        paragraph.drawOn(canvas, cx + 3.4 * mm, y + 2.2 * mm + max(0.0, body_height - required))


def _draw_header(canvas, briefing: dict[str, Any], width: float, height: float) -> float:
    header_height = 12 * mm
    canvas.setFillColor(colors.HexColor("#081522"))
    canvas.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(5 * mm, height - 7.7 * mm, "PILOT")
    pilot_width = pdfmetrics.stringWidth("PILOT", "Helvetica-Bold", 12)
    canvas.setFillColor(_DEPARTURE)
    canvas.drawString(5 * mm + pilot_width, height - 7.7 * mm, "DRIVEN")

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawCentredString(
        width / 2,
        height - 7.6 * mm,
        f"{briefing['flight_number']}  {briefing['route_label']}  {briefing['flight_date']}",
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 5.2)
    canvas.drawRightString(
        width - 5 * mm,
        height - 7.5 * mm,
        f"Updated {briefing['generated_at_display']} | NOTAM {briefing['counts']['notams']} | WX {briefing['counts']['weather']}",
    )
    return height - header_height


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
    margin = 4 * mm
    gap = 2 * mm
    metric_h = 13 * mm
    mass_h = 11 * mm

    metric_items = [
        ("DISTANCE", briefing["metrics"]["distance"]),
        ("EET", briefing["metrics"]["eet"]),
        ("FIRS", str(briefing["metrics"]["fir_count"])),
        ("ETD", briefing["metrics"]["etd"]),
        ("ETA", briefing["metrics"]["eta"]),
        ("AIRCRAFT", briefing["metrics"]["aircraft"]),
        ("CRUISE", briefing["metrics"]["cruise"]),
        ("ALTN", briefing["metrics"]["alternate"]),
    ]
    metric_y = top - metric_h
    _draw_metric_strip(canvas, metric_items, margin, metric_y, width - 2 * margin, metric_h, _PANEL_2)

    mass_items = [
        ("PZFW", briefing["masses"]["pzfw"]),
        ("PLDW", briefing["masses"]["pldw"]),
        ("PTOW", briefing["masses"]["ptow"]),
        ("FUEL", briefing["fuel"]["tanks"]),
        ("TRIP", briefing["fuel"]["trip"]),
        ("DEST", briefing["fuel"]["destination"]),
    ]
    mass_y = metric_y - mass_h
    _draw_metric_strip(canvas, mass_items, margin, mass_y, width - 2 * margin, mass_h, colors.HexColor("#0A2035"))

    summary_h = 15 * mm
    section_label_h = 5 * mm
    main_y = margin + summary_h + 2 * gap
    main_h = mass_y - section_label_h - main_y - gap
    left_w = 49 * mm
    right_w = 49 * mm
    centre_x = margin + left_w + gap
    centre_w = width - 2 * margin - left_w - right_w - 2 * gap

    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica-Bold", 5.4)
    canvas.drawCentredString(
        width / 2,
        mass_y - 3.5 * mm,
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
    _draw_airport_panel(
        canvas,
        briefing["departure"],
        margin,
        main_y,
        left_w,
        main_h,
        "DEPARTURE AIRPORT",
        departure_overlay,
        _note_lines(flight, {"departure"}),
    )
    draw_route_map_pdf(canvas, briefing["route_map"], centre_x, main_y, centre_w, main_h)
    _draw_airport_panel(
        canvas,
        briefing["destination"],
        centre_x + centre_w + gap,
        main_y,
        right_w,
        main_h,
        "DESTINATION AIRPORT",
        destination_overlay,
        _note_lines(flight, {"destination"}),
    )

    grouped = _group_findings(findings)
    summary_items = [
        (
            "AIRPORT",
            f"{sum(item.get('severity') == 'critical' for item in grouped.get('notam', []))} CRITICAL",
        ),
        (
            "WEATHER",
            f"{sum(item.get('severity') in {'critical', 'warning', 'unknown'} for item in grouped.get('weather', []) + grouped.get('vaa', []) + grouped.get('tropical_cyclone', []))} REVIEW",
        ),
        ("EDTO", f"{len(edto_sectors(flight.get('edto') or {}))} SECTORS"),
        ("CONTACTS", f"{len(grouped.get('communications', []))} EARLY"),
        (
            "TERRAIN",
            f"{len(detect_terrain_events(flight.get('route_waypoints') or []))} WINDOWS",
        ),
    ]
    _draw_metric_strip(
        canvas,
        summary_items,
        margin,
        margin,
        width - 2 * margin,
        summary_h,
        _PANEL_2,
    )


def _note_lines(flight: dict[str, Any], placements: set[str]) -> list[str]:
    lines = [
        f"Personal note: {' '.join(str(note.get('note_text') or '').split())}"
        for note in (flight.get("personal_notes") or [])
        if note.get("placement") in placements and note.get("include_level1")
    ]
    if lines:
        lines.append("Pilot-entered content; not ODSS-validated.")
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
        f"{briefing['flight_number']} - TIME-BASED OPERATING GATES",
        2,
    )
    grouped = _group_findings(findings)
    margin = 6 * mm
    gap = 3 * mm
    bottom = 5 * mm
    column_width = (width - 2 * margin - gap) / 2
    right_x = margin + column_width + gap
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

    timeline_h = 27 * mm
    timeline_y = top - timeline_h - gap
    _draw_phase_timeline(
        canvas,
        sectors=sectors,
        communications=grouped.get("communications", []),
        final_actm=final_actm,
        x=margin,
        y=timeline_y,
        width=width - 2 * margin,
        height=timeline_h,
    )
    content_top = timeline_y - gap

    deferred = grouped.get("mel", []) + grouped.get("cdl", []) + grouped.get("cddl", [])
    alternate_notams = [
        item for item in grouped.get("notam", [])
        if (item.get("data") or {}).get("role") in {"destination alternate", "EDTO"}
    ]
    weather_items = [
        item
        for item in grouped.get("vaa", [])
        + grouped.get("tropical_cyclone", [])
        + grouped.get("weather", [])
        if (item.get("data") or {}).get("phase")
        not in {"Departure", "Destination"}
        if (item.get("data") or {}).get("window_status")
        != "no_significant_overlap"
    ]
    communication_lines = _finding_lines(
        grouped.get("communications", []),
        finding_limit=7,
        detail_limit=2,
    ) + _note_lines(flight, {"communications"})
    timing_lines = _finding_lines(
        grouped.get("actual_timing", []),
        finding_limit=5,
        detail_limit=2,
    )
    edto_exceptions = [
        item
        for item in grouped.get("edto", [])
        if item.get("severity") in {"critical", "warning", "unknown"}
    ]
    edto_lines = _finding_lines(
        alternate_notams + edto_exceptions,
        finding_limit=6,
        detail_limit=2,
    )
    edto_view = briefing.get("edto") or {}
    edto_lines.extend(
        f"Sector {sector.get('number', index)}: entry ACTM "
        f"{sector.get('entry') or '--.--'}; exit ACTM "
        f"{sector.get('exit') or '--.--'}"
        + (
            "; ETP ACTM " + ", ".join(sector.get("etps") or [])
            if sector.get("etps")
            else ""
        )
        for index, sector in enumerate(edto_view.get("sectors") or [], start=1)
    )
    edto_lines.extend(
        f"{item['airport']} | {item['period']} | RWY {item['runway']} {item['approach']}"
        for item in (edto_view.get("airports") or [])[:4]
    )

    edto_panel_h = min(
        53 * mm,
        _panel_height(
            edto_lines,
            column_width,
            _STYLES["dark"],
            min_height=30 * mm,
        ),
    )
    _draw_panel(
        canvas,
        margin,
        bottom,
        column_width,
        edto_panel_h,
        "EDTO SECTORS / ALTERNATES",
        edto_lines,
        _EDTO,
        dark=True,
        style=_STYLES["dark"],
    )

    chart_bottom = bottom + edto_panel_h + gap
    chart_available = max(20 * mm, content_top - chart_bottom)
    if sectors:
        chart_gap = 2 * mm
        chart_height = (
            chart_available - chart_gap * (len(sectors) - 1)
        ) / len(sectors)
        cursor = content_top
        for index, sector in enumerate(sectors, start=1):
            start = int(sector.get("entry_actm_minutes") or 0)
            end = int(sector.get("exit_actm_minutes") or start)
            markers = _sector_etp_markers(route_points, sector, index)
            points = _route_window_points(
                route_points,
                start,
                end,
                markers=markers,
            )
            chart_y = cursor - chart_height
            _draw_route_evidence_chart(
                canvas,
                points,
                margin,
                chart_y,
                column_width,
                chart_height,
                title=(
                    f"EDTO {index} | ENTRY {format_actm(start)} | "
                    f"EXIT {format_actm(end)}"
                ),
                mode="edto",
            )
            cursor = chart_y - chart_gap
    else:
        _draw_panel(
            canvas,
            margin,
            chart_bottom,
            column_width,
            chart_available,
            "EDTO ROUTE EVIDENCE",
            ["No EDTO sector was parsed from the uploaded CFP."],
            _EDTO,
            dark=True,
            style=_STYLES["dark"],
        )

    _draw_column_stack(
        canvas,
        right_x,
        content_top,
        bottom,
        column_width,
        [
            {
                "title": "MEL / CDL / CDDL",
                "lines": _finding_lines(deferred, finding_limit=6, detail_limit=2),
                "accent": _WEATHER,
                "dark": True,
                "style": _STYLES["dark"],
            },
            {
                "title": "ACTUAL CLOCK / CALCULATED UTC",
                "lines": timing_lines,
                "accent": _NEUTRAL,
                "dark": True,
                "style": _STYLES["dark"],
            },
            {
                "title": "FIR / COMMUNICATIONS",
                "lines": communication_lines,
                "accent": _COMMUNICATIONS,
                "dark": True,
                "style": _STYLES["dark"],
            },
            {
                "title": "ENROUTE WEATHER / VAAC / TC",
                "lines": _pilot_weather_lines(weather_items, finding_limit=5),
                "accent": _severity_accent(weather_items, _WEATHER),
                "dark": True,
                "style": _STYLES["dark"],
            },
        ],
        gap=gap,
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
    column_width = (width - 2 * margin - gap) / 2
    right_x = margin + column_width + gap
    terrain_findings = grouped.get("terrain", []) + grouped.get("vws", [])
    terrain_lines = _finding_lines(
        terrain_findings,
        finding_limit=7,
        detail_limit=2,
    )
    depress_findings = grouped.get("depressurisation", [])
    depress_lines = _finding_lines(
        depress_findings,
        finding_limit=6,
        detail_limit=3,
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

    panels_h = max(
        38 * mm,
        min(
            64 * mm,
            max(
                _panel_height(
                    terrain_lines,
                    column_width,
                    _STYLES["dark"],
                    min_height=38 * mm,
                ),
                _panel_height(
                    depress_lines,
                    column_width,
                    _STYLES["dark"],
                    min_height=38 * mm,
                ),
            ),
        ),
    )
    _draw_panel(
        canvas,
        margin,
        bottom,
        column_width,
        panels_h,
        "HIGH TERRAIN MSA / VWS",
        terrain_lines or ["No high-terrain exposure was extracted from the CFP."],
        _TERRAIN,
        dark=True,
        style=_STYLES["dark"],
    )
    _draw_panel(
        canvas,
        right_x,
        bottom,
        column_width,
        panels_h,
        "DEPRESSURISATION PROFILE COVERAGE",
        depress_lines or [
            "No approved matching profile was available; pilot review is required."
        ],
        _TERRAIN,
        dark=True,
        style=_STYLES["dark"],
    )

    chart_y = bottom + panels_h + gap
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
    briefing = build_briefing_view(flight, findings, warnings, None)
    if map_image_path:
        briefing["route_map"]["snapshot_path"] = str(map_image_path)
        briefing["route_map"]["snapshot_label"] = map_label or "Realistic route map"

    document = BaseDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=4 * mm,
        rightMargin=4 * mm,
        topMargin=4 * mm,
        bottomMargin=4 * mm,
    )
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="pertinent")
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
