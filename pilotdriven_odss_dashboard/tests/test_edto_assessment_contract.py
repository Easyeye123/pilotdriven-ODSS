from __future__ import annotations

from app.odss.briefing import build_briefing_view
from app.odss.parser import parse_lido


def _lido_pages(flight_number: str, edto_page: str) -> list[str]:
    return [
        f"""SUMMARY EDTO CFP
9VAAA {flight_number} SIN/BKK ETD 0250 01AUG26
SCHED DEP 0250 UTC SCHED ARR 0520 UTC
RTE NO 001 A350-941
WSSS/20C
DCT BOBI1 DCT BOBI2
VTBS/19L
GND  MILES    900
AIR  MILES    930
BURNOFF 02.00 010000
TAXI FUEL 001000
FLT PLAN REQMT 03.00 015000
FUEL IN TANKS 04.00 020000
PZFW 180000
PTOW 200000
PLWT 190000
""",
        edto_page,
        "",
        "",
        "",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]


def _complete_standard_lido_pages(flight_number: str) -> list[str]:
    pages = _lido_pages(flight_number, "")
    pages[0] = pages[0].replace("SUMMARY EDTO CFP", "SUMMARY STANDARD CFP")
    page_count = len(pages)
    return [
        f"PAGE {index} OF {page_count} {flight_number} SIN/BKK 01AUG26\n{page}"
        for index, page in enumerate(pages, start=1)
    ]


def test_sq722_nil_requires_explicit_cfp_declaration_and_evidence() -> None:
    flight = parse_lido(
        _lido_pages("SQ722", "EDTO STATUS: NIL"),
        "SQ722-controlled-cfp.pdf",
    )
    briefing = build_briefing_view(flight, [], [])

    assert flight["edto"]["assessment"]["status"] == "verified_not_applicable"
    assert flight["edto"]["assessment"]["evidence"] == [{
        "source": "uploaded_company_cfp",
        "document_id": "SQ722-controlled-cfp.pdf",
        "source_page": 2,
        "reason_code": "explicit_edto_not_applicable_declaration",
    }]
    assert briefing["edto"]["assessment"]["status"] == "verified_not_applicable"


def test_sq722_complete_standard_lido_without_edto_section_is_verified_nil() -> None:
    flight = parse_lido(
        _complete_standard_lido_pages("SQ722"),
        "SQ722-complete-standard-cfp.pdf",
    )
    briefing = build_briefing_view(flight, [], [])

    assert flight["edto"]["assessment"] == {
        "status": "verified_not_applicable",
        "evidence": [{
            "source": "uploaded_company_cfp",
            "document_id": "SQ722-complete-standard-cfp.pdf",
            "source_page": 1,
            "source_page_start": 1,
            "source_page_end": 7,
            "source_page_count": 7,
            "reason_code": "complete_lido_cfp_no_edto_section",
        }],
    }
    assert briefing["edto"]["assessment"]["status"] == "verified_not_applicable"


def test_partial_standard_lido_without_edto_section_requires_review() -> None:
    pages = [
        page.replace("OF 7", "OF 8", 1)
        for page in _complete_standard_lido_pages("SQ722")
    ]
    # The parseable content is present, but the Lido header proves page 8/8
    # is missing. Absence of EDTO therefore cannot be promoted to verified NIL.
    flight = parse_lido(pages, "SQ722-truncated-standard-cfp.pdf")

    assert flight["edto"]["assessment"]["status"] == "review_required"
    assert (
        flight["edto"]["assessment"]["evidence"][-1]["reason_code"]
        == "explicit_edto_assessment_missing"
    )


def test_sq23_positive_edto_requires_parsed_operational_evidence() -> None:
    flight = parse_lido(
        _lido_pages(
            "SQ23",
            "EDTO INFORMATION\nWIMM 0900-1200 23 ILS 200FT",
        ),
        "SQ23-controlled-cfp.pdf",
    )
    briefing = build_briefing_view(flight, [], [])

    assessment = flight["edto"]["assessment"]
    assert assessment["status"] == "affected"
    assert assessment["evidence"][0]["reason_code"] == "parsed_edto_operational_data"
    assert assessment["evidence"][0]["airport_count"] == 1
    assert briefing["edto"]["assessment"]["status"] == "affected"
    assert briefing["edto"]["airports"][0]["airport"] == "WIMM"


def test_edto_section_continuation_page_preserves_every_sector_and_airport() -> None:
    pages = _lido_pages(
        "SQ24",
        """EDTO INFORMATION:
       7.17 N4125.4 RJCC
ENTRY1      E15100.4
       8.40 N4859.9 PASY
EXIT1       E16437.2
      10.09 N5626.2 PASY
ENTRY2      W17533.1
""",
    )
    pages.insert(
        2,
        """      10.11 N5634.7 PACD
EXIT2       W17503.9
EDTO ENROUTE ALTN AIRPORTS:
RJCC 1157-1706 19R CAT3B 220FT/950M
PANC 1527-2123 07R CAT3B 220FT/982M
""",
    )

    flight = parse_lido(pages, "SQ24-multipage-controlled-cfp.pdf")

    assert [sector["number"] for sector in flight["edto"]["sectors"]] == [1, 2]
    assert flight["edto"]["entry_actm_minutes"] == 437
    assert flight["edto"]["exit_actm_minutes"] == 520
    assert [item["airport"] for item in flight["edto"]["airports"]] == ["RJCC", "PANC"]


def test_empty_edto_section_fails_closed_to_review_required() -> None:
    flight = parse_lido(
        _lido_pages("SQ722", "EDTO INFORMATION"),
        "SQ722-unverified-cfp.pdf",
    )
    briefing = build_briefing_view(flight, [], [])

    assert flight["edto"]["assessment"]["status"] == "review_required"
    assert (
        flight["edto"]["assessment"]["evidence"][-1]["reason_code"]
        == "explicit_edto_assessment_missing"
    )
    assert briefing["edto"]["assessment"]["status"] == "review_required"
    assert briefing["status"] == "REVIEW REQUIRED"


def test_explicit_nil_conflicting_with_operational_data_requires_review() -> None:
    flight = parse_lido(
        _lido_pages(
            "SQ722",
            "EDTO INFORMATION\nEDTO STATUS: NIL\nWIMM 0900-1200 23 ILS 200FT",
        ),
        "SQ722-conflicting-cfp.pdf",
    )
    briefing = build_briefing_view(flight, [], [])

    assert flight["edto"]["assessment"]["status"] == "review_required"
    assert (
        flight["edto"]["assessment"]["evidence"][-1]["reason_code"]
        == "conflicting_edto_applicability_evidence"
    )
    assert briefing["edto"]["assessment"]["status"] == "review_required"
