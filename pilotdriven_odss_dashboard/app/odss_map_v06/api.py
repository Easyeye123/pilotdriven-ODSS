from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from .aws_location import AwsLocationInteractiveRenderer, AwsLocationStaticRenderer
from .config import MapSettings
from .contract import MapContract
from .geojson import build_map_contract
from .renderers import RendererChain
from .schematic import SchematicSvgRenderer


AnalysisLoader = Callable[[str], dict[str, Any] | None]


def create_map_router(
    *,
    load_analysis: AnalysisLoader,
    templates: Jinja2Templates,
    settings: MapSettings,
) -> APIRouter:
    """Create versioned map endpoints without coupling to ODSS persistence."""
    router = APIRouter(tags=["odss-map-v06"])
    interactive = AwsLocationInteractiveRenderer(settings)

    def contract_for(analysis_id: str):
        analysis = load_analysis(analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
        stored_contract = analysis.get("map_contract")
        if stored_contract:
            contract = MapContract.model_validate(stored_contract)
        else:
            flight = analysis.get("flight") or {}
            findings = analysis.get("findings") or []
            contract = build_map_contract(flight, findings, settings)
        contract.metadata["analysis_id"] = analysis_id
        return contract

    @router.get("/v1/analyses/{analysis_id}/map-contract")
    async def map_contract(analysis_id: str) -> JSONResponse:
        return JSONResponse(contract_for(analysis_id).public_dict())

    @router.get("/v1/analyses/{analysis_id}/route.geojson")
    async def route_geojson(analysis_id: str) -> JSONResponse:
        return JSONResponse(contract_for(analysis_id).route_geojson)

    @router.get("/v1/analyses/{analysis_id}/markers.geojson")
    async def marker_geojson(analysis_id: str) -> JSONResponse:
        return JSONResponse(contract_for(analysis_id).markers_geojson)

    @router.get("/v1/analyses/{analysis_id}/hazards.geojson")
    async def hazard_geojson(analysis_id: str) -> JSONResponse:
        return JSONResponse(contract_for(analysis_id).hazards_geojson)

    @router.get("/v1/analyses/{analysis_id}/map-config")
    async def map_config(analysis_id: str) -> JSONResponse:
        contract = contract_for(analysis_id)
        try:
            payload = await interactive.interactive_config(contract)
            payload["fallback"] = contract.fallback
            payload["fallback_url"] = f"/v1/analyses/{analysis_id}/map-fallback"
            payload["warnings"] = contract.warnings
            return JSONResponse(payload)
        except Exception as exc:
            return JSONResponse(
                {
                    "provider": "schematic",
                    "route_hash": contract.route_hash,
                    "fallback": contract.fallback,
                    "fallback_url": f"/v1/analyses/{analysis_id}/map-fallback",
                    "warnings": [
                        *contract.warnings,
                        f"Primary map unavailable: {type(exc).__name__}: {exc}",
                    ],
                }
            )

    @router.get("/v1/analyses/{analysis_id}/map-fallback")
    async def map_fallback(
        analysis_id: str,
        width: int = 1600,
        height: int = 900,
    ) -> Response:
        contract = contract_for(analysis_id)
        renderers = []
        if settings.fallback == "static":
            renderers.append(AwsLocationStaticRenderer(settings))
        if settings.fallback in {"static", "schematic"}:
            renderers.append(SchematicSvgRenderer())
        if not renderers:
            raise HTTPException(status_code=503, detail="Map fallback is disabled")
        result = await RendererChain(*renderers).render_snapshot(
            contract,
            width=max(800, min(width, 4096)),
            height=max(450, min(height, 2160)),
        )
        return Response(
            result.content,
            media_type=result.media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-ODSS-Map-Mode": result.mode,
                "X-ODSS-Map-Label": result.label.replace("—", "-"),
                "X-ODSS-Route-Hash": contract.route_hash,
            },
        )

    @router.get(
        "/render/maps/{analysis_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def print_map(
        request: Request,
        analysis_id: str,
        route_hash: str | None = None,
    ) -> HTMLResponse:
        contract = contract_for(analysis_id)
        if route_hash and route_hash != contract.route_hash:
            raise HTTPException(
                status_code=409,
                detail="Route hash no longer matches this analysis",
            )
        config = await interactive.interactive_config(contract)
        return templates.TemplateResponse(
            request=request,
            name="map_print_v06.html",
            context={
                "analysis_id": analysis_id,
                "map_config": config,
                "contract": contract.public_dict(),
            },
        )

    return router
