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
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph

from .briefing import build_briefing_view, draw_route_map_pdf


PAGE_SIZE = landscape(A4)
LEVEL1_PAGE_SIZE = A4
_DARK = colors.HexColor("#07111F")
_DARK_2 = colors.HexColor("#102843")
_PANEL = colors.HexColor("#0D1B2C")
_PANEL_2 = colors.HexColor("#13283E")
_LINE = colors.HexColor("#28425F")
_TEXT = colors.HexColor("#E8F2FF")
_MUTED = colors.HexColor("#93A4B8")
_BLUE = colors.HexColor("#4DB8FF")
_GREEN = colors.HexColor("#59D48A")
_AMBER = colors.HexColor("#FFB84D")
_RED = colors.HexColor("#FF6B6B")
_PURPLE = colors.HexColor("#B38CFF")
_WHITE_BG = colors.HexColor("#F4F7FA")
_NAVY = colors.HexColor("#173B65")
_GREY = colors.HexColor("#4B5563")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "panel": ParagraphStyle(
            "Visual panel",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=6.2,
            leading=7.5,
            textColor=_TEXT,
        ),
        "panel_small": ParagraphStyle(
            "Visual panel small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.4,
            leading=6.5,
            textColor=_TEXT,
        ),
        "detail": ParagraphStyle(
            "Visual detail",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#1F2937"),
        ),
        "detail_small": ParagraphStyle(
            "Visual detail small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.8,
            leading=7,
            textColor=colors.HexColor("#1F2937"),
        ),
        "level1": ParagraphStyle(
            "Level 1 readable body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=9.2,
            textColor=colors.HexColor("#1F2937"),
        ),
        "metric": ParagraphStyle(
            "Visual metric",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=5.4,
            leading=6.5,
            alignment=TA_CENTER,
            textColor=_TEXT,
        ),
    }


_STYLES = _styles()


def _fit_paragraph(lines: list[str], style: ParagraphStyle, width: float, height: float) -> Paragraph:
    prepared = [line for line in lines if line]
    if not prepared:
        prepared = ["No pertinent item selected."]
    while prepared:
        text = "<br/>".join(escape(line) for line in prepared)
        paragraph = Paragraph(text, style)
        _, required = paragraph.wrap(width, height)
        if required <= height:
            return paragraph
        prepared = prepared[:-1]
    return Paragraph("See expanded brief.", style)


def _draw_text(canvas, lines: list[str], x: float, y: float, width: float, height: float, style: ParagraphStyle) -> None:
    paragraph = _fit_paragraph(lines, style, width, height)
    _, required = paragraph.wrap(width, height)
    paragraph.drawOn(canvas, x, y + height - required)


def _draw_panel(
    canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    lines: list[str],
    accent: colors.Color = _BLUE,
    dark: bool = True,
    style: ParagraphStyle | None = None,
) -> None:
    background = _PANEL if dark else colors.white
    title_background = accent
    canvas.setFillColor(background)
    canvas.setStrokeColor(_LINE if dark else colors.HexColor("#D9E1E8"))
    canvas.roundRect(x, y, width, height, 4, fill=1, stroke=1)
    canvas.setFillColor(title_background)
    canvas.roundRect(x, y + height - 8 * mm, width, 8 * mm, 4, fill=1, stroke=0)
    canvas.rect(x, y + height - 8 * mm, width, 4 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 7.2)
    canvas.drawString(x + 3 * mm, y + height - 5.3 * mm, title)
    _draw_text(
        canvas,
        lines,
        x + 3 * mm,
        y + 3 * mm,
        width - 6 * mm,
        height - 13 * mm,
        style or (_STYLES["panel"] if dark else _STYLES["detail"]),
    )


def _severity_colour(severity: str) -> colors.Color:
    return {
        "critical": _RED,
        "warning": _AMBER,
        "unknown": _PURPLE,
    }.get(severity, _BLUE)


def _draw_metric_strip(canvas, briefing: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    metrics = briefing["metrics"]
    items = [
        ("DISTANCE", metrics["distance"]),
        ("EET", metrics["eet"]),
        ("FIRS", str(metrics["fir_count"])),
        ("ETD", metrics["etd"]),
        ("ETA", metrics["eta"]),
        ("AIRCRAFT", metrics["aircraft"]),
        ("CRUISE", metrics["cruise"]),
        ("ALTN", metrics["alternate"]),
    ]
    cell = width / len(items)
    for index, (label, value) in enumerate(items):
        cx = x + index * cell
        canvas.setFillColor(_PANEL_2)
        canvas.setStrokeColor(_LINE)
        canvas.rect(cx, y, cell, height, fill=1, stroke=1)
        _draw_text(
            canvas,
            [f"<b>{label}</b>", value],
            cx + 1.5 * mm,
            y + 1.2 * mm,
            cell - 3 * mm,
            height - 2.4 * mm,
            _STYLES["metric"],
        )


def _draw_mass_strip(canvas, briefing: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    masses = briefing["masses"]
    fuel = briefing["fuel"]
    items = [
        ("PZFW", masses["pzfw"]),
        ("PLDW", masses["pldw"]),
        ("PTOW", masses["ptow"]),
        ("FUEL", fuel["tanks"]),
        ("TRIP", fuel["trip"]),
        ("DEST", fuel["destination"]),
    ]
    cell = width / len(items)
    for index, (label, value) in enumerate(items):
        cx = x + index * cell
        canvas.setFillColor(colors.HexColor("#0A2035"))
        canvas.setStrokeColor(_LINE)
        canvas.rect(cx, y, cell, height, fill=1, stroke=1)
        _draw_text(
            canvas,
            [f"<b>{label}</b>", value],
            cx + 1.5 * mm,
            y + 1 * mm,
            cell - 3 * mm,
            height - 2 * mm,
            _STYLES["metric"],
        )


def _airport_lines(panel: dict[str, Any]) -> list[str]:
    lines = [
        f"<b>{panel['icao']}</b> | Planned runway {panel['runway']}",
        f"WX: {panel['weather']['primary']}",
    ]
    for item in panel.get("considerations", [])[:4]:
        lines.append(f"- {item['kind']}: {item['text']}")
    return lines


def _draw_airport_panel(
    canvas,
    panel: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    destination: str,
) -> None:
    _draw_panel(canvas, x, y, width, height, title, _airport_lines(panel), _BLUE, True, _STYLES["panel_small"])
    button_y = y + 3 * mm
    button_h = 7 * mm
    canvas.setFillColor(colors.HexColor("#13283E"))
    canvas.setStrokeColor(_BLUE)
    canvas.roundRect(x + 3 * mm, button_y, width - 6 * mm, button_h, 3, fill=1, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 5.8)
    canvas.drawCentredString(x + width / 2, button_y + 2.4 * mm, "VIEW FULL AIRPORT BRIEFING")
    canvas.linkRect("", destination, (x + 3 * mm, button_y, x + width - 3 * mm, button_y + button_h), relative=1, thickness=0)


def _draw_exceptions(canvas, briefing: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    cards = briefing.get("exception_cards") or []
    cell = width / max(1, len(cards))
    for index, card in enumerate(cards):
        cx = x + index * cell
        colour = _severity_colour(card.get("severity", "information"))
        canvas.setFillColor(colors.HexColor("#0D1B2C"))
        canvas.setStrokeColor(colour)
        canvas.roundRect(cx + 1.5 * mm, y, cell - 3 * mm, height, 3, fill=1, stroke=1)
        canvas.setFillColor(colour)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(cx + 4 * mm, y + height - 6.5 * mm, str(card.get("count", 0)))
        canvas.setFillColor(_TEXT)
        canvas.setFont("Helvetica-Bold", 5.6)
        canvas.drawString(cx + 12 * mm, y + height - 5.2 * mm, str(card.get("label") or ""))
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 4.8)
        canvas.drawString(cx + 12 * mm, y + height - 9.2 * mm, str(card.get("detail") or "")[:42])


def _draw_cover(canvas, briefing: dict[str, Any], width: float, height: float) -> None:
    canvas.bookmarkPage("visual_briefing")
    canvas.setFillColor(_DARK)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    margin = 4 * mm
    top_h = 12 * mm
    metric_h = 13 * mm
    mass_h = 11 * mm
    gap = 2 * mm

    canvas.setFillColor(colors.HexColor("#081522"))
    canvas.rect(0, height - top_h, width, top_h, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(margin, height - 7.7 * mm, "PILOTDRIVEN")
    canvas.setFillColor(_BLUE)
    canvas.drawString(margin + 28 * mm, height - 7.7 * mm, "ODSS")
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 8.8)
    canvas.drawString(margin + 50 * mm, height - 7.6 * mm, f"{briefing['flight_number']}  {briefing['route_label']}  {briefing['flight_date']}")
    canvas.setFillColor(_GREEN)
    canvas.setFont("Helvetica-Bold", 6.4)
    canvas.drawRightString(width - margin, height - 5.4 * mm, briefing["status"])
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 5.2)
    canvas.drawRightString(width - margin, height - 9.3 * mm, f"Updated {briefing['generated_at_display']} | NOTAM {briefing['counts']['notams']} | WX {briefing['counts']['weather']}")

    metric_y = height - top_h - metric_h
    _draw_metric_strip(canvas, briefing, margin, metric_y, width - 2 * margin, metric_h)
    mass_y = metric_y - mass_h
    _draw_mass_strip(canvas, briefing, margin, mass_y, width - 2 * margin, mass_h)

    bottom_h = 39 * mm
    exception_h = 15 * mm
    main_y = bottom_h + exception_h + 4 * gap + margin
    main_h = mass_y - main_y - gap
    left_w = 49 * mm
    right_w = 49 * mm
    center_x = margin + left_w + gap
    center_w = width - 2 * margin - left_w - right_w - 2 * gap
    _draw_airport_panel(canvas, briefing["departure"], margin, main_y, left_w, main_h, "DEPARTURE AIRPORT", "departure_detail")
    draw_route_map_pdf(canvas, briefing["route_map"], center_x, main_y, center_w, main_h)
    _draw_airport_panel(canvas, briefing["destination"], center_x + center_w + gap, main_y, right_w, main_h, "DESTINATION AIRPORT", "destination_detail")

    exception_y = bottom_h + 2 * gap + margin
    _draw_exceptions(canvas, briefing, margin, exception_y, width - 2 * margin, exception_h)

    bottom_y = margin + gap
    available = width - 2 * margin - 3 * gap
    comm_w = available * 0.30
    edto_w = available * 0.23
    weather_w = available * 0.29
    links_w = available - comm_w - edto_w - weather_w

    comm_lines = [
        f"{item['time']} | {item['actm']} | {item['event']}"
        for item in briefing.get("communications", [])[:5]
    ] or ["No route-specific early call rule matched."]
    _draw_panel(canvas, margin, bottom_y, comm_w, bottom_h, "FIR COMMUNICATION TIMELINE", comm_lines, _PURPLE, True, _STYLES["panel_small"])
    canvas.linkRect("", "communications_detail", (margin, bottom_y, margin + comm_w, bottom_y + bottom_h), relative=1, thickness=0)

    edto = briefing["edto"]
    edto_lines = [f"ACTM {edto['entry']} - {edto['exit']}"]
    if edto.get("etps"):
        edto_lines.append("ETP: " + ", ".join(edto["etps"]))
    edto_lines.extend(f"{item['airport']} RWY {item['runway']} {item['approach']}" for item in edto.get("airports", [])[:3])
    _draw_panel(canvas, margin + comm_w + gap, bottom_y, edto_w, bottom_h, "EDTO SUMMARY", edto_lines, _GREEN, True, _STYLES["panel_small"])
    canvas.linkRect("", "edto_detail", (margin + comm_w + gap, bottom_y, margin + comm_w + gap + edto_w, bottom_y + bottom_h), relative=1, thickness=0)

    weather_lines = [f"{item['title']}: {item['text']}" for item in briefing.get("weather_cards", [])[:3]]
    _draw_panel(canvas, margin + comm_w + edto_w + 2 * gap, bottom_y, weather_w, bottom_h, "ENROUTE WEATHER", weather_lines, _AMBER, True, _STYLES["panel_small"])

    links_x = margin + comm_w + edto_w + weather_w + 3 * gap
    link_lines = [
        "Page 2 - Operational detail",
        "Page 3 - Route / contingency",
        "MEL, NOTAM, weather and performance",
        "ATC, EDTO, MSA, VWS and profiles",
    ]
    _draw_panel(canvas, links_x, bottom_y, links_w, bottom_h, "BRIEFING LINKS", link_lines, _BLUE, True, _STYLES["panel_small"])
    canvas.linkRect("", "operational_detail", (links_x, bottom_y + bottom_h / 2, links_x + links_w, bottom_y + bottom_h), relative=1, thickness=0)
    canvas.linkRect("", "route_contingency", (links_x, bottom_y, links_x + links_w, bottom_y + bottom_h / 2), relative=1, thickness=0)

    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 4.8)
    canvas.drawCentredString(width / 2, 1.4 * mm, "Decision support only - approved documents, dispatch authority, ATC instructions and PIC judgement remain controlling.")


def _findings_by_engine(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[str(finding.get("engine") or "other")].append(finding)
    return grouped


def _finding_lines(findings: list[dict[str, Any]], limit: int = 7, detail_limit: int = 1) -> list[str]:
    lines: list[str] = []
    for item in findings[:limit]:
        lines.append(f"{item.get('title', 'Finding')}: {item.get('summary', '')}")
        lines.extend(f"- {detail}" for detail in (item.get("details") or [])[:detail_limit])
    return lines or ["No pertinent item selected."]


def _note_lines(flight: dict[str, Any], placements: set[str], level: int) -> list[str]:
    key = "include_level1" if level == 1 else "include_level2"
    selected = [
        note for note in (flight.get("personal_notes") or [])
        if note.get("placement") in placements and note.get(key)
    ]
    lines = [f"Personal note: {str(note.get('note_text') or '').strip()}" for note in selected]
    if lines:
        lines.append("Pilot-entered content; not ODSS-validated.")
    return lines


def _draw_detail_header(canvas, width: float, height: float, title: str, page_number: int) -> None:
    canvas.setFillColor(_WHITE_BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(_NAVY)
    canvas.rect(0, height - 13 * mm, width, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(6 * mm, height - 8.5 * mm, title)
    canvas.setFont("Helvetica", 6)
    canvas.drawRightString(width - 6 * mm, height - 8.3 * mm, f"PilotDriven ODSS | Page {page_number}")
    canvas.setFillColor(_GREY)
    canvas.setFont("Helvetica", 5)
    canvas.drawCentredString(width / 2, 2.2 * mm, "Decision support only - refer to current approved operational documents and live dispatch information.")


def _draw_operational_detail(canvas, flight: dict[str, Any], findings: list[dict[str, Any]], briefing: dict[str, Any], width: float, height: float, level: int) -> None:
    for destination in ("operational_detail", "departure_detail", "destination_detail"):
        canvas.bookmarkPage(destination)
    _draw_detail_header(canvas, width, height, f"{briefing['flight_number']} - OPERATIONAL DETAIL", 2)
    grouped = _findings_by_engine(findings)
    margin = 6 * mm
    gap = 3 * mm
    top = height - 17 * mm
    mass_h = 16 * mm
    mass_w = (width - 2 * margin - 5 * gap) / 6
    mass_items = [
        ("PZFW", briefing["masses"]["pzfw"]),
        ("PLDW", briefing["masses"]["pldw"]),
        ("PTOW", briefing["masses"]["ptow"]),
        ("FUEL", briefing["fuel"]["tanks"]),
        ("TRIP", briefing["fuel"]["trip"]),
        ("DEST", briefing["fuel"]["destination"]),
    ]
    for index, (label, value) in enumerate(mass_items):
        x = margin + index * (mass_w + gap)
        _draw_panel(canvas, x, top - mass_h, mass_w, mass_h, label, [value], _BLUE, False, _STYLES["detail_small"])

    body_top = top - mass_h - gap
    body_bottom = 7 * mm
    body_height = body_top - body_bottom
    column_w = (width - 2 * margin - 2 * gap) / 3
    x1 = margin
    x2 = margin + column_w + gap
    x3 = margin + 2 * (column_w + gap)
    half = (body_height - gap) / 2

    mel_lines = _finding_lines(grouped.get("mel", []) + grouped.get("cddl", []), 7, 2)
    mel_lines.extend(_note_lines(flight, {"separate"}, level)[:2])
    _draw_panel(canvas, x1, body_bottom + half + gap, column_w, half, "MEL / CDL / CDDL", mel_lines, _AMBER, False, _STYLES["detail_small"])
    _draw_panel(canvas, x1, body_bottom, column_w, half, "PERFORMANCE / FUEL", _finding_lines(grouped.get("performance", []) + grouped.get("qa", []), 6, 3), _NAVY, False, _STYLES["detail_small"])

    dep_lines = _airport_lines(briefing["departure"])
    dep_lines.extend(_note_lines(flight, {"departure"}, level))
    dest_lines = _airport_lines(briefing["destination"])
    dest_lines.extend(_note_lines(flight, {"destination"}, level))
    _draw_panel(canvas, x2, body_bottom + half + gap, column_w, half, "DEPARTURE AIRPORT", dep_lines, _BLUE, False, _STYLES["detail_small"])
    _draw_panel(canvas, x2, body_bottom, column_w, half, "DESTINATION AIRPORT", dest_lines, _GREEN, False, _STYLES["detail_small"])

    alternate_notams = [
        item for item in grouped.get("notam", [])
        if item.get("data", {}).get("role") in {"destination alternate", "EDTO"}
    ]
    weather_lines = _finding_lines(grouped.get("weather", []), 7, 1)
    _draw_panel(canvas, x3, body_bottom + half + gap, column_w, half, "ALTERNATES / EDTO AIRPORTS", _finding_lines(alternate_notams + grouped.get("edto", []), 7, 2), _PURPLE, False, _STYLES["detail_small"])
    _draw_panel(canvas, x3, body_bottom, column_w, half, "WEATHER / PERTINENT NOTAM", weather_lines + _finding_lines(grouped.get("notam", []), 4, 1), _RED, False, _STYLES["detail_small"])


def _draw_route_detail(canvas, flight: dict[str, Any], findings: list[dict[str, Any]], briefing: dict[str, Any], width: float, height: float, level: int) -> None:
    for destination in ("route_contingency", "communications_detail", "edto_detail"):
        canvas.bookmarkPage(destination)
    _draw_detail_header(canvas, width, height, f"{briefing['flight_number']} - ROUTE / CONTINGENCY", 3)
    grouped = _findings_by_engine(findings)
    margin = 6 * mm
    gap = 3 * mm
    top = height - 17 * mm
    bottom = 7 * mm
    available_h = top - bottom
    left_w = (width - 2 * margin - 2 * gap) * 0.34
    middle_w = (width - 2 * margin - 2 * gap) * 0.33
    right_w = width - 2 * margin - 2 * gap - left_w - middle_w
    x1 = margin
    x2 = x1 + left_w + gap
    x3 = x2 + middle_w + gap
    half = (available_h - gap) / 2

    comm_lines = _finding_lines(grouped.get("communications", []), 7, 2)
    comm_lines.extend(_note_lines(flight, {"communications"}, level))
    timing_lines = _finding_lines(grouped.get("actual_timing", []) + grouped.get("timeline", []), 7, 2)
    _draw_panel(canvas, x1, bottom + half + gap, left_w, half, "FIR / COMMUNICATIONS", comm_lines, _PURPLE, False, _STYLES["detail_small"])
    _draw_panel(canvas, x1, bottom, left_w, half, "ACTM / CALCULATED UTC TIMELINE", timing_lines, _NAVY, False, _STYLES["detail_small"])

    terrain_lines = _finding_lines(grouped.get("terrain", []) + grouped.get("vws", []), 8, 2)
    depress_lines = _finding_lines(grouped.get("depressurisation", []), 6, 3)
    _draw_panel(canvas, x2, bottom + half + gap, middle_w, half, "TERRAIN MSA / VWS", terrain_lines, _AMBER, False, _STYLES["detail_small"])
    _draw_panel(canvas, x2, bottom, middle_w, half, "DEPRESSURISATION PROFILES", depress_lines, _RED, False, _STYLES["detail_small"])

    edto_lines = _finding_lines(grouped.get("edto", []), 6, 3)
    bobcat_lines = _finding_lines(grouped.get("bobcat", []), 4, 3)
    map_h = available_h * 0.42
    _draw_panel(canvas, x3, top - map_h, right_w, map_h, "EDTO / BOBCAT", edto_lines + bobcat_lines, _GREEN, False, _STYLES["detail_small"])
    draw_route_map_pdf(canvas, briefing["route_map"], x3, bottom, right_w, available_h - map_h - gap)


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


def visual_cover_flowable(briefing: dict[str, Any]) -> Flowable:
    return _FullPageFlowable(lambda canvas, width, height: _draw_cover(canvas, briefing, width, height))


def operational_detail_flowable(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    level: int,
) -> Flowable:
    return _FullPageFlowable(
        lambda canvas, width, height: _draw_operational_detail(canvas, flight, findings, briefing, width, height, level)
    )


def route_detail_flowable(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    level: int,
) -> Flowable:
    return _FullPageFlowable(
        lambda canvas, width, height: _draw_route_detail(canvas, flight, findings, briefing, width, height, level)
    )


def _level1_section_lines(
    grouped: dict[str, list[dict[str, Any]]],
    engines: tuple[str, ...],
    *,
    finding_limit: int,
    detail_limit: int,
) -> list[str]:
    selected: list[dict[str, Any]] = []
    for engine in engines:
        selected.extend(grouped.get(engine, []))
    lines = _finding_lines(selected, finding_limit, detail_limit)
    if len(selected) > finding_limit:
        lines.append(f"{len(selected) - finding_limit} additional finding(s) are retained in Level 2.")
    return lines


def _draw_level1_header(
    canvas,
    briefing: dict[str, Any],
    width: float,
    height: float,
    page_number: int,
) -> float:
    canvas.setFillColor(_WHITE_BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(_NAVY)
    canvas.rect(0, height - 22 * mm, width, 22 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(9 * mm, height - 9 * mm, "PILOTDRIVEN ODSS")
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(
        9 * mm,
        height - 16 * mm,
        f"{briefing['flight_number']}  {briefing['route_label']}  {briefing['flight_date']}",
    )
    canvas.setFont("Helvetica", 6.5)
    canvas.drawRightString(
        width - 9 * mm,
        height - 9 * mm,
        f"LEVEL 1 PERTINENT BRIEF  |  PAGE {page_number}/2",
    )
    canvas.drawRightString(
        width - 9 * mm,
        height - 16 * mm,
        "CFP-derived decision support",
    )
    canvas.setFillColor(_GREY)
    canvas.setFont("Helvetica", 5.8)
    canvas.drawCentredString(
        width / 2,
        5 * mm,
        "Verify against current approved manuals, live dispatch information, ATC instructions and PIC judgement.",
    )
    return height - 27 * mm


def _draw_level1_summary(
    canvas,
    briefing: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    gap = 2.5 * mm
    cell_width = (width - 2 * gap) / 3
    blocks = [
        (
            "FLIGHT",
            [
                f"{briefing['metrics']['aircraft']}  {briefing['registration']}",
                f"ETD {briefing['metrics']['etd']}  ETA {briefing['metrics']['eta']}",
            ],
            _BLUE,
        ),
        (
            "MASS / FUEL",
            [
                f"PZFW {briefing['masses']['pzfw']}  PLDW {briefing['masses']['pldw']}",
                f"PTOW {briefing['masses']['ptow']}",
                f"Tanks {briefing['fuel']['tanks']}  Trip {briefing['fuel']['trip']}",
            ],
            _GREEN,
        ),
        (
            "CLOCK / SCOPE",
            [
                f"Basis {briefing['metrics'].get('clock_basis') or 'ACTM only'}",
                f"NOTAM {briefing['counts']['notams']}  WX {briefing['counts']['weather']}",
            ],
            _PURPLE,
        ),
    ]
    for index, (title, lines, colour) in enumerate(blocks):
        _draw_panel(
            canvas,
            x + index * (cell_width + gap),
            y,
            cell_width,
            height,
            title,
            lines,
            colour,
            False,
            _STYLES["level1"],
        )


def _draw_level1_page(
    canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    briefing: dict[str, Any],
    page_number: int,
    width: float,
    height: float,
) -> None:
    top = _draw_level1_header(canvas, briefing, width, height, page_number)
    grouped = _findings_by_engine(findings)
    margin = 9 * mm
    gap = 3 * mm
    bottom = 11 * mm

    if page_number == 1:
        summary_height = 24 * mm
        _draw_level1_summary(
            canvas,
            briefing,
            margin,
            top - summary_height,
            width - 2 * margin,
            summary_height,
        )
        panel_top = top - summary_height - gap
        panel_titles = [
            (
                "1  MEL / CDL / CDDL",
                _level1_section_lines(grouped, ("mel", "cddl"), finding_limit=6, detail_limit=2)
                + _note_lines(flight, {"separate"}, 1)[:2],
                _AMBER,
            ),
            (
                "2  PERFORMANCE / FUEL / BOBCAT",
                _level1_section_lines(grouped, ("page1", "performance", "bobcat", "qa"), finding_limit=6, detail_limit=2),
                _NAVY,
            ),
            (
                "3  DEPARTURE AIRPORT",
                _airport_lines(briefing["departure"])
                + _level1_section_lines(
                    grouped,
                    ("notam",),
                    finding_limit=3,
                    detail_limit=1,
                )
                + _note_lines(flight, {"departure"}, 1),
                _BLUE,
            ),
            (
                "4  DESTINATION AIRPORT / ALTERNATES / NOTAM",
                _airport_lines(briefing["destination"])
                + _level1_section_lines(grouped, ("weather", "notam"), finding_limit=5, detail_limit=1)
                + _note_lines(flight, {"destination"}, 1),
                _GREEN,
            ),
        ]
    else:
        panel_top = top
        review_lines = [f"Manual review: {warning}" for warning in warnings[:3]]
        panel_titles = [
            (
                "5  FIR / COMMUNICATIONS",
                _level1_section_lines(grouped, ("communications",), finding_limit=7, detail_limit=2)
                + _note_lines(flight, {"communications"}, 1),
                _PURPLE,
            ),
            (
                "6  TERRAIN / VWS / DEPRESSURISATION",
                _level1_section_lines(grouped, ("depressurisation", "terrain", "vws"), finding_limit=7, detail_limit=2)
                + review_lines,
                _RED,
            ),
            (
                "7  EDTO / ENROUTE WEATHER",
                _level1_section_lines(grouped, ("edto", "weather"), finding_limit=7, detail_limit=2),
                _GREEN,
            ),
            (
                "8  ACTM / CALCULATED UTC TIMELINE",
                _level1_section_lines(grouped, ("actual_timing", "timeline"), finding_limit=8, detail_limit=2),
                _NAVY,
            ),
        ]

    panel_height = (panel_top - bottom - 3 * gap) / 4
    for index, (title, lines, colour) in enumerate(panel_titles):
        y = panel_top - (index + 1) * panel_height - index * gap
        _draw_panel(
            canvas,
            margin,
            y,
            width - 2 * margin,
            panel_height,
            title,
            lines,
            colour,
            False,
            _STYLES["level1"],
        )


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
        pagesize=LEVEL1_PAGE_SIZE,
        leftMargin=4 * mm,
        rightMargin=4 * mm,
        topMargin=4 * mm,
        bottomMargin=4 * mm,
    )
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="visual")
    document.addPageTemplates([PageTemplate(id="visual", frames=[frame])])
    story = [
        _FullPageFlowable(
            lambda canvas, width, height: _draw_level1_page(
                canvas,
                flight,
                findings,
                warnings,
                briefing,
                1,
                width,
                height,
            )
        ),
        PageBreak(),
        _FullPageFlowable(
            lambda canvas, width, height: _draw_level1_page(
                canvas,
                flight,
                findings,
                warnings,
                briefing,
                2,
                width,
                height,
            )
        ),
    ]
    document.build(story)


__all__ = [
    "PAGE_SIZE",
    "LEVEL1_PAGE_SIZE",
    "operational_detail_flowable",
    "render_level1_visual",
    "route_detail_flowable",
    "visual_cover_flowable",
]
