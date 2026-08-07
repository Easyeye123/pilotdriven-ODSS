from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from hashlib import sha256
from contextlib import asynccontextmanager
import json
import logging
import os
import secrets
import sqlite3
from pathlib import Path
import traceback
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .analysis import (
    CfpParseRejectedError,
    REPORT_REFRESH_WARNING,
    ReportRenderingFailure,
    infer_metadata,
    load_analysis,
    run_odss_analysis,
)
from .config import APP_VERSION, BASE_DIR, DATA_DIR
from .database import (
    attach_report,
    claim_analysis,
    complete_analysis,
    create_flight,
    create_personal_note,
    delete_personal_note,
    get_flight_by_analysis_id,
    get_flight_by_service_request,
    get_flight_for_tenant,
    get_personal_note,
    init_db,
    list_flights,
    record_audit_event,
    restore_analysis_snapshot,
    restore_personal_note,
    restore_analysis_state,
    save_level3_answer,
    list_personal_notes,
    save_timing_reference,
    update_personal_note,
    update_status,
)
from .odss.constants import format_actm
from .odss.controlled_library import DEPRESS_LIBRARY_METADATA
from .odss.weather_charts import extract_chart_image
from .odss.level3 import generate_level3_artifacts
from .odss.profile_chart_delivery import (
    held_profile_chart,
    render_held_profile_chart_page,
)
from .odss.combined_brief import render_combined_briefing
from .odss.reporting import render_pdf
from .odss.surface_overlays import (
    SurfaceOverlayRequest,
    attach_surface_report_maps,
    validated_surface_overlays,
)
from .odss_map_v06.api import (
    create_map_router,
    fallback_map_response,
    interactive_map_payload,
    map_contract_from_analysis,
)
from .odss_map_v06.config import MapSettings
from .odss_map_v06.report_worker import (
    ReportRefreshClaimConflict,
    publish_staged_artifacts,
    refresh_reports_for_analysis,
    render_reports_for_analysis,
)
from .odss.parser import validate_pdf
from .odss.pilot_briefing import select_pertinent_notams
from .odss.timing import (
    combine_utc_date_time,
    derive_timing_reference,
    display_utc,
    parse_utc,
)
from .personal_notes import (
    PERSONAL_NOTE_PLACEMENT_LABELS,
    serialise_personal_note,
    validate_personal_note,
)
from .service_identity import (
    ServiceIdentity,
    request_service_identity,
    service_identity_from_request,
)

UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
RESULT_DIR = DATA_DIR / "results"
TEMPLATE_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"
MAX_PDF_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
AUTH_REALM = "PilotDriven ODSS"

logger = logging.getLogger(__name__)


def _configured_auth() -> tuple[str, str] | None:
    username = os.environ.get("ODSS_USERNAME")
    password = os.environ.get("ODSS_PASSWORD")
    if username is None and password is None:
        return None
    if not username or not password:
        raise RuntimeError("ODSS_USERNAME and ODSS_PASSWORD must both be configured.")
    return username, password


def _configured_service_token() -> str | None:
    return os.environ.get("ODSS_SERVICE_TOKEN", "").strip() or None


def _dashboard_tenant_id() -> str:
    tenant_id = os.environ.get(
        "ODSS_LEGACY_DASHBOARD_TENANT_ID",
        "personal-dashboard",
    ).strip()
    if not tenant_id or len(tenant_id) > 64 or not all(
        character.isalnum() or character in "._:-"
        for character in tenant_id
    ):
        raise RuntimeError("ODSS_LEGACY_DASHBOARD_TENANT_ID is invalid.")
    controlled_tenant = _controlled_library_tenant_id()
    if controlled_tenant and tenant_id != controlled_tenant:
        raise RuntimeError(
            "ODSS_LEGACY_DASHBOARD_TENANT_ID does not match the controlled "
            "profile library tenant."
        )
    return tenant_id


def _controlled_library_tenant_id() -> str | None:
    if DEPRESS_LIBRARY_METADATA.get("status") != "controlled-index-loaded":
        return None
    return str(DEPRESS_LIBRARY_METADATA.get("tenant_id") or "").strip() or None


def _legacy_dashboard_enabled() -> bool:
    configured = os.environ.get("ODSS_ENABLE_LEGACY_DASHBOARD")
    if configured is not None:
        return configured.strip().casefold() in {"1", "true", "yes", "on"}
    # A service deployment is API-only unless an administrator explicitly
    # enables the separately tenant-scoped legacy dashboard.
    return _configured_service_token() is None


def _is_service_path(path: str) -> bool:
    return path == "/v1/health" or path.startswith("/v1/") or path.startswith("/render/maps/")


def _is_service_authorized(request: Request, token: str) -> bool:
    scheme, separator, value = request.headers.get("authorization", "").partition(" ")
    return (
        separator == " "
        and scheme.lower() == "bearer"
        and secrets.compare_digest(value, token)
    )


def _is_authorized(request: Request, username: str, password: str) -> bool:
    scheme, separator, token = request.headers.get("authorization", "").partition(" ")
    if separator != " " or scheme.lower() != "basic":
        return False
    expected = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return secrets.compare_digest(token, expected)


def _is_trusted_write_request(request: Request) -> bool:
    fetch_site = request.headers.get("sec-fetch-site", "").casefold()
    if fetch_site == "same-origin":
        return True
    if fetch_site in {"same-site", "cross-site"}:
        return False

    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc.casefold() == request.headers.get("host", "").casefold()


def _secure_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    _configured_auth()
    MapSettings.from_env()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="PilotDriven ODSS Personal Dashboard", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
map_settings = MapSettings.from_env()


@app.middleware("http")
async def protect_dashboard(request: Request, call_next):
    if request.url.path == "/healthz":
        return _secure_response(await call_next(request))
    if _is_service_path(request.url.path):
        token = _configured_service_token()
        if not token:
            return _secure_response(
                PlainTextResponse("ODSS service authentication is not configured.", status_code=503)
            )
        if not _is_service_authorized(request, token):
            return _secure_response(
                PlainTextResponse("ODSS service authentication required.", status_code=401)
            )
        if request.url.path != "/v1/health":
            try:
                identity = service_identity_from_request(request)
            except HTTPException as exc:
                return _secure_response(
                    JSONResponse(
                        {"detail": exc.detail},
                        status_code=exc.status_code,
                    )
                )
            controlled_tenant = _controlled_library_tenant_id()
            if controlled_tenant and identity.tenant_id != controlled_tenant:
                return _secure_response(
                    JSONResponse(
                        {
                            "detail": (
                                "The controlled profile library is not "
                                "configured for this tenant."
                            )
                        },
                        status_code=403,
                    )
                )
            request.state.service_identity = identity
        return _secure_response(await call_next(request))

    # The protected print page loads same-origin static assets. A worker's
    # bearer header may therefore authorize static files without weakening the
    # Basic-auth dashboard.
    if request.url.path.startswith("/static/"):
        token = _configured_service_token()
        if token and _is_service_authorized(request, token):
            return _secure_response(await call_next(request))
    if not _legacy_dashboard_enabled():
        return _secure_response(PlainTextResponse("Not found.", status_code=404))
    try:
        credentials = _configured_auth()
    except RuntimeError:
        return _secure_response(
            PlainTextResponse("ODSS authentication is not configured safely.", status_code=503)
        )
    if credentials and not _is_authorized(request, *credentials):
        return _secure_response(
            PlainTextResponse(
                "Authentication required.",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{AUTH_REALM}", charset="UTF-8"'},
            )
        )
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _is_trusted_write_request(
        request
    ):
        logger.warning(
            "Cross-origin write refused method=%s path=%s origin=%r host=%r "
            "sec_fetch_site=%r sec_fetch_mode=%r sec_fetch_dest=%r",
            request.method,
            request.url.path,
            request.headers.get("origin"),
            request.headers.get("host"),
            request.headers.get("sec-fetch-site"),
            request.headers.get("sec-fetch-mode"),
            request.headers.get("sec-fetch-dest"),
        )
        return _secure_response(PlainTextResponse("Cross-origin request refused.", status_code=403))
    return _secure_response(await call_next(request))


@app.get("/healthz")
def healthcheck():
    return JSONResponse({"status": "ok", "version": APP_VERSION})


def _normalized_pdf_name(filename: str | None, fallback: str) -> str:
    raw = (filename or fallback).replace("\\", "/")
    name = Path(raw).name
    name = "".join(character for character in name if character.isprintable()).strip()
    if not name:
        name = fallback
    if Path(name).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    stem = Path(name).stem[:160].strip(" .") or Path(fallback).stem
    return f"{stem}.pdf"


async def _store_pdf(file: UploadFile, directory: Path, prefix: str, fallback: str) -> tuple[str, Path]:
    display_name = _normalized_pdf_name(file.filename, fallback)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = directory / f".{prefix}_{token}.part"
    destination = directory / f"{prefix}_{token}.pdf"
    total = 0
    try:
        await file.seek(0)
        with temporary.open("wb") as output:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 25 MB upload limit.")
                output.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="PDF is empty.")
        validate_pdf(temporary)
        temporary.replace(destination)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        raise
    except ValueError as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to store the PDF.") from exc
    return display_name, destination


def _stored_file(path: str | None, directory: Path, missing_detail: str) -> Path:
    if not path:
        raise HTTPException(status_code=404, detail=missing_detail)
    candidate = Path(path)
    try:
        candidate.resolve().relative_to(directory.resolve())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=missing_detail) from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=missing_detail)
    return candidate


def _remove_stored_file(path: str | None, directory: Path) -> None:
    if not path:
        return
    candidate = Path(path)
    try:
        candidate.resolve().relative_to(directory.resolve())
    except (OSError, ValueError):
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        return


def _timing_reference_from_row(flight) -> dict | None:
    if not flight["actual_takeoff_utc"]:
        return None
    return {
        "reference_type": flight["timing_reference_type"] or "takeoff",
        "reference_utc": flight["timing_reference_utc"] or flight["actual_takeoff_utc"],
        "reference_waypoint": flight["timing_reference_waypoint"],
        "actual_takeoff_utc": flight["actual_takeoff_utc"],
    }


def _timing_form_context(flight, analysis: dict | None) -> dict:
    reference_utc = flight["timing_reference_utc"] or ""
    reference_date = ""
    reference_time = ""
    if reference_utc:
        try:
            parsed = parse_utc(reference_utc)
            reference_date = parsed.date().isoformat()
            reference_time = parsed.strftime("%H:%M")
        except ValueError:
            pass

    actual_takeoff_display = None
    if flight["actual_takeoff_utc"]:
        try:
            actual_takeoff_display = display_utc(parse_utc(flight["actual_takeoff_utc"]))
        except ValueError:
            actual_takeoff_display = flight["actual_takeoff_utc"]

    waypoint_options = []
    if analysis:
        seen: set[tuple[str, int]] = set()
        for waypoint in analysis.get("flight", {}).get("route_waypoints", []):
            name = str(waypoint.get("fir_boundary") or waypoint.get("name") or "").lstrip("-")
            actm = waypoint.get("actm_minutes")
            if not name or actm is None or (name, int(actm)) in seen:
                continue
            seen.add((name, int(actm)))
            waypoint_options.append({
                "name": name,
                "actm": format_actm(int(actm)),
            })

    return {
        "reference_type": flight["timing_reference_type"] or "takeoff",
        "reference_date": reference_date,
        "reference_time": reference_time,
        "reference_waypoint": flight["timing_reference_waypoint"] or "",
        "actual_takeoff_display": actual_takeoff_display,
        "waypoint_options": waypoint_options,
    }


def _checkbox_selected(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _validated_note_values(
    placement: str,
    note_text: str,
    include_level1: str | None,
    include_level2: str | None,
) -> tuple[str, str, bool, bool]:
    try:
        return validate_personal_note(
            placement,
            note_text,
            _checkbox_selected(include_level1),
            _checkbox_selected(include_level2),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _record_map_refresh_warning(analysis_path: str | None, error_type: str) -> None:
    if not analysis_path:
        return
    path = Path(analysis_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        view = payload.setdefault("view", {})
        warning = (
            "Realistic map refresh unavailable; the offline map reports were "
            f"preserved ({error_type})."
        )
        warnings = view.setdefault("warnings", [])
        if warning not in warnings:
            warnings.append(warning)
        view["map_render"] = {
            "mode": "schematic-fallback",
            "reports_refreshed": False,
            "warning": warning,
        }
        temporary = path.with_suffix(path.suffix + ".map-warning.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)
    except (OSError, json.JSONDecodeError, TypeError):
        logger.warning(
            "Unable to record map refresh warning flight_analysis=%s",
            path.name,
        )


def _refresh_reports_with_primary_map(flight, result: dict) -> None:
    """Best-effort PDF map upgrade; initial offline reports remain authoritative."""
    try:
        if not (map_settings.aws_location_api_key and map_settings.service_token):
            return
        if not flight or not flight["tenant_id"] or not flight["user_id"]:
            return
        asyncio.run(
            render_reports_for_analysis(
                _public_analysis_id(flight),
                tenant_id=str(flight["tenant_id"]),
                user_id=str(flight["user_id"]),
                settings=map_settings,
            )
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning(
            "Realistic map report refresh failed flight_id=%s error_type=%s; "
            "offline reports preserved",
            flight["id"],
            error_type,
        )
        _record_map_refresh_warning(result.get("analysis_path"), error_type)


def _execute_analysis(
    flight_id: int,
    flight,
    weather_window_preference: dict | None = None,
    *,
    claimed_flight=None,
    locked_mutation: Callable[[object], object | None] | None = None,
    rollback_locked_mutation: Callable[[], None] | None = None,
    preserve_previous_on_failure: bool = False,
    commit_locked_mutation_on_report_failure: bool = False,
    failure_label: str = "analysis refresh",
) -> str | None:
    tenant_id = str(flight["tenant_id"]) if flight["tenant_id"] else None
    if claimed_flight is None:
        claimed_flight = claim_analysis(flight_id, tenant_id)
    if claimed_flight is None:
        raise HTTPException(status_code=409, detail="Analysis is already in progress")
    flight = claimed_flight
    previous_analysis = load_analysis(flight["analysis_path"])
    previous_surface_overlays = (
        (previous_analysis or {}).get("flight", {}).get("surface_overlays") or []
    )
    previous_weather_window = (
        (previous_analysis or {})
        .get("flight", {})
        .get("weather_window_preference")
    )
    previous_artifacts = (
        (flight["analysis_path"], RESULT_DIR),
        (flight["level1_report"], REPORT_DIR),
        (flight["level2_report"], REPORT_DIR),
        (flight["level3_json"], RESULT_DIR),
        (flight["level3_report"], REPORT_DIR),
    )
    result = None
    analysis_snapshot_replaced = False
    try:
        if locked_mutation is not None:
            mutated_flight = locked_mutation(flight)
            if mutated_flight is not None:
                flight = mutated_flight
        report_failure: ReportRenderingFailure | None = None
        try:
            result = run_odss_analysis(
                Path(flight["source_path"]),
                result_dir=RESULT_DIR,
                report_dir=REPORT_DIR,
                flight_id=flight_id,
                actual_takeoff_utc=flight["actual_takeoff_utc"],
                timing_reference=_timing_reference_from_row(flight),
                personal_notes=[dict(note) for note in list_personal_notes(flight_id)],
                surface_overlays=previous_surface_overlays,
                weather_window_preference=(
                    weather_window_preference or previous_weather_window
                ),
            )
        except ReportRenderingFailure as exc:
            result = dict(exc.result)
            if not commit_locked_mutation_on_report_failure:
                raise
            report_failure = exc
            # Keep the last complete PDFs as recoverable files, but mark them
            # stale so no report endpoint can serve them as current.
            result["level1_report"] = flight["level1_report"]
            result["level2_report"] = flight["level2_report"]
            logger.warning(
                "Report refresh failed after valid mutation flight_id=%s "
                "error_type=%s; timing and core analysis retained",
                flight_id,
                exc.error_type,
                exc_info=True,
            )
        if flight["tenant_id"] and flight["user_id"]:
            result.update(
                generate_level3_artifacts(
                    tenant_id=str(flight["tenant_id"]),
                    actor_id=str(flight["user_id"]),
                    analysis_id=_public_analysis_id(flight),
                    analysis_path=Path(str(result["analysis_path"])),
                    result_dir=RESULT_DIR,
                    report_dir=REPORT_DIR,
                )
            )
        # Publish the new artifact pointers while retaining Processing as the
        # ownership claim. The optional primary-map refresh writes those same
        # JSON/PDF artifacts and must finish before another mutation can start.
        complete_analysis(
            flight_id,
            result,
            tenant_id,
            release_claim=False,
        )
        analysis_snapshot_replaced = True
        new_artifacts = (
            (result.get("analysis_path"), RESULT_DIR),
            (result.get("level1_report"), REPORT_DIR),
            (result.get("level2_report"), REPORT_DIR),
            (result.get("level3_json"), RESULT_DIR),
            (result.get("level3_report"), REPORT_DIR),
        )
        if report_failure is None:
            _refresh_reports_with_primary_map(flight, result)
        update_status(flight_id, "Completed", tenant_id=tenant_id)
        for (previous_path, directory), (new_path, _) in zip(
            previous_artifacts,
            new_artifacts,
            strict=True,
        ):
            if previous_path and previous_path != new_path:
                _remove_stored_file(previous_path, directory)
        return None
    except Exception as exc:
        snapshot_restore_error = None
        if analysis_snapshot_replaced:
            try:
                # Restore the authoritative row before removing any newly
                # generated files. If this compensation fails, retain those
                # files so the database never points at paths we deleted.
                restore_analysis_snapshot(
                    flight_id,
                    claimed_flight,
                    tenant_id=tenant_id,
                )
            except Exception as restore_exc:
                snapshot_restore_error = (
                    f"{type(restore_exc).__name__}: {restore_exc}"
                )
                logger.exception(
                    "Analysis snapshot restore failed flight_id=%s",
                    flight_id,
                )
        if result and snapshot_restore_error is None:
            previous_paths = {
                str(path)
                for path, _directory in previous_artifacts
                if path
            }
            for candidate, directory in (
                (result.get("analysis_path"), RESULT_DIR),
                (result.get("level1_report"), REPORT_DIR),
                (result.get("level2_report"), REPORT_DIR),
                (result.get("level3_json"), RESULT_DIR),
                (result.get("level3_report"), REPORT_DIR),
            ):
                if candidate and str(candidate) not in previous_paths:
                    _remove_stored_file(candidate, directory)
        error = f"{type(exc).__name__}: {exc}"
        rollback_error = None
        if rollback_locked_mutation is not None:
            try:
                rollback_locked_mutation()
            except Exception as rollback_exc:
                rollback_error = (
                    f"{type(rollback_exc).__name__}: {rollback_exc}"
                )
                logger.exception(
                    "Locked analysis mutation rollback failed flight_id=%s",
                    flight_id,
                )
        if snapshot_restore_error:
            rollback_error = (
                f"{rollback_error}; {snapshot_restore_error}"
                if rollback_error
                else snapshot_restore_error
            )
        if preserve_previous_on_failure and rollback_error is None:
            restore_analysis_state(
                flight_id,
                str(claimed_flight["status"]),
                claimed_flight["notes"],
                f"Rejected {failure_label}: {error}",
                tenant_id=tenant_id,
                analysis_failure_category=claimed_flight[
                    "analysis_failure_category"
                ],
            )
        else:
            if rollback_error:
                error = f"{error}; rollback failed: {rollback_error}"
            update_status(
                flight_id,
                "Failed",
                "Analysis failed. The detailed error is shown below.",
                last_error=error,
                tenant_id=tenant_id,
                analysis_failure_category=(
                    "cfp_parse_rejected"
                    if isinstance(exc, CfpParseRejectedError)
                    else "infrastructure"
                ),
            )
        traceback.print_exc()
        return error


def _regenerate_after_note_change(
    flight,
    locked_mutation: Callable[[object], object | None],
    rollback_locked_mutation: Callable[[], None],
) -> str | None:
    """Apply one dashboard note mutation under the per-flight claim.

    Notes may be authored before the first analysis. In that case this claims
    the row only long enough to store the note, then restores the exact prior
    flight state. Once reports exist, the same claim spans mutation, report
    regeneration, and any rollback.
    """
    flight_id = int(flight["id"])
    tenant_id = _dashboard_tenant_id()
    claimed_flight = claim_analysis(flight_id, tenant_id)
    if claimed_flight is None:
        return "analysis-running"
    if claimed_flight["analysis_path"] or claimed_flight["status"] == "Completed":
        failure_detail = _execute_analysis(
            flight_id,
            claimed_flight,
            claimed_flight=claimed_flight,
            locked_mutation=locked_mutation,
            rollback_locked_mutation=rollback_locked_mutation,
            preserve_previous_on_failure=True,
            failure_label="personal-note update",
        )
        return "refresh-failed" if failure_detail else None

    try:
        locked_mutation(claimed_flight)
    except Exception:
        try:
            rollback_locked_mutation()
        finally:
            restore_analysis_state(
                flight_id,
                str(claimed_flight["status"]),
                claimed_flight["notes"],
                claimed_flight["last_error"],
                tenant_id=tenant_id,
                analysis_failure_category=claimed_flight[
                    "analysis_failure_category"
                ],
            )
        raise
    restore_analysis_state(
        flight_id,
        str(claimed_flight["status"]),
        claimed_flight["notes"],
        claimed_flight["last_error"],
        tenant_id=tenant_id,
        analysis_failure_category=claimed_flight["analysis_failure_category"],
    )
    return None


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"flights": list_flights(_dashboard_tenant_id())},
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(request=request, name="upload.html", context={})


@app.post("/upload")
async def upload_cfp(
    file: UploadFile = File(...),
    flight_number: str = Form(""),
    flight_date: str = Form(""),
    departure: str = Form(""),
    destination: str = Form(""),
    aircraft: str = Form(""),
    registration: str = Form(""),
):
    filename, dest = await _store_pdf(file, UPLOAD_DIR, "cfp", "uploaded.pdf")

    inferred = infer_metadata(filename)
    record = {
        "flight_number": flight_number or inferred["flight_number"],
        "flight_date": flight_date,
        "departure": departure.upper(),
        "destination": destination.upper(),
        "aircraft": aircraft,
        "registration": registration.upper(),
        "source_filename": filename,
        "source_path": str(dest),
        "status": "Uploaded",
        "tenant_id": _dashboard_tenant_id(),
        "user_id": "legacy-dashboard-user",
    }
    try:
        flight_id = create_flight(record)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.get("/flights/{flight_id}", response_class=HTMLResponse)
def flight_workspace(request: Request, flight_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    analysis = load_analysis(flight["analysis_path"])
    notices = {
        "analysis-running": "Analysis is already running. This page still shows the last completed result.",
        "refresh-failed": "The refresh failed. The last completed reports remain available below.",
        "reports-not-current": (
            "Timing saved, but the Level 1 and Level 2 reports are not current. "
            "Retry report generation before use."
        ),
    }
    return templates.TemplateResponse(
        request=request,
        name="flight.html",
        context={
            "flight": flight,
            "analysis": analysis,
            "timing_form": _timing_form_context(flight, analysis),
            "personal_notes": list_personal_notes(flight_id),
            "personal_note_placement_labels": PERSONAL_NOTE_PLACEMENT_LABELS,
            "notice": notices.get(request.query_params.get("notice", "")),
        },
    )


def _dashboard_map_contract(flight_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    analysis = load_analysis(flight["analysis_path"])
    if not analysis:
        raise HTTPException(status_code=409, detail="Analysis is not complete")
    try:
        return map_contract_from_analysis(
            analysis,
            map_settings,
            analysis_id=_public_analysis_id(flight),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="A canonical map is not available for this analysis",
        ) from exc


@app.get("/flights/{flight_id}/map-config")
async def dashboard_map_config(flight_id: int):
    contract = _dashboard_map_contract(flight_id)
    payload = await interactive_map_payload(
        contract,
        map_settings,
        fallback_url=f"/flights/{flight_id}/map-fallback",
    )
    return JSONResponse(payload)


@app.get("/flights/{flight_id}/map-fallback")
async def dashboard_map_fallback(
    flight_id: int,
    width: int = 1600,
    height: int = 900,
):
    contract = _dashboard_map_contract(flight_id)
    return await fallback_map_response(
        contract,
        map_settings,
        width=width,
        height=height,
    )


@app.post("/flights/{flight_id}/analyse")
def analyse_flight(flight_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running",
            status_code=303,
        )
    _execute_analysis(flight_id, flight)
    refreshed = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    notice = "?notice=refresh-failed" if refreshed and refreshed["status"] == "Failed" else ""
    return RedirectResponse(url=f"/flights/{flight_id}{notice}", status_code=303)


@app.post("/flights/{flight_id}/timing")
def update_operational_clock(
    flight_id: int,
    reference_type: str = Form(...),
    reference_date: str = Form(...),
    reference_time: str = Form(...),
    reference_waypoint: str = Form(""),
):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#actual-time",
            status_code=303,
        )

    try:
        reference_datetime = combine_utc_date_time(reference_date, reference_time)
        analysis = load_analysis(flight["analysis_path"])
        parsed_flight = analysis.get("flight") if analysis else None
        derive_timing_reference(
            parsed_flight,
            reference_type,
            reference_datetime.isoformat(),
            reference_waypoint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    previous_timing: dict[str, object] | None = None
    timing_changed = False

    def apply_timing(claimed_flight):
        nonlocal previous_timing, timing_changed
        current_analysis = load_analysis(claimed_flight["analysis_path"])
        try:
            reference = derive_timing_reference(
                current_analysis.get("flight") if current_analysis else None,
                reference_type,
                reference_datetime.isoformat(),
                reference_waypoint,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        previous_timing = {
            "actual_takeoff_utc": claimed_flight["actual_takeoff_utc"],
            "reference_type": claimed_flight["timing_reference_type"],
            "reference_utc": claimed_flight["timing_reference_utc"],
            "reference_waypoint": claimed_flight["timing_reference_waypoint"],
        }
        save_timing_reference(
            flight_id,
            reference["actual_takeoff_utc"],
            reference["reference_type"],
            reference["reference_utc"],
            reference.get("reference_waypoint"),
            tenant_id=_dashboard_tenant_id(),
        )
        timing_changed = True
        updated = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
        if not updated:
            raise RuntimeError("Flight was lost after timing update")
        return updated

    def rollback_timing() -> None:
        if not timing_changed or previous_timing is None:
            return
        save_timing_reference(
            flight_id,
            previous_timing["actual_takeoff_utc"],
            previous_timing["reference_type"],
            previous_timing["reference_utc"],
            previous_timing["reference_waypoint"],
            tenant_id=_dashboard_tenant_id(),
        )

    try:
        failure_detail = _execute_analysis(
            flight_id,
            flight,
            locked_mutation=apply_timing,
            rollback_locked_mutation=rollback_timing,
            preserve_previous_on_failure=True,
            commit_locked_mutation_on_report_failure=True,
            failure_label="timing update",
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#actual-time",
            status_code=303,
        )
    refreshed = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    reports_not_current = bool(
        refreshed and refreshed["report_refresh_state"] != "current"
    )
    notice = (
        "?notice=reports-not-current"
        if reports_not_current
        else "?notice=refresh-failed"
        if failure_detail
        else ""
    )
    return RedirectResponse(
        url=f"/flights/{flight_id}{notice}#actual-time",
        status_code=303,
    )


@app.post("/flights/{flight_id}/notes")
def add_personal_note(
    flight_id: int,
    placement: str = Form(...),
    note_text: str = Form(...),
    include_level1: str | None = Form(None),
    include_level2: str | None = Form(None),
):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#personal-notes",
            status_code=303,
        )
    values = _validated_note_values(
        placement,
        note_text,
        include_level1,
        include_level2,
    )
    note_id: int | None = None

    def add_note(claimed_flight):
        nonlocal note_id
        note_id = create_personal_note(flight_id, *values)
        return claimed_flight

    def rollback_added_note() -> None:
        if note_id is not None and get_personal_note(flight_id, note_id):
            delete_personal_note(flight_id, note_id)

    notice = _regenerate_after_note_change(flight, add_note, rollback_added_note)
    query = f"?notice={notice}" if notice else ""
    return RedirectResponse(
        url=f"/flights/{flight_id}{query}#personal-notes",
        status_code=303,
    )


@app.post("/flights/{flight_id}/notes/{note_id}/update")
def edit_personal_note(
    flight_id: int,
    note_id: int,
    placement: str = Form(...),
    note_text: str = Form(...),
    include_level1: str | None = Form(None),
    include_level2: str | None = Form(None),
):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#personal-notes",
            status_code=303,
        )
    if not get_personal_note(flight_id, note_id):
        raise HTTPException(status_code=404, detail="Personal note not found")
    values = _validated_note_values(
        placement,
        note_text,
        include_level1,
        include_level2,
    )
    note_snapshot: dict | None = None
    note_updated = False

    def update_note(claimed_flight):
        nonlocal note_snapshot, note_updated
        current_note = get_personal_note(flight_id, note_id)
        if not current_note:
            raise RuntimeError("Personal note no longer exists")
        note_snapshot = dict(current_note)
        update_personal_note(flight_id, note_id, *values)
        note_updated = True
        return claimed_flight

    def rollback_updated_note() -> None:
        if not note_updated or note_snapshot is None:
            return
        if get_personal_note(flight_id, note_id):
            delete_personal_note(flight_id, note_id)
        restore_personal_note(flight_id, note_snapshot)

    notice = _regenerate_after_note_change(flight, update_note, rollback_updated_note)
    query = f"?notice={notice}" if notice else ""
    return RedirectResponse(
        url=f"/flights/{flight_id}{query}#personal-notes",
        status_code=303,
    )


@app.post("/flights/{flight_id}/notes/{note_id}/delete")
def remove_personal_note(flight_id: int, note_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#personal-notes",
            status_code=303,
        )
    if not get_personal_note(flight_id, note_id):
        raise HTTPException(status_code=404, detail="Personal note not found")
    note_snapshot: dict | None = None
    note_deleted = False

    def delete_note(claimed_flight):
        nonlocal note_snapshot, note_deleted
        current_note = get_personal_note(flight_id, note_id)
        if not current_note:
            raise RuntimeError("Personal note no longer exists")
        note_snapshot = dict(current_note)
        delete_personal_note(flight_id, note_id)
        note_deleted = True
        return claimed_flight

    def rollback_deleted_note() -> None:
        if note_deleted and note_snapshot is not None:
            restore_personal_note(flight_id, note_snapshot)

    notice = _regenerate_after_note_change(flight, delete_note, rollback_deleted_note)
    query = f"?notice={notice}" if notice else ""
    return RedirectResponse(
        url=f"/flights/{flight_id}{query}#personal-notes",
        status_code=303,
    )


@app.post("/flights/{flight_id}/reports/{level}")
async def upload_report(flight_id: int, level: int, file: UploadFile = File(...)):
    if level not in (1, 2):
        raise HTTPException(status_code=400, detail="Report level must be 1 or 2")
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    _, dest = await _store_pdf(
        file,
        REPORT_DIR,
        f"flight_{flight_id}_level_{level}",
        "report.pdf",
    )
    try:
        attach_report(
            flight_id,
            level,
            str(dest),
            tenant_id=_dashboard_tenant_id(),
        )
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    previous = flight["level1_report"] if level == 1 else flight["level2_report"]
    if previous != str(dest):
        _remove_stored_file(previous, REPORT_DIR)
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.get("/files/source/{flight_id}")
def download_source(flight_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    path = _stored_file(flight["source_path"], UPLOAD_DIR, "Source PDF not found")
    return FileResponse(
        path,
        filename=_normalized_pdf_name(flight["source_filename"], "source.pdf"),
        media_type="application/pdf",
    )


@app.get("/files/report/{flight_id}/{level}")
def download_report(flight_id: int, level: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if level not in (1, 2):
        raise HTTPException(status_code=400, detail="Report level must be 1 or 2")
    _require_current_reports(flight)
    stored_path = flight["level1_report"] if level == 1 else flight["level2_report"]
    path = _stored_file(stored_path, REPORT_DIR, "Report not generated")
    filename = f"{flight['flight_number'] or f'flight-{flight_id}'}_level_{level}.pdf"
    return FileResponse(path, filename=filename, media_type="application/pdf")


@app.get("/files/analysis/{flight_id}")
def download_analysis(flight_id: int):
    flight = get_flight_for_tenant(flight_id, _dashboard_tenant_id())
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    path = _stored_file(flight["analysis_path"], RESULT_DIR, "Analysis not generated")
    filename = f"{flight['flight_number'] or f'flight-{flight_id}'}_analysis.json"
    return FileResponse(path, filename=filename, media_type="application/json")

class ServiceTimingRequest(BaseModel):
    reference_type: str = Field(pattern="^(takeoff|waypoint_ata)$")
    reference_utc: str
    reference_waypoint: str | None = None
    weather_before_minutes: int | None = Field(default=None, ge=0, le=720)
    weather_after_minutes: int | None = Field(default=None, ge=0, le=720)


class ServiceWeatherWindowRequest(BaseModel):
    before_minutes: int = Field(ge=0, le=720)
    after_minutes: int = Field(ge=0, le=720)


class ServicePersonalNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    placement: str = Field(min_length=1, max_length=32)
    note_text: str = Field(min_length=1, max_length=2_000)
    include_level1: StrictBool
    include_level2: StrictBool


class ServiceLevel3AnswerRequest(BaseModel):
    answer: str | None = Field(default=None, max_length=500)
    declined: bool = False


def _public_analysis_id(flight) -> str:
    return str(flight["analysis_id"] or f"legacy-{flight['id']}")


def _service_flight(analysis_id: str, identity: ServiceIdentity):
    flight = get_flight_by_analysis_id(analysis_id, identity.tenant_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return flight


def _service_analysis(
    analysis_id: str,
    identity: ServiceIdentity,
) -> tuple[object, dict]:
    flight = _service_flight(analysis_id, identity)
    analysis = load_analysis(flight["analysis_path"])
    if not analysis:
        raise HTTPException(status_code=409, detail="Analysis is not complete")
    return flight, analysis


def _surface_report_route_map(analysis: dict) -> tuple[Path | None, str | None]:
    render = (analysis.get("view") or {}).get("map_render") or {}
    raw_path = render.get("artifact_path")
    if not raw_path:
        return None, None
    candidate = Path(str(raw_path))
    try:
        candidate.resolve().relative_to((DATA_DIR / "maps").resolve())
    except (OSError, ValueError):
        return None, None
    if (
        not candidate.is_file()
        or candidate.suffix.casefold() not in {".png", ".jpg", ".jpeg"}
    ):
        return None, None
    return candidate, str(render.get("label") or "Realistic route map")


def _surface_overlay_summary(overlays: list[dict]) -> list[dict]:
    return [
        {
            "icao": overlay["icao"],
            "role": overlay["role"],
            "window": overlay["window"],
            "counts": overlay["counts"],
            "report_map": overlay.get("report_map"),
        }
        for overlay in overlays
    ]


def _publish_surface_overlay_reports(
    flight,
    analysis: dict,
    overlays: list[dict],
) -> None:
    analysis_path = _stored_file(
        flight["analysis_path"],
        RESULT_DIR,
        "Analysis not generated",
    )
    level1_path = _stored_file(
        flight["level1_report"],
        REPORT_DIR,
        "Level 1 report not generated",
    )
    level2_path = _stored_file(
        flight["level2_report"],
        REPORT_DIR,
        "Level 2 report not generated",
    )
    updated = json.loads(json.dumps(analysis))
    updated_flight = updated.setdefault("flight", {})
    updated_flight["surface_overlays"] = overlays
    updated.setdefault("view", {})["surface_overlays"] = _surface_overlay_summary(
        overlays
    )
    route_map_path, route_map_label = _surface_report_route_map(updated)
    warnings = (updated.get("view") or {}).get("warnings") or []
    findings = updated.get("findings") or []

    analysis_temp = analysis_path.with_suffix(analysis_path.suffix + ".surface.tmp")
    level1_temp = level1_path.with_suffix(level1_path.suffix + ".surface.tmp")
    level2_temp = level2_path.with_suffix(level2_path.suffix + ".surface.tmp")
    try:
        render_pdf(
            updated_flight,
            findings,
            warnings,
            1,
            level1_temp,
            map_image_path=route_map_path,
            map_label=route_map_label,
        )
        render_pdf(
            updated_flight,
            findings,
            warnings,
            2,
            level2_temp,
            map_image_path=route_map_path,
            map_label=route_map_label,
        )
        # Level 2 may register governed source-chart page targets on the
        # updated flight. Serialize after both reports render, then publish the
        # report pair and analysis JSON as one rollback-capable artifact set.
        analysis_temp.write_text(json.dumps(updated, indent=2), encoding="utf-8")
        publish_staged_artifacts([
            (level1_temp, level1_path),
            (level2_temp, level2_path),
            (analysis_temp, analysis_path),
        ])
    finally:
        analysis_temp.unlink(missing_ok=True)
        level1_temp.unlink(missing_ok=True)
        level2_temp.unlink(missing_ok=True)


REPORTS_NOT_CURRENT_DETAIL = (
    "Reports are not current for the active analysis. Retry report generation."
)


def _report_refresh_summary(flight) -> dict:
    state = str(flight["report_refresh_state"] or "pending")
    return {
        "state": state,
        "reports_current": state == "current",
        "warning": REPORT_REFRESH_WARNING if state == "failed" else None,
    }


def _require_current_reports(flight) -> None:
    if (
        str(flight["status"] or "") != "Processing"
        and _report_refresh_summary(flight)["reports_current"]
    ):
        return
    raise HTTPException(status_code=409, detail=REPORTS_NOT_CURRENT_DETAIL)


def _service_summary(flight) -> dict:
    analysis_id = _public_analysis_id(flight)
    report_refresh = _report_refresh_summary(flight)
    if str(flight["status"] or "") == "Failed":
        safe_failure = (
            _supported_cfp_failure_detail(flight)
            if flight["analysis_failure_category"] == "cfp_parse_rejected"
            else _temporary_analysis_failure_detail(flight)
        )
        warnings = [safe_failure["message"]]
    else:
        warnings = [flight["last_error"]] if flight["last_error"] else []
    if report_refresh["warning"] and report_refresh["warning"] not in warnings:
        warnings.append(report_refresh["warning"])
    return {
        "analysis_id": analysis_id,
        "analysis_version": flight["analysis_version"] or APP_VERSION,
        "status": flight["status"],
        "created_at": flight["created_at"],
        "updated_at": flight["updated_at"],
        "flight": {
            "flight_number": flight["flight_number"],
            "flight_date": flight["flight_date"],
            "departure": flight["departure"],
            "destination": flight["destination"],
            "aircraft": flight["aircraft"],
            "registration": flight["registration"],
        },
        "context": {
            "tenant_id": flight["tenant_id"],
            "user_id": flight["user_id"],
            "workspace_id": flight["workspace_id"],
            "external_flight_id": flight["external_flight_id"],
        },
        "warnings": warnings,
        "report_refresh": report_refresh,
        "links": {
            "self": f"/v1/analyses/{analysis_id}",
            "briefing": f"/v1/analyses/{analysis_id}/briefing",
            "map_contract": f"/v1/analyses/{analysis_id}/map-contract",
            "route_geojson": f"/v1/analyses/{analysis_id}/route.geojson",
            "markers_geojson": f"/v1/analyses/{analysis_id}/markers.geojson",
            "hazards_geojson": f"/v1/analyses/{analysis_id}/hazards.geojson",
            "map_config": f"/v1/analyses/{analysis_id}/map-config",
            "profile_charts": f"/v1/analyses/{analysis_id}/profile-charts/{{chart_number}}",
            "combined_report": f"/v1/analyses/{analysis_id}/reports/combined",
            "level_1_report": f"/v1/analyses/{analysis_id}/reports/level-1",
            "level_2_report": f"/v1/analyses/{analysis_id}/reports/level-2",
            "level_3": f"/v1/analyses/{analysis_id}/level-3",
            "level_3_report": f"/v1/analyses/{analysis_id}/reports/level-3",
            "timing": f"/v1/analyses/{analysis_id}/timing",
            "surface_overlays": f"/v1/analyses/{analysis_id}/surface-overlays",
            "weather_charts": f"/v1/analyses/{analysis_id}/weather-charts/{{chart_number}}",
            "render_reports": f"/v1/analyses/{analysis_id}/reports/render",
        },
    }


SERVICE_NOTAM_FINDING_LIMIT = 64


def _service_notam_snapshot(analysis: dict) -> dict:
    """Rank, deduplicate and bound evaluated NOTAMs with omission provenance."""

    source_findings = [
        item
        for item in (analysis.get("findings") or [])
        if item.get("engine") == "notam"
    ]
    ranked_findings = (
        select_pertinent_notams(source_findings, limit=len(source_findings))
        if source_findings
        else []
    )
    selected_findings = ranked_findings[:SERVICE_NOTAM_FINDING_LIMIT]
    result: list[dict] = []
    for item in selected_findings:
        data = item.get("data") or {}
        source_references = data.get("source_references") or []
        source_pages = [
            page
            for source in source_references
            for page in (source.get("pages") or [])
            if isinstance(page, int) and page > 0
        ]
        result.append({
            "notam_id": data.get("notam_id"),
            "location": data.get("location"),
            "category": data.get("category"),
            "text": data.get("raw_text"),
            "summary": item.get("summary"),
            "role": data.get("role"),
            "applicability": data.get("applicability"),
            "validity_status": data.get("validity_status"),
            "schedule_status": data.get("schedule_status"),
            "valid_from_utc": data.get("valid_from_utc"),
            "valid_to_utc": data.get("valid_to_utc"),
            "window_start_utc": data.get("window_start_utc"),
            "window_end_utc": data.get("window_end_utc"),
            "schedule": data.get("schedule"),
            "state_at_reference": data.get("stateAtReference"),
            "reference_at": data.get("referenceAt"),
            "source_page": source_pages[0] if source_pages else None,
        })
    return {
        "items": result,
        "summary": {
            "source_count": len(source_findings),
            "ranked_count": len(ranked_findings),
            "returned_count": len(result),
            "omitted_count": max(0, len(ranked_findings) - len(result)),
            "duplicate_count": max(0, len(source_findings) - len(ranked_findings)),
            "limit": SERVICE_NOTAM_FINDING_LIMIT,
        },
    }


def _service_personal_notes(flight_id: int) -> list[dict]:
    return [
        serialise_personal_note(dict(note))
        for note in list_personal_notes(flight_id)
    ]


@app.get("/v1/health")
def service_health():
    profile_source = {
        key: DEPRESS_LIBRARY_METADATA.get(key)
        for key in (
            "status",
            "issue_date",
            "coverage_scope",
            "profile_count",
            "source",
            "source_document_sha256",
            "index_sha256",
        )
        if DEPRESS_LIBRARY_METADATA.get(key) is not None
    }
    return JSONResponse({
        "status": "ok",
        "version": APP_VERSION,
        "map_contract": "1.1",
        "map_provider": map_settings.provider,
        "map_style": map_settings.style,
        "playwright_capture_configured": bool(
            map_settings.aws_location_api_key and map_settings.service_token
        ),
        "depressurization_profile_source": profile_source,
    })


def _supported_cfp_failure_detail(flight) -> dict[str, str]:
    return {
        "code": "CFP_FORMAT_UNSUPPORTED_OR_INVALID",
        "message": (
            "This PDF could not be processed as a supported Lido CFP. "
            "Check the file and upload it again."
        ),
        "analysis_id": _public_analysis_id(flight),
    }


def _temporary_analysis_failure_detail(flight) -> dict[str, str]:
    return {
        "code": "ANALYSIS_TEMPORARILY_UNAVAILABLE",
        "message": (
            "PilotDriven could not complete this analysis. Retry the same "
            "upload; the original request remains safe to replay."
        ),
        "analysis_id": _public_analysis_id(flight),
    }


def _raise_stored_analysis_failure(flight) -> None:
    if flight["analysis_failure_category"] == "cfp_parse_rejected":
        raise HTTPException(
            status_code=422,
            detail=_supported_cfp_failure_detail(flight),
        )
    raise HTTPException(
        status_code=503,
        detail=_temporary_analysis_failure_detail(flight),
    )


def _replay_service_analysis(flight) -> JSONResponse | None:
    status = str(flight["status"] or "")
    if status == "Completed":
        return JSONResponse(_service_summary(flight), status_code=200)
    if status in {"Processing", "Uploaded"}:
        raise HTTPException(status_code=409, detail="Analysis is already in progress")
    if flight["analysis_failure_category"] == "cfp_parse_rejected":
        _raise_stored_analysis_failure(flight)
    # A failed infrastructure attempt remains replayable under the same
    # idempotency key. The caller reruns the retained, validated upload.
    return None


def _service_weather_window_preference(
    before_minutes: int | None,
    after_minutes: int | None,
) -> dict[str, int] | None:
    if before_minutes is None and after_minutes is None:
        return None
    return {
        key: value
        for key, value in (
            ("before_minutes", before_minutes),
            ("after_minutes", after_minutes),
        )
        if value is not None
    }


async def _run_service_analysis_record(
    flight,
    weather_window_preference: dict[str, int] | None,
    *,
    success_status_code: int,
) -> JSONResponse:
    flight_id = int(flight["id"])
    tenant_id = str(flight["tenant_id"])
    claimed_flight = await asyncio.to_thread(
        claim_analysis,
        flight_id,
        tenant_id,
        expected_status=str(flight["status"] or ""),
    )
    if claimed_flight is None:
        current = get_flight_for_tenant(flight_id, tenant_id)
        if not current:
            raise HTTPException(status_code=500, detail="Analysis record was lost")
        replay = _replay_service_analysis(current)
        if replay is not None:
            return replay
        # Another retry may itself have failed after this caller read the old
        # Failed row. Do not start an unbounded third attempt in this request.
        _raise_stored_analysis_failure(current)
    await asyncio.to_thread(
        _execute_analysis,
        flight_id,
        claimed_flight,
        weather_window_preference,
        claimed_flight=claimed_flight,
    )
    completed = get_flight_for_tenant(flight_id, tenant_id)
    if not completed:
        raise HTTPException(status_code=500, detail="Analysis record was lost")
    if completed["status"] != "Completed":
        _raise_stored_analysis_failure(completed)
    return JSONResponse(
        _service_summary(completed),
        status_code=success_status_code,
    )


@app.post("/v1/analyses", status_code=201)
async def create_service_analysis(
    request: Request,
    file: UploadFile = File(...),
    flight_number: str = Form(""),
    flight_date: str = Form(""),
    departure: str = Form(""),
    destination: str = Form(""),
    aircraft: str = Form(""),
    registration: str = Form(""),
    weather_before_minutes: int | None = Form(default=None, ge=0, le=720),
    weather_after_minutes: int | None = Form(default=None, ge=0, le=720),
):
    identity = request_service_identity(request)
    tenant_id = identity.tenant_id
    service_request_id = identity.request_id
    weather_window_preference = _service_weather_window_preference(
        weather_before_minutes,
        weather_after_minutes,
    )
    if service_request_id:
        existing = get_flight_by_service_request(tenant_id, service_request_id)
        if existing:
            replay = _replay_service_analysis(existing)
            if replay is not None:
                return replay
            return await _run_service_analysis_record(
                existing,
                weather_window_preference,
                success_status_code=200,
            )
    filename, dest = await _store_pdf(file, UPLOAD_DIR, "cfp", "uploaded.pdf")
    inferred = infer_metadata(filename)
    record = {
        "flight_number": flight_number or inferred["flight_number"],
        "flight_date": flight_date,
        "departure": departure.upper(),
        "destination": destination.upper(),
        "aircraft": aircraft,
        "registration": registration.upper(),
        "source_filename": filename,
        "source_path": str(dest),
        "status": "Uploaded",
        "tenant_id": tenant_id,
        "user_id": identity.user_id,
        "workspace_id": identity.workspace_id,
        "external_flight_id": identity.flight_id,
        "analysis_version": APP_VERSION,
        "service_request_id": service_request_id,
    }
    try:
        flight_id = create_flight(record)
    except sqlite3.IntegrityError:
        dest.unlink(missing_ok=True)
        existing = (
            get_flight_by_service_request(tenant_id, service_request_id)
            if service_request_id
            else None
        )
        if existing is None:
            raise
        replay = _replay_service_analysis(existing)
        if replay is not None:
            return replay
        return await _run_service_analysis_record(
            existing,
            weather_window_preference,
            success_status_code=200,
        )
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    flight = get_flight_for_tenant(flight_id, tenant_id)
    if not flight:
        raise HTTPException(status_code=500, detail="Analysis record was not created")
    return await _run_service_analysis_record(
        flight,
        weather_window_preference,
        success_status_code=201,
    )


@app.get("/v1/analyses/{analysis_id}")
def get_service_analysis(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    return JSONResponse(_service_summary(_service_flight(analysis_id, identity)))


@app.get("/v1/analyses/{analysis_id}/briefing")
def get_service_briefing(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    flight, analysis = _service_analysis(analysis_id, identity)
    view = analysis.get("view") or {}
    analysis_flight = analysis.get("flight") or {}
    notam_snapshot = _service_notam_snapshot(analysis)
    report_refresh = _report_refresh_summary(flight)
    warnings = list(view.get("warnings") or [])
    if report_refresh["warning"] and report_refresh["warning"] not in warnings:
        warnings.append(report_refresh["warning"])
    return JSONResponse({
        "analysis_id": analysis_id,
        "schema_version": analysis.get("schema_version"),
        "flight": analysis_flight,
        "briefing": view.get("briefing"),
        "timing": view.get("timing"),
        "personal_notes": analysis_flight.get("personal_notes") or [],
        "warnings": warnings,
        "report_refresh": report_refresh,
        "notam_findings": notam_snapshot["items"],
        "notam_findings_summary": notam_snapshot["summary"],
        "weather_charts": analysis.get("weather_charts") or {"status": "unavailable", "charts": []},
        "generated_at_utc": view.get("generated_at_utc"),
        "report_links": _service_summary(flight)["links"],
    })


@app.get("/v1/analyses/{analysis_id}/profile-charts/{chart_number}")
def get_service_profile_chart(
    request: Request,
    analysis_id: str,
    chart_number: str,
):
    identity = request_service_identity(request)
    flight, analysis = _service_analysis(analysis_id, identity)
    _require_current_reports(flight)
    artifact = held_profile_chart(analysis, chart_number)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Profile chart not found")
    level2_path = _stored_file(
        flight["level2_report"],
        REPORT_DIR,
        "Validated profile chart artifact is unavailable",
    )
    try:
        image = render_held_profile_chart_page(level2_path, artifact)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "Held profile chart delivery failed analysis_id=%s chart=%s",
            analysis_id,
            chart_number,
            exc_info=True,
        )
        raise HTTPException(
            status_code=404,
            detail="Validated profile chart artifact is unavailable",
        ) from exc
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/v1/analyses/{analysis_id}/weather-charts/{chart_number}")
def get_service_weather_chart(
    request: Request,
    analysis_id: str,
    chart_number: str,
):
    """Serve one held briefing chart — the page of the uploaded package itself.

    The image is re-extracted from the stored source PDF and checked against
    the sha256 pinned at analysis time, so what is served is provably the page
    the pilot uploaded and nothing regenerated.
    """
    identity = request_service_identity(request)
    flight, analysis = _service_analysis(analysis_id, identity)
    manifest = analysis.get("weather_charts") or {}
    try:
        wanted = int(chart_number)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Weather chart not found")
    entry = next(
        (item for item in manifest.get("charts") or [] if item.get("chart_number") == wanted),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Weather chart not found")
    source_path = _stored_file(flight["source_path"], UPLOAD_DIR, "Source PDF not found")
    try:
        image = extract_chart_image(source_path, int(entry["page_number"]))
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "Held weather chart delivery failed analysis_id=%s chart=%s",
            analysis_id,
            chart_number,
            exc_info=True,
        )
        raise HTTPException(status_code=404, detail="Held weather chart is unavailable") from exc
    if image is None or sha256(image).hexdigest() != entry.get("image_sha256"):
        raise HTTPException(status_code=404, detail="Held weather chart failed integrity verification")
    return Response(
        content=image,
        media_type=entry.get("media_type") or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/v1/analyses/{analysis_id}/timing")
def update_service_timing(
    request: Request,
    analysis_id: str,
    payload: ServiceTimingRequest,
):
    identity = request_service_identity(request)
    flight, analysis = _service_analysis(analysis_id, identity)
    try:
        parsed_reference_utc = parse_utc(payload.reference_utc).isoformat()
        # Reject malformed request data before claiming the analysis. The same
        # derivation is repeated from the authoritative post-claim analysis.
        derive_timing_reference(
            analysis.get("flight"),
            payload.reference_type,
            parsed_reference_utc,
            payload.reference_waypoint or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    flight_id = int(flight["id"])
    previous_timing: dict[str, object] | None = None
    timing_changed = False
    requested_weather_window = (
        {}
        if (
            payload.weather_before_minutes is not None
            or payload.weather_after_minutes is not None
        )
        else None
    )

    def apply_timing(claimed_flight):
        nonlocal previous_timing, timing_changed
        current_analysis = load_analysis(claimed_flight["analysis_path"])
        if not current_analysis:
            raise RuntimeError("Authoritative analysis is not available")
        try:
            reference = derive_timing_reference(
                current_analysis.get("flight"),
                payload.reference_type,
                parsed_reference_utc,
                payload.reference_waypoint or "",
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        previous_timing = {
            "actual_takeoff_utc": claimed_flight["actual_takeoff_utc"],
            "reference_type": claimed_flight["timing_reference_type"],
            "reference_utc": claimed_flight["timing_reference_utc"],
            "reference_waypoint": claimed_flight["timing_reference_waypoint"],
        }
        if requested_weather_window is not None:
            stored_weather_window = (
                (current_analysis.get("flight") or {}).get(
                    "weather_window_preference"
                )
                or {}
            )
            requested_weather_window.update(
                {
                    "before_minutes": (
                        payload.weather_before_minutes
                        if payload.weather_before_minutes is not None
                        else int(stored_weather_window.get("before_minutes", 60))
                    ),
                    "after_minutes": (
                        payload.weather_after_minutes
                        if payload.weather_after_minutes is not None
                        else int(stored_weather_window.get("after_minutes", 60))
                    ),
                }
            )
        save_timing_reference(
            flight_id,
            reference["actual_takeoff_utc"],
            reference["reference_type"],
            reference["reference_utc"],
            reference.get("reference_waypoint"),
            tenant_id=identity.tenant_id,
        )
        timing_changed = True
        updated = get_flight_for_tenant(flight_id, identity.tenant_id)
        if not updated:
            raise RuntimeError("Analysis record was lost after timing update")
        return updated

    def rollback_timing() -> None:
        if not timing_changed or previous_timing is None:
            return
        save_timing_reference(
            flight_id,
            previous_timing["actual_takeoff_utc"],
            previous_timing["reference_type"],
            previous_timing["reference_utc"],
            previous_timing["reference_waypoint"],
            tenant_id=identity.tenant_id,
        )

    failure_detail = _execute_analysis(
        flight_id,
        flight,
        weather_window_preference=requested_weather_window,
        locked_mutation=apply_timing,
        rollback_locked_mutation=rollback_timing,
        preserve_previous_on_failure=True,
        commit_locked_mutation_on_report_failure=True,
        failure_label="timing update",
    )
    if failure_detail:
        raise HTTPException(status_code=422, detail=failure_detail)
    refreshed = get_flight_for_tenant(flight_id, identity.tenant_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return JSONResponse(_service_summary(refreshed))


@app.post("/v1/analyses/{analysis_id}/weather-window")
def update_service_weather_window(
    request: Request,
    analysis_id: str,
    payload: ServiceWeatherWindowRequest,
):
    """Re-run the active analysis with a new weather relevance window.

    This deliberately does not create or alter an actual-takeoff reference.
    Existing scheduled/actual timing and surface overlays are preserved by the
    normal analysis executor while every stored view and PDF is regenerated.
    """
    identity = request_service_identity(request)
    flight, _analysis = _service_analysis(analysis_id, identity)
    failure_detail = _execute_analysis(
        int(flight["id"]),
        flight,
        weather_window_preference={
            "before_minutes": payload.before_minutes,
            "after_minutes": payload.after_minutes,
        },
        preserve_previous_on_failure=True,
        failure_label="weather-window update",
    )
    if failure_detail:
        raise HTTPException(status_code=422, detail=failure_detail)
    refreshed = get_flight_for_tenant(int(flight["id"]), identity.tenant_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return JSONResponse(_service_summary(refreshed))


@app.post("/v1/analyses/{analysis_id}/notes", status_code=201)
def add_service_personal_note(
    request: Request,
    analysis_id: str,
    payload: ServicePersonalNoteRequest,
):
    identity = request_service_identity(request)
    flight, _analysis = _service_analysis(analysis_id, identity)
    if flight["status"] != "Completed":
        raise HTTPException(
            status_code=409,
            detail="Personal notes can only change a completed analysis.",
        )
    try:
        values = validate_personal_note(
            payload.placement,
            payload.note_text,
            payload.include_level1,
            payload.include_level2,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    flight_id = int(flight["id"])
    note_id: int | None = None

    def add_note(claimed_flight):
        nonlocal note_id
        if claimed_flight["status"] != "Completed":
            raise RuntimeError("Personal notes require a completed analysis")
        note_id = create_personal_note(flight_id, *values)
        return claimed_flight

    def rollback_added_note() -> None:
        if note_id is not None and get_personal_note(flight_id, note_id):
            delete_personal_note(flight_id, note_id)

    failure_detail = _execute_analysis(
        flight_id,
        flight,
        locked_mutation=add_note,
        rollback_locked_mutation=rollback_added_note,
        preserve_previous_on_failure=True,
        failure_label="personal-note addition",
    )
    if failure_detail:
        raise HTTPException(status_code=422, detail=failure_detail)

    refreshed = get_flight_for_tenant(flight_id, identity.tenant_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if note_id is None:
        raise HTTPException(status_code=409, detail="Personal note was not retained")
    note = get_personal_note(flight_id, note_id)
    if not note:
        raise HTTPException(status_code=409, detail="Personal note was not retained")
    return JSONResponse(
        {
            "analysis_id": analysis_id,
            "note": serialise_personal_note(dict(note)),
            "notes": _service_personal_notes(flight_id),
        },
        status_code=201,
    )


@app.delete("/v1/analyses/{analysis_id}/notes/{note_id}")
def delete_service_personal_note(
    request: Request,
    analysis_id: str,
    note_id: int,
):
    identity = request_service_identity(request)
    flight, _analysis = _service_analysis(analysis_id, identity)
    if flight["status"] != "Completed":
        raise HTTPException(
            status_code=409,
            detail="Personal notes can only change a completed analysis.",
        )

    flight_id = int(flight["id"])
    if not get_personal_note(flight_id, note_id):
        raise HTTPException(status_code=404, detail="Personal note not found")
    note_snapshot: dict | None = None
    note_deleted = False

    def delete_note(claimed_flight):
        nonlocal note_snapshot, note_deleted
        if claimed_flight["status"] != "Completed":
            raise RuntimeError("Personal notes require a completed analysis")
        current_note = get_personal_note(flight_id, note_id)
        if not current_note:
            raise RuntimeError("Personal note no longer exists")
        note_snapshot = dict(current_note)
        delete_personal_note(flight_id, note_id)
        note_deleted = True
        return claimed_flight

    def rollback_deleted_note() -> None:
        if note_deleted and note_snapshot is not None:
            restore_personal_note(flight_id, note_snapshot)

    failure_detail = _execute_analysis(
        flight_id,
        flight,
        locked_mutation=delete_note,
        rollback_locked_mutation=rollback_deleted_note,
        preserve_previous_on_failure=True,
        failure_label="personal-note deletion",
    )
    if failure_detail:
        raise HTTPException(status_code=422, detail=failure_detail)

    refreshed = get_flight_for_tenant(flight_id, identity.tenant_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return JSONResponse(
        {
            "analysis_id": analysis_id,
            "notes": _service_personal_notes(flight_id),
        }
    )


@app.post("/v1/analyses/{analysis_id}/surface-overlays")
async def update_service_surface_overlays(
    request: Request,
    analysis_id: str,
    payload: SurfaceOverlayRequest,
):
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    claimed_flight = claim_analysis(int(flight["id"]), identity.tenant_id)
    if claimed_flight is None:
        raise HTTPException(status_code=409, detail="Analysis is already in progress")
    try:
        analysis = load_analysis(claimed_flight["analysis_path"])
        if not analysis:
            raise ValueError("Analysis is not complete")
        overlays = validated_surface_overlays(
            payload,
            analysis.get("flight") or {},
        )
        prepared = await attach_surface_report_maps(
            analysis_id,
            overlays,
            map_settings,
        )
        _publish_surface_overlay_reports(claimed_flight, analysis, prepared)
        record_audit_event(
            tenant_id=identity.tenant_id,
            actor_id=identity.user_id,
            action=(
                "analysis.surface_overlays_published"
                if prepared
                else "analysis.surface_overlays_cleared"
            ),
            resource_type="analysis",
            resource_id=analysis_id,
            details={
                "cleared": not prepared,
                "airports": [
                    {
                        "icao": overlay["icao"],
                        "role": overlay["role"],
                        "mapped": overlay["counts"]["mapped"],
                        "review_required": overlay["counts"]["reviewRequired"],
                        "map_mode": (overlay.get("report_map") or {}).get("mode"),
                    }
                    for overlay in prepared
                ],
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        restore_analysis_state(
            int(claimed_flight["id"]),
            str(claimed_flight["status"]),
            claimed_flight["notes"],
            claimed_flight["last_error"],
            tenant_id=identity.tenant_id,
            analysis_failure_category=claimed_flight[
                "analysis_failure_category"
            ],
        )
    return JSONResponse({
        "analysis_id": analysis_id,
        "surface_overlays": _surface_overlay_summary(prepared),
        "report_links": _service_summary(claimed_flight)["links"],
    })


@app.post("/v1/analyses/{analysis_id}/reports/render")
async def render_service_reports(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    _service_flight(analysis_id, identity)
    try:
        result = await refresh_reports_for_analysis(
            analysis_id,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            settings=map_settings,
        )
    except ReportRefreshClaimConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Analysis is already in progress",
        ) from exc
    except (LookupError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refreshed_flight = _service_flight(analysis_id, identity)
    return JSONResponse({
        "analysis_id": analysis_id,
        "map_render": result,
        "report_refresh": _report_refresh_summary(refreshed_flight),
        "links": _service_summary(refreshed_flight)["links"],
    })


@app.get("/v1/analyses/{analysis_id}/reports/combined")
def get_service_combined_report(request: Request, analysis_id: str):
    """The one-PDF Flight Briefing (07 Aug spec), rendered on demand from the
    stored analysis and cached against its exact artifact state. Serving on
    demand means analyses stored before this release - including currently
    open flights - get the combined briefing without re-analysis."""
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    _require_current_reports(flight)
    analysis_path = _stored_file(
        flight["analysis_path"], RESULT_DIR, "Analysis not generated"
    )
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis_flight = analysis.get("flight") or {}
    findings = analysis.get("findings") or []
    warnings = (analysis.get("view") or {}).get("warnings") or []
    weather_charts = analysis.get("weather_charts")
    source_path: str | None
    try:
        source_path = str(
            _stored_file(flight["source_path"], UPLOAD_DIR, "Source PDF not found")
        )
    except HTTPException:
        source_path = None
    if not analysis_flight.get("fuel_summary") and source_path:
        # Older stored analyses predate the page-1 summary parser. The source
        # document is held, so derive it deterministically now rather than
        # rendering a review flag over data we can prove.
        from .odss.parser import extract_pages, parse_page1_fuel_summary

        try:
            analysis_flight["fuel_summary"] = parse_page1_fuel_summary(
                extract_pages(Path(source_path))[0]
            )
        except (OSError, ValueError):
            analysis_flight["fuel_summary"] = None
    token = sha256(
        f"{analysis_path.stat().st_mtime_ns}:{flight['id']}".encode("utf-8")
    ).hexdigest()[:16]
    cache_path = REPORT_DIR / f"flight_{flight['id']}_combined_{token}.pdf"
    if not cache_path.exists():
        staging = cache_path.with_suffix(".tmp")
        try:
            render_combined_briefing(
                analysis_flight,
                findings,
                warnings,
                staging,
                source_pdf_path=source_path,
                weather_charts=weather_charts,
            )
            staging.replace(cache_path)
        finally:
            staging.unlink(missing_ok=True)
        for stale in REPORT_DIR.glob(f"flight_{flight['id']}_combined_*.pdf"):
            if stale != cache_path:
                stale.unlink(missing_ok=True)
    return FileResponse(
        cache_path,
        filename=f"{flight['flight_number'] or analysis_id}_Flight_Briefing.pdf",
        media_type="application/pdf",
    )


@app.get("/v1/analyses/{analysis_id}/reports/level-1")
def get_service_level_1_report(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    _require_current_reports(flight)
    path = _stored_file(flight["level1_report"], REPORT_DIR, "Level 1 report not generated")
    return FileResponse(
        path,
        filename=f"{flight['flight_number'] or analysis_id}_level_1.pdf",
        media_type="application/pdf",
    )


@app.get("/v1/analyses/{analysis_id}/reports/level-2")
def get_service_level_2_report(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    _require_current_reports(flight)
    path = _stored_file(flight["level2_report"], REPORT_DIR, "Level 2 report not generated")
    return FileResponse(
        path,
        filename=f"{flight['flight_number'] or analysis_id}_level_2.pdf",
        media_type="application/pdf",
    )


@app.get("/v1/analyses/{analysis_id}/level-3")
def get_service_level_3(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    path = _stored_file(
        flight["level3_json"],
        RESULT_DIR,
        "Level 3 artifact not generated",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="Level 3 artifact is unavailable") from exc
    return JSONResponse(payload)


@app.get("/v1/analyses/{analysis_id}/reports/level-3")
def get_service_level_3_report(request: Request, analysis_id: str):
    identity = request_service_identity(request)
    flight = _service_flight(analysis_id, identity)
    path = _stored_file(
        flight["level3_report"],
        REPORT_DIR,
        "Level 3 report not generated",
    )
    return FileResponse(
        path,
        filename=f"{flight['flight_number'] or analysis_id}_level_3.pdf",
        media_type="application/pdf",
    )


@app.post("/v1/analyses/{analysis_id}/level-3/questions/{question_id}")
def answer_service_level_3_question(
    request: Request,
    analysis_id: str,
    question_id: str,
    payload: ServiceLevel3AnswerRequest,
):
    identity = request_service_identity(request)
    flight, _analysis = _service_analysis(analysis_id, identity)
    current_path = _stored_file(
        flight["level3_json"],
        RESULT_DIR,
        "Level 3 artifact not generated",
    )
    current = json.loads(current_path.read_text(encoding="utf-8"))
    question = next(
        (
            item
            for item in current.get("pilot_questions") or []
            if item.get("question_id") == question_id
        ),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Level 3 question not found")
    if payload.declined:
        answer_text = None
        answer_state = "declined"
    else:
        answer_text = " ".join(str(payload.answer or "").split())
        if answer_text not in (question.get("options") or []):
            raise HTTPException(
                status_code=400,
                detail="Answer must be one of the approved scoped options.",
            )
        answer_state = "answered"
    save_level3_answer(
        tenant_id=identity.tenant_id,
        analysis_id=analysis_id,
        question_id=question_id,
        answer_text=answer_text,
        answer_state=answer_state,
        answered_by=identity.user_id,
    )
    record_audit_event(
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        action="level3.question_recorded",
        resource_type="analysis",
        resource_id=analysis_id,
        details={
            "question_id": question_id,
            "answer_state": answer_state,
            "pilot_entered": True,
            "validated": False,
        },
    )
    regenerated = generate_level3_artifacts(
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        analysis_id=analysis_id,
        analysis_path=Path(str(flight["analysis_path"])),
        result_dir=RESULT_DIR,
        report_dir=REPORT_DIR,
    )
    return JSONResponse(regenerated["artifact"])


def _load_service_analysis(analysis_id: str, tenant_id: str) -> dict | None:
    flight = get_flight_by_analysis_id(analysis_id, tenant_id)
    return load_analysis(flight["analysis_path"]) if flight else None


app.include_router(
    create_map_router(
        load_analysis=_load_service_analysis,
        load_identity=request_service_identity,
        templates=templates,
        settings=map_settings,
    )
)
