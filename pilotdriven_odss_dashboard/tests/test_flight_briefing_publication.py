from __future__ import annotations

from copy import deepcopy

import pytest

from app.odss.flight_briefing_publication import (
    FlightBriefingPublicationError,
    build_combined_report_plan,
    build_flight_briefing_filename,
    deduplicate_findings_for_combined_report,
    validate_flight_briefing_publication,
)


def _flight() -> dict:
    return {
        "flight_number": "SQ365",
        "flight_date": "07 AUG 2026",
        "departure": "LIRF",
        "destination": "WSSS",
        "bobcat": {"waypoint": "BIROS"},
        "edto": {},
        "depressurisation_profile_charts": [
            {
                "chart_number": "8-3",
                "source_document": "Synthetic A350 Depressurisation Profiles",
                "source_revision": "TEST REV",
                "source_page": 210,
                "source_link": "helpyou://synthetic/depressurisation/8-3",
                "crop_box": [42, 88, 760, 518],
                "route_airway_match_verified": True,
                "aircraft_effectivity_verified": True,
                "chart_image_validated": True,
                "combined_analysis_chart_embedded": True,
                "combined_cropped_source_chart_embedded": True,
            }
        ],
    }


def _findings() -> list[dict]:
    return [
        {"finding_id": "page1", "engine": "page1", "title": "CFP Page 1", "details": []},
        {"finding_id": "perf", "engine": "performance", "title": "Performance", "details": []},
        {"finding_id": "cddl", "engine": "cddl", "title": "CDDL", "details": []},
        {"finding_id": "cdl", "engine": "cdl", "title": "CDL 38-05", "details": []},
        {"finding_id": "notam", "engine": "notam", "title": "Airport NOTAM", "details": []},
        {"finding_id": "bobcat", "engine": "bobcat", "title": "BOBCAT", "details": []},
        {"finding_id": "comm", "engine": "communications", "title": "FIR contact", "details": []},
        {"finding_id": "wx", "engine": "weather", "title": "SIGMET review", "details": []},
        {"finding_id": "vaa", "engine": "vaa", "title": "VA review", "details": []},
        {"finding_id": "terrain", "engine": "terrain", "title": "High Terrain Exposure", "details": []},
        {
            "finding_id": "profile-8-3",
            "engine": "depressurisation",
            "title": "Profile 8-3",
            "details": [],
            "data": {"chart_number": "8-3"},
        },
    ]


def _gate(category: str, target: str) -> dict:
    return {
        "category": category,
        "label": category,
        "target": target,
        "link_resolves": True,
    }


def _hazard_finding() -> dict:
    return {
        "product_type": "SIGMET",
        "issuer": "TEST MWO",
        "issue_time_utc": "2026-08-07T04:07:00Z",
        "valid_from_utc": "2026-08-07T04:07:00Z",
        "valid_to_utc": "2026-08-07T10:00:00Z",
        "phenomenon": "VA CLD",
        "observation_status": "OBS",
        "intensity": "not specified by issuing authority",
        "position": {"type": "Polygon", "coordinates": [[1, 2], [3, 4], [5, 6]]},
        "vertical_extent": "SFC/FL240",
        "movement": "SE 10KT",
        "trend": "NC",
        "route_relationship": "No intersection with filed departure route",
        "time_relationship": "Closest passage after validity",
        "level_relationship": "No route/level intersection",
        "operational_consequence": "No route consequence from this product",
        "classification": "NOT_PROMOTED",
        "reason_codes": ["NO_HORIZONTAL_INTERSECTION", "NOT_VALID_AT_PROJECTED_CROSSING"],
        "source_id": "SRC-SIGMET-TEST",
    }


def _manifest() -> dict:
    destinations = [
        "evidence_performance_fuel",
        "evidence_mel_cdl",
        "evidence_airports",
        "evidence_communications",
        "evidence_hazards",
        "evidence_terrain_depressurisation",
        "source_crops",
    ]
    return {
        "protocol_version": "1.3.0",
        "report": {
            "mode": "combined",
            "filename": "SQ365_07AUG2026_Flight_Briefing.pdf",
            "title": "SQ365 — 07 AUG 2026 — Flight Briefing",
            "section_titles": [
                "FLIGHT BRIEFING",
                "PERFORMANCE / FUEL",
                "MEL / CDL / CDDL",
                "AIRPORTS / NOTAM",
                "OPERATIONAL HAZARD ASSESSMENT",
                "HIGH TERRAIN / DEPRESSURISATION",
            ],
            "user_facing_text": ["Flight-specific operational information"],
            "full_cfp_appended": False,
            "full_cfp_embedded": False,
            "embedded_files": [],
        },
        "layout": {
            "page_format": "A4 landscape",
            "detail_font_scale": 1.2,
            "minimum_detail_font_pt": 8.4,
            "minimum_numeric_font_pt": 8.4,
            "text_overlap_count": 0,
            "clipped_text_count": 0,
            "page1": {
                "information_side": "left",
                "map_side": "right",
                "logo": {
                    "asset_id": "pilotdriven-forward-wing-v1",
                    "asset_hash": "sha256:test",
                    "uses_x_mark": False,
                },
                "airport_cards": [
                    {
                        "role": role,
                        "width": 178.0,
                        "height": 92.0,
                        "horizontal_alignment": "left",
                        "vertical_alignment": "middle",
                    }
                    for role in ("departure", "destination", "alternate")
                ],
            },
        },
        "page1_critical_items": {
            "flight_identity": True,
            "route_and_runway": True,
            "schedule_and_block_time": True,
            "aircraft_type_and_registration": True,
            "distance_and_cruise_component": True,
            "burnoff_and_statistical_contingency": True,
            "preferred_alternate_and_weather": True,
            "planned_masses": True,
            "flight_plan_requirement": True,
            "fuel_in_tanks": True,
            "excess_fuel_and_allocation": True,
            "mel_cdl_cddl": True,
            "flow_allocation_when_present": True,
        },
        "evidence_destinations": destinations,
        "decision_gates": [
            _gate("BOBCAT", "evidence_communications"),
            _gate("MEL/CDL", "evidence_mel_cdl"),
            _gate("TERRAIN/DEPRESS", "evidence_terrain_depressurisation"),
            _gate("SIGMET/HAZARDS", "evidence_hazards"),
            _gate("AIRPORTS", "evidence_airports"),
            _gate("PERFORMANCE/FUEL", "evidence_performance_fuel"),
            _gate("FIR/COMMUNICATIONS", "evidence_communications"),
        ],
        "source_crops": [
            {
                "category": "MEL/CDL",
                "source_document": "Synthetic CDL",
                "source_revision_or_effective_date": "eff 05.05.26",
                "source_reference": "38-05",
                "source_page": "339",
                "crop_box": [40, 70, 760, 440],
                "embedded": True,
                "link_target": "source_crops",
            },
            {
                "category": "DEPRESSURISATION",
                "source_document": "Synthetic A350 Depressurisation Profiles",
                "source_revision_or_effective_date": "TEST REV",
                "source_reference": "Profile 8-3",
                "source_page": "210",
                "crop_box": [42, 88, 760, 518],
                "embedded": True,
                "link_target": "source_crops",
            },
        ],
        "facts": [
            {"fact_id": "fuel.ptow", "location": "flight_overview", "primary": True},
            {"fact_id": "fuel.ptow", "location": "evidence_performance_fuel", "primary": False},
            {"fact_id": "cdl.38-05", "location": "evidence_mel_cdl", "primary": True},
        ],
        "hazard_assessment": {
            "nil_inference": False,
            "products_reviewed": [
                {
                    "product_class": "VOLCANIC_ASH_SIGMET",
                    "source_id": "SRC-SIGMET-TEST",
                }
            ],
            "coverage_gaps": [
                {
                    "product_class": "CLEAR_AIR_TURBULENCE",
                    "reason": "No authoritative CAT product in the synthetic package",
                    "interpreted_as_nil": False,
                }
            ],
            "findings": [_hazard_finding()],
        },
        "release_checks": {
            "airport_card_geometry": True,
            "decision_gate_links": True,
            "source_crops": True,
            "fact_deduplication": True,
            "hazard_completeness": True,
            "source_link_integrity": True,
            "visual_preflight": True,
        },
    }


def _codes(error: FlightBriefingPublicationError) -> set[str]:
    return {item["code"] for item in error.violations}


def test_filename_uses_flight_date_and_flight_briefing_title() -> None:
    assert build_flight_briefing_filename(_flight()) == "SQ365_07AUG2026_Flight_Briefing.pdf"


def test_valid_combined_publication_contract_passes() -> None:
    assert validate_flight_briefing_publication(_flight(), _findings(), _manifest()) == []


def test_prohibited_level_and_pertinent_terms_fail() -> None:
    manifest = _manifest()
    manifest["report"]["section_titles"].append("Level 1 Pertinent Brief")
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert "PROHIBITED_REPORT_TERMINOLOGY" in _codes(captured.value)


def test_full_cfp_appendix_or_attachment_fails() -> None:
    manifest = _manifest()
    manifest["report"]["full_cfp_appended"] = True
    manifest["report"]["embedded_files"] = [{"type": "lido_cfp"}]
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {"FULL_CFP_APPENDED", "FULL_CFP_ATTACHMENT_PRESENT"}.issubset(_codes(captured.value))


def test_page1_information_left_and_map_right_are_mandatory() -> None:
    manifest = _manifest()
    manifest["layout"]["page1"]["information_side"] = "right"
    manifest["layout"]["page1"]["map_side"] = "left"
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {
        "PAGE1_INFORMATION_SIDE_INVALID",
        "PAGE1_MAP_SIDE_INVALID",
    }.issubset(_codes(captured.value))


def test_airport_cards_must_have_equal_geometry_and_middle_alignment() -> None:
    manifest = _manifest()
    cards = manifest["layout"]["page1"]["airport_cards"]
    cards[2]["height"] = 99.0
    cards[1]["vertical_alignment"] = "bottom"
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {
        "AIRPORT_CARD_GEOMETRY_UNEQUAL",
        "AIRPORT_CARD_VERTICAL_ALIGNMENT_INVALID",
    }.issubset(_codes(captured.value))


def test_detail_and_numeric_fonts_must_be_twenty_percent_larger() -> None:
    manifest = _manifest()
    manifest["layout"]["detail_font_scale"] = 1.1
    manifest["layout"]["minimum_numeric_font_pt"] = 8.0
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {
        "DETAIL_FONT_SCALE_TOO_SMALL",
        "MINIMUM_FONT_SIZE_TOO_SMALL",
    }.issubset(_codes(captured.value))


def test_x_logo_is_rejected() -> None:
    manifest = _manifest()
    manifest["layout"]["page1"]["logo"]["uses_x_mark"] = True
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert "PILOTDRIVEN_X_LOGO_PROHIBITED" in _codes(captured.value)


def test_decision_gates_require_valid_evidence_links_and_no_tech_label() -> None:
    manifest = _manifest()
    gate = next(item for item in manifest["decision_gates"] if item["category"] == "MEL/CDL")
    gate["label"] = "TECH"
    gate["link_resolves"] = False
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {
        "TECH_LABEL_PROHIBITED",
        "DECISION_GATE_LINK_INVALID",
    }.issubset(_codes(captured.value))


def test_required_mel_and_depressurisation_source_crops_fail_closed() -> None:
    manifest = _manifest()
    manifest["source_crops"] = []
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert "REQUIRED_SOURCE_CROP_MISSING" in _codes(captured.value)


def test_matched_profile_requires_combined_analysis_and_cropped_chart() -> None:
    flight = _flight()
    flight["depressurisation_profile_charts"][0]["combined_cropped_source_chart_embedded"] = False
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(flight, _findings(), _manifest())
    assert "DEPRESSURISATION_PROFILE_VALIDATION_INCOMPLETE" in _codes(captured.value)


def test_each_fact_has_exactly_one_primary_location() -> None:
    manifest = _manifest()
    manifest["facts"][1]["primary"] = True
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert "FACT_PRIMARY_LOCATION_INVALID" in _codes(captured.value)


def test_hazard_findings_require_exact_fields_and_gaps_never_mean_nil() -> None:
    manifest = _manifest()
    del manifest["hazard_assessment"]["findings"][0]["position"]
    manifest["hazard_assessment"]["coverage_gaps"][0]["interpreted_as_nil"] = True
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert {
        "HAZARD_FINDING_FIELD_MISSING",
        "HAZARD_COVERAGE_GAP_INTERPRETED_AS_NIL",
    }.issubset(_codes(captured.value))


def test_sq365_page1_overlap_regression_is_a_release_failure() -> None:
    manifest = _manifest()
    manifest["layout"]["text_overlap_count"] = 2
    with pytest.raises(FlightBriefingPublicationError) as captured:
        validate_flight_briefing_publication(_flight(), _findings(), manifest)
    assert "TEXT_OVERLAP_DETECTED" in _codes(captured.value)


def test_non_edto_flight_does_not_require_an_edto_source_crop() -> None:
    manifest = _manifest()
    assert all(item["category"] != "EDTO" for item in manifest["source_crops"])
    assert validate_flight_briefing_publication(_flight(), _findings(), manifest) == []


def test_deduplication_keeps_one_primary_finding_and_merges_support() -> None:
    findings = [
        {
            "finding_id": "SIGMET-1",
            "engine": "weather",
            "title": "SIGMET",
            "details": ["Exact product"],
            "source_ids": ["SRC-1"],
        },
        {
            "finding_id": "SIGMET-1",
            "engine": "weather",
            "title": "SIGMET repeated",
            "details": ["Route/time screening"],
            "source_ids": ["SRC-2"],
        },
    ]
    prepared = deduplicate_findings_for_combined_report(findings)
    assert len(prepared) == 1
    assert prepared[0]["duplicate_count"] == 1
    assert prepared[0]["details"] == ["Exact product", "Route/time screening"]
    assert prepared[0]["source_ids"] == ["SRC-1", "SRC-2"]


def test_combined_report_plan_has_no_level_sections_and_uses_current_filename() -> None:
    plan = build_combined_report_plan(_flight(), _findings())
    assert plan["filename"] == "SQ365_07AUG2026_Flight_Briefing.pdf"
    assert all("LEVEL" not in section["title"] for section in plan["sections"])
    assert "evidence_mel_cdl" in plan["evidence_destinations"]
    assert "MEL/CDL" in plan["decision_gate_categories"]
