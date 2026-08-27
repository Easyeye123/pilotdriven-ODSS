from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString
from shapely.ops import transform

from .models import Coordinate, ResolvedSurfaceFinding, SurfaceClause
from .notam import (
    evaluate_aircraft_code,
    evaluate_applicability,
    parse_notam_fields,
    parse_surface_clauses,
)
from .osm import SurfaceGraph

_TO_METRES = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True).transform
_TO_LONLAT = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True).transform


def parse_briefing_time(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _geometry_parts(geometry) -> list[list[Coordinate]]:
    if geometry is None:
        return []
    if isinstance(geometry, MultiLineString):
        components = list(geometry.geoms)
    else:
        components = [geometry]
    return [
        [(float(lon), float(lat)) for lon, lat in line.coords]
        for line in components
        if len(line.coords) >= 2
    ]


def _x_points(parts: list[list[Coordinate]], spacing_m: float = 180.0) -> list[Coordinate]:
    points: list[Coordinate] = []
    for coordinates in parts:
        line = LineString(coordinates)
        line_m = transform(_TO_METRES, line)
        if line_m.length <= spacing_m * 1.25:
            distances = [line_m.length / 2.0]
        else:
            count = max(2, int(line_m.length // spacing_m))
            distances = [line_m.length * (index + 1) / (count + 1) for index in range(count)]
        for distance in distances:
            point = transform(_TO_LONLAT, line_m.interpolate(distance))
            points.append((float(point.x), float(point.y)))
    return points


def _junction_coordinates(graph: SurfaceGraph, target_ref: str, refs: Iterable[str]) -> list[Coordinate]:
    coordinates: list[Coordinate] = []
    seen = set()
    for ref in refs:
        for node_id in graph.intersection_nodes(target_ref, ref):
            coordinate = graph.coordinate(node_id)
            rounded = (round(coordinate[0], 8), round(coordinate[1], 8))
            if rounded not in seen:
                seen.add(rounded)
                coordinates.append(coordinate)
    return coordinates


def _unmapped(
    graph: SurfaceGraph,
    fields,
    clause: SurfaceClause,
    applicability,
    affects_selected_aircraft,
    reason: str,
    *,
    warnings: list[str] | None = None,
) -> ResolvedSurfaceFinding:
    return ResolvedSurfaceFinding(
        notam_id=fields.notam_id,
        airport=fields.airport or graph.snapshot.airport,
        clause=clause,
        applicability=applicability,
        affects_selected_aircraft=affects_selected_aircraft,
        confidence="unmapped",
        match_method=clause.method,
        reason=reason,
        effective_from=fields.starts_at.isoformat().replace("+00:00", "Z") if fields.starts_at else None,
        effective_to=fields.ends_at.isoformat().replace("+00:00", "Z") if fields.ends_at else None,
        schedule=fields.schedule,
        warnings=warnings or [],
    )


def resolve_surface_notam(
    graph: SurfaceGraph,
    raw_notam: str,
    *,
    briefing_time_utc: str | datetime | None = None,
    selected_aircraft_code: str | None = None,
) -> list[ResolvedSurfaceFinding]:
    fields = parse_notam_fields(raw_notam)
    if fields.airport and fields.airport != graph.snapshot.airport:
        raise ValueError(
            f"NOTAM A-line is {fields.airport}; loaded surface snapshot is {graph.snapshot.airport}."
        )
    briefing_time = parse_briefing_time(briefing_time_utc)
    applicability = evaluate_applicability(fields, briefing_time)
    findings: list[ResolvedSurfaceFinding] = []
    for clause in parse_surface_clauses(fields):
        affects_selected_aircraft = evaluate_aircraft_code(clause, selected_aircraft_code)
        if not graph.ways_for_ref(clause.target_ref):
            findings.append(
                _unmapped(
                    graph,
                    fields,
                    clause,
                    applicability,
                    affects_selected_aircraft,
                    f"Surface reference {clause.target_ref} is absent from the versioned WSSS OSM snapshot.",
                )
            )
            continue

        if clause.method == "between_intersections":
            assert clause.start_ref and clause.end_ref
            path = graph.path_between_refs(clause.target_ref, clause.start_ref, clause.end_ref)
            if path is None:
                findings.append(
                    _unmapped(
                        graph,
                        fields,
                        clause,
                        applicability,
                        affects_selected_aircraft,
                        (
                            f"Could not find a connected {clause.target_ref} path between "
                            f"{clause.start_ref} and {clause.end_ref}."
                        ),
                    )
                )
                continue
            confidence = (
                "high"
                if path["candidate_count"] == 1
                and path["start_candidate_count"] == 1
                and path["end_candidate_count"] == 1
                else "medium"
            )
            warnings = []
            if confidence == "medium":
                warnings.append("Multiple candidate intersections existed; the shortest connected target-ref path was selected.")
            coordinates = path["coordinates"]
            parts = [coordinates]
            findings.append(
                ResolvedSurfaceFinding(
                    notam_id=fields.notam_id,
                    airport=fields.airport or graph.snapshot.airport,
                    clause=clause,
                    applicability=applicability,
                    affects_selected_aircraft=affects_selected_aircraft,
                    confidence=confidence,
                    match_method="exact_ref_intersection_path",
                    reason=(
                        f"Matched {clause.target_ref} between intersections with "
                        f"{clause.start_ref} and {clause.end_ref}."
                    ),
                    line_coordinates=coordinates,
                    line_parts=parts,
                    x_coordinates=_x_points(parts),
                    junction_coordinates=_junction_coordinates(
                        graph, clause.target_ref, clause.include_junction_refs
                    ),
                    source_osm_ids=path["source_osm_ids"],
                    effective_from=fields.starts_at.isoformat().replace("+00:00", "Z") if fields.starts_at else None,
                    effective_to=fields.ends_at.isoformat().replace("+00:00", "Z") if fields.ends_at else None,
                    schedule=fields.schedule,
                    warnings=warnings,
                )
            )
            continue

        if clause.method in {"behind_stand", "behind_stand_range"}:
            assert clause.stand_start
            projected = graph.project_stand_range(
                clause.target_ref,
                clause.stand_start,
                clause.stand_end,
            )
            if projected is None:
                missing = clause.stand_start if not clause.stand_end else f"{clause.stand_start}–{clause.stand_end}"
                findings.append(
                    _unmapped(
                        graph,
                        fields,
                        clause,
                        applicability,
                        affects_selected_aircraft,
                        f"Could not project stand reference {missing} onto {clause.target_ref}.",
                    )
                )
                continue
            projection_error = float(projected["projection_error_m"])
            if projection_error > 250.0:
                findings.append(
                    _unmapped(
                        graph,
                        fields,
                        clause,
                        applicability,
                        affects_selected_aircraft,
                        (
                            f"Stand projection error {projection_error:.0f} m exceeds the 250 m proof-of-concept limit."
                        ),
                    )
                )
                continue
            confidence = "medium" if projection_error <= 120.0 else "low"
            coordinates = projected["coordinates"]
            parts = [coordinates]
            findings.append(
                ResolvedSurfaceFinding(
                    notam_id=fields.notam_id,
                    airport=fields.airport or graph.snapshot.airport,
                    clause=clause,
                    applicability=applicability,
                    affects_selected_aircraft=affects_selected_aircraft,
                    confidence=confidence,
                    match_method="stand_projection_to_surface_ref",
                    reason=(
                        f"Projected stand reference(s) onto {clause.target_ref}; "
                        f"combined projection error {projection_error:.0f} m."
                    ),
                    line_coordinates=coordinates,
                    line_parts=parts,
                    x_coordinates=_x_points(parts, spacing_m=90.0),
                    junction_coordinates=_junction_coordinates(
                        graph, clause.target_ref, clause.include_junction_refs
                    ),
                    source_osm_ids=projected["source_osm_ids"],
                    effective_from=fields.starts_at.isoformat().replace("+00:00", "Z") if fields.starts_at else None,
                    effective_to=fields.ends_at.isoformat().replace("+00:00", "Z") if fields.ends_at else None,
                    schedule=fields.schedule,
                    warnings=["Stand-derived extents require current-chart verification before operational promotion."],
                )
            )
            continue

        geometry = graph.whole_ref_geometry(clause.target_ref)
        parts = _geometry_parts(geometry)
        if not parts:
            findings.append(
                _unmapped(
                    graph,
                    fields,
                    clause,
                    applicability,
                    affects_selected_aircraft,
                    f"No drawable line geometry was available for {clause.target_ref}.",
                )
            )
            continue
        confidence = "high" if len(parts) == 1 else "medium"
        warnings = []
        if len(parts) > 1:
            warnings.append(
                f"{clause.target_ref} contains {len(parts)} disconnected mapped components; all are shown."
            )
        if clause.method == "aircraft_code_restriction" and affects_selected_aircraft is False:
            reason = (
                f"Restriction is mapped, but selected aircraft code {selected_aircraft_code} is not affected."
            )
        elif clause.method == "aircraft_code_restriction" and affects_selected_aircraft is None:
            reason = "Restriction is mapped; selected aircraft code was not supplied or could not be evaluated."
        else:
            reason = f"Matched complete OSM surface reference {clause.target_ref}."
        findings.append(
            ResolvedSurfaceFinding(
                notam_id=fields.notam_id,
                airport=fields.airport or graph.snapshot.airport,
                clause=clause,
                applicability=applicability,
                affects_selected_aircraft=affects_selected_aircraft,
                confidence=confidence,
                match_method="exact_surface_ref",
                reason=reason,
                line_coordinates=parts[0],
                line_parts=parts,
                x_coordinates=_x_points(parts),
                junction_coordinates=_junction_coordinates(
                    graph, clause.target_ref, clause.include_junction_refs
                ),
                source_osm_ids=graph.source_ids_for_ref(clause.target_ref),
                effective_from=fields.starts_at.isoformat().replace("+00:00", "Z") if fields.starts_at else None,
                effective_to=fields.ends_at.isoformat().replace("+00:00", "Z") if fields.ends_at else None,
                schedule=fields.schedule,
                warnings=warnings,
            )
        )
    return findings
