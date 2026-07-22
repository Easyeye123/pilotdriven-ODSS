from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import MapSettings
from .contract import MapContract
from .renderers import MapRenderError, MapRenderResult


class AwsLocationInteractiveRenderer:
    name = "aws-location-maplibre"

    def __init__(self, settings: MapSettings):
        self.settings = settings

    async def interactive_config(
        self,
        contract: MapContract,
    ) -> dict[str, Any]:
        style_url = self.settings.style_descriptor_url
        if not style_url:
            raise MapRenderError("AWS Location API key is not configured")
        return {
            "provider": self.name,
            "style_url": style_url,
            "route": contract.route_geojson,
            "markers": contract.markers_geojson,
            "bounds": contract.bounds.model_dump(),
            "priority_labels": contract.priority_labels,
            "route_hash": contract.route_hash,
            "attribution": contract.attribution,
        }

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        raise MapRenderError(
            "Interactive renderer requires the Playwright snapshot adapter"
        )


class AwsLocationStaticRenderer:
    """Fallback renderer using Amazon Location Maps V2 GetStaticMap.

    Hybrid is not supported by the static API. Satellite is used for the
    realistic fallback and the route/selected markers are supplied as a
    compact GeoJSON overlay.
    """

    name = "aws-location-static"

    def __init__(
        self,
        settings: MapSettings,
        *,
        timeout_seconds: float = 20.0,
    ):
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    async def interactive_config(
        self,
        contract: MapContract,
    ) -> dict[str, Any]:
        raise MapRenderError("Static renderer has no interactive config")

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        key = self.settings.aws_location_api_key
        if not key:
            raise MapRenderError("AWS Location API key is not configured")

        width = max(64, min(int(width), 1400))
        height = max(64, min(int(height), 1400))
        overlay = None
        overlay_text = ""
        # The canonical route can contain hundreds of points. Static-map
        # overlays have a 4,200-character limit, so presentation geometry is
        # progressively simplified while preserving route order and endpoints.
        for route_point_limit, marker_limit in (
            (100, 12),
            (80, 12),
            (60, 8),
            (40, 6),
            (30, 4),
            (20, 2),
        ):
            candidate = _static_overlay(
                contract,
                marker_limit=marker_limit,
                route_point_limit=route_point_limit,
            )
            candidate_text = json.dumps(
                candidate,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            if len(candidate_text) <= 4200:
                overlay = candidate
                overlay_text = candidate_text
                break
        if overlay is None:
            raise MapRenderError(
                "Static map GeoJSON overlay exceeds the 4,200-character limit"
            )

        params = {
            "key": key,
            "style": "Satellite",
            "width": str(width),
            "height": str(height),
            "lang": self.settings.language,
            "padding": str(max(12, min(width, height) // 20)),
            "crop-labels": "true",
            "pois": "Disabled",
            "bounding-box": _bounding_box(contract),
            "geojson-overlay": overlay_text,
        }
        url = f"{self.settings.static_map_endpoint}?{urlencode(params)}"
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise MapRenderError(
                    f"GetStaticMap returned HTTP {response.status_code}"
                )
            content_type = response.headers.get(
                "content-type",
                "image/jpeg",
            )
            if not content_type.startswith("image/"):
                raise MapRenderError(
                    f"GetStaticMap returned unexpected content type {content_type}"
                )
            return MapRenderResult(
                provider=self.name,
                mode="static-fallback",
                content=response.content,
                media_type=content_type,
                label=(
                    "Static map fallback — Hybrid print rendering unavailable"
                ),
                warnings=list(contract.warnings),
                metadata={
                    "route_hash": contract.route_hash,
                    "style": "Satellite",
                },
            )


def _static_overlay(
    contract: MapContract,
    *,
    marker_limit: int = 12,
    route_point_limit: int = 100,
) -> dict[str, Any]:
    """Create a compact overlay that remains below AWS's size limit."""
    route_features = contract.route_geojson.get("features", [])
    selected = set(contract.priority_labels)
    markers = [
        feature
        for feature in contract.markers_geojson.get("features", [])
        if feature.get("properties", {}).get("name") in selected
    ][:marker_limit]

    features = []
    for route in route_features[:1]:
        copied = {
            "type": "Feature",
            "geometry": _simplify_route_geometry(
                route["geometry"],
                max_points=max(2, route_point_limit),
            ),
            "properties": {
                "color": "#F4FAFF",
                "width": 5,
                "outline-color": "#173B65",
                "outline-width": 2,
            },
        }
        features.append(copied)

    for marker in markers:
        props = marker.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "geometry": marker["geometry"],
                "properties": {
                    "label": str(props.get("name") or "")[:12],
                    "color": _marker_colour(str(props.get("role") or "route")),
                    "size": "small",
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _bounding_box(contract: MapContract) -> str:
    bounds = contract.bounds
    return (
        f"{bounds.west:.6f},{bounds.south:.6f},"
        f"{bounds.east:.6f},{bounds.north:.6f}"
    )


def _simplify_route_geometry(geometry: dict[str, Any], *, max_points: int) -> dict[str, Any]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coordinates, list):
        return {
            "type": "LineString",
            "coordinates": _sample_coordinates(coordinates, max_points),
        }
    if geometry_type == "MultiLineString" and isinstance(coordinates, list):
        segments = [segment for segment in coordinates if isinstance(segment, list)]
        total = sum(len(segment) for segment in segments) or 1
        simplified = []
        for segment in segments:
            allocation = max(2, round(max_points * len(segment) / total))
            simplified.append(_sample_coordinates(segment, allocation))
        return {"type": "MultiLineString", "coordinates": simplified}
    return geometry


def _sample_coordinates(coordinates: list[Any], maximum: int) -> list[Any]:
    if len(coordinates) <= maximum or maximum < 2:
        return coordinates
    indices: list[int] = []
    for position in range(maximum):
        index = round(position * (len(coordinates) - 1) / (maximum - 1))
        if not indices or index != indices[-1]:
            indices.append(index)
    return [coordinates[index] for index in indices]


def _marker_colour(role: str) -> str:
    return {
        "departure": "#4DB8FF",
        "destination": "#4DB8FF",
        "bobcat": "#FFB84D",
        "kabul": "#FF6B6B",
        "early_contact": "#B38CFF",
        "edto_entry": "#55D6BE",
        "edto_etp": "#55D6BE",
        "edto_exit": "#55D6BE",
        "depressurisation_critical": "#FF7F66",
        "terrain_critical": "#FF7F66",
    }.get(role, "#DCEEFF")
