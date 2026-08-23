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
    MARGIN,
    PAGE_SIZE,
    T_BODY,
    T_CARD_HEAD,
    T_MICRO,
    T_SMALL,
    WEATHER_AMBER,
    _audit_rev3_v8_briefing_projection,
    _performance_margin_presentation,
    _performance_selected_presentation,
    _eta_display,
    _hazard_page_plans,
    _operational_fir_boundary_summary,
    _operational_terrain_summary,
    _route_anchor_entries,
    _terrain_table_points,
    combined_briefing_cache_token,
    crop_source_region,
    draw_analysis_page,
    draw_operational_enroute_assurance_page,
    governed_deferred_source_target,
    render_combined_briefing,
)
from app.odss.briefing import build_briefing_view
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


def test_eta_display_keeps_missing_destination_timing_unavailable():
    assert _eta_display("0416") == "ETA 0416Z"
    assert _eta_display("0416Z") == "ETA 0416Z"
    assert _eta_display("--") == "ETA --"
    assert _eta_display(None) == "ETA --"


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
    # The boss-facing flow is seven compact operational sections.  This
    # fixture also carries real terrain events, so the controlled terrain
    # evidence is appended as page 8 instead of being forced into the core.
    assert len(rendered) == 8
    first = rendered[0].get_text()
    assert "CFP P1 - ROUTE / LEVELS" in first
    # The route/levels context remains above the five boss-facing summary
    # cards and phase-action strip.
    assert "CFP P1 - ROUTE / LEVELS + ANALYSIS OVERLAY" in first
    for card in ("PERFORMANCE", "FUEL", "STATUS", "WEATHER", "ALTERNATES"):
        assert card in first
    assert "PHASE ACTION" in first
    assert "Tanks 118,274 kg" in first.replace(" ", ",")
    titles = "\n".join(rendered[n].get_text() for n in range(len(rendered)))
    for expected in (
        "DECISION ANALYSIS",
        "PERFORMANCE / FUEL / STATUS",
        "MEL/CDL AND CDDL",
        "AIRPORTS / ALTERNATES",
        "WEATHER / ROUTE HAZARDS",
        "ENROUTE / ASSURANCE",
        "HIGH TERRAIN EXPOSURE AND DEPRESSURISATION",
    ):
        assert expected in titles
    weather_page = " ".join(rendered[5].get_text().split())
    assert "Coverage gaps are source gaps, not NIL findings." in weather_page
    airports_page = " ".join(rendered[4].get_text().split())
    assert "PLAN · EBBR RWY 07R" in airports_page
    assert "PLAN · WSSS RWY 20R" in airports_page
    assert "1 SECTOR / 1 ALTN / FULL EDTO: DASHBOARD" in airports_page
    performance_page = " ".join(rendered[2].get_text().split())
    assert "RUNWAY / CONDITION · EBBR -- / --" in performance_page


def test_compact_pdf_has_seven_core_outline_entries_plus_real_terrain(rendered):
    assert [row[1] for row in rendered.get_toc()] == [
        "Flight Overview",
        "Decision Analysis",
        "Performance / Fuel / Status",
        "MEL/CDL Evidence",
        "Airports / Alternates",
        "Weather / Route Hazards",
        "Enroute / Assurance",
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
    page_text = document[3].get_text()
    assert page_text.count("CABIN COMPACTORS") == 1
    assert page_text.count("CTRL / SYSB") == 1
    assert page_text.count("CDL 20-20 / 30-30") == 1
    assert "CDL 10-10" in page_text
    assert "UNSPECIFIED" not in page_text
    assert "UNCLASSIFIED" not in page_text
    governed_links = [
        str(link.get("uri") or "")
        for link in document[3].get_links()
        if "governed-deferred-reference" in str(link.get("uri") or "")
    ]
    assert len(governed_links) == 2
    assert any("reference=10-10" in link for link in governed_links)
    assert any("reference=20-20" in link for link in governed_links)
    assert page_text.count("GOVERNED LINK UNAVAILABLE · CFP SOURCE HELD") == 2
    assert "+2 SOURCE DECLARATIONS REMAIN IN DASHBOARD" in page_text


def test_compact_sq910_four_shape_declarations_never_publish_placeholders(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = {
        "state": "verified",
        "rows": {
            "fuel_in_tanks": {"fuel_kg": 43_891},
            "flt_plan_reqmt": {"fuel_kg": 25_044},
        },
    }
    flight["performance"] = {"maximum_fuel_available_kg": 36_420}
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

    document = fitz.open(output)
    overview_text = " ".join(document[0].get_text().split())
    assert "MAX FUEL 36,420 vs tanks 43,891 · RECONCILE" in overview_text
    assert "ENG 2 LATCH · CHECK EACH DEPARTURE" in overview_text

    page_text = document[2].get_text().upper()
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


def test_overview_premeasures_dense_destination_before_lossless_alternate(
    tmp_path,
    monkeypatch,
):
    """A seven-line bulletin block can still be dense once the selected
    operational highlight and preferred-alternate plan are included.

    This is the production shape held by SQ223 on 18 Aug.  Page 1 must choose
    its wider/taller destination geometry before drawing; failing late would
    either abort the briefing or tempt a caller to truncate source detail.
    """
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view
    destination_metar = "SA 172000 AUTO 05006KT 9999 // NCD 08/07 Q1018="
    destination_taf = (
        "FT 171706 1718/1900 05005KT 9999 FEW045 FM180300 29010KT "
        "9999 SCT045 FM181400 05005KT 9999 SCT040 FM181800 05005KT "
        "9999 -SHRA SCT035 BKN045="
    )
    destination_highlight = (
        "LOC IGD 109.5 RWY21 subject to interruption / possible signal "
        "oscillation due crane operations; runway is not reported closed."
    )

    def dense_destination_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["destination"]["weather"].update({
            "metar": destination_metar,
            "taf": destination_taf,
        })
        view["overview"]["destination"]["primary_operational_highlight"] = {
            "text": destination_highlight,
            "signal_family": "approach_navaid",
            "notam_id": "1H5709/26",
            "source_page": 22,
        }
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        dense_destination_view,
    )
    flight = sample_flight()
    flight["alternates"] = [{
        "airport": "YGEL",
        "runway": "21",
        "approach": "VORDME",
        "distance_nm": 242,
    }]
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "dense-destination-lossless-alternate.pdf"

    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    overview_text = " ".join(document[0].get_text().split())
    for expected in (
        destination_metar,
        destination_taf,
        destination_highlight,
        "GET/YGEL/21",
        "VORDME",
        "242 NM",
        "00:55",
        "4,680 kg",
    ):
        assert " ".join(expected.split()) in overview_text
    physical = scan_physical_pdf(output)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][0]["visible_overlap_count"] == 0


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
    assert len(document) == 8
    assert "+1 IN DASHBOARD" in document[3].get_text()
    assert "+1 SOURCE DECLARATION REMAINS IN DASHBOARD" in document[3].get_text()
    assert "Full selected detail remains in dashboard" in document[4].get_text()


def test_compact_airport_matrix_keeps_vhhh_without_inventing_preferred_status(
    tmp_path,
    monkeypatch,
):
    from copy import deepcopy

    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def lower_card_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        panels = list(view["airport_operational_panels"])
        edto_panel = next(
            panel
            for panel in panels
            if "edto" in set(panel.get("role_keys") or [])
        )
        edto_panel["card_summary_lines"] = [
            {
                "kind": "metar",
                "label": "METAR",
                "text": (
                    "SA 201900 10005KT 060V130 9999 -RA FEW010 BKN018 "
                    "BKN025 26/25 Q1005 NOSIG RMK A2968="
                ),
            },
            {
                "kind": "taf",
                "label": "TAF",
                "text": (
                    "FT 201700 2018/2124 06005KT 7000 FEW010 BKN032 BKN060 "
                    "TEMPO 2018/2024 11007KT 4000 SHRA FEW008 FEW012CB "
                    "BKN017 BKN040 TEMPO 2100/2104 2000 +TSRA"
                ),
            },
            {
                "kind": "notam",
                "text": "Runway restriction applies during the selected window.",
            },
            {
                "kind": "notam",
                "text": "LOWER-FOUR-FINAL selected source fact remains complete.",
            },
        ]

        alternate = deepcopy(
            next(
                panel
                for panel in panels
                if "alternate" in set(panel.get("role_keys") or [])
            )
        )
        alternate.update({
            "icao": "VHHH",
            "role_key": "alternate",
            "role_keys": ["alternate"],
            "role": "preferred alternate",
            "roles": ["preferred alternate"],
            "operational_rows": [{
                "runway": "07R",
                "approach": "CAT1DME",
                "minima": "588FT/2000M",
                "distance_nm": 657,
                "time_minutes": 104,
                "fuel_kg": 9059,
            }],
            "card_summary_lines": [
                {
                    "kind": "metar",
                    "label": "METAR",
                    "text": (
                        "SA 201900 12008KT 9999 FEW020 SCT040 29/25 Q1007 "
                        "NOSIG RMK A2974="
                    ),
                },
                {
                    "kind": "taf",
                    "label": "TAF",
                    "text": (
                        "FT 201700 2018/2124 12010KT 9999 FEW020 SCT040 "
                        "TEMPO 2018/2024 5000 SHRA FEW012CB BKN020 "
                        "TEMPO 2100/2104 2500 +TSRA SCT008CB BKN015"
                    ),
                },
                {
                    "kind": "notam",
                    "text": "Approach restriction applies during the selected window.",
                },
                {
                    "kind": "notam",
                    "text": "LOWER-FIVE-FINAL selected source fact remains complete.",
                },
            ],
        })
        panels.append(alternate)
        view["airport_operational_panels"] = panels
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        lower_card_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["alternates"].append({
        "airport": "VHHH",
        "runway": "07R",
        "approach": "CAT1DME",
        "minima": "588FT/2000M",
        "distance_nm": 657,
        "time_minutes": 104,
        "fuel_kg": 9059,
    })
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "compact-lower-airport-cards.pdf"

    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    airport_text = " ".join(document[4].get_text().split())
    assert len(document) == 8
    assert "VHHH" in airport_text
    assert "PREFERRED · VHHH" not in airport_text
    physical = scan_physical_pdf(output)
    assert physical["valid"], physical["violations"]


def test_compact_airport_single_alternate_row_keeps_honest_source_status(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def single_row_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        panels = [
            panel
            for panel in view["airport_operational_panels"]
            if not set(panel.get("role_keys") or [])
            & {"edto", "fuel_enroute_airport"}
        ]
        alternate = next(
            panel
            for panel in panels
            if "alternate" in set(panel.get("role_keys") or [])
        )
        alternate["card_summary_lines"] = [
            {
                "kind": "notam",
                "text": (
                    "SINGLE-ROW-FINAL selected source fact remains complete "
                    "after measured card placement."
                ),
            },
        ]
        view["airport_operational_panels"] = panels
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        single_row_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "compact-single-row-airport-cards.pdf"

    render_combined_briefing(flight, findings, [], output)

    document = fitz.open(output)
    airport_text = " ".join(document[4].get_text().split())
    assert len(document) == 8
    assert "PREFERRED · WSAP" in airport_text
    assert "METAR UNAVAILABLE · TAF UNAVAILABLE · 0 NOTICE(S)" in airport_text
    physical = scan_physical_pdf(output)
    assert physical["valid"], physical["violations"]


def test_compact_station_summary_fails_closed_before_truncating_source_facts(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def over_capacity_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        departure_panel = next(
            panel
            for panel in view["airport_operational_panels"]
            if "departure" in set(panel.get("role_keys") or [])
        )
        departure_panel["card_summary_lines"] = [{
            "kind": "notam",
            "label": "OVER-CAPACITY-01",
            "notam_id": "OVER-CAPACITY-01",
            "text": "complete selected source wording " * 80,
            "source_page": 16,
        }]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        over_capacity_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]

    with pytest.raises(ValueError, match="airport summary exceeds readable capacity"):
        render_combined_briefing(
            flight,
            findings,
            [],
            tmp_path / "over-capacity-compact-airport-card.pdf",
        )


def test_compact_station_summary_shows_three_shared_notices_with_sources(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def exact_station_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        panels = view["airport_operational_panels"]
        departure = next(
            panel
            for panel in panels
            if "departure" in set(panel.get("role_keys") or [])
        )
        destination = next(
            panel
            for panel in panels
            if "destination" in set(panel.get("role_keys") or [])
        )
        departure["selected_notams"] = [
            {"notam_id": f"DEP-{index:02d}"}
            for index in range(17)
        ]
        departure["card_summary_lines"] = [
            {
                "kind": "notam",
                "label": "SX120/25",
                "text": (
                    "RWY 02C/20C closes 1730-2130Z; ETD 0050Z "
                    "precedes closure by 16h40."
                ),
                "source_page": 16,
            },
            {
                "kind": "notam",
                "label": "SX97/26",
                "text": "RWY 02C/20C restriction applies during the departure window.",
                "source_page": 18,
            },
            {
                "kind": "notam",
                "label": "SX98/26",
                "text": "RWY 02R/20L is unavailable for civil use.",
                "source_page": 16,
            },
        ]
        destination["selected_notams"] = [
            {"notam_id": f"DST-{index:02d}"}
            for index in range(35)
        ]
        destination["card_summary_lines"] = [
            {
                "kind": "notam",
                "label": "1B3881/26",
                "text": "ILS RWY 24 unavailable during the destination window.",
                "source_page": 22,
            },
            {
                "kind": "notam",
                "label": "1B2938/26",
                "text": "RWY 06/24 strip grading applies during the destination window.",
                "source_page": 22,
            },
            {
                "kind": "notam",
                "label": "1B4113/26",
                "text": "TWY F1B closed due WIP.",
                "source_page": 22,
            },
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        exact_station_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    output = tmp_path / "three-shared-airport-notices.pdf"

    render_combined_briefing(flight, findings, [], output)

    page_text = " ".join(fitz.open(output)[4].get_text().split())
    assert "APPLICABLE NOTICES · 17 held, 3 shown" in page_text
    assert "APPLICABLE NOTICES · 35 held, 3 shown" in page_text
    for notice_id, source_page in (
        ("SX120/25", 16),
        ("SX97/26", 18),
        ("SX98/26", 16),
        ("1B3881/26", 22),
        ("1B2938/26", 22),
        ("1B4113/26", 22),
    ):
        assert notice_id in page_text
        assert f"SOURCE CFP p{source_page}" in page_text
    assert "FIRST ·" not in page_text


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
    assert COMBINED_BRIEFING_SCHEMA_VERSION == "2026-08-24-boss-flow-v22"
    assert combined_briefing_cache_token(123, 7) != combined_briefing_cache_token(
        123,
        7,
        schema_version="2026-08-23-boss-flow-v11",
    )


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


@pytest.mark.parametrize(
    ("airport", "runway", "approach", "distance_nm", "minutes", "fuel_kg"),
    [
        ("WMKK", "14L", "LOCDME", 287, 55, 4_680),
        ("WSAP", "20", "CAT1DME", 90, 21, 2_036),
    ],
)
def test_operational_page1_keeps_the_complete_alternate_fuel_above_summary_cards(
    tmp_path,
    airport,
    runway,
    approach,
    distance_nm,
    minutes,
    fuel_kg,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["fuel_summary"]["rows"]["altn_fuel"] = {
        "time_minutes": minutes,
        "fuel_kg": fuel_kg,
    }
    flight["alternates"] = [{
        "airport": airport,
        "runway": runway,
        "approach": approach,
        "distance_nm": distance_nm,
    }]
    flight["weather"].append({
        "location": flight["departure"],
        "record_type": "TAF",
        "text": " ".join(["FT 160800 1609/1715 09012KT 9999 SCT020"] * 10),
        "source_page": 21,
    })
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / f"alternate-fuel-{airport}.pdf"

    render_combined_briefing(flight, findings, [], out)

    page = fitz.open(out)[0]
    expected = f"{distance_nm} NM · {minutes // 60:02d}:{minutes % 60:02d} · {fuel_kg:,} kg"
    assert expected in " ".join(page.get_text().split())
    fuel_rect = page.search_for(f"{fuel_kg:,} kg")[0]
    lower_summary_top = page.rect.height - (30.0 + 132.0)
    assert fuel_rect.y1 <= lower_summary_top - 2.0


def test_no_deferred_page_never_invents_a_missing_source_or_remedy(rendered):
    page = rendered[3]
    text = " ".join(page.get_text().split())
    assert "STATUS CLEAR" in text
    assert "NO DEFERRED DECLARATION PRINTED" in text
    assert "No governed remedy link applies" in text
    assert "CFP DECLARATION" not in text
    assert "source is not mounted" not in text
    assert "GOVERNED LINK UNAVAILABLE" not in text
    assert not [
        link
        for link in page.get_links()
        if "governed-deferred-reference" in str(link.get("uri") or "")
    ]


def test_operational_terrain_seventh_row_stays_above_manual_review_panel(rendered):
    page = rendered[7]
    matal = next(rect for rect in page.search_for("MATAL") if rect.x0 < 100)
    review = min(page.search_for("MANUAL REVIEW REQUIRED"), key=lambda rect: rect.y0)
    assert matal.y1 + 2.0 <= review.y0


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

    operational_out = tmp_path / "grouped-deferred-operational.pdf"
    render_combined_briefing(flight, findings, [], operational_out)
    operational_pages = fitz.open(operational_out)
    assert "2 CFP declaration(s)" in operational_pages[0].get_text()
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


def test_deferred_crop_starts_on_the_matched_declaration_not_prior_half_line(
    tmp_path,
):
    source = tmp_path / "deferred-source.pdf"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((50, 100), "PREVIOUS DECLARATION LAST LINE", fontsize=10)
        page.insert_text((50, 112), "AA IFEDDL", fontsize=10)
        page.insert_text((50, 124), "SEAT IFE AUDIO JACK", fontsize=10)
        page.insert_text((50, 148), "BB CDDL", fontsize=10)
        document.save(source)

    crop = crop_source_region(
        str(source),
        needle="AA IFEDDL",
        end_needle="BB CDDL",
        source_pages=[1],
        pad_y=0,
        full_width=True,
    )

    assert crop is not None
    assert crop["png"].startswith(b"\x89PNG\r\n\x1a\n")
    clip_y0 = crop["clip_bbox"][1]
    matched_y0 = crop["matched_bbox"][1]
    with fitz.open(source) as document:
        previous_y1 = document[0].search_for(
            "PREVIOUS DECLARATION LAST LINE"
        )[0].y1
    assert clip_y0 >= matched_y0
    assert clip_y0 >= previous_y1
    assert clip_y0 < crop["matched_bbox"][3]


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


def test_boss_flow_operational_blocks_hold_the_8_4pt_readability_floor(rendered):
    def undersized_spans(page, *, top: float):
        undersized = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "").strip()
                    y0 = float(span.get("bbox", (0, 0, 0, 0))[1])
                    if (
                        text
                        and top <= y0 < page.rect.height - 30.0
                        and float(span.get("size") or 0.0) < 8.39
                    ):
                        undersized.append((text, span.get("size"), y0))
        return undersized

    # Page 1 is entirely operational after its navigation strip. Scan the
    # whole physical body, including airport facts, route/map labels and the
    # arrival-time basis; selected-card assertions previously missed these.
    assert not undersized_spans(rendered[0], top=90.0)
    assert not undersized_spans(rendered[1], top=90.0)
    assert not undersized_spans(rendered[5], top=90.0)


def test_boss_flow_pages_have_no_physical_text_overlap(rendered):
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    physical = scan_physical_pdf(Path(rendered.name))
    assert physical["valid"], physical["violations"]
    for page_number in (2, 3, 6):
        assert physical["pages"][page_number - 1]["visible_overlap_count"] == 0


def test_dense_page1_preserves_a_long_source_taf_at_the_readability_floor(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    long_taf = (
        "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB "
        "FM220100 19013G19KT P6SM VCSH BKN025 OVC040 FM220400 "
        "20013KT P6SM BKN025 BKN250 FM221200 24014KT P6SM BKN025 "
        "OVC040 TEMPO 2212/2214 SCT025 FM221400 24014KT P6SM SCT025 "
        "BKN060 FM221900 23012KT P6SM BKN060 PROB30 2219/2223 4SM "
        "-TSRA BKN040CB FM230100 31011KT P6SM SCT060"
    )
    flight["weather"].append({
        "location": flight["destination"],
        "record_type": "TAF",
        "text": long_taf,
        "source_page": 21,
    })
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "dense-page1-taf.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    first_page = document[0]
    extracted = " ".join(first_page.get_text().split())
    assert "FT 212321 2200/2306" in extracted
    assert "FM230100 31011KT P6SM SCT060" in extracted
    undersized = [
        (str(span.get("text") or "").strip(), span.get("size"))
        for block in first_page.get_text("dict").get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
        and 90 <= float(span.get("bbox", (0, 0, 0, 0))[1])
        < first_page.rect.height - 30
        and float(span.get("size") or 0.0) < 8.39
    ]
    assert not undersized

    from scripts.run_private_cfp_corpus import scan_physical_pdf

    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][0]["visible_overlap_count"] == 0


@pytest.mark.parametrize(
    "dense_stations",
    [("departure",), ("departure", "destination")],
)
def test_dense_page1_preserves_departure_and_dual_station_tafs(
    tmp_path,
    dense_stations,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    long_taf = (
        "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB "
        "FM220100 19013G19KT P6SM VCSH BKN025 OVC040 FM220400 "
        "20013KT P6SM BKN025 BKN250 FM221200 24014KT P6SM BKN025 "
        "OVC040 TEMPO 2212/2214 SCT025 FM221400 24014KT P6SM SCT025 "
        "BKN060 FM221900 23012KT P6SM BKN060 PROB30 2219/2223 4SM "
        "-TSRA BKN040CB FM230100 31011KT P6SM SCT060"
    )
    for station_role in dense_stations:
        flight["weather"].append({
            "location": flight[station_role],
            "record_type": "TAF",
            "text": long_taf,
            "source_page": 21,
        })
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / f"dense-page1-{'-'.join(dense_stations)}.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    first_page = document[0]
    extracted = " ".join(first_page.get_text().split())
    assert extracted.count("FT 212321 2200/2306") == len(dense_stations)
    assert extracted.count("FM230100 31011KT P6SM SCT060") == len(dense_stations)
    undersized = [
        (str(span.get("text") or "").strip(), span.get("size"))
        for block in first_page.get_text("dict").get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
        and 90 <= float(span.get("bbox", (0, 0, 0, 0))[1])
        < first_page.rect.height - 30
        and float(span.get("size") or 0.0) < 8.39
    ]
    assert not undersized

    from scripts.run_private_cfp_corpus import scan_physical_pdf

    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][0]["visible_overlap_count"] == 0


def test_page1_wraps_long_edto_alternate_display_without_elision(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["edto"]["airports"][0].update({
        "airport": "PGUM",
        "runway": "24R",
        "approach": "CIRC VORDME@06L",
        "minima": "1035FT/4316M",
    })
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "wrapped-edto-alternate.pdf"

    render_combined_briefing(flight, findings, [], out)

    first_page = " ".join(fitz.open(out)[0].get_text().split())
    assert "PGUM RWY24R CIRC VORDME@06L 1035FT/4316M | TOP-UP 0 KG" in first_page


def test_operational_overview_uses_true_edto_top_up_and_dashboard_receipt(
    tmp_path,
):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["fuel_summary"]["rows"]["edto_top_up"] = {
        "time_minutes": 1,
        "fuel_kg": 71,
    }
    flight["edto"]["sectors"] = [
        {
            "number": 1,
            "entry_actm_minutes": 559,
            "exit_actm_minutes": 590,
            "entry": {"name": "ENTRY1", "actm_minutes": 559},
            "exit": {"name": "EXIT1", "actm_minutes": 590},
            "etps": [],
        },
        {
            "number": 2,
            "entry_actm_minutes": 620,
            "exit_actm_minutes": 650,
            "entry": {"name": "ENTRY2", "actm_minutes": 620},
            "exit": {"name": "EXIT2", "actm_minutes": 650},
            "etps": [],
        },
    ]
    flight["edto"]["airports"].append({
        "airport": "RJCC",
        "runway": "19R",
        "approach": "CAT3B",
        "minima": "220FT/950M",
        "period": "22 JUL 1157Z - 22 JUL 1706Z",
    })
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "positive-edto-top-up.pdf"

    render_combined_briefing(flight, findings, [], out)

    first_page = " ".join(fitz.open(out)[0].get_text().split())
    assert "TOP-UP 71 KG" in first_page
    assert "TOP-UP 0 KG" not in first_page
    assert "2 SECTORS / 2 ALTN | FULL EDTO: DASHBOARD" in first_page


def test_operational_overview_long_route_points_to_dashboard(tmp_path):
    flight = sample_flight()
    flight["route_text"] = " ".join(
        ["WSSS/20C"] + [f"FIX{index:02d} A{index:03d}" for index in range(1, 25)] + ["KJFK/22L"]
    )
    flight["planned_level_profile"] = "/".join(
        ["SIN"] + [f"FIX{index:02d}/3{index:02d}" for index in range(1, 14)]
    )
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "long-route-dashboard-pointer.pdf"

    render_combined_briefing(flight, findings, [], out)

    first_page = " ".join(fitz.open(out)[0].get_text().split())
    assert "FULL ROUTE: DASHBOARD" in first_page
    assert "FULL: DASHBOARD" in first_page
    assert "AIRPORTS PAGE" not in first_page


def test_operational_overview_chips_wrap_before_the_route_map(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["route_identifier"] = "RTE99"
    flight["plan_number"] = "11"
    flight["edto_rvsm"] = "EDTO / RVSM"
    flight["cost_index"] = 999
    flight["apd_percent"] = 100
    flight["fuel_summary"]["cruise_wind_component_kt"] = 111
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "wrapped-overview-chips.pdf"

    render_combined_briefing(flight, findings, [], out)

    page = fitz.open(out)[0]
    spans = [
        span
        for block in page.get_text("dict").get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
    ]
    labels = {"RTE99 P11", "EDTO / RVSM", "CI 999", "APD 100%", "CRZ P111"}
    chips = [span for span in spans if str(span.get("text") or "").strip() in labels]
    assert {str(span.get("text") or "").strip() for span in chips} == labels

    width, _ = PAGE_SIZE
    full_w = width - 2 * MARGIN
    departure_w = full_w * 0.20
    destination_w = full_w * 0.23
    centre_x = MARGIN + departure_w + 10
    centre_w = full_w - departure_w - destination_w - 20
    centre_inner_x = centre_x + 10
    text_w = centre_w * 0.69 - 11.0
    map_x = centre_inner_x + text_w + 14
    assert all(float(span["bbox"][2]) < map_x for span in chips)
    assert len({round(float(span["bbox"][1]), 1) for span in chips}) >= 2


@pytest.mark.parametrize(
    "eosid",
    [
        (
            "STRAIGHT OUT VIA EXTENDED RUNWAY CENTRELINE THEN TURN RIGHT "
            "AT THREE THOUSAND FEET"
        ),
        " ".join(["ROUTING"] * 100),
        "Z" * 300,
    ],
    ids=["boss-style-sentence", "hundred-word-route", "unbroken-token"],
)
def test_operational_performance_prints_candidates_and_known_inputs(
    tmp_path,
    eosid,
):
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    flight = sample_flight()
    flight["performance"] = {
        "runway": "07R",
        "runway_condition": "DRY",
        "thrust_setting": "FULL",
        "flap_setting": 2,
        "temperature_c": 32,
        "qnh_hpa": 1013,
        "wind": "050/03KT",
        "packs_on": True,
        "anti_ice_on": False,
        "eosid": eosid,
        "obstacle_rtow_kg": 256_906,
        "landing_rtow_kg": 252_000,
        "structural_rtow_kg": 280_000,
        "controlling_rtow_kg": 252_000,
        "maximum_fuel_available_kg": 90_000,
    }
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "performance-candidates.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    assert len(document) == 8
    performance_page = " ".join(document[2].get_text().split())
    assert "RTOW PERF · 256,906 kg" in performance_page
    assert "RTOW LAND · 252,000 kg" in performance_page
    assert "RTOW STRUCT · 280,000 kg" in performance_page
    assert "CFP RTOW · 252,000 kg" in performance_page
    assert "CONDITIONS" in performance_page
    assert "PACKS ON" in performance_page
    assert "ANTI-ICE OFF" in performance_page
    assert "EOSID" in performance_page
    if " " in eosid:
        assert " ".join(eosid.split()) in performance_page
    else:
        assert eosid in "".join(performance_page.split())
    assert "WIND 050/03KT" in performance_page
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][2]["visible_overlap_count"] == 0


def test_operational_performance_adds_lossless_eosid_continuation_page(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def long_destination_notams(
        flight,
        findings,
        warnings,
        timing_view=None,
        weather_charts=None,
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        destination = next(
            panel
            for panel in view["airport_operational_panels"]
            if "destination" in panel.get("role_keys", [])
        )
        destination["card_summary_lines"] = [
            {
                "kind": "notam",
                "notam_id": f"DEST{index}",
                "text": " ".join(["LONG APPLICABLE SOURCE DETAIL"] * 2),
            }
            for index in range(1, 4)
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        long_destination_notams,
    )
    flight = sample_flight()
    flight["deferred_items"] = []
    eosid = " ".join(f"ROUTE{index:04d}" for index in range(1_600))
    flight["performance"] = {
        "runway": "07R",
        "runway_condition": "DRY",
        "thrust_setting": "FULL",
        "flap_setting": 2,
        "temperature_c": 32,
        "qnh_hpa": 1013,
        "wind": "050/03KT",
        "packs_on": True,
        "anti_ice_on": False,
        "eosid": eosid,
        "obstacle_rtow_kg": 256_906,
        "landing_rtow_kg": 252_000,
        "structural_rtow_kg": 280_000,
        "controlling_rtow_kg": 252_000,
        "maximum_fuel_available_kg": 90_000,
    }
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    out = tmp_path / "performance-eosid-continuation.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    continuation_count = sum(
        bool(
            re.search(
                r"LOSSLESS CONTINUATION\s+\d+/\d+",
                page.get_text(),
                re.IGNORECASE,
            )
        )
        for page in document[3:]
    )
    assert continuation_count >= 2
    assert len(document) == 8 + continuation_count
    mel_page_number = 4 + continuation_count
    airports_page_number = 5 + continuation_count
    overview_text = " ".join(document[0].get_text().split())
    assert f"Exact evidence on page {mel_page_number}" in overview_text
    assert f"Full matrix on page {airports_page_number}" in overview_text
    assert f"OPEN P{airports_page_number}" in overview_text
    assert (
        f"EOSID lossless continuation: {continuation_count} pages start p4"
        in document[2].get_text()
    )
    continuation_text = " ".join(
        text
        for page in document[3 : 3 + continuation_count]
        for text in page.get_text().split()
    )
    assert "EOSID / ESCAPE ROUTING" in continuation_text
    expected_tokens = eosid.split()
    cursor = 0
    for token in continuation_text.split():
        if token == expected_tokens[cursor]:
            cursor += 1
            if cursor == len(expected_tokens):
                break
    assert cursor == len(expected_tokens)
    assert "MEL/CDL AND CDDL" in document[mel_page_number - 1].get_text()
    assert "AIRPORTS / ALTERNATES" in document[airports_page_number - 1].get_text()
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    for page in physical["pages"][3 : 3 + continuation_count]:
        assert page["visible_overlap_count"] == 0


def test_decision_row_reallocates_width_for_one_dense_source_finding(
    tmp_path,
):
    from reportlab.pdfgen import canvas as reportlab_canvas

    flight = sample_flight()
    findings = [
        item
        for item in sample_findings()
        if item["engine"] != "depressurisation"
    ]
    briefing = build_briefing_view(flight, findings, [])
    decisions = [
        {
            "rank": index,
            "title": f"Synthetic decision {index}",
            "summary": "Short source-backed review item.",
            "severity": "warning",
            "engine": "analysis",
            "source_reference": "Shared briefing view",
            "target": "sec_enroute",
        }
        for index in range(1, 7)
    ]
    decisions[4].update({
        "engine": "deferred_dispatch_gate",
        "title": "Synthetic deferred dispatch gate",
        "summary": " ".join(
            ["REVIEW SOURCE CONTROLLED ITEM BEFORE EACH DEPARTURE"] * 9
        )
        + " FINAL-CONTROLLED-TAIL",
        "source_reference": (
            "Uploaded CFP deferred declaration · AA MEL 25-21-50A "
            "SYNTHETIC CONTROLLED SOURCE"
        ),
        "target": "sec_mel_cdl",
    })
    briefing["decision_findings"] = decisions
    out = tmp_path / "adaptive-decision-row.pdf"
    pdf = reportlab_canvas.Canvas(str(out), pagesize=(841.89, 595.28))
    for anchor in (
        "sec_overview",
        "sec_analysis",
        "sec_performance",
        "sec_airports",
        "sec_hazard",
        "sec_mel_cdl",
        "sec_enroute",
        "sec_terrain",
        "sec_time",
    ):
        pdf.bookmarkPage(anchor)
    draw_analysis_page(
        pdf,
        flight,
        briefing,
        findings,
        page_number=2,
        page_count=7,
    )
    pdf.showPage()
    pdf.save()

    page = fitz.open(out)[0]
    assert "FINAL-CONTROLLED-TAIL" in page.get_text()

    from scripts.run_private_cfp_corpus import scan_physical_pdf

    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][0]["visible_overlap_count"] == 0


def test_release_gate_separator_rules_do_not_cross_wrapped_text(rendered):
    page = rendered[6]
    gate_title = page.search_for("NUMBERED RELEASE GATES")[0]
    assurance_title = min(
        page.search_for("SOURCE ASSURANCE"),
        key=lambda rect: rect.y0,
    )
    first_gate = page.search_for("1. PERFORMANCE")[0]
    last_gate = page.search_for("5. COMMUNICATIONS")[0]
    body_spans = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                if gate_title.y1 < rect.y0 and rect.y1 < assurance_title.y0:
                    body_spans.append(rect)

    separators = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            start, end = item[1], item[2]
            if (
                abs(start.y - end.y) < 0.1
                and end.x - start.x > 500.0
                and first_gate.y1 < start.y < last_gate.y0
            ):
                separators.append(start.y)

    assert len(separators) == 4
    intersections = [
        (separator, rect)
        for separator in separators
        for rect in body_spans
        if rect.y0 <= separator <= rect.y1
    ]
    assert not intersections


def test_compact_capacity_reflows_long_deferred_and_release_gates(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def long_gate_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["deferred_dispatch_gates"] = [
            {
                "title": "TRASH COMPACTORS",
                "summary": (
                    "TRASH COMPACTOR ONE JAMMED; USE SPARE LINER. TRASH "
                    "COMPACTOR TWO INOPERATIVE; DO NOT LOAD. CABIN CREW MUST "
                    "CONFIRM ALTERNATE STOWAGE BEFORE RELEASE. "
                    "FINALDEFERREDTAIL"
                ),
                "source_segments": [],
            },
            {"title": "CDL 57-21", "summary": "Source review required."},
            {"title": "CDL 57-23 / 53-66", "summary": "Source review required."},
            {"title": "IN SIA/00-003 R9", "summary": "Source review required."},
        ]
        release_gates = list(view.get("release_gates") or [])
        assert len(release_gates) >= 2
        release_gates[1] = {
            **release_gates[1],
            "detail": (
                "NON-ESSENTIAL EQUIPMENT AND FURNISHINGS MAINT ENTRY LAVATORY "
                "LM46 NIL FLUSHING LAV LM46 BB EN A380EN-38-29161 MAINT "
                "ENTRY: REF EN A380EN-38-29161, DUE TO REPORTS OF WATER "
                "LEAKAGE INTO MAIN CABIN AND SUSPECTED DAMAGED U2R DRAIN "
                "TUBES, TO CARRY OUT TEMP SEALAGE OF FWD AND AFT FLOOR DRAIN "
                "PORTS ON U2R DOOR. TO INSPECT FWD AND AFT FLOOR DRAIN PORTS "
                "ON U2R DOOR FOR HST CONDITION AND WATER POOLING PRIOR TO "
                "EVERY DEPARTURE. TO REAPPLY HST IF NECESSARY AND CLEAN UP "
                "ANY WATER FINALRELEASETAIL"
            ),
        }
        view["release_gates"] = release_gates
        return view

    monkeypatch.setattr(briefing_module, "build_briefing_view", long_gate_view)
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "long-operational-gates.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    assert "FINALDEFERREDTAIL" in document[3].get_text()
    assert "FINALRELEASETAIL" in document[6].get_text()
    assert "COMPANY BULLETINS / INTAM" in document[6].get_text()
    for page_index in (3, 6):
        body_sizes = [
            float(span.get("size") or 0.0)
            for block in document[page_index].get_text("dict").get("blocks", [])
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if str(span.get("text") or "").strip()
            and 90.0 <= float(span.get("bbox", (0, 0, 0, 0))[1]) < 560.0
        ]
        assert min(body_sizes) >= 8.39
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][3]["visible_overlap_count"] == 0
    assert physical["pages"][6]["visible_overlap_count"] == 0


def test_compact_fir_and_terrain_receipts_are_whole_and_explicit():
    suffix = (
        ". Contact procedure/frequency unavailable; no lead or frequency "
        "is inferred."
    )
    fir_summary = " | ".join(
        f"F{index:03d} +{index:02d}:00 (CFP p{7 + index // 4})"
        for index in range(1, 27)
    ) + suffix
    compact_fir = _operational_fir_boundary_summary(
        fir_summary,
        text_width=200.0,
        max_lines=9,
    )
    assert compact_fir.endswith(suffix)
    assert "Showing " in compact_fir
    assert "of 26 FIR boundary groups" in compact_fir
    assert "dashboard and lossless audit briefing" in compact_fir
    assert "F001 +01:00 (CFP p7)" in compact_fir
    assert "F026 +26:00" not in compact_fir

    terrain_summary = (
        "4 MSA >100* windows (ALPHA 111*, max 111* at ALPHA; BRAVO 117* "
        "to CHARLIE 136*, max 159* at DELTA; ECHO 114*, max 114* at ECHO; "
        "FOXTROT 126* to GOLF 124*, max 166* at HOTEL); 0/4 terrain "
        "windows have validated profile matches - manual review required "
        "for 4 unmatched terrain windows"
    )
    terrain = {
        "summary": terrain_summary,
        "events": [
            {
                "maximum": {
                    "name": name,
                    "msa_hundreds_ft": value,
                }
            }
            for name, value in (
                ("ALPHA", 111),
                ("DELTA", 159),
                ("ECHO", 114),
                ("HOTEL", 166),
            )
        ],
    }
    compact_terrain = _operational_terrain_summary(
        terrain,
        has_terrain_annex=True,
        text_width=155.0,
        max_lines=9,
    )
    assert "4 MSA >100* window(s)" in compact_terrain
    assert "maximum 166* at HOTEL" in compact_terrain
    assert "manual review required for 4 unmatched terrain windows" in compact_terrain
    assert "Full governed terrain/profile evidence follows this page" in compact_terrain
    assert terrain["summary"] == terrain_summary


def test_enroute_card_compacts_route_and_long_fir_receipts_without_hiding_sources(
    tmp_path,
):
    from reportlab.pdfgen import canvas as reportlab_canvas
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    fir_suffix = (
        ". Contact procedure/frequency unavailable; no lead or frequency "
        "is inferred."
    )
    fir_summary = " | ".join(
        f"F{index:03d} +{index:02d}:00 (CFP p{7 + index // 4})"
        for index in range(1, 32)
    ) + fir_suffix
    route_airspace = {
        "record_count": 16,
        "source_page_text": "CFP pp75-98",
        "military_source_record": {"notam_id": "1A2118/26"},
        "card_summary": (
            "ROUTE AIRSPACE · REVIEW · 16 source notice(s) · CFP pp75-98. "
            "Military-training record 1A2118/26 is source-held. Route/level "
            "applicability and any ATC-clearance effect are not inferred; full "
            "held records remain in the dashboard."
        ),
    }
    briefing = {
        "communications": [],
        "fir_boundary_summary": fir_summary,
        "route_airspace": route_airspace,
        "intam": {
            "record_count": 21,
            "source_pages": list(range(39, 46)),
            "review_queue": [
                {
                    "source_page": 39 + index,
                    "category": f"CATEGORY-{index}",
                    "identity": f"HELD-{index}",
                    "headline": (
                        "Source-held bulletin headline requiring governed review "
                        f"number {index}"
                    ),
                }
                for index in range(1, 9)
            ],
        },
        "terrain": {
            "summary": (
                "No MSA >100* event is present in the shared route/profile "
                "analysis; this is not a terrain-clearance finding."
            ),
            "events": [],
        },
        "release_gates": [
            {
                "label": f"GATE-{index}",
                "status": "OPEN",
                "detail": (
                    " ".join(
                        ["SOURCE-HELD CONTROLLED STATUS REVIEW REQUIRED"] * 12
                    )
                    if index == 2
                    else " ".join(
                        ["Source-held release evidence requires review"] * 4
                    )
                ),
            }
            for index in range(1, 6)
        ],
        "source_assurance": [
            {
                "source": f"SOURCE-{index}",
                "status": "HELD",
                "detail": f"Bounded source receipt {index}.",
            }
            for index in range(1, 8)
        ],
    }
    out = tmp_path / "long-route-airspace-fir.pdf"
    pdf = reportlab_canvas.Canvas(str(out), pagesize=(841.89, 595.28))
    pdf.bookmarkPage("sec_overview")

    draw_operational_enroute_assurance_page(
        pdf,
        sample_flight(),
        briefing,
        page_number=7,
        page_count=7,
        has_terrain_annex=False,
    )
    pdf.showPage()
    pdf.save()

    page = fitz.open(out)[0]
    text = " ".join(page.get_text().split())
    assert "16 route-airspace notice(s) held - CFP pp75-98" in text
    assert "Military-training 1A2118/26 held" in text
    assert "Showing " in text
    assert "of 31 FIR boundary groups" in text
    assert "F001 +01:00 (CFP p7)" in text
    assert "F031 +31:00" not in text
    assert "full boundary rows remain in dashboard and lossless audit briefing" in text
    assert "Contact procedure/frequency unavailable" in text
    assert "HELD - 21 records - CFP pp39-45" in text
    assert "REVIEW QUEUE - NOT RELEVANCE-SELECTED" in text
    assert "HELD-1" in text
    assert "HELD-8" not in text
    assert "held review-queue examples from 21 source records" in text
    assert "full held records remain in dashboard and lossless audit briefing" in text
    assurance_receipt = re.search(
        r"Showing ([1-6]) of 7 source-assurance rows",
        text,
    )
    assert assurance_receipt
    assert "SOURCE-1 · HELD" in text
    assert "SOURCE-7 · HELD" not in text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][0]["visible_overlap_count"] == 0


def test_enroute_page_prints_complete_source_ledger_when_all_rows_fit(tmp_path):
    from reportlab.pdfgen import canvas as reportlab_canvas

    briefing = {
        "communications": [],
        "fir_boundary_summary": "",
        "route_airspace": {"record_count": 0},
        "intam": {"record_count": 0, "source_pages": [], "review_queue": []},
        "terrain": {"summary": "No strict MSA >100* window detected", "events": []},
        "release_gates": [{"label": "STATUS", "status": "REVIEW", "detail": "Confirm the held release status."}],
        "source_assurance": [
            {"source": "UPLOADED CFP", "status": "HELD", "detail": "test.pdf"},
            {"source": "CFP WEATHER", "status": "HELD", "detail": "3 source records."},
        ],
    }
    out = tmp_path / "complete-source-ledger.pdf"
    pdf = reportlab_canvas.Canvas(str(out), pagesize=(841.89, 595.28))
    pdf.bookmarkPage("sec_overview")
    draw_operational_enroute_assurance_page(
        pdf,
        sample_flight(),
        briefing,
        page_number=7,
        page_count=7,
        has_terrain_annex=False,
    )
    pdf.showPage()
    pdf.save()

    text = " ".join(fitz.open(out)[0].get_text().split())
    assert "SOURCE LEDGER · COMPLETE" in text
    assert "All 2 source-assurance rows shown" in text
    assert "UPLOADED CFP · HELD" in text
    assert "CFP WEATHER · HELD" in text


def test_enroute_page_refuses_silent_release_gate_overflow(tmp_path):
    from reportlab.pdfgen import canvas as reportlab_canvas

    briefing = {
        "communications": [],
        "fir_boundary_summary": "",
        "route_airspace": {"record_count": 0},
        "intam": {"record_count": 0, "source_pages": [], "review_queue": []},
        "terrain": {"summary": "No strict MSA >100* window detected", "events": []},
        "release_gates": [
            {"label": f"GATE-{index}", "status": "REVIEW", "detail": "Review required."}
            for index in range(6)
        ],
        "source_assurance": [],
    }
    pdf = reportlab_canvas.Canvas(str(tmp_path / "too-many-gates.pdf"), pagesize=(841.89, 595.28))
    pdf.bookmarkPage("sec_overview")
    with pytest.raises(ValueError, match="more than five release gates"):
        draw_operational_enroute_assurance_page(
            pdf,
            sample_flight(),
            briefing,
            page_number=7,
            page_count=7,
            has_terrain_annex=False,
        )


def test_lossless_hazard_plan_moves_sigmet_after_full_named_advisories():
    cards = [
        {"name": f"TEST SIGMET {index}", "_screen_lines": ["ONE", "TWO"]}
        for index in (1, 2)
    ]
    advisories = [{
        "name": f"VOLCANO {index}",
        "derived": " ".join(["LONG SOURCE-DERIVED ADVISORY RECEIPT"] * 8),
    } for index in (1, 2)]

    plans = _hazard_page_plans([cards], [advisories], [[]], [])

    planned_names = [
        card["name"]
        for plan in plans
        for card in plan["sigmet_cards"]
    ]
    assert planned_names == ["TEST SIGMET 1", "TEST SIGMET 2"]
    assert len(plans[0]["sigmet_cards"]) == 1
    assert len(plans) == 2


def test_compact_baseline_is_seven_pages_without_real_terrain_evidence(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["depressurisation_profile_charts"] = []
    for waypoint in flight.get("route_waypoints") or []:
        if waypoint.get("msa_hundreds_ft") is not None:
            waypoint["msa_hundreds_ft"] = min(
                int(waypoint["msa_hundreds_ft"]),
                100,
            )
    findings = [
        item
        for item in sample_findings()
        if item["engine"] not in {"terrain", "vws", "depressurisation"}
    ]
    out = tmp_path / "seven-page-no-terrain.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    assert len(document) == 7
    assert [row[1] for row in document.get_toc()][-1] == "Enroute / Assurance"
    assert "No strict MSA >100* window detected" in document[6].get_text()


def test_weather_page_uses_readable_source_status_cards_not_tiny_crops(rendered):
    weather = rendered[5].get_text()
    assert "CFP WEATHER SOURCE" in weather
    assert "WEATHER-CHART SOURCE STATUS" in weather
    assert "UNAVAILABLE - weather-chart detection did not establish appendix presence" in weather
    assert "absence is not inferred" in weather
    assert "WAFC ROUTE CHART - SOURCE CONTEXT" not in weather


def test_operational_weather_page_names_the_governed_selected_chart(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from app.odss import weather_charts as weather_charts_module

    real_build = briefing_module.build_briefing_view
    chart_bytes = b"governed-operational-chart"

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
            "reason": "Governed route-context chart selected inside the CFP flight window.",
            "selected_charts": [{
                "page_number": 1,
                "label": "SIGWX · FL250-FL600 · valid 2026-08-19T12:00:00+00:00",
                "display_label": "SIGWX · FL250-FL600 · VALID 19 AUG 1200Z",
                "valid_time_utc": "2026-08-19T12:00:00+00:00",
                "valid_time_display": "19 AUG 1200Z",
                "kind": "sigwx_high_level",
                "image_sha256": hashlib.sha256(chart_bytes).hexdigest(),
            }],
            "raw_chart_count": 1,
            "held_pages": [1],
        }
        return view

    monkeypatch.setattr(briefing_module, "build_briefing_view", selected_chart_view)
    monkeypatch.setattr(
        weather_charts_module,
        "extract_chart_image",
        lambda source, page_number: chart_bytes,
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
    out = tmp_path / "selected-operational-chart.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        out,
        source_pdf_path=str(source),
        weather_charts={"charts": []},
    )

    document = fitz.open(out)
    weather = document[5]
    text = " ".join(weather.get_text().split())
    assert "SELECTED · SIGWX · FL250-FL600 · VALID 19 AUG 1200Z" in text
    assert "T12:00:00" not in text
    assert "+00:00" not in text
    assert "Full selected chart: dashboard" in text
    for word in weather.get_text("words"):
        assert 0 <= word[0] <= word[2] <= weather.rect.width
        assert 0 <= word[1] <= word[3] <= weather.rect.height


def test_operational_weather_page_keeps_first_two_shared_sigmet_dispositions(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module

    real_build = briefing_module.build_briefing_view

    def two_sigmet_view(
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
                "name": "YMMM SIGMET P02 - SEV TURB",
                "disposition": "NOT PROMOTED",
                "screening": "Outside the governed route window.",
            },
            {
                "name": "YMMM SIGMET Q01 - SEV TURB",
                "disposition": "PROMOTED",
                "screening": "Intersects the governed route window.",
            },
        ]
        view["vaa"]["cfp_advisories"] = [
            {
                "name": f"TEST VOLCANO {index}",
                "derived": "Source-held CFP notice; crew review required.",
                "text": "SHORT SOURCE TEXT",
                "source_page": 20 + index,
            }
            for index in (1, 2)
        ]
        return view

    monkeypatch.setattr(briefing_module, "build_briefing_view", two_sigmet_view)
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "two-operational-sigmets.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    weather = " ".join(document[5].get_text().split())
    assert "YMMM SIGMET P02 - SEV TURB DISPOSITION · NOT PROMOTED" in weather
    assert "YMMM SIGMET Q01 - SEV TURB DISPOSITION · PROMOTED" in weather


def test_weather_vaac_assurance_keeps_full_five_centre_receipt(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view
    responsible_line = (
        "Responsible for this route: ANCHORAGE, DARWIN, MONTREAL, TOKYO, "
        "WASHINGTON - NOT reached: ANCHORAGE, DARWIN, MONTREAL, TOKYO, "
        "WASHINGTON (review gap); boundary segments need review"
    )

    def five_centre_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        hazards = dict(view.get("hazards") or {})
        hazards["coverage_ledger"] = [
            {"label": label, "status": "unavailable"}
            for label in ("AIRMET", "TC SIGMET", "VA SIGMET")
        ]
        vaac_reach = dict(hazards.get("vaac_reach") or {})
        vaac_reach["responsible_line"] = responsible_line
        hazards["vaac_reach"] = vaac_reach
        view["hazards"] = hazards
        return view

    monkeypatch.setattr(briefing_module, "build_briefing_view", five_centre_view)
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "five-centre-vaac-receipt.pdf"

    render_combined_briefing(flight, findings, [], out)

    document = fitz.open(out)
    weather_page = document[5]
    weather_text = " ".join(weather_page.get_text().split())
    assert responsible_line in weather_text
    top_card_sizes = [
        float(span.get("size") or 0.0)
        for block in weather_page.get_text("dict").get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
        and 100.0 <= float(span.get("bbox", (0, 0, 0, 0))[1]) < 220.0
    ]
    assert min(top_card_sizes) >= 8.39
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][5]["visible_overlap_count"] == 0


def test_source_held_charts_intam_and_fir_clocks_reach_compact_pages(tmp_path):
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    flight["route_waypoints"] = [
        waypoint
        for waypoint in flight.get("route_waypoints") or []
        if not waypoint.get("fir_boundary")
    ] + [
        {
            "name": f"-{fir}",
            "fir_boundary": fir,
            "actm_minutes": actm,
            "source_page": source_page,
            "latitude": None,
            "longitude": None,
            "msa_hundreds_ft": None,
            "msa_asterisk": False,
            "vws": None,
            "airway_in": None,
        }
        for fir, actm, source_page in (
            ("WIIF", 3, 7),
            ("WSJC", 14, 7),
            ("WSJC", 56, 7),
            ("RPHI", 121, 8),
        )
    ]
    flight["intam_records"] = [
        {
            "priority": 1,
            "category": "OPS",
            "identity": f"BULLETIN-{index:02d}",
            "date_token": "260821",
            "header": f"1.OPS BULLETIN-{index:02d} 260821",
            "headline": f"HELD COMPANY BULLETIN {index:02d}",
            "source_page": 39 + min(6, index // 3),
        }
        for index in range(21)
    ]
    manifest = {
        "status": "held",
        "charts": [
            {
                "chart_number": index,
                "page_number": 45 + index,
                "kind": "unclassified",
                "classification_status": "unclassified",
                "verified": False,
                "image_sha256": f"{index:064x}",
                "source": "uploaded_package",
            }
            for index in range(1, 13)
        ],
    }
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "source-held-compact.pdf"

    render_combined_briefing(
        flight,
        findings,
        [],
        out,
        weather_charts=manifest,
    )

    document = fitz.open(out)
    weather = document[5].get_text()
    enroute = document[6].get_text()
    assert "HELD - 12 raster chart page(s) - CFP pp46-57" in weather
    assert "Route relevance/classification review required" in weather
    assert "No weather-chart appendix detected" not in weather
    normalized_enroute = " ".join(enroute.split())
    for boundary in ("WIIF +00:03", "WSJC +00:14/+00:56", "RPHI +02:01"):
        assert boundary in normalized_enroute
    assert "contact procedure/frequency unavailable" in normalized_enroute.lower()
    assert "HELD - 21 records - CFP pp39-45" in enroute
    assert "NOT RELEVANCE-SELECTED" in " ".join(enroute.split())
    assert "COMPANY BULLETINS / INTAM · HELD" in enroute


def test_decision_bookkeeping_and_deferred_cards_use_truthful_targets():
    from app.odss.briefing import _decision_finding_projection

    projected = _decision_finding_projection([
        {
            "engine": "deferred_declaration",
            "severity": "unknown",
            "title": "AA IFEDDL",
            "summary": "Source declaration held.",
            "data": {"source_page": 1},
        },
        {
            "engine": "page1",
            "severity": "information",
            "title": "CFP Page 1 organised control summary",
            "summary": "Uploaded source summary.",
            "data": {"source_page": 1},
        },
    ])

    assert {item["engine"]: item["target"] for item in projected} == {
        "deferred_declaration": "sec_mel_cdl",
        "page1": "sec_overview",
    }


def test_material_open_gates_displace_bookkeeping_on_decision_page():
    from app.odss.briefing import (
        _decision_finding_projection,
        _release_gate_projection,
    )

    findings = [
        {
            "engine": "notam",
            "severity": "critical",
            "title": "Departure NOTAM SX98/26",
            "summary": "RWY 02R/20L is not available for civil use.",
            "data": {
                "role": "departure",
                "location": "WSSS",
                "notam_id": "SX98/26",
                "raw_text": "RWY 02R/20L IS NOT AVBL FOR CIVIL USE",
            },
        },
        {
            "engine": "notam",
            "severity": "critical",
            "title": "Destination NOTAM 1B3881/26",
            "summary": "ILS RWY 24 unavailable during the destination window.",
            "data": {
                "role": "destination",
                "location": "RPLL",
                "notam_id": "1B3881/26",
                "source_page": 22,
            },
        },
        {
            "engine": "weather",
            "severity": "warning",
            "title": "Departure weather - WSSS",
            "summary": "Benign terminal forecast held.",
            "data": {"location": "WSSS", "phase": "Departure"},
        },
        {
            "engine": "weather",
            "severity": "warning",
            "title": "Destination alternate weather - RCKH",
            "summary": "Rain and low cloud overlap the alternate window.",
            "data": {
                "location": "RCKH",
                "phase": "Destination alternate",
                "mechanism": "RAIN / SHOWERS; LOW CLOUD / CEILING",
            },
        },
        {
            "engine": "deferred_declaration",
            "severity": "unknown",
            "title": "AA IFEDDL",
            "summary": "Source declaration held.",
            "data": {},
        },
        {
            "engine": "communications",
            "severity": "unknown",
            "title": "FIR communication review required",
            "summary": "Current procedure unavailable.",
            "data": {},
        },
        {
            "engine": "page1",
            "severity": "information",
            "title": "CFP Page 1 organised control summary",
            "summary": "Uploaded source summary.",
            "data": {},
        },
    ]
    airport_panels = [
        {
            "icao": "WSSS",
            "role_keys": ["departure"],
            "operational_rows": [{"runway": "20C"}],
            "card_summary_lines": [
                {
                    "kind": "notam",
                    "notam_id": "SX98/26",
                    "different_runway": True,
                }
            ],
        },
        {
            "icao": "RPLL",
            "role_keys": ["destination"],
            "operational_rows": [{"runway": "24"}],
            "card_summary_lines": [
                {
                    "kind": "notam",
                    "label": "1B3881/26",
                    "notam_id": "1B3881/26",
                    "text": "ILS RWY 24 unavailable.",
                    "source_page": 22,
                    "signal_family": "approach_navaid",
                },
                {
                    "kind": "notam",
                    "label": "1B2938/26",
                    "notam_id": "1B2938/26",
                    "text": "RWY 06/24 strip grading applies.",
                    "source_page": 22,
                    "signal_family": "runway_restriction",
                },
                {
                    "kind": "notam",
                    "label": "1B4113/26",
                    "notam_id": "1B4113/26",
                    "text": "TWY F1B closed due WIP.",
                    "source_page": 22,
                    "signal_family": "taxiway",
                },
            ],
            "selected_notams": [
                {
                    "notam_id": "1B3774/26",
                    "item_e_text": (
                        "RPA GA APN PRKG BAY NR 71 DUE WIP; "
                        "CRANE WITH BOOM HGT APRX 36FT"
                    ),
                    "valid_from_utc": "2026-07-27T10:48:00+00:00",
                    "valid_to_utc": "2026-08-31T23:59:00+00:00",
                    "window_start_utc": "2026-08-21T02:45:00+00:00",
                    "window_end_utc": "2026-08-21T06:45:00+00:00",
                    "source_page": 23,
                },
                {
                    "notam_id": "1B4243/26",
                    "item_e_text": (
                        "RPA T1 PRKG BAY NR 21 DUE WIP; "
                        "CRANE WITH BOOM HGT APRX 43FT"
                    ),
                    "valid_from_utc": "2026-08-21T04:00:00+00:00",
                    "valid_to_utc": "2026-08-21T07:00:00+00:00",
                    "window_start_utc": "2026-08-21T02:45:00+00:00",
                    "window_end_utc": "2026-08-21T06:45:00+00:00",
                    "source_page": 22,
                },
            ],
        },
        {
            "icao": "RCKH",
            "role_keys": ["alternate"],
            "weather": {
                "metar": {
                    "text": "SA 201900 10005KT 060V130 9999 -RA FEW010 BKN018",
                    "source_page": 14,
                },
                "taf": {
                    "text": (
                        "FT 201700 2018/2124 06005KT 7000 FEW010 BKN032 "
                        "TEMPO 2018/2024 11007KT 4000 SHRA"
                    ),
                    "source_page": 14,
                },
            },
        },
    ]
    projected = _decision_finding_projection(
        findings,
        performance_rows=[{
            "label": "PERFORMANCE MAX FUEL / TANKS",
            "status": "OPEN",
            "detail": "Printed maximum fuel is below fuel in tanks.",
            "source_reference": "Uploaded CFP performance inputs",
        }],
        deferred_gates=[{
            "title": "IN SIA/00-017 R1",
            "category": "operational-restriction",
            "status": "dispatch-confirmation-required",
            "summary": (
                "ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS "
                "LOOSE; CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE"
            ),
            "source_segments": [{"source_declaration": "DD IN SIA/00-017 R1"}],
        }],
        airport_panels=airport_panels,
        coverage_rows=[
            {"label": "AIRMET", "status": "unavailable"},
            {"label": "TC SIGMET", "status": "unavailable"},
            {"label": "VA SIGMET", "status": "unavailable"},
        ],
    )

    assert len(projected) == 6
    assert [item["engine"] for item in projected] == [
        "notam",
        "performance_reconciliation",
        "weather_coverage",
        "arrival_ground",
        "deferred_dispatch_gate",
        "alternate_weather",
    ]
    by_engine = {item["engine"]: item for item in projected}
    assert by_engine["performance_reconciliation"]["target"] == "sec_performance"
    assert "PERFORMANCE MAX FUEL / TANKS" in by_engine[
        "performance_reconciliation"
    ]["title"]
    assert by_engine["deferred_dispatch_gate"]["target"] == "sec_mel_cdl"
    assert "IN SIA/00-017 R1" in by_engine["deferred_dispatch_gate"]["title"]
    assert "ENG 2 FAN COWLS LATCH" in by_engine[
        "deferred_dispatch_gate"
    ]["summary"]
    assert by_engine["weather_coverage"]["target"] == "sec_hazard"
    assert "gap is not a NIL" in by_engine["weather_coverage"]["summary"]
    assert by_engine["arrival_ground"]["target"] == "sec_airports"
    assert "1B2938/26" in by_engine["arrival_ground"]["summary"]
    assert "1B4113/26" in by_engine["arrival_ground"]["summary"]
    assert "1B4243/26" in by_engine["arrival_ground"]["summary"]
    assert "Bay 21" in by_engine["arrival_ground"]["summary"]
    assert "43 ft" in by_engine["arrival_ground"]["summary"]
    assert "Bay 71" not in by_engine["arrival_ground"]["summary"]
    assert by_engine["alternate_weather"]["target"] == "sec_hazard"
    assert "RCKH" in by_engine["alternate_weather"]["title"]
    assert "10005KT 060V130 9999 -RA" in by_engine["alternate_weather"]["summary"]
    assert "06005KT 7000" in by_engine["alternate_weather"]["summary"]
    assert "11007KT 4000 SHRA" in by_engine["alternate_weather"]["summary"]
    assert "source only; applicability not re-inferred" in by_engine[
        "alternate_weather"
    ]["summary"]
    assert by_engine["alternate_weather"]["source_reference"] == (
        "Uploaded company CFP · p14 · Airport weather list"
    )
    assert not any("SX98/26" in item["title"] for item in projected)
    assert "page1" not in by_engine
    assert not any(item["title"] == "AA IFEDDL" for item in projected)

    release_gates = _release_gate_projection(
        projected,
        performance_rows=[{
            "label": "PERFORMANCE MAX FUEL / TANKS",
            "status": "OPEN",
            "detail": "Printed maximum fuel is below fuel in tanks.",
        }],
        deferred_gates=[
            {"summary": "TRASH COMPACTOR 212 NO POWER"},
            {
                "summary": (
                    "ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS "
                    "LOOSE; CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE"
                ),
                "overview_summary": "ENG 2 LATCH · CHECK EACH DEPARTURE",
            },
        ],
        coverage_ledger=[
            {"label": "AIRMET", "status": "unavailable"},
            {"label": "TC SIGMET", "status": "unavailable"},
            {"label": "VA SIGMET", "status": "unavailable"},
        ],
        communications=[],
    )
    release_by_label = {gate["label"]: gate for gate in release_gates}
    assert "ENG 2 FAN COWLS LATCH" in release_by_label["STATUS"]["detail"]
    assert "TRASH COMPACTOR" not in release_by_label["STATUS"]["detail"]
    assert "1B3881/26" in release_by_label["AIRPORTS"]["detail"]
    assert "ILS RWY 24 unavailable" in release_by_label["AIRPORTS"]["detail"]
    assert "RPLL arrival ground constraints" in release_by_label["AIRPORTS"]["detail"]
    assert "SX120" not in release_by_label["AIRPORTS"]["detail"]
    assert "source-coverage gap is not a NIL" in release_by_label["WEATHER"]["detail"]


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
        "Destination NOTAM SX120/25": 4,
        "Destination Alternate NOTAM 1A1772/26": 4,
        "Departure NOTAM 1A2469/26": 4,
        "WEATHER COVERAGE INCOMPLETE": 5,
        "Early ATC/FIR action before OAKX": 6,
        "High-MSA event 1": 7,
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
    # The compact flow keeps the EDTO classification and top-up on overview;
    # it does not manufacture a separate legacy EDTO page.
    first = rendered[0].get_text()
    assert "EDTO" in first
    assert "NON-EDTO" not in first
    assert "TOP-UP 0 KG" in first
    text = "\n".join(page.get_text() for page in rendered)
    assert "EDTO / ENROUTE AIRPORTS" not in text
    assert "CFP EDTO TABLE" not in text
    assert "ENROUTE / ASSURANCE" in rendered[6].get_text()


def test_compact_edto_route_context_stays_on_overview(rendered):
    first = rendered[0].get_text()
    assert "EDTO" in first
    assert "ENTRY1" in first


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


def test_standard_cfp_keeps_one_non_edto_label_without_legacy_page(tmp_path, monkeypatch):
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
    page5 = document[4].get_text()
    toc = [row[1] for row in document.get_toc()]

    assert "SUMMARY EDTO CFP" not in text
    assert text.count("NON-EDTO") == 1
    assert "DESTINATION ALTERNATE ASSESSMENT MATRIX" in page5
    assert "PREFERRED · WSAP" in page5
    for retired in (
        "EDTO / ENROUTE AIRPORTS",
        "EDTO BOUNDARY / STATUS",
        "CFP EDTO TABLE",
        "ENTRY ACTM",
        "EXIT ACTM",
        "EDTO TOP-UP",
        "EDTO ALTERNATE SECTOR",
    ):
        assert retired not in text
    assert toc[1] == "Decision Analysis"
    assert toc[4] == "Airports / Alternates"
    assert "EDTO / Enroute Airports" not in toc
    assert classification_panels == []


def test_explicit_non_edto_cfp_keeps_its_page_one_classification(tmp_path):
    flight = sample_flight()
    explicit_page1 = SQ23_PAGE1.replace(
        "SUMMARY EDTO CFP",
        "SUMMARY NON EDTO CFP",
    )
    flight["edto_rvsm"] = None
    flight["fuel_summary"] = parse_page1_fuel_summary(explicit_page1)
    flight["edto"] = {
        "assessment": {"status": "verified_not_applicable", "evidence": []},
        "sectors": [],
        "airports": [],
    }
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "explicit-non-edto.pdf"

    render_combined_briefing(flight, findings, [], out)

    text = "\n".join(page.get_text() for page in fitz.open(out))
    assert text.count("NON-EDTO") == 1
    assert "SUMMARY EDTO CFP" not in text


def test_airport_identity_places_iata_beside_icao(rendered):
    first = rendered[0].get_text()
    assert "BRU / EBBR" in first
    assert "SIN / WSSS" in first


def test_compact_airport_matrix_excludes_edto_and_fuel_enroute_roles(
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
    airport_page = document[4].get_text()
    for station in ("EBBR", "WSSS", "WSAP"):
        assert station in airport_page
    for excluded_role_station in ("VTBD", "WIII"):
        assert excluded_role_station not in airport_page
    for index in range(1, 7):
        assert f"FE{index}/26" not in airport_page
        assert f"EXACT WIII ITEM E {index}" not in airport_page


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
        "scheduled_arrival_utc": "2026-08-01T13:00:00+00:00",
        "actual_takeoff_utc": "2026-08-01T10:05:00+00:00",
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
        "flight_identity": {"actual_takeoff_hhmm": "1005Z"},
        "overview": {"destination": {"icao": "BBBB"}},
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
    assert entries[-1]["time"] == "1305Z"


def test_route_timeline_does_not_publish_an_enroute_point_as_arrival():
    flight = {
        "scheduled_departure_utc": "2026-08-01T10:00:00+00:00",
        "scheduled_arrival_utc": "2026-08-01T13:00:00+00:00",
        "actual_takeoff_utc": "2026-08-01T10:05:00+00:00",
        "departure": "AAAA",
        "destination": "BBBB",
        "route_waypoints": [
            {"name": "AAAA", "actm_minutes": 0},
            {"name": "TOD", "actm_minutes": 155},
        ],
    }
    briefing = {
        "flight_identity": {
            "actual_takeoff_hhmm": "1005Z",
            "eta_hhmm": "--",
            "eta_status": "unavailable",
        },
        "overview": {"destination": {"icao": "BBBB"}},
        "hazards": {"sigmet_cards": []},
        "terrain": {"events": []},
    }

    entries = _route_anchor_entries(flight, briefing)

    assert entries[-1]["label"] == "BBBB"
    assert entries[-1]["time"] == "--"
    assert entries[-1]["actm"] is None
    assert all(entry["label"] != "TOD" for entry in entries)


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
        # The immutable audit profile deliberately keeps only its historical
        # two compact station-summary rows.  High-cardinality losslessness is
        # proven from the full selected records, which are the actual source
        # consumed by the continuation planner.
        panel["selected_notams"] = [
            {
                "notam_id": f"STATION-SOURCE-{index:02d}",
                "pertinence_kind": "other",
                "pertinence_rank": index,
                "severity": "warning",
                "summary": (
                    f"STATION-SOURCE-{index:02d} BEGIN "
                    + "complete operational wording remains visible " * 8
                    + f" END-{index:02d}"
                ),
                "item_e_text": (
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


def test_operational_vaa_cards_print_shared_applicability_before_source_excerpt(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view

    def four_advisory_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        view["vaa"]["cfp_advisories"] = [
            {
                "name": f"CFP VOLCANO ADVISORY · TESTVOLCANO-{index}",
                "volcano": f"TESTVOLCANO-{index}",
                "notam_id": f"1A900{index}/26",
                "valid_from": f"20 AUG 01{index}0Z",
                "valid_to": "21 AUG 0100Z",
                "derived": (
                    f"Source-held CFP notice {index}; operational applicability "
                    "remains a crew/dispatch review."
                ),
                "text": (
                    f"SOURCE-START-{index} "
                    + "complete source advisory wording " * 18
                    + f"SOURCE-END-{index}"
                ),
                "source_page": 40 + index,
            }
            for index in range(1, 5)
        ]
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        four_advisory_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "operational-vaa-applicability.pdf"

    render_combined_briefing(flight, findings, [], out)

    page = fitz.open(out)[5]
    text = " ".join(page.get_text().split())
    for index in range(1, 5):
        title = f"TESTVOLCANO-{index} · 1A900{index}/26"
        applicability = (
            f"Source-held CFP notice {index}; operational applicability remains "
            "a crew/dispatch review."
        )
        assert title in text
        assert applicability in text
        assert f"SOURCE p{40 + index}" in text
        assert f"20 AUG 01{index}0Z" in text
        assert "21 AUG 0100Z" in text
        assert f"SOURCE-START-{index}" in text
        title_position = text.index(title)
        applicability_position = text.index(applicability, title_position)
        source_position = text.index("SOURCE TEXT ·", applicability_position)
        assert title_position < applicability_position < source_position
    assert "SOURCE-END-1" not in text
    assert "CONTINUED · FULL SOURCE IN DASHBOARD" in text
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][5]["visible_overlap_count"] == 0


def test_operational_vaa_cards_keep_full_va_sigmet_name_beside_cfp_notices(
    tmp_path,
    monkeypatch,
):
    from app.odss import briefing as briefing_module
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    real_build = briefing_module.build_briefing_view
    full_sigmet_name = "VOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 18"

    def mixed_advisory_view(
        flight, findings, warnings, timing_view=None, weather_charts=None
    ):
        view = real_build(
            flight,
            findings,
            warnings,
            timing_view=timing_view,
            weather_charts=weather_charts,
        )
        notices = [
            {
                "name": (
                    f"CFP VOLCANO ADVISORY · TESTVOLCANO-{index} · "
                    f"1A910{index}/26"
                ),
                "advisory_kind": "CFP_VAA_NOTICE",
                "volcano": f"TESTVOLCANO-{index}",
                "notam_id": f"1A910{index}/26",
                "valid_from": f"20 AUG 01{index}0Z",
                "valid_to": "21 AUG 0100Z",
                "derived": (
                    "Source-held CFP notice; operational applicability remains "
                    "a crew/dispatch review."
                ),
                "text": f"SOURCE CFP NOTICE {index} REQUIRES REVIEW.",
                "source_page": 40 + index,
            }
            for index in range(1, 4)
        ]
        notices.append({
            "name": full_sigmet_name,
            "advisory_kind": "VA_SIGMET",
            "valid_from": "20 AUG 0200Z",
            "valid_to": "20 AUG 0800Z",
            "derived": (
                "VA SIGMET source-held; route applicability remains a "
                "crew/dispatch review."
            ),
            "text": "SOURCE VA SIGMET ASH CLOUD POSITION AND FORECAST HELD.",
            "source_page": 44,
        })
        view["vaa"]["cfp_advisories"] = notices
        return view

    monkeypatch.setattr(
        briefing_module,
        "build_briefing_view",
        mixed_advisory_view,
    )
    flight = sample_flight()
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ23_PAGE1)
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    out = tmp_path / "operational-mixed-vaa.pdf"

    render_combined_briefing(flight, findings, [], out)

    page = fitz.open(out)[5]
    text = " ".join(page.get_text().split())
    assert full_sigmet_name in text
    assert "VA SIGMET source-held; route applicability remains a crew/dispatch review." in text
    for index in range(1, 4):
        assert f"TESTVOLCANO-{index} · 1A910{index}/26" in text
        assert (
            f"CFP VOLCANO ADVISORY · TESTVOLCANO-{index} · 1A910{index}/26"
            not in text
        )
    physical = scan_physical_pdf(out)
    assert physical["valid"], physical["violations"]
    assert physical["pages"][5]["visible_overlap_count"] == 0


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
    performance = " ".join(document[2].get_text().split())
    assert "280,000" in overview
    assert "+80,000" in overview
    assert "SELECTED RTOW · 280,000 kg" in performance
    assert "Selected RTOW 280,000 kg minus PTOW 200,000 kg equals +80,000 kg." in performance
    assert "SELECTED RTOW · 290,000 kg" not in performance


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

    performance = " ".join(fitz.open(out)[2].get_text().split())
    assert "A complete RTOW/PTOW pair is unavailable in the parsed CFP." in performance
    assert "STATUS · MANUAL REVIEW REQUIRED" in performance
    assert "kg gives" not in performance


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

    hazard = " ".join(fitz.open(out)[5].get_text().split())
    assert hazard.count("ENROUTE SIGMET") == 1
    assert hazard.count(
        "No enroute SIGMET record is printed in this CFP weather package."
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


def test_audit_rev3_v8_projection_isolates_operational_only_records():
    flight = sample_flight()
    briefing = {
        "communications": [
            {"record_kind": "fir_boundary_source", "event": "NEW FIR"},
            {"record_kind": "procedure", "event": "LEGACY CONTACT"},
        ],
        "vaa": {
            "cfp_advisories": [
                {"advisory_kind": "CFP_VAA_NOTICE", "name": "NEW VAA"},
                {"record_type": "VA_SIGMET", "name": "LEGACY SIGMET"},
            ],
        },
        "fuel_summary": {
            "rows": {"fuel_in_tanks": {"fuel_kg": 1000}},
            "derived_fuel_kg": {"taxi_to_landing": 900},
        },
        "airport_operational_panels": [
            {
                "role_key": "destination",
                "role_keys": ["destination"],
                "operational_rows": [{"runway": "20R"}],
                "card_summary_lines": [
                    {"kind": "weather", "label": "METAR", "text": "HELD"},
                    {"kind": "notam", "label": "NEW-1", "text": "NEW"},
                    {"kind": "notam", "label": "NEW-2", "text": "NEW"},
                    {"kind": "notam", "label": "NEW-3", "text": "NEW"},
                ],
                "selected_notams": [
                    {
                        "notam_id": "SX120/25",
                        "item_e_text": "RWY 02L/20R CLSD",
                        "summary": "Planned runway closure review.",
                        "pertinence_kind": "runway_closure",
                        "pertinence_rank": 1,
                        "severity": "critical",
                    },
                    {
                        "notam_id": "SX98/26",
                        "item_e_text": "RWY 02R/20L NOT AVBL",
                        "summary": "Other runway unavailable.",
                        "pertinence_kind": "runway_closure",
                        "pertinence_rank": 1,
                        "severity": "critical",
                    },
                    {
                        "notam_id": "SX97/26",
                        "item_e_text": "TWY S2 CLSD",
                        "summary": "Taxiway closed.",
                        "pertinence_kind": "taxiway_closure",
                        "pertinence_rank": 2,
                        "severity": "warning",
                    },
                ],
            },
        ],
    }

    projected = _audit_rev3_v8_briefing_projection(flight, briefing)

    assert [item["event"] for item in projected["communications"]] == [
        "LEGACY CONTACT"
    ]
    assert [item["name"] for item in projected["vaa"]["cfp_advisories"]] == [
        "LEGACY SIGMET"
    ]
    assert "derived_fuel_kg" not in projected["fuel_summary"]
    projected_notams = [
        line["label"]
        for line in projected["airport_operational_panels"][0][
            "card_summary_lines"
        ]
        if line["kind"] == "notam"
    ]
    assert projected_notams == ["SX120/25", "SX98/26"]
    assert len(briefing["communications"]) == 2
    assert "derived_fuel_kg" in briefing["fuel_summary"]
    assert len(briefing["airport_operational_panels"][0]["card_summary_lines"]) == 4


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
    performance = " ".join(document[2].get_text().split())
    assert "TANKER" in performance
    assert "RETURN SECTOR REQ" in performance
    assert "23,324" in performance


# --- 23 Aug 2026: page-1 PERFORMANCE card, pertinent NOTAMs, arrival basis ---


def test_page_one_carries_the_performance_card_in_place_of_flight_basis(rendered):
    # Boss, 21 Aug (R2-9): "add PERFORMANCE card to p1 (GPT layout)". The
    # flight-basis facts already live in the header, chips and footer.
    first = rendered[0].get_text()
    assert "\nPERFORMANCE\n" in first
    assert "CFP P1 - FLIGHT BASIS" not in first
    assert "RTOW unavailable" in first
    assert "PTOW 245,529 kg" in first
    assert "Margin unavailable" in first


def test_destination_card_states_the_arrival_basis(rendered):
    # Boss, 21 Aug (R2-14): "is it based on the flight time?... too small".
    first = rendered[0].get_text()
    assert "ETA 2159Z" in first
    assert "STD 0945Z -> STA 2240Z" in first
    assert "scheduled STA 2240Z" in first
    assert "filed EET" in first
    assert "ETA 2240Z" not in first


def test_decision_timeline_states_its_clock_basis(rendered):
    second = rendered[1].get_text()
    assert "0952Z" in second and "2159Z" in second
    assert "ATOT 0952Z + CFP ACTM drives clocks" in second
    assert "calculated ETA 2159Z from filed EET 12:07" in second
    assert "STD 0945Z / STA 2240Z (12:55)" in second
    assert "from STD 0945Z gives nominal 2240Z" not in second


def test_long_section_header_keeps_the_schedule_labels(rendered):
    terrain = " ".join(rendered[6].get_text().split())
    assert "UTC STD 0945Z -> STA 2240Z" in terrain


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
