from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .models import ResolvedSurfaceFinding
from .osm import SurfaceGraph


def _line_geometry(finding: ResolvedSurfaceFinding) -> dict[str, Any] | None:
    parts = finding.line_parts or ([finding.line_coordinates] if finding.line_coordinates else [])
    parts = [part for part in parts if len(part) >= 2]
    if not parts:
        return None
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": [list(coord) for coord in parts[0]]}
    return {
        "type": "MultiLineString",
        "coordinates": [[[lon, lat] for lon, lat in part] for part in parts],
    }


def _overlay_features(findings: Iterable[ResolvedSurfaceFinding]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for finding_index, finding in enumerate(findings):
        if not finding.mapped:
            continue
        line = _line_geometry(finding)
        base_properties = {
            "notam_id": finding.notam_id,
            "airport": finding.airport,
            "surface_type": finding.clause.target_kind,
            "surface_ref": finding.clause.target_ref,
            "operational_state": finding.clause.operation,
            "applicability": finding.applicability,
            "affects_selected_aircraft": finding.affects_selected_aircraft,
            "match_method": finding.match_method,
            "match_confidence": finding.confidence,
            "effective_from": finding.effective_from,
            "effective_to": finding.effective_to,
            "schedule": finding.schedule,
            "source_osm_ids": finding.source_osm_ids,
            "source": "official-notam-plus-openstreetmap-geometry",
            "display": finding.applicability != "inactive" and finding.affects_selected_aircraft is not False,
            "not_for_navigation": True,
        }
        if line:
            features.append(
                {
                    "type": "Feature",
                    "id": f"finding-{finding_index}-line",
                    "geometry": line,
                    "properties": {**base_properties, "symbol": "surface-overlay-line"},
                }
            )
        for marker_index, coordinate in enumerate(finding.x_coordinates):
            features.append(
                {
                    "type": "Feature",
                    "id": f"finding-{finding_index}-x-{marker_index}",
                    "geometry": {"type": "Point", "coordinates": list(coordinate)},
                    "properties": {**base_properties, "symbol": "closure-x"},
                }
            )
        for marker_index, coordinate in enumerate(finding.junction_coordinates):
            features.append(
                {
                    "type": "Feature",
                    "id": f"finding-{finding_index}-junction-{marker_index}",
                    "geometry": {"type": "Point", "coordinates": list(coordinate)},
                    "properties": {**base_properties, "symbol": "included-junction"},
                }
            )
    return features


def build_surface_contract(
    graph: SurfaceGraph,
    findings: list[ResolvedSurfaceFinding],
    *,
    briefing_time_utc: str | None = None,
    include_surface_geometry: bool = True,
) -> dict[str, Any]:
    south, west, north, east = graph.snapshot.bbox
    unmapped = [finding.as_dict() for finding in findings if not finding.mapped]
    warnings = [
        "Official NOTAM text is authoritative; OpenStreetMap supplies candidate geometry only.",
        "Surface display is for briefing orientation only and is not for navigation.",
        "Promote an airport to operational graphical use only after current State-chart coverage review.",
    ]
    for finding in findings:
        warnings.extend(finding.warnings)
    warnings = list(dict.fromkeys(warnings))
    return {
        "schema_version": "1.0",
        "airport": graph.snapshot.airport,
        "briefing_time_utc": briefing_time_utc,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "geometry_source": {
            "provider": graph.snapshot.source,
            "dataset_timestamp": graph.snapshot.source_timestamp,
            "snapshot_generated_at_utc": graph.snapshot.generated_at_utc,
            "bbox": {
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            },
            "attribution": graph.snapshot.attribution,
            "licence": graph.snapshot.licence,
            "airport_review_state": "proof-of-concept-unreviewed",
        },
        "coverage": graph.coverage,
        "surface_geojson": graph.base_geojson() if include_surface_geometry else None,
        "notam_overlays_geojson": {
            "type": "FeatureCollection",
            "features": _overlay_features(findings),
        },
        "findings": [finding.as_dict() for finding in findings],
        "unmapped_items": unmapped,
        "warnings": warnings,
        "fallback": {
            "text_only_available": True,
            "curated_registry_available": False,
        },
        "not_for_navigation": True,
    }
