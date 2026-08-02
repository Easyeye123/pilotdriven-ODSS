from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader


@dataclass(frozen=True)
class ReportQualityViolation:
    code: str
    message: str


class ReportQualityError(RuntimeError):
    def __init__(self, violations: list[ReportQualityViolation]):
        self.violations = violations
        super().__init__(
            "Report failed publication quality checks: "
            + "; ".join(item.message for item in violations)
        )


_A4_LANDSCAPE_WIDTH = 841.89
_A4_LANDSCAPE_HEIGHT = 595.28
_PAGE_TOLERANCE_POINTS = 8.0
_PILOT_FACING_FORBIDDEN = (
    ("PILOT_TECHNICAL_RAG", re.compile(r"\bRAG\b", re.IGNORECASE)),
    ("PILOT_TECHNICAL_CANONICAL", re.compile(r"\bcanonical\b", re.IGNORECASE)),
    ("PILOT_INTERNAL_FINDING_ID", re.compile(r"\bL[123]-[A-Z][A-Z0-9-]{3,}\b")),
    ("PILOT_TRIGGER_LABEL", re.compile(r"\bTrigger\s*:", re.IGNORECASE)),
    ("PILOT_DECISION_POINT_LABEL", re.compile(r"\bDecision point\s*:", re.IGNORECASE)),
)
_LEVEL_1_PAGE_2_TITLE = re.compile(
    r"^\s*[A-Z0-9][A-Z0-9 -]{1,15}\s*-\s*OPERATIONAL TIMING\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LEVEL_1_PAGE_3_TITLE = re.compile(
    r"\bDEPRESSURISATION PROFILE ANALYSIS\b",
    re.IGNORECASE,
)
_LEVEL_1_NOTAM_WINDOW = re.compile(
    r"APPLICABLE NOTAMS WITHIN STD\s*/\s*STA\s*(?:±|\+/-)\s*2 HOURS",
    re.IGNORECASE,
)
_LEVEL_1_MAP_MARKERS = (
    "Filed route from CFP coordinates",
    "Route coordinates unavailable",
)
_LEVEL_1_RETIRED_HEADINGS = (
    "WEATHER / PERTINENT NOTAM",
    "OPERATIONAL DETAIL",
    "ROUTE / CONTINGENCY",
)
_LEVEL_2_PAGE_TITLES = (
    ("ANALYSIS OVERVIEW",),
    ("PERFORMANCE, FUEL AND AIRPORT BASIS",),
    ("FLIGHT-WINDOW NOTAM APPLICABILITY",),
    ("EDTO SECTORS AND SUITABILITY INPUTS", "EDTO STATUS"),
    ("OCEANIC AND FIR COMMUNICATIONS",),
    ("DEPRESSURISATION PROFILE MATCH MATRIX",),
    ("WEATHER AND PROMOTION RESULT",),
)
_LEVEL_2_SOURCE_CHART_MARKER = "LEVEL 2 SOURCE CHART - PROFILE"
_LEVEL_2_NOTAM_CONTINUATION_MARKER = "LEVEL 2 - NOTAM CONTINUATION"
_LEVEL_2_AIP_SUPPLEMENT_MARKER = "LEVEL 2 - AIP SUPPLEMENT DETAILS"
_LEVEL_2_FAIL_CLOSED_ADVISORY_RESULTS = (
    (
        "SIGMET review required",
        "Flight-window coverage incomplete - review the current official source.",
    ),
    (
        "Volcanic ash review required",
        "Applicability unresolved - review official volcanic-ash source.",
    ),
    (
        "Tropical cyclone review required",
        "Applicability unresolved - review official cyclone source.",
    ),
)


def validate_report_pdf(
    path: Path,
    *,
    level: int,
    level3_status: str | None = None,
) -> dict[str, Any]:
    violations: list[ReportQualityViolation] = []
    try:
        reader = PdfReader(path)
    except Exception as exc:
        return {
            "valid": False,
            "page_count": 0,
            "violations": [
                ReportQualityViolation(
                    "PDF_UNREADABLE",
                    f"The generated PDF cannot be read: {type(exc).__name__}.",
                )
            ],
        }

    pages = list(reader.pages)
    page_count = len(pages)
    if level == 1 and page_count != 3:
        violations.append(ReportQualityViolation(
            "LEVEL_1_PAGE_CONTRACT",
            f"Level 1 must contain exactly 3 pages; generated {page_count}.",
        ))
    elif level == 2 and page_count < 7:
        # Seven structured pages plus one appended page per embedded
        # depressurisation source chart (v1.3 publication gate).
        violations.append(ReportQualityViolation(
            "LEVEL_2_PAGE_CONTRACT",
            f"Level 2 must contain at least 7 pages; generated {page_count}.",
        ))
    elif level == 3:
        maximum = 1 if str(level3_status).upper() == "PARTIAL" else 5
        if not 1 <= page_count <= maximum:
            violations.append(ReportQualityViolation(
                "LEVEL_3_PAGE_CONTRACT",
                f"Level 3 {str(level3_status or '').upper() or 'report'} must contain 1 to {maximum} page(s); generated {page_count}.",
            ))

    extracted_pages: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if (
            width <= height
            or abs(width - _A4_LANDSCAPE_WIDTH) > _PAGE_TOLERANCE_POINTS
            or abs(height - _A4_LANDSCAPE_HEIGHT) > _PAGE_TOLERANCE_POINTS
        ):
            violations.append(ReportQualityViolation(
                "PAGE_FORMAT_CONTRACT",
                f"Page {page_number} is not A4 landscape.",
            ))
        try:
            extracted_pages.append(page.extract_text() or "")
        except Exception as exc:
            violations.append(ReportQualityViolation(
                "PDF_TEXT_UNREADABLE",
                f"Page {page_number} text cannot be checked: {type(exc).__name__}.",
            ))
            extracted_pages.append("")

    pilot_text = "\n".join(extracted_pages)
    if level in {1, 2, 3}:
        for code, pattern in _PILOT_FACING_FORBIDDEN:
            if pattern.search(pilot_text):
                violations.append(ReportQualityViolation(
                    code,
                    f"Pilot-facing Level {level} contains prohibited internal wording matched by {pattern.pattern}.",
                ))

    if level == 1 and page_count == 3:
        if not _LEVEL_1_NOTAM_WINDOW.search(extracted_pages[0]):
            violations.append(ReportQualityViolation(
                "LEVEL_1_NOTAM_WINDOW_HEADING",
                "Level 1 page 1 must identify applicable NOTAMs within STD / STA ±2 hours.",
            ))
        if not _LEVEL_1_PAGE_2_TITLE.search(extracted_pages[1]):
            violations.append(ReportQualityViolation(
                "LEVEL_1_PAGE_2_STRUCTURE",
                "Level 1 page 2 must be the time-based operating-gates page.",
            ))
        if not _LEVEL_1_PAGE_3_TITLE.search(extracted_pages[2]):
            violations.append(ReportQualityViolation(
                "LEVEL_1_PAGE_3_STRUCTURE",
                "Level 1 page 3 must be the high-terrain-exposure page.",
            ))
        map_occurrences = sum(
            page_text.count(marker)
            for page_text in extracted_pages
            for marker in _LEVEL_1_MAP_MARKERS
        )
        if map_occurrences != 1:
            violations.append(ReportQualityViolation(
                "LEVEL_1_SINGLE_MAP_CONTRACT",
                f"Level 1 must contain exactly one route-map presentation; found {map_occurrences}.",
            ))
        for retired_heading in _LEVEL_1_RETIRED_HEADINGS:
            if retired_heading.lower() in pilot_text.lower():
                violations.append(ReportQualityViolation(
                    "LEVEL_1_RETIRED_DUPLICATE_SECTION",
                    f"Level 1 contains retired duplicate section heading: {retired_heading}.",
                ))

    if level == 2 and page_count >= 7:
        for page_index, accepted_titles in enumerate(_LEVEL_2_PAGE_TITLES):
            if not any(
                title.lower() in extracted_pages[page_index].lower()
                for title in accepted_titles
            ):
                violations.append(ReportQualityViolation(
                    "LEVEL_2_PAGE_STRUCTURE",
                    (
                        f"Level 2 page {page_index + 1} must contain "
                        f"one of {', '.join(accepted_titles)}."
                    ),
                ))
        weather_page = " ".join(extracted_pages[6].split())
        weather_page_folded = weather_page.casefold()
        for title, complete_result in _LEVEL_2_FAIL_CLOSED_ADVISORY_RESULTS:
            if (
                title.casefold() in weather_page_folded
                and complete_result.casefold() not in weather_page_folded
            ):
                violations.append(ReportQualityViolation(
                    "LEVEL_2_ADVISORY_RESULT_INCOMPLETE",
                    (
                        f"Level 2 page 7 contains {title!r} without its complete "
                        "fail-closed result and official-source instruction."
                    ),
                ))
        source_chart_seen = False
        for page_index in range(7, page_count):
            appended_text = extracted_pages[page_index].lower()
            is_source_chart = _LEVEL_2_SOURCE_CHART_MARKER.lower() in appended_text
            is_notam_continuation = (
                _LEVEL_2_NOTAM_CONTINUATION_MARKER.lower() in appended_text
            )
            is_aip_supplement = (
                _LEVEL_2_AIP_SUPPLEMENT_MARKER.lower() in appended_text
            )
            if is_source_chart:
                source_chart_seen = True
                continue
            if is_notam_continuation and not source_chart_seen:
                continue
            if is_aip_supplement and not source_chart_seen:
                continue
            if not is_source_chart:
                violations.append(ReportQualityViolation(
                    "LEVEL_2_APPENDIX_STRUCTURE",
                    (
                        f"Level 2 page {page_index + 1} must be a NOTAM "
                        "continuation or AIP supplement detail page before the "
                        "source charts, or an embedded depressurisation "
                        "source-chart page."
                    ),
                ))

    return {
        "valid": not violations,
        "page_count": page_count,
        "violations": violations,
    }


def assert_report_quality(
    path: Path,
    *,
    level: int,
    level3_status: str | None = None,
) -> dict[str, Any]:
    result = validate_report_pdf(
        path,
        level=level,
        level3_status=level3_status,
    )
    if not result["valid"]:
        raise ReportQualityError(result["violations"])
    return result


__all__ = [
    "ReportQualityError",
    "ReportQualityViolation",
    "assert_report_quality",
    "validate_report_pdf",
]
