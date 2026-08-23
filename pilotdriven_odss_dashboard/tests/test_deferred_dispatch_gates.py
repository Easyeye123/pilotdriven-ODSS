from __future__ import annotations

from copy import deepcopy

from app.odss.briefing import build_briefing_view
from app.odss.deferred_dispatch import (
    build_deferred_dispatch_gates,
    split_deferred_source_segments,
)
from app.odss.parser import parse_lido


def _parsed_flight() -> dict:
    page_one = (
        "SUMMARY STANDARD CFP\n"
        "9VAAA ZZ901 AAA/BBB ETD 0250 01AUG26\n"
        "SCHED DEP 0250 UTC SCHED ARR 0520 UTC\n"
        "RTE NO 001 A350-941 MH CAPT TEST PILOT\n"
        "AAAA/20\n"
        "DCT POINTA DCT POINTB\n"
        "BBBB/19\n"
        "GND MILES 900\n"
        "BURNOFF 02.00 010000\n"
        "TAXI FUEL 001000\n"
        "FLT PLAN REQMT 03.00 015000\n"
        "FUEL IN TANKS 04.00 020000\n"
        "PZFW 180000\n"
        "PTOW 200000\n"
        "PLWT 190000\n"
    )
    waypoint_log = (
        "POINTA       01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
        "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
        " \n"
        "POINTB       02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
        "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
    )
    return parse_lido(
        [page_one, "", "", "", "", "", waypoint_log],
        "synthetic-dispatch-gates.pdf",
    )


def test_nested_declarations_are_split_and_grouped_from_source_subjects() -> None:
    deferred_items = [
        {
            "item_type": "CDDL",
            "reference": "UNSPECIFIED",
            "description": "CABIN COMPACTOR, UNIT ONE, JAMMED",
            "company_remark": "USE SPARE LINER",
        },
        {
            "item_type": "CDDL",
            "reference": "UNSPECIFIED",
            "description": "CABIN COMPACTOR, UNIT TWO, NO POWER",
            "company_remark": "USE SPARE LINER",
        },
        {
            "item_type": "CDL",
            "reference": "10-10",
            "description": "LEFT WING PANEL SEAL DAMAGED",
            "company_remark": None,
        },
        {
            "item_type": "CDL",
            "reference": "20-20",
            "description": "RIGHT HINGED ACCESS DOOR SEAL DAMAGED",
            "company_remark": (
                "ZZ IN OPS/42 R3 BOTH CTRL (1A AND 1B) REMOVED. "
                "SYSB SYS NOT AVAILABLE. "
                "YY CDL 30-30 AFT LANDING GEAR DOOR SEAL MISSING"
            ),
        },
    ]
    untouched = deepcopy(deferred_items)

    gates = build_deferred_dispatch_gates(deferred_items)

    assert deferred_items == untouched
    assert [gate["title"] for gate in gates] == [
        "CABIN COMPACTORS",
        "CTRL / SYSB",
        "CDL 10-10",
        "CDL 20-20 / 30-30",
    ]
    assert gates[0]["source_item_indices"] == [0, 1]
    assert gates[0]["grouping_basis"] == "shared-source-subject"
    assert gates[1]["category"] == "operational-restriction"
    assert gates[1]["references"] == ["OPS/42 R3"]
    assert gates[3]["references"] == ["20-20", "30-30"]
    assert [
        segment["origin"] for segment in gates[3]["source_segments"]
    ] == ["parsed-item", "embedded-declaration"]
    assert gates[3]["source_segments"][1]["source_declaration"] == (
        "YY CDL 30-30"
    )
    assert gates[3]["source_segments"][1]["source_field"] == (
        "deferred_items[3].company_remark"
    )
    assert [
        row["title"]
        for gate in gates
        for row in gate["publication_rows"]
    ] == ["CDDL", "CDDL", "OPS/42 R3", "CDL 10-10", "CDL 20-20", "CDL 30-30"]


def test_unnumbered_cddl_uses_only_source_bounded_uplift_reference() -> None:
    gates = build_deferred_dispatch_gates([{
        "item_type": "CDDL",
        "reference": "UNSPECIFIED",
        "description": "CABIN COMPACTOR NO POWER",
        "company_remark": "212 UPLIFT TRASH BAG",
    }])

    assert gates[0]["publication_rows"][0]["title"] == "CDDL 212"
    assert gates[0]["publication_rows"][0]["reference"] == "212"


def test_bare_cddl_without_subject_uses_its_printed_declaration_not_placeholder() -> None:
    gates = build_deferred_dispatch_gates([{
        "item_type": "CDDL",
        "reference": "UNSPECIFIED",
        "source_declaration": "BB CDDL",
        "description": "",
        "company_remark": "",
    }])

    assert gates[0]["title"] == "BB CDDL"
    assert gates[0]["publication_rows"][0]["title"] == "CDDL"
    assert "UNSPECIFIED" not in str(gates[0])


def test_internal_only_unknown_declaration_never_becomes_a_pilot_gate() -> None:
    assert build_deferred_dispatch_gates([{
        "item_type": "UNCLASSIFIED",
        "reference": "UNSPECIFIED",
        "description": "",
        "company_remark": "",
    }]) == []

    gates = build_deferred_dispatch_gates([{
        "item_type": "UNCLASSIFIED",
        "reference": "IFEDDL",
        "description": "SEAT IFE AUDIO UNAVAILABLE",
        "company_remark": "",
    }])
    assert gates[0]["title"] == "DEFERRED ITEM IFEDDL"
    pilot_projection = {
        "title": gates[0]["title"],
        "summary": gates[0]["summary"],
        "references": gates[0]["references"],
        "publication_rows": gates[0]["publication_rows"],
    }
    assert "UNCLASSIFIED" not in str(pilot_projection)
    assert "UNSPECIFIED" not in str(pilot_projection)


def test_explicit_internal_declaration_never_becomes_a_pilot_gate_title() -> None:
    assert build_deferred_dispatch_gates([{
        "item_type": "UNCLASSIFIED",
        "reference": "UNSPECIFIED",
        "source_declaration": "UNCLASSIFIED UNSPECIFIED",
        "description": "",
        "company_remark": "",
    }]) == []

    raw_item = {
        "item_type": "UNCLASSIFIED",
        "reference": "UNSPECIFIED",
        "source_declaration": "AA UNCLASSIFIED UNSPECIFIED",
        "description": "SEAT IFE AUDIO UNAVAILABLE",
        "company_remark": "",
    }
    gates = build_deferred_dispatch_gates([raw_item])
    pilot_projection = {
        "title": gates[0]["title"],
        "summary": gates[0]["summary"],
        "references": gates[0]["references"],
        "publication_rows": gates[0]["publication_rows"],
    }
    assert "UNCLASSIFIED" not in str(pilot_projection)
    assert "UNSPECIFIED" not in str(pilot_projection)
    assert gates[0]["title"] != "AA"
    assert raw_item["source_declaration"] == "AA UNCLASSIFIED UNSPECIFIED"


def test_ambiguous_uppercase_prose_is_not_promoted_to_a_source_gate() -> None:
    deferred_items = [{
        "item_type": "MEL",
        "reference": "40-40",
        "description": "CABIN CONTROL RESTRICTION",
        "company_remark": "PROCEED TO IN CABIN MODE UNTIL MAINTENANCE REVIEW",
    }]

    segments = split_deferred_source_segments(deferred_items)

    assert len(segments) == 1
    assert segments[0]["origin"] == "parsed-item"
    assert segments[0]["restriction"] == deferred_items[0]["company_remark"]
    assert build_deferred_dispatch_gates(deferred_items)[0]["title"] == (
        "MEL 40-40"
    )


def test_source_segments_carry_crop_provenance_into_the_shared_view() -> None:
    deferred_items = [{
        "item_type": "CDL",
        "reference": "10-10",
        "source_declaration": "AA CDL 10-10",
        "source_page": 1,
        "description": "FORWARD SEAL DAMAGED",
        "company_remark": "ZZ IN OPS/42 R3 BOTH CTRL REMOVED",
    }, {
        "item_type": "MEL",
        "reference": "20-20",
        "source_declaration": "BB MEL 20-20",
        "source_page": 2,
        "description": "AFT SYSTEM INOPERATIVE",
        "company_remark": "",
    }]

    segments = split_deferred_source_segments(deferred_items)

    first_item_segments = [
        segment
        for segment in segments
        if segment["source_item_index"] == 0
    ]
    assert {segment["source_page"] for segment in first_item_segments} == {1}
    assert {
        segment["crop_end_needle"] for segment in first_item_segments
    } == {"BB MEL 20-20"}
    assert segments[-1]["source_page"] == 2
    assert segments[-1]["crop_end_needle"] == "PLAN"


def test_briefing_exposes_projection_without_replacing_raw_deferred_items() -> None:
    flight = _parsed_flight()
    flight["deferred_items"] = [{
        "item_type": "CDL",
        "reference": "50-50",
        "description": "FORWARD SERVICE DOOR SEAL DAMAGED",
        "company_remark": (
            "XX IN OPS/9 R2 BOTH CTRL REMOVED. "
            "WW CDL 60-60 AFT SERVICE DOOR SEAL MISSING"
        ),
    }]
    untouched = deepcopy(flight["deferred_items"])

    view = build_briefing_view(flight, [], [])

    assert flight["deferred_items"] == untouched
    assert [gate["title"] for gate in view["deferred_dispatch_gates"]] == [
        "CTRL",
        "CDL 50-50 / 60-60",
    ]
    for gate in view["deferred_dispatch_gates"]:
        assert gate["status"] == "dispatch-confirmation-required"
        assert gate["source_segments"]


def test_empty_source_has_no_synthetic_dispatch_gate() -> None:
    assert build_deferred_dispatch_gates([]) == []
    assert build_deferred_dispatch_gates(None) == []
