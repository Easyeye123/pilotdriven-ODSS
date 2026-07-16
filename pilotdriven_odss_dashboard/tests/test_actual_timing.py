from __future__ import annotations

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
        "LIDO CFP PAGE 2\nTAKEOFF PERFORMANCE\nWSSS RWY 02L\nRWY COND: DRY\n",
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


@pytest.fixture
def timing_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "data" / "odss.db")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path / "data" / "reports")
    monkeypatch.setattr(main, "RESULT_DIR", tmp_path / "data" / "results")
    with TestClient(main.app, follow_redirects=False) as client:
        yield client


def _upload(client: TestClient) -> int:
    response = client.post(
        "/upload",
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_actual_takeoff_entry_runs_analysis_and_calculates_waypoint_utc(
    timing_app: TestClient,
) -> None:
    flight_id = _upload(timing_app)

    response = timing_app.post(
        f"/flights/{flight_id}/timing",
        data={
            "reference_type": "takeoff",
            "reference_date": "2026-07-11",
            "reference_time": "10:45",
            "reference_waypoint": "",
        },
    )
    flight = database.get_flight(flight_id)
    analysis = timing_app.get(f"/files/analysis/{flight_id}").json()

    assert response.status_code == 303
    assert flight is not None
    assert flight["status"] == "Completed"
    assert flight["actual_takeoff_utc"] == "2026-07-11T10:45:00+00:00"
    assert analysis["schema_version"] == "0.4.0"
    assert analysis["view"]["timing"]["actual_takeoff_display"] == "11 JUL 1045Z"
    waypoint_times = {
        item["display_name"]: item["utc_clock"]
        for item in analysis["view"]["timing"]["waypoints"]
    }
    assert waypoint_times["BOBI1"] == "1100Z"
    assert waypoint_times["BOBI2"] == "1110Z"
    assert any(item["engine"] == "actual_timing" for item in analysis["findings"])


def test_waypoint_ata_derives_takeoff_anchor_and_recalculates_route(
    timing_app: TestClient,
) -> None:
    flight_id = _upload(timing_app)
    assert timing_app.post(f"/flights/{flight_id}/analyse").status_code == 303

    response = timing_app.post(
        f"/flights/{flight_id}/timing",
        data={
            "reference_type": "waypoint_ata",
            "reference_date": "2026-07-11",
            "reference_time": "11:15",
            "reference_waypoint": "BOBI2",
        },
    )
    flight = database.get_flight(flight_id)
    analysis = timing_app.get(f"/files/analysis/{flight_id}").json()

    assert response.status_code == 303
    assert flight is not None
    assert flight["actual_takeoff_utc"] == "2026-07-11T10:50:00+00:00"
    assert flight["timing_reference_type"] == "waypoint_ata"
    assert flight["timing_reference_waypoint"] == "BOBI2"
    assert analysis["view"]["timing"]["reference"]["reference_waypoint"] == "BOBI2"
    waypoint_times = {
        item["display_name"]: item["utc_clock"]
        for item in analysis["view"]["timing"]["waypoints"]
    }
    assert waypoint_times["BOBI1"] == "1105Z"
    assert waypoint_times["BOBI2"] == "1115Z"


def test_unknown_waypoint_ata_is_rejected_without_changing_clock(
    timing_app: TestClient,
) -> None:
    flight_id = _upload(timing_app)
    assert timing_app.post(f"/flights/{flight_id}/analyse").status_code == 303

    response = timing_app.post(
        f"/flights/{flight_id}/timing",
        data={
            "reference_type": "waypoint_ata",
            "reference_date": "2026-07-11",
            "reference_time": "11:15",
            "reference_waypoint": "NOTONROUTE",
        },
    )
    flight = database.get_flight(flight_id)

    assert response.status_code == 400
    assert "was not found in the parsed CFP route" in response.json()["detail"]
    assert flight is not None
    assert flight["actual_takeoff_utc"] is None
