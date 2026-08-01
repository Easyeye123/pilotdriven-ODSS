from __future__ import annotations

import sys
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
import app.main as main
from app.personal_notes import validate_personal_note


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
def web_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "data" / "odss.db")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "data" / "uploads")
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path / "data" / "reports")
    monkeypatch.setattr(main, "RESULT_DIR", tmp_path / "data" / "results")
    with TestClient(main.app, follow_redirects=False) as client:
        yield client


def _upload_and_analyse(client: TestClient) -> int:
    response = client.post(
        "/upload",
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert response.status_code == 303
    flight_id = int(response.headers["location"].rsplit("/", 1)[1])
    assert client.post(f"/flights/{flight_id}/analyse").status_code == 303
    assert database.get_flight(flight_id)["status"] == "Completed"
    return flight_id


def _pdf_text(response) -> str:
    reader = PdfReader(BytesIO(response.content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_personal_note_validation_requires_text_and_report_level() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_personal_note("departure", "   ", True, True)
    with pytest.raises(ValueError, match="Select Level 1"):
        validate_personal_note("departure", "Brief the runway change", False, False)
    with pytest.raises(ValueError, match="valid personal-note placement"):
        validate_personal_note("unknown", "Brief the runway change", True, True)


def test_personal_notes_are_persisted_positioned_and_regenerate_reports(
    web_app: TestClient,
) -> None:
    client = web_app
    flight_id = _upload_and_analyse(client)

    response = client.post(
        f"/flights/{flight_id}/notes",
        data={
            "placement": "departure",
            "note_text": "Confirm departure stand and pushback plan.",
            "include_level1": "on",
            "include_level2": "on",
        },
    )
    assert response.status_code == 303
    notes = database.list_personal_notes(flight_id)
    assert len(notes) == 1
    note_id = notes[0]["id"]

    workspace = client.get(f"/flights/{flight_id}")
    assert workspace.status_code == 200
    assert "Confirm departure stand and pushback plan." in workspace.text
    assert "Departure airport section" in workspace.text

    analysis = client.get(f"/files/analysis/{flight_id}").json()
    assert analysis["schema_version"] == "0.6.1"
    assert analysis["view"]["personal_note_count"] == 1
    assert analysis["flight"]["personal_notes"][0]["placement"] == "departure"

    level1_text = _pdf_text(client.get(f"/files/report/{flight_id}/1"))
    level2_text = _pdf_text(client.get(f"/files/report/{flight_id}/2"))
    level1_compact = " ".join(level1_text.split())
    level2_compact = " ".join(level2_text.split())
    assert "DEPARTURE -" in level1_text
    assert "Confirm departure stand and pushback plan." in level1_compact
    assert "Pilot-entered note." in level1_compact
    assert "Departure airport - personal notes" in level2_compact
    assert "Confirm departure stand and pushback plan." in level2_compact
    assert "pilot-entered note" in level2_compact

    response = client.post(
        f"/flights/{flight_id}/notes",
        data={
            "placement": "communications",
            "note_text": "Monitor the company frequency before the FIR transfer.",
            "include_level2": "on",
        },
    )
    assert response.status_code == 303
    level1_text = _pdf_text(client.get(f"/files/report/{flight_id}/1"))
    level2_text = _pdf_text(client.get(f"/files/report/{flight_id}/2"))
    level2_compact = " ".join(level2_text.split())
    assert "Monitor the company frequency before the FIR transfer." not in level1_text
    assert "LEVEL 2 - OCEANIC / FIR COMMUNICATIONS" in level2_text
    assert "PERSONAL NOTE" in level2_compact
    assert "Monitor the company frequency before the FIR transfer." in level2_compact

    response = client.post(
        f"/flights/{flight_id}/notes/{note_id}/update",
        data={
            "placement": "destination",
            "note_text": "Confirm destination stand and towing requirement.",
            "include_level1": "on",
            "include_level2": "on",
        },
    )
    assert response.status_code == 303
    updated = database.get_personal_note(flight_id, note_id)
    assert updated["placement"] == "destination"
    assert updated["note_text"] == "Confirm destination stand and towing requirement."
    level1_text = _pdf_text(client.get(f"/files/report/{flight_id}/1"))
    level1_compact = " ".join(level1_text.split())
    assert "DESTINATION -" in level1_text
    assert "Confirm destination stand and towing requirement." in level1_compact
    assert "Confirm departure stand and pushback plan." not in level1_compact

    response = client.post(f"/flights/{flight_id}/notes/{note_id}/delete")
    assert response.status_code == 303
    assert database.get_personal_note(flight_id, note_id) is None
    level1_text = _pdf_text(client.get(f"/files/report/{flight_id}/1"))
    assert "Confirm destination stand and towing requirement." not in level1_text


def test_note_without_selected_report_level_is_rejected(web_app: TestClient) -> None:
    client = web_app
    flight_id = _upload_and_analyse(client)
    response = client.post(
        f"/flights/{flight_id}/notes",
        data={
            "placement": "separate",
            "note_text": "Dashboard-only note",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Select Level 1")
    assert database.list_personal_notes(flight_id) == []


def test_stale_dashboard_note_update_and_delete_losers_do_not_mutate(
    web_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = web_app
    flight_id = _upload_and_analyse(client)
    added = client.post(
        f"/flights/{flight_id}/notes",
        data={
            "placement": "departure",
            "note_text": "Keep this exact note while another refresh owns the flight.",
            "include_level1": "on",
            "include_level2": "on",
        },
    )
    assert added.status_code == 303
    note = database.list_personal_notes(flight_id)[0]
    note_snapshot = dict(note)
    stale_flight = database.get_flight_for_tenant(
        flight_id,
        main._dashboard_tenant_id(),
    )
    assert stale_flight is not None
    artifact_paths = {
        field: Path(str(stale_flight[field]))
        for field in ("analysis_path", "level1_report", "level2_report")
    }
    artifact_bytes = {field: path.read_bytes() for field, path in artifact_paths.items()}

    claimed = database.claim_analysis(flight_id, main._dashboard_tenant_id())
    assert claimed is not None
    original_update = main.update_personal_note
    original_delete = main.delete_personal_note
    mutation_calls = {"update": 0, "delete": 0}

    def counted_update(*args, **kwargs):
        mutation_calls["update"] += 1
        return original_update(*args, **kwargs)

    def counted_delete(*args, **kwargs):
        mutation_calls["delete"] += 1
        return original_delete(*args, **kwargs)

    monkeypatch.setattr(main, "get_flight_for_tenant", lambda *args: stale_flight)
    monkeypatch.setattr(main, "update_personal_note", counted_update)
    monkeypatch.setattr(main, "delete_personal_note", counted_delete)
    try:
        rejected_update = client.post(
            f"/flights/{flight_id}/notes/{note['id']}/update",
            data={
                "placement": "destination",
                "note_text": "This stale update must never be stored.",
                "include_level1": "on",
                "include_level2": "on",
            },
        )
        rejected_delete = client.post(
            f"/flights/{flight_id}/notes/{note['id']}/delete",
        )
    finally:
        database.restore_analysis_state(
            flight_id,
            str(claimed["status"]),
            claimed["notes"],
            claimed["last_error"],
            tenant_id=main._dashboard_tenant_id(),
        )

    stored_note = database.get_personal_note(flight_id, int(note["id"]))
    assert rejected_update.status_code == 303
    assert rejected_delete.status_code == 303
    assert "notice=analysis-running" in rejected_update.headers["location"]
    assert "notice=analysis-running" in rejected_delete.headers["location"]
    assert mutation_calls == {"update": 0, "delete": 0}
    assert stored_note is not None
    assert dict(stored_note) == note_snapshot
    for field, path in artifact_paths.items():
        assert path.read_bytes() == artifact_bytes[field]
