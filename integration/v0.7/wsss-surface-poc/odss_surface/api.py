from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .contract import build_surface_contract
from .osm import SurfaceGraph, load_snapshot
from .resolver import resolve_surface_notam

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PACKAGE_ROOT / "fixtures" / "wsss_surface_snapshot.json"
STATIC_ROOT = PACKAGE_ROOT / "static"


class SurfaceResolveRequest(BaseModel):
    notam_text: str = Field(min_length=8, max_length=80_000)
    briefing_time_utc: str | None = None
    aircraft_code: str | None = Field(default=None, pattern=r"^[A-Fa-f]$")
    include_surface_geometry: bool = True


@lru_cache(maxsize=2)
def _load_graph(snapshot_path: str) -> SurfaceGraph:
    return SurfaceGraph(load_snapshot(snapshot_path))


def get_graph() -> SurfaceGraph:
    snapshot = Path(os.environ.get("ODSS_WSSS_SURFACE_SNAPSHOT", DEFAULT_SNAPSHOT))
    if not snapshot.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "The WSSS OSM surface snapshot is not installed. Run scripts/fetch_wsss_osm.py "
                "or set ODSS_WSSS_SURFACE_SNAPSHOT."
            ),
        )
    try:
        return _load_graph(str(snapshot.resolve()))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Unable to load WSSS surface snapshot: {exc}") from exc


router = APIRouter(prefix="/v1/airports/WSSS", tags=["surface-notam-poc"])


@router.get("/surface-geometry")
def surface_geometry():
    graph = get_graph()
    return build_surface_contract(graph, [], include_surface_geometry=True)


@router.post("/surface-resolve")
def surface_resolve(request: SurfaceResolveRequest):
    graph = get_graph()
    try:
        findings = resolve_surface_notam(
            graph,
            request.notam_text,
            briefing_time_utc=request.briefing_time_utc,
            selected_aircraft_code=request.aircraft_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_surface_contract(
        graph,
        findings,
        briefing_time_utc=request.briefing_time_utc,
        include_surface_geometry=request.include_surface_geometry,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="ODSS WSSS Surface NOTAM Proof of Concept",
        version="0.7.0-poc",
        description=(
            "Deterministic WSSS NOTAM-to-OpenStreetMap surface geometry resolver. "
            "The official NOTAM remains authoritative."
        ),
    )
    app.include_router(router)
    if STATIC_ROOT.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

        @app.get("/demo", include_in_schema=False)
        def demo():
            return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/healthz")
    def health():
        snapshot = Path(os.environ.get("ODSS_WSSS_SURFACE_SNAPSHOT", DEFAULT_SNAPSHOT))
        return {
            "status": "ok",
            "snapshot_available": snapshot.is_file(),
            "snapshot_path": str(snapshot),
        }

    return app


app = create_app()
