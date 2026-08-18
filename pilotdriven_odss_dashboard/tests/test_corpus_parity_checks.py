from __future__ import annotations

from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import _edto_classification, _edto_operational_rows
from app.odss.parser import parse_lido
from scripts.run_private_cfp_corpus import check_cross_surface_parity


LOG_PAGE_HIGH = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 117*0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)
LOG_PAGE_LOW = LOG_PAGE_HIGH.replace("117*0225", "056 0225")


def _flight(log_page: str) -> dict:
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
    flight = parse_lido([page1, "", "", "", "", "", log_page], "parity.pdf")
    flight["weather"] = [
        {"location": "WSSS", "record_type": "METAR", "text": "SA 010200 11007KT 9999"},
    ]
    return flight


def _passing_text(flight: dict) -> str:
    view = build_briefing_view(flight, [], [])
    parts = [value for _, value in _edto_operational_rows(
        _edto_classification(flight), view["edto"], flight.get("fuel_summary") or {}
    )]
    parts.append(view["terrain"]["summary"])
    for role in ("departure", "destination"):
        weather = view[role]["weather"]
        if weather.get("metar"):
            parts.append(f"METAR {weather['metar']}")
        if weather.get("taf"):
            parts.append(f"TAF {weather['taf']}")
    for item in (flight.get("fuel_summary") or {}).get("excess_breakdown") or []:
        if item.get("fuel_kg"):
            parts.append(f"{item['label']} {item['fuel_kg']:,} kg")
    return "\n".join(parts)


def test_complete_output_passes() -> None:
    for log_page in (LOG_PAGE_HIGH, LOG_PAGE_LOW):
        flight = _flight(log_page)
        result = check_cross_surface_parity(flight, [], [], _passing_text(flight))
        assert result["valid"], result["failures"]


def test_terrain_contradiction_fails() -> None:
    flight = _flight(LOG_PAGE_HIGH)
    text = _passing_text(flight) + "\nNo strict MSA >100* window detected"
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("terrain" in failure for failure in result["failures"])


def test_missing_no_window_sentence_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = _passing_text(flight).replace("No strict MSA >100* window detected", "")
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("terrain" in failure for failure in result["failures"])


def test_missing_edto_row_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    view = build_briefing_view(flight, [], [])
    rows = _edto_operational_rows(
        _edto_classification(flight), view["edto"], flight.get("fuel_summary") or {}
    )
    text = _passing_text(flight).replace(rows[0][1], "")
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("edto" in failure for failure in result["failures"])


def test_unprinted_bulletin_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = _passing_text(flight).replace("METAR SA 010200", "METAR WITHHELD")
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("weather" in failure for failure in result["failures"])


def test_excess_item_without_kg_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = _passing_text(flight)
    flight["fuel_summary"] = {"excess_breakdown": [{"label": "POLICY", "fuel_kg": 1500}], "rows": {}}
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("units" in failure for failure in result["failures"])


def test_banned_wording_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = _passing_text(flight) + "\nLEVEL 2 - PROFILE MATCH"
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("naming" in failure for failure in result["failures"])


def test_unnamed_volcanic_ash_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"].append({
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION MT KRAKATAU SFC/FL070",
    })
    text = _passing_text(flight)
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("VOLCANIC ASH" in failure for failure in result["failures"])
    result_ok = check_cross_surface_parity(flight, [], [], text + "\nVOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 08")
    assert result_ok["valid"], result_ok["failures"]


def test_missing_derived_screening_line_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"].append({
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION "
            "MT KRAKATAU VA CLD OBS WI S0720 E10749 - S0720 E10849 - "
            "S0620 E10800 SFC/FL070"
        ),
    })
    named = _passing_text(flight) + "\nVOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 08"
    result = check_cross_surface_parity(flight, [], [], named)
    assert not result["valid"]
    assert any("derived" in failure for failure in result["failures"])
    result_ok = check_cross_surface_parity(
        flight, [], [], named + "\nClosest approach 60 NM near ALPHA; ash layer SFC/FL070"
    )
    assert result_ok["valid"], result_ok["failures"]
