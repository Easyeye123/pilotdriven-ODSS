from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
from pypdf import PdfReader

import app.database as database
from app.odss.finding_ids import assign_finding_ids
from app.odss.level3 import (
    PILOT_DECISION_STATEMENT,
    _render_level3_pdf,
    build_level3_artifact,
)
from app.odss.policy_index import policy_snapshot_from_env


def _analysis() -> dict:
    findings = [{
        "rule_id": "PERFORMANCE-AUTO",
        "engine": "performance",
        "severity": "warning",
        "title": "Structural margin requires review",
        "summary": "Planned mass is at a structural limit.",
        "details": ["This Level 2 detail must not be copied into Level 3."],
        "data": {"phase": "departure"},
    }]
    assign_finding_ids(findings)
    return {
        "schema_version": "0.6.1",
        "flight": {
            "flight_number": "SQ999",
            "flight_date": "25JUL26",
            "departure": "WSSS",
            "destination": "KJFK",
            "aircraft_type": "A359",
            "registration": "9V-SMA",
        },
        "findings": findings,
        "view": {"timing": {"events": []}},
        "level3_inputs": {
            "weather_coverage": {
                "status": "complete",
                "source": "synthetic-regression-only",
            }
        },
    }


def _snapshot() -> dict:
    return {
        "schema_version": "1.1",
        "tenant_id": "tenant-a",
        "state": "ready",
        "reason": None,
        "source_path": "/private/policy/tenant-a.json",
        "source_sha256": "f" * 64,
        "documents": [{
            "document_id": "om-a",
            "title": "Synthetic Test Operations Manual",
            "document_type": "operations_manual",
            "revision": "Revision 7",
            "effective_date": "2026-07-01",
            "source_sha256": "a" * 64,
            "status": "approved",
            "current": True,
            "approved_by": "policy-owner",
            "approved_at_utc": "2026-07-02T00:00:00+00:00",
        }],
        "clauses": [{
            "clause_id": "om-a-weight-1",
            "document_id": "om-a",
            "section": "4.2 Weight limits",
            "page": "42",
            "exact_support": "Use the current approved structural limit for the aircraft.",
            "applicability_reason": "The deterministic finding concerns departure performance.",
            "decision_frame": "Review the available margin and applicable operating context.",
            "applicable_options": ["Continue review", "Request dispatch review"],
            "facets": {
                "engines": ["performance"],
                "rule_ids": [],
                "severities": [],
                "phases": ["departure"],
                "airports": [],
                "aircraft_types": [],
                "registrations": [],
            },
            "ambiguity_question": {
                "prompt": "Which approved dispatch review state applies?",
                "options": ["Confirmed", "Not confirmed"],
            },
        }],
    }


def test_level3_joins_finding_ids_to_provenance_and_calculates_only_mounted_margin() -> None:
    analysis = _analysis()
    finding_id = analysis["findings"][0]["finding_id"]
    analysis["level3_inputs"] = {
        "weather_coverage": {
            "status": "complete",
            "source": "synthetic-regression-only",
        },
        "margins": [{
            "margin_id": "structural-weight",
            "label": "Structural weight margin",
            "actual": 280_000,
            "limit": 280_000,
            "unit": "kg",
            "direction": "maximum",
            "source_clause_id": "om-a-weight-1",
            "finding_ids": [finding_id],
        }]
    }

    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot=_snapshot(),
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
        generated_at_utc="2026-07-25T00:00:00+00:00",
    )

    assert artifact["status"] == "COMPLETE"
    assert artifact["decision_authority"] == "pilot"
    assert artifact["generation"]["llm_operational_verdict"] is False
    assert artifact["policy_digest"][0] == {
        "finding_id": finding_id,
        "finding_title": "Structural margin requires review",
        "clause_id": "om-a-weight-1",
        "document_id": "om-a",
        "document_title": "Synthetic Test Operations Manual",
        "document_type": "operations_manual",
        "revision": "Revision 7",
        "effective_date": "2026-07-01",
        "section": "4.2 Weight limits",
        "page": "42",
        "exact_support": "Use the current approved structural limit for the aircraft.",
        "applicability_reason": "The deterministic finding concerns departure performance.",
        "decision_frame": "Review the available margin and applicable operating context.",
        "source_sha256": "a" * 64,
    }
    assert artifact["margins"][0]["margin"] == 0
    assert artifact["margins"][0]["source_clause_id"] == "om-a-weight-1"
    assert artifact["margins"][0]["source"] == {
        "document_title": "Synthetic Test Operations Manual",
        "revision": "Revision 7",
        "effective_date": "2026-07-01",
        "section": "4.2 Weight limits",
        "page": "42",
        "source_sha256": "a" * 64,
    }
    assert artifact["threat_cards"][0]["pilot_decision_statement"] == PILOT_DECISION_STATEMENT
    assert "This Level 2 detail" not in json.dumps(artifact)
    assert artifact["pilot_questions"][0]["state"] == "OPEN"


def test_level3_fails_closed_when_approved_sources_are_unavailable() -> None:
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=_analysis(),
        snapshot={
            "schema_version": "1.1",
            "tenant_id": "tenant-a",
            "state": "unavailable",
            "reason": "No approved operator policy index is mounted.",
            "source_sha256": None,
            "documents": [],
            "clauses": [],
        },
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
    )

    assert artifact["status"] == "PARTIAL"
    assert artifact["policy_digest"] == []
    assert artifact["margins"] == []
    assert artifact["threat_cards"] == []
    assert artifact["pilot_questions"] == []
    assert artifact["decision_summary"]["open_decision_count"] == 0
    assert artifact["decision_summary"]["presentation_mode"] == "compact-partial-ledger"
    assert artifact["audit_trace"]["actionable_finding_count"] == 1
    assert len(artifact["audit_trace"]["uncovered_finding_ids"]) == 1
    assert any(
        item["key"] == "approved-policy-library"
        and item["status"] == "review_required"
        for item in artifact["completeness_ledger"]
    )


def test_level3_fails_closed_when_weather_coverage_is_disabled() -> None:
    analysis = _analysis()
    analysis["level3_inputs"].pop("weather_coverage")
    analysis["flight"]["vaa_review"] = {
        "status": "not_assessed",
        "coverage_status": "disabled",
        "reason_codes": ["source_disabled"],
    }
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot=_snapshot(),
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
    )

    weather = next(
        item
        for item in artifact["completeness_ledger"]
        if item["key"] == "weather-coverage"
    )
    assert artifact["status"] == "PARTIAL"
    assert weather["status"] == "review_required"
    assert "has not been confirmed" in weather["reason"]
    assert "coverage is disabled" in weather["reason"]


def test_level3_timeline_uses_deterministic_calculated_utc() -> None:
    analysis = _analysis()
    finding_id = analysis["findings"][0]["finding_id"]
    analysis["level3_inputs"]["timeline_points"] = [{
        "label": "Destination crossing",
        "actm_minutes": 1054,
        "utc_iso": "2026-07-25T21:54:00+00:00",
        "utc_display": "25 JUL 2154Z",
        "finding_ids": [finding_id],
    }]
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot=_snapshot(),
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
    )

    assert artifact["timeline_points"] == [{
        "label": "Destination crossing",
        "utc": "2026-07-25T21:54:00+00:00",
        "actm_minutes": 1054,
        "source": "deterministic-odss-timing",
        "finding_ids": [finding_id],
    }]


def test_level3_pdf_escapes_controlled_source_markup(tmp_path: Path) -> None:
    analysis = _analysis()
    analysis["findings"][0]["title"] = "Performance <review> & confirmation"
    snapshot = _snapshot()
    snapshot["documents"][0]["title"] = "Manual <R&D>"
    snapshot["clauses"][0]["exact_support"] = "Limit A < B & verify current revision."
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot=snapshot,
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
    )
    destination = tmp_path / "level3.pdf"

    _render_level3_pdf(artifact, destination)

    assert destination.read_bytes().startswith(b"%PDF-")
    assert destination.stat().st_size > 1_000


def test_level3_compact_partial_pdf_does_not_repeat_uncovered_findings(
    tmp_path: Path,
) -> None:
    analysis = _analysis()
    analysis["findings"] = [{
        "rule_id": f"WEATHER-{index + 1}",
        "engine": "weather",
        "severity": "warning",
        "title": f"Internal Level 2 weather record {index + 1}",
        "summary": f"RAW WEATHER RECORD {index + 1} must not be repeated.",
        "data": {"phase": "enroute"},
    } for index in range(160)]
    analysis["flight"]["vaa_review"] = {
        "status": "review_required",
        "coverage_status": "global_current_active_sigmet",
        "reason_codes": [],
    }
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot={
            "schema_version": "1.1",
            "tenant_id": "tenant-a",
            "state": "unavailable",
            "reason": "No approved operator policy index is mounted.",
            "source_sha256": None,
            "documents": [],
            "clauses": [],
        },
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
    )
    destination = tmp_path / "level3-compact-partial.pdf"

    _render_level3_pdf(artifact, destination)

    pages = PdfReader(destination).pages
    text = "\n".join((page.extract_text() or "") for page in pages)
    assert len(pages) == 1
    assert artifact["threat_cards"] == []
    assert "160 of 160 pertinent" in text
    assert "RAW WEATHER RECORD" not in text
    assert "Internal Level 2 weather record" not in text
    assert "L2-" not in text
    assert "Trigger:" not in text
    assert "Decision point:" not in text
    assert "Decision summary" not in text
    assert "Open decisions" not in text
    assert "Internal trace identifiers" not in text
    assert "Pertinent review item" in text
    assert "Pilot review required" in text
    assert "Review gates" in text
    assert f"{sum(item['status'] != 'complete' for item in artifact['completeness_ledger'])}" in text
    assert "normalized-flight-input" not in text
    assert "approved-policy-library" not in text
    assert "finding-policy-coverage" not in text
    assert "global_current_active_sigmet" not in text
    assert "current global active SIGMET feed" in text


def test_level3_policy_backed_pdf_keeps_trace_ids_in_audit_only(
    tmp_path: Path,
) -> None:
    analysis = _analysis()
    analysis["findings"].append({
        "rule_id": "NOTAM-UNMATCHED",
        "engine": "notam",
        "severity": "warning",
        "title": "Unmatched runway closure raw record",
        "summary": "RAW NOTAM TEXT MUST REMAIN IN LEVEL 2.",
        "data": {"phase": "arrival", "airport": "KJFK"},
    })
    artifact = build_level3_artifact(
        analysis_id="analysis-a",
        analysis=analysis,
        snapshot=_snapshot(),
        snapshot_id="snapshot-a",
        snapshot_sha256="b" * 64,
        generated_at_utc="2026-07-25T00:00:00+00:00",
    )
    destination = tmp_path / "level3-policy-backed.pdf"

    _render_level3_pdf(artifact, destination)

    text = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(destination).pages
    )
    all_internal_ids = {
        item["finding_id"]
        for item in analysis["findings"]
    }
    assert artifact["decision_summary"]["presentation_mode"] == "policy-backed"
    assert len(artifact["threat_cards"]) == 1
    assert len(artifact["audit_trace"]["uncovered_finding_ids"]) == 1
    assert "Synthetic Test Operations Manual" in text
    assert "Revision 7" in text
    assert "effective 2026-07-01" in text
    assert "4.2 Weight limits" in text
    assert "p.42" in text
    assert "Use the current approved structural limit" in text
    assert "Pilot retains final authority." in text
    assert "Decision summary" not in text
    assert "Decision point:" not in text
    assert "Trigger:" not in text
    assert "RAW NOTAM TEXT" not in text
    assert "This Level 2 detail" not in text
    assert "om-a-weight-1" not in text
    assert "L2-" not in text
    assert not (all_internal_ids & set(text.split()))


def test_policy_mount_accepts_only_current_approved_tenant_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tenant-a.json"
    payload = {
        "schema_version": "1.1",
        "tenant_id": "tenant-a",
        "generated_at_utc": "2026-07-24T00:00:00Z",
        "documents": [
            {
                "document_id": "current",
                "title": "Current manual",
                "document_type": "operations_manual",
                "revision": "R1",
                "effective_date": "2026-07-01",
                "source_sha256": "a" * 64,
                "status": "approved",
                "current": True,
                "approved_by": "owner",
                "approved_at_utc": "2026-07-02T00:00:00Z",
            },
            {
                "document_id": "future",
                "title": "Future manual",
                "document_type": "operations_manual",
                "revision": "R2",
                "effective_date": "2026-08-01",
                "source_sha256": "b" * 64,
                "status": "approved",
                "current": True,
                "approved_by": "owner",
                "approved_at_utc": "2026-07-02T00:00:00Z",
            },
        ],
        "clauses": [{
            "clause_id": "current-c1",
            "document_id": "current",
            "section": "1",
            "page": "1",
            "exact_support": "Current support.",
            "applicability_reason": "Current finding.",
            "decision_frame": "Review current context.",
            "facets": {"engines": ["performance"]},
        }, {
            "clause_id": "future-c1",
            "document_id": "future",
            "section": "1",
            "page": "1",
            "exact_support": "Future support.",
            "applicability_reason": "Future finding.",
            "decision_frame": "Review future context.",
            "facets": {"engines": ["performance"]},
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ODSS_LEVEL3_POLICY_INDEX_PATH", str(path))

    snapshot = policy_snapshot_from_env(
        tenant_id="tenant-a",
        flight_date="25JUL26",
    )
    wrong_tenant = policy_snapshot_from_env(
        tenant_id="tenant-b",
        flight_date="25JUL26",
    )

    assert snapshot["state"] == "ready"
    assert [item["document_id"] for item in snapshot["documents"]] == ["current"]
    assert [item["clause_id"] for item in snapshot["clauses"]] == ["current-c1"]
    assert wrong_tenant["state"] == "invalid"
    assert wrong_tenant["documents"] == []


def test_policy_snapshot_and_audit_records_are_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "odss.db")
    database.init_db()
    database.create_flight({
        "source_filename": "test.pdf",
        "source_path": str(tmp_path / "test.pdf"),
        "tenant_id": "tenant-a",
        "user_id": "pilot-a",
        "analysis_id": "analysis-a",
    })
    first = database.get_or_create_policy_snapshot(
        tenant_id="tenant-a",
        analysis_id="analysis-a",
        snapshot={"state": "unavailable", "documents": [], "clauses": []},
    )
    second = database.get_or_create_policy_snapshot(
        tenant_id="tenant-a",
        analysis_id="analysis-a",
        snapshot={"state": "ready", "documents": [{"unexpected": True}], "clauses": []},
    )
    event_id = database.record_audit_event(
        tenant_id="tenant-a",
        actor_id="pilot-a",
        action="test.created",
        resource_type="analysis",
        resource_id="analysis-a",
        details={"safe": True},
    )

    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE policy_snapshots SET snapshot_json='{}' WHERE id=?",
                (first["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM audit_events WHERE id=?",
                (event_id,),
            )
