from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import fitz


_CHART_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,31}$")
_REQUIRED_SOURCE_FIELDS = (
    "source_document",
    "source_revision",
    "source_page",
    "source_link",
)
_REQUIRED_VALIDATION_FIELDS = (
    "route_airway_match_verified",
    "aircraft_effectivity_verified",
    "chart_image_validated",
    "level2_full_source_chart_embedded",
)


def held_profile_chart(
    analysis: dict[str, Any],
    chart_number: str,
) -> dict[str, Any] | None:
    """Return an exact publishable chart target, never a guessed profile.

    The stored Level 2 page is the governed artifact already selected during
    deterministic analysis. This delivery gate repeats every publication
    requirement before exposing it to the browser.
    """
    requested = str(chart_number or "").strip().upper()
    if not _CHART_NUMBER.fullmatch(requested):
        return None

    charts = (analysis.get("flight") or {}).get(
        "depressurisation_profile_charts"
    ) or []
    for candidate in charts:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("chart_number") or "").strip().upper() != requested:
            continue
        if any(not str(candidate.get(field) or "").strip() for field in _REQUIRED_SOURCE_FIELDS):
            return None
        if any(candidate.get(field) is not True for field in _REQUIRED_VALIDATION_FIELDS):
            return None
        page_number = candidate.get("level2_report_page")
        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
        ):
            return None
        return candidate
    return None


def render_held_profile_chart_page(
    report_path: Path,
    artifact: dict[str, Any],
) -> bytes:
    """Render the exact held Level 2 source-chart page as a browser image."""
    page_index = int(artifact["level2_report_page"]) - 1
    document = fitz.open(report_path)
    try:
        if page_index < 0 or page_index >= document.page_count:
            raise LookupError("Held profile chart report page is unavailable")
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


__all__ = ["held_profile_chart", "render_held_profile_chart_page"]
