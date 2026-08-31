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
    "Filed route from OFP coordinates",
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
_LEVEL_2_SOURCE_CHART_MARKER = "SOURCE CHART - PROFILE"
_LEVEL_2_NOTAM_CONTINUATION_MARKER = "NOTAM CONTINUATION"
_LEVEL_2_AIP_SUPPLEMENT_MARKER = "AIP SUPPLEMENT DETAILS"
_LEVEL_2_GOVERNED_TABLE_CONTINUATION_MARKERS = (
    "WEATHER CONTINUED",
    "ADVISORIES CONTINUED",
)
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

# REV3 canon contract (boss, 20 Aug: "this format, this content, this
# look"): seven fixed sections in the tab-strip order - the old time-gates,
# performance and comms pages fold into pages 1, 2 and 4.
# 21 Aug amendments from the SQ910 round: the PRIORITY strip is removed
# ("don't waste words like this - remove all this") and the analysis page
# label follows his GPT reference's "DECISION ANALYSIS".
_COMBINED_FIXED_PREFIX = (
    ("OFP P1 - ROUTE / LEVELS",),
)
_COMBINED_ANALYSIS_MARKERS = (
    "DECISION ANALYSIS",
    "FLIGHT-PHASE DECISION TIMELINE",
)
_COMBINED_MEL_TITLE = "MEL/CDL AND CDDL"
_COMBINED_CONTINUABLE_SECTIONS = (
    ("EDTO / ENROUTE AIRPORTS", "DESTINATION ALTERNATES"),
    ("AIRPORTS / NOTAM APPLICABILITY",),
    ("OPERATIONAL HAZARD ASSESSMENT",),
)
_COMBINED_TERRAIN_MARKERS = ("HIGH TERRAIN EXPOSURE AND DEPRESSURISATION",)
_COMBINED_CONTINUATION_MARKER = "CONTINUED ("
_COMBINED_PROFILE_TITLE = "DEPRESSURISATION PROFILE"
_COMBINED_BOSS_FLOW_PAGES = (
    (
        "OFP P1 - ROUTE / LEVELS",
        "RELEASE",
        "BEFORE PUSH",
        "ROUTE",
        "ARRIVAL",
        "PERFORMANCE",
        "FUEL",
        "STATUS",
        "WEATHER",
        "ALTERNATES",
    ),
    ("DECISION ANALYSIS", "FLIGHT-PHASE DECISION TIMELINE", "SOURCE"),
    ("PERFORMANCE / FUEL / STATUS", "RECONCILIATION / RELEASE REVIEW"),
    ("MEL/CDL AND CDDL", "SOURCE DECLARATION"),
    ("AIRPORTS / ALTERNATES", "DESTINATION ALTERNATE ASSESSMENT MATRIX"),
    ("WEATHER / ROUTE HAZARDS", "NAMED DIRECT / OFP VOLCANO ADVISORIES"),
    ("ENROUTE / ASSURANCE", "NUMBERED RELEASE GATES", "SOURCE ASSURANCE"),
    ("COVERAGE CHECKLIST", "CAT / VWS EVIDENCE", "AIREP / PIREP"),
)
_COMBINED_OPERATIONAL_PAGE_ONE_MARKERS = (
    "OFP PAGE 1 - FLIGHT BRIEFING",
    "SCHEDULE",
    "DEPARTURE",
    "DESTINATION",
    "MASS / PERFORMANCE",
    "FUEL / TIME RESERVES",
    "FLIGHT PLAN / ALTERNATE",
    "ITEMS REQUIRING CONFIRMATION",
)
_COMBINED_EOSID_CONTINUATION_MARKERS = (
    "EOSID / ESCAPE ROUTING",
    "LOSSLESS CONTINUATION",
)
_COMBINED_EOSID_DECLARATION = re.compile(
    r"EOSID LOSSLESS CONTINUATION\s*:\s*(?P<count>\d+)\s+PAGES?\s+STARTS?\s+P(?P<page>\d+)",
    re.IGNORECASE,
)
_COMBINED_EOSID_PAGE = re.compile(
    r"LOSSLESS CONTINUATION\s+(?P<index>\d+)\s*/\s*(?P<count>\d+)",
    re.IGNORECASE,
)
_COMBINED_AIRPORT_INDEX_MARKER = "AIRPORT SURFACE / NOTES INDEX"
_COMBINED_AIRPORT_INDEX_DECLARATION = re.compile(
    r"(?P<airports>\d+)\s+FILED\s+SURFACE\s*/\s*NOTES\s+AIRPORTS\s*"
    r"[·-]\s*(?P<count>\d+)\s+INDEX\s+PAGES?\s+FOLLOW",
    re.IGNORECASE,
)
_COMBINED_AIRPORT_INDEX_PAGE = re.compile(
    r"AIRPORT\s+SURFACE\s*/\s*NOTES\s+INDEX\s*[·-]\s*"
    r"(?P<index>\d+)\s*/\s*(?P<count>\d+)",
    re.IGNORECASE,
)
_COMBINED_AIRPORT_INDEX_ENTRY = re.compile(
    r"AIRPORT\s+(?P<index>\d+)\s*/\s*(?P<count>\d+)\s*"
    r"[·-]\s*(?P<icao>[A-Z]{4})\b",
    re.IGNORECASE,
)
_COMBINED_RUNWAY_SHORTENING_TITLE = (
    "RUNWAY SHORTENING / DECLARED DISTANCES"
)
_COMBINED_CRITICAL_APPROACH_TITLE = (
    "CRITICAL INSTRUMENT APPROACH IMPACTS"
)
_COMBINED_EDTO_DETAIL_TITLE = "EDTO TIMING / ALTERNATES"
_COMBINED_AIRPORT_NOTAM_DETAIL_TITLE = "ALL SELECTED NOTAM DETAILS"
_COMBINED_VAAC_RECEIPT_TITLE = "VAAC SOURCE RECEIPTS"
_COMBINED_VAAC_RECEIPT_PAGE = re.compile(
    r"CONTINUED\s*\(\s*(?P<index>\d+)\s*/\s*(?P<count>\d+)\s*\)",
    re.IGNORECASE,
)
_COMBINED_RETIRED_LABELS = (
    "LEVEL 1",
    "LEVEL 2",
    "PERTINENT BRIEF",
    "EVIDENCE LEVEL",
)


def validate_combined_briefing_pdf(path: Path) -> dict[str, Any]:
    """Validate the post-Level-1/Level-2 Flight Briefing page contract.

    MEL/CDL continuation pages and governed depressurisation source charts are
    dynamic, while the operational section order remains fixed. Keeping this
    separate from ``validate_report_pdf(level=2)`` prevents the retired report
    layout from silently becoming the publication gate for the combined PDF.
    """
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
    if page_count < 7:
        violations.append(ReportQualityViolation(
            "COMBINED_PAGE_CONTRACT",
            f"Flight Briefing must contain at least 7 pages; generated {page_count}.",
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
            text = page.extract_text() or ""
        except Exception as exc:
            violations.append(ReportQualityViolation(
                "PDF_TEXT_UNREADABLE",
                f"Page {page_number} text cannot be checked: {type(exc).__name__}.",
            ))
            text = ""
        extracted_pages.append(text)
        if "FLIGHT BRIEFING" not in text.upper():
            violations.append(ReportQualityViolation(
                "COMBINED_PAGE_CHROME",
                f"Flight Briefing page {page_number} is missing its report label.",
            ))

    pilot_text = "\n".join(extracted_pages)
    for code, pattern in _PILOT_FACING_FORBIDDEN:
        if pattern.search(pilot_text):
            violations.append(ReportQualityViolation(
                code,
                f"Flight Briefing contains prohibited internal wording matched by {pattern.pattern}.",
            ))
    folded_text = pilot_text.upper()
    pilot_lines = {
        " ".join(line.upper().split())
        for line in pilot_text.splitlines()
        if line.strip()
    }
    for label in _COMBINED_RETIRED_LABELS:
        if label in pilot_lines:
            violations.append(ReportQualityViolation(
                "COMBINED_RETIRED_LABEL",
                f"Flight Briefing contains retired pilot-facing label: {label}.",
            ))

    is_boss_flow = (
        page_count >= len(_COMBINED_BOSS_FLOW_PAGES)
        and "PERFORMANCE / FUEL / STATUS" in extracted_pages[2].upper()
    )
    if is_boss_flow:
        # Pages 1-3 are fixed. A source EOSID that cannot share page 3 may
        # add measured continuation pages here; the remaining boss-flow pages
        # keep their order and are validated from the resulting cursor.
        cursor = 0
        for fixed_index, legacy_markers in enumerate(
            _COMBINED_BOSS_FLOW_PAGES[:3]
        ):
            required_markers = (
                _COMBINED_OPERATIONAL_PAGE_ONE_MARKERS
                if fixed_index == 0
                and "OFP PAGE 1 - FLIGHT BRIEFING"
                in extracted_pages[cursor].upper()
                else legacy_markers
            )
            page_text = extracted_pages[cursor].upper()
            missing = [
                marker for marker in required_markers if marker not in page_text
            ]
            if missing:
                violations.append(ReportQualityViolation(
                    "COMBINED_BOSS_FLOW_STRUCTURE",
                    (
                        f"Flight Briefing page {cursor + 1} is missing "
                        f"{', '.join(missing)}."
                    ),
                ))
            cursor += 1
        eosid_declaration = _COMBINED_EOSID_DECLARATION.search(
            extracted_pages[2]
        )
        eosid_continuations: list[tuple[int, int]] = []
        while cursor < page_count:
            continuation_text = extracted_pages[cursor]
            continuation_upper = continuation_text.upper()
            continuation_match = _COMBINED_EOSID_PAGE.search(
                continuation_text
            )
            if not (
                continuation_match
                and all(
                    marker in continuation_upper
                    for marker in _COMBINED_EOSID_CONTINUATION_MARKERS
                )
            ):
                break
            eosid_continuations.append((
                int(continuation_match.group("index")),
                int(continuation_match.group("count")),
            ))
            cursor += 1
        eosid_structure_valid = True
        if eosid_continuations:
            declared_count = (
                int(eosid_declaration.group("count"))
                if eosid_declaration
                else 0
            )
            declared_start = (
                int(eosid_declaration.group("page"))
                if eosid_declaration
                else 0
            )
            observed_indices = [index for index, _ in eosid_continuations]
            observed_counts = {count for _, count in eosid_continuations}
            eosid_structure_valid = bool(
                eosid_declaration
                and declared_start == 4
                and declared_count == len(eosid_continuations)
                and observed_indices
                == list(range(1, declared_count + 1))
                and observed_counts == {declared_count}
            )
        elif eosid_declaration:
            eosid_structure_valid = False
        if not eosid_structure_valid:
            violations.append(ReportQualityViolation(
                "COMBINED_EOSID_CONTINUATION_STRUCTURE",
                (
                    "EOSID continuation pages must be declared on page 3 "
                    "and form one complete ordered 1/N through N/N sequence."
                ),
            ))
        for flow_index, required_markers in enumerate(
            _COMBINED_BOSS_FLOW_PAGES[3:]
        ):
            page_text = (
                extracted_pages[cursor].upper()
                if cursor < page_count
                else ""
            )
            missing = [
                marker for marker in required_markers if marker not in page_text
            ]
            if missing:
                violations.append(ReportQualityViolation(
                    "COMBINED_BOSS_FLOW_STRUCTURE",
                    (
                        f"Flight Briefing page {cursor + 1} is missing "
                        f"{', '.join(missing)}."
                    ),
                ))
            cursor += 1
            if flow_index == 0:
                while (
                    cursor < page_count
                    and _COMBINED_MEL_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    continuation_text = extracted_pages[cursor].upper()
                    if _COMBINED_CONTINUATION_MARKER not in continuation_text:
                        violations.append(ReportQualityViolation(
                            "COMBINED_DUPLICATE_PRIMARY",
                            (
                                f"Flight Briefing page {cursor + 1} repeats "
                                "the MEL/CDL primary page instead of declaring "
                                "a continuation."
                            ),
                        ))
                    cursor += 1
            elif flow_index == 1:
                edto_detail_pages: list[tuple[int, int]] = []
                while (
                    cursor < page_count
                    and _COMBINED_EDTO_DETAIL_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    page_match = _COMBINED_VAAC_RECEIPT_PAGE.search(
                        extracted_pages[cursor]
                    )
                    edto_detail_pages.append((
                        int(page_match.group("index")) if page_match else 0,
                        int(page_match.group("count")) if page_match else 0,
                    ))
                    cursor += 1
                declaration = _COMBINED_AIRPORT_INDEX_DECLARATION.search(
                    page_text
                )
                airport_index_pages: list[tuple[int, int]] = []
                airport_index_texts: list[str] = []
                while (
                    cursor < page_count
                    and _COMBINED_AIRPORT_INDEX_MARKER
                    in extracted_pages[cursor].upper()
                ):
                    page_match = _COMBINED_AIRPORT_INDEX_PAGE.search(
                        extracted_pages[cursor]
                    )
                    airport_index_texts.append(extracted_pages[cursor])
                    if page_match:
                        airport_index_pages.append((
                            int(page_match.group("index")),
                            int(page_match.group("count")),
                        ))
                    else:
                        airport_index_pages.append((0, 0))
                    cursor += 1

                airport_index_structure_valid = True
                if airport_index_pages:
                    declared_count = (
                        int(declaration.group("count"))
                        if declaration
                        else 0
                    )
                    observed_indices = [
                        index for index, _ in airport_index_pages
                    ]
                    observed_counts = {
                        count for _, count in airport_index_pages
                    }
                    airport_index_structure_valid = bool(
                        declaration
                        and declared_count == len(airport_index_pages)
                        and observed_indices
                        == list(range(1, declared_count + 1))
                        and observed_counts == {declared_count}
                    )
                elif declaration:
                    airport_index_structure_valid = False
                if not airport_index_structure_valid:
                    violations.append(ReportQualityViolation(
                        "COMBINED_AIRPORT_INDEX_STRUCTURE",
                        (
                            "Airport surface/notes index pages must be declared "
                            "on the Airports / Alternates page and form one "
                            "complete ordered 1/N through N/N sequence."
                        ),
                    ))
                if declaration and airport_index_pages:
                    declared_airports = int(declaration.group("airports"))
                    airport_entries: list[tuple[int, int, str]] = []
                    for index_text in airport_index_texts:
                        for line in index_text.splitlines():
                            if "CONTINUED" in line.upper():
                                continue
                            match = _COMBINED_AIRPORT_INDEX_ENTRY.search(line)
                            if match:
                                airport_entries.append((
                                    int(match.group("index")),
                                    int(match.group("count")),
                                    match.group("icao").upper(),
                                ))
                    entries_valid = bool(
                        [index for index, _, _ in airport_entries]
                        == list(range(1, declared_airports + 1))
                        and {count for _, count, _ in airport_entries}
                        == {declared_airports}
                        and len({icao for _, _, icao in airport_entries})
                        == declared_airports
                    )
                    if not entries_valid:
                        violations.append(ReportQualityViolation(
                            "COMBINED_AIRPORT_INDEX_ENTRY_STRUCTURE",
                            (
                                "Airport surface/notes entries must match the "
                                "declared filed-airport count and form one "
                                "unique ordered 1/N through N/N ICAO list."
                            ),
                        ))
                airport_notam_pages: list[tuple[int, int]] = []
                while (
                    cursor < page_count
                    and _COMBINED_AIRPORT_NOTAM_DETAIL_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    page_match = _COMBINED_VAAC_RECEIPT_PAGE.search(
                        extracted_pages[cursor]
                    )
                    airport_notam_pages.append((
                        int(page_match.group("index")) if page_match else 0,
                        int(page_match.group("count")) if page_match else 0,
                    ))
                    cursor += 1
                critical_approach_pages: list[tuple[int, int]] = []
                while (
                    cursor < page_count
                    and _COMBINED_CRITICAL_APPROACH_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    page_match = _COMBINED_VAAC_RECEIPT_PAGE.search(
                        extracted_pages[cursor]
                    )
                    critical_approach_pages.append((
                        int(page_match.group("index")) if page_match else 0,
                        int(page_match.group("count")) if page_match else 0,
                    ))
                    cursor += 1
                shortening_pages: list[tuple[int, int]] = []
                while (
                    cursor < page_count
                    and _COMBINED_RUNWAY_SHORTENING_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    page_match = _COMBINED_VAAC_RECEIPT_PAGE.search(
                        extracted_pages[cursor]
                    )
                    if page_match:
                        shortening_pages.append((
                            int(page_match.group("index")),
                            int(page_match.group("count")),
                        ))
                    else:
                        shortening_pages.append((0, 0))
                    cursor += 1
                if shortening_pages:
                    expected_start = (
                        2
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                        + len(critical_approach_pages)
                    )
                    expected_count = (
                        1
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                        + len(critical_approach_pages)
                        + len(shortening_pages)
                    )
                    if not (
                        [index for index, _ in shortening_pages]
                        == list(range(expected_start, expected_count + 1))
                        and {count for _, count in shortening_pages}
                        == {expected_count}
                    ):
                        violations.append(ReportQualityViolation(
                            "COMBINED_RUNWAY_SHORTENING_STRUCTURE",
                            (
                                "Runway-shortening receipts must form one "
                                "complete ordered Airports continuation "
                                "sequence."
                            ),
                        ))
                if critical_approach_pages:
                    expected_start = (
                        2
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                    )
                    expected_count = (
                        1
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                        + len(critical_approach_pages)
                        + len(shortening_pages)
                    )
                    if not (
                        [index for index, _ in critical_approach_pages]
                        == list(range(
                            expected_start,
                            expected_start + len(critical_approach_pages),
                        ))
                        and {count for _, count in critical_approach_pages}
                        == {expected_count}
                    ):
                        violations.append(ReportQualityViolation(
                            "COMBINED_CRITICAL_APPROACH_STRUCTURE",
                            (
                                "Critical-approach receipts must form one "
                                "complete ordered Airports continuation "
                                "sequence."
                            ),
                        ))
                if edto_detail_pages:
                    expected_count = (
                        1
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                        + len(critical_approach_pages)
                        + len(shortening_pages)
                    )
                    if not (
                        [index for index, _ in edto_detail_pages]
                        == list(range(2, 2 + len(edto_detail_pages)))
                        and {count for _, count in edto_detail_pages}
                        == {expected_count}
                    ):
                        violations.append(ReportQualityViolation(
                            "COMBINED_EDTO_DETAIL_STRUCTURE",
                            (
                                "EDTO timing/alternate receipts must form one "
                                "complete ordered Airports continuation sequence."
                            ),
                        ))
                if airport_notam_pages:
                    expected_start = (
                        2
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                    )
                    expected_count = (
                        1
                        + len(edto_detail_pages)
                        + len(airport_index_pages)
                        + len(airport_notam_pages)
                        + len(critical_approach_pages)
                        + len(shortening_pages)
                    )
                    if not (
                        [index for index, _ in airport_notam_pages]
                        == list(range(
                            expected_start,
                            expected_start + len(airport_notam_pages),
                        ))
                        and {count for _, count in airport_notam_pages}
                        == {expected_count}
                    ):
                        violations.append(ReportQualityViolation(
                            "COMBINED_AIRPORT_NOTAM_DETAIL_STRUCTURE",
                            (
                                "Selected-NOTAM receipts must form one "
                                "complete ordered Airports continuation "
                                "sequence."
                            ),
                        ))
            elif flow_index == 2:
                receipt_pages: list[tuple[int, int]] = []
                while (
                    cursor < page_count
                    and _COMBINED_VAAC_RECEIPT_TITLE
                    in extracted_pages[cursor].upper()
                ):
                    receipt_text = extracted_pages[cursor]
                    receipt_match = _COMBINED_VAAC_RECEIPT_PAGE.search(
                        receipt_text
                    )
                    if receipt_match:
                        receipt_pages.append((
                            int(receipt_match.group("index")),
                            int(receipt_match.group("count")),
                        ))
                    else:
                        receipt_pages.append((0, 0))
                    cursor += 1
                if receipt_pages:
                    expected_count = len(receipt_pages) + 1
                    if not (
                        [index for index, _ in receipt_pages]
                        == list(range(2, expected_count + 1))
                        and {count for _, count in receipt_pages}
                        == {expected_count}
                    ):
                        violations.append(ReportQualityViolation(
                            "COMBINED_VAAC_RECEIPT_STRUCTURE",
                            (
                                "VAAC receipt pages must form one complete "
                                "ordered weather continuation sequence."
                            ),
                        ))
        for page_index in range(cursor, page_count):
            page_text = extracted_pages[page_index].upper()
            if not (
                all(marker in page_text for marker in _COMBINED_TERRAIN_MARKERS)
                or _COMBINED_PROFILE_TITLE in page_text
            ):
                violations.append(ReportQualityViolation(
                    "COMBINED_CONDITIONAL_TERRAIN_STRUCTURE",
                    (
                        f"Flight Briefing page {page_index + 1} must be an "
                        "actual terrain/profile evidence page."
                    ),
                ))
        return {
            "valid": not violations,
            "page_count": page_count,
            "violations": violations,
        }

    if page_count >= 4:
        for page_index, required_markers in enumerate(_COMBINED_FIXED_PREFIX):
            page_text = extracted_pages[page_index].upper()
            if not all(marker in page_text for marker in required_markers):
                violations.append(ReportQualityViolation(
                    "COMBINED_PAGE_STRUCTURE",
                    (
                        f"Flight Briefing page {page_index + 1} must contain "
                        f"{', '.join(required_markers)}."
                    ),
                ))

        cursor = len(_COMBINED_FIXED_PREFIX)
        if cursor >= page_count or not all(
            marker in extracted_pages[cursor].upper()
            for marker in _COMBINED_ANALYSIS_MARKERS
        ):
            violations.append(ReportQualityViolation(
                "COMBINED_PAGE_STRUCTURE",
                (
                    f"Flight Briefing page {cursor + 1} must contain "
                    f"{', '.join(_COMBINED_ANALYSIS_MARKERS)}."
                ),
            ))
        else:
            if _COMBINED_CONTINUATION_MARKER in extracted_pages[cursor].upper():
                violations.append(ReportQualityViolation(
                    "COMBINED_CONTINUATION_ORDER",
                    "DECISION ANALYSIS must have exactly one primary page first.",
                ))
            cursor += 1
            while (
                cursor < page_count
                and "DECISION ANALYSIS" in extracted_pages[cursor].upper()
            ):
                continuation_text = extracted_pages[cursor].upper()
                if _COMBINED_CONTINUATION_MARKER not in continuation_text:
                    violations.append(ReportQualityViolation(
                        "COMBINED_DUPLICATE_PRIMARY",
                        (
                            f"Flight Briefing page {cursor + 1} repeats the "
                            "DECISION ANALYSIS primary page instead of "
                            "declaring a continuation."
                        ),
                    ))
                cursor += 1

        mel_pages = 0
        while cursor < page_count and _COMBINED_MEL_TITLE in extracted_pages[cursor].upper():
            mel_pages += 1
            cursor += 1
        if mel_pages == 0:
            violations.append(ReportQualityViolation(
                "COMBINED_MEL_STRUCTURE",
                "Flight Briefing must contain at least one MEL/CDL and CDDL page.",
            ))

        for accepted_markers in _COMBINED_CONTINUABLE_SECTIONS:
            primary_text = (
                extracted_pages[cursor].upper()
                if cursor < page_count
                else ""
            )
            section_marker = next(
                (
                    marker
                    for marker in accepted_markers
                    if marker in primary_text
                ),
                None,
            )
            if section_marker is None:
                violations.append(ReportQualityViolation(
                    "COMBINED_PAGE_STRUCTURE",
                    (
                        f"Flight Briefing page {cursor + 1} must contain "
                        f"{' or '.join(accepted_markers)}."
                    ),
                ))
                continue
            if _COMBINED_CONTINUATION_MARKER in primary_text:
                violations.append(ReportQualityViolation(
                    "COMBINED_CONTINUATION_ORDER",
                    (
                        f"Flight Briefing page {cursor + 1} starts "
                        f"{section_marker} as a continuation; "
                        "the section must have exactly one primary page first."
                    ),
                ))
            cursor += 1
            while (
                cursor < page_count
                and section_marker in extracted_pages[cursor].upper()
            ):
                continuation_text = extracted_pages[cursor].upper()
                if _COMBINED_CONTINUATION_MARKER not in continuation_text:
                    violations.append(ReportQualityViolation(
                        "COMBINED_DUPLICATE_PRIMARY",
                        (
                            f"Flight Briefing page {cursor + 1} repeats the "
                            f"{section_marker} primary page instead "
                            "of declaring a continuation."
                        ),
                    ))
                cursor += 1

        if cursor >= page_count or not all(
            marker in extracted_pages[cursor].upper()
            for marker in _COMBINED_TERRAIN_MARKERS
        ):
            violations.append(ReportQualityViolation(
                "COMBINED_PAGE_STRUCTURE",
                (
                    f"Flight Briefing page {cursor + 1} must contain "
                    f"{', '.join(_COMBINED_TERRAIN_MARKERS)}."
                ),
            ))
        else:
            if _COMBINED_CONTINUATION_MARKER in extracted_pages[cursor].upper():
                violations.append(ReportQualityViolation(
                    "COMBINED_CONTINUATION_ORDER",
                    "The terrain section must have exactly one primary page first.",
                ))
            cursor += 1
            while cursor < page_count and all(
                marker in extracted_pages[cursor].upper()
                for marker in _COMBINED_TERRAIN_MARKERS
            ):
                continuation_text = extracted_pages[cursor].upper()
                if _COMBINED_CONTINUATION_MARKER not in continuation_text:
                    violations.append(ReportQualityViolation(
                        "COMBINED_DUPLICATE_PRIMARY",
                        (
                            f"Flight Briefing page {cursor + 1} repeats the "
                            "terrain primary page instead of declaring a "
                            "continuation."
                        ),
                    ))
                cursor += 1

        while cursor < page_count:
            if _COMBINED_PROFILE_TITLE not in extracted_pages[cursor].upper():
                violations.append(ReportQualityViolation(
                    "COMBINED_PROFILE_STRUCTURE",
                    (
                        f"Flight Briefing page {cursor + 1} must be a governed "
                        "depressurisation profile source-chart page."
                    ),
                ))
            cursor += 1

    return {
        "valid": not violations,
        "page_count": page_count,
        "violations": violations,
    }


def assert_combined_briefing_quality(path: Path) -> dict[str, Any]:
    result = validate_combined_briefing_pdf(path)
    if not result["valid"]:
        raise ReportQualityError(result["violations"])
    return result


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
            is_governed_table_continuation = any(
                marker.lower() in appended_text
                for marker in _LEVEL_2_GOVERNED_TABLE_CONTINUATION_MARKERS
            )
            if is_source_chart:
                source_chart_seen = True
                continue
            if is_notam_continuation and not source_chart_seen:
                continue
            if is_aip_supplement and not source_chart_seen:
                continue
            if is_governed_table_continuation and not source_chart_seen:
                continue
            if not is_source_chart:
                violations.append(ReportQualityViolation(
                    "LEVEL_2_APPENDIX_STRUCTURE",
                    (
                        f"Level 2 page {page_index + 1} must be a NOTAM "
                        "continuation, AIP supplement detail, or governed "
                        "weather/advisory continuation page before the source "
                        "charts, or an embedded depressurisation source-chart "
                        "page."
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
    "assert_combined_briefing_quality",
    "assert_report_quality",
    "validate_combined_briefing_pdf",
    "validate_report_pdf",
]
