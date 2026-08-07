from __future__ import annotations

from typing import Any


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


def _crop_box_valid(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(item) for item in value)
    except (TypeError, ValueError):
        return False
    return x1 > x0 and y1 > y0


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


def validate_depressurisation_profile_charts(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    level: int | str,
) -> list[dict[str, str]]:
    """Fail closed when an approved profile is named but its chart is not published.

    Legacy Level 1 requires the flight-specific analysis chart. Legacy Level 2
    requires the complete authoritative chart page. The current combined Flight
    Briefing requires both the flight-specific analysis and a tightly cropped
    authoritative source chart with its crop box and provenance.

    A profile identifier, source chip or hyperlink alone is never sufficient.
    """
    mode: str
    if isinstance(level, str):
        mode = level.strip().casefold().replace("_", "-")
    else:
        mode = str(level)
    if mode not in {"1", "2", "combined", "flight-briefing"}:
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
    if mode == "1":
        embedded_fields = ("level1_analysis_chart_embedded",)
    elif mode == "2":
        embedded_fields = ("level2_full_source_chart_embedded",)
    else:
        embedded_fields = (
            "combined_analysis_chart_embedded",
            "combined_cropped_source_chart_embedded",
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

        for embedded_field in embedded_fields:
            if artifact.get(embedded_field) is not True:
                violations.append({
                    "code": "DEPRESSURISATION_PROFILE_CHART_MISSING_FROM_REPORT",
                    "location": f"{location}.{embedded_field}",
                    "message": (
                        f"Profile {chart_number} must be visibly embedded for report "
                        f"mode {mode}; a profile number or source link alone is not a "
                        "compliant release."
                    ),
                })

        if mode in {"combined", "flight-briefing"} and not _crop_box_valid(
            artifact.get("crop_box")
        ):
            violations.append({
                "code": "DEPRESSURISATION_PROFILE_CROP_BOX_INVALID",
                "location": f"{location}.crop_box",
                "message": (
                    f"Profile {chart_number} requires a valid cropped source-chart box "
                    "for the combined Flight Briefing."
                ),
            })

    if violations:
        raise DepressurisationProfileChartPublicationError(violations)
    return []
