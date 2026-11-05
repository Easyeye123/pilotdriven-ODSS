"""ATC-EARLY-CALLS, the served half of the three dashboard states (independent QA of release 539, F1, 25 Oct 2026).

QA saw the early-call list only on a fresh upload; a reopened pack and "Create updated briefing" showed none while the
PDFs printed the calls. The tab QA used was still running the release-537 app (output/pd-atc-dash-20261025/README.md);
the app half of every state is pinned in the app suite (tests/atc-early-calls-dashboard-states-20261025.test.mjs).
This file pins what the service hands each state through `GET /v1/analyses/{id}/briefing`, with genuine OFPs:

  - a fresh upload: the served view carries the composed early calls, the same record the PDF is rendered from;
  - a reopened pack whose stored view predates v118 (saved on 537, where the record had no early calls): the
    held-analysis rebuild serves the calls the current rule reads from the held analysis - nothing is re-analysed;
  - "Create updated briefing": a new analysis of the same held bytes with its saved take-off restored serves the same
    calls with their UTC from that take-off, and its downloaded six-page PDF prints each timed call at its ACTM.

Genuine OFPs come from the private CFP corpus (PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR) and are skipped where not held;
David's SQ301 is not a corpus member and is read only when that directory holds it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
import app.main as main
import app.odss.surface_overlays as surface_overlays
import app.odss_map_v06.report_worker as report_worker
from app.odss.combined_brief import COMBINED_BRIEFING_SCHEMA_VERSION
from app.odss.concise_pdf_gate import normalized
from app.odss.enroute_contact import ENROUTE_CONTACT_RULE, early_call_sentence
from app.odss_map_v06.config import MapSettings

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "SQ301": "SQ30124102026MAN.pdf",       # David's 24 Oct MAN-SIN
    "SQ303": "SQ30316072026BRU 81.pdf",     # the route of the brief GPT handed over
}
# The publication rules and enroute rule a pack saved on release 537 holds (before ATC-EARLY-CALLS).
PRE_V118_PUBLICATION = "2026-10-25-depress-chart-issuance-v117"
PRE_V17_ENROUTE_RULE = "enroute-contact-v16"


def _source(key: str) -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    source = corpus / SOURCES[key]
    if not source.is_file():
        pytest.skip(f"{SOURCES[key]} is not held in the private CFP corpus")
    return source


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data = tmp_path / "data"
    monkeypatch.setattr(database, "DB_PATH", data / "odss.db")
    monkeypatch.setattr(main, "UPLOAD_DIR", data / "uploads")
    monkeypatch.setattr(main, "REPORT_DIR", data / "reports")
    monkeypatch.setattr(main, "RESULT_DIR", data / "results")
    monkeypatch.setattr(report_worker, "MAP_DIR", data / "maps")
    monkeypatch.setattr(surface_overlays, "SURFACE_MAP_DIR", data / "maps")
    monkeypatch.setattr(main, "map_settings", MapSettings())
    monkeypatch.setenv("ODSS_SERVICE_TOKEN", "service-test-token")
    monkeypatch.delenv("AWS_LOCATION_API_KEY", raising=False)
    with TestClient(main.app, follow_redirects=False) as client:
        yield client


HEADERS = {"Authorization": "Bearer service-test-token", "X-PilotDriven-Tenant-Id": "tenant-1", "X-PilotDriven-User-Id": "pilot-7"}


def _analyse(client: TestClient, source: Path) -> str:
    response = client.post("/v1/analyses", headers=HEADERS, files={"file": (source.name, source.read_bytes(), "application/pdf")},
                           data={"weather_before_minutes": "60", "weather_after_minutes": "60"})
    assert response.status_code == 201, response.text[:300]
    return response.json()["analysis_id"]


def _served(client: TestClient, analysis_id: str) -> dict:
    response = client.get(f"/v1/analyses/{analysis_id}/briefing", headers=HEADERS)
    assert response.status_code == 200, response.text[:300]
    return response.json()


def _calls(served: dict) -> list[dict]:
    record = served["briefing"]["enroute_contact"]
    assert record["rule"] == ENROUTE_CONTACT_RULE
    return record["early_calls"]


def _identity(call: dict) -> tuple:
    return (call["fir"], tuple(call["notam_ids"]), (call.get("call_window") or {}).get("by_actm"), call.get("entry_fir"), call.get("entry_actm"))


@pytest.mark.parametrize("key", ["SQ301", "SQ303"])
def test_served_early_calls_in_the_fresh_reopened_and_updated_states(key, service: TestClient):
    source = _source(key)

    # Fresh upload: the served view is the one the PDF renders from, and it holds the composed calls.
    fresh_id = _analyse(service, source)
    fresh = _served(service, fresh_id)
    fresh_calls = _calls(fresh)
    assert len([call for call in fresh_calls if call.get("call_window")]) >= 2, f"{key} holds its timed early calls"
    assert fresh["briefing"]["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    assert fresh["rebuilt_from_held_analysis"] is False

    # Reopened pack saved before v118: its stored view has no early calls. The service rebuilds the view from the held
    # analysis under the rules in service and serves the calls the current rule reads - the same as the fresh ones.
    analysis_paths = sorted((main.RESULT_DIR).rglob("*_analysis.json"), key=lambda p: p.stat().st_mtime)
    assert analysis_paths, "the stored analysis is held"
    stored_path = analysis_paths[-1]
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    view_briefing = stored["view"]["briefing"]
    view_briefing["publication_rules"] = PRE_V118_PUBLICATION
    record = view_briefing["enroute_contact"]
    record.pop("early_calls")
    record["rule"] = PRE_V17_ENROUTE_RULE
    record["state_sentence"] = "No approved early-call rule is held. " + record["state_sentence"].split("held. ", 1)[-1]
    stored_path.write_text(json.dumps(stored), encoding="utf-8")
    reopened = _served(service, fresh_id)
    assert reopened["rebuilt_from_held_analysis"] is True
    assert reopened["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    assert [early_call_sentence(call) for call in _calls(reopened)] == [early_call_sentence(call) for call in fresh_calls]
    assert not reopened["briefing"]["enroute_contact"]["state_sentence"].startswith("No approved early-call rule")

    # Create updated briefing: a new analysis of the same held bytes, the saved take-off restored through /timing.
    updated_id = _analyse(service, source)
    std = dt.datetime.fromisoformat(fresh["flight"]["scheduled_departure_utc"].replace("Z", "+00:00"))
    atot = (std + dt.timedelta(minutes=17)).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = service.post(f"/v1/analyses/{updated_id}/timing", headers=HEADERS, json={"reference_type": "takeoff", "reference_utc": atot})
    assert response.status_code == 200, response.text[:300]
    updated = _served(service, updated_id)
    updated_calls = _calls(updated)
    assert [_identity(call) for call in updated_calls] == [_identity(call) for call in fresh_calls]
    for call in updated_calls:
        if call.get("call_window"):
            due = call["call_window"].get("from_actm") or call["call_window"]["by_actm"]
            hours, minutes = (int(part) for part in due.split(":"))
            expected = (dt.datetime.fromisoformat(atot.replace("Z", "+00:00")) + dt.timedelta(hours=hours, minutes=minutes)).strftime("%H%MZ")
            assert call["due_utc"] == expected, f"{call['notam_ids']}: UTC from the restored take-off"

    # The updated copy's downloaded six-page PDF prints each timed call at its ACTM (whole, or named on the line).
    response = service.get(f"/v1/analyses/{updated_id}/reports/combined", headers=HEADERS)
    assert response.status_code == 200, response.text[:300]
    with fitz.open(stream=response.content, filetype="pdf") as document:
        pages = [page.get_text() for page in document]
    assert len(pages) == 6
    page6 = normalized(pages[5])
    for call in updated_calls:
        if not call.get("call_window"):
            continue
        due = call["call_window"].get("from_actm") or call["call_window"]["by_actm"]
        assert normalized(f"ACTM {due}") in page6, f"{call['notam_ids']} at ACTM {due} on page 6"
        assert all(normalized(notice) in page6 for notice in call["notam_ids"]), f"{call['notam_ids']} named on page 6"
