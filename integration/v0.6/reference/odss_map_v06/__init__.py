"""ODSS v0.6 map-contract and renderer reference package.

This package is intentionally independent of the current Jinja dashboard.
It is the integration boundary intended for the future PilotDriven application.
"""

from .config import MapSettings
from .contract import MapBounds, MapContract
from .geojson import build_map_contract
from .renderers import MapRenderError, MapRenderResult, MapRenderer, RendererChain

__all__ = [
    "MapBounds",
    "MapContract",
    "MapRenderError",
    "MapRenderResult",
    "MapRenderer",
    "MapSettings",
    "RendererChain",
    "build_map_contract",
]
