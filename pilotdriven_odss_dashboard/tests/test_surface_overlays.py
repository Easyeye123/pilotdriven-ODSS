from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.odss.surface_overlays import (
    SurfaceOverlayRequest,
    SurfaceReviewFinding,
    _styled_surface_overlay,
    surface_mark_presentation,
)
from app.odss.pertinent_brief import _surface_overlay_lines


@pytest.mark.parametrize(
    ("mark_class", "state", "expected"),
    [
        ("closure", "active_at_reference", "closure"),
        ("closure", "begins_after_reference", "scheduled"),
        ("scheduled", "begins_after_reference", "scheduled"),
        ("equipment", "active_at_reference", "equipment"),
        ("locator", "unknown_at_reference", "locator"),
        ("closure", "unknown_at_reference", "locator"),
        (None, None, "locator"),
        ("closure", "ended_before_reference", None),
    ],
)
def test_surface_mark_presentation_fails_safe(
    mark_class: str | None,
    state: str | None,
    expected: str | None,
) -> None:
    assert surface_mark_presentation({
        "markClass": mark_class,
        "stateAtReference": state,
    }) == expected


def _line_feature(feature_id: str, offset: float) -> dict:
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {
            "featureId": feature_id,
            "aeroway": "taxiway",
            "ref": feature_id,
            "source": "openstreetmap",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[103.9 + offset, 1.3], [103.91 + offset, 1.31]],
        },
    }


def _marker(offset: float) -> dict:
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Point",
            "coordinates": [103.9 + offset, 1.3],
        },
    }


def test_styled_surface_overlay_separates_classes_and_omits_ended_marks() -> None:
    feature_ids = ["active", "scheduled", "equipment", "locator", "ended"]
    states = {
        "active": ("closure", "active_at_reference"),
        "scheduled": ("scheduled", "begins_after_reference"),
        "equipment": ("equipment", "active_at_reference"),
        "locator": ("locator", "unknown_at_reference"),
        "ended": ("closure", "ended_before_reference"),
    }
    contract = {
        "featureCollection": {
            "type": "FeatureCollection",
            "features": [
                _line_feature(feature_id, index / 100)
                for index, feature_id in enumerate(feature_ids)
            ],
        },
        "mapped": [
            {
                "notamNumber": f"N-{feature_id}",
                "featureIds": [feature_id],
                "markClass": states[feature_id][0],
                "stateAtReference": states[feature_id][1],
                "markers": [_marker(index / 100)],
            }
            for index, feature_id in enumerate(feature_ids)
        ],
    }

    styled = _styled_surface_overlay(contract)
    surface_features = styled["features"][: len(feature_ids)]
    marker_features = styled["features"][len(feature_ids):]

    assert [item["properties"]["color"] for item in surface_features] == [
        "#EF4444",
        "#FBBF24",
        "#D97706",
        "#94A3B8",
        "#E5E7EB",
    ]
    assert [item["properties"]["label"] for item in marker_features] == [
        "X",
        "S",
        "!",
        "?",
    ]
    assert all(
        item["properties"]["color"] != "#EF4444"
        for item in surface_features[1:]
    )


def test_surface_overlay_clear_must_be_explicit() -> None:
    assert SurfaceOverlayRequest.model_validate({"overlays": []}).overlays == []
    with pytest.raises(ValidationError):
        SurfaceOverlayRequest.model_validate({})


def test_review_required_surface_accepts_bounded_official_source_conflict() -> None:
    finding = {
        "notamNumber": "SX68/26",
        "entityType": "taxiway",
        "entityRef": "W9/W/R",
        "scope": "ambiguous",
        "plainEnglish": "The uploaded and reviewed publication times conflict.",
        "evidence": "Uploaded 1430Z; reviewed source 1730Z.",
        "sourceConflict": {
            "publicationId": "SUP 068/2026",
            "sourceUrl": "https://aim-sg.caas.gov.sg/example",
            "checkedAt": "2026-08-01T00:00:00.000Z",
            "conflictingFields": ["startsAt"],
            "uploaded": {
                "startsAt": "2026-05-14T14:30:00.000Z",
                "endsAt": "2026-10-01T21:30:00.000Z",
            },
            "reviewed": {
                "startsAt": "2026-05-14T17:30:00.000Z",
                "endsAt": "2026-10-01T21:30:00.000Z",
            },
        },
    }

    conflict = SurfaceReviewFinding.model_validate(finding).sourceConflict
    assert conflict is not None
    assert conflict.publicationId == "SUP 068/2026"
    assert conflict.conflictingFields == ["startsAt"]


def test_report_names_caas_timing_conflict_and_both_zulu_values() -> None:
    overlay = {
        "mapped": [],
        "reviewRequired": [
            {
                "notamNumber": "A1000/26",
                "entityType": "taxiway",
                "entityRef": "S1",
                "plainEnglish": "Surface location unresolved.",
            },
            {
                "notamNumber": "A1001/26",
                "entityType": "taxiway",
                "entityRef": "S2",
                "plainEnglish": "Surface location unresolved.",
            },
            {
                "notamNumber": "SX68/26",
                "entityType": "taxiway",
                "entityRef": "W9/W/R",
                "plainEnglish": "Uploaded and reviewed publication times conflict.",
                "sourceConflict": {
                    "publicationId": "SUP 068/2026",
                    "sourceUrl": "https://aim-sg.caas.gov.sg/example",
                    "conflictingFields": ["startsAt"],
                    "uploaded": {"startsAt": "2026-05-14T14:30:00Z"},
                    "reviewed": {"startsAt": "2026-05-14T17:30:00Z"},
                },
            }
        ],
    }

    text = "\n".join(_surface_overlay_lines(overlay, detail_limit=4))

    assert "CAAS SUP 068/2026" in text
    assert "start uploaded 14 MAY 26 1430Z" in text
    assert "reviewed 14 MAY 26 1730Z" in text
    assert "pilot review required" in text
    assert "A1001/26" not in text


def test_report_summary_does_not_call_nonclosures_closed() -> None:
    overlay = {
        "mapped": [
            {
                "entityType": "runway",
                "entityRef": "02C/20C",
                "markClass": "scheduled",
                "stateAtReference": "begins_after_reference",
            },
            {
                "entityType": "taxiway",
                "entityRef": "S2",
                "notamNumber": "A1234/26",
                "markClass": "equipment",
                "stateAtReference": "active_at_reference",
                "referenceAt": "2026-08-01T05:35:00+00:00",
                "referenceInterval": {
                    "startsAt": "2026-08-01T04:00:00+00:00",
                    "endsAt": "2026-08-01T06:00:00+00:00",
                },
            },
            {
                "entityType": "taxiway",
                "entityRef": "W9",
                "markClass": "locator",
                "stateAtReference": "unknown_at_reference",
            },
            {
                "entityType": "runway",
                "entityRef": "04L/22R",
                "markClass": "closure",
                "stateAtReference": "ended_before_reference",
            },
        ],
        "reviewRequired": [],
    }

    text = "\n".join(_surface_overlay_lines(overlay, detail_limit=4))

    assert "scheduled restriction mark" in text
    assert "equipment-unavailable mark" in text
    assert "locator/review mark" in text
    assert "Scheduled: RUNWAY 02C/20C" in text
    assert "Equipment: TAXIWAY S2" in text
    assert "Equipment: TAXIWAY S2 | A1234/26 | 0400Z-0600Z" in text
    assert "Review locator: TAXIWAY W9" in text
    assert "Closed:" not in text
    assert "04L/22R" not in text
