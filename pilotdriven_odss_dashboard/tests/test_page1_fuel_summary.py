"""CFP page-1 fuel and weight summary — parsed whole, verified arithmetically.

The boss's 07 Aug instruction: "this part has to be in. Page 1 of the CFP has
to be given more attention." The block is machine-printed by Lido with exact
internal arithmetic, so the parser proves every figure against every other
before anything is allowed to display it. A block that does not sum is
reported for review, never shown as numbers.

Both fixtures are real: SIA23 KJFK-WSSS (EDTO, tailwind, itemised excess) is
lifted verbatim from the held CFP PDF; SIA365 LIRF-WSSS (NON EDTO, headwind)
is the block the boss transcribed from his own flight's plan.
"""

from __future__ import annotations

from app.odss.parser import parse_page1_fuel_summary

SQ23_PAGE1 = """

OFP

PAGE  1 OF 21 SIA23 JFK/SIN 25JUL26

              SINGAPORE AIRLINES - SUMMARY EDTO CFP
              -------------------------------------
REMARKS:
T/O PERF CALCULATED WITH LPC: RTOW(PERF) 297.4T

EXCESS FUEL:
1.INTAM   3000KG  FUEL ALL FLEETS-9008 (SUBJ TO PAXLOAD)
2.FMC     0KG
3.MEL     0KG
4.TANKER  0KG
5.TMM     0KG
6.POLICY  0KG
7.OTHERS  0KG

                                             TIME   FUEL
GND  MILES    9197  CRZ COMP P025   BURNOFF  17.57  107027
AIR  MILES    8760                STAT CONT  00.08  000793
ALTN KUL (WMKK)                   ALTN FUEL  00.55  004680
                                  ALTN HOLD  00.30  002174
           TOP UP TO 60 MINS DEST HOLD FUEL  00.00  000000
                                EDTO TOP UP  00.00  000000
                                  TAXI FUEL         000600
PZFW 162326                  FLT PLAN REQMT  19.30  115274

PTOW 280000                     EXCESS FUEL  00.30  003000

PLWT 172973                   FUEL IN TANKS  20.00  118274
"""

SQ365_PAGE1 = """
PAGE  1 OF 18 SIA365 FCO/SIN 07AUG26

              SINGAPORE AIRLINES - SUMMARY NON EDTO CFP
              -----------------------------------------
GND MILES 5716 CRZ COMP M017 BURNOFF 12.08 072139
AIR MILES 5929 STAT CONT 00.08 000819
ALTN CIA (LIRA) ALTN FUEL 00.27 002454
ALTN HOLD 00.30 002256
TOP UP TO 60 MINS DEST HOLD FUEL 00.00 000000
EDTO TOP UP 00.00 000000
TAXI FUEL 000600
PZFW 167800 FLT PLAN REQMT 13.13 078268
PTOW 251868 EXCESS FUEL 01.05 006400
PLWT 179729 FUEL IN TANKS 14.17 084668
"""


def test_reads_the_full_edto_summary_block():
    summary = parse_page1_fuel_summary(SQ23_PAGE1)

    assert summary["state"] == "verified"
    assert summary["classification"] == "EDTO"
    assert summary["source_classification"] == "EDTO"
    assert summary["ground_miles_nm"] == 9197
    assert summary["air_miles_nm"] == 8760
    assert summary["cruise_wind_component_kt"] == 25
    assert summary["alternate"] == {"designator": "KUL", "icao": "WMKK"}
    assert summary["rows"]["burnoff"] == {"time_minutes": 17 * 60 + 57, "fuel_kg": 107027}
    assert summary["rows"]["stat_cont"] == {"time_minutes": 8, "fuel_kg": 793}
    assert summary["rows"]["altn_fuel"] == {"time_minutes": 55, "fuel_kg": 4680}
    assert summary["rows"]["altn_hold"] == {"time_minutes": 30, "fuel_kg": 2174}
    assert summary["rows"]["dest_hold_top_up"] == {"time_minutes": 0, "fuel_kg": 0}
    assert summary["rows"]["edto_top_up"] == {"time_minutes": 0, "fuel_kg": 0}
    assert summary["taxi_fuel_kg"] == 600
    assert summary["rows"]["flt_plan_reqmt"] == {"time_minutes": 19 * 60 + 30, "fuel_kg": 115274}
    assert summary["rows"]["excess_fuel"] == {"time_minutes": 30, "fuel_kg": 3000}
    assert summary["rows"]["fuel_in_tanks"] == {"time_minutes": 20 * 60, "fuel_kg": 118274}
    assert summary["masses_kg"] == {"pzfw": 162326, "ptow": 280000, "plwt": 172973}
    assert summary["discrepancies"] == []


def test_reads_the_non_edto_summary_with_headwind():
    summary = parse_page1_fuel_summary(SQ365_PAGE1)

    assert summary["state"] == "verified"
    assert summary["classification"] == "NON EDTO"
    assert summary["source_classification"] == "NON EDTO"
    assert summary["cruise_wind_component_kt"] == -17
    assert summary["alternate"] == {"designator": "CIA", "icao": "LIRA"}
    assert summary["rows"]["burnoff"]["fuel_kg"] == 72139
    assert summary["rows"]["fuel_in_tanks"] == {"time_minutes": 14 * 60 + 17, "fuel_kg": 84668}
    assert summary["masses_kg"] == {"pzfw": 167800, "ptow": 251868, "plwt": 179729}
    assert summary["discrepancies"] == []


def test_standard_summary_is_non_edto_without_rewriting_the_source_label():
    summary = parse_page1_fuel_summary(
        SQ365_PAGE1.replace("SUMMARY NON EDTO CFP", "SUMMARY STANDARD CFP")
    )

    assert summary["state"] == "verified"
    assert summary["classification"] == "NON EDTO"
    assert summary["source_classification"] == "STANDARD"


def test_excess_breakdown_is_kept_when_printed():
    summary = parse_page1_fuel_summary(SQ23_PAGE1)

    assert summary["excess_breakdown"][0] == {"label": "INTAM", "fuel_kg": 3000}
    assert {item["label"] for item in summary["excess_breakdown"]} == {
        "INTAM", "FMC", "MEL", "TANKER", "TMM", "POLICY", "OTHERS",
    }
    assert sum(item["fuel_kg"] for item in summary["excess_breakdown"]) == 3000


def test_every_arithmetic_identity_is_proved():
    summary = parse_page1_fuel_summary(SQ23_PAGE1)

    checks = {check["name"] for check in summary["checks"]}
    assert {
        "fuel_requirement_sum",
        "fuel_tanks_sum",
        "mass_landing_identity",
        "mass_takeoff_identity",
        "time_requirement_sum",
        "time_tanks_sum",
    } <= checks
    assert all(check["passed"] for check in summary["checks"])


def test_a_block_that_does_not_sum_is_review_required_not_displayed():
    corrupted = SQ23_PAGE1.replace("107027", "107028")
    summary = parse_page1_fuel_summary(corrupted)

    assert summary["state"] == "review_required"
    assert any("fuel_requirement_sum" in item for item in summary["discrepancies"])
    # The parsed figures remain available for the review trail, but the state
    # is the display gate: review_required must never render as numbers.
    assert summary["rows"]["burnoff"]["fuel_kg"] == 107028


def test_a_missing_core_row_is_review_required():
    truncated = SQ23_PAGE1.replace(
        "PZFW 162326                  FLT PLAN REQMT  19.30  115274", ""
    )
    summary = parse_page1_fuel_summary(truncated)

    assert summary["state"] == "review_required"
    assert any("flt_plan_reqmt" in item for item in summary["discrepancies"])


def test_a_page_without_the_block_returns_none():
    assert parse_page1_fuel_summary("ROUTE LOG ONLY\nNO SUMMARY HERE") is None


SQ365_FILED_PAGE1 = """
PAGE  1 OF 112 SIA365 FCO/SIN 07AUG26

              SINGAPORE AIRLINES - SUMMARY NON EDTO CFP
              -----------------------------------------
GND  MILES    5721  CRZ COMP P011   BURNOFF  11.26  070667
AIR  MILES    5601                STAT CONT  00.14  001425
ALTN QPG (WSAP)                   ALTN FUEL  00.21  002008
                                  ALTN HOLD  00.30  002347
           TOP UP TO 60 MINS DEST HOLD FUEL  00.00  000000
                                  TAXI FUEL         000600
PZFW 179478                  FLT PLAN REQMT  12.30  077047

PTOW 262125                     EXCESS FUEL  01.00  006200

PLWT 191458                   FUEL IN TANKS  13.31  083247
"""


def test_an_absent_top_up_line_is_conditional_print_not_a_defect():
    # SIA365's FILED CFP (verbatim): a NON EDTO plan omits the EDTO TOP UP
    # line entirely. Absence contributes zero to the sums and must verify.
    summary = parse_page1_fuel_summary(SQ365_FILED_PAGE1)

    assert summary["state"] == "verified"
    assert summary["rows"]["edto_top_up"] is None
    assert summary["discrepancies"] == []
    checks = {check["name"]: check["passed"] for check in summary["checks"]}
    assert checks["fuel_requirement_sum"] is True
    assert checks["time_requirement_sum"] is True
