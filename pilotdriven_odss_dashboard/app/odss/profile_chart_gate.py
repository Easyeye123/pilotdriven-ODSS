from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .controlled_library import DEPRESS_LIBRARY_METADATA


class DepressurisationProfileChartPublicationError(RuntimeError):
    """Raised when a report would publish a profile match without its chart."""

    def __init__(self, violations: list[dict[str, str]]):
        super().__init__(
            "Depressurisation profile chart publication gate failed: "
            + "; ".join(item["message"] for item in violations)
        )
        self.violations = violations


def _text(value: Any) -> str:
    return str(value or "").strip()


def _matched_profile_numbers(findings: list[dict[str, Any]]) -> list[str]:
    """Return each proposed approved profile number once, in report order."""
    numbers: list[str] = []
    for finding in findings:
        if finding.get("engine") != "depressurisation":
            continue
        chart_number = _text((finding.get("data") or {}).get("chart_number"))
        if chart_number and chart_number not in numbers:
            numbers.append(chart_number)
    return numbers


def build_profile_chart_artifact_contracts(
    chart_images: list[dict[str, Any]],
    *,
    level1_report_page: int,
    level2_report_pages: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Build report targets for each governed profile chart actually validated."""
    artifacts: list[dict[str, Any]] = []
    for image in chart_images:
        chart_number = str(image["chart_number"])
        profile = image["profile"]
        artifact = {
            "chart_number": chart_number,
            "source_document": DEPRESS_LIBRARY_METADATA.get("title"),
            "source_revision": DEPRESS_LIBRARY_METADATA.get("issue_date"),
            "source_page": profile.get("chart_page"),
            "source_link": profile.get("chart_artifact_key"),
            "route_airway_match_verified": True,
            "aircraft_effectivity_verified": True,
            "chart_image_validated": True,
            "level1_analysis_chart_embedded": True,
            "level1_report_page": level1_report_page,
        }
        if level2_report_pages is not None:
            artifact.update({
                "level2_full_source_chart_embedded": True,
                "level2_report_page": level2_report_pages[chart_number],
            })
        artifacts.append(artifact)
    return artifacts


def validate_depressurisation_profile_charts(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    level: int,
) -> list[dict[str, str]]:
    """Fail closed when an approved profile is named but its chart is not published.

    Level 1 must contain a validated decision-support analysis chart tied to the
    approved source chart. Level 2 must contain the complete authoritative source
    chart page. A profile identifier, source chip or hyperlink alone is not enough.
    """
    if level not in {1, 2}:
        return []

    profile_numbers = _matched_profile_numbers(findings)
    if not profile_numbers:
        return []

    artifacts = flight.get("depressurisation_profile_charts") or []
    artifacts_by_number = {
        _text(item.get("chart_number")): item
        for item in artifacts
        if isinstance(item, dict) and _text(item.get("chart_number"))
    }

    violations: list[dict[str, str]] = []
    embedded_field = (
        "level1_analysis_chart_embedded"
        if level == 1
        else "level2_full_source_chart_embedded"
    )

    for chart_number in profile_numbers:
        artifact = artifacts_by_number.get(chart_number)
        location = f"depressurisation_profile_charts[{chart_number}]"
        if artifact is None:
            violations.append({
                "code": "DEPRESSURISATION_PROFILE_CHART_ARTIFACT_MISSING",
                "location": location,
                "message": (
                    f"Profile {chart_number} is proposed in the briefing but no "
                    "profile-chart artifact is registered."
                ),
            })
            continue

        for field in (
            "source_document",
            "source_revision",
            "source_page",
            "source_link",
        ):
            if not _text(artifact.get(field)):
                violations.append({
                    "code": "DEPRESSURISATION_PROFILE_SOURCE_INCOMPLETE",
                    "location": f"{location}.{field}",
                    "message": f"Profile {chart_number} requires {field}.",
                })

        for field in (
            "route_airway_match_verified",
            "aircraft_effectivity_verified",
            "chart_image_validated",
        ):
            if artifact.get(field) is not True:
                violations.append({
                    "code": "DEPRESSURISATION_PROFILE_VALIDATION_INCOMPLETE",
                    "location": f"{location}.{field}",
                    "message": f"Profile {chart_number} requires {field}=true.",
                })

        if artifact.get(embedded_field) is not True:
            violations.append({
                "code": "DEPRESSURISATION_PROFILE_CHART_MISSING_FROM_REPORT",
                "location": f"{location}.{embedded_field}",
                "message": (
                    f"Profile {chart_number} must be visibly embedded in Level {level}; "
                    "a profile number or source link alone is not a compliant release."
                ),
            })

        report_page_field = f"level{level}_report_page"
        report_page = artifact.get(report_page_field)
        if (
            not isinstance(report_page, int)
            or isinstance(report_page, bool)
            or report_page < 1
        ):
            violations.append({
                "code": "DEPRESSURISATION_PROFILE_REPORT_TARGET_MISSING",
                "location": f"{location}.{report_page_field}",
                "message": (
                    f"Profile {chart_number} requires its actual Level {level} "
                    "report page."
                ),
            })
    if violations:
        raise DepressurisationProfileChartPublicationError(violations)
    return []
