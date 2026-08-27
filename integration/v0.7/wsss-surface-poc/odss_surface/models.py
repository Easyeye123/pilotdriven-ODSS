from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Coordinate = tuple[float, float]
GeometryConfidence = Literal["high", "medium", "low", "unmapped"]
OperationalState = Literal["closed", "restricted", "information"]
ApplicabilityState = Literal["active", "inactive", "schedule_review", "unknown"]


@dataclass(frozen=True)
class SurfaceWay:
    osm_id: int
    aeroway: str
    ref: str | None
    node_ids: tuple[int | str, ...]
    coordinates: tuple[Coordinate, ...]
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SurfacePoint:
    osm_id: int
    aeroway: str
    ref: str | None
    coordinate: Coordinate
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SurfaceSnapshot:
    airport: str
    source: str
    source_timestamp: str | None
    generated_at_utc: str
    bbox: tuple[float, float, float, float]
    ways: tuple[SurfaceWay, ...]
    points: tuple[SurfacePoint, ...]
    attribution: str = "© OpenStreetMap contributors"
    licence: str = "ODbL-1.0"


@dataclass(frozen=True)
class NotamFields:
    notam_id: str | None
    airport: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    schedule: str | None
    e_line: str
    raw: str


@dataclass(frozen=True)
class SurfaceClause:
    raw: str
    target_ref: str
    target_kind: Literal["taxiway", "taxilane", "runway"]
    operation: OperationalState
    method: Literal[
        "whole_surface",
        "between_intersections",
        "behind_stand",
        "behind_stand_range",
        "aircraft_code_restriction",
    ]
    start_ref: str | None = None
    end_ref: str | None = None
    stand_start: str | None = None
    stand_end: str | None = None
    include_junction_refs: tuple[str, ...] = ()
    restricted_code: str | None = None
    restricted_code_and_above: bool = False


@dataclass
class ResolvedSurfaceFinding:
    notam_id: str | None
    airport: str
    clause: SurfaceClause
    applicability: ApplicabilityState
    affects_selected_aircraft: bool | None
    confidence: GeometryConfidence
    match_method: str
    reason: str
    line_coordinates: list[Coordinate] = field(default_factory=list)
    line_parts: list[list[Coordinate]] = field(default_factory=list)
    x_coordinates: list[Coordinate] = field(default_factory=list)
    junction_coordinates: list[Coordinate] = field(default_factory=list)
    source_osm_ids: list[int] = field(default_factory=list)
    effective_from: str | None = None
    effective_to: str | None = None
    schedule: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def mapped(self) -> bool:
        return bool(self.line_coordinates or self.line_parts or self.x_coordinates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "notam_id": self.notam_id,
            "airport": self.airport,
            "clause": {
                "raw": self.clause.raw,
                "target_ref": self.clause.target_ref,
                "target_kind": self.clause.target_kind,
                "operation": self.clause.operation,
                "method": self.clause.method,
                "start_ref": self.clause.start_ref,
                "end_ref": self.clause.end_ref,
                "stand_start": self.clause.stand_start,
                "stand_end": self.clause.stand_end,
                "include_junction_refs": list(self.clause.include_junction_refs),
                "restricted_code": self.clause.restricted_code,
                "restricted_code_and_above": self.clause.restricted_code_and_above,
            },
            "applicability": self.applicability,
            "affects_selected_aircraft": self.affects_selected_aircraft,
            "confidence": self.confidence,
            "match_method": self.match_method,
            "reason": self.reason,
            "mapped": self.mapped,
            "line_coordinates": self.line_coordinates,
            "line_parts": self.line_parts,
            "x_coordinates": self.x_coordinates,
            "junction_coordinates": self.junction_coordinates,
            "source_osm_ids": self.source_osm_ids,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "schedule": self.schedule,
            "warnings": self.warnings,
        }
