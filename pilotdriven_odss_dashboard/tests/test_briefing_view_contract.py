from __future__ import annotations

from app.odss.briefing import build_briefing_view
from app.odss.parser import parse_lido


LOG_PAGE_HIGH = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 117*0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)
LOG_PAGE_LOW = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)


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
    pages = [page1, "", "", "", "", "", log_page]
    return parse_lido(pages, "briefing-view-contract.pdf")


def test_terrain_key_is_engine_backed_and_always_present() -> None:
    high = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    assert high["terrain"]["events"], "a >100* waypoint must produce a terrain event"
    assert "No strict MSA" not in high["terrain"]["summary"]

    low = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert low["terrain"]["events"] == []
    assert low["terrain"]["summary"] == "No strict MSA >100* window detected"


def test_terrain_summary_and_events_can_never_disagree() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    has_events = bool(view["terrain"]["events"])
    says_none = "No strict MSA" in view["terrain"]["summary"]
    assert has_events != says_none


def test_airport_panels_carry_raw_metar_and_taf() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [
        {"location": "WSSS", "record_type": "METAR", "text": "SA 172000 11007KT 9999 FEW018", "source_page": 14},
        {"location": "WSSS", "record_type": "TAF", "text": "FT 171700 1718/1900 14008KT 9999", "source_page": 14},
        {"location": "VTBS", "record_type": "METAR", "text": "SA 172000 AUTO 05006KT 9999", "source_page": 15},
    ]
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] == "SA 172000 11007KT 9999 FEW018"
    assert view["departure"]["weather"]["taf"] == "FT 171700 1718/1900 14008KT 9999"
    assert view["destination"]["weather"]["metar"] == "SA 172000 AUTO 05006KT 9999"
    assert view["destination"]["weather"]["taf"] is None


def test_airport_panels_without_records_stay_honest() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] is None
    assert view["departure"]["weather"]["taf"] is None


def test_metrics_carry_the_captain() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert view["metrics"]["captain"] == "TESTA B C"


def test_edto_operational_rows_are_part_of_the_view() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    rows = view["edto"]["operational_rows"]
    assert rows and rows[0]["label"] == "CLASSIFICATION"
    labels = [row["label"] for row in rows]
    assert "GATE" in labels and "FUEL" in labels
    assert all(isinstance(row["value"], str) and row["value"] for row in rows)


def test_va_sigmet_records_become_named_deduped_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    record = {
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 WIII- WIIF JAKARTA FIR VA ERUPTION MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI S0614 E10534 - S0623 E10451 SFC/FL070 MOV NW 10KT NC=",
        "source_page": 13,
    }
    flight["weather"] = [dict(record), dict(record)]
    view = build_briefing_view(flight, [], [])
    advisories = view["vaa"]["cfp_advisories"]
    assert len(advisories) == 1, "identical wx-list reprints collapse to one advisory"
    assert advisories[0]["name"] == "VOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 08"
    assert advisories[0]["valid_from"] == "172009" and advisories[0]["valid_to"] == "180208"


def test_va_polygon_screening_derives_closest_approach() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION "
            "MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI "
            "S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070 MOV NW 10KT NC="
        ),
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    derived = view["vaa"]["cfp_advisories"][0]["derived"]
    # Nearest polygon point sits 60 NM north of ALPHA (S08 20.2 E107 49.7):
    # the screening says so with the passage time (ALPHA ACTM 01:25 after the
    # 0250Z departure), the layer, and the no-official-VAAC caveat verbatim.
    # The SIGMET's validity day is nowhere near this synthetic flight date,
    # so no expiry comparison may be printed.
    assert derived.startswith("Closest approach 60 NM near ALPHA; route passes ~0415Z; ash layer SFC/FL070;")
    assert "expiry" not in derived and "validity (to" not in derived
    assert "official VAAC confirmation unavailable" in derived


def test_va_screening_compares_passage_time_with_sigmet_validity() -> None:
    flight = _flight(LOG_PAGE_LOW)
    polygon = "WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070"
    # Passage is ~0415Z on 01 Aug (ALPHA ACTM 01:25 after 0250Z departure).
    for valid, expected in (
        ("010300/010500", "inside the SIGMET's validity (to 0500Z)"),
        ("010200/010355", "20 min after the SIGMET's 0355Z expiry"),
    ):
        flight["weather"] = [{
            "location": "WIIF", "record_type": "VA_SIGMET",
            "text": f"WIIF JAKARTA FIR WV SIGMET 08 VALID {valid} VA ERUPTION MT KRAKATAU {polygon}",
        }]
        view = build_briefing_view(flight, [], [])
        derived = view["vaa"]["cfp_advisories"][0]["derived"]
        assert expected in derived, derived


def test_va_advisory_without_readable_polygon_has_no_derived_line() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        # Two-point "polygon": unreadable as an area, so no distance may be
        # invented - the card shows only the named advisory.
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION MT KRAKATAU WI S0614 E10534 - S0623 E10451 SFC/FL070",
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"][0]["derived"] is None


def test_no_va_records_mean_no_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"] == []
