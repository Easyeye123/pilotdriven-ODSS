from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .constants import ENGINE_ORDER


_TITLES = {
    "page1": "CFP Page 1 organised summary",
    "bobcat": "BOBCAT / Kabul slot control",
    "mel": "MEL review",
    "cddl": "CDDL / CDL review",
    "performance": "Performance and fuel",
    "weather": "Weather",
    "notam": "Pertinent NOTAM",
    "communications": "Early ATC contact / FIR entry calls",
    "terrain": "Terrain MSA events",
    "vws": "Vertical wind shear events",
    "depressurisation": "Depressurisation profiles",
    "edto": "EDTO",
    "timeline": "Route-critical ACTM timeline",
    "qa": "Quality assurance",
}


def report_sections(findings: list[dict[str, Any]], level: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        grouped[finding["engine"]].append(finding)
    page_breaks = (
        {"mel", "weather", "communications", "depressurisation", "timeline"}
        if level == 2
        else {"communications"}
    )
    sections: list[dict[str, Any]] = []
    for engine in ENGINE_ORDER:
        engine_findings = grouped.get(engine, [])
        if not engine_findings:
            continue
        lines: list[str] = []
        severity = "information"
        finding_limit = len(engine_findings) if level == 2 else (8 if engine == "notam" else 12)
        for finding in engine_findings[:finding_limit]:
            if finding["severity"] != "information":
                severity = finding["severity"]
            lines.append(f"{finding['title']}: {finding['summary']}")
            detail_limit = (
                len(finding["details"])
                if level == 2
                else (6 if engine in {"page1", "performance", "timeline"} else 2)
            )
            lines.extend(f"- {detail}" for detail in finding["details"][:detail_limit])
        sections.append({
            "title": _TITLES[engine],
            "lines": lines,
            "severity": severity,
            "page_break_before": engine in page_breaks,
        })
    return sections


def render_pdf(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    level: int,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ODSS Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=17,
        textColor=colors.HexColor("#173B65"),
        alignment=TA_CENTER,
    )
    subtitle = ParagraphStyle(
        "ODSS Subtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=colors.HexColor("#4B5563"),
        alignment=TA_CENTER,
    )
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
    footer = ParagraphStyle(
        "ODSS Footer",
        parent=body,
        fontSize=6.5,
        leading=7.5,
        textColor=colors.HexColor("#4B5563"),
        alignment=TA_CENTER,
    )
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )
    report_title = (
        f"{flight['flight_number']} {flight['departure']}-{flight['destination']}"
        if level == 1
        else f"{flight['flight_number']} Expanded Operational Analysis"
    )
    report_subtitle = f"Level {level} - {flight['flight_date']}"
    story = [
        Paragraph(report_title, title),
        Paragraph(report_subtitle, subtitle),
        Spacer(1, 2 * mm),
    ]
    page_number = 1
    for index, section in enumerate(report_sections(findings, level)):
        if section["page_break_before"] and index > 0:
            story.append(PageBreak())
            page_number += 1
            story.extend([
                Paragraph(f"{report_title} - Page {page_number}", title),
                Paragraph(report_subtitle, subtitle),
                Spacer(1, 2 * mm),
            ])
        colour = {
            "critical": colors.HexColor("#9F1D2F"),
            "warning": colors.HexColor("#A96800"),
        }.get(section["severity"], colors.HexColor("#173B65"))
        header = Table([[Paragraph(section["title"], heading)]], colWidths=[190 * mm])
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colour),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(header)
        lines = section["lines"] or ["No findings."]
        for offset in range(0, len(lines), 40):
            content = "<br/>".join(
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for line in lines[offset: offset + 40]
            )
            box = Table([[Paragraph(content, body)]], colWidths=[190 * mm])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7FA")),
                ("BOX", (0, 0), (-1, -1), 0.5, colour),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.extend([box, Spacer(1, 1 * mm)])
    story.append(Paragraph(
        "Decision support only. Current approved documents, dispatch authority, "
        "ATC instructions and pilot-in-command judgement remain controlling.",
        footer,
    ))
    document.build(story)
