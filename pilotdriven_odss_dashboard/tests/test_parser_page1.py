from __future__ import annotations

from app.odss.parser import (
    _CAPTAIN_RE,
    _ZFW_BURN_RE,
    _waypoint_log_start,
    parse_lido,
)


PROSE_PAGE = "RTOW CALCULATIONS\nLIMIT Obstacle RTOW 256906 FLAPS 2\nMAX FUEL AVAIL: 058015\n"

# Real two-line waypoint-log shape (frequencies, fused MSA star, second line
# coordinates) lifted from a LIDO CFP where the log begins one page earlier
# than the legacy fixed offset assumed.
LOG_PAGE_A = (
    "WPT   FREQ   ACTM\n"
    "PKP   114.2  00.38 0.06 ... ... ... ... ... ..... 490  004  00.5 ...\n"
    "S02 10.0 E106 08.5 056 0044 400 ... 145 P01 07064 466 1915 027.2 ...\n"
    " \n"
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 117*0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
)
LOG_PAGE_B = (
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)


def _cfp_pages_with_log_from(log_index: int) -> list[str]:
    page1 = (
        "SUMMARY EDTO CFP\n"
        "9VAAA SQ999 SIN/BKK ETD 0250 01AUG26\n"
        "SCHED DEP 0250 UTC SCHED ARR 0520 UTC\n"
        "RTE NO 001            A350-941 MH  CAPT TESTA B C\n"
        "WSSS/20C\n"
        "DCT PKP DCT ALPHA DCT BRAVO\n"
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
        "ZFW CHANGE P1000KG BURN ADD   96KG / M1000KG BURN LESS  96 KG\n"
        "APPROVED/ACCEPTED BY CAPT(SIGN) .....................\n"
    )
    pages = [page1]
    while len(pages) < log_index:
        pages.append(PROSE_PAGE)
    pages.append(LOG_PAGE_A)
    pages.append(LOG_PAGE_B)
    return pages


def test_waypoint_log_start_is_detected_by_content_not_offset() -> None:
    pages = [PROSE_PAGE] * 5 + [LOG_PAGE_A, LOG_PAGE_B]
    assert _waypoint_log_start(pages) == 5

    legacy = [PROSE_PAGE] * 6 + [LOG_PAGE_A, LOG_PAGE_B]
    assert _waypoint_log_start(legacy) == 6


def test_waypoint_log_start_falls_back_to_legacy_offset_without_log() -> None:
    assert _waypoint_log_start([PROSE_PAGE] * 9) == 6


def test_parse_lido_reads_log_from_detected_page() -> None:
    flight = parse_lido(_cfp_pages_with_log_from(5), "log-shift.pdf")
    names = [w["name"] for w in flight["route_waypoints"]]
    assert "PKP" in names and "ALPHA" in names and "BRAVO" in names

    alpha = next(w for w in flight["route_waypoints"] if w["name"] == "ALPHA")
    assert alpha["msa_hundreds_ft"] == 117
    assert alpha["msa_asterisk"] is True


def test_parse_lido_legacy_log_position_still_reads() -> None:
    flight = parse_lido(_cfp_pages_with_log_from(6), "log-legacy.pdf")
    names = [w["name"] for w in flight["route_waypoints"]]
    assert "ALPHA" in names and "BRAVO" in names


def test_zfw_dual_direction_add_line_parses() -> None:
    match = _ZFW_BURN_RE.search(
        "ZFW CHANGE P1000KG BURN ADD   96KG / M1000KG BURN LESS  96 KG"
    )
    assert match is not None
    assert int(match.group("kg")) == 96


def test_zfw_slash_form_still_parses() -> None:
    match = _ZFW_BURN_RE.search("ZFW CHANGE / M1000KG BURN LESS 454 KG")
    assert match is not None
    assert int(match.group("kg")) == 454


def test_captain_parsed_from_plan_line() -> None:
    match = _CAPTAIN_RE.search(
        "RTE NO SINPER33E            A350-941 MH  CAPT CHAN K B DAVID\n9VSHC  SIA223"
    )
    assert match is not None
    assert match.group("name").strip() == "CHAN K B DAVID"


def test_captain_signature_placeholder_is_ignored() -> None:
    assert _CAPTAIN_RE.search("APPROVED/ACCEPTED BY CAPT(SIGN) .............") is None


def test_parse_lido_carries_captain_and_zfw_fields() -> None:
    flight = parse_lido(_cfp_pages_with_log_from(5), "fields.pdf")
    assert flight["captain"] == "TESTA B C"
    assert flight["zfw_change_burn_kg_per_1000"] == 96
