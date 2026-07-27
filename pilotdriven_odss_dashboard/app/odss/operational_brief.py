from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph

from .briefing import build_briefing_view, draw_route_map_pdf
from .constants import edto_sectors, format_actm
from .engines import detect_terrain_events
from .pilot_briefing import (
    prepare_pilot_findings,
    select_concise_weather,
    select_pertinent_notams,
)
from .pertinent_brief import (
    _draw_route_evidence_chart,
    _route_window_points,
    _sector_etp_markers,
)
from .report_facts import (
    actm_utc_label,
    build_route_gate_rows,
    select_route_gate_rows,
)


PAGE_SIZE = landscape(A4)

_BACKGROUND = colors.HexColor("#061421")
_PANEL = colors.HexColor("#10253A")
_PANEL_ALT = colors.HexColor("#0C2032")
_LINE = colors.HexColor("#31506D")
_TEXT = colors.HexColor("#E9F2FA")
_MUTED = colors.HexColor("#9AAFC1")
_HEADER = colors.HexColor("#7E94AA")
_CYAN = colors.HexColor("#32A8DC")
_BLUE = colors.HexColor("#2F80ED")
_VIOLET = colors.HexColor("#8755ED")
_GREEN = colors.HexColor("#38B77D")
_AMBER = colors.HexColor("#F3A51A")
_TEAL = colors.HexColor("#39B8B6")
_ORANGE = colors.HexColor("#E88B20")
_RED = colors.HexColor("#D84A5B")

_STYLES = getSampleStyleSheet()
_BODY = ParagraphStyle(
    "Operational body",
    parent=_STYLES["BodyText"],
    fontName="Helvetica",
    fontSize=6.2,
    leading=8.0,
    textColor=_TEXT,
    spaceBefore=0,
    spaceAfter=0,
)
_BODY_SMALL = ParagraphStyle(
    "Operational body small",
    parent=_BODY,
    fontSize=5.4,
    leading=6.7,
)

_INTERNAL_DOCUMENT_NAME = re.compile(
    r"^(?:cfp|ofp|upload|document)[_-][a-f0-9]{12,}.*\.pdf$",
    re.IGNORECASE,
)


def _text(value: Any, fallback: str = "Not available") -> str:
    normalized = " ".join(str(value or "").split())
    return normalized or fallback


def _pilot_text(value: Any, fallback: str = "Not available") -> str:
    text = _text(value, fallback)
    replacements = {
        "\u2192": "->",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2022": "/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _display_document_title(reference: dict[str, Any]) -> str:
    title = _text(
        reference.get("display_title") or reference.get("document_title"),
        "",
    )
    if not title:
        provider = _text(reference.get("provider"), "Approved source")
        return provider.replace("-", " ").title()
    if _INTERNAL_DOCUMENT_NAME.match(title):
        return "Uploaded company CFP"
    return title


def _page_label(values: Iterable[Any]) -> str:
    pages = sorted(
        {
            int(value)
            for value in values
            if isinstance(value, int) and value > 0
        }
    )
    if not pages:
        return ""
    ranges: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    prefix = "p." if len(pages) == 1 else "pp."
    return f"{prefix} {', '.join(ranges)}"


def _source_label(finding: dict[str, Any]) -> str:
    references = [
        item
        for item in ((finding.get("data") or {}).get("source_references") or [])
        if isinstance(item, dict)
    ]
    if not references:
        pages = [
            value
            for value in (
                (finding.get("data") or {}).get("source_page"),
                (finding.get("data") or {}).get("page"),
            )
            if isinstance(value, int)
        ]
        return (
            f"Evidence: Uploaded company CFP; {_page_label(pages)}."
            if pages
            else "Evidence: Uploaded company CFP."
        )
    reference = references[0]
    parts = [_display_document_title(reference)]
    if reference.get("revision"):
        parts.append(f"revision {_pilot_text(reference['revision'])}")
    if reference.get("section"):
        parts.append(_pilot_text(reference["section"]))
    pages = _page_label(reference.get("pages") or [])
    if pages:
        parts.append(pages)
    if reference.get("retrieved_at_utc"):
        parts.append(f"retrieved {_utc(reference['retrieved_at_utc'])}")
    validity = [
        value
        for value in (
            reference.get("valid_from_utc"),
            reference.get("valid_to_utc"),
        )
        if value
    ]
    if validity:
        parts.append(f"valid {' to '.join(_utc(value) for value in validity)}")
    if reference.get("availability_status") == "source-incomplete":
        parts.append("coverage incomplete - review required")
    elif reference.get("availability_status") == "controlled-source-not-mounted":
        parts.append("approved source unavailable - review required")
    return f"Evidence: {'; '.join(part for part in parts if part)}."


def _compact_source_label(finding: dict[str, Any]) -> str:
    data = finding.get("data") or {}
    references = [
        item
        for item in (data.get("source_references") or [])
        if isinstance(item, dict)
    ]
    labels: list[str] = []
    for reference in references:
        source_type = str(reference.get("source_type") or "")
        if source_type == "uploaded_cfp":
            page = _page_label(reference.get("pages") or [])
            label = f"CFP {page}".strip()
        else:
            label = _text(
                reference.get("provider")
                or reference.get("display_title")
                or reference.get("document_title"),
                "Approved source",
            ).replace("-", " ")
            validity = [
                value
                for value in (
                    reference.get("valid_from_utc"),
                    reference.get("valid_to_utc"),
                )
                if value
            ]
            if validity:
                label += " / valid " + " to ".join(
                    _utc(value) for value in validity
                )
        status = str(reference.get("availability_status") or "")
        if status in {"source-incomplete", "controlled-source-not-mounted"}:
            label += " / review required"
        if label not in labels:
            labels.append(label)
        if len(labels) == 2:
            break
    if labels:
        return " / ".join(labels)
    page = data.get("source_page") or data.get("page")
    return f"CFP p. {page}" if isinstance(page, int) and page > 0 else "Uploaded CFP"


def _utc(value: Any) -> str:
    text = _text(value, "")
    if not text:
        return "Not available"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _pilot_text(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d %b %Y %H%MZ").upper()


def _clip(value: Any, width: float, *, font: str = "Helvetica", size: float = 5.6) -> str:
    text = _pilot_text(value)
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    suffix = "..."
    while text and pdfmetrics.stringWidth(text + suffix, font, size) > width:
        text = text[:-1]
    return text.rstrip() + suffix


def _wrap(value: Any, width: float, *, font: str = "Helvetica", size: float = 5.6) -> list[str]:
    words = _pilot_text(value).split()
    if not words:
        return ["Not available"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped(
    canvas: pdf_canvas.Canvas,
    value: Any,
    x: float,
    y_top: float,
    width: float,
    height: float,
    *,
    size: float = 6.2,
    leading: float = 8.0,
    colour: colors.Color = _TEXT,
    bold: bool = False,
) -> None:
    style = ParagraphStyle(
        "Operational dynamic",
        parent=_BODY,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading,
        textColor=colour,
    )
    paragraph = Paragraph(escape(_pilot_text(value)), style)
    _, required = paragraph.wrap(width, height)
    paragraph.drawOn(canvas, x, y_top - min(required, height))


def _draw_background(canvas: pdf_canvas.Canvas) -> None:
    width, height = PAGE_SIZE
    canvas.setFillColor(_BACKGROUND)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)


def _draw_header(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    briefing: dict[str, Any],
    *,
    label: str,
    page_number: int,
) -> float:
    width, height = PAGE_SIZE
    margin = 7 * mm
    top = height - 6 * mm

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(margin, top - 4 * mm, "PILOT")
    pilot_width = pdfmetrics.stringWidth("PILOT", "Helvetica-Bold", 12)
    canvas.setFillColor(_CYAN)
    canvas.drawString(margin + pilot_width, top - 4 * mm, "DRIVEN")

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(62 * mm, top - 3.2 * mm, _pilot_text(briefing.get("flight_number")))
    canvas.setFont("Helvetica-Bold", 10.2)
    canvas.drawString(62 * mm, top - 9.4 * mm, _pilot_text(briefing.get("route_label")))

    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(
        160 * mm,
        top - 2.8 * mm,
        (
            f"{_pilot_text(briefing.get('flight_date'))} UTC · "
            f"{_pilot_text(briefing['metrics'].get('clock_basis'))}"
            if briefing["metrics"].get("atot")
            else f"{_pilot_text(briefing.get('flight_date'))} UTC"
        ),
    )
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 6.2)
    canvas.drawString(
        160 * mm,
        top - 7.2 * mm,
        f"DEP {_pilot_text(briefing['metrics'].get('etd'))} -> ARR {_pilot_text(briefing['metrics'].get('eta'))}",
    )
    canvas.drawString(
        160 * mm,
        top - 11.1 * mm,
        (
            f"Aircraft {_pilot_text(briefing['metrics'].get('aircraft'))} · "
            f"ATOT {_pilot_text(briefing['metrics'].get('atot'))}"
            if briefing["metrics"].get("atot")
            else f"Aircraft {_pilot_text(briefing['metrics'].get('aircraft'))}"
        ),
    )

    pill_w = 57 * mm
    pill_h = 6.2 * mm
    pill_x = width - margin - pill_w
    pill_y = top - 7.2 * mm
    canvas.setStrokeColor(_CYAN)
    canvas.setLineWidth(0.8)
    canvas.roundRect(pill_x, pill_y, pill_w, pill_h, 7, fill=0, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica", 6.3)
    canvas.drawCentredString(pill_x + pill_w / 2, pill_y + 2.1 * mm, label)

    line_y = top - 16 * mm
    canvas.setStrokeColor(_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(margin, line_y, width - margin, line_y)

    footer_y = 5.4 * mm
    canvas.line(margin, footer_y + 2.6 * mm, width - margin, footer_y + 2.6 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 5.2)
    canvas.drawString(
        margin,
        footer_y,
        (
            f"PILOTDRIVEN ODSS | {_pilot_text(briefing.get('flight_number'))} | "
            f"Uploaded company CFP | {_pilot_text(briefing.get('flight_date'))}"
        ),
    )
    canvas.drawRightString(
        width - margin,
        footer_y,
        f"Page {page_number} of 7",
    )
    return line_y - 7 * mm


def _draw_title(canvas: pdf_canvas.Canvas, title: str, y: float) -> float:
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(7 * mm, y, title)
    return y - 5.5 * mm


def _panel(
    canvas: pdf_canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    title: str,
    accent: colors.Color,
    body: str | None = None,
    body_size: float = 6.2,
) -> tuple[float, float, float, float]:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.setLineWidth(0.6)
    canvas.roundRect(x, y, width, height, 7, fill=1, stroke=1)
    bar_h = 7 * mm
    canvas.setFillColor(accent)
    canvas.roundRect(x, y + height - bar_h, width, bar_h, 7, fill=1, stroke=0)
    canvas.rect(x, y + height - bar_h, width, bar_h / 2, fill=1, stroke=0)
    canvas.setFillColor(_BACKGROUND)
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(x + 3 * mm, y + height - 4.6 * mm, _clip(title, width - 6 * mm, font="Helvetica-Bold", size=6.5))
    body_x = x + 3 * mm
    body_y = y + 3 * mm
    body_w = width - 6 * mm
    body_h = height - bar_h - 5 * mm
    if body:
        _draw_wrapped(
            canvas,
            body,
            body_x,
            body_y + body_h,
            body_w,
            body_h,
            size=body_size,
            leading=body_size + 1.8,
        )
    return body_x, body_y, body_w, body_h


def _metric_cards(
    canvas: pdf_canvas.Canvas,
    items: Sequence[tuple[str, str, str]],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    gap = 2.2 * mm
    cell_w = (width - gap * (len(items) - 1)) / max(1, len(items))
    for index, (label, value, note) in enumerate(items):
        cx = x + index * (cell_w + gap)
        canvas.setFillColor(_PANEL)
        canvas.setStrokeColor(_LINE)
        canvas.roundRect(cx, y, cell_w, height, 7, fill=1, stroke=1)
        canvas.setFillColor(_GREEN if index % 3 == 0 else _CYAN if index % 3 == 1 else _AMBER)
        canvas.rect(cx, y + height - 1.2 * mm, cell_w, 1.2 * mm, fill=1, stroke=0)
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica-Bold", 5.8)
        canvas.drawString(cx + 3 * mm, y + height - 5.3 * mm, _clip(label, cell_w - 6 * mm, font="Helvetica-Bold", size=5.8))
        canvas.setFillColor(_TEXT)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(cx + 3 * mm, y + height - 11.8 * mm, _clip(value, cell_w - 6 * mm, font="Helvetica-Bold", size=13))
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 5.1)
        canvas.drawString(cx + 3 * mm, y + 3 * mm, _clip(note, cell_w - 6 * mm, size=5.1))


def _strip(
    canvas: pdf_canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    body: str,
    accent: colors.Color,
) -> None:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 7, fill=1, stroke=1)
    title_w = 38 * mm
    canvas.setFillColor(accent)
    canvas.setFont("Helvetica-Bold", 5.6)
    canvas.drawString(
        x + 3 * mm,
        y + height / 2 - 1.8,
        _clip(title, title_w - 5 * mm, font="Helvetica-Bold", size=5.6),
    )
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica", 5.4)
    canvas.drawString(
        x + title_w,
        y + height / 2 - 1.8,
        _clip(body, width - title_w - 3 * mm, size=5.4),
    )


def _draw_table(
    canvas: pdf_canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    columns: Sequence[tuple[str, float]],
    rows: Sequence[Sequence[Any]],
    accent: colors.Color = _HEADER,
    empty_text: str = "No applicable item was extracted.",
    max_rows: int | None = None,
) -> int:
    data = list(rows)
    if max_rows is not None:
        data = data[:max_rows]
    if not data:
        data = [[empty_text] + [""] * (len(columns) - 1)]

    header_h = 8.5 * mm
    available = height - header_h
    row_h = min(10 * mm, available / max(1, len(data)))
    if row_h < 6.5 * mm:
        visible_count = max(1, int(available // (6.5 * mm)))
        data = data[:visible_count]
        row_h = available / max(1, len(data))

    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.rect(x, y, width, height, fill=1, stroke=1)
    canvas.setFillColor(accent)
    canvas.rect(x, y + height - header_h, width, header_h, fill=1, stroke=0)

    column_x = x
    widths = [width * fraction for _, fraction in columns]
    for index, ((label, _), column_width) in enumerate(zip(columns, widths)):
        canvas.setFillColor(_BACKGROUND)
        canvas.setFont("Helvetica-Bold", 5.5)
        canvas.drawString(
            column_x + 2 * mm,
            y + height - 5.4 * mm,
            _clip(label, column_width - 4 * mm, font="Helvetica-Bold", size=5.5),
        )
        if index:
            canvas.setStrokeColor(_LINE)
            canvas.line(column_x, y, column_x, y + height)
        column_x += column_width

    top = y + height - header_h
    canvas.setFont("Helvetica", 5.3)
    for row_index, row in enumerate(data):
        row_top = top - row_index * row_h
        row_bottom = row_top - row_h
        if row_index % 2:
            canvas.setFillColor(_PANEL_ALT)
            canvas.rect(x, row_bottom, width, row_h, fill=1, stroke=0)
        canvas.setStrokeColor(_LINE)
        canvas.line(x, row_bottom, x + width, row_bottom)
        column_x = x
        for column_index, column_width in enumerate(widths):
            value = row[column_index] if column_index < len(row) else ""
            inner_w = column_width - 4 * mm
            lines = _wrap(
                value,
                inner_w,
                font="Helvetica-Bold" if column_index == 0 else "Helvetica",
                size=5.2,
            )
            max_lines = max(1, int((row_h - 2.4 * mm) // 5.9))
            lines = lines[:max_lines]
            if len(_pilot_text(value)) and len(lines) == max_lines:
                lines[-1] = _clip(
                    lines[-1],
                    inner_w,
                    font="Helvetica-Bold" if column_index == 0 else "Helvetica",
                    size=5.2,
                )
            canvas.setFillColor(_TEXT if column_index == 0 else _MUTED)
            canvas.setFont(
                "Helvetica-Bold" if column_index == 0 else "Helvetica",
                5.2,
            )
            line_y = row_top - 3.6 * mm
            for line in lines:
                canvas.drawString(column_x + 2 * mm, line_y, line)
                line_y -= 2.2 * mm
            column_x += column_width
    return len(data)


def _grouped(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[str(finding.get("engine") or "other")].append(finding)
    return grouped


def _personal_notes(flight: dict[str, Any], placement: str) -> list[str]:
    return [
        _text(note.get("note_text"), "")
        for note in (flight.get("personal_notes") or [])
        if note.get("placement") == placement
        and note.get("include_level2")
        and _text(note.get("note_text"), "")
    ]


def _personal_note_row(
    flight: dict[str, Any],
    placement: str,
    label: str,
) -> list[str] | None:
    notes = _personal_notes(flight, placement)
    if not notes:
        return None
    return [
        "PERSONAL NOTE",
        " / ".join(notes),
        (
            f"{label}; pilot-entered content, not extracted, validated "
            "or endorsed."
        ),
    ]


def _weather_summary(finding: dict[str, Any]) -> str:
    data = finding.get("data") or {}
    phase = _text(data.get("phase"), "Flight phase")
    location = _text(data.get("location"), "")
    window = _text(data.get("utc_window"), "time unresolved")
    mechanism = _text(data.get("mechanism"), _text(finding.get("summary")))
    effect = _text(data.get("flight_effect"), "Pilot review required.")
    context = " / ".join(part for part in (phase, location, window) if part)
    return f"{context}: {mechanism}. {effect}"


def _finding_summary(finding: dict[str, Any]) -> str:
    if finding.get("engine") == "weather":
        return _weather_summary(finding)
    return _pilot_text(finding.get("summary"))


def _top_findings(
    findings: list[dict[str, Any]],
    *,
    limit: int,
    excluded: set[str] | None = None,
) -> list[dict[str, Any]]:
    rank = {"critical": 0, "warning": 1, "unknown": 2}
    excluded = excluded or set()
    return sorted(
        [
            item
            for item in findings
            if item.get("engine") not in excluded
            and item.get("severity") in rank
        ],
        key=lambda item: (
            rank.get(str(item.get("severity")), 4),
            _pilot_text(item.get("title")),
        ),
    )[:limit]


def _notam_rows(findings: list[dict[str, Any]]) -> list[list[str]]:
    grouped_rows: dict[
        tuple[str, str, str, str],
        dict[str, Any],
    ] = {}
    for item in select_pertinent_notams(findings, limit=24):
        data = item.get("data") or {}
        role = _text(data.get("role"), "Flight")
        station = _text(
            data.get("location")
            or data.get("icao")
            or data.get("station"),
            role,
        )
        notam_id = _text(
            data.get("notam_id")
            or data.get("reference")
            or data.get("id"),
            "",
        )
        if not notam_id:
            match = re.search(r"\b[A-Z]\d{3,5}/\d{2}\b", _text(item.get("title"), ""))
            notam_id = match.group(0) if match else "CFP NOTAM"
        condition = _finding_summary(item)
        window = _text(
            data.get("operating_window")
            or data.get("utc_window")
            or data.get("schedule"),
            "",
        )
        if not window:
            window = _brief_utc_window(
                data.get("window_start_utc"),
                data.get("window_end_utc"),
            )
        applicability = _notam_flight_effect(item, role)
        key = (
            station.upper(),
            " ".join(condition.lower().split()),
            " ".join(window.upper().split()),
            " ".join(applicability.lower().split()),
        )
        row = grouped_rows.setdefault(
            key,
            {
                "station": station,
                "ids": [],
                "sources": [],
                "condition": condition,
                "window": window,
                "effect": applicability,
            },
        )
        if notam_id not in row["ids"]:
            row["ids"].append(notam_id)
        source = _compact_source_label(item)
        if source not in row["sources"]:
            row["sources"].append(source)

    rows: list[list[str]] = []
    for row in grouped_rows.values():
        identifiers = list(row["ids"])
        reference = " + ".join(identifiers[:3])
        if len(identifiers) > 3:
            reference += f" + {len(identifiers) - 3} more"
        sources = " / ".join(row["sources"][:2])
        rows.append([
            row["station"],
            f"{reference} / {sources}",
            row["condition"],
            row["window"],
            row["effect"],
        ])
    return rows


def _brief_utc_window(start_value: Any, end_value: Any) -> str:
    def parse(value: Any) -> datetime | None:
        text = _text(value, "")
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    start = parse(start_value)
    end = parse(end_value)
    if start is None or end is None:
        return "Applicable flight window"
    if start.date() == end.date():
        return (
            f"{start.strftime('%d %b').upper()} "
            f"{start.strftime('%H%M')}Z-{end.strftime('%H%M')}Z"
        )
    return (
        f"{start.strftime('%d %b %H%M').upper()}Z-"
        f"{end.strftime('%d %b %H%M').upper()}Z"
    )


def _notam_flight_effect(finding: dict[str, Any], role: str) -> str:
    data = finding.get("data") or {}
    explicit = _text(data.get("flight_effect") or data.get("effect"), "")
    if explicit:
        return explicit

    if str(data.get("applicability") or "").lower() in {
        "review",
        "review_required",
        "unresolved",
    }:
        return "Restriction unresolved - pilot review required."

    pertinence_kind = str(data.get("pertinence_kind") or "").lower()
    category = str(data.get("category") or "").upper()
    if pertinence_kind == "airport_closure":
        return "Airport availability affected."
    if pertinence_kind == "approach_navaid_closure" or category in {
        "APPROACH",
        "NAVAID",
    }:
        return "Approach or navigation availability affected."
    if pertinence_kind in {"surface_restriction", "taxiway_closure"} or category in {
        "TAXIWAY",
        "APRON",
    }:
        return "Taxi routing affected."
    if pertinence_kind == "runway_closure" or category == "RUNWAY":
        return "Runway availability affected."
    return f"Applicable to the {role.lower()} window."


def _finding_rows(items: list[dict[str, Any]], *, limit: int = 8) -> list[list[str]]:
    return [
        [
            _pilot_text(item.get("title"), "Operational item"),
            _finding_summary(item),
            _source_label(item),
        ]
        for item in items[:limit]
    ]


def _edto_sector_airports(sector: dict[str, Any]) -> str:
    airports: list[str] = []
    for value in sector.get("airports") or []:
        airport = _text(value, "")
        if airport and airport not in airports:
            airports.append(airport)
    for etp in sector.get("etps") or []:
        if not isinstance(etp, dict):
            continue
        for value in etp.get("airports") or []:
            airport = _text(value, "")
            if airport and airport not in airports:
                airports.append(airport)
    return " / ".join(airports) or "CFP alternates"


def _communications_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items[:10]:
        data = item.get("data") or {}
        rows.append([
            _text(data.get("fir") or data.get("location"), _text(item.get("title"))),
            _text(data.get("basis") or data.get("waypoint"), "CFP route"),
            _text(data.get("actm") or data.get("utc_window"), "Time review required"),
            _finding_summary(item),
        ])
    return rows


def _weather_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    clear: list[str] = []
    for item in select_concise_weather(items):
        data = item.get("data") or {}
        phase = _text(data.get("phase"), "Flight")
        location = _text(data.get("location"), "")
        window = _text(data.get("utc_window"), "Window unresolved")
        status = _text(data.get("window_status"), "review_required")
        if status == "no_significant_overlap":
            clear.append(
                " / ".join(part for part in (phase, location, window) if part)
            )
            continue
        rows.append(
            [
                " / ".join(part for part in (phase, location) if part),
                window,
                _text(data.get("mechanism"), "Not safely classified"),
                _text(data.get("flight_effect"), "Pilot review required."),
                _compact_source_label(item),
            ]
        )
    if clear:
        rows.append(
            [
                "Checked windows",
                "; ".join(clear[:4]),
                "No significant CFP forecast group overlapped.",
                "Confirm the latest operational weather before use.",
                "Uploaded CFP",
            ]
        )
    return rows


def _advisory_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        data = item.get("data") or {}
        status = _text(data.get("status"), "review_required").replace("_", " ")
        reason_codes = [
            _pilot_text(value).replace("_", " ")
            for value in (data.get("reason_codes") or [])
        ]
        rows.append(
            [
                _pilot_text(item.get("title"), "Advisory review"),
                status.upper(),
                _finding_summary(item),
                "; ".join(reason_codes[:2]) or "Coverage review required",
                _compact_source_label(item),
            ]
        )
    return rows


def _promotion_rows(findings: list[dict[str, Any]]) -> list[list[str]]:
    categories: Sequence[tuple[str, set[str]]] = (
        ("AIRPORT / NOTAM", {"notam"}),
        ("PERFORMANCE", {"performance", "page1"}),
        ("WEATHER", {"weather"}),
        ("EDTO", {"edto"}),
        ("TERRAIN / PROFILE", {"terrain", "vws", "depressurisation"}),
        ("COMMUNICATIONS", {"communications", "bobcat"}),
        ("ADVISORIES", {"vaa", "tropical_cyclone"}),
    )
    rank = {"critical": 0, "warning": 1, "unknown": 2, "information": 3}
    rows: list[list[str]] = []
    for label, engines in categories:
        items = [
            item
            for item in findings
            if str(item.get("engine") or "") in engines
            and item.get("severity") in rank
        ]
        if not items:
            continue
        items.sort(key=lambda item: rank.get(str(item.get("severity")), 4))
        promoted = [
            item
            for item in items
            if item.get("severity") in {"critical", "warning"}
        ]
        review = [
            item
            for item in items
            if item.get("severity") == "unknown"
        ]
        brief = "LEVEL 1" if promoted else "LEVEL 2 REVIEW"
        counts: list[str] = []
        if promoted:
            counts.append(f"{len(promoted)} pertinent")
        if review:
            counts.append(f"{len(review)} unresolved")
        rationale = (
            f"{', '.join(counts) or f'{len(items)} checked'}; "
            f"see the dedicated Level 2 section."
        )
        rows.append(
            [
                label,
                brief,
                rationale,
                _source_label(items[0]),
            ]
        )
    return rows


def _overview_rows(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[list[str]]:
    grouped = _grouped(findings)
    route_gates = build_route_gate_rows(flight)
    terrain_windows = detect_terrain_events(flight.get("route_waypoints") or [])
    rows = [
        [
            "FLIGHT-WINDOW NOTAMS",
            f"{len(select_pertinent_notams(grouped.get('notam', []), limit=24))} pertinent records",
            "Page 3",
            "Uploaded CFP",
        ],
        [
            "EDTO",
            f"{len(edto_sectors(flight.get('edto') or {}))} parsed sectors",
            "Page 4",
            "Uploaded CFP",
        ],
        [
            "OCEANIC / FIR",
            f"{len(route_gates)} parsed route gates",
            "Page 5",
            "CFP route",
        ],
        [
            "TERRAIN / PROFILE",
            f"{len(terrain_windows)} exposure windows",
            "Page 6",
            "CFP MSA points",
        ],
        [
            "WEATHER",
            f"{len(grouped.get('weather', []))} checked flight windows",
            "Page 7",
            "CFP / official sources",
        ],
        [
            "VAAC / TC",
            (
                f"{len(grouped.get('vaa', [])) + len(grouped.get('tropical_cyclone', []))} "
                "coverage results"
            ),
            "Page 7",
            "Approved advisory sources",
        ],
    ]
    return rows


def _terrain_rows(
    flight: dict[str, Any],
    terrain_findings: list[dict[str, Any]],
    depress_findings: list[dict[str, Any]],
) -> list[list[str]]:
    rows: list[list[str]] = []
    profiles = depress_findings
    for index, event in enumerate(detect_terrain_events(flight.get("route_waypoints") or []), start=1):
        first = event.get("first_high") or {}
        last = event.get("last_high") or first
        maximum = event.get("maximum") or {}
        start = first.get("actm_minutes")
        end = last.get("actm_minutes")
        exposure = (
            f"{_text(first.get('name'), 'start')} - "
            f"{_text(last.get('name'), 'end')}"
        )
        max_msa = maximum.get("msa_hundreds_ft")
        maximum_label = (
            f"{int(max_msa):03d}{'*' if maximum.get('msa_asterisk') else ''} "
            f"{_text(maximum.get('name'), '')}"
            if max_msa is not None
            else "Not resolved"
        )
        profile = (
            _finding_summary(profiles[index - 1])
            if index - 1 < len(profiles)
            else "Not confirmed"
        )
        rows.append([
            str(index),
            f"{format_actm(start)}-{format_actm(end)}",
            exposure,
            maximum_label,
            profile,
        ])
    if not rows and terrain_findings:
        rows = [
            [
                str(index),
                "Time review required",
                _pilot_text(item.get("title")),
                _finding_summary(item),
                (
                    _finding_summary(profiles[index - 1])
                    if index - 1 < len(profiles)
                    else "Not confirmed"
                ),
            ]
            for index, item in enumerate(terrain_findings[:6], start=1)
        ]
    return rows


def _draw_route_panel(
    canvas: pdf_canvas.Canvas,
    route_map: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
) -> None:
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 7, fill=1, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(x + 3 * mm, y + height - 5 * mm, _clip(title, width - 6 * mm, font="Helvetica-Bold", size=6.5))
    draw_route_map_pdf(
        canvas,
        route_map,
        x + 2 * mm,
        y + 2 * mm,
        width - 4 * mm,
        height - 9 * mm,
    )


def _draw_terrain_profile(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    points = [
        item
        for item in (flight.get("route_waypoints") or [])
        if item.get("actm_minutes") is not None
        and item.get("msa_hundreds_ft") is not None
    ]
    canvas.setFillColor(_PANEL)
    canvas.setStrokeColor(_LINE)
    canvas.roundRect(x, y, width, height, 7, fill=1, stroke=1)
    canvas.setFillColor(_TEXT)
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(x + 3 * mm, y + height - 5 * mm, "CFP MSA PROFILE")
    chart_x = x + 7 * mm
    chart_y = y + 7 * mm
    chart_w = width - 12 * mm
    chart_h = height - 17 * mm
    canvas.setStrokeColor(_LINE)
    canvas.line(chart_x, chart_y, chart_x, chart_y + chart_h)
    canvas.line(chart_x, chart_y, chart_x + chart_w, chart_y)
    if not points:
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 6)
        canvas.drawCentredString(x + width / 2, y + height / 2, "No CFP MSA points available.")
        return
    min_t = min(int(item["actm_minutes"]) for item in points)
    max_t = max(int(item["actm_minutes"]) for item in points)
    max_msa = max(int(item["msa_hundreds_ft"]) for item in points)
    scale_t = max(1, max_t - min_t)
    scale_msa = max(1, max_msa)
    previous: tuple[float, float] | None = None
    for point in points:
        px = chart_x + ((int(point["actm_minutes"]) - min_t) / scale_t) * chart_w
        py = chart_y + (int(point["msa_hundreds_ft"]) / scale_msa) * chart_h
        if previous:
            canvas.setStrokeColor(_TEXT)
            canvas.setLineWidth(0.7)
            canvas.line(previous[0], previous[1], px, py)
        colour = _RED if int(point["msa_hundreds_ft"]) > 150 else _AMBER if int(point["msa_hundreds_ft"]) > 100 else _CYAN
        canvas.setFillColor(colour)
        canvas.circle(px, py, 1.7, fill=1, stroke=0)
        if point.get("msa_asterisk") or int(point["msa_hundreds_ft"]) > 100:
            canvas.setFillColor(_TEXT)
            canvas.setFont("Helvetica-Bold", 4.5)
            canvas.drawCentredString(
                px,
                py + 2.3 * mm,
                _clip(
                    f"{_text(point.get('name'), '')} {int(point['msa_hundreds_ft']):03d}{'*' if point.get('msa_asterisk') else ''}",
                    22 * mm,
                    font="Helvetica-Bold",
                    size=4.5,
                ),
            )
        previous = (px, py)


def _page_one(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - OPERATIONAL BRIEF", page_number=1)
    top = _draw_title(canvas, "ANALYSIS OVERVIEW", top)
    margin = 7 * mm
    gap = 3 * mm
    left_w = 185 * mm
    right_x = margin + left_w + gap
    right_w = PAGE_SIZE[0] - margin - right_x
    map_h = 82 * mm
    map_y = top - map_h
    _draw_route_panel(
        canvas,
        briefing["route_map"],
        margin,
        map_y,
        left_w,
        map_h,
        f"{briefing['flight_number']} CFP ROUTE",
    )
    body_x, body_y, body_w, body_h = _panel(
        canvas,
        right_x,
        map_y,
        right_w,
        map_h,
        title="FLIGHT / MASS / FUEL",
        accent=_HEADER,
    )
    metrics = [
        ("DISTANCE", briefing["metrics"]["distance"]),
        ("EET", briefing["metrics"]["eet"]),
        ("LEVELS", briefing["metrics"]["cruise"]),
        ("PZFW", briefing["masses"]["pzfw"]),
        ("PTOW", briefing["masses"]["ptow"]),
        ("PLDW", briefing["masses"]["pldw"]),
        ("FUEL", briefing["fuel"]["tanks"]),
        ("TRIP", briefing["fuel"]["trip"]),
        ("DEST", briefing["fuel"]["destination"]),
    ]
    row_h = body_h / len(metrics)
    for index, (label, value) in enumerate(metrics):
        y = body_y + body_h - (index + 0.7) * row_h
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 5.7)
        canvas.drawString(body_x, y, label)
        canvas.setFillColor(_TEXT)
        canvas.setFont("Helvetica-Bold", 5.9)
        canvas.drawRightString(body_x + body_w, y, _clip(value, body_w * 0.58, font="Helvetica-Bold", size=5.9))

    table_y = 18 * mm
    table_h = map_y - table_y - gap
    rows = _overview_rows(flight, findings)
    _draw_table(
        canvas,
        x=margin,
        y=table_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=table_h,
        columns=(
            ("ANALYSIS AREA", 0.22),
            ("COVERAGE", 0.43),
            ("CONTINUE", 0.10),
            ("SOURCE BASIS", 0.25),
        ),
        rows=rows,
        max_rows=6,
    )


def _page_two(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - PERFORMANCE / AIRPORTS", page_number=2)
    top = _draw_title(canvas, "PERFORMANCE, FUEL AND AIRPORT BASIS", top)
    margin = 7 * mm
    gap = 3 * mm
    cards_h = 20 * mm
    cards_y = top - cards_h
    performance = flight.get("performance") or {}
    masses = flight.get("masses") or {}
    fuel = flight.get("fuel") or {}
    ptow = masses.get("planned_takeoff_weight_kg")

    def _mass(value: Any) -> str:
        return f"{int(value):,} kg" if value is not None else "Not parsed"

    def _margin(value: Any, comparison: Any) -> str:
        if value is None or comparison is None:
            return "Margin review required"
        return f"{int(value) - int(comparison):+,} kg to PTOW"

    _metric_cards(
        canvas,
        [
            (
                "RTOW (PERF)",
                _mass(performance.get("obstacle_rtow_kg")),
                _margin(performance.get("obstacle_rtow_kg"), ptow),
            ),
            (
                "STRUCTURAL MTOW",
                _mass(performance.get("structural_rtow_kg")),
                _margin(performance.get("structural_rtow_kg"), ptow),
            ),
            (
                "LANDING WEIGHT",
                briefing["masses"]["pldw"],
                "Planned landing weight",
            ),
            (
                "EXCESS FUEL",
                _mass(fuel.get("excess_fuel_kg")),
                "CFP excess above required fuel",
            ),
        ],
        margin,
        cards_y,
        PAGE_SIZE[0] - 2 * margin,
        cards_h,
    )
    group = _grouped(findings)
    notams = select_pertinent_notams(group.get("notam", []), limit=18)
    weather = select_concise_weather(group.get("weather", []))

    def _notam_basis(roles: set[str]) -> tuple[str, str]:
        selected = [
            item
            for item in notams
            if _text((item.get("data") or {}).get("role"), "").lower()
            in roles
        ]
        kinds: dict[str, int] = defaultdict(int)
        for item in selected:
            kind = _text(
                (item.get("data") or {}).get("pertinence_kind"),
                "other",
            ).replace("_", " ")
            kinds[kind] += 1
        summary = "; ".join(
            f"{count} {kind}"
            for kind, count in sorted(kinds.items())
        )
        return (
            summary or "No pertinent record promoted",
            f"{len(selected)} records; details on Page 3",
        )

    def _weather_basis(phases: set[str]) -> tuple[str, str]:
        selected = [
            item
            for item in weather
            if _text((item.get("data") or {}).get("phase"), "").lower()
            in phases
        ]
        statuses: dict[str, int] = defaultdict(int)
        for item in selected:
            status = _text(
                (item.get("data") or {}).get("window_status"),
                "review required",
            ).replace("_", " ")
            statuses[status] += 1
        summary = "; ".join(
            f"{count} {status}"
            for status, count in sorted(statuses.items())
        )
        return (
            summary or "Weather window unavailable",
            "Flight-time assessment on Page 7",
        )

    def _surface_basis(role: str, icao: str) -> tuple[str, str]:
        overlay = next(
            (
                item
                for item in (flight.get("surface_overlays") or [])
                if item.get("role") == role and item.get("icao") == icao
            ),
            None,
        )
        if not overlay:
            return (
                "No validated overlay attached",
                "Airport-chart review required",
            )
        count = len(overlay.get("markers") or overlay.get("features") or [])
        return (
            f"{count} validated surface marks",
            "Overlay available in airport view",
        )

    departure = _text(flight.get("departure"), "Departure")
    destination = _text(flight.get("destination"), "Destination")
    dep_weather, dep_weather_effect = _weather_basis({"departure"})
    dest_weather, dest_weather_effect = _weather_basis(
        {"destination", "destination alternate"}
    )
    dep_notam, dep_notam_effect = _notam_basis({"departure"})
    dest_notam, dest_notam_effect = _notam_basis(
        {"destination", "destination alternate"}
    )
    dep_surface, dep_surface_effect = _surface_basis("departure", departure)
    dest_surface, dest_surface_effect = _surface_basis(
        "destination",
        destination,
    )
    performance_basis = " / ".join(
        part
        for part in (
            _text(performance.get("runway_condition"), ""),
            _text(performance.get("wind"), ""),
            _text(performance.get("thrust_setting"), ""),
        )
        if part
    ) or "Performance inputs incomplete"
    alternates = ", ".join(
        _text(item.get("airport"), "")
        for item in (flight.get("alternates") or [])
        if isinstance(item, dict) and item.get("airport")
    ) or "No destination alternate parsed"
    left_rows = [
        ["RUNWAY / SID", f"{flight.get('departure_runway') or '--'} / {departure}", "Planned CFP basis"],
        ["PERFORMANCE", performance_basis, "RTOW results shown above"],
        ["WEATHER", dep_weather, dep_weather_effect],
        ["PERTINENT NOTAMS", dep_notam, dep_notam_effect],
        ["SURFACE OVERLAY", dep_surface, dep_surface_effect],
        ["SOURCE BOUNDARY", "Uploaded company CFP", "Current operational sources remain controlling"],
    ]
    right_rows = [
        ["RUNWAY / ARRIVAL", f"{flight.get('destination_runway') or '--'} / {destination}", "Planned CFP basis"],
        ["WEATHER", dest_weather, dest_weather_effect],
        ["PERTINENT NOTAMS", dest_notam, dest_notam_effect],
        ["ALTERNATES", alternates, "Suitability inputs continue on Page 4"],
        ["SURFACE OVERLAY", dest_surface, dest_surface_effect],
        ["SOURCE BOUNDARY", "Uploaded company CFP", "Current operational sources remain controlling"],
    ]
    departure_note = _personal_note_row(
        flight,
        "departure",
        "Departure airport - personal notes",
    )
    destination_note = _personal_note_row(
        flight,
        "destination",
        "Destination airport - personal notes",
    )
    if departure_note:
        left_rows.insert(-1, departure_note)
    if destination_note:
        right_rows.insert(-1, destination_note)
    content_h = 112 * mm
    content_y = cards_y - content_h - 4 * mm
    column_w = (PAGE_SIZE[0] - 2 * margin - gap) / 2
    for x, title, accent, rows in (
        (margin, f"{departure} DEPARTURE", _CYAN, left_rows),
        (margin + column_w + gap, f"{destination} / ALTERNATES", _VIOLET, right_rows),
    ):
        body_x, body_y, body_w, body_h = _panel(
            canvas,
            x,
            content_y,
            column_w,
            content_h,
            title=title,
            accent=accent,
        )
        _draw_table(
            canvas,
            x=body_x,
            y=body_y,
            width=body_w,
            height=body_h,
            columns=(("ITEM", 0.23), ("EVIDENCE", 0.49), ("EFFECT", 0.28)),
            rows=rows,
            accent=accent,
            max_rows=7,
        )


def _page_three(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - NOTAM APPLICABILITY", page_number=3)
    top = _draw_title(canvas, "FLIGHT-WINDOW NOTAM APPLICABILITY", top)
    margin = 7 * mm
    table_y = 35 * mm
    _draw_table(
        canvas,
        x=margin,
        y=table_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=top - table_y,
        columns=(
            ("STN / ROLE", 0.10),
            ("REF", 0.14),
            ("CONDITION", 0.31),
            ("WINDOW", 0.22),
            ("FLIGHT EFFECT", 0.23),
        ),
        rows=_notam_rows(_grouped(findings).get("notam", [])),
        accent=_HEADER,
        max_rows=14,
        empty_text="No pertinent time-applicable NOTAM was extracted; source coverage must still be checked.",
    )
    _strip(
        canvas,
        x=margin,
        y=18 * mm,
        width=PAGE_SIZE[0] - 2 * margin,
        height=13 * mm,
        title="PERTINENCE RULE",
        accent=_HEADER,
        body=(
            "Runway, airport, approach and navigation closures are shown first. "
            "Lower-priority applicable records remain available in audit evidence."
        ),
    )


def _page_four(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - EDTO / WEATHER", page_number=4)
    top = _draw_title(canvas, "EDTO SECTORS AND SUITABILITY INPUTS", top)
    margin = 7 * mm
    gap = 3 * mm
    map_h = 70 * mm
    map_y = top - map_h
    sectors = edto_sectors(flight.get("edto") or {})
    route_points = list((briefing.get("route_map") or {}).get("points") or [])
    if sectors:
        chart_gap = 3 * mm
        chart_count = min(2, len(sectors))
        chart_w = (
            PAGE_SIZE[0] - 2 * margin - chart_gap * (chart_count - 1)
        ) / chart_count
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
                margin + (index - 1) * (chart_w + chart_gap),
                map_y,
                chart_w,
                map_h,
                title=(
                    f"EDTO {index} | ENTRY {format_actm(start)} | "
                    f"EXIT {format_actm(end)}"
                ),
                mode="edto",
            )
    else:
        _draw_route_panel(
            canvas,
            briefing["route_map"],
            margin,
            map_y,
            PAGE_SIZE[0] - 2 * margin,
            map_h,
            f"{briefing['flight_number']} EDTO ROUTE / CFP COORDINATES",
        )
    sector_rows = [
        [
            str(index),
            f"{format_actm(item.get('entry_actm_minutes'))}-{format_actm(item.get('exit_actm_minutes'))}",
            (
                f"{actm_utc_label(flight, item.get('entry_actm_minutes')).split('/', 1)[-1].strip()}-"
                f"{actm_utc_label(flight, item.get('exit_actm_minutes')).split('/', 1)[-1].strip()}"
            ),
            _edto_sector_airports(item),
            ", ".join(format_actm(value) for value in item.get("etp_actm_minutes") or []) or "No separate ETP printed",
        ]
        for index, item in enumerate(sectors, start=1)
    ]
    group = _grouped(findings)
    weather = [
        item
        for item in select_concise_weather(group.get("weather", []))
        if _text((item.get("data") or {}).get("phase"), "").lower()
        == "edto"
    ]
    weather_by_location = {
        _text((item.get("data") or {}).get("location"), "").upper(): item
        for item in weather
    }
    edto_source_by_airport = {
        _text(item.get("airport"), "").upper(): item
        for item in (flight.get("edto") or {}).get("airports", [])
        if isinstance(item, dict)
    }
    airport_rows: list[list[str]] = []
    for item in (briefing.get("edto") or {}).get("airports", []):
        airport = _text(item.get("airport"), "Airport")
        weather_item = weather_by_location.get(airport.upper())
        source_airport = edto_source_by_airport.get(airport.upper(), {})
        airport_rows.append(
            [
                airport,
                _text(item.get("period"), "Period unresolved"),
                (
                    f"RWY {_text(item.get('runway'), '--')} / "
                    f"{_text(item.get('approach'), 'approach review')} / "
                    f"{_text(item.get('minima') or source_airport.get('minima'), 'minima review')}"
                ),
                (
                    _weather_summary(weather_item)
                    if weather_item
                    else "No complete weather result - review required."
                ),
                (
                    _compact_source_label(weather_item)
                    if weather_item
                    else "Uploaded CFP"
                ),
            ]
        )

    sector_h = 24 * mm
    sector_y = map_y - gap - sector_h
    _draw_table(
        canvas,
        x=margin,
        y=sector_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=sector_h,
        columns=(
            ("SEG", 0.06),
            ("ACTM", 0.15),
            ("UTC", 0.20),
            ("AIRPORTS", 0.28),
            ("ETP", 0.31),
        ),
        rows=sector_rows,
        accent=_GREEN,
        max_rows=2,
        empty_text="No EDTO sector was parsed from the uploaded CFP.",
    )
    airport_h = 35 * mm
    airport_y = sector_y - gap - airport_h
    _draw_table(
        canvas,
        x=margin,
        y=airport_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=airport_h,
        columns=(
            ("APT", 0.08),
            ("CHECKED PERIOD", 0.19),
            ("RUNWAY / APPROACH / MINIMA", 0.25),
            ("WEATHER RESULT", 0.32),
            ("EVIDENCE", 0.16),
        ),
        rows=airport_rows,
        accent=_GREEN,
        max_rows=4,
        empty_text="No EDTO airport suitability period was parsed.",
    )
    _strip(
        canvas,
        x=margin,
        y=18 * mm,
        width=PAGE_SIZE[0] - 2 * margin,
        height=9 * mm,
        title="EDTO DECISION INPUT",
        accent=_GREEN,
        body=(
            "CFP sector timing and checked-period weather are shown; current "
            "airport suitability, minima, NOTAMs and weather remain controlling."
        ),
    )


def _page_five(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - OCEANIC / FIR COMMUNICATIONS", page_number=5)
    top = _draw_title(canvas, "OCEANIC AND FIR COMMUNICATIONS", top)
    margin = 7 * mm
    gap = 3 * mm
    group = _grouped(findings)
    selected = select_route_gate_rows(
        build_route_gate_rows(flight),
        limit=20,
    )
    gate_rows = [
        [
            item["gate"],
            item["basis"],
            item["time"],
            f"{item['result']} {item['evidence']}",
        ]
        for item in selected
    ]
    communications_note = _personal_note_row(
        flight,
        "communications",
        "Enroute ATC / communications - personal notes",
    )
    if communications_note:
        gate_rows.append(
            [
                communications_note[0],
                "Pilot-entered",
                "",
                f"{communications_note[1]} {communications_note[2]}",
            ]
        )
    split = max(1, (len(gate_rows) + 1) // 2)
    left_rows = gate_rows[:split]
    right_rows = gate_rows[split:]
    if not right_rows:
        right_rows = [
            [
                "SOURCE STATUS",
                "Current procedures",
                "At time of use",
                "Approved communication source unavailable - review required.",
            ]
        ]
    left_w = (PAGE_SIZE[0] - 2 * margin - gap) / 2
    visible_rows = max(len(left_rows), len(right_rows))
    table_h = min(
        top - 58 * mm,
        8.5 * mm + max(1, visible_rows) * 10 * mm,
    )
    table_y = top - table_h
    _draw_table(
        canvas,
        x=margin,
        y=table_y,
        width=left_w,
        height=table_h,
        columns=(("GATE", 0.21), ("BASIS", 0.23), ("ACTM / UTC", 0.24), ("RESULT", 0.32)),
        rows=left_rows,
        accent=_CYAN,
        max_rows=10,
        empty_text="No CFP route gate was extracted.",
    )
    _draw_table(
        canvas,
        x=margin + left_w + gap,
        y=table_y,
        width=left_w,
        height=table_h,
        columns=(("GATE", 0.21), ("BASIS", 0.23), ("ACTM / UTC", 0.24), ("RESULT", 0.32)),
        rows=right_rows,
        accent=_CYAN,
        max_rows=10,
        empty_text="No additional CFP route gate was extracted.",
    )
    source_finding = (group.get("communications") or [{}])[0]
    _strip(
        canvas,
        x=margin,
        y=32 * mm,
        width=PAGE_SIZE[0] - 2 * margin,
        height=10 * mm,
        title="PROCEDURE STATUS",
        accent=_AMBER,
        body=(
            "CFP route and crossing times are shown. Current approved contact "
            f"procedures are unavailable - review required. {_compact_source_label(source_finding)}"
        ),
    )
    _strip(
        canvas,
        x=margin,
        y=18 * mm,
        width=PAGE_SIZE[0] - 2 * margin,
        height=10 * mm,
        title="PILOT USE",
        accent=_HEADER,
        body=(
            "Use the official CFP and current authorised communications source; "
            "no frequency or early-contact instruction is inferred."
        ),
    )


def _page_six(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - TERRAIN / DEPRESSURISATION", page_number=6)
    top = _draw_title(canvas, "HIGH-TERRAIN EXPOSURE AND PROFILE COVERAGE", top)
    margin = 7 * mm
    gap = 3 * mm
    chart_h = 98 * mm
    chart_y = top - chart_h
    group = _grouped(findings)
    events = detect_terrain_events(flight.get("route_waypoints") or [])
    route_points = list((briefing.get("route_map") or {}).get("points") or [])
    if events:
        if len(events) == 1:
            event_groups = [events]
        else:
            gaps: list[int] = []
            for index in range(len(events) - 1):
                current_end = (
                    (
                        events[index].get("drop")
                        or events[index].get("last_high")
                        or {}
                    ).get("actm_minutes")
                )
                next_start = (
                    (
                        events[index + 1].get("preceding")
                        or events[index + 1].get("first_high")
                        or {}
                    ).get("actm_minutes")
                )
                gaps.append(
                    max(
                        0,
                        int(next_start or 0) - int(current_end or 0),
                    )
                )
            split_at = gaps.index(max(gaps)) + 1
            event_groups = [events[:split_at], events[split_at:]]

        chart_w = (
            PAGE_SIZE[0] - 2 * margin - gap * (len(event_groups) - 1)
        ) / len(event_groups)
        for index, event_group in enumerate(event_groups):
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
                margin + index * (chart_w + gap),
                chart_y,
                chart_w,
                chart_h,
                title=(
                    f"{chr(65 + index)}  "
                    f"{_text(start_point.get('name'), 'START').lstrip('-')} - "
                    f"{_text(end_point.get('name'), 'END').lstrip('-')}"
                ),
                mode="terrain",
            )
    else:
        _draw_route_panel(
            canvas,
            briefing["route_map"],
            margin,
            chart_y,
            PAGE_SIZE[0] - 2 * margin,
            chart_h,
            "CFP ROUTE / TERRAIN CONTEXT",
        )
    rows = _terrain_rows(
        flight,
        group.get("terrain", []) + group.get("vws", []),
        group.get("depressurisation", []),
    )
    table_y = 29 * mm
    table_h = 8.5 * mm + max(1, len(rows)) * 10 * mm
    _draw_table(
        canvas,
        x=margin,
        y=table_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=table_h,
        columns=(
            ("REF", 0.08),
            ("ACTM", 0.15),
            ("ACTUAL EXPOSURE", 0.25),
            ("MAX", 0.18),
            ("PROFILE COVERAGE", 0.34),
        ),
        rows=rows,
        accent=_AMBER,
        max_rows=6,
        empty_text="No high-terrain exposure was extracted from CFP MSA points.",
    )
    _strip(
        canvas,
        x=margin,
        y=18 * mm,
        width=PAGE_SIZE[0] - 2 * margin,
        height=8 * mm,
        title="BOUNDARY",
        accent=_AMBER,
        body="Only validated CFP MSA points and approved profile matches are presented; missing coverage remains review required.",
    )


def _page_seven(
    canvas: pdf_canvas.Canvas,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    briefing: dict[str, Any],
    warnings: list[str],
) -> None:
    top = _draw_header(canvas, flight, briefing, label="LEVEL 2 - WEATHER / VAAC / PROMOTION", page_number=7)
    top = _draw_title(canvas, "WEATHER, VAAC AND PROMOTION RESULT", top)
    margin = 7 * mm
    gap = 3 * mm
    group = _grouped(findings)
    advisories = group.get("vaa", []) + group.get("tropical_cyclone", [])
    weather_rows = _weather_rows(
        [
            item
            for item in group.get("weather", [])
            if _text((item.get("data") or {}).get("phase"), "").lower()
            != "edto"
        ]
    )
    advisory_rows = _advisory_rows(advisories)
    panel_h = 84 * mm
    panel_y = top - panel_h
    weather_w = 184 * mm
    advisory_w = PAGE_SIZE[0] - 2 * margin - gap - weather_w
    _draw_table(
        canvas,
        x=margin,
        y=panel_y,
        width=weather_w,
        height=panel_h,
        columns=(
            ("PHASE / LOCATION", 0.17),
            ("UTC WINDOW", 0.18),
            ("MECHANISM", 0.20),
            ("FLIGHT EFFECT", 0.29),
            ("SOURCE", 0.16),
        ),
        rows=weather_rows,
        accent=_AMBER,
        max_rows=8,
        empty_text="No complete current weather result is available - review required.",
    )
    compact_advisory_rows = [
        [
            f"{row[0]} / {row[1]}",
            f"{row[2]} {row[3]}",
            row[4],
        ]
        for row in advisory_rows
    ]
    if warnings:
        compact_advisory_rows.append(
            [
                "SOURCE COVERAGE / REVIEW REQUIRED",
                "Coverage note: "
                + "; ".join(_pilot_text(item) for item in warnings[:2]),
                "Coverage status",
            ]
        )
    _draw_table(
        canvas,
        x=margin + weather_w + gap,
        y=panel_y,
        width=advisory_w,
        height=panel_h,
        columns=(("PRODUCT / STATUS", 0.27), ("RESULT", 0.47), ("SOURCE", 0.26)),
        rows=compact_advisory_rows,
        accent=_TEAL,
        max_rows=4,
        empty_text="No complete current advisory coverage is available - review required.",
    )

    promotion_rows = _promotion_rows(findings)
    separate_note = _personal_note_row(
        flight,
        "separate",
        "Personal notes",
    )
    if separate_note:
        promotion_rows.insert(
            0,
            [
                separate_note[0],
                "PILOT",
                separate_note[1],
                separate_note[2],
            ],
        )
    table_y = 18 * mm
    table_h = panel_y - table_y - gap
    _draw_table(
        canvas,
        x=margin,
        y=table_y,
        width=PAGE_SIZE[0] - 2 * margin,
        height=table_h,
        columns=(
            ("CATEGORY", 0.22),
            ("BRIEF", 0.10),
            ("PROMOTION RESULT", 0.43),
            ("EVIDENCE", 0.25),
        ),
        rows=promotion_rows,
        accent=_HEADER,
        max_rows=7,
    )


def render_level2_visual(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    path: Path,
    *,
    map_image_path: Path | None = None,
    map_label: str | None = None,
) -> None:
    """Render the fixed seven-page operational brief.

    Page purposes are fixed publication structure. Flight-specific values,
    findings, map points, evidence and applicability remain deterministic
    inputs from the uploaded CFP and approved source adapters.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    pilot_findings = prepare_pilot_findings(findings, notam_limit=24)
    briefing = build_briefing_view(
        flight,
        pilot_findings,
        warnings,
        flight.get("timing_view"),
    )
    if map_image_path:
        briefing["route_map"]["snapshot_path"] = str(map_image_path)
        briefing["route_map"]["snapshot_label"] = map_label or "Realistic route map"

    document = pdf_canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pages = (
        lambda: _page_one(document, flight, pilot_findings, briefing),
        lambda: _page_two(document, flight, pilot_findings, briefing),
        lambda: _page_three(document, flight, pilot_findings, briefing),
        lambda: _page_four(document, flight, pilot_findings, briefing),
        lambda: _page_five(document, flight, pilot_findings, briefing),
        lambda: _page_six(document, flight, pilot_findings, briefing),
        lambda: _page_seven(
            document,
            flight,
            pilot_findings,
            briefing,
            warnings,
        ),
    )
    for index, draw_page in enumerate(pages):
        _draw_background(document)
        draw_page()
        if index < len(pages) - 1:
            document.showPage()
    document.save()


__all__ = ["PAGE_SIZE", "render_level2_visual"]
