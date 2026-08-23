from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.odss.briefing import (
    _edto_classification,
    _edto_operational_rows,
    build_briefing_view,
)
from app.odss.combined_brief import _fuel_panel_rows
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


def test_edto_operational_rows_retain_real_edto_sector_and_fuel_facts() -> None:
    rows = _edto_operational_rows(
        "EDTO",
        {
            "assessment": {"status": "verified"},
            "sectors": [{
                "number": 1,
                "entry": "01.00",
                "exit": "02.00",
                "etps": ["01.30"],
                "etp_count": 1,
            }],
            "airports": [],
        },
        {
            "source_classification": "EDTO",
            "rows": {"edto_top_up": {"fuel_kg": 1_200}},
        },
    )

    labels = [label for label, _ in rows]
    assert labels == ["CLASSIFICATION", "SECTOR 1", "ETPS 1", "FUEL", "GATE"]
    assert ("FUEL", "EDTO top-up 1,200 kg.") in rows


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


@pytest.mark.parametrize(
    ("label", "fuel_kg", "operational_row"),
    [
        ("POLICY", 1_500, "POLICY · 00:17 | 1,500 kg"),
        ("TANKER", 18_847, "TANKER · 03:16 | 18,847 kg"),
    ],
)
def test_excess_mass_unit_accepts_the_bounded_operational_fuel_row(
    label: str,
    fuel_kg: int,
    operational_row: str,
) -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["fuel_summary"]["excess_breakdown"] = [
        {"label": label, "fuel_kg": fuel_kg}
    ]
    text = _passing_text(flight).replace(f"\n{label} {fuel_kg:,} kg", "")

    result = check_cross_surface_parity(
        flight,
        [],
        [],
        text,
        unit_output_text=operational_row,
    )

    assert result["valid"], result["failures"]


def test_excess_mass_unit_still_rejects_a_unitless_operational_fuel_row() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["fuel_summary"]["excess_breakdown"] = [
        {"label": "POLICY", "fuel_kg": 1_500}
    ]
    text = _passing_text(flight).replace("\nPOLICY 1,500 kg", "")

    result = check_cross_surface_parity(
        flight,
        [],
        [],
        text,
        unit_output_text="POLICY · 00:17 | 1,500",
    )

    assert not result["valid"]
    assert any("units" in failure for failure in result["failures"])


def test_excess_mass_unit_accepts_each_item_in_one_allocation_row() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["fuel_summary"]["excess_breakdown"] = [
        {"label": "INTAM", "fuel_kg": 3_200},
        {"label": "TMM", "fuel_kg": 3_200},
    ]
    text = _passing_text(flight)
    text = text.replace("\nINTAM 3,200 kg", "")
    text = text.replace("\nTMM 3,200 kg", "")

    result = check_cross_surface_parity(
        flight,
        [],
        [],
        text,
        unit_output_text="ALLOCATION · INTAM 3,200 kg + TMM 3,200 kg",
    )

    assert result["valid"], result["failures"]


@pytest.mark.parametrize(
    "operational_row",
    [
        "ALLOCATION · INTAM 3,200 + TMM 3,200 kg",
        "ALLOCATION · INTAM 3,100 kg + TMM 3,200 kg",
        "ALLOCATION · FMC 3,200 kg + TMM 3,200 kg",
        "ALLOCATION · INTAM\n3,200 kg + TMM 3,200 kg",
    ],
)
def test_excess_allocation_row_rejects_missing_or_cross_row_mass_evidence(
    operational_row: str,
) -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["fuel_summary"]["excess_breakdown"] = [
        {"label": "INTAM", "fuel_kg": 3_200},
        {"label": "TMM", "fuel_kg": 3_200},
    ]
    text = _passing_text(flight)
    text = text.replace("\nINTAM 3,200 kg", "")
    text = text.replace("\nTMM 3,200 kg", "")

    result = check_cross_surface_parity(
        flight,
        [],
        [],
        text,
        unit_output_text=operational_row,
    )

    assert not result["valid"]
    assert any("units" in failure for failure in result["failures"])


def test_operational_fuel_rows_preserve_single_source_allocation_label() -> None:
    rows = _fuel_panel_rows({
        "rows": {
            "excess_fuel": {"time_minutes": 17, "fuel_kg": 1_500},
        },
        "excess_breakdown": [{"label": "POLICY", "fuel_kg": 1_500}],
    })

    assert ("POLICY", "00:17 | 1,500 kg") in rows
    assert not any(label == "EXCESS" for label, _ in rows)


def test_operational_fuel_rows_keep_each_mixed_allocation_with_kg() -> None:
    rows = _fuel_panel_rows({
        "rows": {
            "excess_fuel": {"time_minutes": 17, "fuel_kg": 1_500},
        },
        "excess_breakdown": [
            {"label": "POLICY", "fuel_kg": 1_000},
            {"label": "TANKER", "fuel_kg": 500},
        ],
    })

    assert ("EXCESS", "00:17 | 1,500 kg") in rows
    assert ("ALLOCATION", "POLICY 1,000 kg + TANKER 500 kg") in rows


def test_banned_wording_fails() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = _passing_text(flight) + "\nLEVEL 2"
    result = check_cross_surface_parity(flight, [], [], text)
    assert not result["valid"]
    assert any("naming" in failure for failure in result["failures"])


def test_level_wording_inside_source_fact_is_not_a_retired_layout_label() -> None:
    flight = _flight(LOG_PAGE_LOW)
    text = (
        _passing_text(flight)
        + "\nILS RWY 08R DOWNGRADED TO CAT I, LEVEL 2 "
        "(ICAO CLASSIFICATION I/E/2)."
    )

    result = check_cross_surface_parity(flight, [], [], text)

    assert result["valid"], result["failures"]


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
    derived = next(
        item["derived"]
        for item in build_briefing_view(flight, [], [])["vaa"]["cfp_advisories"]
        if item.get("advisory_kind") == "VA_SIGMET"
    )
    result_ok = check_cross_surface_parity(
        flight,
        [],
        [],
        named + "\n" + derived,
    )
    assert result_ok["valid"], result_ok["failures"]


def test_cfp_vaa_parity_uses_operational_atomic_identity_and_derived_line() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["volcanic_advisories"] = [{
        "volcano": "MAYON",
        "notam_id": "1B4235/26",
        "text": "MAYON VOLCANO ON ALERT LEVEL 2.",
        "source_page": 34,
    }]
    audit_text = (
        _passing_text(flight)
        + "\nCFP VOLCANO ADVISORY · MAYON · 1B4235/26"
    )
    derived = (
        "Source-held CFP notice; operational applicability remains "
        "a crew/dispatch review."
    )
    operational_text = f"MAYON · 1B4235/26\n{derived}"

    passed = check_cross_surface_parity(
        flight,
        [],
        [],
        audit_text,
        unit_output_text=operational_text,
    )
    assert passed["valid"], passed["failures"]

    missing_identity = check_cross_surface_parity(
        flight,
        [],
        [],
        audit_text,
        unit_output_text=f"MAYON\n{derived}",
    )
    assert not missing_identity["valid"]
    assert any("advisory identity" in row for row in missing_identity["failures"])

    missing_derived = check_cross_surface_parity(
        flight,
        [],
        [],
        audit_text,
        unit_output_text="MAYON · 1B4235/26",
    )
    assert not missing_derived["valid"]
    assert any("derived applicability" in row for row in missing_derived["failures"])


def _extraction_flight() -> dict:
    return {
        "notams": [
            {"location": "WSSS", "notam_id": "A0001/26"},
            {"location": "WSSS", "notam_id": "A0002/26"},
            {"location": "WMKK", "notam_id": "A0003/26"},
        ],
        "weather": [
            {
                "record_type": "METAR",
                "location": "WSSS",
                "source_page": 10,
                "text": "SA SOURCE ONE",
            },
            {
                "record_type": "TAF",
                "location": "WSSS",
                "source_page": 11,
                "text": "FT SOURCE TWO",
            },
            {
                "record_type": "SIGMET",
                "location": "WSJC",
                "source_page": 12,
                "text": "WS SOURCE THREE",
            },
            {
                "record_type": "METAR",
                "location": "WSSS",
                "source_page": None,
                "text": "LIVE RECORD MUST NOT ENTER THE PIN",
                "source": "noaa_awc_live",
            },
        ],
        "alternates": [
            {"airport": "WSAP"},
            {"airport": "WMKK"},
            {"airport": "WIII"},
        ],
        "deferred_items": [
            {"item_type": "MEL", "reference": "21-01-01"},
            {"item_type": "CDL", "reference": "32-02-02"},
            {"item_type": "MEL", "reference": "34-03-03"},
        ],
        "edto": {
            "sectors": [{"number": 1}, {"number": 2}, {"number": 3}],
            "airports": [
                {"airport": "WADD"},
                {"airport": "WIII"},
                {"airport": "VYYY"},
            ],
        },
        "fuel_enroute_airports": [
            {"airport": "WIII"},
            {"airport": "WADD"},
            {"airport": "VYYY"},
        ],
        "route_waypoints": [
            {"name": "ALPHA", "airway_in": "DCT", "msa_hundreds_ft": 30},
            {"name": "BRAVO", "airway_in": "A1", "msa_hundreds_ft": 40},
            {"name": "CHARLIE", "airway_in": "B2", "msa_hundreds_ft": 50},
        ],
    }


def _extraction_expectation(flight: dict) -> dict:
    from scripts.run_private_cfp_corpus import build_extraction_snapshot

    snapshot = build_extraction_snapshot(flight)
    assert snapshot["structure_failures"] == []
    return {
        "counts": snapshot["counts"],
        "identity_sha256": snapshot["identity_sha256"],
    }


def test_extraction_digest_has_a_fixed_canonical_json_vector() -> None:
    from scripts.run_private_cfp_corpus import _record_digest

    assert _record_digest([{"b": 2, "a": 1}]) == (
        "44c7deead2ed8313d29655e45c0d1469419213c93d9f44d66da7c7afe46e74e3"
    )


def test_extraction_weather_pin_excludes_live_noaa_awc() -> None:
    from scripts.run_private_cfp_corpus import build_extraction_snapshot

    with_live = _extraction_flight()
    without_live = deepcopy(with_live)
    without_live["weather"].pop()

    assert build_extraction_snapshot(with_live) == build_extraction_snapshot(without_live)
    assert build_extraction_snapshot(with_live)["counts"]["weather"] == 3


@pytest.mark.parametrize(
    ("container", "field", "failure_path"),
    [
        ("flight", "notams", "notams"),
        ("flight", "weather", "weather"),
        ("flight", "alternates", "alternates"),
        ("flight", "deferred_items", "deferred_items"),
        ("edto", "sectors", "edto.sectors"),
        ("edto", "airports", "edto.airports"),
        ("flight", "fuel_enroute_airports", "fuel_enroute_airports"),
        ("flight", "route_waypoints", "route_waypoints"),
    ],
)
def test_extraction_contract_rejects_a_missing_whole_domain(
    container: str,
    field: str,
    failure_path: str,
) -> None:
    from scripts.run_private_cfp_corpus import check_extraction_expectations

    flight = _extraction_flight()
    expected = _extraction_expectation(flight)
    changed = deepcopy(flight)
    target = changed if container == "flight" else changed["edto"]
    del target[field]

    result = check_extraction_expectations(changed, expected)

    assert result["valid"] is False
    assert f"{failure_path} is missing" in result["failures"]


def test_extraction_contract_rejects_removed_middle_row_and_duplicate_replacement() -> None:
    from scripts.run_private_cfp_corpus import check_extraction_expectations

    flight = _extraction_flight()
    expected = _extraction_expectation(flight)
    changed = deepcopy(flight)
    changed["notams"].pop(1)
    changed["notams"].append(deepcopy(changed["notams"][-1]))

    result = check_extraction_expectations(changed, expected)

    assert result["valid"] is False
    assert not any("notams.count" in failure for failure in result["failures"])
    assert "notams.identity_sha256 changed" in result["failures"]


def test_extraction_contract_hashes_weather_raw_text_without_storing_it() -> None:
    from scripts.run_private_cfp_corpus import check_extraction_expectations

    flight = _extraction_flight()
    expected = _extraction_expectation(flight)
    changed = deepcopy(flight)
    changed["weather"][1]["text"] = "FT SOURCE TWO CHANGED"

    result = check_extraction_expectations(changed, expected)

    assert result["valid"] is False
    assert result["failures"] == ["weather.identity_sha256 changed"]


def test_extraction_contract_hashes_full_waypoint_record_not_only_route_identity() -> None:
    from scripts.run_private_cfp_corpus import check_extraction_expectations

    flight = _extraction_flight()
    expected = _extraction_expectation(flight)
    changed = deepcopy(flight)
    changed["route_waypoints"][1]["msa_hundreds_ft"] = 41

    result = check_extraction_expectations(changed, expected)

    assert result["valid"] is False
    assert result["failures"] == ["route_waypoints.identity_sha256 changed"]


def test_manifest_requires_static_extraction_expectations_for_every_case(
    tmp_path: Path,
) -> None:
    from scripts.run_private_cfp_corpus import DEFAULT_MANIFEST, load_manifest

    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["cases"][0].pop("extraction_expectations")
    malformed = tmp_path / "missing-extraction-expectations.json"
    malformed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="case is incomplete"):
        load_manifest(malformed)


def test_parsed_fact_coverage_catches_a_dropped_fact() -> None:
    # The exact regression class this gate exists for: the parser held the
    # EDTO minima but no surface printed it (deploys #1-#19).
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    flight = {
        "edto": {"airports": [{"airport": "WADD", "runway": "27", "approach": "CAT1DME", "minima": "453FT/1900M"}]},
        "captain": "CHAN K B DAVID",
        "registration": "9VSHB",
        "route_text": "YPPH/21 DCT AVNEX Q11 TESAT",
        "cost_index": 70,
    }
    text_with = "WADD/27 | CAT1DME | 453FT/1900M CHAN K B DAVID 9V-SHB YPPH/21 DCT AVNEX Q11 TESAT"
    ok = check_parsed_fact_coverage(flight, text_with)
    assert ok["valid"], ok["missing"]

    text_without = text_with.replace("453FT/1900M", "")
    bad = check_parsed_fact_coverage(flight, text_without)
    assert not bad["valid"]
    assert any("minima" in item for item in bad["missing"])


def test_parsed_fact_coverage_normalises_times_wraps_and_registrations() -> None:
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    flight = {
        "fuel_summary": {"rows": {"burnoff": {"fuel_kg": 28711, "time_minutes": 298}}},
        "registration": "9VSHY",
        "planned_level_profile": "SIN/340/GUGIT/360/IGONA/380/LEMOD/380/DOH",
    }
    # burnoff prints as 28,711/4:58; the registration prints hyphenated; the
    # profile wraps across lines (a space appears mid-chain in extracted text).
    text = "BURNOFF 28,711/4:58 REG 9V-SHY SIN/340/GUGIT/360/ IGONA/380/LEMOD/380/DOH"
    result = check_parsed_fact_coverage(flight, text)
    assert result["valid"], result["missing"]


def test_parsed_fact_coverage_accepts_a_fact_on_either_pdf_surface() -> None:
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    flight = {
        "fuel_summary": {
            "derived_fuel_kg": {"takeoff": 43_291, "landing": 23_924},
        },
    }
    audit_text = "FROZEN AUDIT FUEL TABLE"
    operational_text = "DERIVED T/O FUEL 43,291 KG / LDG FUEL 23,924 KG"

    paired = check_parsed_fact_coverage(
        flight,
        audit_text,
        operational_output_text=operational_text,
    )
    assert paired["valid"], paired["missing"]

    audit_only = check_parsed_fact_coverage(flight, audit_text)
    assert not audit_only["valid"]
    assert any(
        "derived_fuel_kg.takeoff" in row for row in audit_only["missing"]
    )

    missing_from_both = check_parsed_fact_coverage(
        flight,
        "FROZEN AUDIT T/O FUEL 43,291 KG",
        operational_output_text="OPERATIONAL FUEL TABLE",
    )
    assert not missing_from_both["valid"]
    assert any(
        "derived_fuel_kg.landing" in row
        for row in missing_from_both["missing"]
    )


def test_long_route_fact_accepts_visible_ordered_tokens_across_page_chrome() -> None:
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    route_tokens = [f"RTE{index:03d}" for index in range(1, 81)]
    flight = {"route_text": " ".join(route_tokens)}
    visible_text = (
        "CFP ROUTE "
        + " ".join(route_tokens[:40])
        + " PAGE 2 OF 2 AIRPORTS CONTINUED SOURCE "
        + " ".join(route_tokens[40:])
    )

    passed = check_parsed_fact_coverage(flight, visible_text)
    assert passed["valid"], passed["missing"]

    missing_token = visible_text.replace("RTE057", "MISSING", 1)
    failed = check_parsed_fact_coverage(flight, missing_token)
    assert not failed["valid"]
    assert any("route_text" in item for item in failed["missing"])


def test_fact_waivers_are_explained_and_limited_to_non_operational_metadata() -> None:
    from scripts.run_private_cfp_corpus import FACT_WAIVERS

    for path, reason in FACT_WAIVERS.items():
        assert len(reason.strip()) >= 15, f"waiver for {path} needs a real reason"
        assert not path.startswith(("alternates", "performance.", "fuel.", "deferred_items[]")), (
            f"pilot-visible operational fact cannot be waived: {path}"
        )
        assert not path.startswith("fuel_summary.rows."), (
            f"pilot-visible fuel row cannot be waived: {path}"
        )
        assert not path.startswith("fuel_summary.excess_breakdown"), (
            f"pilot-visible excess-fuel fact cannot be waived: {path}"
        )


def test_pdf_fact_coverage_requires_every_alternate() -> None:
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    flight = {
        "alternates": [
            {"airport": "WSAP", "runway": "20", "approach": "CAT1DME", "minima": "3000FT/5000M"},
            {"airport": "WMKK", "runway": "14L", "approach": "LOCDME", "minima": "446FT/1400M"},
        ],
    }
    preferred_only = "WSAP RWY 20 CAT1DME 3000FT/5000M"
    result = check_parsed_fact_coverage(flight, preferred_only)
    assert not result["valid"]
    assert any("WMKK" in item for item in result["missing"])

    complete = check_parsed_fact_coverage(
        flight,
        preferred_only + " WMKK RWY 14L LOCDME 446FT/1400M",
    )
    assert complete["valid"], complete["missing"]


def test_pdf_fact_coverage_rejects_performance_fuel_and_deferred_omissions() -> None:
    from scripts.run_private_cfp_corpus import check_parsed_fact_coverage

    flight = {
        "performance": {
            "runway": "20C",
            "runway_condition": "DRY",
            "thrust_setting": "TOGA/FLEX(STD)",
            "qnh_hpa": 1021,
            "wind": "180/10KT",
            "packs_on": True,
            "anti_ice_on": False,
            "eosid": "STRAIGHT OUT",
            "obstacle_rtow_kg": 297400,
            "landing_rtow_kg": 312027,
            "structural_rtow_kg": 280000,
            "maximum_fuel_available_kg": 50000,
        },
        "fuel": {"planned_destination_fuel_kg": 9316},
        "fuel_summary": {
            "rows": {
                "fuel_in_tanks": {"time_minutes": 320, "fuel_kg": 45000},
                "excess_fuel": {"time_minutes": 45, "fuel_kg": 3000},
                "dest_hold_top_up": {"time_minutes": 30, "fuel_kg": 1000},
                "edto_top_up": {"time_minutes": 15, "fuel_kg": 500},
            },
            "excess_breakdown": [{"label": "POLICY", "fuel_kg": 1500}],
        },
        "deferred_items": [{
            "item_type": "MEL",
            "reference": "21-01-01",
            "description": "PACK FLOW CONTROL VALVE INOPERATIVE",
            "company_remark": "APPLY THE CFP OPERATING RESTRICTION",
        }],
    }
    complete_text = " ".join([
        "RWY 20C DRY TOGA/FLEX(STD) QNH 1021 WIND 180/10KT",
        "PACKS / ANTI-ICE ON / OFF EOSID STRAIGHT OUT",
        "RTOW PERF 297,400 RTOW LAND 312,027 RTOW STRUCT 280,000 MAX FUEL 50,000",
        "PLANNED DESTINATION FUEL 9,316",
        "FUEL IN TANKS 45,000 05.20 EXCESS 3,000 00.45",
        "DEST HOLD TOP UP 1,000 00.30 EDTO TOP UP 500 00.15",
        "EXCESS ALLOCATION POLICY 1,500",
        "MEL 21-01-01 PACK FLOW CONTROL VALVE INOPERATIVE",
        "APPLY THE CFP OPERATING RESTRICTION",
    ])

    complete = check_parsed_fact_coverage(flight, complete_text)
    assert complete["valid"], complete["missing"]

    omissions = [
        ("STRAIGHT OUT", "performance.eosid"),
        ("297,400", "performance.obstacle_rtow_kg"),
        ("PACKS / ANTI-ICE ON / OFF", "performance.packs_on"),
        ("9,316", "fuel.planned_destination_fuel_kg"),
        ("POLICY", "fuel_summary.excess_breakdown[].label"),
        ("APPLY THE CFP OPERATING RESTRICTION", "deferred_items[].company_remark"),
    ]
    for token, expected_path in omissions:
        incomplete = complete_text.replace(token, "", 1)
        result = check_parsed_fact_coverage(flight, incomplete)
        assert not result["valid"], f"omitting {expected_path} must fail PDF coverage"
        assert any(expected_path in item for item in result["missing"]), result["missing"]


def test_pdf_renderer_raw_flight_reads_only_shrink() -> None:
    # Renderer purity: content composed from raw `flight` data inside the PDF
    # renderer is invisible to the dashboard (the VAAC reach leaked this way,
    # deploy #20). New content goes through build_briefing_view, where every
    # surface inherits it - so this count may fall but never rise.
    import ast
    import re
    from pathlib import Path

    source = Path("app/odss/combined_brief.py").read_text(encoding="utf-8")
    # The explicit REV3-v8 audit compatibility functions reproduce an
    # immutable historical renderer and are separately guarded by exact
    # raster equality.  They do not compose new product content, so exclude
    # only those named functions from this current-surface purity budget.
    source_lines = source.splitlines(keepends=True)
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.FunctionDef)
            and "audit_rev3_v8" in node.name
        ):
            source_lines[node.lineno - 1:node.end_lineno] = [
                "\n" for _ in range(node.lineno - 1, node.end_lineno)
            ]
    current_renderer_source = "".join(source_lines)
    count = len(
        re.findall(r"flight\.get\(|flight\[", current_renderer_source)
    )
    assert count <= 83, (
        f"combined_brief.py now reads raw flight data {count} times (baseline 83). "
        "Compose the new content in build_briefing_view instead, so the dashboard "
        "prints it too."
    )
