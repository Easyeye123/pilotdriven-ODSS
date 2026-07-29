from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import fitz
import pytest
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import analysis
from app.odss.briefing import (
    _display_registration,
    _pilot_route_map_label,
    build_route_map,
    render_route_svg,
)
from app.odss.pertinent_brief import CATEGORY_COLOURS
from app.odss.report_facts import (
    build_route_gate_rows,
    is_confirmed_profile_finding,
    profile_coverage_label,
    profile_findings_for_terrain_event,
    select_route_gate_rows,
)
from app.odss.engines import detect_terrain_events
from app.odss.operational_brief import _source_label
from app.odss.reporting import render_pdf, report_sections


def test_display_registration_formats_singapore_mark_without_changing_other_marks() -> None:
    assert _display_registration("9VSMQ") == "9V-SMQ"
    assert _display_registration("9V-SMQ") == "9V-SMQ"
    assert _display_registration("D-ABCD") == "D-ABCD"


def _notam(
    notam_id: str,
    role: str,
    severity: str = "warning",
    priority_score: int = 1,
    schedule: str | None = None,
) -> dict[str, Any]:
    details = []
    if schedule:
        details.append(f"Schedule: {schedule}.")
    details.extend([
        "Operating window 2026-07-11T09:30:00+00:00 to 2026-07-11T11:30:00+00:00.",
        f"Location WSSS; category {role}.",
        "Validity 2026-07-01T00:00:00+00:00 to 2026-07-31T23:59:00+00:00.",
    ])
    return {
        "engine": "notam",
        "severity": severity,
        "title": f"{role.title()} NOTAM {notam_id}",
        "summary": f"Operational finding for {role}.",
        "details": details,
        "data": {
            "role": role,
            "priority_score": priority_score,
            "schedule": schedule,
        },
    }


def _weather(index: int) -> dict[str, Any]:
    text = (
        "TAF WSSS 161100Z 1612/1718 18010KT 9999 FEW020 SCT040 "
        "TEMPO 1612/1618 4000 TSRA BKN015CB BECMG 1700/1702 22015G25KT "
    ) * 5
    return {
        "engine": "weather",
        "severity": "warning",
        "title": f"Weather record {index:02d}",
        "summary": text,
        "details": ["Record type: TAF."],
        "data": {},
    }


def _pertinent_weather() -> dict[str, Any]:
    return {
        "engine": "weather",
        "severity": "warning",
        "title": "EDTO weather - VTSP",
        "summary": (
            "EDTO; 25 JUL 1821Z-2039Z: Forecast weather overlapping this "
            "window: convection / thunderstorms. Applicable conditions: "
            "wind 280 degrees 8 kt; visibility 10 km or more; scattered "
            "2000 ft. Nearby observation: wind 260 degrees 11 kt at "
            "2026-07-25T16:30:00+00:00. Flight effect: Diversion-airport "
            "suitability during the checked period requires review."
        ),
        "details": [
            "Phase: EDTO.",
            "UTC window: 25 JUL 1821Z-2039Z.",
            "Applicable conditions: wind 280 degrees 8 kt.",
            "Timing: convection / thunderstorms overlaps 20:00Z-20:39Z.",
            "Nearby observation: wind 260 degrees 11 kt.",
            "Operational mechanism: convection / thunderstorms.",
            "Flight effect: Diversion-airport suitability requires review.",
        ],
        "data": {
            "phase": "EDTO",
            "location": "VTSP",
            "utc_window": "25 JUL 1821Z-2039Z",
            "mechanism": "convection / thunderstorms",
            "timing": "convection / thunderstorms overlaps 20:00Z-20:39Z.",
            "flight_effect": "Diversion-airport suitability requires review.",
            "applicable_conditions": "wind 280 degrees 8 kt",
            "observed_conditions": "wind 260 degrees 11 kt",
            "observation_time_utc": "2026-07-25T16:30:00+00:00",
            "window_status": "pertinent",
            "window_status_text": "Forecast weather overlaps this window.",
        },
    }


def _no_overlap_weather(
    *,
    location: str,
    phase: str,
    window: str,
) -> dict[str, Any]:
    return {
        "engine": "weather",
        "severity": "information",
        "title": f"{phase} weather - {location}",
        "summary": "No significant weather group overlaps this window.",
        "details": [],
        "data": {
            "phase": phase,
            "location": location,
            "utc_window": window,
            "mechanism": "None in time-overlapping forecast groups",
            "flight_effect": "No adverse flight effect was identified.",
            "window_status": "no_significant_overlap",
            "window_status_text": (
                "No significant weather group overlaps this window."
            ),
        },
    }


def _review_required_weather(
    *,
    location: str,
    phase: str,
    window: str,
) -> dict[str, Any]:
    return {
        "engine": "weather",
        "severity": "warning",
        "title": f"{phase} weather - {location}",
        "summary": "Forecast coverage is incomplete — review required.",
        "details": [],
        "data": {
            "phase": phase,
            "location": location,
            "utc_window": window,
            "mechanism": "None safely classified",
            "timing": f"The CFP TAF does not fully cover {window}.",
            "flight_effect": "Forecast coverage is incomplete.",
            "window_status": "review_required",
        },
    }


def _flight() -> dict[str, Any]:
    return {
        "flight_number": "SQ304",
        "departure": "WSSS",
        "destination": "EBBR",
        "departure_runway": "20C",
        "destination_runway": "07L",
        "flight_date": "11JUL26",
        "scheduled_departure_utc": "2026-07-11T10:30:00+00:00",
        "scheduled_arrival_utc": "2026-07-11T22:00:00+00:00",
        "aircraft_type": "A350-941",
        "registration": "9V-SMG",
        "ground_distance_nm": 5933,
        "planned_level_profile": "SIN/350/POINT/390/BRU/410",
        "route_waypoints": [
            {"name": "WSSS", "actm_minutes": 0, "latitude": 1.36, "longitude": 103.99, "fir_boundary": None, "airway_in": None, "msa_hundreds_ft": 4, "vws": 1},
            {"name": "-VOMF", "actm_minutes": 120, "latitude": 13.93, "longitude": 92.33, "fir_boundary": "VOMF", "airway_in": "L759", "msa_hundreds_ft": None, "vws": 2},
            {"name": "POINT", "actm_minutes": 360, "latitude": 31.40, "longitude": 69.00, "fir_boundary": None, "airway_in": "L750", "msa_hundreds_ft": 166, "vws": 5},
            {"name": "EBBR", "actm_minutes": 690, "latitude": 50.90, "longitude": 4.48, "fir_boundary": None, "airway_in": "DCT", "msa_hundreds_ft": 5, "vws": 2},
        ],
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_landing_weight_kg": 175802,
            "planned_takeoff_weight_kg": 245529,
        },
        "fuel": {
            "fuel_in_tanks_kg": 79643,
            "trip_fuel_kg": 69727,
            "planned_destination_fuel_kg": 9316,
        },
        "alternates": [{"airport": "EDDL", "runway": "05L", "approach": "CAT1DME"}],
        "edto": {"entry_actm_minutes": 120, "exit_actm_minutes": 150, "etp_actm_minutes": [135], "airports": []},
        "weather": [],
        "notams": [],
        "personal_notes": [],
    }


def test_route_gates_are_derived_from_generic_cfp_route_and_fail_closed() -> None:
    flight = _flight()
    flight["route_text"] = "WSSS DCT ALPHA NATB BRAVO DCT EBBR"
    flight["route_waypoints"] = [
        {
            "name": "WSSS",
            "actm_minutes": 0,
            "source_page": 7,
            "fir_boundary": None,
        },
        {
            "name": "ALPHA",
            "actm_minutes": 120,
            "source_page": 8,
            "fir_boundary": None,
        },
        {
            "name": "-TEST",
            "actm_minutes": 180,
            "source_page": 8,
            "fir_boundary": "TEST",
        },
        {
            "name": "BRAVO",
            "actm_minutes": 240,
            "source_page": 9,
            "fir_boundary": None,
        },
        {
            "name": "EBBR",
            "actm_minutes": 690,
            "source_page": 15,
            "fir_boundary": None,
        },
    ]

    rows = build_route_gate_rows(flight)
    selected = select_route_gate_rows(rows, limit=3)

    assert rows[0]["gate"] == "NAT B"
    assert rows[0]["basis"] == "ALPHA - BRAVO"
    assert "11 JUL 1230Z" in rows[0]["time"]
    assert any(item["gate"] == "TEST" for item in selected)
    assert selected[-1]["gate"] == "EBBR"
    assert all(
        item["status"] == "review_required"
        or item["kind"] == "arrival"
        for item in selected
    )
    assert all(
        "review required" not in item["result"].lower()
        for item in selected
    )


def test_profile_findings_join_by_terrain_event_not_list_position() -> None:
    events = detect_terrain_events(
        [
            {
                "name": "START",
                "actm_minutes": 0,
                "msa_hundreds_ft": 90,
            },
            {
                "name": "HIGH1",
                "actm_minutes": 10,
                "msa_hundreds_ft": 120,
                "msa_asterisk": True,
            },
            {
                "name": "MIDDLE",
                "actm_minutes": 20,
                "msa_hundreds_ft": 90,
            },
            {
                "name": "HIGH2",
                "actm_minutes": 30,
                "msa_hundreds_ft": 130,
                "msa_asterisk": True,
            },
            {
                "name": "END",
                "actm_minutes": 40,
                "msa_hundreds_ft": 90,
            },
        ]
    )
    findings = [
        {
            "engine": "depressurisation",
            "summary": "Manual chart-index review is required.",
            "data": {},
        },
        {
            "engine": "depressurisation",
            "summary": "Candidate chart for the second event.",
            "data": {
                "terrain_event_id": events[1]["terrain_event_id"],
                "start_actm_minutes": 30,
                "chart_number": "GEN-2",
            },
        },
        {
            "engine": "depressurisation",
            "summary": "Second chart for the same event.",
            "data": {
                "terrain_event_id": events[1]["terrain_event_id"],
                "start_actm_minutes": 30,
                "chart_number": "GEN-3",
            },
        },
    ]

    assert [
        item["summary"]
        for item in profile_findings_for_terrain_event(events[0], findings)
    ] == ["Manual chart-index review is required."]
    assert [
        item["data"]["chart_number"]
        for item in profile_findings_for_terrain_event(events[1], findings)
    ] == ["GEN-2", "GEN-3"]


def test_route_map_limits_routine_labels_on_dense_long_haul_routes() -> None:
    flight = _flight()
    flight["route_waypoints"] = [
        {
            "name": f"P{index:02d}",
            "actm_minutes": index * 20,
            "latitude": 1.0 + index,
            "longitude": 104.0 - index * 2.0,
            "fir_boundary": f"FIR{index:02d}" if index not in {0, 29} else None,
            "msa_hundreds_ft": None,
            "vws": None,
            "airway_in": "DCT",
        }
        for index in range(30)
    ]

    route_map = build_route_map(flight)

    assert route_map["available"] is True
    assert 0 in route_map["label_indices"]
    assert 29 in route_map["label_indices"]
    assert len(route_map["label_indices"]) <= 12

    svg = render_route_svg(route_map)
    assert 'fill="#153044"' in svg
    assert "Filed route from CFP coordinates" in svg


def test_level1_notams_preserve_critical_roles_schedule_and_omission_count() -> None:
    findings = [
        _notam(f"D{index:02d}/26", "departure", priority_score=30 - index)
        for index in range(12)
    ]
    findings.extend([
        _notam(
            "A1234/26",
            "destination",
            severity="critical",
            priority_score=100,
            schedule="DLY 0200-0400",
        ),
        _notam("A2000/26", "destination alternate", priority_score=20),
        _notam("A3000/26", "EDTO", priority_score=10),
    ])
    findings.extend([
        _notam(f"I{index:02d}/26", "informational", priority_score=index)
        for index in range(10)
    ])

    section = report_sections(findings, 1)[0]
    text = "\n".join(section["lines"])

    assert section["severity"] == "critical"
    assert "Destination NOTAM A1234/26" in text
    assert "- Schedule: DLY 0200-0400." in text
    assert "Departure NOTAM" in text
    assert "Destination Alternate NOTAM A2000/26" in text
    assert "Edto NOTAM A3000/26" in text
    assert (
        "9 duplicate or lower-priority applicable NOTAM record(s) retained in audit evidence."
        in text
    )


def test_level1_matches_three_page_landscape_review_brief(tmp_path: Path) -> None:
    path = tmp_path / "level_1.pdf"
    flight = _flight()
    for page_number, point in enumerate(flight["route_waypoints"], start=7):
        point["source_page"] = page_number
    findings = [
        _weather(1),
        _notam("A1000/26", "departure"),
        {
            "engine": "depressurisation",
            "severity": "unknown",
            "title": "High terrain detected but no profile matched",
            "summary": (
                "No controlled profile is confirmed; manual chart-index review "
                "is required."
            ),
            "details": [
                "The approved controlled profile index is not mounted."
            ],
            "data": {
                "reference_status": "controlled-source-not-mounted",
                "controlled_index_loaded": False,
            },
        },
        *[
            {
                "engine": "terrain",
                "severity": "warning",
                "title": f"High-MSA event {index}",
                "summary": "Review terrain escape planning.",
                "details": [],
                "data": {},
            }
            for index in range(1, 9)
        ],
    ]
    render_pdf(flight, findings, [], 1, path)

    reader = PdfReader(path)
    assert len(reader.pages) == 3
    first = reader.pages[0].extract_text() or ""
    second = reader.pages[1].extract_text() or ""
    third = reader.pages[2].extract_text() or ""

    assert "PILOT" in first and "DRIVEN" in first
    assert "REVIEW REQUIRED" not in first
    assert "BRIEFING COMPLETE" not in first
    assert "Decision support only" not in first
    assert "Decision support only" not in second
    assert "Decision support only" not in third
    assert float(reader.pages[0].mediabox.width) > float(reader.pages[0].mediabox.height)
    assert "LEVEL 1 - PERTINENT BRIEF" in first
    assert "PERFORMANCE" in first
    assert "EXCESS FUEL" in first
    assert "EDTO" in first
    assert "OCEANIC" in first
    assert "HIGH TERRAIN" in first
    assert "DEPARTURE - WSSS" in first
    assert "DESTINATION - EBBR" in first
    assert "DECISION GATES" in first
    assert "APPLICABLE NOTAMS WITHIN STD / STA ±2 HOURS" in first
    assert "Filed route from CFP coordinates" in first
    assert "SQ304 - OPERATIONAL TIMING" in second
    assert "FLIGHT PHASE WINDOWS" in second
    assert "EDTO 1 | ENTRY 02.00 | EXIT 02.30" in second
    assert "MEL / CDL / CDDL" not in second
    assert "PERFORMANCE / FUEL" not in second
    assert "WEATHER / PERTINENT NOTAM" not in second
    assert "ROUTE GATE" in second
    assert "TAKEOFF WEIGHT" in second
    assert "DATA COVERAGE" in second
    assert "SQ304 - HIGH TERRAIN EXPOSURE" in third
    assert "Geographic route strip - validated CFP MSA points only" in third
    assert "FIR / COMMUNICATIONS" not in third
    assert "ACTUAL EXPOSURE" in third
    assert "PROFILE / COVERAGE" in third
    assert "BOUNDARY LOGIC" in third
    assert "PROFILE COVERAGE" in third
    assert "PROFILE FINDINGS" not in third
    assert "approved controlled profile index is not mounted" in third
    assert third.count(
        "No controlled profile is confirmed; manual chart-index review is required."
    ) == 0
    assert third.count("No exact profile confirmed - review required") >= 1
    assert third.lower().count("manual chart-index review is required") == 1
    assert "ACTM / CALCULATED UTC" not in third
    assert "first validated CFP high-MSA trigger" in third
    assert "first subsequent point where that trigger clears" in third
    for page_number, page_text in enumerate((first, second, third), start=1):
        assert "A350-941 / 9V-SMG" in page_text
        assert f"PAGE {page_number} OF 3" in page_text
        assert f"Page {page_number} of 3" in page_text
    assert "representative gates" not in second
    assert "CFP p." not in second
    assert "CFP p." not in third
    assert "parsed" not in second.lower()
    assert "..." not in first
    assert "…" not in first
    assert sum(
        "Filed route from CFP coordinates" in (page.extract_text() or "")
        for page in reader.pages
    ) == 1


def test_confirmed_profile_is_prominent_in_l1_and_complete_in_l2(
    tmp_path: Path,
) -> None:
    flight = _flight()
    event = detect_terrain_events(flight["route_waypoints"])[0]
    finding = {
        "engine": "depressurisation",
        "severity": "warning",
        "title": "Profile 1 - VOMF to EBBR",
        "summary": "Proposed depressurisation chart GEN-1; critical point POINT.",
        "details": [],
        "data": {
            "chart_number": "GEN-1",
            "critical_point": "POINT",
            "terrain_event_id": event["terrain_event_id"],
            "start_actm_minutes": event["first_high"]["actm_minutes"],
            "route_start": "VOMF",
            "route_end": "EBBR",
            "coverage_complete": True,
            "reference_status": "controlled-index-loaded",
        },
    }

    assert is_confirmed_profile_finding(finding) is True
    for level, page_index, expected_pages in ((1, 2, 3), (2, 5, 7)):
        path = tmp_path / f"confirmed-profile-level-{level}.pdf"
        render_pdf(flight, [finding], [], level, path)
        reader = PdfReader(path)
        assert len(reader.pages) == expected_pages
        page = " ".join((reader.pages[page_index].extract_text() or "").split())
        assert "GEN-1 VOMF-EBBR / CP POINT" in page
        assert "UTC" in page
        if level == 2:
            assert "DUR" in page
            assert "330 min" in page


def test_partial_profile_is_never_presented_as_confirmed() -> None:
    finding = {
        "engine": "depressurisation",
        "summary": "Candidate profile",
        "data": {
            "chart_number": "GEN-2",
            "critical_point": "POINT",
            "route_start": "START",
            "route_end": "MID",
            "coverage_complete": False,
            "reference_status": "controlled-index-loaded",
        },
    }

    assert is_confirmed_profile_finding(finding) is False
    assert profile_coverage_label([finding]) == (
        "Incomplete coverage (GEN-2) - review required"
    )


def test_level1_weather_uses_pertinent_operational_lines_not_raw_repetition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_1_pertinent_weather.pdf"

    render_pdf(_flight(), [_pertinent_weather()], [], 1, path)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(path).pages
    )
    reader = PdfReader(path)
    page1 = reader.pages[0].extract_text() or ""
    page2 = reader.pages[1].extract_text() or ""
    page3 = reader.pages[2].extract_text() or ""
    assert "EDTO weather - VTSP" in text
    assert "EDTO weather - VTSP" in page1
    assert "EDTO weather - VTSP" not in page2
    assert "EDTO weather - VTSP" not in page3
    assert "EDTO | VTSP | 25 JUL 1821Z-2039Z" in page1
    assert "convection / thunderstorms" in page1
    assert "Diversion-airport suitability requires review." in page1
    assert "Applicable conditions:" not in text
    assert "Nearby observation:" not in text
    assert "2026-07-25T16:30:00+00:00" not in text


def test_level1_groups_repeated_incomplete_weather_without_hiding_review(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_1_grouped_incomplete_weather.pdf"
    findings = [
        _pertinent_weather(),
        _review_required_weather(
            location="CYQX",
            phase="EDTO",
            window="25 JUL 0526Z-0917Z",
        ),
        _review_required_weather(
            location="EINN",
            phase="EDTO",
            window="25 JUL 0649Z-0917Z",
        ),
        {
            "engine": "vaa",
            "severity": "unknown",
            "title": "Volcanic ash review required",
            "summary": "Coverage is incomplete.",
            "details": [],
            "data": {"status": "review_required"},
        },
        {
            "engine": "tropical_cyclone",
            "severity": "unknown",
            "title": "Tropical cyclone review required",
            "summary": "Coverage is incomplete.",
            "details": [],
            "data": {"status": "review_required"},
        },
    ]

    render_pdf(_flight(), findings, [], 1, path)

    reader = PdfReader(path)
    page1 = " ".join((reader.pages[0].extract_text() or "").split())
    page2 = " ".join((reader.pages[1].extract_text() or "").split())
    assert page1.count("Weather coverage incomplete") == 1
    assert "EDTO / CYQX / 25 JUL 0526Z-0917Z" in page1
    assert "EDTO / EINN / 25 JUL 0649Z-0917Z" in page1
    assert "VAA and tropical-cyclone review required" in page2
    assert "Forecast coverage is incomplete." not in f"{page1} {page2}"


def test_level2_matches_seven_page_operational_contract(tmp_path: Path) -> None:
    path = tmp_path / "level_2.pdf"
    render_pdf(_flight(), [_weather(index) for index in range(24)], [], 2, path)

    reader = PdfReader(path)
    assert len(reader.pages) == 7
    pages = [page.extract_text() or "" for page in reader.pages]
    first = pages[0]
    second = pages[1]

    assert "PILOTDRIVEN" in first
    assert "PZFW" in first and "166,486 kg" in first
    assert "ANALYSIS OVERVIEW" in first
    assert "PERFORMANCE, FUEL AND AIRPORT BASIS" in second
    assert "FLIGHT-WINDOW NOTAM APPLICABILITY" in pages[2]
    assert "EDTO SECTORS AND SUITABILITY INPUTS" in pages[3]
    assert "OCEANIC AND FIR COMMUNICATIONS" in pages[4]
    assert "PILOT USE" not in pages[4]
    assert "Crossing time parsed." not in pages[4]
    assert "HIGH-TERRAIN EXPOSURE AND PROFILE COVERAGE" in pages[5]
    assert "WEATHER, VAAC AND PROMOTION RESULT" in pages[6]
    assert "see the dedicated Level 2 section" not in pages[6]
    assert all(f"Page {index} of 7" in text for index, text in enumerate(pages, 1))


def test_level2_preserves_page_contract_when_sections_are_sparse(tmp_path: Path) -> None:
    path = tmp_path / "level_2_compact.pdf"
    findings = [
        _weather(1),
        _notam("A1000/26", "departure"),
        {
            "engine": "terrain",
            "severity": "warning",
            "title": "High-MSA event",
            "summary": "Review terrain escape planning.",
            "details": ["Maximum MSA 190 at ORT."],
            "data": {},
        },
    ]

    render_pdf(_flight(), findings, ["Source review required."], 2, path)

    reader = PdfReader(path)
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    assert len(reader.pages) == 7
    assert "FLIGHT-WINDOW NOTAM APPLICABILITY" in page_text[2]
    assert "HIGH-TERRAIN EXPOSURE AND PROFILE COVERAGE" in page_text[5]
    assert "WEATHER, VAAC AND PROMOTION RESULT" in page_text[6]
    assert "Coverage note:" not in page_text[6]


def test_level2_uses_readable_centered_rows_without_blank_table_filler(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_readability.pdf"
    findings = [
        _weather(1),
        _notam("A1000/26", "departure"),
        {
            "engine": "sigmet",
            "severity": "unknown",
            "title": "SIGMET review required",
            "summary": "Current official coverage requires review.",
            "details": [],
            "data": {"status": "review_required"},
        },
    ]

    render_pdf(
        _flight(),
        findings,
        ["Current official coverage requires review."],
        2,
        path,
    )

    document = fitz.open(path)

    def spans(page_number: int, needle: str) -> list[dict[str, Any]]:
        return [
            span
            for block in document[page_number].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if needle in span["text"]
        ]

    def blocks(page_number: int, needle: str) -> list[dict[str, Any]]:
        return [
            block
            for block in document[page_number].get_text("dict")["blocks"]
            if needle in " ".join(
                span["text"]
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )
        ]

    page_two_first = spans(1, "RUNWAY / SID")
    page_two_last = blocks(1, "SURFACE OVERLAY")
    page_seven_advisory = blocks(
        6,
        "SIGMET review required",
    )

    assert page_two_first and min(span["size"] for span in page_two_first) >= 9.9
    assert page_two_last and max(block["bbox"][1] for block in page_two_last) >= 430
    assert page_seven_advisory
    assert min(block["bbox"][1] for block in page_seven_advisory) >= 100


def test_level2_edto_weather_result_is_concise_and_readable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_edto_weather.pdf"
    flight = _flight()
    flight["edto"]["airports"] = [
        {
            "airport": "VTSP",
            "period": "25 JUL 1821Z-2039Z",
            "runway": "09",
            "approach": "CAT1DME",
            "minima": "450FT/1800M",
        },
        {
            "airport": "WMKK",
            "period": "25 JUL 1821Z-2039Z",
            "runway": "14L",
            "approach": "CAT1DME",
            "minima": "420FT/1500M",
        },
        {
            "airport": "VOMM",
            "period": "25 JUL 1821Z-2039Z",
            "runway": "25",
            "approach": "CAT1DME",
            "minima": "450FT/1800M",
        },
        {
            "airport": "WSSS",
            "period": "25 JUL 1821Z-2039Z",
            "runway": "20C",
            "approach": "CAT1DME",
            "minima": "420FT/1500M",
        },
    ]

    render_pdf(flight, [_pertinent_weather()], [], 2, path)

    page = fitz.open(path)[3]
    page_text = page.get_text()
    normalized_text = " ".join(page_text.split())
    assert "Convection / thunderstorms" in page_text
    assert "Suitability review required." in normalized_text
    assert "VTSP: Convection / thunderstorms" in normalized_text
    assert "current airport suitability" not in normalized_text
    assert "EDTO / VTSP / 25 JUL 1821Z-2039Z" not in page_text
    readable_result_spans = [
        span
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["size"] >= 8.9
    ]
    readable_result = " ".join(
        span["text"]
        for span in readable_result_spans
    )
    assert "Convection / thunderstorms" in readable_result
    assert "Suitability review required." in readable_result


def test_fixed_report_typography_stays_inside_page_without_text_overlap(
    tmp_path: Path,
) -> None:
    findings = [
        *[_weather(index) for index in range(12)],
        *[
            _notam(
                f"A{index:04d}/26",
                "departure" if index % 2 else "destination",
            )
            for index in range(1, 9)
        ],
    ]

    for level, expected_pages in ((1, 3), (2, 7)):
        path = tmp_path / f"level_{level}_typography_geometry.pdf"
        render_pdf(_flight(), findings, ["Source review required."], level, path)
        document = fitz.open(path)
        assert len(document) == expected_pages

        for page in document:
            lines: list[tuple[fitz.Rect, int, str]] = []
            for block_index, block in enumerate(page.get_text("dict")["blocks"]):
                for line in block.get("lines", []):
                    text = "".join(
                        span["text"]
                        for span in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue
                    bounds = fitz.Rect(line["bbox"])
                    assert page.rect.contains(bounds), text
                    lines.append((bounds, block_index, text))

            for index, (left, left_block, left_text) in enumerate(lines):
                for right, right_block, right_text in lines[index + 1:]:
                    if left_block == right_block:
                        continue
                    intersection = left & right
                    assert not (
                        intersection.width > 0.5
                        and intersection.height > 0.5
                    ), f"{left_text!r} overlaps {right_text!r}"


def test_level2_notam_table_uses_actual_window_and_pilot_facing_effect(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_notam_window.pdf"
    active = _notam("1A6475/26", "departure")
    active["data"].update({
        "location": "WSSS",
        "applicability": "active",
        "pertinence_kind": "runway_closure",
        "window_start_utc": "2026-07-11T09:30:00+00:00",
        "window_end_utc": "2026-07-11T11:30:00+00:00",
    })
    unresolved = _notam("A1001/26", "destination")
    unresolved["data"].update({
        "location": "EBBR",
        "applicability": "review",
        "window_start_utc": "2026-07-11T21:00:00+00:00",
        "window_end_utc": "2026-07-12T01:00:00+00:00",
    })

    render_pdf(_flight(), [active, unresolved], [], 2, path)

    page = PdfReader(path).pages[2].extract_text() or ""
    normalized = " ".join(page.split())
    assert "A6475/26" in normalized
    assert "1A6475/26" not in normalized
    assert "11 JUL 0930Z-1130Z" in normalized
    assert "11 JUL 2100Z-12 JUL 0100Z" in normalized
    assert "Runway availability affected." in normalized
    assert "Restriction unresolved - pilot review required." in normalized
    assert " active " not in f" {normalized.lower()} "


def test_reference_timed_notam_uses_validity_not_screening_window(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_reference_timed_notam.pdf"
    begins_after_etd = _notam("1A6475/26", "departure", severity="critical")
    begins_after_etd.update({
        "title": "Departure NOTAM 1A6475/26",
        "summary": (
            "Rwy 04L/22R closed or unavailable during the applicable "
            "departure window."
        ),
    })
    begins_after_etd["data"].update({
        "location": "KJFK",
        "notam_id": "1A6475/26",
        "pertinence_kind": "runway_closure",
        "applicability": "active",
        "valid_from_utc": "2026-07-25T03:00:00+00:00",
        "valid_to_utc": "2026-07-25T10:00:00+00:00",
        "window_start_utc": "2026-07-25T01:15:00+00:00",
        "window_end_utc": "2026-07-25T03:15:00+00:00",
        "stateAtReference": "begins_after_reference",
        "referenceAt": "2026-07-25T02:15:00+00:00",
        "minutesDelta": 45,
    })
    active_at_etd = _notam("1A4842/26", "departure", severity="critical")
    active_at_etd["data"].update({
        "location": "KJFK",
        "notam_id": "1A4842/26",
        "pertinence_kind": "approach_navaid_closure",
        "applicability": "active",
        "valid_from_utc": "2026-05-13T16:30:00+00:00",
        "valid_to_utc": "2026-08-31T23:59:00+00:00",
        "stateAtReference": "active_at_reference",
        "referenceAt": "2026-07-25T02:15:00+00:00",
        "minutesDelta": 0,
    })
    flight = _flight()
    flight.update({
        "flight_number": "SQ23",
        "departure": "KJFK",
        "destination": "WSSS",
        "flight_date": "25JUL26",
        "scheduled_departure_utc": "2026-07-25T02:15:00+00:00",
        "scheduled_arrival_utc": "2026-07-25T21:30:00+00:00",
    })

    render_pdf(flight, [begins_after_etd, active_at_etd], [], 2, path)

    page = " ".join(
        (PdfReader(path).pages[2].extract_text() or "").split()
    )
    assert "A6475/26" in page
    assert "1A6475/26" not in page
    assert "Rwy 04L/22R closed or unavailable." in page
    assert "25 JUL 0300Z-1000Z" in page
    assert "Begins 45 min after ETD; active 0300Z-1000Z." in page
    assert "Active at ETD." in page
    assert "25 JUL 0115Z-0315Z" not in page


def test_level1_normalizes_prefixed_notam_references_in_decision_gates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_1_normalized_notam_refs.pdf"
    findings = [
        _notam("1A4842/26", "departure", severity="critical", priority_score=30),
        _notam("1A4843/26", "departure", severity="critical", priority_score=29),
        _notam("1SX120/25", "destination", severity="critical", priority_score=28),
    ]

    render_pdf(_flight(), findings, [], 1, path)

    first = " ".join(
        (PdfReader(path).pages[0].extract_text() or "").split()
    )
    assert "A4842/26" in first
    assert "A4843/26" in first
    assert "SX120/25" in first
    assert "1A4842/26" not in first
    assert "1A4843/26" not in first
    assert "1SX120/25" not in first


def test_level2_notam_table_merges_duplicate_operational_conditions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_notam_deduplicated.pdf"
    first = _notam("A1000/26", "departure", priority_score=20)
    second = _notam("A1001/26", "departure", priority_score=19)
    for item in (first, second):
        item["data"].update({
            "location": "WSSS",
            "applicability": "active",
            "pertinence_kind": "approach_navaid_closure",
            "window_start_utc": "2026-07-11T09:30:00+00:00",
            "window_end_utc": "2026-07-11T11:30:00+00:00",
        })
        item["summary"] = "ILS RWY 20C unavailable during the departure window."

    render_pdf(_flight(), [first, second], [], 2, path)

    page = PdfReader(path).pages[2].extract_text() or ""
    normalized = " ".join(page.split())
    assert normalized.count(
        "ILS RWY 20C unavailable during the departure window."
    ) == 1
    assert "A1000/26 + A1001/26" in normalized
    assert "Approach or navigation availability affected." in normalized


def test_level2_cites_originating_evidence_without_exposing_trace_ids(
    tmp_path: Path,
) -> None:
    level1_path = tmp_path / "level_1_source_contract.pdf"
    level2_path = tmp_path / "level_2_source_contract.pdf"
    item = _notam("A1000/26", "departure")
    item["finding_id"] = "L2-NOTAM-internal-trace"
    item["data"].update({
        "audit_evidence_ref": "notam:42",
        "source_references": [
            {
                "source_type": "uploaded_cfp",
                "document_title": "SQ304_CFP.pdf",
                "section": "NOTAM package",
                "pages": [101, 102, 103],
            }
        ],
    })

    render_pdf(_flight(), [item], [], 1, level1_path)
    render_pdf(_flight(), [item], [], 2, level2_path)

    level1_text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(level1_path).pages
    )
    level2_text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(level2_path).pages
    )
    assert "Evidence:" not in level1_text
    assert "Uploaded CFP" in " ".join(level2_text.split())
    assert "CFP pp. 101-103" not in " ".join(level2_text.split())
    assert _source_label(item) == (
        "Evidence: SQ304_CFP.pdf; NOTAM package; pp. 101-103."
    )
    assert "L2-NOTAM-internal-trace" not in level2_text
    assert "notam:42" not in level2_text


def test_level2_uses_pilot_facing_title_for_internal_cfp_document_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_safe_source_title.pdf"
    item = _notam("A1000/26", "departure")
    item["data"]["source_references"] = [
        {
            "source_type": "uploaded_cfp",
            "document_title": "cfp_98abe9902fa8439e874724881c1ac28e.pdf",
            "display_title": "Uploaded company CFP",
            "section": "NOTAM package",
            "pages": [36, 37],
        }
    ]

    render_pdf(_flight(), [item], [], 2, path)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(path).pages
    )
    assert "Uploaded CFP" in " ".join(text.split())
    assert "CFP pp. 36-37" not in " ".join(text.split())
    assert _source_label(item) == (
        "Evidence: Uploaded company CFP; NOTAM package; pp. 36-37."
    )
    assert "cfp_98abe9902fa8439e874724881c1ac28e.pdf" not in text


def test_level2_weather_is_concise_deduplicated_and_does_not_repeat_raw_opmet(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_concise_weather.pdf"

    render_pdf(_flight(), [_weather(1), _weather(2)], [], 2, path)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(path).pages
    )
    assert "TAF WSSS 161100Z" not in text
    assert "trigger" not in text.lower()
    # The analysis overview is an index. The primary weather fact is shown
    # once on the dedicated page and raw source-record labels are suppressed.
    assert "Weather record 01" not in text
    assert "Weather record 02" not in text
    normalized = " ".join(text.split())
    assert normalized.count("convection / thunderstorms") == 1
    assert "Enroute UTC window not resolved" in normalized
    assert "UTC window: UTC window not resolved." not in text
    assert "Operational mechanism:" not in text
    assert (
        "Route deviation, flight-level strategy or timing may be affected."
        in normalized
    )


def test_level2_groups_repeated_no_overlap_weather_into_one_checked_summary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_grouped_clear_weather.pdf"
    findings = [
        _pertinent_weather(),
        _no_overlap_weather(
            location="KJFK",
            phase="Departure",
            window="25 JUL 0115Z-0315Z",
        ),
        _no_overlap_weather(
            location="WSSS",
            phase="Destination",
            window="25 JUL 1930Z-2330Z",
        ),
    ]

    render_pdf(_flight(), findings, [], 2, path)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(path).pages
    )
    normalized = " ".join(text.split())
    assert normalized.count(
        "No significant CFP forecast group overlapped."
    ) == 1
    assert "DEPA KJFK 25 JUL 0115Z-0315Z" in normalized
    assert "DEST WSSS 25 JUL 1930Z-2330Z" in normalized
    assert normalized.lower().count(
        "confirm the latest operational weather before use"
    ) == 1


def test_level2_deduplicates_repeated_notam_window_detail_rows() -> None:
    first = _notam("A1000/26", "departure")
    second = _notam("A1001/26", "departure")

    section = next(
        item
        for item in report_sections([first, second], 2)
        if item["engine"] == "notam"
    )

    assert section["lines"].count(
        "- Operating window 2026-07-11T09:30:00+00:00 to "
        "2026-07-11T11:30:00+00:00."
    ) == 1
    assert section["lines"].count(
        "- Location WSSS; category departure."
    ) == 1


def test_level2_uses_human_source_names_without_raw_provider_identifiers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_source_times.pdf"
    item = _notam("A1000/26", "departure")
    item["data"]["source_references"] = [{
        "source_type": "official_advisory",
        "provider": "noaa-awc-international-sigmet",
        "retrieved_at_utc": "2026-07-27T08:16:48.364917+00:00",
        "valid_from_utc": "2026-07-27T02:30:00+00:00",
        "valid_to_utc": "2026-07-27T13:20:00+00:00",
        "availability_status": "source-incomplete",
    }]

    render_pdf(_flight(), [item], [], 2, path)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(path).pages
    )
    normalized = " ".join(text.split())
    assert "Official SIGMET source" in normalized
    assert "noaa" not in normalized.lower()
    assert "awc" not in normalized.lower()
    assert "international sigmet" not in normalized.lower()
    assert ".364917+00:00" not in normalized


def test_level2_deduplicates_advisory_status_and_source_boilerplate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_advisory_deduplication.pdf"
    source = {
        "source_type": "official_advisory",
        "provider": "noaa-awc-international-sigmet",
    }
    findings = [
        {
            "engine": engine,
            "severity": "unknown",
            "title": title,
            "summary": "Official coverage is incomplete for this flight.",
            "details": [],
            "data": {
                "status": "review_required",
                "reason_codes": ["coverage_not_complete_for_flight"],
                "source_references": [source],
            },
        }
        for engine, title in (
            ("sigmet", "SIGMET review required"),
            ("vaa", "Volcanic ash review required"),
            ("tropical_cyclone", "Tropical cyclone review required"),
        )
    ]

    render_pdf(_flight(), findings, [], 2, path)

    page_seven = " ".join(
        (PdfReader(path).pages[6].extract_text() or "").split()
    )
    assert page_seven.count("Official SIGMET source") == 1
    assert page_seven.count("Same source") == 2
    assert "/ REVIEW REQUIRED" not in page_seven
    assert "coverage not complete for flight" not in page_seven


def test_level2_consolidates_unavailable_profile_wording_on_page_six(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_2_profile_boundary.pdf"
    findings = [{
        "engine": "depressurisation",
        "severity": "unknown",
        "title": "High terrain detected but no profile matched",
        "summary": (
            "No controlled profile is confirmed; manual chart-index review "
            "is required."
        ),
        "details": ["The approved controlled profile index is not mounted."],
        "data": {
            "reference_status": "controlled-source-not-mounted",
            "controlled_index_loaded": False,
        },
    }]

    render_pdf(_flight(), findings, [], 2, path)

    page_six = " ".join(
        (PdfReader(path).pages[5].extract_text() or "").split()
    )
    assert "No controlled profile is confirmed" not in page_six
    assert page_six.lower().count("controlled profile") == 1
    assert "otherwise chart review is required" in page_six.lower()


def test_route_map_label_hides_renderer_fallback_internals() -> None:
    assert _pilot_route_map_label(
        "Static map fallback - Hybrid print rendering unavailable"
    ) == "Route map"
    assert _pilot_route_map_label("Approved route display") == (
        "Approved route display"
    )


def test_level2_compacts_deterministic_event_details_without_losing_facts() -> None:
    section = next(
        item
        for item in report_sections([{
            "engine": "terrain",
            "severity": "warning",
            "title": "High-MSA event 1",
            "summary": "ACTM 07.45-07.52, max 109*.",
            "details": [
                "First high-MSA waypoint SOKRU.",
                "Maximum 109* at SOKRU.",
                "Profile matching context begins at OLIMP.",
            ],
            "data": {},
        }], 2)
        if item["engine"] == "terrain"
    )

    assert section["lines"] == [
        "High-MSA event 1: ACTM 07.45-07.52, max 109*.",
        (
            "- First high-MSA waypoint SOKRU; Maximum 109* at SOKRU; "
            "Profile matching context begins at OLIMP."
        ),
    ]


def test_run_analysis_normalizes_identity_before_json_and_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    flight = {
        "flight_number": "SIA304",
        "flight_date": "11JUL26",
        "departure": "WSSS",
        "destination": "EBBR",
        "aircraft_type": "A350-941",
        "registration": "9V-SMG",
        "weather": [],
        "notams": [],
    }
    rendered_identities = []

    monkeypatch.setattr(analysis, "extract_pages", lambda path: ["CFP"])
    monkeypatch.setattr(analysis, "parse_lido", lambda pages, name: dict(flight))
    monkeypatch.setattr(analysis, "analyse", lambda parsed: ([], []))

    def capture_render(
        parsed: dict[str, Any],
        findings: list[dict[str, Any]],
        warnings: list[str],
        level: int,
        path: Path,
    ) -> None:
        rendered_identities.append(parsed["flight_number"])
        path.write_bytes(b"pdf")

    monkeypatch.setattr(analysis, "render_pdf", capture_render)

    result = analysis.run_odss_analysis(
        tmp_path / "source.pdf",
        tmp_path / "results",
        tmp_path / "reports",
        7,
    )
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))

    assert result["flight_number"] == "SQ304"
    assert payload["flight"]["flight_number"] == "SQ304"
    assert payload["view"]["briefing"]["route_label"] == "WSSS → EBBR"
    assert rendered_identities == ["SQ304", "SQ304"]


def test_pilot_brief_category_colours_are_distinct_and_stable() -> None:
    assert CATEGORY_COLOURS == {
        "departure": "#2F80ED",
        "destination": "#7C4DFF",
        "edto": "#2EAD74",
        "weather": "#D99116",
        "communications": "#0F8B8D",
        "terrain": "#D97706",
        "critical": "#C62828",
        "neutral": "#64748B",
    }
    assert CATEGORY_COLOURS["departure"] != CATEGORY_COLOURS["destination"]


def test_level1_integrates_volcanic_ash_without_source_gate_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_1_vaa.pdf"
    flight = _flight()
    flight["vaa_review"] = {
        "status": "affected",
        "provider": "Anchorage VAAC",
        "retrieved_at_utc": "2026-07-22T07:00:00+00:00",
        "matches": [],
        "hazard_features": [],
    }
    findings = [
        {
            "engine": "vaa",
            "severity": "critical",
            "title": "Sheveluch volcanic ash proximity",
            "summary": "Time-matched route screening requires operational action.",
            "details": [
                "Closest route sector TED-GKN at 1551Z.",
                "PANC EDTO suitability requires the latest advisory.",
            ],
            "data": {},
        }
    ]

    render_pdf(flight, findings, [], 1, path)

    reader = PdfReader(path)
    assert len(reader.pages) == 3
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Sheveluch volcanic ash proximity" in text
    assert "Time-matched route screening requires operational action." in text
    assert "SOURCE / PROVENANCE" not in text
    assert "MANUAL REVIEW REQUIRED" not in text
