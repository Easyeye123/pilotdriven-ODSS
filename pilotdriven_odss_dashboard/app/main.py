from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import logging
import os
import secrets
from pathlib import Path
import traceback
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .analysis import infer_metadata, load_analysis, run_odss_analysis
from .config import APP_VERSION, BASE_DIR, DATA_DIR
from .database import (
    attach_report,
    begin_analysis,
    complete_analysis,
    create_flight,
    create_personal_note,
    delete_personal_note,
    get_flight,
    get_flight_by_analysis_id,
    get_flight_by_service_request,
    get_personal_note,
    init_db,
    list_flights,
    list_personal_notes,
    save_timing_reference,
    update_personal_note,
    update_status,
)
from .odss.constants import format_actm
from .odss_map_v06.api import create_map_router
from .odss_map_v06.config import MapSettings
from .odss_map_v06.report_worker import render_reports_for_analysis
from .odss.parser import validate_pdf
from .odss.timing import (
    combine_utc_date_time,
    derive_timing_reference,
    display_utc,
    parse_utc,
)
from .personal_notes import (
    PERSONAL_NOTE_PLACEMENT_LABELS,
    validate_personal_note,
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
    response.headers["Referrer-Policy"] = "no-referrer"
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
        return _secure_response(await call_next(request))

    # The protected print page loads same-origin static assets. A worker's
    # bearer header may therefore authorize static files without weakening the
    # Basic-auth dashboard.
    if request.url.path.startswith("/static/"):
        token = _configured_service_token()
        if token and _is_service_authorized(request, token):
            return _secure_response(await call_next(request))
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


def _execute_analysis(flight_id: int, flight) -> None:
    previous_artifacts = (
        (flight["analysis_path"], RESULT_DIR),
        (flight["level1_report"], REPORT_DIR),
        (flight["level2_report"], REPORT_DIR),
    )
    if not begin_analysis(flight_id):
        raise HTTPException(status_code=409, detail="Analysis is already in progress")

    result = None
    try:
        result = run_odss_analysis(
            Path(flight["source_path"]),
            result_dir=RESULT_DIR,
            report_dir=REPORT_DIR,
            flight_id=flight_id,
            actual_takeoff_utc=flight["actual_takeoff_utc"],
            timing_reference=_timing_reference_from_row(flight),
            personal_notes=[dict(note) for note in list_personal_notes(flight_id)],
        )
        complete_analysis(flight_id, result)
        new_artifacts = (
            (result.get("analysis_path"), RESULT_DIR),
            (result.get("level1_report"), REPORT_DIR),
            (result.get("level2_report"), REPORT_DIR),
        )
        for (previous_path, directory), (new_path, _) in zip(
            previous_artifacts,
            new_artifacts,
            strict=True,
        ):
            if previous_path and previous_path != new_path:
                _remove_stored_file(previous_path, directory)
    except Exception as exc:
        if result:
            _remove_stored_file(result.get("analysis_path"), RESULT_DIR)
            _remove_stored_file(result.get("level1_report"), REPORT_DIR)
            _remove_stored_file(result.get("level2_report"), REPORT_DIR)
        error = f"{type(exc).__name__}: {exc}"
        update_status(
            flight_id,
            "Failed",
            "Analysis failed. The detailed error is shown below.",
            last_error=error,
        )
        traceback.print_exc()


def _regenerate_after_note_change(flight_id: int) -> None:
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        raise HTTPException(status_code=409, detail="Analysis is already in progress")
    if flight["analysis_path"] or flight["status"] == "Completed":
        _execute_analysis(flight_id, flight)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"flights": list_flights()},
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
    }
    try:
        flight_id = create_flight(record)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.get("/flights/{flight_id}", response_class=HTMLResponse)
def flight_workspace(request: Request, flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    analysis = load_analysis(flight["analysis_path"])
    notices = {
        "analysis-running": "Analysis is already running. This page still shows the last completed result.",
        "refresh-failed": "The refresh failed. The last completed reports remain available below.",
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


@app.post("/flights/{flight_id}/analyse")
def analyse_flight(flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running",
            status_code=303,
        )
    _execute_analysis(flight_id, flight)
    refreshed = get_flight(flight_id)
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
    flight = get_flight(flight_id)
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
        reference = derive_timing_reference(
            parsed_flight,
            reference_type,
            reference_datetime.isoformat(),
            reference_waypoint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    save_timing_reference(
        flight_id,
        reference["actual_takeoff_utc"],
        reference["reference_type"],
        reference["reference_utc"],
        reference.get("reference_waypoint"),
    )
    updated_flight = get_flight(flight_id)
    if not updated_flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    _execute_analysis(flight_id, updated_flight)
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.post("/flights/{flight_id}/notes")
def add_personal_note(
    flight_id: int,
    placement: str = Form(...),
    note_text: str = Form(...),
    include_level1: str | None = Form(None),
    include_level2: str | None = Form(None),
):
    flight = get_flight(flight_id)
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
    create_personal_note(flight_id, *values)
    _regenerate_after_note_change(flight_id)
    return RedirectResponse(url=f"/flights/{flight_id}#personal-notes", status_code=303)


@app.post("/flights/{flight_id}/notes/{note_id}/update")
def edit_personal_note(
    flight_id: int,
    note_id: int,
    placement: str = Form(...),
    note_text: str = Form(...),
    include_level1: str | None = Form(None),
    include_level2: str | None = Form(None),
):
    flight = get_flight(flight_id)
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
    update_personal_note(flight_id, note_id, *values)
    _regenerate_after_note_change(flight_id)
    return RedirectResponse(url=f"/flights/{flight_id}#personal-notes", status_code=303)


@app.post("/flights/{flight_id}/notes/{note_id}/delete")
def remove_personal_note(flight_id: int, note_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight["status"] == "Processing":
        return RedirectResponse(
            url=f"/flights/{flight_id}?notice=analysis-running#personal-notes",
            status_code=303,
        )
    if not get_personal_note(flight_id, note_id):
        raise HTTPException(status_code=404, detail="Personal note not found")
    delete_personal_note(flight_id, note_id)
    _regenerate_after_note_change(flight_id)
    return RedirectResponse(url=f"/flights/{flight_id}#personal-notes", status_code=303)


@app.post("/flights/{flight_id}/reports/{level}")
async def upload_report(flight_id: int, level: int, file: UploadFile = File(...)):
    if level not in (1, 2):
        raise HTTPException(status_code=400, detail="Report level must be 1 or 2")
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    _, dest = await _store_pdf(
        file,
        REPORT_DIR,
        f"flight_{flight_id}_level_{level}",
        "report.pdf",
    )
    try:
        attach_report(flight_id, level, str(dest))
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    previous = flight["level1_report"] if level == 1 else flight["level2_report"]
    if previous != str(dest):
        _remove_stored_file(previous, REPORT_DIR)
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.get("/files/source/{flight_id}")
def download_source(flight_id: int):
    flight = get_flight(flight_id)
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
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if level not in (1, 2):
        raise HTTPException(status_code=400, detail="Report level must be 1 or 2")
    stored_path = flight["level1_report"] if level == 1 else flight["level2_report"]
    path = _stored_file(stored_path, REPORT_DIR, "Report not generated")
    filename = f"{flight['flight_number'] or f'flight-{flight_id}'}_level_{level}.pdf"
    return FileResponse(path, filename=filename, media_type="application/pdf")


@app.get("/files/analysis/{flight_id}")
def download_analysis(flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    path = _stored_file(flight["analysis_path"], RESULT_DIR, "Analysis not generated")
    filename = f"{flight['flight_number'] or f'flight-{flight_id}'}_analysis.json"
    return FileResponse(path, filename=filename, media_type="application/json")

class ServiceTimingRequest(BaseModel):
    reference_type: str = Field(pattern="^(takeoff|waypoint_ata)$")
    reference_utc: str
    reference_waypoint: str | None = None


def _public_analysis_id(flight) -> str:
    return str(flight["analysis_id"] or f"legacy-{flight['id']}")


def _service_flight(analysis_id: str):
    flight = get_flight_by_analysis_id(analysis_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return flight


def _service_analysis(analysis_id: str) -> tuple[object, dict]:
    flight = _service_flight(analysis_id)
    analysis = load_analysis(flight["analysis_path"])
    if not analysis:
        raise HTTPException(status_code=409, detail="Analysis is not complete")
    return flight, analysis


def _service_summary(flight) -> dict:
    analysis_id = _public_analysis_id(flight)
    return {
        "analysis_id": analysis_id,
        "analysis_version": flight["analysis_version"] or "0.6.0",
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
        "warnings": [flight["last_error"]] if flight["last_error"] else [],
        "links": {
            "self": f"/v1/analyses/{analysis_id}",
            "briefing": f"/v1/analyses/{analysis_id}/briefing",
            "map_contract": f"/v1/analyses/{analysis_id}/map-contract",
            "route_geojson": f"/v1/analyses/{analysis_id}/route.geojson",
            "markers_geojson": f"/v1/analyses/{analysis_id}/markers.geojson",
            "map_config": f"/v1/analyses/{analysis_id}/map-config",
            "level_1_report": f"/v1/analyses/{analysis_id}/reports/level-1",
            "level_2_report": f"/v1/analyses/{analysis_id}/reports/level-2",
            "timing": f"/v1/analyses/{analysis_id}/timing",
            "render_reports": f"/v1/analyses/{analysis_id}/reports/render",
        },
    }


@app.get("/v1/health")
def service_health():
    return JSONResponse({
        "status": "ok",
        "version": APP_VERSION,
        "map_contract": "1.0",
        "map_provider": map_settings.provider,
        "map_style": map_settings.style,
        "playwright_capture_configured": bool(
            map_settings.aws_location_api_key and map_settings.service_token
        ),
    })


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
):
    tenant_id = request.headers.get("x-pilotdriven-tenant-id")
    service_request_id = request.headers.get("x-pilotdriven-request-id", "").strip() or None
    if service_request_id:
        existing = get_flight_by_service_request(tenant_id, service_request_id)
        if existing:
            return JSONResponse(_service_summary(existing), status_code=200)
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
        "user_id": request.headers.get("x-pilotdriven-user-id"),
        "workspace_id": request.headers.get("x-pilotdriven-workspace-id"),
        "external_flight_id": request.headers.get("x-pilotdriven-flight-id"),
        "analysis_version": "0.6.0",
        "service_request_id": service_request_id,
    }
    try:
        flight_id = create_flight(record)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=500, detail="Analysis record was not created")
    _execute_analysis(flight_id, flight)
    completed = get_flight(flight_id)
    if not completed:
        raise HTTPException(status_code=500, detail="Analysis record was lost")
    if completed["status"] != "Completed":
        raise HTTPException(
            status_code=422,
            detail=completed["last_error"] or "ODSS analysis failed",
        )
    return JSONResponse(_service_summary(completed), status_code=201)


@app.get("/v1/analyses/{analysis_id}")
def get_service_analysis(analysis_id: str):
    return JSONResponse(_service_summary(_service_flight(analysis_id)))


@app.get("/v1/analyses/{analysis_id}/briefing")
def get_service_briefing(analysis_id: str):
    flight, analysis = _service_analysis(analysis_id)
    view = analysis.get("view") or {}
    return JSONResponse({
        "analysis_id": analysis_id,
        "schema_version": analysis.get("schema_version"),
        "flight": analysis.get("flight"),
        "briefing": view.get("briefing"),
        "timing": view.get("timing"),
        "warnings": view.get("warnings") or [],
        "generated_at_utc": view.get("generated_at_utc"),
        "report_links": _service_summary(flight)["links"],
    })


@app.post("/v1/analyses/{analysis_id}/timing")
def update_service_timing(analysis_id: str, payload: ServiceTimingRequest):
    flight, analysis = _service_analysis(analysis_id)
    try:
        reference = derive_timing_reference(
            analysis.get("flight"),
            payload.reference_type,
            parse_utc(payload.reference_utc).isoformat(),
            payload.reference_waypoint or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_timing_reference(
        int(flight["id"]),
        reference["actual_takeoff_utc"],
        reference["reference_type"],
        reference["reference_utc"],
        reference.get("reference_waypoint"),
    )
    updated = get_flight(int(flight["id"]))
    if not updated:
        raise HTTPException(status_code=404, detail="Analysis not found")
    _execute_analysis(int(flight["id"]), updated)
    refreshed = get_flight(int(flight["id"]))
    if not refreshed:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return JSONResponse(_service_summary(refreshed))


@app.post("/v1/analyses/{analysis_id}/reports/render")
async def render_service_reports(analysis_id: str):
    _service_analysis(analysis_id)
    try:
        result = await render_reports_for_analysis(
            analysis_id,
            settings=map_settings,
        )
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({
        "analysis_id": analysis_id,
        "map_render": result,
        "links": _service_summary(_service_flight(analysis_id))["links"],
    })


@app.get("/v1/analyses/{analysis_id}/reports/level-1")
def get_service_level_1_report(analysis_id: str):
    flight = _service_flight(analysis_id)
    path = _stored_file(flight["level1_report"], REPORT_DIR, "Level 1 report not generated")
    return FileResponse(
        path,
        filename=f"{flight['flight_number'] or analysis_id}_level_1.pdf",
        media_type="application/pdf",
    )


@app.get("/v1/analyses/{analysis_id}/reports/level-2")
def get_service_level_2_report(analysis_id: str):
    flight = _service_flight(analysis_id)
    path = _stored_file(flight["level2_report"], REPORT_DIR, "Level 2 report not generated")
    return FileResponse(
        path,
        filename=f"{flight['flight_number'] or analysis_id}_level_2.pdf",
        media_type="application/pdf",
    )


def _load_service_analysis(analysis_id: str) -> dict | None:
    flight = get_flight_by_analysis_id(analysis_id)
    return load_analysis(flight["analysis_path"]) if flight else None


app.include_router(
    create_map_router(
        load_analysis=_load_service_analysis,
        templates=templates,
        settings=map_settings,
    )
)
