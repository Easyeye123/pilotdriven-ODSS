from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import DATA_DIR
from ..odss_map_v06.config import MapSettings


SURFACE_MAP_DIR = DATA_DIR / "maps"
MAX_SURFACE_FEATURES = 256
MAX_SURFACE_MATCHES = 128
MAX_COORDINATE_POINTS = 20_000


def surface_conflict_publication_label(conflict: dict[str, Any]) -> str:
    """Return one authority/publication label without repeating authority."""

    publication = " ".join(
        str(conflict.get("publicationId") or "publication").split()
    )
    source_url = str(conflict.get("sourceUrl") or "").strip()
    try:
        hostname = (urlsplit(source_url).hostname or "").lower().rstrip(".")
    except ValueError:
        hostname = ""
    caas_hostname = "aim-sg.caas.gov.sg"
    authority = (
        "CAAS"
        if hostname == caas_hostname or hostname.endswith(f".{caas_hostname}")
        else "SOURCE"
    )
    publication_upper = publication.upper()
    if publication_upper == authority:
        return authority
    if publication_upper.startswith(f"{authority} "):
        return f"{authority} {publication.split(' ', 1)[1]}"
    return f"{authority} {publication}"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _coordinate_points(value: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []

    def visit(item: Any) -> None:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            longitude = float(item[0])
            latitude = float(item[1])
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("Surface GeoJSON contains an invalid coordinate.")
            points.append((longitude, latitude))
            if len(points) > MAX_COORDINATE_POINTS:
                raise ValueError("Surface GeoJSON exceeds the coordinate limit.")
            return
        if isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return points


class SurfaceGeometry(_StrictModel):
    type: Literal["LineString", "Polygon"]
    coordinates: list[Any]

    @model_validator(mode="after")
    def validate_coordinates(self):
        points = _coordinate_points(self.coordinates)
        minimum = 2 if self.type == "LineString" else 4
        if len(points) < minimum:
            raise ValueError("Surface GeoJSON geometry is incomplete.")
        return self


class SurfaceFeatureProperties(_StrictModel):
    featureId: str = Field(min_length=1, max_length=160)
    aeroway: Literal["runway", "taxiway", "taxilane", "apron"]
    ref: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=160)
    source: str = Field(default="openstreetmap", max_length=64)


class SurfaceFeature(_StrictModel):
    type: Literal["Feature"]
    id: str = Field(min_length=1, max_length=160)
    properties: SurfaceFeatureProperties
    geometry: SurfaceGeometry

    @model_validator(mode="after")
    def validate_identity(self):
        if self.id != self.properties.featureId:
            raise ValueError("Surface feature id and property id do not match.")
        return self


class SurfaceFeatureCollection(_StrictModel):
    type: Literal["FeatureCollection"]
    features: list[SurfaceFeature] = Field(max_length=MAX_SURFACE_FEATURES)


class SurfacePointGeometry(_StrictModel):
    type: Literal["Point"]
    coordinates: list[float] = Field(min_length=2, max_length=3)

    @field_validator("coordinates")
    @classmethod
    def validate_point(cls, value: list[float]) -> list[float]:
        _coordinate_points(value)
        return value


class SurfaceMarker(_StrictModel):
    type: Literal["Feature"]
    properties: dict[str, Any] = Field(default_factory=dict)
    geometry: SurfacePointGeometry


SurfaceMarkClass = Literal["closure", "scheduled", "equipment", "locator"]
SurfaceReferenceState = Literal[
    "active_at_reference",
    "begins_after_reference",
    "ended_before_reference",
    "unknown_at_reference",
]


class SurfaceReferenceInterval(_StrictModel):
    startsAt: str | None = Field(default=None, max_length=64)
    endsAt: str | None = Field(default=None, max_length=64)


class SurfaceMappedFinding(_StrictModel):
    notamNumber: str | None = Field(default=None, max_length=64)
    entityType: Literal["runway", "taxiway", "apron"] | None = None
    entityRef: str | None = Field(default=None, max_length=64)
    scope: str = Field(default="whole_entity", max_length=32)
    featureIds: list[str] = Field(default_factory=list, max_length=64)
    plainEnglish: str | None = Field(default=None, max_length=500)
    evidence: str | None = Field(default=None, max_length=2_000)
    markClass: SurfaceMarkClass | None = None
    stateAtReference: SurfaceReferenceState | None = None
    referenceAt: str | None = Field(default=None, max_length=64)
    referenceInterval: SurfaceReferenceInterval | None = None
    markers: list[SurfaceMarker] = Field(default_factory=list, max_length=64)


class SurfaceSourceInterval(_StrictModel):
    startsAt: str | None = Field(default=None, max_length=64)
    endsAt: str | None = Field(default=None, max_length=64)


class SurfaceSourceConflict(_StrictModel):
    publicationId: str | None = Field(default=None, max_length=160)
    sourceUrl: str | None = Field(default=None, max_length=1_000)
    checkedAt: str | None = Field(default=None, max_length=64)
    conflictingFields: list[Literal["startsAt", "endsAt"]] = Field(
        default_factory=list,
        max_length=2,
    )
    uploaded: SurfaceSourceInterval
    reviewed: SurfaceSourceInterval


class SurfaceReviewFinding(_StrictModel):
    notamNumber: str | None = Field(default=None, max_length=64)
    entityType: Literal["runway", "taxiway", "apron", "unknown"] | None = None
    entityRef: str | None = Field(default=None, max_length=64)
    scope: str = Field(default="ambiguous", max_length=32)
    plainEnglish: str | None = Field(default=None, max_length=500)
    evidence: str | None = Field(default=None, max_length=2_000)
    sourceConflict: SurfaceSourceConflict | None = None


class SurfaceSource(_StrictModel):
    provider: Literal["openstreetmap"]
    fetchedAt: str | None = Field(default=None, max_length=64)
    sourceUpdatedAt: str | None = Field(default=None, max_length=64)
    attribution: str = Field(min_length=1, max_length=200)
    licenceUrl: str = Field(min_length=1, max_length=500)
    referenceOnly: Literal[True]


class SurfaceBounds(_StrictModel):
    west: float
    south: float
    east: float
    north: float

    @model_validator(mode="after")
    def validate_bounds(self):
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("Surface longitude bounds are invalid.")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("Surface latitude bounds are invalid.")
        return self


class SurfaceWindow(_StrictModel):
    startsAt: str | None = Field(default=None, max_length=64)
    endsAt: str | None = Field(default=None, max_length=64)
    basis: Literal[
        "filed-std-sta",
        "scheduled_departure",
        "scheduled_arrival",
        "actual_takeoff",
        "calculated_destination_from_atot_and_cfp_actm",
    ]


class SurfaceCounts(_StrictModel):
    mapped: int = Field(ge=0, le=MAX_SURFACE_MATCHES)
    reviewRequired: int = Field(ge=0, le=MAX_SURFACE_MATCHES)
    runways: int = Field(ge=0, le=64)


class SurfaceOverlayContract(_StrictModel):
    schemaVersion: Literal["1.0"]
    icao: str = Field(pattern=r"^[A-Z]{4}$")
    name: str = Field(min_length=1, max_length=200)
    role: Literal["departure", "destination"]
    window: SurfaceWindow
    source: SurfaceSource
    bounds: SurfaceBounds | None
    featureCollection: SurfaceFeatureCollection
    mapped: list[SurfaceMappedFinding] = Field(max_length=MAX_SURFACE_MATCHES)
    reviewRequired: list[SurfaceReviewFinding] = Field(max_length=MAX_SURFACE_MATCHES)
    counts: SurfaceCounts

    @model_validator(mode="after")
    def validate_references(self):
        feature_ids = {
            feature.properties.featureId
            for feature in self.featureCollection.features
        }
        for match in self.mapped:
            if not match.featureIds or not set(match.featureIds).issubset(feature_ids):
                raise ValueError(
                    "A mapped surface finding must reference only supplied geometry."
                )
        runway_count = sum(
            feature.properties.aeroway == "runway"
            for feature in self.featureCollection.features
        )
        if runway_count != self.counts.runways:
            raise ValueError("Surface runway count does not match its geometry.")
        if len(self.mapped) != self.counts.mapped:
            raise ValueError("Surface mapped count does not match its findings.")
        if len(self.reviewRequired) != self.counts.reviewRequired:
            raise ValueError("Surface review count does not match its findings.")
        return self


class SurfaceOverlayRequest(_StrictModel):
    # The field stays required so an omitted payload cannot clear an analysis by
    # accident. An explicit empty list is the fail-safe clear after a timing
    # refresh can no longer validate the previous marks.
    overlays: list[SurfaceOverlayContract] = Field(max_length=2)


def validated_surface_overlays(
    request: SurfaceOverlayRequest,
    flight: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = {
        "departure": str(flight.get("departure") or "").strip().upper(),
        "destination": str(flight.get("destination") or "").strip().upper(),
    }
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for overlay in request.overlays:
        if overlay.role in seen:
            raise ValueError(f"Duplicate {overlay.role} surface overlay.")
        seen.add(overlay.role)
        if overlay.icao != expected[overlay.role]:
            raise ValueError(
                f"{overlay.role.title()} surface overlay does not match the analysed flight."
            )
        result.append(overlay.model_dump(mode="json"))
    return result


def _sample_line(coordinates: list[Any], maximum: int = 16) -> list[Any]:
    if len(coordinates) <= maximum:
        return coordinates
    return [
        coordinates[
            round(index * (len(coordinates) - 1) / (maximum - 1))
        ]
        for index in range(maximum)
    ]


_SURFACE_STYLES = {
    "closure": {
        "color": "#EF4444",
        "width": 8,
        "outline-color": "#7F1D1D",
        "outline-width": 2,
        "fill-color": "#EF4444",
        "fill-opacity": 0.55,
        "marker-label": "X",
    },
    "scheduled": {
        "color": "#FBBF24",
        "width": 7,
        "outline-color": "#92400E",
        "outline-width": 2,
        "fill-color": "#FBBF24",
        "fill-opacity": 0.42,
        "marker-label": "S",
    },
    "equipment": {
        "color": "#D97706",
        "width": 6,
        "outline-color": "#78350F",
        "outline-width": 2,
        "fill-color": "#D97706",
        "fill-opacity": 0.36,
        "marker-label": "!",
    },
    "locator": {
        "color": "#94A3B8",
        "width": 5,
        "outline-color": "#475569",
        "outline-width": 1,
        "fill-color": "#94A3B8",
        "fill-opacity": 0.24,
        "marker-label": "?",
    },
}
_SURFACE_STYLE_PRIORITY = {
    "locator": 0,
    "equipment": 1,
    "scheduled": 2,
    "closure": 3,
}


def surface_mark_presentation(match: dict[str, Any]) -> str | None:
    """Return a fail-safe visual class for a time-qualified surface finding."""

    state = str(match.get("stateAtReference") or "").strip().casefold()
    mark_class = str(match.get("markClass") or "").strip().casefold()
    if state == "ended_before_reference":
        return None
    if state == "begins_after_reference" or mark_class == "scheduled":
        return "scheduled"
    if mark_class == "equipment":
        return "equipment"
    if mark_class == "closure" and state == "active_at_reference":
        return "closure"
    # Missing/unknown timing, explicit locator rows, and legacy unclassified
    # rows remain visible only as review locators. They must never become red.
    return "locator"


def _styled_surface_overlay(contract: dict[str, Any]) -> dict[str, Any]:
    feature_marks: dict[str, str] = {}
    for match in contract.get("mapped") or []:
        presentation = surface_mark_presentation(match)
        if presentation is None:
            continue
        for feature_id in match.get("featureIds") or []:
            key = str(feature_id)
            previous = feature_marks.get(key)
            if (
                previous is None
                or _SURFACE_STYLE_PRIORITY[presentation]
                > _SURFACE_STYLE_PRIORITY[previous]
            ):
                feature_marks[key] = presentation

    features: list[dict[str, Any]] = []
    for feature in (contract.get("featureCollection") or {}).get("features") or []:
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        feature_id = str((feature.get("properties") or {}).get("featureId") or "")
        if geometry_type == "LineString" and isinstance(coordinates, list):
            geometry = {
                "type": "LineString",
                "coordinates": _sample_line(coordinates),
            }
        elif geometry_type != "Polygon":
            continue
        presentation = feature_marks.get(feature_id)
        style = _SURFACE_STYLES.get(presentation or "")
        properties: dict[str, Any] = {
            "color": style["color"] if style else "#E5E7EB",
            "width": style["width"] if style else 3,
            "outline-color": (
                style["outline-color"] if style else "#334155"
            ),
            "outline-width": style["outline-width"] if style else 1,
        }
        if geometry_type == "Polygon":
            properties.update({
                "fill-color": (
                    style["fill-color"] if style else "#64748B"
                ),
                "fill-opacity": (
                    style["fill-opacity"] if style else 0.18
                ),
            })
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        })
    for match in contract.get("mapped") or []:
        presentation = surface_mark_presentation(match)
        if presentation is None:
            continue
        style = _SURFACE_STYLES[presentation]
        for marker in match.get("markers") or []:
            features.append({
                "type": "Feature",
                "geometry": marker["geometry"],
                "properties": {
                    "label": style["marker-label"],
                    "color": style["color"],
                    "size": "small",
                },
            })
    return {"type": "FeatureCollection", "features": features}


class SurfaceOverlayRenderError(RuntimeError):
    pass


async def render_surface_static_map(
    contract: dict[str, Any],
    settings: MapSettings,
    destination_stem: Path,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    key = settings.static_map_api_key
    bounds = contract.get("bounds")
    if not key:
        raise SurfaceOverlayRenderError("Amazon Location static-map key is unavailable.")
    if not bounds:
        raise SurfaceOverlayRenderError("Airport surface bounds are unavailable.")

    overlay = _styled_surface_overlay(contract)
    overlay_text = json.dumps(overlay, separators=(",", ":"), ensure_ascii=True)
    if len(overlay_text) > 4_200:
        raise SurfaceOverlayRenderError(
            "Airport surface overlay exceeds the Amazon static-map limit."
        )
    params = {
        "key": key,
        "style": "Satellite",
        "width": "700",
        "height": "520",
        "padding": "24",
        "bounding-box": (
            f"{bounds['west']:.7f},{bounds['south']:.7f},"
            f"{bounds['east']:.7f},{bounds['north']:.7f}"
        ),
        "geojson-overlay": overlay_text,
    }
    url = f"{settings.static_map_endpoint}?{urlencode(params)}"
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise SurfaceOverlayRenderError(
            f"Amazon Location static map returned HTTP {response.status_code}."
        )
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type not in {"image/png", "image/jpeg", "image/jpg"}:
        raise SurfaceOverlayRenderError(
            "Amazon Location static map returned an unsupported file."
        )
    extension = ".png" if media_type == "image/png" else ".jpg"
    destination = destination_stem.with_suffix(extension)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    return {
        "provider": "aws-location-static",
        "mode": "static",
        "style": "Satellite",
        "image_path": str(destination),
        "media_type": media_type,
        "label": "Amazon Location Satellite + validated CFP surface overlay",
    }


async def attach_surface_report_maps(
    analysis_id: str,
    overlays: list[dict[str, Any]],
    settings: MapSettings,
    *,
    output_dir: Path | None = None,
) -> list[dict[str, Any]]:
    directory = output_dir or SURFACE_MAP_DIR
    prepared: list[dict[str, Any]] = []
    for overlay in overlays:
        item = dict(overlay)
        stem = directory / f"{analysis_id}_{item['role']}_{item['icao']}_surface"
        try:
            item["report_map"] = await render_surface_static_map(
                item,
                settings,
                stem,
            )
        except (SurfaceOverlayRenderError, httpx.HTTPError) as exc:
            item["report_map"] = {
                "provider": "openstreetmap",
                "mode": "schematic-fallback",
                "style": "schematic",
                "image_path": None,
                "media_type": None,
                "label": "Validated OSM surface schematic; live basemap unavailable",
                "warning": str(exc),
            }
        prepared.append(item)
    return prepared


__all__ = [
    "SurfaceOverlayRequest",
    "attach_surface_report_maps",
    "surface_mark_presentation",
    "validated_surface_overlays",
]
