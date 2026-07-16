from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..personal_notes import PERSONAL_NOTE_PLACEMENT_LABELS
from .briefing import build_briefing_view
from .constants import ENGINE_ORDER
from .visual_reporting import PAGE_SIZE, render_level1_visual, visual_cover_flowable


_TITLES = {
    "page1": "CFP Page 1 organised summary",
    "bobcat": "BOBCAT / Kabul slot control",
    "mel": "MEL review",
    "cddl": "CDDL / CDL review",
    "performance": "Performance and fuel",
    "weather": "Weather",
    "notam": "Pertinent NOTAM",
    "communications": "Early ATC contact / FIR entry calls",
    "actual_timing": "Actual takeoff / calculated UTC timeline",
    "terrain": "Terrain MSA events",
    "vws": "Vertical wind shear events",
    "depressurisation": "Depressurisation profiles",
    "edto": "EDTO",
    "timeline": "Route-critical ACTM timeline",
    "qa": "Quality assurance",
}

_NOTE_TITLES = {
    "separate": "Personal notes",
    "departure": "Departure airport - personal notes",
    "destination": "Destination airport - personal notes",
    "communications": "Enroute ATC / communications - personal notes",
}

_REPORT_ORDER = [
    "page1",
    "bobcat",
    "mel",
    "cddl",
    "performance",
    "weather",
    "notam",
    "note:departure",
    "note:destination",
    "communications",
    "note:communications",
    "actual_timing",
    "terrain",
    "vws",
    "depressurisation",
    "edto",
    "timeline",
    "note:separate",
    "qa",
]

_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}
_ROLE_RANK = {"departure": 0, "destination": 1, "destination alternate": 2, "EDTO": 3, "informational": 4}


class _BookmarkFlowable(Flowable):
    def __init__(self, *names: str):
        super().__init__()
        self.names = names

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return 0, 0

    def draw(self) -> None:
        for name in self.names:
            self.canv.bookmarkPage(name)


def _select_level1_notams(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        findings,
        key=lambda item: (
            _ROLE_RANK.get(item.get("data", {}).get("role", "informational"), 5),
            -_SEVERITY_RANK.get(item.get("severity", "information"), 0),
            -int(item.get("data", {}).get("priority_score", 0)),
            item.get("title", ""),
        ),
    )
    selected = [item for item in ordered if item.get("severity") == "critical"]
    for role in ("departure", "destination", "destination alternate", "EDTO"):
        if any(item.get("data", {}).get("role") == role for item in selected):
            continue
        candidate = next((item for item in ordered if item.get("data", {}).get("role") == role), None)
        if candidate is not None and candidate not in selected:
            selected.append(candidate)
    for item in ordered:
        if len(selected) >= 16:
            break
        if item not in selected:
            selected.append(item)
    return sorted(
        selected,
        key=lambda item: (
            _ROLE_RANK.get(item.get("data", {}).get("role", "informational"), 5),
            -_SEVERITY_RANK.get(item.get("severity", "information"), 0),
            -int(item.get("data", {}).get("priority_score", 0)),
            item.get("title", ""),
        ),
    )


def _automatic_section(
    engine: str,
    engine_findings: list[dict[str, Any]],
    level: int,
    page_breaks: set[str],
) -> dict[str, Any] | None:
    if not engine_findings:
        return None
    selected_findings = (
        _select_level1_notams(engine_findings)
        if level == 1 and engine == "notam"
        else engine_findings
    )
    lines: list[str] = []
    severity = max(
        (finding["severity"] for finding in selected_findings),
        key=lambda value: _SEVERITY_RANK.get(value, 0),
        default="information",
    )
    finding_limit = len(selected_findings) if level == 2 or engine == "notam" else 12
    for finding in selected_findings[:finding_limit]:
        lines.append(f"{finding['title']}: {finding['summary']}")
        detail_limit = (
            len(finding["details"])
            if level == 2
            else (
                20 if engine == "actual_timing"
                else 6 if engine in {"page1", "performance", "timeline"}
                else 1 if engine == "notam"
                else 2
            )
        )
        lines.extend(f"- {detail}" for detail in finding["details"][:detail_limit])
    if level == 1 and engine == "notam" and len(selected_findings) < len(engine_findings):
        lines.append(
            f"{len(engine_findings) - len(selected_findings)} lower-priority active or review NOTAM findings omitted; see Level 2."
        )
    return {
        "engine": engine,
        "title": _TITLES.get(engine, engine.replace("_", " ").title()),
        "lines": lines,
        "severity": severity,
        "page_break_before": engine in page_breaks,
    }


def _personal_note_section(
    placement: str,
    notes: list[dict[str, Any]],
    level: int,
) -> dict[str, Any] | None:
    inclusion_key = "include_level1" if level == 1 else "include_level2"
    selected = [
        note
        for note in notes
        if note.get("placement") == placement and bool(note.get(inclusion_key))
    ]
    if not selected:
        return None

    lines: list[str] = []
    for index, note in enumerate(selected, start=1):
        text_lines = [
            line.strip()
            for line in str(note.get("note_text") or "").splitlines()
            if line.strip()
        ]
        if not text_lines:
            continue
        lines.append(f"Personal note {index}: {text_lines[0]}")
        lines.extend(f"- {line}" for line in text_lines[1:])
    lines.append(
        "Pilot-entered personal content; it is not extracted, validated or endorsed by the ODSS engine."
    )
    return {
        "engine": f"personal_notes_{placement}",
        "title": _NOTE_TITLES.get(
            placement,
            PERSONAL_NOTE_PLACEMENT_LABELS.get(placement, "Personal notes"),
        ),
        "lines": lines,
        "severity": "personal",
        "page_break_before": False,
    }


def report_sections(
    findings: list[dict[str, Any]],
    level: int,
    personal_notes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[finding["engine"]].append(finding)
    page_breaks = (
        {"mel", "weather", "actual_timing", "depressurisation", "timeline"}
        if level == 2
        else set()
    )

    automatic = {
        engine: section
        for engine in ENGINE_ORDER
        if (
            section := _automatic_section(
                engine,
                grouped.get(engine, []),
                level,
                page_breaks,
            )
        )
    }
    note_sections = {
        placement: section
        for placement in PERSONAL_NOTE_PLACEMENT_LABELS
        if (
            section := _personal_note_section(
                placement,
                personal_notes or [],
                level,
            )
        )
    }

    sections: list[dict[str, Any]] = []
    used_engines: set[str] = set()
    for item in _REPORT_ORDER:
        if item.startswith("note:"):
            placement = item.split(":", 1)[1]
            section = note_sections.get(placement)
        else:
            section = automatic.get(item)
            used_engines.add(item)
        if section:
            sections.append(section)

    for engine in ENGINE_ORDER:
        if engine in used_engines:
            continue
        section = automatic.get(engine)
        if section:
            sections.append(section)
    for engine, engine_findings in grouped.items():
        if engine in ENGINE_ORDER:
            continue
        section = _automatic_section(engine, engine_findings, level, page_breaks)
        if section:
            sections.append(section)
    return sections


def render_pdf(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    level: int,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if level == 1:
        render_level1_visual(flight, findings, warnings, path)
        return

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "ODSS Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11,
        textColor=colors.white,
    )
    body = ParagraphStyle(
        "ODSS Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=9.2,
    )
    document = BaseDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=7 * mm,
        rightMargin=7 * mm,
        topMargin=20 * mm,
        bottomMargin=13 * mm,
    )
    report_title = f"{flight['flight_number']} Expanded Operational Analysis"
    report_subtitle = f"Level {level} - {flight['flight_date']}"
    if flight.get("actual_takeoff_utc"):
        report_subtitle += f" - actual clock anchored {flight['actual_takeoff_utc']}"
    sections = report_sections(findings, level, flight.get("personal_notes") or [])
    if warnings:
        sections.append({
            "engine": "warnings",
            "title": "Applicability and parser warnings",
            "lines": warnings,
            "severity": "warning",
            "page_break_before": True,
        })

    briefing = build_briefing_view(
        flight,
        findings,
        warnings,
        flight.get("timing_view"),
    )

    def draw_page(canvas, document_template) -> None:
        if canvas.getPageNumber() == 1:
            return
        width, height = PAGE_SIZE
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#173B65"))
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawCentredString(width / 2, height - 10 * mm, report_title)
        canvas.setFillColor(colors.HexColor("#4B5563"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(width / 2, height - 15 * mm, report_subtitle)
        canvas.setStrokeColor(colors.HexColor("#D9E1E8"))
        canvas.line(7 * mm, height - 17 * mm, width - 7 * mm, height - 17 * mm)
        canvas.setFont("Helvetica", 6.2)
        canvas.drawString(
            7 * mm,
            6 * mm,
            "Decision support only - approved documents, dispatch authority, ATC instructions and PIC judgement remain controlling.",
        )
        canvas.drawRightString(width - 7 * mm, 6 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="body",
    )
    document.addPageTemplates([PageTemplate(id="report", frames=[frame], onPageEnd=draw_page)])

    story: list[Any] = [
        visual_cover_flowable(briefing),
        PageBreak(),
        _BookmarkFlowable(
            "operational_detail",
            "departure_detail",
            "destination_detail",
            "route_contingency",
            "communications_detail",
            "edto_detail",
        ),
    ]
    for index, section in enumerate(sections):
        if section["page_break_before"] and index > 0:
            story.append(PageBreak())
        colour = {
            "critical": colors.HexColor("#9F1D2F"),
            "warning": colors.HexColor("#A96800"),
            "personal": colors.HexColor("#5B4B8A"),
        }.get(section["severity"], colors.HexColor("#173B65"))
        lines = section["lines"] or ["No findings."]
        rows = [[Paragraph(section["title"], heading)]]
        rows.extend([
            [Paragraph(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), body)]
            for line in lines
        ])
        table = Table(rows, colWidths=[document.width], repeatRows=1, splitByRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colour),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F5F7FA")),
            ("BOX", (0, 0), (-1, -1), 0.5, colour),
            ("LINEBELOW", (0, 1), (-1, -2), 0.2, colors.HexColor("#D9E1E8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([table, Spacer(1, 1 * mm)])
    document.build(story)
