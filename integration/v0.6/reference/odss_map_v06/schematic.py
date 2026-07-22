from __future__ import annotations

from html import escape
from typing import Any

from .contract import MapContract
from .renderers import MapRenderResult


class SchematicSvgRenderer:
    """Last-resort offline renderer.

    This is intentionally labelled and must never masquerade as the primary
    realistic map. It returns SVG bytes so the current ReportLab/dashboard
    adapter can continue to use its existing schematic route display.
    """

    name = "schematic-offline"

    async def interactive_config(
        self,
        contract: MapContract,
    ) -> dict[str, Any]:
        return {
            "provider": self.name,
            "route": contract.route_geojson,
            "markers": contract.markers_geojson,
            "hazards": contract.hazards_geojson,
            "label": "Schematic route display — basemap unavailable",
        }

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        svg = _render_svg(contract, width=max(800, width), height=max(450, height))
        return MapRenderResult(
            provider=self.name,
            mode="schematic-fallback",
            content=svg.encode("utf-8"),
            media_type="image/svg+xml",
            label="Schematic route display — basemap unavailable",
            warnings=[
                *contract.warnings,
                "Primary and static basemap renderers were unavailable.",
            ],
            metadata={"route_hash": contract.route_hash},
        )


def _render_svg(contract: MapContract, *, width: int, height: int) -> str:
    markers = contract.markers_geojson.get("features", [])
    if len(markers) < 2:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            '<rect width="100%" height="100%" fill="#07111f"/>'
            '<text x="50%" y="50%" fill="#93a4b8" text-anchor="middle">'
            'Route unavailable</text></svg>'
        )

    west = contract.bounds.west
    east = contract.bounds.east
    south = contract.bounds.south
    north = contract.bounds.north
    span_x = max(east - west, 0.1)
    span_y = max(north - south, 0.1)

    def project(coordinates: list[float]) -> tuple[float, float]:
        lon, lat = coordinates
        x = 30 + (lon - west) / span_x * (width - 60)
        y = height - 30 - (lat - south) / span_y * (height - 60)
        return x, y

    projected = [
        project(feature["geometry"]["coordinates"])
        for feature in markers
    ]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in projected)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" rx="12" fill="#07111f"/>',
    ]
    for feature in contract.hazards_geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinate_sets = geometry.get("coordinates") or []
        polygons = [coordinate_sets] if geometry.get("type") == "Polygon" else coordinate_sets
        for polygon in polygons:
            if not polygon:
                continue
            ring = polygon[0]
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (project(item) for item in ring))
            parts.append(
                f'<polygon points="{points}" fill="#ff6b6b" fill-opacity="0.30" '
                'stroke="#ffb84d" stroke-width="2"/>'
            )
    parts.append(
        f'<polyline points="{polyline}" fill="none" stroke="#dceeff" '
        'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    selected = set(contract.priority_labels)
    for feature, (x, y) in zip(markers, projected):
        props = feature.get("properties", {})
        name = str(props.get("name") or "")
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
            'fill="#4db8ff" stroke="#07111f" stroke-width="2"/>'
        )
        if name in selected:
            parts.append(
                f'<text x="{x + 7:.1f}" y="{y - 7:.1f}" '
                'fill="#e8f2ff" font-family="Arial" font-size="13">'
                f'{escape(name)}</text>'
            )
    parts.append(
        f'<text x="16" y="{height - 12}" fill="#ffb84d" '
        'font-family="Arial" font-size="12">'
        'Schematic route display — basemap unavailable</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
