from __future__ import annotations

import pytest

from app.odss.profile_chart_gate import (
    DepressurisationProfileChartPublicationError,
    validate_depressurisation_profile_charts,
)
from app.odss.operational_brief import build_profile_chart_artifacts


def _findings() -> list[dict]:
    return [
        {
            "engine": "depressurisation",
            "data": {
                "chart_number": "10-4",
                "coverage_complete": True,
            },
        },
        {
            "engine": "depressurisation",
            "data": {
                "chart_number": "8-5",
                "coverage_complete": True,
            },
        },
    ]


def _artifact(chart_number: str) -> dict:
    source_page = 269 if chart_number == "10-4" else 235
    return {
        "chart_number": chart_number,
        "source_document": "A350 Depressurization Profiles",
        "source_revision": "12 JUN 2026",
        "source_page": source_page,
        "source_link": f"helpyou://a350-depressurisation/page/{source_page}",
        "route_airway_match_verified": True,
        "aircraft_effectivity_verified": True,
        "chart_image_validated": True,
        "level1_analysis_chart_embedded": True,
        "level1_report_page": 3,
        "level2_full_source_chart_embedded": True,
        "level2_report_page": 8 if chart_number == "10-4" else 9,
    }


def test_level1_blocks_profile_identifiers_without_embedded_analysis_charts() -> None:
    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts({}, _findings(), 1)

    codes = {item["code"] for item in captured.value.violations}
    assert "DEPRESSURISATION_PROFILE_CHART_ARTIFACT_MISSING" in codes


def test_level2_blocks_source_links_without_full_embedded_chart_page() -> None:
    artifact = _artifact("10-4")
    artifact["level2_full_source_chart_embedded"] = False
    flight = {"depressurisation_profile_charts": [artifact, _artifact("8-5")]}

    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts(flight, _findings(), 2)

    assert any(
        item["code"] == "DEPRESSURISATION_PROFILE_CHART_MISSING_FROM_REPORT"
        and item["location"].endswith("level2_full_source_chart_embedded")
        for item in captured.value.violations
    )


def test_profile_chart_gate_accepts_validated_level1_and_level2_artifacts() -> None:
    flight = {
        "depressurisation_profile_charts": [
            _artifact("10-4"),
            _artifact("8-5"),
        ]
    }

    assert validate_depressurisation_profile_charts(flight, _findings(), 1) == []
    assert validate_depressurisation_profile_charts(flight, _findings(), 2) == []


def test_level2_blocks_embedded_chart_without_real_report_target() -> None:
    artifact = _artifact("10-4")
    artifact.pop("level2_report_page")
    flight = {"depressurisation_profile_charts": [artifact, _artifact("8-5")]}

    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts(flight, _findings(), 2)

    missing_locations = {
        item["location"]
        for item in captured.value.violations
        if item["code"] == "DEPRESSURISATION_PROFILE_REPORT_TARGET_MISSING"
    }
    assert missing_locations == {
        "depressurisation_profile_charts[10-4].level2_report_page",
    }


def test_level1_blocks_embedded_chart_without_real_report_target() -> None:
    artifact = _artifact("10-4")
    artifact.pop("level1_report_page")
    flight = {"depressurisation_profile_charts": [artifact, _artifact("8-5")]}

    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts(flight, _findings(), 1)

    missing_locations = {
        item["location"]
        for item in captured.value.violations
        if item["code"] == "DEPRESSURISATION_PROFILE_REPORT_TARGET_MISSING"
    }
    assert missing_locations == {
        "depressurisation_profile_charts[10-4].level1_report_page",
    }


def test_level2_artifact_contract_publishes_actual_report_page() -> None:
    artifacts = build_profile_chart_artifacts(
        [{
            "chart_number": "8-7",
            "profile": {
                "chart_page": 241,
                "chart_artifact_key": "charts/profile-8-7.pdf",
            },
        }],
        {"8-7": 10},
    )

    assert artifacts[0]["level1_report_page"] == 3
    assert artifacts[0]["level2_report_page"] == 10
    assert "level2_report_anchor" not in artifacts[0]


def test_unmatched_high_terrain_without_a_proposed_profile_does_not_require_a_chart() -> None:
    findings = [
        {
            "engine": "depressurisation",
            "title": "High terrain detected but no profile matched",
            "data": {},
        }
    ]

    assert validate_depressurisation_profile_charts({}, findings, 1) == []
    assert validate_depressurisation_profile_charts({}, findings, 2) == []
