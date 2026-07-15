from __future__ import annotations

from pathlib import Path
import shutil
import traceback
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analysis import infer_metadata, load_analysis, run_odss_analysis
from .database import (
    attach_report,
    complete_analysis,
    create_flight,
    get_flight,
    init_db,
    list_flights,
    update_status,
)

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
REPORT_DIR = BASE_DIR / "data" / "reports"
RESULT_DIR = BASE_DIR / "data" / "results"
TEMPLATE_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="PilotDriven ODSS Personal Dashboard", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


@app.on_event("startup")
def startup() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


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
    filename = file.filename or "uploaded.pdf"
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
    dest = UPLOAD_DIR / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

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
    flight_id = create_flight(record)
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

    update_status(flight_id, "Processing", "Parsing Lido CFP and running ODSS engines.")
    try:
        result = run_odss_analysis(
            Path(flight["source_path"]),
            result_dir=RESULT_DIR,
            report_dir=REPORT_DIR,
            flight_id=flight_id,
        )
        complete_analysis(flight_id, result)
    except Exception as exc:
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
    filename = file.filename or "report.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Report must be a PDF")
    dest = REPORT_DIR / f"flight_{flight_id}_level_{level}_{Path(filename).name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    attach_report(flight_id, level, str(dest))
    return RedirectResponse(url=f"/flights/{flight_id}", status_code=303)


@app.get("/files/source/{flight_id}")
def download_source(flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    return FileResponse(
        flight["source_path"],
        filename=flight["source_filename"],
        media_type="application/pdf",
    )


@app.get("/files/report/{flight_id}/{level}")
def download_report(flight_id: int, level: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if level not in (1, 2):
        raise HTTPException(status_code=400, detail="Report level must be 1 or 2")
    path = flight["level1_report"] if level == 1 else flight["level2_report"]
    if not path:
        raise HTTPException(status_code=404, detail="Report not generated")
    return FileResponse(path, filename=Path(path).name, media_type="application/pdf")


@app.get("/files/analysis/{flight_id}")
def download_analysis(flight_id: int):
    flight = get_flight(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    path = flight["analysis_path"]
    if not path:
        raise HTTPException(status_code=404, detail="Analysis not generated")
    return FileResponse(path, filename=Path(path).name, media_type="application/json")
