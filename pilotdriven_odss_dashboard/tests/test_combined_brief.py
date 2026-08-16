"""The combined Flight Briefing renders whole and clean of legacy naming."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.combined_brief import (
    T_BODY,
    T_CARD_HEAD,
    T_MICRO,
    T_SMALL,
    render_combined_briefing,
)
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


def test_long_airport_copy_never_reaches_the_card_tag(tmp_path):
    # 08 Aug audit: realistic long airport wording could collide with the
    # DEP/DEST tag. The card reserves its tag band now; prove it with copy far
    # longer than any real weather line, then scan page 1 for text overlaps.
    long_copy = (
        "Friday RWY 02C/20C closure 1730-2130Z ends 30 minutes before ETA with "
        "TAF 16008KT 9999 FEW015 SCT020 BECMG 0810/0812 26012KT and current "
        "ATIS controlling; follow the greens active for night LVP taxi guidance "
        "with verbal clearance limit controls in force throughout the window."
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    for finding in findings:
        if finding["engine"] in {"notam", "weather"}:
            finding["summary"] = long_copy
    out = tmp_path / "long-copy.pdf"
    render_combined_briefing(flight, findings, [], out)
    page = fitz.open(out)[0]

    def ink(box):
        # Word boxes carry ascender/descender slack; stacked lines with tight
        # leading share box space without sharing ink. Measure the cap core.
        rect = fitz.Rect(box[:4])
        inset = rect.height * 0.22
        return fitz.Rect(rect.x0, rect.y0 + inset, rect.x1, rect.y1 - inset)

    words = [ink(w) for w in page.get_text("words")]
    overlaps = []
    for i, a in enumerate(words):
        for b in words[i + 1:]:
            inter = a & b
            if inter.is_empty:
                continue
            if inter.width > 1.0 and inter.height > 1.5:
                overlaps.append((a, b))
    assert not overlaps, f"{len(overlaps)} overlapping text pairs on page 1"


def test_the_open_control_appears_once_per_gate(rendered):
    first = rendered[0].get_text()
    # Six gates, six OPEN controls — a doubled draw would double the count.
    assert first.count("OPEN >") == 6


def test_report_copy_uses_a_cockpit_readable_minimum_scale():
    # The first +20% pass still left the dense report copy at 6.5 pt. Keep the
    # reusable scale above that floor so a later layout edit cannot quietly
    # make the generated briefing tiny again.
    assert T_CARD_HEAD >= 9.2
    assert T_BODY >= 9.2
    assert T_SMALL >= 8.0
    assert T_MICRO >= 7.2


def test_rendered_report_content_never_shrinks_below_the_readable_floor(rendered):
    too_small = []
    for page_number, page in enumerate(rendered, start=1):
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "").strip()
                    top = float(span.get("bbox", (0, 0, 0, 0))[1])
                    if text and 65 < top < page.rect.height - 30 and span["size"] < 7.15:
                        too_small.append((page_number, text, span["size"]))
    assert not too_small, too_small[:20]


def test_every_detail_page_has_a_real_overview_return_link(rendered):
    assert "BACK TO OVERVIEW" not in rendered[0].get_text()
    for page in rendered[1:]:
        assert "BACK TO OVERVIEW" in page.get_text()
        links = page.get_links()
        assert any(
            (link.get("kind") == fitz.LINK_GOTO and link.get("page") == 0)
            or (link.get("kind") == fitz.LINK_NAMED and link.get("page") == "1")
            for link in links
        )


def test_overview_return_link_does_not_cover_header_identity(rendered):
    for page in rendered[1:]:
        return_link = next(
            link for link in page.get_links()
            if (link.get("kind") == fitz.LINK_GOTO and link.get("page") == 0)
            or (link.get("kind") == fitz.LINK_NAMED and link.get("page") == "1")
        )
        for label in ("BLOCK", "FLIGHT BRIEFING"):
            for text_box in page.search_for(label):
                assert (return_link["from"] & text_box).is_empty


def test_edto_gate_label_agrees_with_the_cfp_classification(rendered):
    first = rendered[0].get_text()
    assert "CFP classified EDTO CFP" in first
    assert "NON-EDTO" not in first


def test_edto_page_prints_the_parsed_entry_and_exit(rendered):
    second = rendered[1].get_text()
    assert "ENTRY ACTM" in second
    assert "EXIT ACTM" in second


def test_missing_classification_never_defaults_to_edto(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = {}
    flight["edto"] = {}
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "classification-review.pdf"
    render_combined_briefing(flight, findings, [], out)
    text = "\n".join(page.get_text() for page in fitz.open(out))

    assert "EDTO REVIEW" in text
    assert "SUMMARY EDTO CFP" not in text


def test_airport_identity_places_iata_beside_icao(rendered):
    first = rendered[0].get_text()
    assert "BRU / EBBR" in first
    assert "SIN / WSSS" in first


def test_hazard_page_states_the_direct_vaac_centre_coverage(rendered):
    hazard = "\n".join(page.get_text() for page in rendered)
    assert "VAAC CENTRES" in hazard
    assert "0/9 reached" in hazard


def test_publication_filename_carries_flight_and_expanded_date():
    from app.odss.combined_brief import combined_briefing_filename

    assert combined_briefing_filename("SIA365", "07AUG26") == "SIA365_07AUG2026_Flight_Briefing.pdf"
    assert combined_briefing_filename("SQ366", "04AUG2026") == "SQ366_04AUG2026_Flight_Briefing.pdf"
    # A date the pattern cannot vouch for is omitted, never guessed.
    assert combined_briefing_filename("SIA23", "??") == "SIA23_Flight_Briefing.pdf"
