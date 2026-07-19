from __future__ import annotations

import base64
import sys
from collections.abc import Iterator
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
import app.main as main


def _build_lido_pdf() -> bytes:
    pages = [
        """SUMMARY CFP
9V-SMG SIA304 SIN/BRU ETD 1030 11JUL26
SCHED DEP 1030 UTC SCHED ARR 2200 UTC
RTE NO 001 A350-941
CRUISE CI 35
EDTO/RVSM
WSSS/02L
DCT BOBI1 DCT BOBI2 EBBR/25L
BURNOFF 11.30 050000
STAT CONT 00.30 002000
ALTN FUEL 00.20 001500
ALTN HOLD 00.15 001000
TAXI FUEL 001000
FLT PLAN REQMT 13.00 060000
FUEL IN TANKS 14.00 065000
PZFW 180000
PTOW 245000
PLWT 195000
""",
        "LIDO CFP PAGE 2\nTAKEOFF PERFORMANCE\nWSSS RWY 02L\nRWY COND:  DRY\nEOSID : STRAIGHT OUT.\n",
        "LIDO CFP PAGE 3\nEDTO INFORMATION\n",
        "LIDO CFP PAGE 4\nFUEL AND MASS SUMMARY\n",
        "LIDO CFP PAGE 5\nALTERNATE SUMMARY\n",
        "LIDO CFP PAGE 6\nROUTE LOG CONTINUED\n",
        """LIDO CFP PAGE 7
BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox((36, 36, 560, 806), text, fontname="courier", fontsize=9)
        return document.tobytes()
    finally:
        document.close()


@pytest.fixture(scope="session")
def lido_pdf() -> bytes:
    return _build_lido_pdf()


@pytest.fixture
def web_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, dict[str, Path]]]:
    paths = {
        "database": tmp_path / "data" / "odss.db",
        "uploads": tmp_path / "data" / "uploads",
        "reports": tmp_path / "data" / "reports",
        "results": tmp_path / "data" / "results",
    }
    monkeypatch.setattr(database, "DB_PATH", paths["database"])
    monkeypatch.setattr(main, "UPLOAD_DIR", paths["uploads"])
    monkeypatch.setattr(main, "REPORT_DIR", paths["reports"])
    monkeypatch.setattr(main, "RESULT_DIR", paths["results"])
    with TestClient(main.app, follow_redirects=False) as client:
        yield client, paths


def _upload(client: TestClient, content: bytes, filename: str = "SQ304.pdf") -> int:
    response = client.post(
        "/upload",
        files={"file": (filename, content, "application/pdf")},
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_long_filename_upload_analyse_and_downloads(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, paths = web_app
    filename = f"SQ304-{'A' * 300}.pdf"
    flight_id = _upload(client, lido_pdf, filename)
    uploaded = database.get_flight(flight_id)

    assert uploaded is not None
    assert uploaded["status"] == "Uploaded"
    assert uploaded["source_filename"].startswith("SQ304-")
    assert len(uploaded["source_filename"]) <= 164
    assert Path(uploaded["source_path"]).parent == paths["uploads"]
    assert Path(uploaded["source_path"]).name.startswith("cfp_")
    assert Path(uploaded["source_path"]).read_bytes() == lido_pdf

    response = client.post(f"/flights/{flight_id}/analyse")
    completed = database.get_flight(flight_id)

    assert response.status_code == 303
    assert completed is not None
    assert completed["status"] == "Completed"
    assert completed["last_error"] is None
    assert Path(completed["analysis_path"]).parent == paths["results"]
    assert Path(completed["level1_report"]).parent == paths["reports"]
    assert Path(completed["level2_report"]).parent == paths["reports"]

    workspace = client.get(f"/flights/{flight_id}")
    source = client.get(f"/files/source/{flight_id}")
    level1 = client.get(f"/files/report/{flight_id}/1")
    level2 = client.get(f"/files/report/{flight_id}/2")
    analysis = client.get(f"/files/analysis/{flight_id}")

    assert workspace.status_code == 200
    assert "Download Level 1 PDF" in workspace.text
    assert "Download Level 2 PDF" in workspace.text
    assert "Download analysis JSON" in workspace.text
    assert source.status_code == 200
    assert source.content == lido_pdf
    assert level1.status_code == 200
    assert level1.content.startswith(b"%PDF")
    assert level2.status_code == 200
    assert level2.content.startswith(b"%PDF")
    assert analysis.status_code == 200
    assert analysis.json()["flight"]["flight_number"] == "SQ304"
    assert analysis.json()["flight"]["departure"] == "WSSS"
    assert analysis.json()["flight"]["destination"] == "EBBR"
    assert analysis.json()["flight"]["performance"]["runway_condition"] == "DRY"
    assert analysis.json()["flight"]["performance"]["eosid"] == "STRAIGHT OUT"
    assert analysis.json()["view"]["page_count"] == 7
    assert len(analysis.json()["flight"]["route_waypoints"]) == 2


def test_health_is_public_and_dashboard_requires_configured_credentials(
    web_app: tuple[TestClient, dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = web_app
    monkeypatch.setenv("ODSS_USERNAME", "boss")
    monkeypatch.setenv("ODSS_PASSWORD", "correct horse battery staple")

    health = client.get("/healthz")
    anonymous = client.get("/")
    wrong = client.get(
        "/",
        headers={"Authorization": "Basic " + base64.b64encode(b"boss:wrong").decode("ascii")},
    )
    authorized = client.get(
        "/",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(b"boss:correct horse battery staple").decode("ascii")
        },
    )

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "0.5.0"}
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"].startswith("Basic")
    assert wrong.status_code == 401
    assert authorized.status_code == 200
    assert authorized.headers["cache-control"] == "no-store"


def test_authenticated_cross_origin_write_is_refused(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = web_app
    monkeypatch.setenv("ODSS_USERNAME", "boss")
    monkeypatch.setenv("ODSS_PASSWORD", "secret")
    authorization = "Basic " + base64.b64encode(b"boss:secret").decode("ascii")

    response = client.post(
        "/upload",
        headers={"Authorization": authorization, "Origin": "https://attacker.example"},
        files={"file": ("SQ304.pdf", lido_pdf, "application/pdf")},
    )

    assert response.status_code == 403
    assert database.list_flights() == []


def test_fake_pdf_is_rejected_without_storage(
    web_app: tuple[TestClient, dict[str, Path]],
) -> None:
    client, paths = web_app

    response = client.post(
        "/upload",
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "File is not a readable PDF"
    assert database.list_flights() == []
    assert list(paths["uploads"].iterdir()) == []


def test_pdf_size_limit_removes_partial_upload(
    web_app: tuple[TestClient, dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, paths = web_app
    monkeypatch.setattr(main, "MAX_PDF_BYTES", 256)

    response = client.post(
        "/upload",
        files={"file": ("oversized.pdf", b"x" * 257, "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "PDF exceeds the 25 MB upload limit."
    assert database.list_flights() == []
    assert list(paths["uploads"].iterdir()) == []


def test_nonexistent_flight_report_creates_no_orphan(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, paths = web_app

    response = client.post(
        "/flights/999/reports/1",
        files={"file": ("report.pdf", lido_pdf, "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Flight not found"
    assert list(paths["reports"].iterdir()) == []


def test_failed_rerun_clears_stale_artifacts_and_links(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, _ = web_app
    flight_id = _upload(client, lido_pdf)
    assert client.post(f"/flights/{flight_id}/analyse").status_code == 303
    completed = database.get_flight(flight_id)

    assert completed is not None
    assert completed["status"] == "Completed"
    assert completed["analysis_path"]
    assert completed["level1_report"]
    assert completed["level2_report"]

    Path(completed["source_path"]).write_bytes(b"broken")
    response = client.post(f"/flights/{flight_id}/analyse")
    failed = database.get_flight(flight_id)
    workspace = client.get(f"/flights/{flight_id}")

    assert response.status_code == 303
    assert failed is not None
    assert failed["status"] == "Failed"
    assert failed["analysis_path"] is None
    assert failed["level1_report"] is None
    assert failed["level2_report"] is None
    assert "Download Level 1 PDF" not in workspace.text
    assert "Download Level 2 PDF" not in workspace.text
    assert "Download analysis JSON" not in workspace.text
    assert "structured findings" not in workspace.text
    assert client.get(f"/files/report/{flight_id}/1").status_code == 404
    assert client.get(f"/files/report/{flight_id}/2").status_code == 404
    assert client.get(f"/files/analysis/{flight_id}").status_code == 404


def test_duplicate_analysis_request_is_rejected(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, _ = web_app
    flight_id = _upload(client, lido_pdf)

    assert database.begin_analysis(flight_id) is True
    response = client.post(f"/flights/{flight_id}/analyse")

    assert response.status_code == 409
    assert response.json()["detail"] == "Analysis is already in progress"
    assert database.get_flight(flight_id)["status"] == "Processing"


def test_startup_recovers_interrupted_analysis(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, _ = web_app
    flight_id = _upload(client, lido_pdf)

    assert database.begin_analysis(flight_id) is True
    database.init_db()
    flight = database.get_flight(flight_id)

    assert flight["status"] == "Failed"
    assert flight["last_error"] == "Analysis interrupted by application shutdown or restart."
    assert database.begin_analysis(flight_id) is True


def test_database_completion_failure_removes_new_artifacts(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, paths = web_app
    flight_id = _upload(client, lido_pdf)

    def fail_completion(*args, **kwargs) -> None:
        raise OSError("database unavailable")

    monkeypatch.setattr(main, "complete_analysis", fail_completion)
    response = client.post(f"/flights/{flight_id}/analyse")
    flight = database.get_flight(flight_id)

    assert response.status_code == 303
    assert flight["status"] == "Failed"
    assert flight["analysis_path"] is None
    assert flight["level1_report"] is None
    assert flight["level2_report"] is None
    assert list(paths["results"].iterdir()) == []
    assert list(paths["reports"].iterdir()) == []


def test_missing_source_file_returns_controlled_404(
    web_app: tuple[TestClient, dict[str, Path]],
    lido_pdf: bytes,
) -> None:
    client, _ = web_app
    flight_id = _upload(client, lido_pdf)
    flight = database.get_flight(flight_id)

    assert flight is not None
    Path(flight["source_path"]).unlink()
    response = client.get(f"/files/source/{flight_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Source PDF not found"
