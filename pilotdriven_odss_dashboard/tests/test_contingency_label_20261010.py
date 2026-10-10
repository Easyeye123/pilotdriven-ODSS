"""F13 of Codex's independent QA of release 472 (10 Oct 2026): the contingency line is read under the label it prints.

The genuine SQ314 SIN-LGW 15 Aug OFP prints its contingency as a percentage of trip fuel, "3% CONT  00.23  002497"
(with an ERA en-route alternate, EDDF), where the other 29 held OFPs print "STAT CONT". The page-1 reader knew only
"STAT CONT", so SQ314's contingency was not held: contingency_fuel_kg was null, the summary reported
"missing line: stat_cont", the dashboard raised unverified fuel arithmetic and the PDF printed "STAT CONT Not held /
Arithmetic: not verified". The line is now read in either printed form, its printed label is held on the row, and every
surface prints that label; nothing relabels a percentage contingency as STAT CONT.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.fuel_rows import contingency_label
from app.odss.parser import extract_pages, parse_lido, parse_page1_fuel_summary

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"


def _flight(name: str) -> dict:
    source = CORPUS / name
    if not source.exists():
        pytest.skip(f"private CFP corpus file {name} is not available")
    return parse_lido(extract_pages(source), source.name)


BLOCK = """
                                             TIME   FUEL
GND  MILES    6178  CRZ COMP M012   BURNOFF  12.53  083220
AIR  MILES    6334  ERA EDDF/FRA    {label}  00.23  002497
ALTN MAN (EGCC)                   ALTN FUEL  00.39  003650
                                  ALTN HOLD  00.30  002375
           TOP UP TO 60 MINS DEST HOLD FUEL  00.00  000000
                                EDTO TOP UP  00.00  000000
                                  TAXI FUEL         000600
PZFW 180000                  FLT PLAN REQMT  14.25  092342
PTOW 275000                     EXCESS FUEL  00.30  003258
PLWT 191780                   FUEL IN TANKS  14.55  095600
"""


def test_genuine_sq314_holds_its_3_percent_contingency_and_its_arithmetic_verifies() -> None:
    flight = _flight("lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf")
    summary = flight["fuel_summary"]
    assert summary["rows"]["stat_cont"] == {"time_minutes": 23, "fuel_kg": 2497, "label": "3% CONT"}
    assert "missing line: stat_cont" not in summary["discrepancies"]
    assert {"name": "fuel_requirement_sum", "passed": True, "lhs": 92342, "rhs": 92342} in summary["checks"]
    assert summary["state"] == "verified", summary["discrepancies"]
    assert flight["fuel"]["contingency_fuel_kg"] == 2497
    assert contingency_label(summary["rows"]) == "3% CONT"


def test_genuine_stat_cont_keeps_its_own_label() -> None:
    summary = _flight("SQ02325072026JFK.pdf")["fuel_summary"]
    assert summary["rows"]["stat_cont"] == {"time_minutes": 8, "fuel_kg": 793, "label": "STAT CONT"}
    assert contingency_label(summary["rows"]) == "STAT CONT"


@pytest.mark.parametrize("printed", ["STAT CONT", "3% CONT", "5% CONT", "10% CONT", "2.5% CONT", "STAT  CONT"])
def test_each_printed_form_is_read_with_its_label(printed: str) -> None:
    summary = parse_page1_fuel_summary(BLOCK.format(label=printed.ljust(9)))
    assert summary["rows"]["stat_cont"] == {"time_minutes": 23, "fuel_kg": 2497, "label": " ".join(printed.split())}
    assert summary["state"] == "verified"


def test_a_line_that_is_not_a_contingency_is_not_read_as_one() -> None:
    summary = parse_page1_fuel_summary(BLOCK.format(label="ERA FUEL "))
    assert summary["rows"]["stat_cont"] is None
    assert "missing line: stat_cont" in summary["discrepancies"]


def test_the_label_a_surface_prints() -> None:
    # A row held before labels were kept was read only from "STAT CONT"; no row means no contingency line was read.
    assert contingency_label({"stat_cont": {"time_minutes": 8, "fuel_kg": 793}}) == "STAT CONT"
    assert contingency_label({"stat_cont": {"time_minutes": 23, "fuel_kg": 2497, "label": "3% CONT"}}) == "3% CONT"
    assert contingency_label({"stat_cont": None}) == "CONT"
    assert contingency_label(None) == "CONT"


def test_genuine_sq314_six_page_pdf_prints_the_3_percent_contingency_and_verified_arithmetic(tmp_path) -> None:
    # Codex's production PDF p3 read "STAT CONT Not held / Arithmetic: not verified" (rendered/F13-SQ314-production-page3.png).
    import json

    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    source = CORPUS / "lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf"
    if not source.exists():
        pytest.skip("private CFP corpus file for SQ314 is not available")
    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    target = tmp_path / "SQ314.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], target,
                             source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {})
    with fitz.open(target) as document:
        assert document.page_count == 6
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert "3% CONT" in text
    assert "STAT CONT" not in text, "a percentage contingency is never relabelled"
    assert "2,497" in text
    assert "not verified" not in text.lower(), "the page-1 arithmetic verifies with the contingency held"
