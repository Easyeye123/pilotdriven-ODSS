"""The boss's six-page Flight Briefing format, asserted on real corpus flights.

9 Sep 2026, 21:17-21:20. David sent four reference briefings and said:

    "This format from beginning has always been this."
    "Get this right, and then we talk about tweaking from this."
    "Page 1 is good."
    [circling the reference page 2 DECISION ANALYSIS] "This for the longest
    time doesn't work."
    "So you have to check and make sure the memory losses and standard
    established does not degenerate. How do you ensure that???"

His reference ``SQ910_21AUG2026_Flight_Briefing.pdf`` is six pages: OVERVIEW,
DECISION ANALYSIS, PERFORMANCE / FUEL / TECH, AIRPORTS / ALTERNATES,
WEATHER / ROUTE HAZARDS, ENROUTE / INTAM / ASSURANCE. Every page carries the
navigation ribbon and the footer triplet. The production download on 15 Sep
2026 was nine pages with our own section names and no Decision Analysis page
at all.

This module is the answer to "how do you ensure that": the structure is
asserted against the analysed briefing rendered from the real private CFP
corpus - the same SQ910 OFP his reference was made from - not from a
hand-written fixture that can be edited to match whatever we happen to draw.
"""
from __future__ import annotations

from pathlib import Path
import re

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import (
    MAX_BRIEFING_PAGES,
    NAV_RIBBON,
    PAGE_TITLES,
    check_concise_pdf,
    normalized,
)
from scripts.run_private_cfp_corpus import scan_physical_pdf


CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"

# The three flights David sent reference briefings for on 9 Sep 2026.
CORPUS_CASES = {
    "SQ910": "SQ91021082026SIN.pdf",
    "SQ481": "SQ48125082026JNB.pdf",
    "SQ38": "SQ38-29AUG2026-OFP-for-prod-proof.pdf",
}

_RENDERED: dict[str, dict] = {}


def rendered(flight_key: str, tmp_path_factory) -> dict:
    """Run the real analysis once per flight and publish the real download."""
    if flight_key in _RENDERED:
        return _RENDERED[flight_key]
    source = CORPUS / CORPUS_CASES[flight_key]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {CORPUS_CASES[flight_key]} is not available")
    import json

    root = tmp_path_factory.mktemp(f"boss-format-{flight_key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"]
    findings = payload["findings"]
    warnings = payload.get("view", {}).get("warnings") or []
    path = root / f"{flight_key}_Flight_Briefing.pdf"
    render_combined_briefing(
        flight, findings, warnings, path,
        weather_charts=payload.get("weather_charts") or {},
    )
    view = build_briefing_view(
        flight, findings, warnings,
        timing_view=flight.get("timing_view"),
        weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[flight_key] = {
        "path": path, "flight": flight, "findings": findings,
        "view": view, "pages": pages,
        "folded": [normalized(page) for page in pages],
    }
    return _RENDERED[flight_key]


@pytest.fixture(scope="session", params=sorted(CORPUS_CASES))
def briefing(request, tmp_path_factory):
    return rendered(request.param, tmp_path_factory)


def test_download_is_the_six_page_reference_format(briefing):
    """Nine pages with our own names is the thing he rejected."""
    assert MAX_BRIEFING_PAGES == 6
    with fitz.open(briefing["path"]) as document:
        assert len(document) == 6


def test_every_page_carries_its_reference_title_in_order(briefing):
    titles = (
        "OVERVIEW",
        "DECISION ANALYSIS",
        "PERFORMANCE, FUEL AND TECHNICAL STATUS",
        "AIRPORTS / ALTERNATES",
        "WEATHER / ROUTE HAZARDS",
        "ENROUTE / INTAM / ASSURANCE",
    )
    assert tuple(PAGE_TITLES) == titles
    for index, title in enumerate(titles):
        assert normalized(title) in briefing["folded"][index], (
            f"page {index + 1} must be {title}"
        )


def test_navigation_ribbon_is_on_every_page_with_the_active_item(briefing):
    assert NAV_RIBBON == (
        "OVERVIEW", "ANALYSIS", "PERF / FUEL / TECH",
        "AIRPORTS", "WEATHER", "ENROUTE / INTAM",
    )
    for index, folded in enumerate(briefing["folded"]):
        for item in NAV_RIBBON:
            assert normalized(item) in folded, (
                f"page {index + 1} is missing ribbon item {item}"
            )
        assert normalized(f"FLIGHT BRIEFING | PAGE {index + 1} OF 6") in folded
    # The active ribbon item is underlined, exactly like his reference.
    with fitz.open(briefing["path"]) as document:
        for index, page in enumerate(document):
            spans = [
                span
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["text"].strip() == NAV_RIBBON[index]
            ]
            assert spans, f"page {index + 1} has no ribbon entry to underline"
            target = spans[0]
            rules = [
                drawing for drawing in page.get_drawings()
                if abs(drawing["rect"].height) <= 2.5
                and drawing["rect"].x0 <= target["bbox"][0] + 1.5
                and drawing["rect"].x1 >= target["bbox"][2] - 1.5
                and 0 < drawing["rect"].y0 - target["bbox"][3] < 8
            ]
            assert rules, f"ribbon item {NAV_RIBBON[index]} is not underlined"


def test_footer_triplet_names_the_flight_the_assurance_and_the_page(briefing):
    identity = briefing["view"]["flight_identity"]
    flight = briefing["flight"]
    left = (
        f"{briefing['view']['flight_number']} | "
        f"{briefing['view']['flight_date']} | "
        f"{flight['departure']}-{flight['destination']} | "
        f"{identity['aircraft_type']} {identity['registration']} | "
        f"OFP {identity['ofp']}"
    )
    for index, folded in enumerate(briefing["folded"]):
        assert normalized(left) in folded, f"page {index + 1} footer identity"
        assert normalized(f"Page {index + 1} of 6") in folded
    assert normalized(
        "CFP P1 PRIORITISED | SOURCE FACTS + LABELLED ANALYSIS | AI AUTHORITY: NONE"
    ) in briefing["folded"][0]


def test_page_one_is_departure_route_map_destination_then_tiles_and_strip(briefing):
    page = briefing["folded"][0]
    for marker in (
        "DEPARTURE", "DESTINATION", "CFP ROUTE - PERTINENT DECISION GATES",
        "PERFORMANCE", "FUEL", "TECH STATUS", "WEATHER / HAZARDS", "ALTN / ROUTE",
        "RELEASE", "BEFORE PUSH", "ROUTE", "ARRIVAL", "WEATHER",
        "PLAN", "SCHEDULE", "METAR", "TAF", "PERTINENT",
    ):
        assert normalized(marker) in page, f"page 1 is missing {marker}"
    assert page.count("CFP P1") >= 5, "each page-1 tile carries its provenance tag"
    # The schematic route map he circled is drawn, not described.
    with fitz.open(briefing["path"]) as document:
        assert len(document[0].get_drawings()) > 40


def test_page_two_is_the_decision_analysis_he_circled_in_green(briefing):
    """'This for the longest time doesn't work.' - 9 Sep 2026, 21:17:52."""
    page = briefing["folded"][1]
    findings = briefing["view"]["decision_findings"]
    assert findings, "the analysis must hold ranked decision findings"
    assert normalized("DECISION ANALYSIS") in page
    assert normalized("FLIGHT-PHASE DECISION TIMELINE") in page
    pills = re.findall(r"\b(MAJOR|MODERATE|INFO|REVIEW)\b", briefing["pages"][1])
    assert len([p for p in pills if p in {"MAJOR", "MODERATE"}]) >= 1, (
        "a severity pill must be published for the evidenced findings"
    )
    assert len(pills) >= len(findings)
    for finding in findings:
        assert normalized(finding["title"]) in page, (
            f"decision finding {finding['rank']} is missing from page 2"
        )
    # Every dot on the timeline is annotated with its level and time.
    assert normalized("DEP") in page
    assert re.search(r"\b\d{2}:\d{2}\b|\b\d{4}Z\b", briefing["pages"][1])


def test_relocated_content_keeps_its_owning_section(briefing):
    """Nothing published today is dropped; it moves to the section that owns it."""
    view, folded = briefing["view"], briefing["folded"]
    for analysed in view["airport_pdf_analysis"]:
        for line in analysed["lines"]:
            assert normalized(line["text"]) in folded[3], (
                f"{analysed['icao']} consequence left the airports page"
            )
    for row in view["deferred_pdf_analysis"]:
        assert normalized(row["text"]) in folded[2], (
            "a deferred declaration left the performance / tech page"
        )
    assert normalized(view["departure"]["weather"]["metar"]) in folded[4]
    assert normalized(view["destination"]["weather"]["metar"]) in folded[4]


def test_publication_gate_and_physical_scan_accept_the_new_format(briefing):
    view = briefing["view"]
    result = check_concise_pdf(
        briefing["path"], flight=briefing["flight"], view=view,
        airport_analysis=view["airport_pdf_analysis"],
        alternate_analysis=view["alternate_pdf_analysis"],
    )
    assert result["valid"], result["violations"]
    assert result["page_count"] == 6
    physical = scan_physical_pdf(briefing["path"])
    assert physical["valid"], physical["violations"][:4]
    with fitz.open(briefing["path"]) as document:
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        assert span["size"] >= 8.9, span["text"]
