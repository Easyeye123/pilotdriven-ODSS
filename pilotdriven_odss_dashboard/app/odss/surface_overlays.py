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
MAX_BOUNDARY_RINGS = 32
# Amazon Location's static-map API rejects a ``geojson-overlay`` query value
# longer than this. The 10 Sep 2026 satellite surface map introduced the cap
# with no test; ``fit_static_map_overlay`` now simplifies deterministically
# down to it and fails closed when the runways and marks alone do not fit.
STATIC_MAP_OVERLAY_LIMIT = 4_200


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


def _closed_ring(ring: Any) -> list[tuple[float, float]]:
    """One boundary ring: closed, at least four vertices, enclosing an area."""
    if not isinstance(ring, list) or not all(
        isinstance(point, list)
        and len(point) >= 2
        and isinstance(point[0], (int, float))
        and isinstance(point[1], (int, float))
        for point in ring
    ):
        raise ValueError("An aerodrome boundary ring must be a list of [longitude, latitude] points.")
    points = _coordinate_points(ring)
    if len(points) < 4 or points[0] != points[-1]:
        raise ValueError("An aerodrome boundary ring must be closed with at least four points.")
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += x0 * y1 - x1 * y0
    if abs(area) < 1e-10:
        raise ValueError("An aerodrome boundary ring must enclose an area.")
    return points


class SurfaceAerodromeBoundary(_StrictModel):
    """The exact OSM aerodrome outline the app already computes.

    ``exactAerodromeBoundary`` (PilotDriven ``airport-report-scope.mjs``)
    returns ``{outer: [ring...], inner: [ring...]}`` for the report-eligibility
    test. The same shape is carried here so the figure can stroke the field
    outline instead of floating three runway lines in black space.
    """

    outer: list[list[Any]] = Field(min_length=1, max_length=MAX_BOUNDARY_RINGS)
    inner: list[list[Any]] = Field(default_factory=list, max_length=MAX_BOUNDARY_RINGS)

    @model_validator(mode="after")
    def validate_rings(self):
        for ring in [*self.outer, *self.inner]:
            _closed_ring(ring)
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


SurfaceMarkClass = Literal[
    "closure",
    "shortening",
    "scheduled",
    "equipment",
    "locator",
]
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
    # Optional so a browser still on the previous app bundle publishes as
    # before; when supplied it is the field outline of the figure.
    aerodromeBoundary: SurfaceAerodromeBoundary | None = None
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


class AirportNoteLine(_StrictModel):
    sourceObject: str = Field(min_length=1, max_length=96)
    path: str = Field(min_length=1, max_length=512)
    value: str = Field(min_length=1, max_length=4_000)


class AirportNoteObject(_StrictModel):
    name: str = Field(min_length=1, max_length=96)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AirportNotesPublication(_StrictModel):
    status: Literal["released", "unavailable"]
    message: str = Field(min_length=1, max_length=200)
    releaseStatus: str | None = Field(default=None, max_length=40)
    availabilityStatus: Literal[
        "current",
        "no_current_released_match",
        "source_unavailable",
        "future",
        "expired",
        "withdrawn",
        "review_required",
    ] | None = None
    airportVersion: str | None = Field(default=None, max_length=80)
    cycle: str | None = Field(default=None, max_length=40)
    schemaVersion: str | None = Field(default=None, max_length=40)
    objects: list[AirportNoteObject] = Field(max_length=24)
    lines: list[AirportNoteLine] = Field(max_length=96)
    omittedLineCount: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_release(self):
        if self.status == "released":
            if self.releaseStatus != "released":
                raise ValueError("Released airport notes require released source status.")
            if self.availabilityStatus != "current":
                raise ValueError(
                    "Released airport notes require current availability."
                )
            if not self.airportVersion or not self.cycle or not self.schemaVersion:
                raise ValueError("Released airport notes require package identity and cycle.")
        else:
            if self.availabilityStatus == "current":
                raise ValueError(
                    "Unavailable airport notes cannot claim current availability."
                )
            if self.lines or self.objects:
                raise ValueError("Unavailable airport notes cannot publish package content.")
        return self


class AirportSurfaceIndexWindow(_StrictModel):
    startsAt: str | None = Field(default=None, max_length=64)
    endsAt: str | None = Field(default=None, max_length=64)
    referenceAt: str | None = Field(default=None, max_length=64)
    referenceBasis: str | None = Field(default=None, max_length=120)


class AirportSurfaceIndexEntry(_StrictModel):
    icao: str = Field(pattern=r"^[A-Z]{4}$")
    name: str = Field(default="", max_length=200)
    roles: list[
        Literal[
            "departure",
            "destination",
            "destination_alternate",
            "edto",
            "fuel_enroute",
            "fuel_enroute_airport",
            "enroute",
        ]
    ] = Field(min_length=1, max_length=7)
    roleLabel: str = Field(min_length=1, max_length=160)
    stationStatus: Literal["held", "unavailable", "error"]
    sourceLabel: str = Field(min_length=1, max_length=240)
    window: AirportSurfaceIndexWindow
    notamCount: int = Field(ge=0, le=10_000)
    notes: AirportNotesPublication


class SurfaceOverlayRequest(_StrictModel):
    # The field stays required so an omitted payload cannot clear an analysis by
    # accident. An explicit empty list is the fail-safe clear after a timing
    # refresh can no longer validate the previous marks.
    overlays: list[SurfaceOverlayContract] = Field(max_length=2)
    # Omission means "leave the published index unchanged" so a browser that
    # loaded the previous app bundle cannot erase it while refreshing the two
    # legacy map overlays. An explicit [] remains the deliberate clear.
    # The bound must clear a real ULR station package — SQ38 WSSS-KLAX
    # (29 Aug 2026) filed 39 station airports and the previous cap of 30
    # rejected the whole publication as a 422.
    airport_surface_index: list[AirportSurfaceIndexEntry] | None = Field(
        default=None,
        max_length=64,
    )


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


def validated_airport_surface_index(
    request: SurfaceOverlayRequest,
    flight: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if request.airport_surface_index is None:
        return None
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    departure = str(flight.get("departure") or "").strip().upper()
    destination = str(flight.get("destination") or "").strip().upper()
    for entry in request.airport_surface_index:
        if entry.icao in seen:
            raise ValueError(f"Duplicate {entry.icao} airport surface index entry.")
        seen.add(entry.icao)
        if "departure" in entry.roles and entry.icao != departure:
            raise ValueError("Departure airport surface index does not match the analysed flight.")
        if "destination" in entry.roles and entry.icao != destination:
            raise ValueError("Destination airport surface index does not match the analysed flight.")
        result.append(entry.model_dump(mode="json"))
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
    "shortening": {
        "color": "#F59E0B",
        "width": 7,
        "outline-color": "#78350F",
        "outline-width": 2,
        "fill-color": "#F59E0B",
        "fill-opacity": 0.4,
        "marker-label": "R",
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
    "shortening": 3,
    "closure": 4,
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
    if mark_class == "shortening" and state == "active_at_reference":
        return "shortening"
    if mark_class == "closure" and state == "active_at_reference":
        return "closure"
    # Missing/unknown timing, explicit locator rows, and legacy unclassified
    # rows remain visible only as review locators. They must never become red.
    return "locator"


def _rounded(coordinates: Any, precision: int | None) -> Any:
    if precision is None:
        return coordinates
    if (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        return [round(float(coordinates[0]), precision), round(float(coordinates[1]), precision)]
    if isinstance(coordinates, list):
        return [_rounded(item, precision) for item in coordinates]
    return coordinates


def _styled_surface_overlay(
    contract: dict[str, Any],
    *,
    context_points: int = 16,
    held_points: int = 16,
    keep_context: bool = True,
    precision: int | None = None,
) -> dict[str, Any]:
    """Style the validated overlay for the Amazon Location static map.

    Runways and every marked feature are *held*: they are always emitted.
    Unmarked taxiways, taxilanes and aprons are *context*: they may be thinned
    to ``context_points`` per line or, at ``keep_context=False``, left out so
    the query stays under the provider's byte cap. Polygons are never
    resampled - a ring with vertices removed is a different shape.
    """
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
        properties = feature.get("properties") or {}
        feature_id = str(properties.get("featureId") or "")
        presentation = feature_marks.get(feature_id)
        held = presentation is not None or properties.get("aeroway") == "runway"
        if not held and not keep_context:
            continue
        if geometry_type == "LineString" and isinstance(coordinates, list):
            geometry = {
                "type": "LineString",
                "coordinates": _rounded(
                    _sample_line(coordinates, held_points if held else context_points),
                    precision,
                ),
            }
        elif geometry_type == "Polygon":
            geometry = {
                "type": "Polygon",
                "coordinates": _rounded(coordinates, precision),
            }
        else:
            continue
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


# The simplification ladder, in order. Each rung is (name, context points per
# line, held points per line, keep context, coordinate decimals). The first
# rung is byte-identical to the unsimplified overlay so an overlay that fits
# is sent exactly as validated; six decimals is about 0.1 m, finer than the
# 700 px satellite image can show.
_STATIC_MAP_RUNGS: tuple[tuple[str, int, int, bool, int | None], ...] = (
    ("full", 16, 16, True, None),
    ("rounded", 16, 16, True, 6),
    ("context-8", 8, 16, True, 6),
    ("context-4", 4, 16, True, 6),
    ("context-2", 2, 16, True, 6),
    ("held-only", 2, 16, False, 6),
    ("held-8", 2, 8, False, 6),
    ("held-4", 2, 4, False, 6),
)


def _encode_overlay(overlay: dict[str, Any]) -> str:
    return json.dumps(overlay, separators=(",", ":"), ensure_ascii=True)


def fit_static_map_overlay(
    contract: dict[str, Any],
    *,
    limit: int = STATIC_MAP_OVERLAY_LIMIT,
) -> tuple[str, dict[str, Any]]:
    """Encode the styled overlay within the provider's byte cap.

    Deterministic: the same contract always takes the same rung. Runways,
    marked features and their markers are never dropped; when they alone do
    not fit, the satellite render is refused (``SurfaceOverlayRenderError``)
    and the validated schematic stands. Thinning a picture is acceptable;
    losing a closure from it is not.
    """
    feature_ids = {
        str(feature_id)
        for match in contract.get("mapped") or []
        if surface_mark_presentation(match) is not None
        for feature_id in match.get("featureIds") or []
    }
    source_features = (contract.get("featureCollection") or {}).get("features") or []
    runways = sum(
        (feature.get("properties") or {}).get("aeroway") == "runway"
        for feature in source_features
    )
    marked = sum(
        str((feature.get("properties") or {}).get("featureId") or "") in feature_ids
        and (feature.get("properties") or {}).get("aeroway") != "runway"
        for feature in source_features
    )
    for name, context_points, held_points, keep_context, precision in _STATIC_MAP_RUNGS:
        overlay = _styled_surface_overlay(
            contract,
            context_points=context_points,
            held_points=held_points,
            keep_context=keep_context,
            precision=precision,
        )
        text = _encode_overlay(overlay)
        if len(text.encode("utf-8")) <= limit:
            lines = [
                feature for feature in overlay["features"]
                if feature["geometry"]["type"] != "Point"
            ]
            return text, {
                "bytes": len(text),
                "limit": limit,
                "rung": name,
                "kept": {
                    "runways": runways,
                    "marked": marked,
                    "context": max(0, len(lines) - runways - marked),
                    "markers": len(overlay["features"]) - len(lines),
                },
            }
    raise SurfaceOverlayRenderError(
        "Airport surface overlay exceeds the Amazon static-map limit even with "
        "context removed; the runways and marks are not thinned further."
    )


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

    overlay_text, overlay_receipt = fit_static_map_overlay(contract)
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
        "label": "Amazon Location Satellite + validated OFP surface overlay",
        "overlay": overlay_receipt,
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
    "STATIC_MAP_OVERLAY_LIMIT",
    "SurfaceAerodromeBoundary",
    "SurfaceOverlayRequest",
    "validated_airport_surface_index",
    "attach_surface_report_maps",
    "fit_static_map_overlay",
    "surface_mark_presentation",
    "validated_surface_overlays",
]
