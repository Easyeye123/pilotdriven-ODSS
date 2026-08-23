from __future__ import annotations

from app.odss.parser import (
    _CAPTAIN_RE,
    _ZFW_BURN_RE,
    _parse_deferred_items,
    _parse_intam_records,
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
        "FLT RULES: EDTO/RVSM CRUISE CI 73 APD 1.8 PCT\n"
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
        "2000 FT BELOW AT CI70 BURN ADD 632KG / TIME 04.52\n"
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
    assert flight["zfw_change_burn_add_kg_per_1000"] == 96
    assert flight["zfw_change_burn_less_kg_per_1000"] == 96
    assert flight["lower_cruise_sensitivity"] == {
        "offset_ft": 2000,
        "cost_index": 70,
        "burn_add_kg": 632,
        "time_token": "04.52",
        "time_display": "4:52",
    }


def test_parse_lido_carries_route_identifier_and_apd_from_page_one() -> None:
    flight = parse_lido(_cfp_pages_with_log_from(5), "overview-fields.pdf")

    assert flight["route_identifier"] == "001"
    assert flight["edto_rvsm"] == "EDTO/RVSM"
    assert flight["cost_index"] == 73
    assert flight["apd_percent"] == 1.8


def test_parse_lido_preserves_intermediate_mnps_in_printed_flight_rules() -> None:
    pages = _cfp_pages_with_log_from(5)
    pages[0] = pages[0].replace("EDTO/RVSM", "EDTO/MNPS/RVSM")

    flight = parse_lido(pages, "mnps-rules.pdf")

    assert flight["edto_rvsm"] == "EDTO/MNPS/RVSM"


def test_parse_lido_preserves_single_printed_rvsm_flight_rule() -> None:
    pages = _cfp_pages_with_log_from(5)
    pages[0] = pages[0].replace("EDTO/RVSM", "RVSM")

    flight = parse_lido(pages, "non-edto-rvsm-rules.pdf")

    assert flight["edto_rvsm"] == "RVSM"


SQ910_DECLARATION_BLOCK = (
    "AA IFEDDL\n"
    "   SEAT IFE (YCL), AUDIO JACK, NO AUDIO\n"
    "   41E, 57A X CLASS B\n"
    "BB CDDL\n"
    "   TRASH COMPACTOR 212 NO POWER\n"
    "   TO UPLIFT TRASH BAGS\n"
    "CC MEL 25-20-50A\n"
    "   D4L GALLEY CHILLER NO.1 RED LIGHT BLINKING\n"
    "   TO UPLIFT DRY ICE\n"
    "DD IN SIA/00-017 R1\n"
    "   ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE.\n"
    "   HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE\n"
    "   TO APPLY WHENEVER NECESSARY\n"
)


def test_sq910_four_shape_declaration_block_parses_as_first_class_items() -> None:
    # Boss, 21 Aug 2026 SQ910 CFP page 1 verbatim. Prod printed
    # "UNCLASSIFIED; CDDL UNSPECIFIED" and folded the DD IN engineering
    # notice (ENG 2 fan cowl latch - his GPT's MAJOR release gate) into the
    # MEL item's remark. Every declaration survives under the CFP's own word.
    pages = _cfp_pages_with_log_from(2)
    pages[0] = pages[0].replace(
        "RTE NO 001",
        SQ910_DECLARATION_BLOCK + "PLAN 3\nRTE NO 001",
    )
    result = parse_lido(pages, "SQ910.pdf")
    items = result["deferred_items"]
    assert [item["item_type"] for item in items] == ["IFEDDL", "CDDL", "MEL", "IN"]
    assert items[0]["reference"] is None
    assert items[0]["description"] == "SEAT IFE (YCL), AUDIO JACK, NO AUDIO"
    assert items[0]["company_remark"] == "41E, 57A X CLASS B"
    assert items[1]["reference"] is None
    assert items[1]["description"] == "TRASH COMPACTOR 212 NO POWER"
    assert items[1]["company_remark"] == "TO UPLIFT TRASH BAGS"
    assert items[2]["reference"] == "25-20-50A"
    assert items[2]["description"] == "D4L GALLEY CHILLER NO.1 RED LIGHT BLINKING"
    assert items[2]["company_remark"] == "TO UPLIFT DRY ICE"
    assert items[3]["reference"] == "SIA/00-017 R1"
    assert items[3]["description"] == "ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE."
    assert (
        items[3]["company_remark"]
        == "HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE TO APPLY WHENEVER NECESSARY"
    )


def test_prefixed_declaration_with_undashed_trailing_text_is_kept() -> None:
    # SQ366 4 Aug CFP prints "CC MEL PREAMBLE SECTION MEL AND CMS REV 18NOV 25"
    # — no dash between reference and trailing words. The line stays a
    # first-class item with the trailing words as its description.
    items = _parse_deferred_items(
        "SUMMARY STANDARD CFP\n"
        "AA MEL 29-10-03A - RESERVOIR AIR BLEED VALVE\n"
        "CC MEL PREAMBLE SECTION MEL AND CMS REV 18NOV 25 \n"
        "PLAN 2\n"
    )
    assert [(item["item_type"], item["reference"]) for item in items] == [
        ("MEL", "29-10-03A"),
        ("MEL", "PREAMBLE"),
    ]
    assert items[0]["description"] == "RESERVOIR AIR BLEED VALVE"
    assert items[1]["description"] == "SECTION MEL AND CMS REV 18NOV 25"


def test_intam_projection_holds_headers_headlines_and_physical_pages() -> None:
    pages = [
        "SUMMARY CFP",
        (
            "INTAM\n\n1.OPS A350-606 260321\n"
            "SYSTEM RESETS (UPDATED 06APR2026)\n\nBODY TEXT\n"
        ),
        (
            "2. SEC SSC 04/2026 010426\n"
            "SSE MNL SECURITY STATUS\n\nSTATUS : AMBER\n"
        ),
    ]

    records = _parse_intam_records(pages, (1, 3))

    assert records == [
        {
            "priority": 1,
            "category": "OPS",
            "identity": "A350-606",
            "date_token": "260321",
            "header": "1.OPS A350-606 260321",
            "headline": "SYSTEM RESETS (UPDATED 06APR2026)",
            "source_page": 2,
        },
        {
            "priority": 2,
            "category": "SEC",
            "identity": "SSC 04/2026",
            "date_token": "010426",
            "header": "2. SEC SSC 04/2026 010426",
            "headline": "SSE MNL SECURITY STATUS",
            "source_page": 3,
        },
    ]
