from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odss_surface.api import create_app
from odss_surface.contract import build_surface_contract
from odss_surface.notam import parse_notam_fields, parse_surface_clauses
from odss_surface.osm import SurfaceGraph, load_snapshot
from odss_surface.resolver import resolve_surface_notam

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic_wsss_surface_snapshot.json"


@pytest.fixture()
def graph() -> SurfaceGraph:
    return SurfaceGraph(load_snapshot(FIXTURE))


def test_parse_two_numbered_closures():
    raw = json.loads((ROOT / "fixtures" / "wsss_regression_notams.json").read_text())[0]["raw"]
    fields = parse_notam_fields(raw)
    clauses = parse_surface_clauses(fields)
    assert [item.target_ref for item in clauses] == ["R7", "R5"]
    assert clauses[0].start_ref == "R"
    assert clauses[0].end_ref == "R4"
    assert set(clauses[0].include_junction_refs) >= {"R7", "R5"}


def test_resolve_intersection_ranges(graph: SurfaceGraph):
    case = json.loads((ROOT / "fixtures" / "wsss_regression_notams.json").read_text())[0]
    findings = resolve_surface_notam(
        graph,
        case["raw"],
        briefing_time_utc=case["briefing_time_utc"],
    )
    assert len(findings) == 2
    assert all(item.mapped for item in findings)
    assert all(item.applicability == "active" for item in findings)
    assert findings[0].confidence == "high"
    assert findings[0].line_coordinates[0] == pytest.approx((103.995, 1.350))
    assert findings[0].line_coordinates[-1] == pytest.approx((103.995, 1.354))
    assert findings[0].junction_coordinates
    assert findings[1].line_coordinates[0] == pytest.approx((103.995, 1.352))
    assert findings[1].line_coordinates[-1] == pytest.approx((104.003, 1.352))


def test_resolve_whole_surface(graph: SurfaceGraph):
    raw = "A1000/26 NOTAMN A) WSSS B) 2607211200 C) 2607211800 E) TWY P7 CLSD"
    findings = resolve_surface_notam(graph, raw, briefing_time_utc="2026-07-21T14:00:00Z")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.mapped
    assert finding.confidence == "high"
    assert finding.source_osm_ids == [1011]
    assert finding.x_coordinates


def test_resolve_behind_single_stand_is_medium_confidence(graph: SurfaceGraph):
    raw = "A1001/26 NOTAMN A) WSSS B) 2607211200 C) 2607211800 E) TXL P7 BEHIND ACFT STAND D49 CLSD"
    findings = resolve_surface_notam(graph, raw, briefing_time_utc="2026-07-21T14:00:00Z")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.mapped
    assert finding.confidence in {"medium", "low"}
    assert finding.match_method == "stand_projection_to_surface_ref"
    assert finding.x_coordinates


def test_aircraft_code_restriction(graph: SurfaceGraph):
    raw = "A1002/26 NOTAMN A) WSSS B) 2607211200 C) 2607211800 E) TWY R7 NOT AVBL FOR ACFT CODE F"
    f_code_f = resolve_surface_notam(
        graph, raw, briefing_time_utc="2026-07-21T14:00:00Z", selected_aircraft_code="F"
    )[0]
    f_code_e = resolve_surface_notam(
        graph, raw, briefing_time_utc="2026-07-21T14:00:00Z", selected_aircraft_code="E"
    )[0]
    assert f_code_f.affects_selected_aircraft is True
    assert f_code_e.affects_selected_aircraft is False
    contract = build_surface_contract(graph, [f_code_e], briefing_time_utc="2026-07-21T14:00:00Z")
    assert contract["notam_overlays_geojson"]["features"][0]["properties"]["display"] is False


def test_inactive_notam_is_preserved_but_not_displayed(graph: SurfaceGraph):
    raw = "A1003/26 NOTAMN A) WSSS B) 2607211200 C) 2607211300 E) TWY P7 CLSD"
    finding = resolve_surface_notam(graph, raw, briefing_time_utc="2026-07-21T14:00:00Z")[0]
    assert finding.applicability == "inactive"
    contract = build_surface_contract(graph, [finding], briefing_time_utc="2026-07-21T14:00:00Z")
    assert all(feature["properties"]["display"] is False for feature in contract["notam_overlays_geojson"]["features"])


def test_unknown_ref_is_not_mapped(graph: SurfaceGraph):
    raw = "A1004/26 NOTAMN A) WSSS B) 2607211200 C) 2607211800 E) TWY ZZ9 CLSD"
    finding = resolve_surface_notam(graph, raw, briefing_time_utc="2026-07-21T14:00:00Z")[0]
    assert not finding.mapped
    assert finding.confidence == "unmapped"


def test_contract_attribution_and_safety_boundary(graph: SurfaceGraph):
    contract = build_surface_contract(graph, [], briefing_time_utc="2026-07-21T14:00:00Z")
    assert contract["not_for_navigation"] is True
    assert "OpenStreetMap" not in contract["geometry_source"]["attribution"] or contract["geometry_source"]["provider"] == "synthetic-test-fixture"
    assert contract["surface_geojson"]["type"] == "FeatureCollection"
    assert contract["geometry_source"]["airport_review_state"] == "proof-of-concept-unreviewed"


def test_api_returns_contract(monkeypatch):
    monkeypatch.setenv("ODSS_WSSS_SURFACE_SNAPSHOT", str(FIXTURE))
    client = TestClient(create_app())
    response = client.post(
        "/v1/airports/WSSS/surface-resolve",
        json={
            "notam_text": "A1005/26 NOTAMN A) WSSS B) 2607211200 C) 2607211800 E) TWY P7 CLSD",
            "briefing_time_utc": "2026-07-21T14:00:00Z",
            "aircraft_code": "F",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["airport"] == "WSSS"
    assert payload["findings"][0]["mapped"] is True
    assert any(feature["properties"]["symbol"] == "closure-x" for feature in payload["notam_overlays_geojson"]["features"])
