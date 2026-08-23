"""The combined Flight Briefing renders whole and clean of legacy naming."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.combined_brief import (
    COMBINED_BRIEFING_SCHEMA_VERSION,
    CRITICAL,
    EDTO_GREEN,
    T_BODY,
    T_CARD_HEAD,
    T_MICRO,
    T_SMALL,
    WEATHER_AMBER,
    _performance_margin_presentation,
    _performance_selected_presentation,
    _route_anchor_entries,
    _terrain_table_points,
    crop_source_region,
    governed_deferred_source_target,
    render_combined_briefing,
)
from app.odss.constants import format_actm
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
    # The boss-facing production download is exactly the seven compact REV3
    # operational sections. Lossless continuation pages are opt-in.
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
        "DECISION ANALYSIS",
        "MEL/CDL AND CDDL",
        "AIRPORTS / NOTAM APPLICABILITY",
        "OPERATIONAL HAZARD ASSESSMENT",
        "HIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
    ):
        assert expected in titles


def test_compact_pdf_has_seven_real_outline_entries(rendered):
    assert [row[1] for row in rendered.get_toc()] == [
        "Flight Overview",
        "Decision Analysis",
        "CDDL / CDL",
        "EDTO / Enroute Airports",
        "Airports / NOTAM",
        "Operational Hazards",
        "Terrain / Depressurisation",
    ]


def test_compact_dispatch_gates_use_the_shared_source_projection(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["deferred_items"] = [{
        "item_type": "CDDL",
        "reference": "UNSPECIFIED",
        "description": "CABIN COMPACTOR UNIT ONE JAMMED",
        "company_remark": "USE SPARE LINER",
    }, {
        "item_type": "CDDL",
        "reference": "UNSPECIFIED",
        "description": "CABIN COMPACTOR UNIT TWO NO POWER",
        "company_remark": "USE SPARE LINER",
    }, {
        "item_type": "CDL",
        "reference": "10-10",
        "description": "LEFT WING PANEL SEAL DAMAGED",
    }, {
        "item_type": "CDL",
        "reference": "20-20",
        "description": "RIGHT HINGED ACCESS DOOR SEAL DAMAGED",
        "company_remark": (
            "ZZ IN OPS/42 R3 BOTH CTRL REMOVED. SYSB SYS NOT AVAILABLE. "
            "YY CDL 30-30 AFT LANDING GEAR DOOR SEAL MISSING"
        ),
    }]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "compact-shared-dispatch-gates.pdf"

    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    page_text = document[2].get_text()
    assert page_text.count("CABIN COMPACTORS") == 1
    assert page_text.count("CTRL / SYSB") == 1
    assert page_text.count("CDL 20-20 / 30-30") == 1
    assert "CDL 10-10" in page_text
    assert "UNSPECIFIED" not in page_text
    assert "UNCLASSIFIED" not in page_text
    assert not any(
        "governed-deferred-reference" in str(link.get("uri") or "")
        for link in document[2].get_links()
    )


def test_compact_sq910_four_shape_declarations_never_publish_placeholders(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["deferred_items"] = [
        {
            "item_type": "IFEDDL",
            "reference": None,
            "source_declaration": "AA IFEDDL",
            "description": "SEAT IFE (YCL), AUDIO JACK, NO AUDIO",
            "company_remark": "41E, 57A X CLASS B",
        },
        {
            "item_type": "CDDL",
            "reference": None,
            "source_declaration": "BB CDDL",
            "description": "TRASH COMPACTOR 212 NO POWER",
            "company_remark": "TO UPLIFT TRASH BAGS",
        },
        {
            "item_type": "MEL",
            "reference": "25-20-50A",
            "source_declaration": "CC MEL 25-20-50A",
            "description": "D4L GALLEY CHILLER NO.1 RED LIGHT BLINKING",
            "company_remark": "TO UPLIFT DRY ICE",
        },
        {
            "item_type": "IN",
            "reference": "SIA/00-017 R1",
            "source_declaration": "DD IN SIA/00-017 R1",
            "description": (
                "ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE"
            ),
            "company_remark": (
                "HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE"
            ),
        },
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "sq910-four-shape-declarations.pdf"

    render_combined_briefing(flight, findings, [], output)

    page_text = fitz.open(output)[2].get_text().upper()
    for expected in (
        "SEAT IFE",
        "TRASH COMPACTOR",
        "MEL 25-20-50A",
        "IN SIA/00-017 R1",
    ):
        assert expected in page_text
    assert "UNSPECIFIED" not in page_text
    assert "UNCLASSIFIED" not in page_text


def test_compact_overview_never_publishes_legacy_deferred_markers(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    raw_item = {
        "item_type": "UNCLASSIFIED",
        "reference": "UNSPECIFIED",
        "description": "LEGACY SOURCE TEXT REQUIRES REVIEW",
    }
    flight["deferred_items"] = [raw_item]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "legacy-deferred-markers.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        output,
        include_audit_appendix=True,
    )

    document_text = "\n".join(
        page.get_text() for page in fitz.open(output)
    ).upper()
    assert "DEFERRED ITEM" in document_text
    assert "UNCLASSIFIED" not in document_text
    assert "UNSPECIFIED" not in document_text
    assert raw_item["item_type"] == "UNCLASSIFIED"
    assert raw_item["reference"] == "UNSPECIFIED"


def test_overview_destination_schedule_uses_the_cfp_arrival_not_last_waypoint(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["scheduled_arrival_utc"] = "2026-07-16T22:40:00+00:00"
    flight["route_waypoints"][-1]["actm_minutes"] = 300
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "arrival-schedule-source.pdf"

    render_combined_briefing(flight, findings, [], output)

    page_text = fitz.open(output)[0].get_text()
    assert page_text.count("2240Z") >= 2
    assert "1445Z" not in page_text


def test_compact_pdf_marks_high_cardinality_content_that_remains_in_dashboard(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    descriptions = (
        "HYDRAULIC PUMP",
        "CABIN LIGHT",
        "GALLEY CHILLER",
        "RADIO PANEL",
        "OXYGEN MASK",
    )
    flight["deferred_items"] = [
        {
            "item_type": "MEL",
            "reference": f"20-20-{index}",
            "description": description,
        }
        for index, description in enumerate(descriptions, start=1)
    ]
    flight["alternates"] = [
        {
            "airport": code,
            "runway": "20",
            "approach": "CAT1",
        }
        for code in ("AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF")
    ]
    flight["edto"]["airports"] = [
        {
            "airport": code,
            "runway": "20",
            "approach": "CAT1",
            "minima": "400FT/1500M",
        }
        for code in ("GGGG", "HHHH", "IIII", "JJJJ")
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "compact-high-cardinality.pdf"

    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    assert len(document) == 7
    assert "+1 IN DASHBOARD" in document[2].get_text()
    assert "additional EDTO/enroute cards remain in dashboard" in document[3].get_text()
    assert "additional airport/NOTAM audit rows remain in dashboard" in document[4].get_text()


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
    render_combined_briefing(
        flight, findings, [], output, include_audit_appendix=True
    )

    document = fitz.open(output)
    mel_page = next(
        page
        for page in document
        if "CFP REMARK - NOT THE APPROVED MEL REMEDY" in page.get_text()
    )
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
    # 21 Aug (SQ910 round): the PRIORITY strip is removed outright - no gate
    # rows and no strip words on page 1; the operating gates live on
    # page 2 with their own links.
    first = rendered[0].get_text()
    assert first.count("OPEN >") == 0
    assert "PRIORITY" not in first


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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    pages = fitz.open(out)

    assert pages[0].get_text().count("MEL 25-20-50A") == 1
    assert pages[1].get_text().count("MEL 25-20-50A") == 1
    mel_page = next(
        page.get_text()
        for page in pages
        if "CFP REMARK - NOT THE APPROVED MEL REMEDY" in page.get_text()
    )
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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    document = fitz.open(out)

    mel_page = " ".join(
        page.get_text()
        for page in document
        if "MEL/CDL AND CDDL" in page.get_text()
    )
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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    document = fitz.open(out)

    compact_mel_pages = [
        page.get_text()
        for page in document
        if "CROPPED CFP DECLARATION" in page.get_text()
    ]
    assert len(compact_mel_pages) == 3
    first_mel_page, second_mel_page, third_mel_page = compact_mel_pages
    for index in range(4):
        assert f"TEST-{index + 1}" in first_mel_page
    assert "TEST-5" not in first_mel_page
    for index in range(4, 8):
        assert f"TEST-{index + 1}" in second_mel_page
    assert "TEST-9" not in second_mel_page
    assert "TEST-9" in third_mel_page
    assert any(
        "EDTO / ENROUTE AIRPORTS" in page.get_text()
        for page in document
    )


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
    assert crop["width"] < 400, "blank source-page side margins must be trimmed"


def test_source_crop_prefers_provenance_and_scans_beyond_old_page_bounds(
    tmp_path,
):
    source = tmp_path / "deep-source-evidence.pdf"
    document = fitz.open()
    for index in range(60):
        page = document.new_page(width=595, height=842)
        page.insert_text((50, 60), f"SOURCE PAGE {index + 1}")
        if index in {13, 59}:
            page.insert_text((50, 100), "REMOTE GOVERNED SOURCE MARKER")
    document.save(source)
    document.close()

    provenance_crop = crop_source_region(
        str(source),
        needle="REMOTE GOVERNED SOURCE MARKER",
        source_pages=[60],
        page_hint=0,
        dpi=72,
    )
    fallback_crop = crop_source_region(
        str(source),
        needle="REMOTE GOVERNED SOURCE MARKER",
        page_hint=0,
        dpi=72,
    )

    assert provenance_crop is not None
    assert fallback_crop is not None
    assert provenance_crop["page_number"] == 60
    assert fallback_crop["page_number"] == 14


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
    for page in rendered[1:]:
        labels = page.search_for("BACK TO OVERVIEW")
        assert len(labels) == 1
        label = labels[0]
        return_link = next(
            link
            for link in page.get_links()
            if (
                (link.get("kind") == fitz.LINK_GOTO and link.get("page") == 0)
                or (
                    link.get("kind") == fitz.LINK_NAMED
                    and link.get("page") == "1"
                )
            )
            and not (fitz.Rect(link["from"]) & label).is_empty
        )
        hit_area = fitz.Rect(return_link["from"])
        assert hit_area.width <= 110
        assert hit_area.height <= 20


def test_decision_analysis_cards_link_to_their_intended_pages(rendered):
    page = rendered[1]
    expected_pages = {
        "PERFORMANCE / FUEL": 0,
        "CDDL / CDL": 2,
        "EDTO / ENROUTE AIRPORT": 3,
        "OPERATIONAL HAZARDS": 5,
        "AIRPORTS / ALTERNATE": 4,
        "HIGH TERRAIN / VWS": 6,
    }

    def target_page(link):
        if link.get("kind") == fitz.LINK_GOTO:
            return link.get("page")
        if link.get("kind") == fitz.LINK_NAMED:
            named_page = str(link.get("page") or "")
            return int(named_page) - 1 if named_page.isdigit() else None
        return None

    for title, expected_page in expected_pages.items():
        title_boxes = page.search_for(title)
        assert title_boxes, f"missing decision card title: {title}"
        title_box = title_boxes[0]
        card_links = [
            link
            for link in page.get_links()
            if not (fitz.Rect(link["from"]) & title_box).is_empty
        ]
        assert len(card_links) == 1, title
        assert target_page(card_links[0]) == expected_page, title


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
    assert "DEST/EDTO TOP-UP" in first
    assert any(
        "CFP page 1: SUMMARY EDTO CFP." in page.get_text()
        for page in rendered
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )
    edto_page = rendered[3].get_text()
    assert "EDTO / ENROUTE AIRPORTS" in edto_page
    assert "EDTO BOUNDARY / STATUS" in edto_page
    assert "CFP EDTO TABLE" in edto_page
    assert "DESTINATION ALTERNATES" not in edto_page


def test_edto_page_prints_the_parsed_entry_and_exit(rendered):
    second = " ".join(
        page.get_text()
        for page in rendered
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )
    assert "ENTRY ACTM" in second
    assert "EXIT ACTM" in second


def test_edto_pages_print_every_shared_operational_row_verbatim(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view
    alternate_values = [
        (
            f"TEST{index:02d}/05 | CAT1DME | 407FT/1600M | "
            f"12 JUL {1800 + index:04d}Z - 12 JUL {2100 + index:04d}Z"
        )
        for index in range(1, 11)
    ]

    def shared_edto_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["edto"]["operational_rows"] = [
            {
                "label": "CLASSIFICATION",
                "value": "SHARED EDTO CLASSIFICATION SENTINEL",
            },
            {
                "label": "SECTOR 1",
                "value": "ENTRY ACTM 02.21 | EXIT ACTM 03.44",
            },
            *(
                {"label": "EDTO ALTN", "value": value}
                for value in alternate_values
            ),
            {"label": "FUEL", "value": "EDTO top-up 0 kg."},
            {
                "label": "GATE",
                "value": "SHARED EDTO GATE SENTINEL",
            },
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        shared_edto_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "shared-edto-operational-row-continuations.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    edto_pages = [
        page
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    ]
    folded = " ".join(" ".join(page.get_text() for page in edto_pages).split())
    assert len(edto_pages) > 1
    assert "SHARED EDTO CLASSIFICATION SENTINEL" in folded
    assert "SHARED EDTO GATE SENTINEL" in folded
    for value in alternate_values:
        assert value in folded
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    document = fitz.open(out)
    second = "\n".join(
        page.get_text()
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )

    for number, entry, exit_ in (
        (1, "07.29", "08.50"),
        (2, "10.36", "10.40"),
        (3, "13.14", "14.17"),
        (4, "15.05", "16.23"),
    ):
        assert f"SECTOR {number}" in second
        assert f"ENTRY ACTM {entry} | EXIT ACTM {exit_}" in second


def test_high_cardinality_edto_keeps_every_sector_etp_and_selected_station(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["edto"]["sectors"] = [
        {
            "number": number,
            "entry_actm_minutes": number * 60 + 1,
            "exit_actm_minutes": number * 60 + 31,
            "etp_actm_minutes": [number * 60 + 11, number * 60 + 21],
        }
        for number in range(1, 9)
    ]
    flight["edto"]["airports"] = [
        {
            "airport": f"ED{number:02d}",
            "runway": f"{number:02d}",
            "approach": "RNP",
            "minima": f"{400 + number}FT/1600M",
            "period_start_utc": "2026-08-15T17:00:00+00:00",
            "period_end_utc": "2026-08-16T02:00:00+00:00",
        }
        for number in range(1, 7)
    ]
    flight["fuel_enroute_airports"] = [
        {
            "airport": f"FR{number:02d}",
            "role": "fuel_enroute_airport",
            "source_pages": [20 + number],
        }
        for number in range(1, 4)
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "high-cardinality-edto.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    edto_pages = [
        page.get_text()
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    ]
    edto_text = "\n".join(edto_pages)
    assert len(edto_pages) > 1
    assert all("CONTINUED (" in text for text in edto_pages[1:])
    for number in range(1, 9):
        assert f"SECTOR {number}" in edto_text
        assert f"ETPS {number}" in edto_text
        assert format_actm(number * 60 + 11) in edto_text
        assert format_actm(number * 60 + 21) in edto_text
    for number in range(1, 7):
        assert f"ED{number:02d}" in edto_text
    for number in range(1, 4):
        assert f"FR{number:02d}" in edto_text


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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    document = fitz.open(out)
    edto_page = "\n".join(
        page.get_text()
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )

    for airport in ("PGUM", "RJTT", "RJCC", "PASY", "PACD", "KSFO"):
        assert airport in edto_page
    assert "CONTINUED (2/" in edto_page


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


def test_standard_cfp_keeps_its_printed_label_and_is_non_edto(tmp_path, monkeypatch):
    from app.odss import combined_brief as combined_brief_module

    real_panel = combined_brief_module.panel
    classification_panels = []

    def traced_panel(canvas, x, y, w, h, **kwargs):
        if kwargs.get("title") == "CLASSIFICATION":
            classification_panels.append((w, h))
        return real_panel(canvas, x, y, w, h, **kwargs)

    monkeypatch.setattr(combined_brief_module, "panel", traced_panel)
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
    document = fitz.open(out)
    text = "\n".join(page.get_text() for page in document)
    page4 = document[3].get_text()
    toc = [row[1] for row in document.get_toc()]

    assert "SUMMARY STANDARD CFP (non-EDTO)" in text
    assert "SUMMARY EDTO CFP" not in text
    assert "NON-EDTO" in text
    assert "DEST HOLD TOP-UP" in document[0].get_text()
    assert "DEST/EDTO TOP-UP" not in document[0].get_text()
    assert "DESTINATION ALTERNATES" in page4
    assert "CLASSIFICATION" in page4
    assert "CFP ALTERNATE PLANNING" in page4
    for retired in (
        "EDTO / ENROUTE AIRPORTS",
        "EDTO BOUNDARY / STATUS",
        "CFP EDTO TABLE",
        "ENTRY ACTM",
        "EXIT ACTM",
        "EDTO TOP-UP",
        "EDTO ALTERNATE SECTOR",
    ):
        assert retired not in page4
    assert toc[1] == "Decision Analysis"
    assert toc[3] == "Destination Alternates"
    assert "EDTO / Enroute Airports" not in toc
    assert classification_panels == [(
        pytest.approx(combined_brief_module.PAGE_SIZE[0] - 2 * combined_brief_module.MARGIN),
        pytest.approx(combined_brief_module.NON_EDTO_CLASSIFICATION_CARD_HEIGHT),
    )]
    assert classification_panels[0][1] < combined_brief_module.EDTO_CARD_HEIGHT


def test_airport_identity_places_iata_beside_icao(rendered):
    first = rendered[0].get_text()
    assert "BRU / EBBR" in first
    assert "SIN / WSSS" in first


def test_sq214_shape_keeps_the_five_selected_airport_role_cards_on_one_page(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["fuel_enroute_airports"] = [{
        "airport": "WIII",
        "iata": "CGK",
        "name": "JAKARTA",
        "role": "fuel_enroute_airport",
        "source_pages": [15, 24],
    }]
    flight["weather"].extend([
        {
            "location": "WIII",
            "record_type": "METAR",
            "text": "SA 160500 04012KT 6000 SCT020 TEMPO 4000 RA",
            "source_page": 15,
            "source_role": "fuel_enroute_airport",
        },
        {
            "location": "WIII",
            "record_type": "TAF",
            "text": "FT 160500 4000 HZ BECMG 05011KT 8000 NSW",
            "source_page": 15,
            "source_role": "fuel_enroute_airport",
        },
    ])
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    findings.extend(
        {
            "engine": "notam",
            "severity": "warning",
            "title": f"Fuel enroute airport NOTAM FE{index}/26",
            "summary": f"Fuel enroute source fact {index}",
            "details": [],
            "data": {
                "role": "fuel enroute airport",
                "source_role": "fuel_enroute_airport",
                "location": "WIII",
                "notam_id": f"FE{index}/26",
                "raw_text": f"EXACT WIII ITEM E {index}",
                "priority_score": 10 - index,
                "pertinence_rank": 3,
                "pertinence_kind": "runway_approach_restriction",
                "applicability": "active",
                "source_page": 24,
            },
        }
        for index in range(1, 7)
    )
    out = tmp_path / "selected-airport-role-cards.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    airport_page = next(
        page.get_text()
        for page in document
        if all(
            station in page.get_text()
            for station in ("EBBR", "WSSS", "WSAP", "VTBD", "WIII")
        )
    )
    for station in ("EBBR", "WSSS", "WSAP", "VTBD", "WIII"):
        assert station in airport_page
    assert "SA 160500 04012KT" in airport_page
    assert "FT 160500 4000 HZ" in airport_page
    airport_page_flat = " ".join(airport_page.split())
    # The PDF consumes the exact compact shared summaries. Full notice IDs,
    # validity and item-E remain available in the dashboard/audit detail but
    # are intentionally not republished on the REV3 airport card.
    assert "Fuel enroute source fact 1" in airport_page_flat
    for index in range(1, 7):
        assert f"FE{index}/26" not in airport_page
        assert f"EXACT WIII ITEM E {index}" not in airport_page
    edto_page = " ".join(
        page.get_text()
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )
    assert "VTBD - EDTO" in edto_page
    assert "WIII - FUEL ENROUTE AIRPORT" in edto_page


def test_long_route_and_level_profile_continue_verbatim_on_airport_pages(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    route_tokens = [f"RTE{index:03d}" for index in range(1, 181)]
    profile_tokens = [f"FIX{index:03d}/F{300 + index:03d}" for index in range(1, 91)]
    flight["route_text"] = " ".join(route_tokens)
    flight["planned_level_profile"] = "/".join(profile_tokens)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "long-route-profile.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    airport_pages = [
        page
        for page in document
        if "AIRPORTS / NOTAM APPLICABILITY" in page.get_text()
    ]
    continuation_pages = [
        page
        for page in airport_pages
        if "VERBATIM CONTINUATION" in page.get_text()
    ]
    assert continuation_pages
    text = " ".join(page.get_text() for page in continuation_pages)
    profile_source_tokens = [
        token
        for fix_level in profile_tokens
        for token in fix_level.split("/")
    ]
    # Wrapped source lines remain one visible ordered route. Repeating the
    # "CFP ROUTE" label between lines would break this exact fact.
    assert " ".join(route_tokens) in " ".join(text.split())
    for token in (*route_tokens, *profile_source_tokens):
        assert token in text
    for page in continuation_pages:
        rect = page.rect
        for word in page.get_text("words"):
            assert 0 <= word[0] <= word[2] <= rect.width
            assert 0 <= word[1] <= word[3] <= rect.height


def test_route_timeline_uses_governed_roles_not_arbitrary_fir_points():
    flight = {
        "scheduled_departure_utc": "2026-08-01T10:00:00+00:00",
        "departure": "AAAA",
        "destination": "BBBB",
        "route_waypoints": [
            {"name": "AAAA", "actm_minutes": 0},
            {"name": "-FIRX", "actm_minutes": 20},
            {"name": "START", "actm_minutes": 100},
            {"name": "MAXIMUM", "actm_minutes": 110},
            {"name": "END", "actm_minutes": 120},
            {"name": "BBBB", "actm_minutes": 180},
        ],
        "edto": {
            "sectors": [{"entry": {"actm_minutes": 60}}],
        },
    }
    briefing = {
        "hazards": {
            "sigmet_cards": [{
                "sigmet_id": "WX1",
                "valid_to": "010900",
            }],
        },
        "terrain": {
            "events": [{
                "first_high": {
                    "name": "START",
                    "actm_minutes": 100,
                    "msa_hundreds_ft": 110,
                },
                "maximum": {
                    "name": "MAXIMUM",
                    "actm_minutes": 110,
                    "msa_hundreds_ft": 166,
                },
                "last_high": {
                    "name": "END",
                    "actm_minutes": 120,
                    "msa_hundreds_ft": 120,
                },
            }],
        },
    }

    entries = _route_anchor_entries(flight, briefing)

    assert [entry["label"] for entry in entries] == [
        "WX1 EXP",
        "DEP",
        "EDTO",
        "START 110*",
        "MAXIMUM 166*",
        "END 120*",
        "BBBB",
    ]
    assert all(entry["label"] != "FIRX" for entry in entries)


def test_terrain_table_keeps_one_filed_point_after_threshold_drop():
    flight = {
        "route_waypoints": [
            {"name": "BEFORE", "actm_minutes": 10, "msa_hundreds_ft": 40},
            {"name": "HIGH-A", "actm_minutes": 20, "msa_hundreds_ft": 117},
            {"name": "HIGH-B", "actm_minutes": 30, "msa_hundreds_ft": 124},
            {"name": "DROP", "actm_minutes": 40, "msa_hundreds_ft": 53},
            {"name": "AFTER", "actm_minutes": 50, "msa_hundreds_ft": 48},
        ],
    }
    briefing = {
        "terrain": {
            "events": [{
                "preceding": flight["route_waypoints"][0],
                "first_high": flight["route_waypoints"][1],
                "maximum": flight["route_waypoints"][2],
                "last_high": flight["route_waypoints"][2],
                "drop": flight["route_waypoints"][3],
            }],
        },
    }

    assert [
        point["name"] for point in _terrain_table_points(flight, briefing)
    ] == ["BEFORE", "HIGH-A", "HIGH-B", "DROP", "AFTER"]


def test_long_station_source_rows_continue_without_loss_or_overlap(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def high_cardinality_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        panel = view["airport_operational_panels"][0]
        panel["card_summary_lines"] = [
            {
                "kind": "notam",
                "text": (
                    f"STATION-SOURCE-{index:02d} BEGIN "
                    + "complete operational wording remains visible " * 8
                    + f" END-{index:02d}"
                ),
            }
            for index in range(1, 13)
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        high_cardinality_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "long-station-source-rows.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    airport_pages = [
        page
        for page in document
        if "AIRPORTS / NOTAM APPLICABILITY" in page.get_text()
    ]
    airport_text = " ".join(page.get_text() for page in airport_pages)
    assert len(airport_pages) > 1
    for index in range(1, 13):
        assert f"STATION-SOURCE-{index:02d}" in airport_text
        assert f"END-{index:02d}" in airport_text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


def test_all_alternates_and_every_selected_notam_detail_reach_pdf(
    tmp_path,
):
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    alternate_icaos = ("WSAP", "WADD", "WMKK", "VTBS")
    flight["alternates"] = [
        {
            "airport": icao,
            "runway": f"{index:02d}",
            "approach": "CAT1DME",
            "minima": f"{400 + index}FT/1600M",
        }
        for index, icao in enumerate(alternate_icaos, start=1)
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] not in {"depressurisation", "notam"}
    ]
    for index, icao in enumerate(alternate_icaos, start=1):
        findings.append({
            "engine": "notam",
            "severity": "warning",
            "title": f"Alternate NOTAM ALT{index}/26",
            "summary": f"SELECTED SUMMARY {icao}",
            "details": [],
            "data": {
                "role": "destination alternate",
                "source_role": "alternate",
                "location": icao,
                "notam_id": f"ALT{index}/26",
                "raw_text": f"FULL ITEM E {icao} END-{index}",
                "valid_from_utc": f"2026-08-{index:02d}T00:00:00Z",
                "valid_to_utc": f"2026-08-{index:02d}T12:00:00Z",
                "schedule": f"DAILY 0{index}00-1{index}00",
                "applicability": "active",
                "window_start_utc": "2026-08-01T01:00:00Z",
                "window_end_utc": "2026-08-01T03:00:00Z",
                "source_page": 20 + index,
                "priority_score": 20 - index,
                "pertinence_rank": index,
                "pertinence_kind": "runway_approach_restriction",
            },
        })
    out = tmp_path / "all-alternates-and-selected-notams.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    airport_text = " ".join(
        page.get_text()
        for page in document
        if "AIRPORTS / NOTAM APPLICABILITY" in page.get_text()
    )
    folded = " ".join(airport_text.split())
    for index, icao in enumerate(alternate_icaos, start=1):
        assert f"{icao} - DESTINATION ALTERNATE" in folded
        for fact in (
            f"ALT{index}/26",
            f"DAILY 0{index}00-1{index}00",
            "active",
            f"FULL ITEM E {icao} END-{index}",
        ):
            assert fact in folded
    assert "ALL SELECTED NOTAM DETAILS" in folded
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


def test_full_shared_performance_fuel_and_deferred_declarations_reach_pdf(
    tmp_path,
):
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["fuel_summary"]["complete_detail_sentinel"] = (
        "FULL FUEL DETAIL SENTINEL END"
    )
    flight["performance"] = {
        "runway_condition": "DRY",
        "eosid": "STRAIGHT OUT",
        "obstacle_rtow_kg": 297_401,
        "landing_rtow_kg": 312_028,
        "structural_rtow_kg": 280_003,
        "controlling_rtow_kg": 290_004,
        "maximum_fuel_available_kg": 99_147,
        "packs_on": True,
        "anti_ice_on": False,
    }
    flight["fuel_summary"]["rows"]["excess_fuel"]["time_minutes"] = 31
    flight["deferred_items"] = [{
        "item_type": "MEL",
        "reference": "99-99-01",
        "description": "FULL DECLARATION DESCRIPTION END",
        "company_remark": "FULL COMPANY REMARK END",
        "penalty": "FULL PENALTY END",
        "source_page": 1,
    }]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "full-performance-fuel-deferred.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    text = " ".join(" ".join(page.get_text() for page in document).split())
    for fact in (
        "FULL SHARED PERFORMANCE / FUEL DETAILS",
        "297401",
        "312028",
        "280003",
        "290004",
        "DRY",
        "STRAIGHT OUT",
        "99147",
        "PACKS / ANTI-ICE ON / OFF",
        "31 min (00:31)",
        "FULL FUEL DETAIL SENTINEL END",
        "FULL CFP DEFERRED DECLARATIONS",
        "MEL | 99-99-01",
        "FULL DECLARATION DESCRIPTION END",
        "FULL COMPANY REMARK END",
        "FULL PENALTY END",
    ):
        assert fact in text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


def test_all_terrain_events_and_full_vaa_source_text_reach_pdf(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def full_hazard_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["terrain"]["events"] = [
            {
                "terrain_event_id": f"TERRAIN-EVENT-{index:02d}",
                "first_high": {
                    "name": f"START-{index:02d}",
                    "actm_minutes": index * 10,
                    "msa_hundreds_ft": 110 + index,
                },
                "maximum": {
                    "name": f"MAX-{index:02d}",
                    "actm_minutes": index * 10 + 2,
                    "msa_hundreds_ft": 150 + index,
                },
                "last_high": {
                    "name": f"END-{index:02d}",
                    "actm_minutes": index * 10 + 4,
                    "msa_hundreds_ft": 120 + index,
                },
            }
            for index in range(1, 7)
        ]
        view["vaa"]["cfp_advisories"] = [
            {
                "name": f"VOLCANIC ASH TEST {index}",
                "valid_from": "010000",
                "valid_to": "010600",
                "derived": f"DERIVED VAA SCREENING {index}",
                "text": (
                    f"FULL VAA SOURCE {index} "
                    + "complete advisory source wording " * 20
                    + f" VAA-END-{index}"
                ),
                "fir": f"FIR-{index}",
                "source_page": 40 + index,
            }
            for index in range(1, 4)
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        full_hazard_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "all-terrain-and-full-vaa.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    text = " ".join(" ".join(page.get_text() for page in document).split())
    assert "ALL TERRAIN EVENTS / UNMATCHED EXPOSURES" in text
    for index in range(1, 7):
        assert f"TERRAIN-EVENT-{index:02d}" in text
        assert f"END-{index:02d}" in text
    assert text.count("UNMATCHED EXPOSURE - MANUAL REVIEW REQUIRED") >= 6
    assert "FULL VOLCANIC-ASH SOURCE DETAILS" in text
    for index in range(1, 4):
        assert f"FULL VAA SOURCE {index}" in text
        assert f"VAA-END-{index}" in text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


def test_dual_role_station_is_selected_once_per_pdf_section(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["alternates"] = [
        {"airport": "WSAP", "runway": "20", "approach": "CAT1DME"},
        {"airport": "WADD", "runway": "27", "approach": "CAT1DME"},
    ]
    flight["edto"]["airports"] = [
        {"airport": "WADD", "runway": "27", "approach": "CAT1DME"}
    ]
    flight["fuel_enroute_airports"] = [
        {"airport": "WADD", "role": "fuel_enroute_airport"}
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "dual-role-station.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    airport_text = " ".join(
        page.get_text()
        for page in document
        if "AIRPORTS / NOTAM APPLICABILITY" in page.get_text()
    )
    edto_text = " ".join(
        page.get_text()
        for page in document
        if "EDTO / ENROUTE AIRPORTS" in page.get_text()
    )
    merged_title = "WADD - ALTN / EDTO / FUEL ENROUTE"
    assert airport_text.count(merged_title) == 1
    assert edto_text.count(merged_title) == 1
    assert "WADD - ALTN / EDTO / FUEL ENROUTE AI" not in airport_text
    assert "WADD - ALTN / EDTO / FUEL ENROUTE AI" not in edto_text


def test_combined_pdf_consumes_shared_performance_publication(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["masses"]["planned_takeoff_weight_kg"] = 200_000
    flight["performance"] = {
        "obstacle_rtow_kg": 297_400,
        "landing_rtow_kg": 312_027,
        "structural_rtow_kg": 280_000,
        "controlling_rtow_kg": 290_000,
    }
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "shared-performance.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    overview = " ".join(document[0].get_text().split())
    analysis = " ".join(document[1].get_text().split())
    assert "280,000" in overview
    assert "+80,000" in overview
    assert "RTOW 280,000 kg." in analysis
    assert "PTOW 200,000 kg gives 80,000 kg margin." in analysis
    assert "RTOW 290,000 kg." not in analysis


@pytest.mark.parametrize("missing", ["ptow", "limits"])
def test_missing_performance_inputs_fail_closed_in_physical_pdf(
    tmp_path,
    missing,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["performance"] = {"structural_rtow_kg": 280_000}
    if missing == "ptow":
        flight["masses"].pop("planned_takeoff_weight_kg", None)
    else:
        flight["performance"] = {}
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / f"missing-performance-{missing}.pdf"

    render_combined_briefing(flight, findings, [], out)

    analysis = " ".join(fitz.open(out)[1].get_text().split())
    assert "PTOW/RTOW margin unavailable - performance review required." in analysis
    assert "kg gives" not in analysis


def test_performance_margin_presentation_is_fail_closed_and_tri_state():
    assert _performance_margin_presentation({
        "status": "manual-review-required",
        "margin_kg": None,
    }) == ("--", "review required", WEATHER_AMBER)
    assert _performance_margin_presentation({
        "status": "limit-exceeded",
        "margin_kg": -500,
    }) == ("-500 kg", "limit exceeded", CRITICAL)
    assert _performance_margin_presentation({
        "status": "within-limit",
        "margin_kg": 80_000,
    }) == ("+80,000 kg", "to selected RTOW", EDTO_GREEN)
    assert _performance_selected_presentation({
        "status": "manual-review-required",
        "selected_rtow_kg": 280_000,
    }) == ("review required", WEATHER_AMBER)
    assert _performance_selected_presentation({
        "status": "limit-exceeded",
        "selected_rtow_kg": 280_000,
    }) == ("limit exceeded", CRITICAL)
    assert _performance_selected_presentation({
        "status": "within-limit",
        "selected_rtow_kg": 280_000,
    }) == ("most limiting", EDTO_GREEN)


def test_hazard_page_states_the_direct_vaac_centre_coverage(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "full-vaac-centre-coverage.pdf"
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    hazard = "\n".join(page.get_text() for page in fitz.open(out))
    assert "VAAC CENTRES" in hazard
    assert "0/9 reached" in hazard


def test_hazard_page_prints_one_honest_fallback_when_no_sigmet_cards_exist(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def no_sigmet_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["hazards"]["sigmet_cards"] = []
        return view

    monkeypatch.setattr(briefing_module, "build_briefing_view", no_sigmet_view)
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    out = tmp_path / "one-sigmet-fallback.pdf"

    render_combined_briefing(flight, findings, [], out)

    hazard = fitz.open(out)[5].get_text()
    assert hazard.count("ENROUTE SIGMET") == 1
    assert hazard.count(
        "No enroute SIGMET is printed in this CFP weather package."
    ) == 1


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
    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )
    hazard = " ".join(
        page.get_text()
        for page in fitz.open(out)
        if "OPERATIONAL HAZARD ASSESSMENT" in page.get_text()
    ).upper()

    assert "2/9 REACHED" in hazard
    for centre in centres:
        assert centre in hazard
    assert "ANCHORAGE: REACHED" in hazard
    assert "LONDON: UNAVAILABLE" in hazard


def test_hazard_continuations_keep_every_sigmet_card_and_vaac_centre(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def high_cardinality_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["hazards"]["sigmet_cards"] = [
            {
                "name": f"TEST SIGMET {index:02d}",
                "sigmet_id": f"T{index:02d}",
                "valid_from": "010000",
                "valid_to": "010400",
                "layer": "FL200/300",
                "movement": "MOV E 10KT",
                "disposition": "NOT PROMOTED",
                "screening": f"Deterministic screening receipt {index:02d}.",
            }
            for index in range(1, 8)
        ]
        view["hazards"]["vaac_reach"] = {
            "summary": "7/14 reached",
            "centres": [
                {
                    "centre": f"CENTRE-{index:02d}",
                    "status": (
                        "review required because the complete governed "
                        "source response remains pending LONG-VAAC-END"
                        if index == 14
                        else "reached" if index % 2 else "unavailable"
                    ),
                }
                for index in range(1, 15)
            ],
        }
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        high_cardinality_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "continued-hazards.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    hazard_pages = [
        page.get_text()
        for page in document
        if "OPERATIONAL HAZARD ASSESSMENT" in page.get_text()
    ]
    hazard_text = "\n".join(hazard_pages)
    assert len(hazard_pages) >= 4
    assert all("CONTINUED (" in text for text in hazard_pages[1:])
    for index in range(1, 8):
        assert f"TEST SIGMET {index:02d}" in hazard_text
        assert f"screening receipt {index:02d}" in hazard_text
    for index in range(1, 15):
        assert f"CENTRE-{index:02d}" in hazard_text
    assert "LONG-VAAC-END" in hazard_text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]


def test_critical_analysis_continues_every_shared_communication(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def high_cardinality_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["communications"] = [
            {
                "time": f"{index:02d}10Z",
                "actm": f"0{index}.10",
                "event": f"CONTACT EVENT COMMS-{index:02d} BEFORE BOUNDARY",
                "detail": f"Exact shared communication detail COMMS-{index:02d} remains visible.",
            }
            for index in range(1, 8)
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        high_cardinality_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "communications-continuation.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    analysis_pages = [
        page.get_text()
        for page in document
        if "DECISION ANALYSIS" in page.get_text()
    ]
    text = " ".join(analysis_pages)
    assert len(analysis_pages) > 1
    assert all("CONTINUED (" in page for page in analysis_pages[1:])
    for index in range(1, 8):
        assert f"COMMS-{index:02d}" in text


def test_critical_analysis_paginates_wrapped_and_oversized_communications(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def long_communication_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["communications"] = [
            {
                "time": f"0{index}10Z",
                "actm": f"0{index}.10",
                "event": f"LONG-COMMS-{index:02d}",
                "detail": (
                    f"DETAIL-{index:02d} "
                    + "full shared communication wording " * 45
                    + f" END-DETAIL-{index:02d}"
                ),
            }
            for index in range(1, 6)
        ]
        view["communications"].append({
            "time": "9910Z",
            "actm": "99.10",
            "event": "OVERSIZED-COMMS",
            "detail": (
                "OVERSIZED-START "
                + "single oversized shared communication wording " * 240
                + " OVERSIZED-END"
            ),
        })
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        long_communication_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "wrapped-communications.pdf"

    render_combined_briefing(
        flight, findings, [], out, include_audit_appendix=True
    )

    document = fitz.open(out)
    continuation_pages = [
        page
        for page in document
        if "DECISION ANALYSIS - CONTINUED" in page.get_text()
    ]
    continuation_text = " ".join(page.get_text() for page in continuation_pages)
    assert len(continuation_pages) >= 3
    for index in range(1, 6):
        assert f"LONG-COMMS-{index:02d}" in continuation_text
        assert f"END-DETAIL-{index:02d}" in continuation_text
    assert "OVERSIZED-START" in continuation_text
    assert "OVERSIZED-END" in continuation_text
    assert continuation_text.count("9910Z") >= 2
    assert "CONTACT CONT." in continuation_text
    for page in continuation_pages:
        rect = page.rect
        for word in page.get_text("words"):
            assert 0 <= word[0] <= word[2] <= rect.width
            assert 0 <= word[1] <= word[3] <= rect.height


def test_production_combined_renderer_has_no_reference_specific_hardcoding():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "odss"
        / "combined_brief.py"
    ).read_text(encoding="utf-8")
    for identifier in ("SQ214", "WIII", "WADD", "WSAP"):
        assert identifier not in source
    assert re.search(
        r"(?:source[_ -]?page|page_number)\s*[:=]\s*47\b",
        source,
        re.IGNORECASE,
    ) is None
    assert re.search(
        r"(?:chart|chart_number)\s*[:=]\s*5\b",
        source,
        re.IGNORECASE,
    ) is None
    assert "base64" not in source.lower()
    assert "rev3_visual_reference" not in source.lower()


def test_hazard_page_holds_raw_unclassified_charts_for_manual_review(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    manifest = {
        "charts": [
            {
                "chart_number": index,
                "page_number": 40 + index,
                "kind": "unclassified",
                "classification_status": "unclassified",
                "verified": False,
            }
            for index in range(1, 11)
        ]
    }
    out = tmp_path / "manual-review-weather-charts.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        out,
        weather_charts=manifest,
        include_audit_appendix=True,
    )

    text = " ".join(
        page.get_text()
        for page in fitz.open(out)
        if "OPERATIONAL HAZARD ASSESSMENT" in page.get_text()
    ).upper()
    assert "MANUAL REVIEW REQUIRED" in text
    assert "NO GOVERNED ROUTE-CONTEXT CLASSIFICATION IS AVAILABLE" in text
    assert "RAW CHARTS HELD: 10" in text
    assert "UNCLASSIFIED" not in text


def test_hazard_continuations_print_every_governed_selected_wafc_chart(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    manifest = {
        "charts": [
            {
                "chart_number": index,
                "page_number": 40 + index,
                "label": f"ROUTE-CHART-{index:02d}",
                "kind": "sigwx_high_level",
                "classification_status": "classified",
                "verified": True,
                "valid_time_utc": f"2026-08-01T{index:02d}:00:00Z",
                "route_context": {
                    "status": "matched",
                    "governed": True,
                    "basis": f"Governed route/validity match {index:02d}",
                },
            }
            for index in range(1, 8)
        ]
    }

    def selected_chart_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["hazards"]["weather_chart_selection"] = {
            "status": "selected",
            "reason": "Seven governed route-context charts are selected.",
            "selected_charts": [
                {
                    key: value
                    for key, value in chart.items()
                    if key not in {"classification_status", "verified"}
                }
                for chart in manifest["charts"]
            ],
            "raw_chart_count": len(manifest["charts"]),
        }
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        selected_chart_view,
    )
    out = tmp_path / "selected-weather-chart-continuations.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        out,
        weather_charts=manifest,
        include_audit_appendix=True,
    )

    document = fitz.open(out)
    hazard_pages = [
        page
        for page in document
        if "OPERATIONAL HAZARD ASSESSMENT" in page.get_text()
    ]
    text = " ".join(page.get_text() for page in hazard_pages)
    assert len(hazard_pages) == 3
    assert all("CONTINUED (" in page.get_text() for page in hazard_pages[1:])
    for index in range(1, 8):
        assert f"ROUTE-CHART-{index:02d}" in text
    for page in hazard_pages:
        rect = page.rect
        for word in page.get_text("words"):
            assert 0 <= word[0] <= word[2] <= rect.width
            assert 0 <= word[1] <= word[3] <= rect.height


def test_selected_wafc_chart_fails_closed_when_source_bytes_change(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from app.odss import weather_charts as weather_charts_module

    real_build = briefing_module.build_briefing_view

    def selected_chart_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["hazards"]["weather_chart_selection"] = {
            "status": "selected",
            "reason": "A governed route-context chart is selected.",
            "selected_charts": [{
                "page_number": 1,
                "label": "GOVERNED ROUTE CHART",
                "kind": "sigwx_high_level",
                "image_sha256": hashlib.sha256(
                    b"original-governed-chart-bytes"
                ).hexdigest(),
            }],
            "raw_chart_count": 1,
        }
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        selected_chart_view,
    )
    monkeypatch.setattr(
        weather_charts_module,
        "extract_chart_image",
        lambda source, page_number: b"swapped-source-page-bytes",
    )
    source = tmp_path / "source.pdf"
    source_document = fitz.open()
    source_document.new_page(width=595, height=842)
    source_document.save(source)
    source_document.close()
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]

    with pytest.raises(ValueError, match="source image SHA-256 mismatch"):
        render_combined_briefing(
            flight,
            findings,
            [],
            tmp_path / "swapped-chart.pdf",
            source_pdf_path=str(source),
            weather_charts={"charts": []},
        )


def test_publication_filename_carries_flight_and_expanded_date():
    from app.odss.combined_brief import combined_briefing_filename

    assert combined_briefing_filename("SIA365", "07AUG26") == "SIA365_07AUG2026_Flight_Briefing.pdf"
    assert combined_briefing_filename("SQ366", "04AUG2026") == "SQ366_04AUG2026_Flight_Briefing.pdf"
    # A date the pattern cannot vouch for is omitted, never guessed.
    assert combined_briefing_filename("SIA23", "??") == "SIA23_Flight_Briefing.pdf"


def test_tankering_excess_is_written_as_tankering(tmp_path):
    # Boss, 21 Aug 2026 (0:54 fuel video): "the number is correct, but the
    # way it's written is not exactly right" - when CFP page 1 itemises the
    # excess as TANKER with a return-sector requirement, the report says
    # tankering, in his words, not a bare EXCESS figure.
    page1 = SQ23_PAGE1.replace(
        "PAGE  1 OF 21 SIA23 JFK/SIN 25JUL26\n",
        "PAGE  1 OF 21 SIA23 JFK/SIN 25JUL26\n"
        "REMARKS:\n"
        "EXCESS FUEL:\n"
        "1.INTAM     0KG\n"
        "2.FMC       0KG\n"
        "3.MEL       0KG\n"
        "4.TANKER    18847KG RTN SECTOR REQ 23324KG\n"
        "5.TMM       0KG\n",
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(page1)
    assert flight["fuel_summary"]["tanker_return_sector_req_kg"] == 23324
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    flight["actual_takeoff_utc"] = "2026-07-16T09:52:00+00:00"
    flight["timing_view"] = build_timing_view(flight, findings, flight["actual_takeoff_utc"])
    out = tmp_path / "combined.pdf"
    render_combined_briefing(flight, findings, [], out)
    document = fitz.open(out)
    first = document[0].get_text()
    assert "TANKER" in first
    analysis = document[1].get_text()
    assert "tankering" in analysis
    assert "return sector" in analysis
    assert "23,324" in analysis


# --- 23 Aug 2026: page-1 PERFORMANCE card, pertinent NOTAMs, arrival basis ---


def test_page_one_carries_the_performance_card_in_place_of_flight_basis(rendered):
    # Boss, 21 Aug (R2-9): "add PERFORMANCE card to p1 (GPT layout)". The
    # flight-basis facts already live in the header, chips and footer.
    first = rendered[0].get_text()
    assert "CFP P1 - PERFORMANCE" in first
    assert "CFP P1 - FLIGHT BASIS" not in first
    assert "LIMIT" in first
    assert "EOSID" in first


def test_destination_card_states_the_arrival_basis(rendered):
    # Boss, 21 Aug (R2-14): "is it based on the flight time?... too small".
    first = rendered[0].get_text()
    assert "ETA 2240Z" in first
    assert "STD 0945Z" in first
    assert "filed EET" in first


def test_decision_timeline_states_its_clock_basis(rendered):
    second = rendered[1].get_text()
    assert "Filed EET" in second and "from STD 0945Z" in second
    # The fixture applies an actual take-off, so the clocks say so.
    assert "actual take-off 0952Z" in second


def test_pertinent_notam_lines_follow_the_panel_and_skip_the_highlight():
    from app.odss.combined_brief import _pertinent_notam_lines

    panel = {
        "card_summary_lines": [
            {"kind": "weather", "label": "METAR", "text": "SA 201900 11004KT 9999"},
            {"kind": "notam", "label": "SX120/25", "notam_id": "SX120/25", "text": "RWY 02C/20C closes 1730-2130Z; ETD 0050Z precedes closure by 16h40."},
            {"kind": "notam", "label": "SX97/26", "notam_id": "SX97/26", "text": "Rwy 02C/20C restriction applies during the applicable departure window."},
            {"kind": "notam", "label": "SX98/26", "notam_id": "SX98/26", "text": "Twy W9 closed."},
        ]
    }
    lines = _pertinent_notam_lines(panel, skip_notam_id="SX120/25", limit=2)
    assert lines == [
        "SX97/26 Rwy 02C/20C restriction applies during the applicable departure window.",
        "SX98/26 Twy W9 closed.",
    ]
    assert _pertinent_notam_lines({}, skip_notam_id=None, limit=2) == []
