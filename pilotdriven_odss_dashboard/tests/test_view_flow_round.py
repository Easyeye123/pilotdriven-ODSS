"""23 Aug 2026 flow round: view-composed facts every surface prints."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from generate_visual_samples import sample_findings, sample_flight

from app.odss.briefing import _arrival_basis_line, _performance_publication, build_briefing_view
from app.odss.parser import parse_page1_fuel_summary
from app.odss.timing import build_timing_view


SQ910_PAGE1 = (
    "PAGE  1 OF 11 SIA910 SIN/MNL 21AUG26\n"
    "              SINGAPORE AIRLINES - SUMMARY STANDARD CFP\n"
    "GND  MILES    1431  CRZ COMP M012   BURNOFF  03.21  019367\n"
    "AIR  MILES    1520                STAT CONT  00.10  000975\n"
    "ALTN CRK (RPLC)                   ALTN FUEL  00.21  001828\n"
    "                                  ALTN HOLD  00.30  002274\n"
    "                             DEST HOLD FUEL  00.00  000000\n"
    "                                EDTO TOP UP  00.00  000000\n"
    "                                  TAXI FUEL         000600\n"
    "PZFW 169700                  FLT PLAN REQMT  04.23  025044\n"
    "PTOW 212991                     EXCESS FUEL  03.16  018847\n"
    "PLWT 193624                   FUEL IN TANKS  07.38  043891\n"
)


def test_performance_publication_carries_the_cfp_inputs():
    flight = sample_flight()
    flight["performance"] = {
        "runway": "20C", "runway_condition": "DRY", "thrust_setting": "FULL", "flap_setting": 2,
        "temperature_c": 32, "qnh_hpa": None, "wind": "050/03KT", "packs_on": True, "anti_ice_on": False,
        "eosid": "STRAIGHT OUT", "landing_rtow_kg": 224367, "structural_rtow_kg": 250000,
        "maximum_fuel_available_kg": 36420,
    }
    flight["masses"]["planned_takeoff_weight_kg"] = 212991
    publication = _performance_publication(flight)
    assert publication["inputs"] == {
        "runway": "20C", "runway_condition": "DRY", "thrust_setting": "FULL", "flap_setting": 2,
        "temperature_c": 32, "qnh_hpa": None, "wind": "050/03KT", "packs_on": True, "anti_ice_on": False,
        "eosid": "STRAIGHT OUT", "maximum_fuel_available_kg": 36420,
    }
    assert publication["selected_candidate_keys"] == ["landing"]
    assert publication["margin_kg"] == 224367 - 212991


def test_arrival_basis_line_names_std_schedule_and_filed_eet():
    assert _arrival_basis_line("0050", "0445", "3:55", "03.21") == "STD 0050Z + SCHED 3:55 · filed EET 03:21"
    assert _arrival_basis_line("0050", "0445", None, "03.21") == "STD 0050Z · filed EET 03:21"
    assert _arrival_basis_line("", "", None, "--.--") == "Scheduled arrival per CFP page 1"


def test_actual_takeoff_drives_report_eta_without_erasing_the_schedule():
    flight = sample_flight()
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    timing = build_timing_view(
        flight,
        findings,
        "2026-07-16T09:52:00+00:00",
    )

    view = build_briefing_view(
        flight,
        findings,
        [],
        timing_view=timing,
    )
    identity = view["flight_identity"]

    assert identity["eta_hhmm"] == "2159"
    assert identity["scheduled_eta_hhmm"] == "2240"
    assert identity["arrival_basis"] == (
        "ATOT 0952Z + filed EET 12:07 · scheduled STA 2240Z"
    )
    assert identity["timeline_basis"] == (
        "ATOT 0952Z + CFP ACTM drives clocks; calculated ETA 2159Z from "
        "filed EET 12:07. Schedule: STD 0945Z / STA 2240Z (12:55)."
    )
    assert [
        view["overview"]["timeline"][0]["utc_display"],
        view["overview"]["timeline"][-1]["utc_display"],
    ] == ["0952Z", "2159Z"]


def test_actual_takeoff_does_not_invent_an_eta_without_destination_actm():
    flight = sample_flight()
    flight["route_waypoints"] = [
        {"name": flight["departure"], "actm_minutes": 0},
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    timing = build_timing_view(
        flight,
        findings,
        "2026-07-16T09:52:00+00:00",
    )

    view = build_briefing_view(
        flight,
        findings,
        [],
        timing_view=timing,
    )
    identity = view["flight_identity"]

    assert identity["eta_hhmm"] == "--"
    assert identity["eta_status"] == "unavailable"
    assert identity["scheduled_eta_hhmm"] == "2240"
    assert identity["arrival_basis"] == (
        "ATOT 0952Z held; destination ACTM unavailable · scheduled STA 2240Z"
    )
    assert view["metrics"]["eet"] == "--.--"
    assert view["overview"]["timeline"][0]["utc_display"] == "0952Z"
    assert view["overview"]["timeline"][-1]["utc_display"] == "--"


def test_actual_takeoff_does_not_treat_a_positive_enroute_actm_as_arrival():
    flight = sample_flight()
    flight["route_waypoints"] = [
        {"name": flight["departure"], "actm_minutes": 0},
        {"name": "TOD", "actm_minutes": 699},
    ]
    findings = [
        finding
        for finding in sample_findings()
        if finding["engine"] != "depressurisation"
    ]
    timing = build_timing_view(
        flight,
        findings,
        "2026-07-16T09:52:00+00:00",
    )

    view = build_briefing_view(
        flight,
        findings,
        [],
        timing_view=timing,
    )

    assert view["flight_identity"]["eta_hhmm"] == "--"
    assert view["flight_identity"]["eta_status"] == "unavailable"
    assert view["metrics"]["eet"] == "--.--"
    arrival = view["overview"]["timeline"][-1]
    assert arrival["kind"] == "arrival"
    assert arrival["detail"] == flight["destination"]
    assert arrival["actm_minutes"] is None
    assert arrival["utc_display"] == "--"


def test_overview_chips_carry_route_version_and_cruise_component():
    flight = sample_flight()
    flight["route_identifier"] = "SINMNL60"
    flight["plan_number"] = "3"
    flight["fuel_summary"] = parse_page1_fuel_summary(SQ910_PAGE1)
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    view = build_briefing_view(flight, findings, [])
    labels = [chip["label"] for chip in view["overview"]["chips"]]
    assert "SINMNL60 P3" in labels
    assert "CRZ M12" in labels
    assert "NON-EDTO" in labels
    identity = view["flight_identity"]
    assert identity["arrival_basis"].startswith("STD 0945Z")
    assert "filed EET" in identity["arrival_basis"]
    assert "Schedule: STD 0945Z / STA 2240Z (12:55)" in identity["timeline_basis"]
    assert "Filed EET 12:07" in identity["timeline_basis"]
    assert "gives nominal" not in identity["timeline_basis"]


def test_overview_chip_keeps_explicit_non_edto_and_edto_classifications():
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]

    non_edto = sample_flight()
    non_edto["edto_rvsm"] = None
    non_edto["fuel_summary"] = parse_page1_fuel_summary(SQ910_PAGE1)
    non_edto["fuel_summary"]["source_classification"] = "NON EDTO"
    non_edto["fuel_summary"]["classification"] = "NON EDTO"
    non_edto_labels = [
        chip["label"]
        for chip in build_briefing_view(non_edto, findings, [])["overview"]["chips"]
    ]
    assert "NON-EDTO" in non_edto_labels

    edto = sample_flight()
    edto["edto_rvsm"] = None
    edto["fuel_summary"] = {
        "source_classification": "EDTO",
        "classification": "EDTO",
    }
    edto_labels = [
        chip["label"]
        for chip in build_briefing_view(edto, findings, [])["overview"]["chips"]
    ]
    assert "EDTO" in edto_labels
