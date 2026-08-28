from __future__ import annotations

from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss.report_quality import (
    ReportQualityError,
    assert_report_quality,
    validate_combined_briefing_pdf,
    validate_report_pdf,
)
from app.odss.operational_brief import (
    REPORT_TYPOGRAPHY as LEVEL2_TYPOGRAPHY,
)
from app.odss.pertinent_brief import (
    REPORT_TYPOGRAPHY as LEVEL1_TYPOGRAPHY,
)


def _pdf(
    path: Path,
    *,
    pages: int,
    text: str = "Pilot briefing",
    page_texts: list[str] | None = None,
) -> None:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=841.89, height=595.28)
        page.insert_text(
            (40, 50),
            page_texts[index] if page_texts is not None else text,
        )
    document.save(path)
    document.close()


def test_quality_gate_accepts_three_page_a4_landscape_level1(tmp_path: Path) -> None:
    path = tmp_path / "level1.pdf"
    _pdf(
        path,
        pages=3,
        page_texts=[
                "APPLICABLE NOTAMS WITHIN STD / STA ±2 HOURS\n"
                "Filed route from OFP coordinates",
            "SQ304 - OPERATIONAL TIMING",
            "DEPRESSURISATION PROFILE ANALYSIS",
        ],
    )

    result = assert_report_quality(path, level=1)

    assert result["valid"] is True
    assert result["page_count"] == 3


def test_quality_gate_accepts_non_sq_level1_operational_timing_title(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level1-other-carrier.pdf"
    _pdf(
        path,
        pages=3,
        page_texts=[
            "APPLICABLE NOTAMS WITHIN STD / STA +/- 2 HOURS\n"
            "Filed route from OFP coordinates",
            "BAW304 - OPERATIONAL TIMING",
            "DEPRESSURISATION PROFILE ANALYSIS",
        ],
    )

    result = validate_report_pdf(path, level=1)

    assert result["valid"] is True
    assert not any(
        item.code == "LEVEL_1_PAGE_2_STRUCTURE"
        for item in result["violations"]
    )


def test_report_typography_tokens_keep_pilot_content_legible() -> None:
    assert LEVEL1_TYPOGRAPHY["body"] >= 10.0
    assert LEVEL1_TYPOGRAPHY["body_small"] >= 10.0
    assert LEVEL1_TYPOGRAPHY["body_light"] >= 10.0
    assert LEVEL1_TYPOGRAPHY["body_light_small"] >= 10.0
    assert LEVEL1_TYPOGRAPHY["metric"] >= 10.0
    assert LEVEL2_TYPOGRAPHY["body"] >= 10.0
    assert LEVEL2_TYPOGRAPHY["body_small"] >= 10.0
    assert LEVEL2_TYPOGRAPHY["table_body"] >= 10.0
    assert LEVEL2_TYPOGRAPHY["detail_label"] >= 10.0
    assert LEVEL2_TYPOGRAPHY["detail_value"] >= 10.0


def test_quality_gate_rejects_extra_level1_pages(tmp_path: Path) -> None:
    path = tmp_path / "level1-extra.pdf"
    _pdf(path, pages=4)

    with pytest.raises(ReportQualityError) as exc_info:
        assert_report_quality(path, level=1)

    assert any(
        item.code == "LEVEL_1_PAGE_CONTRACT"
        for item in exc_info.value.violations
    )


def _combined_pages(*middle: str) -> list[str]:
    return [
        "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS",
        "FLIGHT BRIEFING\nDECISION ANALYSIS\nFLIGHT-PHASE DECISION TIMELINE",
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL",
        *[f"FLIGHT BRIEFING\n{text}" for text in middle],
        "FLIGHT BRIEFING\nHIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
    ]


def test_combined_quality_gate_accepts_lossless_eosid_continuation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-eosid-continuation.pdf"
    page_texts = [
        (
            "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS\nRELEASE\nBEFORE PUSH\nROUTE\nARRIVAL\n"
            "PERFORMANCE\nFUEL\nSTATUS\nWEATHER\nALTERNATES"
        ),
        (
            "FLIGHT BRIEFING\nDECISION ANALYSIS\n"
            "FLIGHT-PHASE DECISION TIMELINE\nSOURCE"
        ),
        (
            "FLIGHT BRIEFING\nPERFORMANCE / FUEL / STATUS\n"
            "RECONCILIATION / RELEASE REVIEW\n"
            "EOSID LOSSLESS CONTINUATION: 1 PAGE START P4"
        ),
        (
            "FLIGHT BRIEFING\nEOSID / ESCAPE ROUTING\n"
            "LOSSLESS CONTINUATION 1/1"
        ),
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL\nSOURCE DECLARATION",
        (
            "FLIGHT BRIEFING\nAIRPORTS / ALTERNATES\n"
            "DESTINATION ALTERNATE ASSESSMENT MATRIX"
        ),
        (
            "FLIGHT BRIEFING\nWEATHER / ROUTE HAZARDS\n"
            "NAMED DIRECT / OFP VOLCANO ADVISORIES"
        ),
        (
            "FLIGHT BRIEFING\nENROUTE / ASSURANCE\n"
            "NUMBERED RELEASE GATES\nSOURCE ASSURANCE"
        ),
        (
            "FLIGHT BRIEFING\nCOVERAGE CHECKLIST\n"
            "CAT / VWS EVIDENCE\nAIREP / PIREP"
        ),
    ]
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_accepts_declared_airport_index_pages(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-airport-index.pdf"
    airport_codes = [
        "FAOR", "FMMI", "FIMP", "VCBI", "WIMM", "WITT", "WADD",
        "WMKK", "WSSS", "WMSA", "VTBS", "VHHH", "RCTP", "RPLL",
        "VVTS", "VVDN", "WIHH", "WIII", "WBSB",
    ]
    page_texts = [
        (
            "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS\nRELEASE\nBEFORE PUSH\nROUTE\nARRIVAL\n"
            "PERFORMANCE\nFUEL\nSTATUS\nWEATHER\nALTERNATES"
        ),
        (
            "FLIGHT BRIEFING\nDECISION ANALYSIS\n"
            "FLIGHT-PHASE DECISION TIMELINE\nSOURCE"
        ),
        (
            "FLIGHT BRIEFING\nPERFORMANCE / FUEL / STATUS\n"
            "RECONCILIATION / RELEASE REVIEW"
        ),
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL\nSOURCE DECLARATION",
        (
            "FLIGHT BRIEFING\nAIRPORTS / ALTERNATES\n"
            "DESTINATION ALTERNATE ASSESSMENT MATRIX\n"
            "19 FILED SURFACE/NOTES AIRPORTS · 2 INDEX PAGES FOLLOW"
        ),
        (
            "FLIGHT BRIEFING\nAIRPORT SURFACE / NOTES INDEX · 1/2\n"
            + "\n".join(
                f"AIRPORT {index}/19 · {code}"
                for index, code in enumerate(airport_codes[:10], start=1)
            )
        ),
        (
            "FLIGHT BRIEFING\nAIRPORT SURFACE / NOTES INDEX · 2/2\n"
            + "\n".join(
                f"AIRPORT {index}/19 · {code}"
                for index, code in enumerate(airport_codes[10:], start=11)
            )
        ),
        (
            "FLIGHT BRIEFING\nWEATHER / ROUTE HAZARDS\n"
            "NAMED DIRECT / OFP VOLCANO ADVISORIES"
        ),
        (
            "FLIGHT BRIEFING\nENROUTE / ASSURANCE\n"
            "NUMBERED RELEASE GATES\nSOURCE ASSURANCE"
        ),
        (
            "FLIGHT BRIEFING\nCOVERAGE CHECKLIST\n"
            "CAT / VWS EVIDENCE\nAIREP / PIREP"
        ),
    ]
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_rejects_broken_airport_index_sequence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-broken-airport-index.pdf"
    page_texts = [
        (
            "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS\nRELEASE\nBEFORE PUSH\nROUTE\nARRIVAL\n"
            "PERFORMANCE\nFUEL\nSTATUS\nWEATHER\nALTERNATES"
        ),
        (
            "FLIGHT BRIEFING\nDECISION ANALYSIS\n"
            "FLIGHT-PHASE DECISION TIMELINE\nSOURCE"
        ),
        (
            "FLIGHT BRIEFING\nPERFORMANCE / FUEL / STATUS\n"
            "RECONCILIATION / RELEASE REVIEW"
        ),
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL\nSOURCE DECLARATION",
        (
            "FLIGHT BRIEFING\nAIRPORTS / ALTERNATES\n"
            "DESTINATION ALTERNATE ASSESSMENT MATRIX\n"
            "19 FILED SURFACE/NOTES AIRPORTS · 2 INDEX PAGES FOLLOW"
        ),
        "FLIGHT BRIEFING\nAIRPORT SURFACE / NOTES INDEX · 2/2\nAIRPORT 1/19 · FAOR",
        (
            "FLIGHT BRIEFING\nWEATHER / ROUTE HAZARDS\n"
            "NAMED DIRECT / OFP VOLCANO ADVISORIES"
        ),
        (
            "FLIGHT BRIEFING\nENROUTE / ASSURANCE\n"
            "NUMBERED RELEASE GATES\nSOURCE ASSURANCE"
        ),
        (
            "FLIGHT BRIEFING\nCOVERAGE CHECKLIST\n"
            "CAT / VWS EVIDENCE\nAIREP / PIREP"
        ),
    ]
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        violation.code == "COMBINED_AIRPORT_INDEX_STRUCTURE"
        for violation in result["violations"]
    )


def test_combined_quality_gate_rejects_missing_operational_coverage_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-missing-coverage.pdf"
    page_texts = [
        (
            "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS\nRELEASE\nBEFORE PUSH\nROUTE\nARRIVAL\n"
            "PERFORMANCE\nFUEL\nSTATUS\nWEATHER\nALTERNATES"
        ),
        (
            "FLIGHT BRIEFING\nDECISION ANALYSIS\n"
            "FLIGHT-PHASE DECISION TIMELINE\nSOURCE"
        ),
        (
            "FLIGHT BRIEFING\nPERFORMANCE / FUEL / STATUS\n"
            "RECONCILIATION / RELEASE REVIEW"
        ),
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL\nSOURCE DECLARATION",
        (
            "FLIGHT BRIEFING\nAIRPORTS / ALTERNATES\n"
            "DESTINATION ALTERNATE ASSESSMENT MATRIX"
        ),
        (
            "FLIGHT BRIEFING\nWEATHER / ROUTE HAZARDS\n"
            "NAMED DIRECT / OFP VOLCANO ADVISORIES"
        ),
        (
            "FLIGHT BRIEFING\nENROUTE / ASSURANCE\n"
            "NUMBERED RELEASE GATES\nSOURCE ASSURANCE"
        ),
        "FLIGHT BRIEFING\nHIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
    ]
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        violation.code == "COMBINED_BOSS_FLOW_STRUCTURE"
        and "COVERAGE CHECKLIST" in violation.message
        for violation in result["violations"]
    )


@pytest.mark.parametrize(
    ("declaration", "continuations"),
    [
        (
            "EOSID LOSSLESS CONTINUATION: 2 PAGES START P4",
            ["LOSSLESS CONTINUATION 2/2"],
        ),
        (
            "EOSID LOSSLESS CONTINUATION: 2 PAGES START P4",
            ["LOSSLESS CONTINUATION 1/2", "LOSSLESS CONTINUATION 1/2"],
        ),
        (
            "EOSID LOSSLESS CONTINUATION: 2 PAGES START P4",
            ["LOSSLESS CONTINUATION 1/2", "LOSSLESS CONTINUATION 2/3"],
        ),
        ("", ["LOSSLESS CONTINUATION 1/1"]),
    ],
    ids=[
        "missing-first-page",
        "duplicate-index",
        "inconsistent-total",
        "undeclared-continuation",
    ],
)
def test_combined_quality_gate_rejects_broken_eosid_continuation_sequence(
    tmp_path: Path,
    declaration: str,
    continuations: list[str],
) -> None:
    path = tmp_path / "combined-broken-eosid-continuation.pdf"
    page_texts = [
        (
            "FLIGHT BRIEFING\nOFP P1 - ROUTE / LEVELS\nRELEASE\nBEFORE PUSH\nROUTE\nARRIVAL\n"
            "PERFORMANCE\nFUEL\nSTATUS\nWEATHER\nALTERNATES"
        ),
        (
            "FLIGHT BRIEFING\nDECISION ANALYSIS\n"
            "FLIGHT-PHASE DECISION TIMELINE\nSOURCE"
        ),
        (
            "FLIGHT BRIEFING\nPERFORMANCE / FUEL / STATUS\n"
            "RECONCILIATION / RELEASE REVIEW\n"
            + declaration
        ),
        *[
            "FLIGHT BRIEFING\nEOSID / ESCAPE ROUTING\n" + continuation
            for continuation in continuations
        ],
        "FLIGHT BRIEFING\nMEL/CDL AND CDDL\nSOURCE DECLARATION",
        (
            "FLIGHT BRIEFING\nAIRPORTS / ALTERNATES\n"
            "DESTINATION ALTERNATE ASSESSMENT MATRIX"
        ),
        (
            "FLIGHT BRIEFING\nWEATHER / ROUTE HAZARDS\n"
            "NAMED DIRECT / OFP VOLCANO ADVISORIES"
        ),
        (
            "FLIGHT BRIEFING\nENROUTE / ASSURANCE\n"
            "NUMBERED RELEASE GATES\nSOURCE ASSURANCE"
        ),
        (
            "FLIGHT BRIEFING\nCOVERAGE CHECKLIST\n"
            "CAT / VWS EVIDENCE\nAIREP / PIREP"
        ),
    ]
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        violation.code == "COMBINED_EOSID_CONTINUATION_STRUCTURE"
        for violation in result["violations"]
    )


def test_combined_quality_gate_accepts_ordered_section_continuations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-continuations.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "EDTO / ENROUTE AIRPORTS - CONTINUED (2/2)",
        "AIRPORTS / NOTAM APPLICABILITY",
        "AIRPORTS / NOTAM APPLICABILITY - CONTINUED (2/2)",
        "OPERATIONAL HAZARD ASSESSMENT",
        "OPERATIONAL HAZARD ASSESSMENT - CONTINUED (2/2)",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_accepts_non_edto_destination_alternates_section(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-non-edto.pdf"
    page_texts = _combined_pages(
        "DESTINATION ALTERNATES",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_rejects_mixed_alternate_section_continuations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-mixed-alternate-sections.pdf"
    page_texts = _combined_pages(
        "DESTINATION ALTERNATES",
        "EDTO / ENROUTE AIRPORTS - CONTINUED (2/2)",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        violation.code == "COMBINED_PAGE_STRUCTURE"
        for violation in result["violations"]
    )


def test_combined_quality_gate_accepts_critical_analysis_continuation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-analysis-continuation.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts.insert(
        2,
        "FLIGHT BRIEFING\nDECISION ANALYSIS - CONTINUED (2/2)\nFIR / NEXT CONTACT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_rejects_duplicate_analysis_primary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-duplicate-analysis-primary.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts.insert(
        2,
        "FLIGHT BRIEFING\nDECISION ANALYSIS\nFIR / NEXT CONTACT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        item.code == "COMBINED_DUPLICATE_PRIMARY"
        for item in result["violations"]
    )


def test_combined_quality_gate_rejects_wrong_continuation_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-wrong-order.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "OPERATIONAL HAZARD ASSESSMENT",
        "AIRPORTS / NOTAM APPLICABILITY",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(item.code == "COMBINED_PAGE_STRUCTURE" for item in result["violations"])


def test_combined_quality_gate_rejects_duplicate_section_primary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-duplicate-primary.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(item.code == "COMBINED_DUPLICATE_PRIMARY" for item in result["violations"])


def test_combined_quality_gate_accepts_terrain_continuation_before_profiles(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-terrain-continuation.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts.extend((
        "FLIGHT BRIEFING\nHIGH TERRAIN EXPOSURE AND DEPRESSURISATION "
        "- CONTINUED (2/2)\nALL TERRAIN EVENTS / UNMATCHED EXPOSURES",
        "FLIGHT BRIEFING\nDEPRESSURISATION PROFILE SOURCE CHART",
    ))
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


def test_combined_quality_gate_rejects_duplicate_terrain_primary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-duplicate-terrain-primary.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts.append(
        "FLIGHT BRIEFING\nHIGH TERRAIN EXPOSURE AND DEPRESSURISATION\n"
        "ALL TERRAIN EVENTS / UNMATCHED EXPOSURES"
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        item.code == "COMBINED_DUPLICATE_PRIMARY"
        for item in result["violations"]
    )


def test_combined_quality_gate_rejects_terrain_continuation_after_profile(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-late-terrain-continuation.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts.extend((
        "FLIGHT BRIEFING\nDEPRESSURISATION PROFILE SOURCE CHART",
        "FLIGHT BRIEFING\nHIGH TERRAIN EXPOSURE AND DEPRESSURISATION "
        "- CONTINUED (2/2)\nALL TERRAIN EVENTS / UNMATCHED EXPOSURES",
    ))
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        item.code == "COMBINED_PROFILE_STRUCTURE"
        for item in result["violations"]
    )


def test_combined_quality_gate_rejects_standalone_retired_layout_label(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-retired-layout-label.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    page_texts[0] += "\nLEVEL 2"
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is False
    assert any(
        item.code == "COMBINED_RETIRED_LABEL"
        for item in result["violations"]
    )


def test_combined_quality_gate_allows_level_text_inside_source_fact(
    tmp_path: Path,
) -> None:
    path = tmp_path / "combined-source-level-text.pdf"
    page_texts = _combined_pages(
        "EDTO / ENROUTE AIRPORTS",
        (
            "AIRPORTS / NOTAM APPLICABILITY\n"
            "ILS RWY 08R DOWNGRADED TO CAT I, LEVEL 2 "
            "(ICAO CLASSIFICATION I/E/2)."
        ),
        "OPERATIONAL HAZARD ASSESSMENT",
    )
    _pdf(path, pages=len(page_texts), page_texts=page_texts)

    result = validate_combined_briefing_pdf(path)

    assert result["valid"] is True
    assert result["violations"] == []


@pytest.mark.parametrize(
    ("page_texts", "expected_code"),
    (
        (
            [
                "Natural Earth 1:110m land context",
                "SQ304 - OPERATIONAL TIMING",
                "DEPRESSURISATION PROFILE ANALYSIS",
            ],
            "LEVEL_1_NOTAM_WINDOW_HEADING",
        ),
        (
            [
                "APPLICABLE NOTAMS WITHIN STD / STA +/- 2 HOURS\n"
                "Natural Earth 1:110m land context",
                "SQ304 - OPERATIONAL DETAIL",
                "DEPRESSURISATION PROFILE ANALYSIS",
            ],
            "LEVEL_1_PAGE_2_STRUCTURE",
        ),
        (
            [
                "APPLICABLE NOTAMS WITHIN STD / STA +/- 2 HOURS\n"
                "Natural Earth 1:110m land context",
                "SQ304 - OPERATIONAL TIMING",
                "SQ304 - ROUTE / CONTINGENCY",
            ],
            "LEVEL_1_PAGE_3_STRUCTURE",
        ),
        (
            [
                "APPLICABLE NOTAMS WITHIN STD / STA +/- 2 HOURS\n"
                "Natural Earth 1:110m land context",
                "SQ304 - OPERATIONAL TIMING\n"
                "Natural Earth 1:110m land context",
                "DEPRESSURISATION PROFILE ANALYSIS",
            ],
            "LEVEL_1_SINGLE_MAP_CONTRACT",
        ),
    ),
)
def test_quality_gate_rejects_level1_structure_regressions(
    tmp_path: Path,
    page_texts: list[str],
    expected_code: str,
) -> None:
    path = tmp_path / "level1-structure.pdf"
    _pdf(path, pages=3, page_texts=page_texts)

    result = validate_report_pdf(path, level=1)

    assert result["valid"] is False
    assert any(item.code == expected_code for item in result["violations"])


@pytest.mark.parametrize("wording", ("Manual RAG", "canonical route", "Trigger: RWY"))
def test_quality_gate_rejects_internal_pilot_wording(
    tmp_path: Path,
    wording: str,
) -> None:
    path = tmp_path / "level3.pdf"
    _pdf(path, pages=1, text=wording)

    result = validate_report_pdf(path, level=3, level3_status="PARTIAL")

    assert result["valid"] is False
    assert any(item.code.startswith("PILOT_") for item in result["violations"])


def test_quality_gate_requires_fixed_level2_page_contract(tmp_path: Path) -> None:
    path = tmp_path / "level2.pdf"
    _pdf(
        path,
        pages=7,
        page_texts=[
            "ANALYSIS OVERVIEW",
            "PERFORMANCE, FUEL AND AIRPORT BASIS",
            "FLIGHT-WINDOW NOTAM APPLICABILITY",
            "EDTO SECTORS AND SUITABILITY INPUTS",
            "OCEANIC AND FIR COMMUNICATIONS",
            "DEPRESSURISATION PROFILE MATCH MATRIX",
            "WEATHER AND PROMOTION RESULT",
        ],
    )

    result = assert_report_quality(path, level=2)

    assert result["valid"] is True
    assert result["page_count"] == 7


def test_quality_gate_rejects_incomplete_fail_closed_advisory_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level2-clipped-advisory.pdf"
    _pdf(
        path,
        pages=7,
        page_texts=[
            "ANALYSIS OVERVIEW",
            "PERFORMANCE, FUEL AND AIRPORT BASIS",
            "FLIGHT-WINDOW NOTAM APPLICABILITY",
            "EDTO SECTORS AND SUITABILITY INPUTS",
            "OCEANIC AND FIR COMMUNICATIONS",
            "DEPRESSURISATION PROFILE MATCH MATRIX",
            (
                "WEATHER AND PROMOTION RESULT\n"
                "Volcanic ash review required\n"
                "The official sources could not safely confirm that volcanic ash is not"
            ),
        ],
    )

    result = validate_report_pdf(path, level=2)

    assert result["valid"] is False
    assert any(
        item.code == "LEVEL_2_ADVISORY_RESULT_INCOMPLETE"
        for item in result["violations"]
    )


def test_quality_gate_rejects_wrong_level2_page_order(tmp_path: Path) -> None:
    path = tmp_path / "level2-wrong-order.pdf"
    _pdf(
        path,
        pages=7,
        page_texts=[
            "ANALYSIS OVERVIEW",
            "FLIGHT-WINDOW NOTAM APPLICABILITY",
            "PERFORMANCE, FUEL AND AIRPORT BASIS",
            "EDTO SECTORS AND SUITABILITY INPUTS",
            "OCEANIC AND FIR COMMUNICATIONS",
            "DEPRESSURISATION PROFILE MATCH MATRIX",
            "WEATHER AND PROMOTION RESULT",
        ],
    )

    result = validate_report_pdf(path, level=2)

    assert result["valid"] is False
    assert any(item.code == "LEVEL_2_PAGE_STRUCTURE" for item in result["violations"])
