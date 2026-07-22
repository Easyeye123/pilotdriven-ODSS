from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


GeoJson = dict[str, Any]
MarkerRole = Literal[
    "departure",
    "destination",
    "fir",
    "bobcat",
    "kabul",
    "early_contact",
    "edto_entry",
    "edto_etp",
    "edto_exit",
    "depressurisation_critical",
    "terrain_critical",
    "toc",
    "tod",
    "orientation",
    "route",
]


class MapBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    west: float
    south: float
    east: float
    north: float

    @field_validator("west", "east")
    @classmethod
    def longitude_range(cls, value: float) -> float:
        if not -180.0 <= value <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        return value

    @field_validator("south", "north")
    @classmethod
    def latitude_range(cls, value: float) -> float:
        if not -90.0 <= value <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        return value


class MapContract(BaseModel):
    """Versioned rendering contract shared by ODSS and PilotDriven."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.1"
    provider: str = "aws-location"
    style: str = "Hybrid"
    route_hash: str
    route_geojson: GeoJson
    markers_geojson: GeoJson
    hazards_geojson: GeoJson = Field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )
    bounds: MapBounds
    priority_labels: list[str] = Field(default_factory=list)
    attribution: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback: dict[str, bool] = Field(
        default_factory=lambda: {
            "static_available": True,
            "schematic_available": True,
        }
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def route_digest(cls, payload: Any) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def public_dict(self) -> dict[str, Any]:
        """Return the browser-safe contract.

        Secrets are not part of this model. The style descriptor URL is
        returned by a separate authenticated/config endpoint.
        """
        return self.model_dump(mode="json")
