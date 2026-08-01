from __future__ import annotations

from types import MappingProxyType


# One contract owns both the rendered Level 2 headings and every UI deep-link.
# Keeping the page number beside its heading prevents the producer and PDF
# renderer from drifting when the fixed seven-page report changes.
LEVEL2_SECTIONS = MappingProxyType(
    {
        "analysis_overview": MappingProxyType(
            {"page": 1, "heading": "ANALYSIS OVERVIEW"}
        ),
        "airport_basis": MappingProxyType(
            {"page": 2, "heading": "PERFORMANCE, FUEL AND AIRPORT BASIS"}
        ),
        "notam_detail": MappingProxyType(
            {"page": 3, "heading": "FLIGHT-WINDOW NOTAM APPLICABILITY"}
        ),
        "edto_detail": MappingProxyType(
            {"page": 4, "heading": "EDTO SECTORS AND SUITABILITY INPUTS"}
        ),
        "communications_detail": MappingProxyType(
            {"page": 5, "heading": "OCEANIC AND FIR COMMUNICATIONS"}
        ),
        "terrain_detail": MappingProxyType(
            {"page": 6, "heading": "DEPRESSURISATION PROFILE MATCH MATRIX"}
        ),
        "weather_detail": MappingProxyType(
            {"page": 7, "heading": "WEATHER AND PROMOTION RESULT"}
        ),
    }
)


def level2_page(target: str) -> int:
    return int(LEVEL2_SECTIONS[target]["page"])


def level2_heading(target: str) -> str:
    return str(LEVEL2_SECTIONS[target]["heading"])


__all__ = ["LEVEL2_SECTIONS", "level2_heading", "level2_page"]
