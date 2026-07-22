from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..config import DATA_DIR
from ..database import get_flight_by_analysis_id
from ..odss.reporting import render_pdf
from .aws_location import AwsLocationStaticRenderer
from .config import MapSettings
from .contract import MapContract
from .geojson import build_map_contract
from .renderers import MapRenderResult, RendererChain
from .schematic import SchematicSvgRenderer
from .snapshot import PlaywrightMapSnapshotRenderer

MAP_DIR = DATA_DIR / "maps"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read ODSS analysis JSON: {path}") from exc


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _contract_for(analysis_id: str, analysis: dict[str, Any], settings: MapSettings) -> MapContract:
    stored = analysis.get("map_contract")
    if stored:
        contract = MapContract.model_validate(stored)
    else:
        contract = build_map_contract(
            analysis.get("flight") or {},
            analysis.get("findings") or [],
            settings,
        )
    contract.metadata["analysis_id"] = analysis_id
    return contract


def _renderers(settings: MapSettings):
    renderers = [PlaywrightMapSnapshotRenderer(settings)]
    if settings.fallback == "static":
        renderers.append(AwsLocationStaticRenderer(settings))
    if settings.fallback in {"static", "schematic"}:
        renderers.append(SchematicSvgRenderer())
    return renderers


def _artifact_extension(result: MapRenderResult) -> str:
    if result.media_type == "image/png":
        return ".png"
    if result.media_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if result.media_type == "image/svg+xml":
        return ".svg"
    return ".bin"


def _regenerate_reports(
    *,
    analysis: dict[str, Any],
    level1_path: Path,
    level2_path: Path,
    map_result: MapRenderResult,
    map_path: Path,
) -> bool:
    """Regenerate reports only when ReportLab can embed the map artifact.

    The last-resort schematic renderer returns SVG. Existing ODSS reports already
    contain a clearly labelled schematic map, so the worker preserves those files
    rather than introducing a second SVG conversion dependency.
    """
    if map_result.media_type not in {"image/png", "image/jpeg", "image/jpg"}:
        return False

    flight = analysis.get("flight") or {}
    findings = analysis.get("findings") or []
    warnings = (analysis.get("view") or {}).get("warnings") or []

    for level, destination in ((1, level1_path), (2, level2_path)):
        temporary = destination.with_suffix(destination.suffix + ".map.tmp")
        render_pdf(
            flight,
            findings,
            warnings,
            level,
            temporary,
            map_image_path=map_path,
            map_label=map_result.label,
        )
        temporary.replace(destination)
    return True


async def render_reports_for_analysis(
    analysis_id: str,
    *,
    settings: MapSettings | None = None,
    width: int = 1600,
    height: int = 900,
) -> dict[str, Any]:
    """Capture the canonical ODSS map and refresh both report levels.

    This worker is intentionally separate from the browser client. It consumes
    the stored ODSS analysis and map contract; no deterministic aviation finding
    is recalculated in React or in the report renderer.
    """
    settings = settings or MapSettings.from_env()
    flight_row = get_flight_by_analysis_id(analysis_id)
    if not flight_row:
        raise LookupError(f"Analysis {analysis_id} was not found")
    if not flight_row["analysis_path"]:
        raise RuntimeError(f"Analysis {analysis_id} is not complete")

    analysis_path = Path(str(flight_row["analysis_path"]))
    analysis = _load_json(analysis_path)
    contract = _contract_for(analysis_id, analysis, settings)

    result = await RendererChain(*_renderers(settings)).render_snapshot(
        contract,
        width=max(800, min(int(width), 4096)),
        height=max(450, min(int(height), 2160)),
    )

    MAP_DIR.mkdir(parents=True, exist_ok=True)
    extension = _artifact_extension(result)
    map_path = MAP_DIR / f"{analysis_id}_{contract.route_hash[:16]}{extension}"
    result.write(map_path)

    level1_path = Path(str(flight_row["level1_report"]))
    level2_path = Path(str(flight_row["level2_report"]))
    reports_refreshed = _regenerate_reports(
        analysis=analysis,
        level1_path=level1_path,
        level2_path=level2_path,
        map_result=result,
        map_path=map_path,
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    render_metadata = {
        "provider": result.provider,
        "mode": result.mode,
        "media_type": result.media_type,
        "label": result.label,
        "route_hash": contract.route_hash,
        "artifact_path": str(map_path),
        "generated_at_utc": generated_at,
        "reports_refreshed": reports_refreshed,
        "warnings": result.warnings,
        **result.metadata,
    }
    analysis["schema_version"] = "0.6.1"
    analysis["map_contract"] = contract.public_dict()
    analysis.setdefault("view", {})["map_render"] = render_metadata
    _atomic_json_write(analysis_path, analysis)
    return render_metadata


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture the ODSS MapLibre map and regenerate Level 1/2 reports."
    )
    parser.add_argument("analysis_id")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = asyncio.run(
        render_reports_for_analysis(
            args.analysis_id,
            width=args.width,
            height=args.height,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
