"""Governed metadata for manually reviewed official aeronautical publications.

The registry identifies and cites a reviewed publication; it never supplies
operational facts that are absent from the current OFP finding or an attached
verified snapshot.  Report renderers may therefore label source-backed detail
without turning a publication ID into hidden flight-specific behaviour.
"""

from __future__ import annotations

from typing import Any

from .pilot_briefing import normalize_notam_references


_REVIEWED_PUBLICATIONS: tuple[dict[str, Any], ...] = (
    {
        "location": "WSSS",
        "aliases": frozenset({"SX174/24", "SX0174/24"}),
        "authority": "CAAS",
        "publication_id": "AIRAC AIP SUP 174/2024",
        "source_url": (
            "https://aim-sg.caas.gov.sg/aim-content/uploads/aip/14-MAY-2026/"
            "AIP-2/2026-05-14-000000/html/eSUP/"
            "SG-eSUP-AIRAC-2024-174-en-GB.html"
        ),
        "valid_from_utc": "2024-11-28T00:00:00+00:00",
        "valid_to_utc": "2027-12-22T23:59:00+00:00",
        "reviewed_at_utc": "2026-08-02T00:32:09+00:00",
        "reviewed_sections": ("2.2", "2.3", "2.4"),
    },
)

_OPERATIONAL_DETAIL_PRESENTATIONS: dict[str, dict[str, str]] = {
    "lead_in_markings_removed": {
        "label": "Leading markings into closed taxiways removed.",
        "reviewed_section": "2.2",
    },
    "markerboards_yellow_cross": {
        "label": (
            "Unserviceability markerboards and closed markings (yellow crosses) "
            "demarcate closed taxiways."
        ),
        "reviewed_section": "2.2",
    },
    "marker_red_lights": {
        "label": (
            "Fixed red lights on unserviceability markers lit at night and in low "
            "visibility."
        ),
        "reviewed_section": "2.3",
    },
    "centreline_lights_out": {
        "label": (
            "Taxiway centreline lights leading into and within closed taxiways not "
            "in use."
        ),
        "reviewed_section": "2.4",
    },
}


def reviewed_publication_for_notam(
    location: Any,
    reference: Any,
    *,
    publication_id: Any = None,
) -> dict[str, Any] | None:
    """Return reviewed metadata only for an airport-scoped publication alias."""

    normalized_location = str(location or "").strip().upper()
    normalized = normalize_notam_references(reference).strip().upper()
    explicit_publication = str(publication_id or "").strip().upper()
    for publication in _REVIEWED_PUBLICATIONS:
        publication_matches = (
            not explicit_publication
            or explicit_publication == publication["publication_id"].upper()
        )
        if (
            normalized_location == publication["location"]
            and normalized in publication["aliases"]
            and publication_matches
        ):
            return {
                key: value
                for key, value in publication.items()
                if key != "aliases"
            }
    return None


def operational_detail_presentation(code: Any) -> dict[str, str] | None:
    """Return pilot text only for an allowlisted structured detail code."""

    presentation = _OPERATIONAL_DETAIL_PRESENTATIONS.get(
        str(code or "").strip().lower()
    )
    return dict(presentation) if presentation else None


__all__ = [
    "operational_detail_presentation",
    "reviewed_publication_for_notam",
]
