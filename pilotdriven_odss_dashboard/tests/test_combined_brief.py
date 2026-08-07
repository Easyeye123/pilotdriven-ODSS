"""The combined Flight Briefing renders whole and clean of legacy naming."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.combined_brief import render_combined_briefing
from app.odss.parser import parse_page1_fuel_summary
from app.odss.timing import build_timing_view

SQ23_PAGE1 = (
    "PAGE  1 OF 21 SIA23 JFK/SIN 25JUL26\n"
    "              SINGAPORE AIRLINES - SUMMARY EDTO CFP\n"
    "GND  MILES    9197  CRZ COMP P025   BURNOFF  17.57  107027\n"
    "AIR  MILES    8760                STAT CONT  00.08  000793\n"
    "ALTN KUL (WMKK)                   ALTN FUEL  00.55  004680\n"
    "                                  ALTN HOLD  00.30  002174\n"
    "           TOP UP TO 60 MINS DEST HOLD FUEL  00.00  000000\n"
    "                                EDTO TOP UP  00.00  000000\n"
    "                                  TAXI FUEL         000600\n"
    "PZFW 162326                  FLT PLAN REQMT  19.30  115274\n"
    "PTOW 280000                     EXCESS FUEL  00.30  003000\n"
    "PLWT 172973                   FUEL IN TANKS  20.00  118274\n"
)


@pytest.fixture()
def rendered(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    flight["actual_takeoff_utc"] = "2026-07-16T09:52:00+00:00"
    flight["timing_view"] = build_timing_view(flight, findings, flight["actual_takeoff_utc"])
    out = tmp_path / "combined.pdf"
    render_combined_briefing(flight, findings, [], out)
    return fitz.open(out)


def test_renders_the_full_section_set(rendered):
    assert len(rendered) == 9
    first = rendered[0].get_text()
    assert "FLIGHT OVERVIEW" in first
    assert "CFP PAGE 1 - FLIGHT PLAN" in first
    assert "107,027" in first.replace(" ", ",")
    titles = "\n".join(rendered[n].get_text() for n in range(len(rendered)))
    for expected in (
        "PERFORMANCE AND PLANNING SENSITIVITY",
        "MEL/CDL AND CDDL",
        "AIRPORT AND NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
        "FIR COMMUNICATION AND TIME RECONCILIATION",
    ):
        assert expected in titles


def test_the_naming_rule_holds_everywhere(rendered):
    # Boss instruction 2: no Level 1, Level 2, Pertinent brief or Evidence
    # level anywhere in the pilot-facing document.
    text = "\n".join(page.get_text().upper() for page in rendered)
    for banned in ("LEVEL 1", "LEVEL 2", "PERTINENT", "EVIDENCE LEVEL"):
        assert banned not in text, f"banned naming leaked: {banned}"


def test_governance_chrome_is_on_every_page(rendered):
    for page in rendered:
        text = page.get_text()
        assert "DIRECT SOURCES + DETERMINISTIC DERIVATION | AI AUTHORITY: NONE" in text
        assert "SOURCE" in text
