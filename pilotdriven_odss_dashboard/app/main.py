from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import traceback
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analysis import infer_metadata, load_analysis, run_odss_analysis
from .database import (
    attach_report,
    begin_analysis,
    complete_analysis,
    create_flight,
    get_flight,
    init_db,
    list_flights,
    update_status,
)
from .odss.parser import validate_pdf

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
REPORT_DIR = BASE_DIR / "data" / "reports"
RESULT_DIR = BASE_DIR / "data" / "results"
TEMPLATE_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"
MAX_PDF_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="PilotDriven ODSS Personal Dashboard", version="0.2.1", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


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
    return templates.TemplateResponse(
        request=request,
        name="flight.html",
        context={"flight": flight, "analysis": analysis},
    )


@app.post("/flights/{flight_id}/analyse")
def analyse_flight(flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    previous_artifacts = (
        (flight["analysis_path"], RESULT_DIR),
        (flight["level1_report"], REPORT_DIR),
        (flight["level2_report"], REPORT_DIR),
    )
    if not begin_analysis(flight_id):
        raise HTTPException(status_code=409, detail="Analysis is already in progress")
    result = None
    try:
        for path, directory in previous_artifacts:
            _remove_stored_file(path, directory)
        result = run_odss_analysis(
            Path(flight["source_path"]),
            result_dir=RESULT_DIR,
            report_dir=REPORT_DIR,
            flight_id=flight_id,
        )
        complete_analysis(flight_id, result)
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
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


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
