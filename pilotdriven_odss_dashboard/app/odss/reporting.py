from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
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
from .brief_theme import SANS, SANS_BOLD, register_fonts
from .briefing import build_briefing_view
from .constants import ENGINE_ORDER
from .pertinent_brief import render_level1_visual
from .operational_brief import render_level2_visual
from .report_quality import assert_report_quality
from .pilot_briefing import (
    select_concise_weather,
    select_pertinent_notams,
)
from .visual_reporting import PAGE_SIZE, visual_cover_flowable


_TITLES = {
    "page1": "OFP Page 1 organised summary",
    "bobcat": "BOBCAT / Kabul slot control",
    "deferred_declaration": "Unclassified deferred declaration",
    "mel": "MEL review",
    "cddl": "CDDL / CDL review",
    "performance": "Performance and fuel",
    "weather": "Weather",
    "sigmet": "Significant weather advisory review",
    "vaa": "Volcanic ash advisory review",
    "tropical_cyclone": "Tropical cyclone review",
    "notam": "Applicable NOTAMs within STD / STA ±2 hours",
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
    "deferred_declaration",
    "mel",
    "cddl",
    "performance",
    "weather",
    "sigmet",
    "vaa",
    "tropical_cyclone",
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
    return select_pertinent_notams(findings, limit=16)


def _page_label(values: list[Any]) -> str | None:
    pages = sorted(
        {
            int(value)
            for value in values
            if isinstance(value, int) and value > 0
        }
    )
    if not pages:
        return None
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


_PROVIDER_DISPLAY_NAMES = {
    "hong-kong-observatory-public-tc-track": (
        "Hong Kong Observatory tropical-cyclone track"
    ),
    "jma-tokyo-vaac": "JMA Tokyo VAAC",
    "noaa-awc-data-api": "NOAA Aviation Weather Center",
    "noaa-awc-international-sigmet": (
        "NOAA Aviation Weather Center international SIGMET"
    ),
    "openstreetmap": "OpenStreetMap",
}


def _provider_display_name(value: Any) -> str:
    text = str(value or "").strip()
    return _PROVIDER_DISPLAY_NAMES.get(text, text)


def _utc_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d %b %Y %H%MZ").upper()


def _source_reference_line(reference: dict[str, Any]) -> str | None:
    parts: list[str] = []
    document = reference.get("display_title") or reference.get("document_title")
    provider = reference.get("provider")
    if document:
        parts.append(str(document))
    elif provider:
        parts.append(_provider_display_name(provider))
    else:
        return None
    if reference.get("revision"):
        parts.append(f"revision {reference['revision']}")
    if reference.get("section"):
        parts.append(str(reference["section"]))
    pages = _page_label(list(reference.get("pages") or []))
    if pages:
        parts.append(pages)
    if reference.get("retrieved_at_utc"):
        parts.append(f"retrieved {_utc_display(reference['retrieved_at_utc'])}")
    if reference.get("observed_at_utc"):
        parts.append(f"observed {_utc_display(reference['observed_at_utc'])}")
    if reference.get("issued_at_utc"):
        parts.append(f"issued {_utc_display(reference['issued_at_utc'])}")
    validity = [
        value
        for value in (
            reference.get("valid_from_utc"),
            reference.get("valid_to_utc"),
        )
        if value
    ]
    if validity:
        parts.append(
            f"valid {' to '.join(_utc_display(value) for value in validity)}"
        )
    if reference.get("availability_status") == "controlled-source-not-mounted":
        parts.append("approved source unavailable - review required")
    elif reference.get("availability_status") == "source-incomplete":
        parts.append("coverage incomplete - review required")
    if reference.get("source_url"):
        parts.append(str(reference["source_url"]))
    return "Evidence: " + "; ".join(parts) + "."


def _section_source_lines(
    findings: list[dict[str, Any]],
) -> list[str]:
    consolidated: dict[tuple[Any, ...], dict[str, Any]] = {}
    for finding in findings:
        for reference in (
            (finding.get("data") or {}).get("source_references") or []
        ):
            if not isinstance(reference, dict):
                continue
            key = (
                reference.get("source_type"),
                reference.get("display_title"),
                reference.get("document_title"),
                reference.get("provider"),
                reference.get("revision"),
                reference.get("section"),
                reference.get("retrieved_at_utc"),
                reference.get("observed_at_utc"),
                reference.get("issued_at_utc"),
                reference.get("valid_from_utc"),
                reference.get("valid_to_utc"),
                reference.get("availability_status"),
                reference.get("source_url"),
            )
            target = consolidated.setdefault(key, dict(reference))
            target["pages"] = sorted(
                {
                    *[
                        page
                        for page in (target.get("pages") or [])
                        if isinstance(page, int)
                    ],
                    *[
                        page
                        for page in (reference.get("pages") or [])
                        if isinstance(page, int)
                    ],
                }
            )
    return list(
        dict.fromkeys(
            line
            for reference in consolidated.values()
            for line in [_source_reference_line(reference)]
            if line
        )
    )


def _automatic_section(
    engine: str,
    engine_findings: list[dict[str, Any]],
    level: int,
    page_breaks: set[str],
) -> dict[str, Any] | None:
    if not engine_findings:
        return None
    if engine == "notam":
        selected_findings = (
            _select_level1_notams(engine_findings)
            if level == 1
            else select_pertinent_notams(engine_findings, limit=24)
        )
    elif engine == "weather":
        selected_findings = select_concise_weather(engine_findings)
    else:
        selected_findings = engine_findings
    lines: list[str] = []
    severity = max(
        (finding["severity"] for finding in selected_findings),
        key=lambda value: _SEVERITY_RANK.get(value, 0),
        default="information",
    )
    finding_limit = len(selected_findings) if level == 2 or engine == "notam" else 12
    findings_to_render = selected_findings[:finding_limit]
    if engine == "weather" and level == 2:
        pertinent = [
            item
            for item in findings_to_render
            if (item.get("data") or {}).get("window_status")
            != "no_significant_overlap"
        ]
        no_overlap = [
            item
            for item in findings_to_render
            if (item.get("data") or {}).get("window_status")
            == "no_significant_overlap"
        ]
        findings_to_render = pertinent
        if no_overlap:
            checked = "; ".join(
                (
                    f"{(item.get('data') or {}).get('location') or 'location'} "
                    f"({str((item.get('data') or {}).get('phase') or 'phase').lower()}, "
                    f"{(item.get('data') or {}).get('utc_window') or 'window unresolved'})"
                )
                for item in no_overlap
            )
            lines.append(
                "No significant OFP forecast-weather overlap in the checked "
                f"windows: {checked}."
            )
            lines.append(
                "These checks use the uploaded OFP forecast; refresh from the "
                "latest official operational weather before use."
            )
    seen_details: set[str] = set()
    for finding in findings_to_render:
        lines.append(f"{finding['title']}: {finding['summary']}")
        # The concise weather summary already contains phase, checked UTC
        # window, applicable mechanism and flight effect. Repeating its
        # decoded METAR/TAF fields as separate report rows bloats the report
        # and makes the same fact appear twice. The immutable analysis JSON
        # remains the audit path for those source details.
        detail_limit = 0 if engine == "weather" else (
            len(finding["details"])
            if level == 2
            else (
                20 if engine == "actual_timing"
                else 6 if engine in {"page1", "performance", "timeline"}
                else 1 if engine == "notam"
                else 2
            )
        )
        details = [
            str(detail).strip()
            for detail in finding["details"][:detail_limit]
            if str(detail).strip()
        ]
        if level == 2 and engine in {"terrain", "vws", "timeline"}:
            compact = [
                detail.rstrip(".")
                for detail in details
                if detail not in seen_details
            ]
            seen_details.update(details)
            if compact:
                lines.append(f"- {'; '.join(compact)}.")
        else:
            for normalized in details:
                if normalized in seen_details:
                    continue
                seen_details.add(normalized)
                lines.append(f"- {normalized}")
    if level == 2:
        lines.extend(
            f"- {line}"
            for line in _section_source_lines(selected_findings[:finding_limit])
        )
    if engine == "notam" and len(selected_findings) < len(engine_findings):
        lines.append(
            f"{len(engine_findings) - len(selected_findings)} additional grouped "
            "applicable NOTAM row(s) continue in expanded Level 2 and analysis evidence."
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
        "Pilot-entered note."
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
    # Let ReportLab pack detail sections naturally. Forced section breaks made
    # short, valid sections consume mostly-empty pages on real long-haul CFPs.
    page_breaks: set[str] = set()

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
    *,
    map_image_path: Path | None = None,
    map_label: str | None = None,
) -> None:
    register_fonts()
    path.parent.mkdir(parents=True, exist_ok=True)
    if level == 1:
        render_level1_visual(
            flight,
            findings,
            warnings,
            path,
            map_image_path=map_image_path,
            map_label=map_label,
        )
        assert_report_quality(path, level=1)
        return

    if level == 2:
        render_level2_visual(
            flight,
            findings,
            warnings,
            path,
            map_image_path=map_image_path,
            map_label=map_label,
        )
        assert_report_quality(path, level=2)
        return

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "ODSS Heading",
        parent=styles["Heading2"],
        fontName=SANS_BOLD,
        fontSize=9.5,
        leading=11,
        textColor=colors.white,
    )
    # Raised from 7.2pt for the same readability reason as the visual report
    # styles: this is body text read on an iPad at arm's length.
    body = ParagraphStyle(
        "ODSS Body",
        parent=styles["BodyText"],
        fontName=SANS,
        fontSize=9.5,
        leading=12,
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
            "page_break_before": False,
        })

    briefing = build_briefing_view(
        flight,
        findings,
        warnings,
        flight.get("timing_view"),
    )
    if map_image_path:
        briefing["route_map"]["snapshot_path"] = str(map_image_path)
        briefing["route_map"]["snapshot_label"] = map_label or "Realistic route map"

    def draw_page(canvas, document_template) -> None:
        if canvas.getPageNumber() == 1:
            return
        width, height = PAGE_SIZE
        canvas.saveState()
        # Split tables can leave a translated canvas transform on continuation
        # pages. Reset to physical page coordinates before drawing the repeated
        # header/footer so they cannot be clipped or shifted off-page.
        canvas.resetTransforms()
        canvas.setFillColor(colors.HexColor("#173B65"))
        canvas.setFont(SANS_BOLD, 13)
        canvas.drawCentredString(width / 2, height - 10 * mm, report_title)
        canvas.setFillColor(colors.HexColor("#4B5563"))
        canvas.setFont(SANS_BOLD, 8)
        canvas.drawCentredString(width / 2, height - 15 * mm, report_subtitle)
        canvas.setStrokeColor(colors.HexColor("#D9E1E8"))
        canvas.line(7 * mm, height - 17 * mm, width - 7 * mm, height - 17 * mm)
        canvas.setFont(SANS, 6.2)
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
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            # ReportLab tops-aligns cell content by default, which leaves short
            # entries floating against the rule when a neighbouring cell wraps.
            # "middle place the texts in ALL cells" — asked for twice.
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.extend([table, Spacer(1, 1 * mm)])
    document.build(story)
    assert_report_quality(path, level=2)
