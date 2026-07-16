from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

from .constants import ENGINE_ORDER, format_kg


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

_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}
_ROLE_RANK = {"departure": 0, "destination": 1, "destination alternate": 2, "EDTO": 3, "informational": 4}


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


def report_sections(findings: list[dict[str, Any]], level: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[finding["engine"]].append(finding)
    page_breaks = (
        {"mel", "weather", "actual_timing", "depressurisation", "timeline"}
        if level == 2
        else set()
    )
    sections: list[dict[str, Any]] = []
    for engine in ENGINE_ORDER:
        engine_findings = grouped.get(engine, [])
        if not engine_findings:
            continue
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
        sections.append({
            "title": _TITLES[engine],
            "lines": lines,
            "severity": severity,
            "page_break_before": engine in page_breaks,
        })
    return sections


def _planned_mass_strip(flight: dict[str, Any], style: ParagraphStyle) -> Table:
    """Return the first-page mass strip requested for every pertinent brief.

    PLDW is the display label for the CFP planned landing weight, which is
    retained in the canonical model as ``planned_landing_weight_kg``.
    """
    masses = flight.get("masses") or {}
    cells = [
        Paragraph(
            f"<b>PZFW</b><br/>{format_kg(masses.get('planned_zfw_kg'))}",
            style,
        ),
        Paragraph(
            f"<b>PLDW</b><br/>{format_kg(masses.get('planned_landing_weight_kg'))}",
            style,
        ),
        Paragraph(
            f"<b>PTOW</b><br/>{format_kg(masses.get('planned_takeoff_weight_kg'))}",
            style,
        ),
    ]
    table = Table([cells], colWidths=[190 * mm / 3] * 3)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF2F8")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#173B65")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E1E8")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def render_pdf(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
    level: int,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        fontSize=7.5 if level == 1 else 7.2,
        leading=9.2,
    )
    mass_style = ParagraphStyle(
        "ODSS Planned Mass",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#173B65"),
    )
    document = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=23 * mm,
        bottomMargin=15 * mm,
    )
    report_title = (
        f"{flight['flight_number']} {flight['departure']}-{flight['destination']}"
        if level == 1
        else f"{flight['flight_number']} Expanded Operational Analysis"
    )
    report_subtitle = f"Level {level} - {flight['flight_date']}"
    if flight.get("actual_takeoff_utc"):
        report_subtitle += f" - actual clock anchored {flight['actual_takeoff_utc']}"
    sections = report_sections(findings, level)
    if warnings:
        sections.append({
            "title": "Applicability and parser warnings",
            "lines": warnings,
            "severity": "warning",
            "page_break_before": level == 2,
        })

    def draw_page(canvas, document_template) -> None:
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#173B65"))
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawCentredString(width / 2, height - 12 * mm, report_title)
        canvas.setFillColor(colors.HexColor("#4B5563"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(width / 2, height - 17 * mm, report_subtitle)
        canvas.setStrokeColor(colors.HexColor("#D9E1E8"))
        canvas.line(9 * mm, height - 19 * mm, width - 9 * mm, height - 19 * mm)
        canvas.setFont("Helvetica", 6.2)
        canvas.drawString(
            9 * mm,
            7 * mm,
            "Decision support only - approved documents, dispatch authority, ATC instructions and PIC judgement remain controlling.",
        )
        canvas.drawRightString(width - 9 * mm, 7 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="body",
    )
    document.addPageTemplates([PageTemplate(id="report", frames=[frame], onPageEnd=draw_page)])

    story = [_planned_mass_strip(flight, mass_style), Spacer(1, 2 * mm)]
    for index, section in enumerate(sections):
        if section["page_break_before"] and index > 0:
            story.append(PageBreak())
        colour = {
            "critical": colors.HexColor("#9F1D2F"),
            "warning": colors.HexColor("#A96800"),
        }.get(section["severity"], colors.HexColor("#173B65"))
        lines = section["lines"] or ["No findings."]
        rows = [[Paragraph(section["title"], heading)]]
        rows.extend([
            [Paragraph(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), body)]
            for line in lines
        ])
        table = Table(rows, colWidths=[190 * mm], repeatRows=1, splitByRow=1)
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
