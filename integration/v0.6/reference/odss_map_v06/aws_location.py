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
            "hazards": contract.hazards_geojson,
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
        key = self.settings.static_map_api_key
        if not key:
            raise MapRenderError("AWS Location API key is not configured")

        # ``map@2x`` accepts logical dimensions up to 700px and returns a
        # double-density image. Passing 800/1600 here causes a hard HTTP 400.
        width = max(64, min(int(width), 700))
        height = max(64, min(int(height), 700))
        overlay = _static_overlay(contract)
        overlay_text = json.dumps(
            overlay,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(overlay_text) > 4200:
            overlay = _static_overlay(contract, marker_limit=4)
            overlay_text = json.dumps(
                overlay,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        if len(overlay_text) > 4200:
            raise MapRenderError(
                "Static map GeoJSON overlay exceeds the 4,200-character limit"
            )

        params = {
            "key": key,
            "style": "Satellite",
            "width": str(width),
            "height": str(height),
            "padding": str(max(12, min(width, height) // 20)),
            "bounded-positions": _bounded_positions(contract),
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
    for hazard in contract.hazards_geojson.get("features", [])[:4]:
        features.append({
            "type": "Feature",
            "geometry": hazard.get("geometry") or {},
            "properties": {
                "color": "#FFB84D",
                "width": 2,
                "fill-color": "#FF6B6B",
                "fill-opacity": 0.30,
            },
        })
    for route in route_features[:1]:
        copied = {
            "type": "Feature",
            "geometry": route["geometry"],
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


def _bounded_positions(contract: MapContract) -> str:
    coordinates: list[str] = []
    for feature in contract.markers_geojson.get("features", []):
        geometry = feature.get("geometry", {})
        values = geometry.get("coordinates")
        if (
            geometry.get("type") == "Point"
            and isinstance(values, list)
            and len(values) >= 2
        ):
            coordinates.append(f"{float(values[0]):.6f},{float(values[1]):.6f}")
    if len(coordinates) < 2:
        raise MapRenderError("Static map requires at least two bounded positions")
    return ",".join(coordinates)


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
