"""ODSS WSSS airport-surface NOTAM proof of concept.

The official NOTAM is authoritative for operational status.  The OpenStreetMap
snapshot supplies candidate airport-surface geometry only.
"""

from .contract import build_surface_contract
from .notam import parse_notam_fields, parse_surface_clauses
from .osm import SurfaceGraph, load_snapshot
from .resolver import resolve_surface_notam

__all__ = [
    "SurfaceGraph",
    "build_surface_contract",
    "load_snapshot",
    "parse_notam_fields",
    "parse_surface_clauses",
    "resolve_surface_notam",
]
