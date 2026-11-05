"""Lido page 1 may overflow onto a second physical PDF page.

David's SQ882 SIN/HKG OFP of 10 Sep 2026 carried three MEL/CDL remarks on
page 1. The briefing package printed that logical page across two physical
pages: the fuel ladder (TAXI FUEL, PZFW/PTOW/PLWT) sat on a header-less
second page that carried only the package footer. Production rejected the
upload as "Incomplete or unsupported Lido OFP; missing taxi fuel ...".
"""
from __future__ import annotations

import pytest

from app.odss.parser import _complete_standard_lido_cfp_page_span, parse_lido


PAGE1_HEAD = (
    " \n"
    "OFP\n"
    " \n"
    "PAGE  1 OF 2 SIA882 SIN/HKG 10SEP26\n"
    " \n"
    "             SINGAPORE AIRLINES - SUMMARY STANDARD CFP\n"
    "             -----------------------------------------\n"
    "REMARKS:\n"
    "ATTN ALL CONCERN FR MAINTROL\n"
    "AA MEL 25-20-50A\n"
    "   MAINT ENTRY\n"
    "   AIR CHILLER NOT COLD\n"
    "BB MEL 31-19-03A\n"
    "   VIDEO PB ON ECP NOT RESPONSIVE.\n"
    "CC CDL 27-20\n"
    "   MAINT ENTRY: O/B FLAP, O/B CUSHION SEAL FOUND WORN.\n"
    " \n"
    "        PLAN 8\n"
    "RTE NO SINHKG01              A350-941     CAPT TEST A B +\n"
    "9VSHP  SIA882      SIN/HKG   ETD 0040 10SEP26 UTC\n"
    "WSSS/20C DCT ALPHA\n"
    "DCT BRAVO VHHH/07R\n"
    "SIN/360/ALPHA/390/BRAVO/410\n"
    " \n"
    "SCHED DEP 0040 UTC      SCHED ARR 0440 UTC\n"
    " \n"
    "FLT RULES: RVSM                 CRUISE CI 70       APD 1.7  PCT\n"
    " \n"
    "                                             TIME   FUEL\n"
    "GND  MILES    1515  CRZ COMP M007   BURNOFF  03.20  018419\n"
    "SIA 882/10Sep26/WSSS-VHHH Reg:9VSHP OFP:8/0/0\n"
    "Page 1 of 3\n"
)

PAGE1_CONTINUATION = (
    " \n"
    "AIR  MILES    1537                STAT CONT  00.09  000804\n"
    "ALTN MFM (VMMC)                   ALTN FUEL  00.20  001817\n"
    "                                  ALTN HOLD  00.30  002315\n"
    "           TOP UP TO 60 MINS DEST HOLD FUEL  00.00  000000\n"
    "                                  TAXI FUEL         000600\n"
    "PZFW 174700                  FLT PLAN REQMT  04.19  023955\n"
    " \n"
    "PTOW 199155                     EXCESS FUEL  00.12  001100\n"
    " \n"
    "PLWT 180736                   FUEL IN TANKS  04.31  025055\n"
    "SIA 882/10Sep26/WSSS-VHHH Reg:9VSHP OFP:8/0/0\n"
    "Page 2 of 3\n"
)

PAGE2 = (
    " \n"
    "PAGE  2 OF 2 SIA882 SIN/HKG 10SEP26\n"
    " \n"
    "FLT PLANNING ALTN SUMMARY:\n"
    "--------------------------\n"
    "ALTN/RWY  APPROACH      MINIMA    DIST  FL  COMP  TIME  FUEL\n"
    "VMMC/34   RNAV GPS   720FT/3700M  0085  100 P013  0020 01817\n"
    " \n"
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
    "SIA 882/10Sep26/WSSS-VHHH Reg:9VSHP OFP:8/0/0\n"
    "Page 3 of 3\n"
)


def test_page1_fuel_ladder_on_overflow_page_is_parsed():
    flight = parse_lido(
        [PAGE1_HEAD, PAGE1_CONTINUATION, PAGE2],
        "SQ882-10SEP-page1-overflow.pdf",
    )

    assert flight["flight_number"] == "SIA882"
    assert flight["fuel"]["taxi_fuel_kg"] == 600
    assert flight["fuel"]["flight_plan_required_fuel_kg"] == 23955
    assert flight["fuel"]["fuel_in_tanks_kg"] == 25055
    assert flight["fuel"]["trip_fuel_kg"] == 18419
    assert flight["masses"]["planned_zfw_kg"] == 174700
    assert flight["masses"]["planned_takeoff_weight_kg"] == 199155
    assert flight["masses"]["planned_landing_weight_kg"] == 180736
    assert [item["reference"] for item in flight["deferred_items"]] == [
        "25-20-50A",
        "31-19-03A",
        "27-20",
    ]
    assert [alternate["airport"] for alternate in flight["alternates"]] == ["VMMC"]


def test_overflow_page_does_not_break_the_complete_page_sequence_proof():
    assert _complete_standard_lido_cfp_page_span(
        [PAGE1_HEAD, PAGE1_CONTINUATION, PAGE2]
    ) == (1, 2)


@pytest.mark.parametrize(
    "pages",
    [
        # Truncated upload: the declared second page never arrives.
        [PAGE1_HEAD, PAGE1_CONTINUATION],
        # A header-less page without the package footer is not a continuation.
        [PAGE1_HEAD, "ARBITRARY TEXT BLOB WITHOUT ANY LIDO MARKERS\n", PAGE2],
    ],
)
def test_page_sequence_proof_still_fails_closed(pages):
    assert _complete_standard_lido_cfp_page_span(pages) is None


def test_single_physical_page_layout_is_unchanged():
    single_page1 = PAGE1_HEAD.replace("Page 1 of 3\n", "") + PAGE1_CONTINUATION.replace(
        "Page 2 of 3\n", "Page 1 of 2\n"
    )
    flight = parse_lido([single_page1, PAGE2.replace("Page 3 of 3", "Page 2 of 2")], "single.pdf")
    assert flight["masses"]["planned_takeoff_weight_kg"] == 199155
    assert _complete_standard_lido_cfp_page_span(
        [single_page1, PAGE2.replace("Page 3 of 3", "Page 2 of 2")]
    ) == (1, 2)
