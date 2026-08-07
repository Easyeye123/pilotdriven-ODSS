from __future__ import annotations

import pytest

from app.odss.profile_chart_gate import (
    DepressurisationProfileChartPublicationError,
    validate_depressurisation_profile_charts,
)


def _findings() -> list[dict]:
    return [
        {
            "engine": "depressurisation",
            "data": {"chart_number": "10-5"},
        }
    ]


def _artifact() -> dict:
    return {
        "chart_number": "10-5",
        "source_document": "Synthetic A350 Depressurisation Profiles",
        "source_revision": "TEST REV",
        "source_page": 280,
        "source_link": "helpyou://synthetic/depressurisation/10-5",
        "route_airway_match_verified": True,
        "aircraft_effectivity_verified": True,
        "chart_image_validated": True,
        "combined_analysis_chart_embedded": True,
        "combined_cropped_source_chart_embedded": True,
        "crop_box": [40, 70, 760, 510],
    }


def test_combined_report_requires_analysis_and_cropped_source_chart() -> None:
    artifact = _artifact()
    artifact["combined_cropped_source_chart_embedded"] = False
    flight = {"depressurisation_profile_charts": [artifact]}

    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts(flight, _findings(), "combined")

    assert any(
        item["code"] == "DEPRESSURISATION_PROFILE_CHART_MISSING_FROM_REPORT"
        and item["location"].endswith("combined_cropped_source_chart_embedded")
        for item in captured.value.violations
    )


def test_combined_report_requires_valid_crop_box() -> None:
    artifact = _artifact()
    artifact["crop_box"] = [100, 100, 80, 90]
    flight = {"depressurisation_profile_charts": [artifact]}

    with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
        validate_depressurisation_profile_charts(flight, _findings(), "flight-briefing")

    assert any(
        item["code"] == "DEPRESSURISATION_PROFILE_CROP_BOX_INVALID"
        for item in captured.value.violations
    )


def test_combined_report_accepts_validated_cropped_chart() -> None:
    flight = {"depressurisation_profile_charts": [_artifact()]}
    assert validate_depressurisation_profile_charts(
        flight,
        _findings(),
        "combined",
    ) == []
