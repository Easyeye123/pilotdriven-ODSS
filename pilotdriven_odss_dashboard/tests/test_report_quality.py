from __future__ import annotations

from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss.report_quality import (
    ReportQualityError,
    assert_report_quality,
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
                "Filed route from CFP coordinates",
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
            "Filed route from CFP coordinates",
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
