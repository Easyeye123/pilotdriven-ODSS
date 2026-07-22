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
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph

from .briefing import build_briefing_view, draw_route_map_pdf
from .constants import format_actm


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
            fontSize=5.7,
            leading=7.0,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "dark_small": ParagraphStyle(
            "Pertinent dark small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.2,
            leading=6.3,
            textColor=_TEXT,
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light": ParagraphStyle(
            "Pertinent light",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.8,
            leading=7.1,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=0,
            spaceBefore=0,
        ),
        "light_small": ParagraphStyle(
            "Pertinent light small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.25,
            leading=6.35,
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
    canvas.setFont("Helvetica-Bold", 6.9)
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


def _airport_lines(panel: dict[str, Any]) -> list[str]:
    lines = [
        f"{panel['icao']} | Planned runway {panel['runway']}",
        f"WX: {panel['weather']['primary']}",
    ]
    lines.extend(
        f"{item['kind']}: {item['text']}"
        for item in panel.get("considerations", [])[:4]
    )
    return lines


def _airport_accent(panel: dict[str, Any]) -> colors.Color:
    return _DESTINATION if panel.get("role") == "destination" else _DEPARTURE


def _draw_airport_panel(
    canvas,
    panel: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
) -> None:
    _draw_panel(
        canvas,
        x,
        y,
        width,
        height,
        title,
        _airport_lines(panel),
        _airport_accent(panel),
        dark=True,
        style=_STYLES["dark_small"],
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
    return [
        {
            "title": str(item.get("title") or "Operational item"),
            "summary": str(item.get("summary") or ""),
            "severity": str(item.get("severity") or "warning"),
        }
        for item in selected
    ]


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
    canvas.setFillColor(_WHITE_BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(_NAVY)
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

    bottom_panel_h = 32 * mm
    action_h = 18 * mm
    main_y = margin + bottom_panel_h + action_h + 3 * gap
    main_h = mass_y - main_y - gap
    left_w = 49 * mm
    right_w = 49 * mm
    centre_x = margin + left_w + gap
    centre_w = width - 2 * margin - left_w - right_w - 2 * gap

    _draw_airport_panel(canvas, briefing["departure"], margin, main_y, left_w, main_h, "DEPARTURE AIRPORT")
    draw_route_map_pdf(canvas, briefing["route_map"], centre_x, main_y, centre_w, main_h)
    _draw_airport_panel(
        canvas,
        briefing["destination"],
        centre_x + centre_w + gap,
        main_y,
        right_w,
        main_h,
        "DESTINATION AIRPORT",
    )

    action_y = margin + bottom_panel_h + gap
    _draw_action_strip(canvas, findings, margin, action_y, width - 2 * margin, action_h)

    bottom_y = margin
    available = width - 2 * margin - 2 * gap
    comm_w = available * 0.35
    edto_w = available * 0.25
    weather_w = available - comm_w - edto_w

    comm_lines = [
        f"{item['time']} | {item['actm']} | {item['event']}"
        for item in briefing.get("communications", [])[:5]
    ]
    _draw_panel(
        canvas,
        margin,
        bottom_y,
        comm_w,
        bottom_panel_h,
        "FIR / COMMUNICATIONS",
        comm_lines,
        _COMMUNICATIONS,
        dark=True,
        style=_STYLES["dark_small"],
    )

    edto = briefing["edto"]
    edto_lines = [f"ACTM {edto['entry']} - {edto['exit']}"]
    if edto.get("etps"):
        edto_lines.append("ETP: " + ", ".join(edto["etps"]))
    edto_lines.extend(
        f"{item['airport']} RWY {item['runway']} {item['approach']}"
        for item in edto.get("airports", [])[:3]
    )
    _draw_panel(
        canvas,
        margin + comm_w + gap,
        bottom_y,
        edto_w,
        bottom_panel_h,
        "EDTO",
        edto_lines,
        _EDTO,
        dark=True,
        style=_STYLES["dark_small"],
    )

    weather_lines = [
        f"{item['title']}: {item['text']}"
        for item in briefing.get("weather_cards", [])[:3]
    ]
    _draw_panel(
        canvas,
        margin + comm_w + edto_w + 2 * gap,
        bottom_y,
        weather_w,
        bottom_panel_h,
        "WEATHER / VAAC",
        weather_lines,
        _WEATHER,
        dark=True,
        style=_STYLES["dark_small"],
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
        f"{briefing['flight_number']} - OPERATIONAL DETAIL",
        2,
    )
    grouped = _group_findings(findings)
    margin = 6 * mm
    gap = 3 * mm
    bottom = 5 * mm
    column_width = (width - 2 * margin - 2 * gap) / 3

    deferred = grouped.get("mel", []) + grouped.get("cdl", []) + grouped.get("cddl", [])
    performance = grouped.get("performance", []) + grouped.get("qa", [])
    departure_lines = _airport_lines(briefing["departure"]) + _note_lines(flight, {"departure"})
    destination_lines = _airport_lines(briefing["destination"]) + _note_lines(flight, {"destination"})
    alternate_notams = [
        item for item in grouped.get("notam", [])
        if (item.get("data") or {}).get("role") in {"destination alternate", "EDTO"}
    ]
    airport_notams = [
        item for item in grouped.get("notam", [])
        if (item.get("data") or {}).get("role") in {"departure", "destination"}
    ]
    weather_items = grouped.get("weather", []) + grouped.get("vaa", [])

    _draw_column_stack(
        canvas,
        margin,
        top,
        bottom,
        column_width,
        [
            {"title": "MEL / CDL / CDDL", "lines": _finding_lines(deferred, finding_limit=6, detail_limit=2), "accent": _WEATHER},
            {"title": "PERFORMANCE / FUEL", "lines": _finding_lines(performance, finding_limit=5, detail_limit=3), "accent": _NAVY},
        ],
        gap=gap,
    )
    _draw_column_stack(
        canvas,
        margin + column_width + gap,
        top,
        bottom,
        column_width,
        [
            {"title": "DEPARTURE AIRPORT", "lines": departure_lines, "accent": _DEPARTURE},
            {"title": "DESTINATION AIRPORT", "lines": destination_lines, "accent": _DESTINATION},
        ],
        gap=gap,
    )
    _draw_column_stack(
        canvas,
        margin + 2 * (column_width + gap),
        top,
        bottom,
        column_width,
        [
            {
                "title": "ALTERNATES / EDTO AIRPORTS",
                "lines": _finding_lines(alternate_notams + grouped.get("edto", []), finding_limit=6, detail_limit=2),
                "accent": _EDTO,
            },
            {
                "title": "WEATHER / PERTINENT NOTAM",
                "lines": _finding_lines(weather_items + airport_notams, finding_limit=7, detail_limit=1),
                "accent": _severity_accent(weather_items + airport_notams, _WEATHER),
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
        f"{briefing['flight_number']} - ROUTE / CONTINGENCY",
        3,
    )
    grouped = _group_findings(findings)
    margin = 6 * mm
    gap = 3 * mm
    bottom = 5 * mm
    usable_width = width - 2 * margin - 2 * gap
    left_width = usable_width * 0.32
    middle_width = usable_width * 0.33
    right_width = usable_width - left_width - middle_width
    left_x = margin
    middle_x = left_x + left_width + gap
    right_x = middle_x + middle_width + gap

    comm_lines = _finding_lines(grouped.get("communications", []), finding_limit=7, detail_limit=2) + _note_lines(flight, {"communications"})
    timing_lines = _finding_lines(grouped.get("actual_timing", []) + grouped.get("timeline", []), finding_limit=7, detail_limit=2)
    terrain_lines = _finding_lines(grouped.get("terrain", []) + grouped.get("vws", []), finding_limit=7, detail_limit=2)
    depress_lines = _finding_lines(grouped.get("depressurisation", []), finding_limit=6, detail_limit=3)
    edto_bobcat = grouped.get("edto", []) + grouped.get("bobcat", [])
    edto_view = briefing.get("edto") or {}
    edto_summary_lines: list[str] = []
    if edto_view.get("entry") != "--.--" or edto_view.get("exit") != "--.--":
        edto_summary_lines.append(
            f"EDTO ACTM {edto_view.get('entry') or '--.--'} - {edto_view.get('exit') or '--.--'}"
        )
    if edto_view.get("etps"):
        edto_summary_lines.append("ETP: " + ", ".join(edto_view["etps"]))
    edto_summary_lines.extend(
        f"{item['airport']} | {item['period']} | RWY {item['runway']} {item['approach']}"
        for item in edto_view.get("airports", [])[:4]
    )
    edto_bobcat_lines = (
        _finding_lines(edto_bobcat, finding_limit=6, detail_limit=2)
        + edto_summary_lines
    )
    vaa_weather = grouped.get("vaa", []) + [
        item for item in grouped.get("weather", [])
        if "departure" not in str(item.get("title") or "").lower()
        and "destination" not in str(item.get("title") or "").lower()
    ]

    _draw_column_stack(
        canvas,
        left_x,
        top,
        bottom,
        left_width,
        [
            {"title": "FIR / COMMUNICATIONS", "lines": comm_lines, "accent": _COMMUNICATIONS},
            {"title": "ACTM / CALCULATED UTC", "lines": timing_lines, "accent": _NEUTRAL},
        ],
        gap=gap,
    )
    _draw_column_stack(
        canvas,
        middle_x,
        top,
        bottom,
        middle_width,
        [
            {"title": "TERRAIN MSA / VWS", "lines": terrain_lines, "accent": _TERRAIN},
            {"title": "DEPRESSURISATION PROFILES", "lines": depress_lines, "accent": _TERRAIN},
        ],
        gap=gap,
    )

    map_height = 61 * mm
    panel_bottom = bottom + map_height + gap
    _draw_column_stack(
        canvas,
        right_x,
        top,
        panel_bottom,
        right_width,
        [
            {"title": "EDTO / BOBCAT", "lines": edto_bobcat_lines, "accent": _EDTO},
            {
                "title": "ENROUTE WEATHER / VAAC",
                "lines": _finding_lines(vaa_weather, finding_limit=5, detail_limit=2),
                "accent": _severity_accent(vaa_weather, _WEATHER),
            },
        ],
        gap=gap,
    )
    draw_route_map_pdf(canvas, briefing["route_map"], right_x, bottom, right_width, map_height)


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
