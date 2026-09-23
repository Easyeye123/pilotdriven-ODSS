from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.odss.briefing import build_briefing_view
from app.odss.engines import _notam_role_window, _weather_role_window, analyse
from app.odss.parser import extract_pages, parse_lido


def _fuel_enroute_flight(
    *,
    weather_role_heading: str = "FUEL ENROUTE AIRPORT:",
    notam_role_heading: str = "FUEL ENROUTE AIRPORT",
    closing_heading: str = "EDTO SUITABLE ENROUTE AIRPORT(S)",
) -> dict:
    page1 = (
        "SUMMARY STANDARD CFP\n"
        "9VAAA SQ999 SIN/BKK ETD 0250 01AUG26\n"
        "SCHED DEP 0250 UTC SCHED ARR 0520 UTC\n"
        "RTE NO 001            A350-941 MH  CAPT TESTA B C\n"
        "WSSS/20C\n"
        "DCT ALPHA DCT BRAVO\n"
        "VTBS/19L\n"
        "GND  MILES    900\n"
        "AIR  MILES    930\n"
        "BURNOFF 02.00 010000\n"
        "TAXI FUEL 001000\n"
        "FLT PLAN REQMT 03.00 015000\n"
        "FUEL IN TANKS 04.00 020000\n"
        "PZFW 180000\n"
        "PTOW 200000\n"
        "PLWT 190000\n"
    )
    log_page = (
        "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
        "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
        " \n"
        "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
        "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
    )
    weather_page = (
        "AIRPORT WX LIST\n"
        f"{weather_role_heading}\n"
        "WIII/CGK JAKARTA/SOEKARNO HATTA INTL\n"
        "  SA 010200 04012KT 9999 FEW020 29/23 Q1010=\n"
        "  FT 312300 0100/0206 05010KT 9999 SCT020=\n"
        "ENROUTE AIRPORT(S):\n"
        "WMKK/KUL KUALA LUMPUR INTL\n"
        "  SA 010200 00000KT CAVOK 28/22 Q1011=\n"
        "AIRPORTLIST ENDED\n"
    )
    notam_page = (
        "NOTAM\n"
        "====================\n"
        f"{notam_role_heading}\n"
        "====================\n"
        "WIII /CGK   JAKARTA/SOEKARNO HATTA INTL /ADEQ\n"
        "---------------------------------------------\n"
        "++++++++++++++++++++ RUNWAY ++++++++++++++++++++\n"
        "1A2872/26 VALID: 01-JUL-26 0000 - 30-SEP-26 2359\n"
        "  RWY 07R/25L CLSD DUE TO RWY INSPECTION\n"
        "1A2870/26 VALID: 01-JUL-26 0000 - 30-SEP-26 2359\n"
        "  RWY 07L/25R CLSD DUE TO RUBBER DEPOSIT REMOVAL\n"
        "1A2868/26 VALID: 01-JUL-26 0000 - 30-SEP-26 2359\n"
        "  RWY 06/24 CLSD DUE TO RUBBER DEPOSIT REMOVAL\n"
        "++++++++++++++++ APPROACH PROCEDURE ++++++++++++++++\n"
        "SX74/25 VALID: 27-NOV-25 0000 - 27-NOV-26 2359\n"
        "  THE UNSERVICEABILITY OF ILS AND GP RWY 24\n"
        "++++++++++++++++++++ AIRPORT ++++++++++++++++++++\n"
        "1A2574/26 VALID: 22-JUL-26 0743 - 30-SEP-26 2359\n"
        "  D-ATIS LIMITED TRIAL IN PROGRESS. VOICE ATIS REMAINS PRIMARY.\n"
        "================================\n"
        f"{closing_heading}\n"
        "================================\n"
        "WADD /DPS BALI/I GUSTI NGURAH RAI /ADEQ\n"
        "-----------------------------------------\n"
    )
    return parse_lido(
        [page1, log_page, weather_page, notam_page],
        "generic-fuel-enroute.pdf",
    )


def test_dedicated_fuel_enroute_sections_become_first_class_records() -> None:
    flight = _fuel_enroute_flight()

    assert flight["fuel_enroute_airports"] == [{
        "airport": "WIII",
        "iata": "CGK",
        "name": "JAKARTA/SOEKARNO HATTA INTL",
        "role": "fuel_enroute_airport",
        "weather_source_pages": [3],
        "source_pages": [3, 4],
        "notam_source_pages": [4],
    }]
    weather = [item for item in flight["weather"] if item["location"] == "WIII"]
    assert [item["record_type"] for item in weather] == ["METAR", "TAF"]
    assert {item["source_page"] for item in weather} == {3}
    assert {item["source_role"] for item in weather} == {"fuel_enroute_airport"}

    notams = [item for item in flight["notams"] if item["location"] == "WIII"]
    assert {item["notam_id"] for item in notams} == {
        "1A2868/26",
        "1A2870/26",
        "1A2872/26",
        "SX74/25",
        "1A2574/26",
    }
    assert {item["source_page"] for item in notams} == {4}
    assert {item["source_role"] for item in notams} == {"fuel_enroute_airport"}
    d_atis = next(item for item in notams if item["notam_id"] == "1A2574/26")
    assert d_atis["priority_score"] == 0
    assert d_atis["text"] == (
        "D-ATIS LIMITED TRIAL IN PROGRESS. VOICE ATIS REMAINS PRIMARY."
    )


def test_fuel_enroute_identity_is_unioned_when_only_one_appendix_names_role() -> None:
    weather_generic = _fuel_enroute_flight(
        weather_role_heading="ENROUTE AIRPORT(S):",
    )
    notam_generic = _fuel_enroute_flight(
        notam_role_heading="ENROUTE AIRPORT(S)",
    )

    for flight in (weather_generic, notam_generic):
        station = flight["fuel_enroute_airports"][0]
        assert station["airport"] == "WIII"
        assert station["source_pages"] == [3, 4]
        assert {
            record["record_type"]
            for record in flight["weather"]
            if record["location"] == "WIII"
        } == {"METAR", "TAF"}
        assert {
            record["notam_id"]
            for record in flight["notams"]
            if record["location"] == "WIII"
        } >= {"SX74/25", "1A2574/26"}


def test_dual_role_station_uses_union_of_fuel_alternate_and_edto_windows() -> None:
    flight = _fuel_enroute_flight()
    start = datetime(2026, 8, 1, 1, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    alternates = {"WIII"}
    edto_periods = {"WIII": (start, end)}

    role, notam_start, notam_end = _notam_role_window(
        flight,
        "WIII",
        alternates,
        edto_periods,
        {"WIII"},
        "fuel_enroute_airport",
    )
    phase, weather_start, weather_end = _weather_role_window(
        flight,
        "WIII",
        alternates,
        edto_periods,
        {"WIII"},
        "fuel_enroute_airport",
    )

    assert role == "fuel enroute airport"
    assert phase == "Fuel enroute airport"
    assert (notam_start, notam_end) == (start, end)
    assert (weather_start, weather_end) == (start, end)


def test_fuel_enroute_role_reaches_analysis_and_shared_briefing_view() -> None:
    flight = _fuel_enroute_flight()
    findings, warnings = analyse(flight)

    weather_findings = [
        item
        for item in findings
        if item["engine"] == "weather"
        and (item.get("data") or {}).get("location") == "WIII"
    ]
    assert weather_findings
    assert {item["data"]["phase"] for item in weather_findings} == {
        "Fuel enroute airport"
    }
    notam_findings = [
        item
        for item in findings
        if item["engine"] == "notam"
        and (item.get("data") or {}).get("location") == "WIII"
    ]
    assert {item["data"]["role"] for item in notam_findings} == {
        "fuel enroute airport"
    }
    d_atis = next(
        item
        for item in notam_findings
        if item["data"]["notam_id"] == "1A2574/26"
    )
    assert d_atis["severity"] == "information"

    view = build_briefing_view(flight, findings, warnings)
    assert len(view["fuel_enroute_airports"]) == 1
    station = view["fuel_enroute_airports"][0]
    assert station["icao"] == "WIII"
    assert station["iata"] == "CGK"
    assert station["role"] == "fuel enroute airport"
    assert station["role_key"] == "fuel_enroute_airport"
    assert station["source_pages"] == [3, 4]
    assert station["weather"]["metar"]["text"].startswith("SA 010200")
    assert station["weather"]["taf"]["text"].startswith("FT 312300")
    assert station["weather"]["metar"]["source_page"] == 3
    assert {item["notam_id"] for item in station["selected_notams"]} == {
        "A2868/26",
        "A2870/26",
        "A2872/26",
        "SX74/25",
        "A2574/26",
    }
    assert any(
        "D-ATIS LIMITED TRIAL" in item["item_e_text"]
        for item in station["selected_notams"]
    )
    assert {item["source_page"] for item in station["selected_notams"]} == {4}
    compact_notams = [
        item
        for item in station["card_summary_lines"]
        if item["kind"] == "notam"
    ]
    assert compact_notams == [
        {
            "kind": "notam",
            "label": "SX74/25",
            "text": "ILS/GP RWY24 unavailable.",
            "notam_id": "SX74/25",
            "item_e_text": "THE UNSERVICEABILITY OF ILS AND GP RWY 24",
            "source_page": 4,
            "source_role": "fuel_enroute_airport",
                "role": "fuel enroute airport",
                "applicability": "active",
                "stateAtReference": "active_at_reference",
                "referenceAt": "2026-08-01T02:50:00+00:00",
                "minutesDelta": 0,
                "severity": "critical",
            "category": "APPROACH PROCEDURE",
            "pertinence_kind": "approach_navaid_closure",
            "approach_affected": True,
            "approach_condition_review": False,
            "signal_family": "approach_navaid",
            "planned_match": None,
            "different_runway": False,
        },
        {
            "kind": "notam",
            "label": "A2574/26",
            "text": "D-ATIS limited trial; voice ATIS remains primary.",
            "notam_id": "A2574/26",
            "item_e_text": (
                "D-ATIS LIMITED TRIAL IN PROGRESS. VOICE ATIS REMAINS PRIMARY."
            ),
            "source_page": 4,
            "source_role": "fuel_enroute_airport",
                "role": "fuel enroute airport",
                "applicability": "active",
                "stateAtReference": "active_at_reference",
                "referenceAt": "2026-08-01T02:50:00+00:00",
                "minutesDelta": 0,
                "severity": "information",
            "category": "AIRPORT",
            "pertinence_kind": "other_operational",
            "approach_affected": False,
            "approach_condition_review": False,
            "signal_family": "information_service",
            "planned_match": None,
            "different_runway": False,
        },
    ]
    assert [
        item["text"]
        for item in station["card_summary_lines"]
        if item["kind"] == "weather"
    ] == [
        station["weather"]["metar"]["text"],
        station["weather"]["taf"]["text"],
    ]


def test_compact_card_category_coverage_cannot_drop_full_selected_notams() -> None:
    flight = _fuel_enroute_flight()
    for index, area in enumerate(("ALPHA", "BRAVO", "CHARLIE", "DELTA")):
        flight["notams"].append({
            "notam_id": f"EX{index}/26",
            "location": "WIII",
            "category": "RUNWAY",
            "text": f"RWY {10 + index}/28 CLSD FOR INSPECTION AREA {area}",
            "valid_from_utc": "2026-07-01T00:00:00+00:00",
            "valid_to_utc": "2026-09-30T23:59:00+00:00",
            "schedule": None,
            "schedule_review": False,
            "validity_review": False,
            "priority_score": 10,
            "source_page": 4,
            "source_role": "fuel_enroute_airport",
        })

    findings, warnings = analyse(flight)
    panel = build_briefing_view(flight, findings, warnings)[
        "fuel_enroute_airports"
    ][0]

    assert len(panel["selected_notams"]) == 9
    assert {item["notam_id"] for item in panel["selected_notams"]} >= {
        "EX0/26",
        "EX1/26",
        "EX2/26",
        "EX3/26",
        "SX74/25",
        "A2574/26",
    }
    assert [
        item["notam_id"]
        for item in panel["card_summary_lines"]
        if item["kind"] == "notam"
    ] == ["SX74/25", "A2574/26"]


# ---------------------------------------------------------------------------
# The fuel-enroute section ends at the next airport section, whichever LIDO
# prints. Independent QA of release 402 (SQ365 LIRF-WSSS, 23 Sep 2026): a NON
# EDTO CFP prints FUEL ENROUTE AIRPORT (p39) and then EDTO ADEQUATE ENROUTE
# AIRPORT(S) (p40) - no SUITABLE section between them - and the fuel section
# ran on to ENROUTE AIRPORT(S) on p55, so all 34 adequate stations were held as
# fuel-enroute airports: VAAH's card said EDTO adequate enroute, then "Checked
# window · fuel enroute airport", then "during the applicable fuel enroute
# airport window". The same shape is printed on SQ605 (NON EDTO) and on the
# EDTO flights SQ303 16 Jul and SQ214 16 Aug.


@pytest.mark.parametrize(
    "closing_heading",
    [
        "EDTO ADEQUATE ENROUTE AIRPORT(S)",
        "ETOPS SUITABLE ENROUTE AIRPORT(S)",
        "ETOPS ADEQUATE ENROUTE AIRPORT(S)",
        "ADEQUATE ENROUTE AIRPORT(S)",
    ],
)
def test_the_fuel_enroute_section_ends_at_every_airport_section_heading(closing_heading: str) -> None:
    flight = _fuel_enroute_flight(closing_heading=closing_heading)

    assert [station["airport"] for station in flight["fuel_enroute_airports"]] == ["WIII"]
    # Only WIII prints a NOTAM block in this fixture; WADD, past the heading, is not held as a fuel station.
    assert {record["location"] for record in flight["notams"]} == {"WIII"}


def test_the_edto_suitable_heading_still_ends_the_fuel_enroute_section() -> None:
    flight = _fuel_enroute_flight()

    assert [station["airport"] for station in flight["fuel_enroute_airports"]] == ["WIII"]


_CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"


@pytest.mark.parametrize(
    ("filename", "fuel", "analysed_stations", "not_a_fuel_station"),
    [
        # NON EDTO: FUEL ENROUTE p39, EDTO ADEQUATE ENROUTE p40, ENROUTE p55. The
        # stations analysed are the planning stations that print a NOTAM block
        # (EDDM through the engine's standing Munich exception), 7 instead of 36.
        ("SQ36507082026FCO.pdf", ["WIMM"], {"LIRF", "WSSS", "WSAP", "WMKK", "WIDD", "WIMM", "EDDM"}, "VAAH"),
        # NON EDTO: the same shape, both headings on p39; 6 instead of 21.
        ("SQ60508092026ICN.pdf", ["VVTS"], {"RKSI", "WSSS", "WSAP", "WMKK", "WIDD", "VVTS"}, "WMSA"),
        # EDTO, the adequate section follows the fuel section directly (p41); 7 instead of 50.
        ("SQ30316072026BRU 81.pdf", ["VTSP"], {"EBBR", "WSSS", "WSAP", "WMKK", "VTSP", "VTBD", "EDDM"}, "EBOS"),
        # EDTO, the same shape (p25/p26); WIII is both the fuel and the EDTO airport; 6 instead of 12.
        ("lido-briefing_SQ_214_16Aug2026_PER_SIN.pdf", ["WIII"], {"YPPH", "WSSS", "WSAP", "WMKK", "WIDD", "WIII"}, "WADD"),
        # Control: an EDTO SUITABLE section already closed the fuel section; 6, as before.
        ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", ["EPWA"], {"WSSS", "EKCH", "ESMS", "EDDF", "EPWA", "VOMM"}, "WMSA"),
    ],
)
def test_real_ofps_hold_only_their_fuel_enroute_section_as_fuel_stations(
    filename: str, fuel: list[str], analysed_stations: set[str], not_a_fuel_station: str
) -> None:
    source = _CORPUS / filename
    if not source.exists():
        pytest.skip("the private OFP corpus is not available")
    flight = parse_lido(extract_pages(source), filename)

    assert [station["airport"] for station in flight["fuel_enroute_airports"]] == fuel
    assert {record["location"] for record in flight["notams"]} == analysed_stations
    assert not_a_fuel_station not in analysed_stations


@pytest.mark.skipif(not (_CORPUS / "SQ30316072026BRU 81.pdf").exists(), reason="the private OFP corpus is not available")
def test_an_edto_airport_the_over_run_swallowed_keeps_its_edto_window_only() -> None:
    # SQ303's EDTO alternate VTBD sits in the adequate section the fuel section
    # ran into, so its window was widened to the whole flight under the fuel
    # role and its reference moved to departure.
    filename = "SQ30316072026BRU 81.pdf"
    flight = parse_lido(extract_pages(_CORPUS / filename), filename)
    from app.odss.engines import _notam_role_windows

    windows = _notam_role_windows(flight, "VTBD", {a["airport"] for a in flight["alternates"]}, {s["airport"] for s in flight["fuel_enroute_airports"]}, "")
    assert [(role, start.isoformat(), end.isoformat()) for role, start, end in windows] == [
        ("EDTO", "2026-07-16T19:53:00+00:00", "2026-07-16T22:09:00+00:00"),
    ]
    assert {record.get("source_role") for record in flight["notams"] if record["location"] == "VTBD"} == {None}

