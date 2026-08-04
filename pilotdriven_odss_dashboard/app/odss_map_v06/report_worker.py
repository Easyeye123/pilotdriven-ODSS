from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

from ..config import DATA_DIR
from ..database import (
    claim_analysis,
    get_flight_by_analysis_id,
    restore_analysis_state,
    set_report_refresh_state,
)
from ..odss.reporting import render_pdf
from .aws_location import AwsLocationStaticRenderer
from .config import MapSettings
from .contract import MapContract
from .geojson import build_map_contract
from .renderers import MapRenderResult, RendererChain
from .schematic import SchematicSvgRenderer
from .snapshot import PlaywrightMapSnapshotRenderer

MAP_DIR = DATA_DIR / "maps"
_REPORTLAB_MAP_MEDIA_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/jpg",
})


class ReportRefreshClaimConflict(RuntimeError):
    """Another writer already owns the analysis publication claim."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read ODSS analysis JSON: {path}") from exc


def _stage_json_artifact(path: Path, payload: dict[str, Any]) -> Path:
    temporary = path.with_name(
        f".{path.name}.publication-stage-{uuid.uuid4().hex}"
    )
    try:
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _record_current_report_refresh(analysis_path: Path) -> None:
    analysis = _load_json(analysis_path)
    view = analysis.setdefault("view", {})
    prior_refresh = view.get("report_refresh") or {}
    prior_warning = prior_refresh.get("warning")
    if prior_warning:
        view["warnings"] = [
            warning
            for warning in (view.get("warnings") or [])
            if warning != prior_warning
        ]
    view["report_refresh"] = {
        "state": "current",
        "reports_current": True,
        "warning": None,
    }
    staged = _stage_json_artifact(analysis_path, analysis)
    publish_staged_artifacts([(staged, analysis_path)])


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


def _renderers(settings: MapSettings, *, tenant_id: str, user_id: str):
    renderers = [
        PlaywrightMapSnapshotRenderer(
            settings,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    ]
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


def publish_staged_artifacts(
    artifacts: list[tuple[Path, Path]],
) -> None:
    """Publish one artifact set with rollback if any rename fails.

    Callers hold the per-analysis Processing claim while this runs, so report
    and profile endpoints cannot observe the short backup/swap window.
    """
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for staged, destination in artifacts:
            if not staged.is_file():
                raise OSError(f"Staged artifact is unavailable: {staged}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = destination.with_name(
                    f"{destination.name}.publication-backup-{uuid.uuid4().hex}"
                )
                destination.replace(backup)
                backups.append((destination, backup))
        for staged, destination in artifacts:
            staged.replace(destination)
            published.append(destination)
    except Exception as exc:
        rollback_errors: list[str] = []
        for destination in reversed(published):
            try:
                destination.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for destination, backup in reversed(backups):
            try:
                if backup.exists():
                    backup.replace(destination)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise RuntimeError(
                "Artifact publication failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    else:
        for _destination, backup in backups:
            backup.unlink(missing_ok=True)
    finally:
        for staged, _destination in artifacts:
            staged.unlink(missing_ok=True)


def _regenerate_reports(
    *,
    analysis: dict[str, Any],
    level1_path: Path,
    level2_path: Path,
    map_result: MapRenderResult,
    map_path: Path,
    additional_staged_artifacts: list[tuple[Path, Path]] | None = None,
    additional_json_artifacts: list[tuple[dict[str, Any], Path]] | None = None,
) -> bool:
    """Regenerate reports only when ReportLab can embed the map artifact.

    The last-resort schematic renderer returns SVG. Existing ODSS reports already
    contain a clearly labelled schematic map, so the worker preserves those files
    rather than introducing a second SVG conversion dependency.
    """
    additional = list(additional_staged_artifacts or [])
    staged_json: list[tuple[Path, Path]] = []

    def stage_json_artifacts() -> None:
        for payload, destination in additional_json_artifacts or []:
            staged_json.append(
                (_stage_json_artifact(destination, payload), destination)
            )

    if map_result.media_type not in _REPORTLAB_MAP_MEDIA_TYPES:
        try:
            stage_json_artifacts()
            if additional or staged_json:
                publish_staged_artifacts(additional + staged_json)
            return False
        finally:
            for temporary, _destination in additional + staged_json:
                temporary.unlink(missing_ok=True)

    flight = analysis.get("flight") or {}
    findings = analysis.get("findings") or []
    view = analysis.get("view") or {}
    resolved_warning = (view.get("report_refresh") or {}).get("warning")
    warnings = [
        warning
        for warning in (view.get("warnings") or [])
        if warning != resolved_warning
    ]

    staged_reports = [
        (
            level,
            destination.with_name(
                f"{destination.name}.{uuid.uuid4().hex}.map.tmp"
            ),
            destination,
        )
        for level, destination in ((1, level1_path), (2, level2_path))
    ]
    try:
        for level, temporary, _destination in staged_reports:
            render_pdf(
                flight,
                findings,
                warnings,
                level,
                temporary,
                map_image_path=map_path,
                map_label=map_result.label,
            )
        # Level 2 rendering records exact governed source-chart page targets
        # on the analysis object. Serialise only after both PDFs render, then
        # publish JSON, PDFs and map as one rollback-capable artifact set.
        stage_json_artifacts()
        publish_staged_artifacts(
            [
                (temporary, destination)
                for _level, temporary, destination in staged_reports
            ]
            + additional
            + staged_json
        )
    finally:
        for _level, temporary, _destination in staged_reports:
            temporary.unlink(missing_ok=True)
        for temporary, _destination in additional:
            temporary.unlink(missing_ok=True)
        for temporary, _destination in staged_json:
            temporary.unlink(missing_ok=True)
    return True


async def render_reports_for_analysis(
    analysis_id: str,
    *,
    tenant_id: str,
    user_id: str,
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
    flight_row = get_flight_by_analysis_id(analysis_id, tenant_id)
    if not flight_row:
        raise LookupError(f"Analysis {analysis_id} was not found")
    if not flight_row["analysis_path"]:
        raise RuntimeError(f"Analysis {analysis_id} is not complete")

    analysis_path = Path(str(flight_row["analysis_path"]))
    analysis = _load_json(analysis_path)
    contract = _contract_for(analysis_id, analysis, settings)

    result = await RendererChain(
        *_renderers(settings, tenant_id=tenant_id, user_id=user_id)
    ).render_snapshot(
        contract,
        width=max(800, min(int(width), 4096)),
        height=max(450, min(int(height), 2160)),
    )

    MAP_DIR.mkdir(parents=True, exist_ok=True)
    extension = _artifact_extension(result)
    map_path = MAP_DIR / f"{analysis_id}_{contract.route_hash[:16]}{extension}"
    staged_map_path = MAP_DIR / (
        f".{analysis_id}_{contract.route_hash[:16]}.{uuid.uuid4().hex}.stage"
        f"{extension}"
    )
    try:
        result.write(staged_map_path)

        level1_path = Path(str(flight_row["level1_report"]))
        level2_path = Path(str(flight_row["level2_report"]))
        reports_will_refresh = result.media_type in _REPORTLAB_MAP_MEDIA_TYPES
        generated_at = datetime.now(timezone.utc).isoformat()
        render_metadata = {
            "provider": result.provider,
            "mode": result.mode,
            "media_type": result.media_type,
            "label": result.label,
            "route_hash": contract.route_hash,
            "artifact_path": str(map_path),
            "generated_at_utc": generated_at,
            "reports_refreshed": reports_will_refresh,
            "warnings": result.warnings,
            **result.metadata,
        }
        analysis["schema_version"] = "0.6.1"
        analysis["map_contract"] = contract.public_dict()
        analysis.setdefault("view", {})["map_render"] = render_metadata
        reports_refreshed = _regenerate_reports(
            analysis=analysis,
            level1_path=level1_path,
            level2_path=level2_path,
            map_result=result,
            map_path=staged_map_path,
            additional_staged_artifacts=[(staged_map_path, map_path)],
            additional_json_artifacts=[(analysis, analysis_path)],
        )
        if reports_refreshed != reports_will_refresh:
            raise RuntimeError("Report refresh publication state is inconsistent")
    finally:
        staged_map_path.unlink(missing_ok=True)
    return render_metadata


async def refresh_reports_for_analysis(
    analysis_id: str,
    *,
    tenant_id: str,
    user_id: str,
    settings: MapSettings | None = None,
    width: int = 1600,
    height: int = 900,
) -> dict[str, Any]:
    """Own the publication claim and finalize report freshness.

    API and CLI callers use this boundary. Internal callers that already hold
    the Processing claim may use :func:`render_reports_for_analysis` directly.
    """
    flight = get_flight_by_analysis_id(analysis_id, tenant_id)
    if not flight:
        raise LookupError(f"Analysis {analysis_id} was not found")
    claimed = claim_analysis(
        int(flight["id"]),
        tenant_id,
        expected_status=str(flight["status"] or ""),
    )
    if claimed is None:
        raise ReportRefreshClaimConflict(
            f"Analysis {analysis_id} is already being updated"
        )
    try:
        result = await render_reports_for_analysis(
            analysis_id,
            tenant_id=tenant_id,
            user_id=user_id,
            settings=settings,
            width=width,
            height=height,
        )
        if result.get("reports_refreshed"):
            analysis_path = Path(str(claimed["analysis_path"]))
            _record_current_report_refresh(analysis_path)
            set_report_refresh_state(
                int(claimed["id"]),
                "current",
                tenant_id=tenant_id,
            )
        return result
    finally:
        restore_analysis_state(
            int(claimed["id"]),
            str(claimed["status"]),
            claimed["notes"],
            claimed["last_error"],
            tenant_id=tenant_id,
            analysis_failure_category=claimed["analysis_failure_category"],
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture the ODSS MapLibre map and regenerate Level 1/2 reports."
    )
    parser.add_argument("analysis_id")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--user-id", default="odss-report-worker")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = asyncio.run(
        refresh_reports_for_analysis(
            args.analysis_id,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            width=args.width,
            height=args.height,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
