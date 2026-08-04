from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HELPYOU_TESTBED_DB", str(tmp_path / "testbed.db"))
    app_module = importlib.import_module("testbed.app")
    importlib.reload(app_module)
    return TestClient(app_module.app)


def create_scenario(client: TestClient) -> dict:
    response = client.post(
        "/api/sessions",
        json={
            "mode": "flight_scenario",
            "case_id": "SQ23-25JUL26-OEI-ETP1-1D",
            "scenario": "Stable one-engine-inoperative condition at ETP1-1D.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_page_uses_flight_briefing_public_name(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Flight Briefing baseline" in response.text
    assert "PilotDriven ODSS" not in response.text


def test_new_sq23_session_starts_with_unranked_options(client: TestClient) -> None:
    payload = create_scenario(client)
    assert payload["phase"] == "awaiting_pilot_reasoning"
    assert payload["question"]["key"] == "decision.initial"
    assert [item["id"] for item in payload["options"]] == ["CYQX", "EINN"]
    assert all(item["state"] == "conditional" for item in payload["options"])


def test_scenario_mutation_is_blocked(client: TestClient) -> None:
    response = client.post(
        "/api/sessions",
        json={
            "mode": "flight_scenario",
            "case_id": "SQ23-25JUL26-OEI-ETP1-1D",
            "scenario": "Engine fire and smoke at ETP1-1D.",
        },
    )
    assert response.status_code == 422
    assert "fixed as stable OEI" in response.json()["detail"]


def test_first_answer_moves_to_picture_now(client: TestClient) -> None:
    payload = create_scenario(client)
    session_id = payload["session"]["id"]
    response = client.post(
        f"/api/sessions/{session_id}/answer",
        json={
            "question_key": "decision.initial",
            "values": {
                "selected_option": "CYQX",
                "rationale": "It is the shorter Flight Briefing candidate, subject to suitability.",
            },
        },
    )
    assert response.status_code == 200
    next_payload = response.json()
    assert next_payload["question"]["key"] == "endsley.picture_now"


def test_complete_guided_flow_generates_teaching_and_memory(client: TestClient) -> None:
    payload = create_scenario(client)
    session_id = payload["session"]["id"]
    answers = [
        ("decision.initial", {"selected_option": "CYQX", "rationale": "Shorter candidate, subject to suitability."}),
        ("endsley.picture_now", {"confirmed_facts": "Stable OEI at ETP1-1D.\nCYQX and EINN are the CFP pair.", "assumptions": "Landing performance is suitable under the golden-test assumption."}),
        ("endsley.meaning", {"answer": "Distance alone is insufficient; the airport must remain suitable."}),
        ("endsley.projection", {"answer": "Weather, fuel and approach availability may change before arrival."}),
        ("endsley.widen_scan", {"answer": "A runway, weather or aircraft-condition change could invalidate CYQX."}),
        ("endsley.decision_gate", {"decision_gate": "Change to EINN if CYQX weather, runway, approach or landing performance becomes unsuitable.", "fallback": "EINN"}),
        ("rasmussen.capability", {"degraded_capabilities": "One-engine climb and operational flexibility are reduced.", "retained_capabilities": "The aircraft remains controllable and can divert."}),
        ("rasmussen.constraints", {"answer": "Protect terrain clearance, fuel margin and approved landing suitability."}),
        ("rasmussen.objective", {"operational_objective": "Reach the nearest suitable landing aerodrome while retaining a fallback."}),
        ("rasmussen.action_feedback", {"implementation": "Maintain flight path and complete the approved OEI procedure.", "monitoring": "Monitor aircraft condition, weather, fuel, runway and approach status.", "crew_plan": "PF flies; PM obtains data and coordinates ATC and cabin."}),
    ]
    for key, values in answers:
        response = client.post(
            f"/api/sessions/{session_id}/answer",
            json={"question_key": key, "values": values},
        )
        assert response.status_code == 200, response.text
    final = response.json()
    assert final["phase"] == "ready_to_teach"
    assert final["teaching_plan"]["status"] == "conditional"
    assert "nearest suitable aerodrome" in final["teaching_plan"]["answer"]
    assert final["memory"]
    assert final["memory"][0]["raw_pilot_wording"] != final["memory"][0]["ai_interpretation"]


def test_teach_helpyou_keeps_contribution_non_authoritative(client: TestClient) -> None:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "teach_helpyou",
            "scenario": "Share a line-experience observation.",
        },
    ).json()
    session_id = created["session"]["id"]
    response = client.post(
        f"/api/sessions/{session_id}/teach",
        json={
            "record_type": "pilot_experience",
            "raw_pilot_wording": "At this airport, earlier configuration reduced our workload in strong tailwind.",
            "context": "A350, visual approach, direct personal experience.",
            "privacy_scope": "private",
        },
    )
    assert response.status_code == 200
    memory = response.json()["memory"][0]
    assert memory["evidence_status"] == "pilot_reported"
    assert "not operational authority" in memory["ai_interpretation"]


def test_export_contains_transcript_and_memory(client: TestClient) -> None:
    created = create_scenario(client)
    session_id = created["session"]["id"]
    response = client.get(f"/api/sessions/{session_id}/export")
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert payload["schema"] == "PilotDriven-Helpyou-Testbed-Session-v0.1"
    assert payload["messages"]
