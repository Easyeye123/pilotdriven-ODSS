"""The combined Flight Briefing renders whole and clean of legacy naming."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.combined_brief import (
    COMBINED_BRIEFING_SCHEMA_VERSION,
    T_BODY,
    T_CARD_HEAD,
    T_MICRO,
    T_SMALL,
    crop_source_region,
    governed_deferred_source_target,
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
    # REV3 canon: seven sections - dashboard, critical analysis, MEL/CDL,
    # EDTO, airports, hazards, terrain.
    assert len(rendered) == 7
    first = rendered[0].get_text()
    assert "CFP P1 - ROUTE / LEVELS" in first
    # REV3 canon (boss, 20 Aug): page 1 is the dashboard - route/levels
    # panel plus the mass/fuel column, not the old flight-plan grid.
    assert "CFP P1 - ROUTE / LEVELS + ANALYSIS OVERLAY" in first
    assert "CFP P1 - MASS / FUEL" in first
    assert "107,027" in first.replace(" ", ",")
    titles = "\n".join(rendered[n].get_text() for n in range(len(rendered)))
    for expected in (
        "CRITICAL ANALYSIS",
        "MEL/CDL AND CDDL",
        "AIRPORT AND NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
        "HIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
    ):
        assert expected in titles


def test_the_naming_rule_holds_everywhere(rendered):
    # Boss instruction 2: no Level 1, Level 2, Pertinent brief or Evidence
    # level anywhere in the pilot-facing document.
    text = "\n".join(page.get_text().upper() for page in rendered)
    for banned in ("LEVEL 1", "LEVEL 2", "PERTINENT", "EVIDENCE LEVEL"):
        assert banned not in text, f"banned naming leaked: {banned}"


def test_mel_page_embeds_a_durable_signed_in_governed_source_link(tmp_path):
    flight = sample_flight()
    flight["deferred_items"] = [{
        "item_type": "MEL",
        "reference": "25-20-50A",
        "description": "Non-essential equipment and furnishings",
        "company_remark": "Review the current governed item.",
    }]
    output = tmp_path / "mel-source-link.pdf"
    findings = [
        finding for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    mel_page = document[2]
    mel_text = mel_page.get_text()
    assert "CFP REMARK - NOT THE APPROVED MEL REMEDY" in mel_text
    assert "OPEN EXACT MEL ITEM / REMEDY >" in mel_text
    source_links = [
        link["uri"] for link in mel_page.get_links()
        if link.get("uri") and "governed-deferred-reference" in link["uri"]
    ]
    assert len(source_links) == 1
    origin, _, fragment = source_links[0].partition("/#/")
    assert origin == "https://www.pilotdriven.com"
    route, _, query = fragment.partition("?")
    assert route == "governed-deferred-reference"
    assert parse_qs(query) == {
        "type": ["MEL"],
        "reference": ["25-20-50A"],
        "flightNumber": ["SQ303"],
        "registration": ["9V-SMR"],
        "aircraftType": ["A350-941"],
        "departure": ["EBBR"],
        "destination": ["WSSS"],
        "sourcePage": ["1"],
    }
    assert COMBINED_BRIEFING_SCHEMA_VERSION


def test_unclassified_declaration_never_gets_a_governed_source_link():
    assert governed_deferred_source_target(
        sample_flight(),
        {"item_type": "UNCLASSIFIED", "reference": "IFEDDL"},
    ) is None


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
    # REV3 canon (boss, 20 Aug): page 1 is the dashboard with the PRIORITY
    # strip - no gate rows, so no OPEN controls; the operating gates live on
    # page 2 with their own links.
    first = rendered[0].get_text()
    assert first.count("OPEN >") == 0
    assert "PRIORITY" in first


def test_repeated_mel_reference_is_one_gate_and_one_detail_group(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["deferred_items"] = [
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "description": "FIRST CHILLING COMPARTMENT",
            "company_remark": "FIRST GALLEY LOCATION",
        },
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "description": "SECOND CHILLING COMPARTMENT",
            "company_remark": "SECOND GALLEY LOCATION",
        },
    ]
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "grouped-deferred.pdf"
    render_combined_briefing(flight, findings, [], out)
    pages = fitz.open(out)

    assert pages[0].get_text().count("MEL 25-20-50A") == 1
    assert pages[1].get_text().count("MEL 25-20-50A") == 1
    mel_page = pages[2].get_text()
    assert mel_page.count("MEL 25-20-50A") == 1
    assert "FIRST CHILLING COMPARTMENT" in mel_page
    assert "SECOND CHILLING COMPARTMENT" in mel_page


def test_mel_cdl_page_keeps_all_governing_references_and_duplicate_details(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["deferred_items"] = [
        {
            "item_type": "MEL",
            "reference": "73-09-03A",
            "description": "ENG 2 SHORT TERM MINOR FAULT",
        },
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "description": "BOTH SIDE VACUUM GENERATOR INOP",
            "company_remark": "DO NOT USE LAVATORIES ON GROUND.",
        },
        {
            "item_type": "CDL",
            "reference": "27-23",
            "description": "AILERON END SEAL",
            "company_remark": "LH WING INBOARD AILERON END SEAL FOUND DAMAGED",
        },
        {
            "item_type": "CDL",
            "reference": "57-21",
            "description": "FTE PANEL 3 SEAL",
            "company_remark": "LH WING FTE PANEL 3 SEAL HAS MISSING MATERIAL",
        },
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "description": "ALL CHILLERS IN FWD AND AFT GALLEY DOWN",
            "company_remark": "UPLIFT DRY ICE",
        },
    ]
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "all-deferred-groups.pdf"
    render_combined_briefing(flight, findings, [], out)
    document = fitz.open(out)

    mel_page = document[2].get_text()
    mel_page_flat = " ".join(mel_page.split())
    for reference in (
        "MEL 73-09-03A",
        "MEL 25-20-50A",
        "CDL 27-23",
        "CDL 57-21",
    ):
        assert reference in mel_page
    assert mel_page.count("MEL 25-20-50A") == 1
    assert "BOTH SIDE VACUUM GENERATOR INOP" in mel_page_flat
    assert "ALL CHILLERS IN FWD AND AFT GALLEY DOWN" in mel_page_flat
    assert "DO NOT USE LAVATORIES ON GROUND" in mel_page_flat
    assert "UPLIFT DRY ICE" in mel_page_flat


def test_many_governing_references_create_as_many_pages_as_needed(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["deferred_items"] = [
        {
            "item_type": "MEL" if index % 2 == 0 else "CDL",
            "reference": f"TEST-{index + 1}",
            "description": f"GOVERNING ITEM {index + 1}",
        }
        for index in range(9)
    ]
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "continued-deferred.pdf"
    render_combined_briefing(flight, findings, [], out)
    document = fitz.open(out)

    assert len(document) == 9
    first_mel_page = document[2].get_text()
    second_mel_page = document[3].get_text()
    third_mel_page = document[4].get_text()
    assert "MEL/CDL AND CDDL (1/3)" in first_mel_page
    assert "MEL/CDL AND CDDL (2/3)" in second_mel_page
    assert "MEL/CDL AND CDDL (3/3)" in third_mel_page
    for index in range(4):
        assert f"TEST-{index + 1}" in first_mel_page
    assert "TEST-5" not in first_mel_page
    for index in range(4, 8):
        assert f"TEST-{index + 1}" in second_mel_page
    assert "TEST-9" not in second_mel_page
    assert "TEST-9" in third_mel_page
    assert "EDTO AND DESTINATION ALTERNATES" in document[5].get_text()
    assert "Page 6 of 9" in document[5].get_text()


def test_source_crop_extends_to_the_next_printed_section(tmp_path):
    source = tmp_path / "long-deferred-source.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 60), "ATTN ALL CONCERN FR MAINTROL")
    for index in range(12):
        page.insert_text((50, 82 + index * 13), f"ITEM {index + 1} OPERATIONAL CONDITION")
    page.insert_text((50, 255), "RTE NO SYNTHETIC")
    document.save(source)
    document.close()

    crop = crop_source_region(
        str(source),
        needle="ATTN ALL CONCERN",
        end_needle="RTE NO",
        page_hint=0,
        pad_y=8,
        dpi=72,
        full_width=True,
    )

    assert crop is not None
    assert crop["page_number"] == 1
    assert crop["height"] > 170


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
    # REV3 canon: page 1 declares EDTO via the chip and the CLASSIFICATION
    # row; the full source sentence lives on the EDTO page.
    first = rendered[0].get_text()
    assert "EDTO" in first
    assert "NON-EDTO" not in first
    # The full source sentence lives on the EDTO page (page 4 with one MEL page).
    assert "CFP page 1: SUMMARY EDTO CFP." in rendered[3].get_text()


def test_edto_page_prints_the_parsed_entry_and_exit(rendered):
    second = rendered[3].get_text()
    assert "ENTRY ACTM" in second
    assert "EXIT ACTM" in second


def test_edto_page_preserves_every_numbered_sector(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["edto"]["sectors"] = [
        {
            "number": number,
            "entry_actm_minutes": entry,
            "exit_actm_minutes": exit_,
            "etp_actm_minutes": [],
        }
        for number, entry, exit_ in (
            (1, 449, 530),
            (2, 636, 640),
            (3, 794, 857),
            (4, 905, 983),
        )
    ]
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "four-edto-sectors.pdf"
    render_combined_briefing(flight, findings, [], out)
    second = fitz.open(out)[3].get_text()

    for number, entry, exit_ in (
        (1, "07.29", "08.50"),
        (2, "10.36", "10.40"),
        (3, "13.14", "14.17"),
        (4, "15.05", "16.23"),
    ):
        assert f"SECTOR {number}" in second
        assert f"ENTRY ACTM {entry} | EXIT ACTM {exit_}" in second


def test_edto_page_preserves_every_alternate(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["edto"]["airports"] = [
        {
            "airport": airport,
            "runway": runway,
            "approach": "CAT1",
            "period_start_utc": "2026-08-15T17:00:00+00:00",
            "period_end_utc": "2026-08-16T02:00:00+00:00",
        }
        for airport, runway in (
            ("PGUM", "24R"),
            ("RJTT", "34R"),
            ("RJCC", "01R"),
            ("PASY", "28"),
            ("PACD", "15"),
            ("KSFO", "28R"),
        )
    ]
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "six-edto-alternates.pdf"
    render_combined_briefing(flight, findings, [], out)
    edto_page = fitz.open(out)[3].get_text()

    for airport in ("PGUM", "RJTT", "RJCC", "PASY", "PACD", "KSFO"):
        assert airport in edto_page


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


def test_standard_cfp_keeps_its_printed_label_and_is_non_edto(tmp_path):
    flight = sample_flight()
    standard_page1 = SQ23_PAGE1.replace("SUMMARY EDTO CFP", "SUMMARY STANDARD CFP")
    flight["fuel_summary"] = parse_page1_fuel_summary(standard_page1)
    flight["edto"] = {
        "assessment": {"status": "verified_not_applicable", "evidence": []},
        "sectors": [],
        "airports": [],
    }
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "standard-non-edto.pdf"
    render_combined_briefing(flight, findings, [], out)
    text = "\n".join(page.get_text() for page in fitz.open(out))

    assert "SUMMARY STANDARD CFP (non-EDTO)" in text
    assert "SUMMARY EDTO CFP" not in text
    assert "NON-EDTO" in text


def test_airport_identity_places_iata_beside_icao(rendered):
    first = rendered[0].get_text()
    assert "BRU / EBBR" in first
    assert "SIN / WSSS" in first


def test_hazard_page_states_the_direct_vaac_centre_coverage(rendered):
    hazard = "\n".join(page.get_text() for page in rendered)
    assert "VAAC CENTRES" in hazard
    assert "0/9 reached" in hazard


def test_hazard_page_names_each_vaac_centre_and_truth_state(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    centres = (
        "ANCHORAGE",
        "BUENOS AIRES",
        "DARWIN",
        "LONDON",
        "MONTREAL",
        "TOKYO",
        "TOULOUSE",
        "WASHINGTON",
        "WELLINGTON",
    )
    flight["vaa_review"] = {
        "status": "review_required",
        "vaac_centre_ledger": [
            {
                "centre": centre,
                "status": "available" if centre in {"ANCHORAGE", "TOKYO"} else "unavailable",
            }
            for centre in centres
        ],
    }
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "vaac-receipt.pdf"
    render_combined_briefing(flight, findings, [], out)
    hazard = fitz.open(out)[5].get_text().upper()

    assert "2/9 REACHED" in hazard
    for centre in centres:
        assert centre in hazard
    assert "ANCHORAGE: REACHED" in hazard
    assert "LONDON: UNAVAILABLE" in hazard


def test_publication_filename_carries_flight_and_expanded_date():
    from app.odss.combined_brief import combined_briefing_filename

    assert combined_briefing_filename("SIA365", "07AUG26") == "SIA365_07AUG2026_Flight_Briefing.pdf"
    assert combined_briefing_filename("SQ366", "04AUG2026") == "SQ366_04AUG2026_Flight_Briefing.pdf"
    # A date the pattern cannot vouch for is omitted, never guessed.
    assert combined_briefing_filename("SIA23", "??") == "SIA23_Flight_Briefing.pdf"
