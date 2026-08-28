from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
import threading
from types import SimpleNamespace

import fitz
from PIL import Image
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
import app.analysis as analysis_module
import app.main as main
import app.odss.surface_overlays as surface_overlays
import app.odss_map_v06.report_worker as report_worker
from app.odss_map_v06.config import MapSettings


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


def _build_lido_pdf_with_sq481_deferred_block() -> bytes:
    pages = [
        """SUMMARY CFP
9V-SMG SIA304 SIN/BRU ETD 1030 11JUL26
SCHED DEP 1030 UTC SCHED ARR 2200 UTC
AA SEAT 21A TRAY TABLE UNABLE TO STOW
   X CLASS B
   ECDL007905
BB SEAT 21A TRAY TABLE UNABLE TO STOW
   X CLASS B
PLAN 12/0/1
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
            page.insert_textbox(
                (36, 36, 560, 806),
                text,
                fontname="courier",
                fontsize=9,
            )
        return document.tobytes()
    finally:
        document.close()


def _build_lido_pdf_with_notam_windows() -> bytes:
    document = fitz.open(stream=_build_lido_pdf(), filetype="pdf")
    try:
        page = document.new_page()
        page.insert_textbox(
            (36, 36, 560, 806),
            """NOTAM
WSSS/SIN SINGAPORE CHANGI
------------------------
+RUNWAY+
ACTIVE1/26 VALID: 11-JUL-26 0900 - 11-JUL-26 1200
DAILY 1000-1100
RWY 02L CLSD
EXPIRED1/26 VALID: 11-JUL-26 0800 - 11-JUL-26 0929
RWY 02C CLSD
FUTURE1/26 VALID: 11-JUL-26 1131 - 11-JUL-26 1300
RWY 20R CLSD
OFFSCH1/26 VALID: 11-JUL-26 0900 - 11-JUL-26 1200
DAILY 1300-1400
RWY 20C CLSD
BADC1/26 VALID: 32-JUL-26 1000 - 11-ABC-26 1200
RWY 02R CLSD
BADD1/26 VALID: 11-JUL-26 0900 - 11-JUL-26 1200
MON-FRI EXC HOL 1000-1100
RWY 20L CLSD
""",
            fontname="courier",
            fontsize=9,
        )
        return document.tobytes()
    finally:
        document.close()


@pytest.fixture
def service_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
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


def _authorization(
    tenant_id: str = "tenant-1",
    user_id: str = "pilot-7",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer service-test-token",
        "X-PilotDriven-Tenant-Id": tenant_id,
        "X-PilotDriven-User-Id": user_id,
    }


def test_report_refresh_migration_backfills_once_without_promoting_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "legacy-odss.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE flights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_number TEXT,
                flight_date TEXT,
                departure TEXT,
                destination TEXT,
                aircraft TEXT,
                registration TEXT,
                source_filename TEXT NOT NULL,
                source_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Uploaded',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                analysis_path TEXT,
                level1_report TEXT,
                level2_report TEXT,
                level3_json TEXT,
                level3_report TEXT,
                notes TEXT,
                last_error TEXT,
                actual_takeoff_utc TEXT,
                timing_reference_type TEXT,
                timing_reference_waypoint TEXT,
                timing_reference_utc TEXT,
                analysis_id TEXT UNIQUE,
                tenant_id TEXT,
                user_id TEXT,
                workspace_id TEXT,
                external_flight_id TEXT,
                analysis_version TEXT,
                service_request_id TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO flights (
                source_filename, source_path, status,
                level1_report, level2_report
            ) VALUES (?, ?, 'Completed', ?, ?)
            """,
            (
                ("current.pdf", "/tmp/current.pdf", "/tmp/l1.pdf", "/tmp/l2.pdf"),
                ("pending.pdf", "/tmp/pending.pdf", "/tmp/l1-only.pdf", None),
            ),
        )

    database.init_db()
    with database.connect() as connection:
        migrated = connection.execute(
            "SELECT id, report_refresh_state FROM flights ORDER BY id"
        ).fetchall()
        assert [row["report_refresh_state"] for row in migrated] == [
            "current",
            "pending",
        ]
        connection.execute(
            "UPDATE flights SET report_refresh_state='failed' WHERE id=?",
            (migrated[0]["id"],),
        )

    database.init_db()
    with database.connect() as connection:
        preserved = connection.execute(
            "SELECT report_refresh_state FROM flights ORDER BY id"
        ).fetchall()
    assert [row["report_refresh_state"] for row in preserved] == [
        "failed",
        "pending",
    ]


def _surface_contract(
    icao: str,
    role: str,
) -> dict:
    return {
        "schemaVersion": "1.0",
        "icao": icao,
        "name": f"{icao} test airport",
        "role": role,
        "window": {
            "startsAt": "2026-07-11T08:30:00Z",
            "endsAt": "2026-07-11T12:30:00Z",
            "basis": (
                "scheduled_departure"
                if role == "departure"
                else "scheduled_arrival"
            ),
        },
        "source": {
            "provider": "openstreetmap",
            "fetchedAt": "2026-07-11T08:00:00Z",
            "sourceUpdatedAt": "2026-07-10T00:00:00Z",
            "attribution": "© OpenStreetMap contributors",
            "licenceUrl": "https://www.openstreetmap.org/copyright",
            "referenceOnly": True,
        },
        "bounds": {
            "west": 103.98,
            "south": 1.33,
            "east": 104.01,
            "north": 1.37,
        },
        "featureCollection": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "way/runway",
                    "properties": {
                        "featureId": "way/runway",
                        "aeroway": "runway",
                        "ref": "02L/20R",
                        "name": None,
                        "source": "openstreetmap",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[103.985, 1.34], [104.0, 1.36]],
                    },
                },
                {
                    "type": "Feature",
                    "id": "way/taxiway",
                    "properties": {
                        "featureId": "way/taxiway",
                        "aeroway": "taxiway",
                        "ref": "S2",
                        "name": None,
                        "source": "openstreetmap",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[103.99, 1.345], [103.995, 1.35]],
                    },
                },
            ],
        },
        "mapped": [
            {
                "notamNumber": "A9002/26",
                "entityType": "taxiway",
                "entityRef": "S2",
                "scope": "whole_entity",
                "featureIds": ["way/taxiway"],
                "plainEnglish": "Taxiway S2 closed.",
                "evidence": "TWY S2 CLSD",
                "markClass": "closure",
                "stateAtReference": "active_at_reference",
                "referenceAt": "2026-07-11T09:30:00Z",
                "referenceInterval": {
                    "startsAt": "2026-07-11T08:30:00Z",
                    "endsAt": "2026-07-11T12:30:00Z",
                },
                "markers": [],
            }
        ],
        "reviewRequired": [],
        "counts": {
            "mapped": 1,
            "reviewRequired": 0,
            "runways": 1,
        },
    }


def test_service_api_requires_bearer_token(service_app: TestClient) -> None:
    anonymous = service_app.get("/v1/health")
    authorized = service_app.get("/v1/health", headers=_authorization())

    assert anonymous.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["version"] == "0.6.1"
    assert authorized.json()["map_contract"] == "1.1"

    missing_identity = service_app.get(
        "/v1/analyses/unknown",
        headers={"Authorization": "Bearer service-test-token"},
    )
    assert missing_identity.status_code == 400
    legacy_dashboard = service_app.get(
        "/",
        headers={"Authorization": "Basic ZGVtbzpkZW1v"},
    )
    assert legacy_dashboard.status_code == 404


def test_service_rejects_tenant_not_matching_loaded_profile_library(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "DEPRESS_LIBRARY_METADATA",
        {
            "status": "controlled-index-loaded",
            "tenant_id": "tenant-owner",
        },
    )

    accepted = service_app.get(
        "/v1/analyses/unknown",
        headers=_authorization("tenant-owner", "pilot-owner"),
    )
    rejected = service_app.get(
        "/v1/analyses/unknown",
        headers=_authorization("tenant-other", "pilot-other"),
    )

    assert accepted.status_code == 404
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == (
        "The controlled profile library is not configured for this tenant."
    )



def test_playwright_static_assets_accept_service_bearer_with_legacy_basic_auth(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_USERNAME", "legacy-user")
    monkeypatch.setenv("ODSS_PASSWORD", "legacy-password")

    anonymous = service_app.get("/static/odss-maplibre-v06.css")
    service = service_app.get(
        "/static/odss-maplibre-v06.css",
        headers=_authorization(),
    )
    geometry = service_app.get(
        "/static/odss-map-geometry-v06.js",
        headers=_authorization(),
    )
    maplibre = service_app.get(
        "/static/vendor/maplibre-gl-5.6.0/maplibre-gl.js",
        headers=_authorization(),
    )

    assert anonymous.status_code == 404
    assert service.status_code == 200
    assert service.headers["content-type"].startswith("text/css")
    assert geometry.status_code == 200
    assert geometry.headers["content-type"].startswith("text/javascript")
    assert maplibre.status_code == 200
    assert maplibre.headers["content-type"].startswith("text/javascript")


def test_print_map_template_uses_local_runtime_and_full_height_root() -> None:
    template = (main.TEMPLATE_DIR / "map_print_v06.html").read_text(encoding="utf-8")
    stylesheet = (main.STATIC_DIR / "odss-maplibre-v06.css").read_text(encoding="utf-8")
    runtime = (main.STATIC_DIR / "odss-maplibre-v06.js").read_text(encoding="utf-8")

    assert 'class="odss-print-map-root"' in template
    assert "/static/vendor/maplibre-gl-5.6.0/maplibre-gl.js" in template
    assert "/static/odss-map-geometry-v06.js" in template
    assert '"readinessTimeoutMs": map_readiness_timeout_ms' in template
    assert "unpkg.com" not in template
    assert ".odss-print-map-root," in stylesheet
    assert "height: 100%;" in stylesheet
    assert "map.areTilesLoaded()" in runtime
    assert "Map readiness timeout (layers=" in runtime
    assert "window.__ODSS_MAP_INSTANCE__ = map" in runtime
    assert "window.__ODSS_MAP_LAYERS_READY_AT__ = Date.now()" in runtime

def test_service_analysis_exposes_stable_contract_and_explicit_fallback(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers={
            **_authorization(),
            "X-PilotDriven-Tenant-Id": "tenant-1",
            "X-PilotDriven-User-Id": "pilot-7",
            "X-PilotDriven-Workspace-Id": "workspace-3",
            "X-PilotDriven-Flight-Id": "flight-external-304",
        },
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert created.status_code == 201
    payload = created.json()
    analysis_id = payload["analysis_id"]
    assert payload["status"] == "Completed"
    assert payload["context"] == {
        "tenant_id": "tenant-1",
        "user_id": "pilot-7",
        "workspace_id": "workspace-3",
        "external_flight_id": "flight-external-304",
    }
    contract = service_app.get(
        f"/v1/analyses/{analysis_id}/map-contract",
        headers=_authorization(),
    )
    route = service_app.get(
        f"/v1/analyses/{analysis_id}/route.geojson",
        headers=_authorization(),
    )
    markers = service_app.get(
        f"/v1/analyses/{analysis_id}/markers.geojson",
        headers=_authorization(),
    )
    hazards = service_app.get(
        f"/v1/analyses/{analysis_id}/hazards.geojson",
        headers=_authorization(),
    )
    config = service_app.get(
        f"/v1/analyses/{analysis_id}/map-config",
        headers=_authorization(),
    )
    fallback = service_app.get(
        f"/v1/analyses/{analysis_id}/map-fallback",
        headers=_authorization(),
    )

    assert contract.status_code == route.status_code == markers.status_code == hazards.status_code == 200
    contract_payload = contract.json()
    assert contract_payload["schema_version"] == "1.1"
    assert contract_payload["hazards_geojson"] == {"type": "FeatureCollection", "features": []}
    assert len(contract_payload["route_hash"]) == 64
    assert route.json() == contract_payload["route_geojson"]
    assert markers.json() == contract_payload["markers_geojson"]
    assert hazards.json() == contract_payload["hazards_geojson"]
    assert config.json()["route_hash"] == contract_payload["route_hash"]
    assert config.json()["fallback_url"].endswith("/map-fallback")
    assert fallback.status_code == 200
    assert fallback.headers["x-odss-map-mode"] == "schematic-fallback"
    assert fallback.headers["x-odss-route-hash"] == contract_payload["route_hash"]
    assert fallback.headers["content-type"].startswith("image/svg+xml")
    assert b"Schematic route display" in fallback.content

    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()
    assert briefing["schema_version"] == "0.6.1"
    assert briefing["flight"]["flight_number"] == "SQ304"
    assert briefing["flight"]["edto"]["assessment"]["status"] == "review_required"
    assert briefing["briefing"]["edto"]["assessment"]["evidence"][-1][
        "reason_code"
    ] == "explicit_edto_assessment_missing"

    level3 = service_app.get(
        f"/v1/analyses/{analysis_id}/level-3",
        headers=_authorization(),
    )
    level3_report = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-3",
        headers=_authorization(),
    )
    assert level3.status_code == 200
    assert level3.json()["status"] == "PARTIAL"
    assert level3.json()["decision_authority"] == "pilot"
    assert level3.json()["generation"]["llm_operational_verdict"] is False
    assert level3.json()["policy_digest"] == []
    assert any(
        item["key"] == "approved-policy-library"
        and item["status"] == "review_required"
        for item in level3.json()["completeness_ledger"]
    )
    assert level3_report.status_code == 200
    assert level3_report.content.startswith(b"%PDF")


def test_service_briefing_exposes_only_flight_evaluated_notam_findings(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={
            "file": (
                "SQ304-notam-windows.pdf",
                _build_lido_pdf_with_notam_windows(),
                "application/pdf",
            )
        },
    )

    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    response = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    )

    assert response.status_code == 200
    findings = {
        item["notam_id"]: item for item in response.json()["notam_findings"]
    }
    assert response.json()["notam_findings_summary"] == {
        "source_count": 3,
        "ranked_count": 3,
        "returned_count": 3,
        "omitted_count": 0,
        "duplicate_count": 0,
        "limit": main.SERVICE_NOTAM_FINDING_LIMIT,
    }
    assert set(findings) == {"ACTIVE1/26", "BADC1/26", "BADD1/26"}

    active = findings["ACTIVE1/26"]
    assert active == {
        "notam_id": "ACTIVE1/26",
        "location": "WSSS",
        "category": "RUNWAY",
        "text": "DAILY 1000-1100 RWY 02L CLSD",
        "summary": (
            "Rwy 02L closed or unavailable during the applicable departure "
            "window."
        ),
        "role": "departure",
        "applicability": "active",
        "validity_status": "overlaps_flight_window",
        "schedule_status": "overlaps_flight_window",
        "valid_from_utc": "2026-07-11T09:00:00+00:00",
        "valid_to_utc": "2026-07-11T12:00:00+00:00",
        "window_start_utc": "2026-07-11T09:30:00+00:00",
        "window_end_utc": "2026-07-11T11:30:00+00:00",
        "schedule": "DAILY 1000-1100",
        "state_at_reference": "active_at_reference",
        "reference_at": "2026-07-11T10:30:00+00:00",
        "source_page": 8,
    }

    malformed_validity = findings["BADC1/26"]
    assert malformed_validity["applicability"] == "review"
    assert malformed_validity["validity_status"] == "review_required"
    assert malformed_validity["schedule_status"] == "not_applicable"
    assert malformed_validity["state_at_reference"] == "unknown_at_reference"

    unsupported_schedule = findings["BADD1/26"]
    assert unsupported_schedule["applicability"] == "review"
    assert unsupported_schedule["validity_status"] == "overlaps_flight_window"
    assert unsupported_schedule["schedule_status"] == "review_required"
    assert unsupported_schedule["state_at_reference"] == "unknown_at_reference"

    # These records are valid source text, but ODSS evaluated them as outside
    # the active flight window or outside their item-D schedule. They must not
    # be promoted into the bounded service briefing.
    assert "EXPIRED1/26" not in findings
    assert "FUTURE1/26" not in findings
    assert "OFFSCH1/26" not in findings


def test_service_notam_boundary_ranks_before_bounding_and_discloses_omissions() -> None:
    def notam(index: int, *, active: bool = False) -> dict:
        return {
            "engine": "notam",
            "severity": "critical" if active else "information",
            "title": f"Synthetic finding {index}",
            "summary": f"Synthetic finding {index}",
            "data": {
                "notam_id": f"N{index:03d}/26",
                "location": "ZZZZ",
                "category": "TEST",
                "raw_text": f"Synthetic source text {index}",
                "role": "destination",
                "applicability": "active" if active else "review",
                "validity_status": "overlaps_flight_window",
                "schedule_status": "not_applicable",
                "pertinence_rank": 0 if active else 9,
                "priority_score": 999 if active else 0,
                "source_references": [{"pages": [1]}],
            },
        }

    source = [notam(index) for index in range(main.SERVICE_NOTAM_FINDING_LIMIT)]
    source.append(notam(main.SERVICE_NOTAM_FINDING_LIMIT, active=True))
    snapshot = main._service_notam_snapshot({"findings": source})

    assert len(snapshot["items"]) == main.SERVICE_NOTAM_FINDING_LIMIT
    assert snapshot["items"][0]["notam_id"] == (
        f"N{main.SERVICE_NOTAM_FINDING_LIMIT:03d}/26"
    )
    assert snapshot["summary"] == {
        "source_count": main.SERVICE_NOTAM_FINDING_LIMIT + 1,
        "ranked_count": main.SERVICE_NOTAM_FINDING_LIMIT + 1,
        "returned_count": main.SERVICE_NOTAM_FINDING_LIMIT,
        "omitted_count": 1,
        "duplicate_count": 0,
        "limit": main.SERVICE_NOTAM_FINDING_LIMIT,
    }


def test_service_analysis_request_id_is_idempotent(
    service_app: TestClient,
) -> None:
    headers = {
        **_authorization(),
        "X-PilotDriven-Tenant-Id": "tenant-1",
        "X-PilotDriven-Request-Id": "upload-request-304",
    }
    first = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    second = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304-copy.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["analysis_id"] == first.json()["analysis_id"]
    assert len(database.list_flights("tenant-1")) == 1


def test_failed_service_analysis_replay_returns_the_same_safe_422(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {
        **_authorization(),
        "X-PilotDriven-Request-Id": "unsupported-upload-request",
    }

    def fail_analysis(*args, **kwargs):
        raise analysis_module.CfpParseRejectedError(
            "Synthetic carrier-specific parser detail"
        )

    monkeypatch.setattr(main, "run_odss_analysis", fail_analysis)
    first = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("unsupported.pdf", _build_lido_pdf(), "application/pdf")},
    )
    second = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("unsupported-retry.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert first.status_code == 422
    assert second.status_code == 422
    assert first.json() == second.json()
    assert first.json()["detail"]["code"] == "CFP_FORMAT_UNSUPPORTED_OR_INVALID"
    assert first.json()["detail"]["message"] == (
        "This PDF could not be processed as a supported Lido CFP. "
        "Check the file and upload it again."
    )
    assert "Synthetic" not in str(first.json())
    summary = service_app.get(
        f"/v1/analyses/{first.json()['detail']['analysis_id']}",
        headers=_authorization(),
    )
    assert summary.status_code == 200
    assert "Synthetic" not in str(summary.json())
    assert summary.json()["warnings"] == [first.json()["detail"]["message"]]
    assert len(database.list_flights("tenant-1")) == 1


def test_transient_service_analysis_failure_retries_the_existing_request(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {
        **_authorization(),
        "X-PilotDriven-Request-Id": "transient-upload-request",
    }
    original_analysis = main.run_odss_analysis
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Synthetic report infrastructure outage")
        return original_analysis(*args, **kwargs)

    monkeypatch.setattr(main, "run_odss_analysis", fail_once)
    first = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "ANALYSIS_TEMPORARILY_UNAVAILABLE"
    assert "Synthetic" not in str(first.json())
    failed_summary = service_app.get(
        f"/v1/analyses/{first.json()['detail']['analysis_id']}",
        headers=_authorization(),
    )
    assert failed_summary.status_code == 200
    assert "Synthetic" not in str(failed_summary.json())
    assert failed_summary.json()["warnings"] == [
        first.json()["detail"]["message"]
    ]
    second = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304-retry.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert second.status_code == 200
    assert calls == 2
    assert len(database.list_flights("tenant-1")) == 1


def test_concurrent_failed_idempotency_retry_replays_completed_winner(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers={
            **_authorization(),
            "X-PilotDriven-Request-Id": "failed-retry-race",
        },
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    flight = database.get_flight_by_service_request(
        "tenant-1",
        "failed-retry-race",
    )
    assert flight is not None
    database.update_status(
        int(flight["id"]),
        "Failed",
        last_error="Synthetic retryable infrastructure failure",
        tenant_id="tenant-1",
        analysis_failure_category="infrastructure",
    )
    stale_failed = database.get_flight_for_tenant(
        int(flight["id"]),
        "tenant-1",
    )
    assert stale_failed is not None

    original_run = main.run_odss_analysis
    analysis_calls = 0
    analysis_lock = threading.Lock()

    def reject_stale_loser(*args, **kwargs):
        nonlocal analysis_calls
        with analysis_lock:
            analysis_calls += 1
            call_number = analysis_calls
        if call_number > 1:
            raise RuntimeError("Synthetic stale retry reran after completion")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(main, "run_odss_analysis", reject_stale_loser)
    original_claim = main.claim_analysis
    claim_lock = threading.Lock()
    claim_count = 0
    winner_completed = threading.Event()

    def order_retry_claims(*args, **kwargs):
        nonlocal claim_count
        with claim_lock:
            claim_count += 1
            claim_number = claim_count
        if claim_number == 2:
            assert winner_completed.wait(timeout=30)
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(main, "claim_analysis", order_retry_claims)
    original_update_status = main.update_status

    def observe_completion(flight_id, status, *args, **kwargs):
        result = original_update_status(flight_id, status, *args, **kwargs)
        if status == "Completed":
            winner_completed.set()
        return result

    monkeypatch.setattr(main, "update_status", observe_completion)

    def retry_stale_snapshot() -> int:
        try:
            response = asyncio.run(
                main._run_service_analysis_record(
                    stale_failed,
                    None,
                    success_status_code=200,
                )
            )
            return response.status_code
        except main.HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _index: retry_stale_snapshot(), range(2)))

    final = database.get_flight_for_tenant(int(flight["id"]), "tenant-1")
    assert statuses == [200, 200]
    assert analysis_calls == 1
    assert final is not None
    assert final["status"] == "Completed"
    assert final["analysis_failure_category"] is None


def test_concurrent_duplicate_request_id_never_returns_internal_error(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {
        **_authorization(),
        "X-PilotDriven-Request-Id": "concurrent-upload-request",
    }
    original_create = main.create_flight
    simultaneous_create = Barrier(2)

    def synchronized_create(data):
        simultaneous_create.wait(timeout=10)
        return original_create(data)

    monkeypatch.setattr(main, "create_flight", synchronized_create)

    def upload_copy(request: tuple[TestClient, int]):
        client, index = request
        return client.post(
            "/v1/analyses",
            headers=headers,
            files={
                "file": (
                    f"SQ304-concurrent-{index}.pdf",
                    _build_lido_pdf(),
                    "application/pdf",
                )
            },
        )

    with (
        TestClient(main.app, follow_redirects=False) as first_client,
        TestClient(main.app, follow_redirects=False) as second_client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        responses = list(
            executor.map(upload_copy, ((first_client, 1), (second_client, 2)))
        )

    assert all(response.status_code != 500 for response in responses)
    assert any(response.status_code in {200, 201} for response in responses)
    assert {response.status_code for response in responses} <= {200, 201, 409}
    assert len(database.list_flights("tenant-1")) == 1


def test_initial_report_render_failure_rolls_back_all_generated_artifacts(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_report_render(*args, **kwargs):
        raise ValueError("Synthetic report layout failure")

    monkeypatch.setattr(analysis_module, "render_pdf", fail_report_render)
    rejected = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert rejected.status_code == 503
    assert (
        rejected.json()["detail"]["code"]
        == "ANALYSIS_TEMPORARILY_UNAVAILABLE"
    )
    assert "Synthetic" not in str(rejected.json())
    stored = database.list_flights("tenant-1")
    assert len(stored) == 1
    assert stored[0]["status"] == "Failed"
    assert stored[0]["analysis_path"] is None
    assert list(main.RESULT_DIR.glob("*")) == []
    assert list(main.REPORT_DIR.glob("*")) == []


def test_processing_service_analysis_replay_is_never_reported_as_success(
    service_app: TestClient,
) -> None:
    headers = {
        **_authorization(),
        "X-PilotDriven-Request-Id": "processing-upload-request",
    }
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    stored = database.get_flight_by_analysis_id(
        created.json()["analysis_id"],
        "tenant-1",
    )
    assert stored is not None
    database.update_status(int(stored["id"]), "Processing", tenant_id="tenant-1")

    replay = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304-retry.pdf", _build_lido_pdf(), "application/pdf")},
    )

    assert replay.status_code == 409
    assert replay.json()["detail"] == "Analysis is already in progress"
    assert len(database.list_flights("tenant-1")) == 1


def test_async_service_analysis_returns_promptly_and_is_polled_to_completion(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def controlled_background_analysis(
        flight_id,
        flight,
        weather_window_preference=None,
        *,
        claimed_flight=None,
        **_kwargs,
    ):
        assert weather_window_preference == {
            "before_minutes": 45,
            "after_minutes": 75,
        }
        assert claimed_flight is flight
        started.set()
        assert release.wait(timeout=10)
        database.update_status(
            flight_id,
            "Completed",
            tenant_id=str(flight["tenant_id"]),
        )
        return None

    monkeypatch.setattr(main, "_execute_analysis", controlled_background_analysis)
    headers = {
        **_authorization(),
        "X-PilotDriven-Request-Id": "async-upload-request",
    }
    try:
        created = service_app.post(
            "/v1/analyses",
            headers=headers,
            files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
            data={
                "weather_before_minutes": "45",
                "weather_after_minutes": "75",
                "respond_async": "true",
            },
        )

        assert created.status_code == 202
        assert created.json()["status"] == "Processing"
        assert created.json()["failure"] is None
        assert created.headers["retry-after"] == "2"
        assert created.headers["location"].endswith(
            f"/{created.json()['analysis_id']}"
        )
        assert started.wait(timeout=10)

        duplicate = service_app.post(
            "/v1/analyses",
            headers=headers,
            files={
                "file": (
                    "SQ304-duplicate.pdf",
                    _build_lido_pdf(),
                    "application/pdf",
                )
            },
            data={"respond_async": "true"},
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["analysis_id"] == created.json()["analysis_id"]
        assert duplicate.json()["status"] == "Processing"
        assert len(database.list_flights("tenant-1")) == 1

        release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            completed = service_app.get(
                f"/v1/analyses/{created.json()['analysis_id']}",
                headers=_authorization(),
            )
            if completed.json()["status"] == "Completed":
                break
            time.sleep(0.01)
        else:
            pytest.fail("asynchronous analysis did not reach Completed")

        assert completed.status_code == 200
        assert completed.json()["failure"] is None
    finally:
        release.set()


def test_failed_service_summary_exposes_only_safe_retry_metadata(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    flight = database.get_flight_by_analysis_id(
        created.json()["analysis_id"],
        "tenant-1",
    )
    assert flight is not None
    database.update_status(
        int(flight["id"]),
        "Failed",
        last_error="Synthetic private infrastructure detail",
        tenant_id="tenant-1",
        analysis_failure_category="infrastructure",
    )

    summary = service_app.get(
        f"/v1/analyses/{created.json()['analysis_id']}",
        headers=_authorization(),
    )

    assert summary.status_code == 200
    assert summary.json()["failure"] == {
        "code": "ANALYSIS_TEMPORARILY_UNAVAILABLE",
        "message": (
            "PilotDriven could not complete this analysis. Retry the same "
            "upload; the original request remains safe to replay."
        ),
        "retryable": True,
    }
    assert "Synthetic" not in str(summary.json())


def test_service_timing_accepts_atot_and_rejects_unknown_reference(
    service_app: TestClient,
) -> None:
    create_response = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
        data={
            "weather_before_minutes": "45",
            "weather_after_minutes": "75",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    analysis_id = created["analysis_id"]
    initial_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    updated = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
            "weather_before_minutes": 30,
            "weather_after_minutes": 90,
        },
    )
    invalid = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "waypoint",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    assert updated.status_code == 200
    assert invalid.status_code == 422
    assert initial_briefing["flight"]["weather_window_preference"] == {
        "before_minutes": 45,
        "after_minutes": 75,
        "basis": "scheduled_phase_reference",
    }
    assert briefing["timing"]["actual_takeoff_utc"] == "2026-07-11T10:42:00+00:00"
    assert briefing["flight"]["weather_window_preference"] == {
        "before_minutes": 30,
        "after_minutes": 90,
        "basis": "scheduled_phase_reference",
    }


def test_weather_window_regenerates_current_analysis_without_inventing_atot(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    before = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    updated = service_app.post(
        f"/v1/analyses/{analysis_id}/weather-window",
        headers=_authorization(),
        json={"before_minutes": 120, "after_minutes": 90},
    )
    invalid = service_app.post(
        f"/v1/analyses/{analysis_id}/weather-window",
        headers=_authorization(),
        json={"before_minutes": 721, "after_minutes": 90},
    )
    after = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    assert updated.status_code == 200
    assert invalid.status_code == 422
    assert before["timing"] is None
    assert after["timing"] is None
    assert after["flight"]["weather_window_preference"] == {
        "before_minutes": 120,
        "after_minutes": 90,
        "basis": "scheduled_phase_reference",
    }


def test_failed_timing_update_returns_non_200_and_restores_previous_reference(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    prior_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert prior_flight is not None
    timing_fields = (
        "actual_takeoff_utc",
        "timing_reference_type",
        "timing_reference_utc",
        "timing_reference_waypoint",
    )
    prior_timing = {field: prior_flight[field] for field in timing_fields}
    artifact_fields = (
        "analysis_path",
        "level1_report",
        "level2_report",
        "level3_json",
        "level3_report",
    )
    prior_artifacts = {}
    for field in artifact_fields:
        path_value = prior_flight[field]
        if not path_value:
            continue
        artifact_path = Path(path_value)
        assert artifact_path.is_file(), field
        prior_artifacts[field] = (
            str(artifact_path),
            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        )
    assert {"analysis_path", "level1_report", "level2_report"} <= prior_artifacts.keys()

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("Synthetic timing regeneration failure")

    monkeypatch.setattr(main, "run_odss_analysis", fail_analysis)
    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    restored = service_app.get(
        f"/v1/analyses/{analysis_id}",
        headers=_authorization(),
    ).json()
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()
    restored_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")

    assert rejected.status_code == 422
    assert "Synthetic timing regeneration failure" in rejected.json()["detail"]
    assert restored["status"] == "Completed"
    assert briefing["timing"] is None
    assert restored_flight is not None
    assert restored_flight["status"] == "Completed"
    assert {field: restored_flight[field] for field in timing_fields} == prior_timing
    for field, (prior_path, prior_sha256) in prior_artifacts.items():
        assert restored_flight[field] == prior_path
        assert hashlib.sha256(Path(prior_path).read_bytes()).hexdigest() == prior_sha256


def test_report_render_failure_keeps_valid_timing_and_exposes_retryable_state(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    prior_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert prior_flight is not None
    prior_reports = {
        field: (
            str(prior_flight[field]),
            hashlib.sha256(Path(str(prior_flight[field])).read_bytes()).hexdigest(),
        )
        for field in ("level1_report", "level2_report")
    }

    original_render_pdf = analysis_module.render_pdf

    def fail_level_two_report(*args, **kwargs):
        level = args[3] if len(args) > 3 else kwargs["level"]
        if level == 2:
            raise ValueError(
                "Pilot-facing table cell cannot be rendered completely "
                "at row 1, column 3."
            )
        return original_render_pdf(*args, **kwargs)

    monkeypatch.setattr(analysis_module, "render_pdf", fail_level_two_report)
    accepted = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    stored = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    )

    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["status"] == "Completed"
    assert accepted_payload["report_refresh"] == {
        "state": "failed",
        "reports_current": False,
        "warning": (
            "The timing update is active, but the Level 1 and Level 2 reports "
            "could not be refreshed. Retry report generation before use."
        ),
    }
    assert accepted_payload["report_refresh"]["warning"] in accepted_payload["warnings"]
    assert stored is not None
    assert stored["status"] == "Completed"
    assert stored["timing_reference_utc"] == "2026-07-11T10:42:00+00:00"
    assert stored["report_refresh_state"] == "failed"
    assert stored["report_refresh_error_type"] == "ValueError"
    assert briefing.status_code == 200
    assert briefing.json()["timing"]["actual_takeoff_utc"] == "2026-07-11T10:42:00+00:00"
    assert briefing.json()["report_refresh"] == accepted_payload["report_refresh"]
    for field, (prior_path, prior_sha256) in prior_reports.items():
        assert stored[field] == prior_path
        assert hashlib.sha256(Path(prior_path).read_bytes()).hexdigest() == prior_sha256

    for level in (1, 2):
        stale = service_app.get(
            f"/v1/analyses/{analysis_id}/reports/level-{level}",
            headers=_authorization(),
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == (
            "Reports are not current for the active analysis. Retry report generation."
        )

    async def successful_report_retry(*args, **kwargs):
        return {"mode": "primary", "reports_refreshed": True}

    monkeypatch.setattr(
        report_worker,
        "render_reports_for_analysis",
        successful_report_retry,
    )
    retried = service_app.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=_authorization(),
    )
    refreshed = service_app.get(
        f"/v1/analyses/{analysis_id}",
        headers=_authorization(),
    )
    refreshed_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    )

    assert retried.status_code == 200
    assert refreshed.status_code == 200
    assert refreshed.json()["report_refresh"] == {
        "state": "current",
        "reports_current": True,
        "warning": None,
    }
    assert refreshed_briefing.json()["report_refresh"] == refreshed.json()["report_refresh"]
    assert accepted_payload["report_refresh"]["warning"] not in refreshed_briefing.json()["warnings"]
    refreshed_row = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert refreshed_row is not None
    refreshed_analysis = main.load_analysis(refreshed_row["analysis_path"])
    assert refreshed_analysis is not None
    assert refreshed_analysis["view"]["report_refresh"] == refreshed.json()["report_refresh"]
    assert service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=_authorization(),
    ).status_code == 200


def test_concurrent_timing_update_returns_409_without_splitting_stored_state(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    prior_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert prior_flight is not None
    timing_fields = (
        "actual_takeoff_utc",
        "timing_reference_type",
        "timing_reference_utc",
        "timing_reference_waypoint",
    )
    artifact_fields = (
        "analysis_path",
        "level1_report",
        "level2_report",
        "level3_json",
        "level3_report",
    )
    prior_timing = {field: prior_flight[field] for field in timing_fields}
    prior_artifacts = {
        field: (
            str(prior_flight[field]),
            hashlib.sha256(Path(str(prior_flight[field])).read_bytes()).hexdigest(),
        )
        for field in artifact_fields
        if prior_flight[field]
    }
    database.update_status(
        int(prior_flight["id"]),
        "Processing",
        tenant_id="tenant-1",
    )

    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    restored_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")

    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Analysis is already in progress"
    assert restored_flight is not None
    assert restored_flight["status"] == "Processing"
    assert {field: restored_flight[field] for field in timing_fields} == prior_timing
    for field, (prior_path, prior_sha256) in prior_artifacts.items():
        assert restored_flight[field] == prior_path
        assert hashlib.sha256(Path(prior_path).read_bytes()).hexdigest() == prior_sha256


def test_final_status_write_failure_restores_prior_db_artifact_snapshot(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    prior = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert prior is not None
    snapshot_fields = (
        "status",
        "actual_takeoff_utc",
        "timing_reference_type",
        "timing_reference_utc",
        "timing_reference_waypoint",
        "analysis_path",
        "level1_report",
        "level2_report",
        "level3_json",
        "level3_report",
        "report_refresh_state",
        "report_refresh_error_type",
        "analysis_failure_category",
    )
    prior_snapshot = {field: prior[field] for field in snapshot_fields}
    artifact_fields = (
        "analysis_path",
        "level1_report",
        "level2_report",
        "level3_json",
        "level3_report",
    )
    prior_artifacts = {
        field: (
            Path(str(prior[field])),
            hashlib.sha256(Path(str(prior[field])).read_bytes()).hexdigest(),
        )
        for field in artifact_fields
        if prior[field]
    }
    prior_result_files = {path.name for path in main.RESULT_DIR.iterdir()}
    prior_report_files = {path.name for path in main.REPORT_DIR.iterdir()}

    original_update_status = main.update_status
    injected = False

    def fail_completed_status(flight_id, status, *args, **kwargs):
        nonlocal injected
        if status == "Completed" and not injected:
            injected = True
            raise OSError("Synthetic final status write failure")
        return original_update_status(flight_id, status, *args, **kwargs)

    monkeypatch.setattr(main, "update_status", fail_completed_status)
    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )

    restored = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert rejected.status_code == 422
    assert injected is True
    assert restored is not None
    assert {field: restored[field] for field in snapshot_fields} == prior_snapshot
    for field, (path, digest) in prior_artifacts.items():
        assert restored[field] == str(path)
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert {path.name for path in main.RESULT_DIR.iterdir()} == prior_result_files
    assert {path.name for path in main.REPORT_DIR.iterdir()} == prior_report_files
    assert service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).status_code == 200
    for level in (1, 2):
        assert service_app.get(
            f"/v1/analyses/{analysis_id}/reports/level-{level}",
            headers=_authorization(),
        ).status_code == 200


def test_stale_simultaneous_timing_loser_cannot_clobber_winner(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    stale_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert stale_flight is not None
    stale_analysis = main.load_analysis(stale_flight["analysis_path"])
    assert stale_analysis is not None

    original_run = main.run_odss_analysis
    original_service_analysis = main._service_analysis
    winner_running = threading.Event()
    release_winner = threading.Event()

    def blocked_run(*args, **kwargs):
        winner_running.set()
        if not release_winner.wait(timeout=10):
            raise TimeoutError("Concurrent timing test did not release winner")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(main, "run_odss_analysis", blocked_run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        winner_future = pool.submit(
            service_app.post,
            f"/v1/analyses/{analysis_id}/timing",
            headers=_authorization(),
            json={
                "reference_type": "takeoff",
                "reference_utc": "2026-07-11T10:42:00+00:00",
            },
        )
        try:
            assert winner_running.wait(timeout=10)
            # Model a second request that read Completed just before the first
            # request acquired ownership. Its stale snapshot must not permit a
            # timing write after the row has transitioned to Processing.
            monkeypatch.setattr(
                main,
                "_service_analysis",
                lambda analysis_id, identity: (stale_flight, stale_analysis),
            )
            loser = service_app.post(
                f"/v1/analyses/{analysis_id}/timing",
                headers=_authorization(),
                json={
                    "reference_type": "takeoff",
                    "reference_utc": "2026-07-11T11:17:00+00:00",
                },
            )
        finally:
            release_winner.set()
        winner = winner_future.result(timeout=20)

    monkeypatch.setattr(main, "_service_analysis", original_service_analysis)
    final_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    assert winner.status_code == 200
    assert loser.status_code == 409
    assert final_flight is not None
    assert final_flight["status"] == "Completed"
    assert final_flight["timing_reference_utc"] == "2026-07-11T10:42:00+00:00"
    assert briefing["timing"]["actual_takeoff_utc"] == "2026-07-11T10:42:00+00:00"


def test_failed_weather_window_update_retains_completed_artifacts(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    prior_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert prior_flight is not None
    assert all(prior_flight[field] for field in ("analysis_path", "level1_report", "level2_report"))
    prior_paths = {
        field: str(prior_flight[field])
        for field in ("analysis_path", "level1_report", "level2_report")
    }
    prior_hashes = {
        field: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for field, path in prior_paths.items()
    }

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("Synthetic weather-window regeneration failure")

    monkeypatch.setattr(main, "run_odss_analysis", fail_analysis)
    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/weather-window",
        headers=_authorization(),
        json={"before_minutes": 120, "after_minutes": 90},
    )
    restored_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")

    assert rejected.status_code == 422
    assert "Synthetic weather-window regeneration failure" in rejected.json()["detail"]
    assert restored_flight is not None
    assert restored_flight["status"] == "Completed"
    for field, path in prior_paths.items():
        assert restored_flight[field] == path
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == prior_hashes[field]


def test_analysis_claim_stays_owned_through_primary_map_refresh(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    observed_statuses: list[str] = []

    def inspect_refresh_lock(flight, result):
        current = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
        assert current is not None
        observed_statuses.append(str(current["status"]))
        assert database.claim_analysis(int(current["id"]), "tenant-1") is None

    monkeypatch.setattr(main, "_refresh_reports_with_primary_map", inspect_refresh_lock)
    updated = service_app.post(
        f"/v1/analyses/{analysis_id}/weather-window",
        headers=_authorization(),
        json={"before_minutes": 120, "after_minutes": 90},
    )
    final_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")

    assert updated.status_code == 200
    assert observed_statuses == ["Processing"]
    assert final_flight is not None
    assert final_flight["status"] == "Completed"


def test_service_personal_notes_are_validated_tenant_scoped_and_regenerated(
    service_app: TestClient,
) -> None:
    owner_headers = _authorization("tenant-owner", "pilot-owner")
    other_headers = _authorization("tenant-other", "pilot-other")
    created = service_app.post(
        "/v1/analyses",
        headers=owner_headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    note_payload = {
        "placement": "destination",
        "note_text": "Confirm destination stand and taxi routing before descent.",
        "include_level1": True,
        "include_level2": True,
    }

    cross_tenant = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=other_headers,
        json=note_payload,
    )
    no_report_selected = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=owner_headers,
        json={
            **note_payload,
            "include_level1": False,
            "include_level2": False,
        },
    )
    unexpected_field = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=owner_headers,
        json={**note_payload, "tenant_id": "tenant-other"},
    )
    added = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=owner_headers,
        json=note_payload,
    )

    assert cross_tenant.status_code == 404
    assert no_report_selected.status_code == 400
    assert unexpected_field.status_code == 422
    assert added.status_code == 201
    added_note = added.json()["note"]
    assert added_note["placement"] == "destination"
    assert added_note["placement_label"] == "Destination airport section"
    assert added_note["source"] == "pilot_personal_note"
    assert added.json()["notes"] == [added_note]

    briefing_with_note = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert briefing_with_note["personal_notes"] == [added_note]
    level_1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=owner_headers,
    )
    with fitz.open(stream=level_1.content, filetype="pdf") as report:
        report_text = "\n".join(page.get_text() for page in report)
    assert note_payload["note_text"] in " ".join(report_text.split())

    cross_tenant_delete = service_app.delete(
        f"/v1/analyses/{analysis_id}/notes/{added_note['id']}",
        headers=other_headers,
    )
    deleted = service_app.delete(
        f"/v1/analyses/{analysis_id}/notes/{added_note['id']}",
        headers=owner_headers,
    )
    briefing_without_note = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()

    assert cross_tenant_delete.status_code == 404
    assert deleted.status_code == 200
    assert deleted.json()["notes"] == []
    assert briefing_without_note["personal_notes"] == []


def test_stale_simultaneous_note_loser_never_stages_a_note(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    stale_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert stale_flight is not None
    stale_analysis = main.load_analysis(stale_flight["analysis_path"])
    assert stale_analysis is not None

    original_run = main.run_odss_analysis
    original_create_note = main.create_personal_note
    original_service_analysis = main._service_analysis
    winner_running = threading.Event()
    release_winner = threading.Event()
    create_count = 0
    create_count_lock = threading.Lock()

    def counted_create_note(*args, **kwargs):
        nonlocal create_count
        with create_count_lock:
            create_count += 1
        return original_create_note(*args, **kwargs)

    def blocked_run(*args, **kwargs):
        winner_running.set()
        if not release_winner.wait(timeout=10):
            raise TimeoutError("Concurrent note test did not release winner")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(main, "create_personal_note", counted_create_note)
    monkeypatch.setattr(main, "run_odss_analysis", blocked_run)
    winner_payload = {
        "placement": "destination",
        "note_text": "Winner note must be the only staged note.",
        "include_level1": True,
        "include_level2": True,
    }
    with ThreadPoolExecutor(max_workers=1) as pool:
        winner_future = pool.submit(
            service_app.post,
            f"/v1/analyses/{analysis_id}/notes",
            headers=_authorization(),
            json=winner_payload,
        )
        try:
            assert winner_running.wait(timeout=10)
            monkeypatch.setattr(
                main,
                "_service_analysis",
                lambda analysis_id, identity: (stale_flight, stale_analysis),
            )
            loser = service_app.post(
                f"/v1/analyses/{analysis_id}/notes",
                headers=_authorization(),
                json={
                    **winner_payload,
                    "note_text": "This stale losing note must never be staged.",
                },
            )
        finally:
            release_winner.set()
        winner = winner_future.result(timeout=20)

    monkeypatch.setattr(main, "_service_analysis", original_service_analysis)
    final_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert final_flight is not None
    notes = [dict(note) for note in database.list_personal_notes(int(final_flight["id"]))]
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=_authorization(),
    ).json()

    assert winner.status_code == 201
    assert loser.status_code == 409
    assert create_count == 1
    assert [note["note_text"] for note in notes] == [winner_payload["note_text"]]
    assert [note["note_text"] for note in briefing["personal_notes"]] == [
        winner_payload["note_text"]
    ]


def test_service_personal_note_failures_restore_database_and_prior_reports(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    initial_note = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=headers,
        json={
            "placement": "separate",
            "note_text": "Retain this note if regeneration fails.",
            "include_level1": True,
            "include_level2": False,
        },
    ).json()["note"]
    prior_level_1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=headers,
    ).content

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("Synthetic personal-note regeneration failure")

    monkeypatch.setattr(main, "run_odss_analysis", fail_analysis)
    rejected_delete = service_app.delete(
        f"/v1/analyses/{analysis_id}/notes/{initial_note['id']}",
        headers=headers,
    )
    rejected_add = service_app.post(
        f"/v1/analyses/{analysis_id}/notes",
        headers=headers,
        json={
            "placement": "communications",
            "note_text": "This rejected note must not survive.",
            "include_level1": False,
            "include_level2": True,
        },
    )
    restored_summary = service_app.get(
        f"/v1/analyses/{analysis_id}",
        headers=headers,
    ).json()
    restored_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=headers,
    ).json()
    restored_level_1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=headers,
    ).content

    assert rejected_delete.status_code == 422
    assert rejected_add.status_code == 422
    assert "Synthetic personal-note regeneration failure" in rejected_delete.json()["detail"]
    assert restored_summary["status"] == "Completed"
    assert restored_briefing["personal_notes"] == [initial_note]
    restored_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert restored_flight is not None
    assert [
        dict(note)["id"]
        for note in database.list_personal_notes(int(restored_flight["id"]))
    ] == [
        initial_note["id"]
    ]
    assert restored_level_1 == prior_level_1


def test_company_briefing_references_are_tenant_scoped_normalized_and_rendered(
    service_app: TestClient,
) -> None:
    owner_headers = _authorization("tenant-owner", "pilot-owner")
    other_headers = _authorization("tenant-other", "pilot-other")
    created = service_app.post(
        "/v1/analyses",
        headers=owner_headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    item = briefing["flight"]["deferred_items"][0]
    assert item["classification_status"] == "unresolved"
    deferred_entry_id = item["deferred_entry_id"]

    initial_report = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/combined",
        headers=owner_headers,
    )
    assert initial_report.status_code == 200
    with fitz.open(stream=initial_report.content, filetype="pdf") as document:
        initial_text = "\n".join(page.get_text() for page in document)
    assert "MANUAL REVIEW REQUIRED | OFP SOURCE HELD" in initial_text
    assert "25-21-08B" not in initial_text

    ambiguity = (
        "The OFP does not state whether the tray table blocks cabin-door access."
    )
    confirmation = (
        "Confirm the Tech Log door-access condition before selecting B or C."
    )

    def candidate(suffix: str) -> dict:
        reference = f"25-21-08{suffix}"
        return {
            "excerpt": (
                f"MEL {reference} Passenger Seat Meal Table controlled "
                f"candidate {suffix} extract."
            ),
            "citation": {
                "sourceClass": "company_manual",
                "documentTitle": "Synthetic A350 MEL",
                "version": "Revision TEST",
                "effectiveDate": "2026-07-01",
                "page": "221",
                "section": f"MEL {reference}",
                "safeTarget": (
                    "/api/help-you/references/ref-test/open?page=221"
                ),
                "applicability": {
                    "scope": "specified",
                    "fleet": "LH",
                    "aircraft": "A350-941",
                    "status": "confirmed",
                },
                "untrustedExtra": "must not persist",
            },
            "deferredBinding": {
                "deferredEntryId": deferred_entry_id,
                "matchStatus": "candidate",
                "itemType": "MEL",
                "reference": reference,
                "ambiguityReason": ambiguity,
                "confirmationRequired": confirmation,
            },
            "untrustedExtra": "must not persist",
        }

    payload = {
        "status": "available",
        "references": [candidate("B"), candidate("C")],
    }
    unauthenticated = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        json=payload,
    )
    cross_tenant = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=other_headers,
        json=payload,
    )
    assert unauthenticated.status_code == 401
    assert cross_tenant.status_code == 404

    published = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=owner_headers,
        json=payload,
    )
    assert published.status_code == 200
    body = published.json()
    assert body["combined_report"] == {
        "state": "invalidated",
        "render": "on_demand",
        "href": f"/v1/analyses/{analysis_id}/reports/combined",
    }
    stored_references = body["company_briefing_references"]["references"]
    assert len(stored_references) == 2
    assert "untrustedExtra" not in stored_references[0]
    assert "untrustedExtra" not in stored_references[0]["citation"]
    assert stored_references[0]["deferredBinding"] == {
        "deferredEntryId": deferred_entry_id,
        "matchStatus": "candidate",
        "itemType": "MEL",
        "reference": "25-21-08B",
        "ambiguityReason": ambiguity,
        "confirmationRequired": confirmation,
    }
    with database.connect() as conn:
        audit_row = conn.execute(
            """
            SELECT action, details_json FROM audit_events
            WHERE tenant_id=? AND resource_id=?
              AND action='analysis.company_briefing_references_publication_authorized'
            ORDER BY rowid DESC LIMIT 1
            """,
            ("tenant-owner", analysis_id),
        ).fetchone()
    assert audit_row is not None
    audit_details = json.loads(audit_row["details_json"])
    assert audit_details["reference_count"] == 2
    assert audit_details["governed_reference_status"] == "available"
    assert len(audit_details["governed_extract_ids"]) == 2
    assert all(
        extract_id.startswith("governed-deferred-")
        for extract_id in audit_details["governed_extract_ids"]
    )
    assert audit_details["prior_artifact_sha256"] != (
        audit_details["new_artifact_sha256"]
    )
    serialized_audit = json.dumps(audit_details, sort_keys=True)
    assert "controlled candidate B extract" not in serialized_audit
    assert "controlled candidate C extract" not in serialized_audit
    assert "excerpt" not in serialized_audit.lower()

    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-owner")
    assert flight is not None
    stored_analysis = json.loads(
        Path(str(flight["analysis_path"])).read_text(encoding="utf-8")
    )
    assert (
        stored_analysis["company_briefing_references"]
        == body["company_briefing_references"]
    )
    reloaded_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert (
        reloaded_briefing["company_briefing_references"]
        == body["company_briefing_references"]
    )
    published_artifact_sha256 = hashlib.sha256(
        Path(str(flight["analysis_path"])).read_bytes()
    ).hexdigest()

    refreshed_report = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/combined",
        headers=owner_headers,
    )
    assert refreshed_report.status_code == 200
    assert refreshed_report.content != initial_report.content
    with fitz.open(stream=refreshed_report.content, filetype="pdf") as document:
        refreshed_text = "\n".join(page.get_text() for page in document)
    for suffix in ("B", "C"):
        assert refreshed_text.count(
            f"MEL 25-21-08{suffix} Passenger Seat Meal Table controlled "
            f"candidate {suffix} extract."
        ) == 1
    assert refreshed_text.count(
        "CANDIDATE ONLY - MANUAL REVIEW REQUIRED"
    ) == 2
    assert "EXACT CURRENT-APPROVED EXTRACT" not in refreshed_text

    timing = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=owner_headers,
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    assert timing.status_code == 200
    reanalysed_flight = database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-owner",
    )
    assert reanalysed_flight is not None
    reanalysed = json.loads(
        Path(str(reanalysed_flight["analysis_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert (
        reanalysed["company_briefing_references"]
        == body["company_briefing_references"]
    )
    with database.connect() as conn:
        carried_audit = conn.execute(
            """
            SELECT details_json FROM audit_events
            WHERE tenant_id=? AND resource_id=?
              AND action='analysis.company_briefing_references_carried_forward'
            ORDER BY rowid DESC LIMIT 1
            """,
            ("tenant-owner", analysis_id),
        ).fetchone()
    assert carried_audit is not None
    carried_details = json.loads(carried_audit["details_json"])
    assert carried_details["prior_artifact_sha256"] == published_artifact_sha256
    assert carried_details["new_artifact_sha256"] == hashlib.sha256(
        Path(str(reanalysed_flight["analysis_path"])).read_bytes()
    ).hexdigest()
    assert carried_details["source_publication_operation_id"]
    assert carried_details["reason"] == (
        "analysis_recalculated_and_binding_revalidated"
    )

    cleared = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=owner_headers,
        json={"status": "unavailable", "references": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["company_briefing_references"] == {
        "status": "unavailable",
        "references": [],
    }
    cleared_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert cleared_briefing["company_briefing_references"] == {
        "status": "unavailable",
        "references": [],
    }
    cleared_report = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/combined",
        headers=owner_headers,
    )
    assert cleared_report.status_code == 200
    with fitz.open(stream=cleared_report.content, filetype="pdf") as document:
        cleared_text = "\n".join(page.get_text() for page in document)
    assert "25-21-08B Passenger Seat Meal Table controlled" not in cleared_text
    assert "25-21-08C Passenger Seat Meal Table controlled" not in cleared_text


def test_combined_report_cache_uses_the_exact_analysis_byte_snapshot(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))

    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    armed = {"value": True}

    def replace_snapshot(raw: bytes) -> None:
        if not armed["value"]:
            return
        armed["value"] = False
        updated = json.loads(raw)
        updated["company_briefing_references"] = {
            "status": "unavailable",
            "references": [],
        }
        staged = analysis_path.with_name(f"{analysis_path.name}.race.tmp")
        staged.write_text(json.dumps(updated), encoding="utf-8")
        staged.replace(analysis_path)

    def racing_read_bytes(path: Path) -> bytes:
        raw = original_read_bytes(path)
        if path == analysis_path:
            replace_snapshot(raw)
        return raw

    def racing_read_text(path: Path, *args, **kwargs) -> str:
        value = original_read_text(path, *args, **kwargs)
        if path == analysis_path:
            replace_snapshot(value.encode(kwargs.get("encoding") or "utf-8"))
        return value

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)
    monkeypatch.setattr(Path, "read_text", racing_read_text)

    rendered_states: list[str] = []

    def fake_render(_flight, _findings, _warnings, output_path, **kwargs):
        references = kwargs.get("company_briefing_references")
        state = "NEW" if references else "OLD"
        rendered_states.append(state)
        Path(output_path).write_bytes(f"%PDF-1.4\n{state}\n".encode())

    monkeypatch.setattr(main, "render_combined_briefing", fake_render)

    first = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/combined",
        headers=_authorization(),
    )
    second = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/combined",
        headers=_authorization(),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content.endswith(b"OLD\n")
    assert second.content.endswith(b"NEW\n")
    assert rendered_states == ["OLD", "NEW"]


def test_concurrent_combined_report_cache_miss_renders_once_per_flight(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    render_started = threading.Event()
    release_render = threading.Event()
    render_calls = 0
    render_calls_lock = threading.Lock()

    def slow_render(_flight, _findings, _warnings, output_path, **_kwargs):
        nonlocal render_calls
        with render_calls_lock:
            render_calls += 1
        render_started.set()
        assert release_render.wait(timeout=5)
        Path(output_path).write_bytes(b"%PDF-1.4\nSERIALIZED\n")

    monkeypatch.setattr(main, "render_combined_briefing", slow_render)
    path = f"/v1/analyses/{analysis_id}/reports/combined"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service_app.get, path, headers=_authorization())
        assert render_started.wait(timeout=5)
        second_future = pool.submit(service_app.get, path, headers=_authorization())
        time.sleep(0.1)
        assert render_calls == 1
        release_render.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    assert render_calls == 1


def test_combined_report_cache_pruning_counts_an_old_kept_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path)
    paths = []
    for index in range(6):
        path = tmp_path / f"flight_41_combined_token-{index}.pdf"
        path.write_bytes(f"artifact-{index}".encode())
        os.utime(path, ns=(index + 1, index + 1))
        paths.append(path)

    main._prune_combined_report_cache(
        41,
        keep=paths[0],
        max_entries=4,
    )

    retained = set(tmp_path.glob("flight_41_combined_*.pdf"))
    assert len(retained) == 4
    assert paths[0] in retained
    assert retained == {paths[0], paths[3], paths[4], paths[5]}


def test_company_briefing_references_reject_every_unbound_or_incomplete_row(
    service_app: TestClient,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=headers,
    ).json()
    deferred_entry_id = briefing["flight"]["deferred_items"][0][
        "deferred_entry_id"
    ]
    complete = {
        "excerpt": "MEL 25-21-08B Passenger Seat Meal Table controlled extract.",
        "citation": {
            "sourceClass": "company_manual",
            "documentTitle": "Synthetic A350 MEL",
            "version": "Revision TEST",
            "effectiveDate": "2026-07-01",
            "page": "221",
            "section": "MEL 25-21-08B",
            "applicability": {
                "scope": "specified",
                "aircraft": "A350-941",
                "status": "confirmed",
            },
        },
        "deferredBinding": {
            "deferredEntryId": deferred_entry_id,
            "matchStatus": "candidate",
            "itemType": "MEL",
            "reference": "25-21-08B",
            "ambiguityReason": "Door-access effect is absent.",
            "confirmationRequired": "Confirm the Tech Log.",
        },
    }
    invalid_rows = [
        {
            **complete,
            "deferredBinding": {
                **complete["deferredBinding"],
                "deferredEntryId": "ofp-deferred-wrong",
            },
        },
        {
            key: value
            for key, value in complete.items()
            if key != "deferredBinding"
        },
        {
            **complete,
            "citation": {
                **complete["citation"],
                "applicability": {"status": "review_required"},
            },
        },
    ]
    for invalid in invalid_rows:
        rejected = service_app.post(
            f"/v1/analyses/{analysis_id}/company-briefing-references",
            headers=headers,
            json={"status": "available", "references": [invalid]},
        )
        assert rejected.status_code == 422
        assert "does not bind" in rejected.json()["detail"]

    applicability_mismatch = {
        **complete,
        "citation": {
            **complete["citation"],
            "applicability": {
                "scope": "specified",
                "aircraft": "B787-10",
                "status": "confirmed",
            },
        },
    }
    rejected_mismatch = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "available", "references": [applicability_mismatch]},
    )
    assert rejected_mismatch.status_code == 422
    assert "active flight applicability" in rejected_mismatch.json()["detail"]

    malformed_clear = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "unavailable", "references": [complete]},
    )
    assert malformed_clear.status_code == 422
    assert "must contain no entries" in malformed_clear.json()["detail"]

    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    stored_analysis = json.loads(
        Path(str(flight["analysis_path"])).read_text(encoding="utf-8")
    )
    assert "company_briefing_references" not in stored_analysis
    assert database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )["status"] == "Completed"


def test_company_briefing_reference_atomic_commit_failure_is_retryable_and_unchanged_retry_is_idempotent(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))
    prior_artifact = analysis_path.read_bytes()
    prior_mtime = analysis_path.stat().st_mtime_ns

    real_commit = main.commit_company_briefing_reference_publication
    commit_calls = 0

    def fail_first_commit(operation_id: str):
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise sqlite3.OperationalError("synthetic audit store outage")
        return real_commit(operation_id)

    monkeypatch.setattr(
        main,
        "commit_company_briefing_reference_publication",
        fail_first_commit,
    )
    with caplog.at_level(logging.ERROR, logger="app.main"):
        failed = service_app.post(
            f"/v1/analyses/{analysis_id}/company-briefing-references",
            headers=headers,
            json={"status": "unavailable", "references": []},
        )

    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "message": (
            "The governed reference publication was not activated because "
            "its atomic audit commit failed."
        ),
        "publication_persisted": False,
        "publication_state": "unchanged",
        "audit_state": "failed",
        "retry_same_payload": True,
    }
    assert "atomic audit/pointer commit failed" in caplog.text
    assert analysis_path.read_bytes() == prior_artifact
    assert analysis_path.stat().st_mtime_ns == prior_mtime
    assert "company_briefing_references" not in json.loads(prior_artifact)
    assert database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )["status"] == "Completed"

    retried = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "unavailable", "references": []},
    )

    assert retried.status_code == 200
    assert retried.json()["publication"] == {"state": "published"}
    assert retried.json()["audit"]["state"] == "recorded"
    audit_event_id = retried.json()["audit"]["event_id"]
    assert retried.json()["combined_report"]["state"] == "invalidated"
    published_flight = database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )
    assert published_flight is not None
    published_path = Path(str(published_flight["analysis_path"]))
    assert published_path != analysis_path
    persisted_after_retry = published_path.read_bytes()
    assert persisted_after_retry != prior_artifact
    assert json.loads(persisted_after_retry)["company_briefing_references"] == {
        "status": "unavailable",
        "references": [],
    }
    with database.connect() as conn:
        audit = conn.execute(
            "SELECT * FROM audit_events WHERE id=?",
            (audit_event_id,),
        ).fetchone()
        audit_count = conn.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE resource_id=?
              AND action='analysis.company_briefing_references_publication_authorized'
            """,
            (analysis_id,),
        ).fetchone()[0]
    assert audit is not None
    audit_details = json.loads(audit["details_json"])
    assert audit_details["prior_artifact_sha256"] == hashlib.sha256(
        prior_artifact
    ).hexdigest()
    assert audit_details["new_artifact_sha256"] == hashlib.sha256(
        persisted_after_retry
    ).hexdigest()
    assert audit_details["governed_extract_ids"] == []
    assert audit_details["combined_report"] == (
        "invalidated_for_on_demand_render"
    )

    def audit_outage_must_not_be_called(_operation_id: str):
        raise AssertionError("unchanged retry attempted another audit commit")

    monkeypatch.setattr(
        main,
        "commit_company_briefing_reference_publication",
        audit_outage_must_not_be_called,
    )
    mtime_after_retry = published_path.stat().st_mtime_ns
    retried_unchanged = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "unavailable", "references": []},
    )
    assert retried_unchanged.status_code == 200
    assert retried_unchanged.json()["publication"] == {"state": "unchanged"}
    assert retried_unchanged.json()["audit"]["event_id"] == audit_event_id
    assert published_path.read_bytes() == persisted_after_retry
    assert published_path.stat().st_mtime_ns == mtime_after_retry
    with database.connect() as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE resource_id=?
              AND action='analysis.company_briefing_references_publication_authorized'
            """,
            (analysis_id,),
        ).fetchone()[0] == audit_count


def test_company_briefing_reference_publication_failure_keeps_prior_artifact(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))
    prior_artifact = analysis_path.read_bytes()
    def fail_publication(_artifacts) -> None:
        raise OSError("synthetic governed artifact publication failure")

    monkeypatch.setattr(main, "publish_staged_artifacts", fail_publication)
    failed = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "unavailable", "references": []},
    )

    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "message": (
            "The governed reference artifact could not be prepared. The prior "
            "analysis remains active; retry the same payload."
        ),
        "publication_persisted": False,
        "publication_state": "unchanged",
        "audit_state": "not_started",
        "retry_same_payload": True,
    }
    assert analysis_path.read_bytes() == prior_artifact
    with database.connect() as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE resource_id=?
              AND action='analysis.company_briefing_references_publication_authorized'
            """,
            (analysis_id,),
        ).fetchone()[0] == 0
    assert database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )["status"] == "Completed"


def test_company_briefing_reference_post_commit_cleanup_error_reports_success(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))
    prior_artifact = analysis_path.read_bytes()

    def commit_then_warn(artifacts) -> None:
        staged, destination = artifacts[0]
        staged.replace(destination)
        raise OSError("synthetic backup cleanup warning")

    monkeypatch.setattr(main, "publish_staged_artifacts", commit_then_warn)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        published = service_app.post(
            f"/v1/analyses/{analysis_id}/company-briefing-references",
            headers=headers,
            json={"status": "unavailable", "references": []},
        )

    assert published.status_code == 200
    assert published.json()["publication"] == {"state": "published"}
    assert "target committed with a cleanup warning" in caplog.text
    current_flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert current_flight is not None
    current_path = Path(str(current_flight["analysis_path"]))
    committed = current_path.read_bytes()
    assert committed != prior_artifact
    assert json.loads(committed)["company_briefing_references"] == {
        "status": "unavailable",
        "references": [],
    }


def test_company_briefing_reference_claim_compare_and_set_requires_completed(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={
            "file": (
                "SQ304.pdf",
                _build_lido_pdf_with_sq481_deferred_block(),
                "application/pdf",
            )
        },
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))
    prior_artifact = analysis_path.read_bytes()
    real_prepare = main.prepare_company_briefing_reference_publication
    prepare_calls = 0

    def race_prepare(**kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        database.update_status(
            int(kwargs["flight_id"]),
            "Failed",
            notes="Synthetic concurrent state transition.",
            tenant_id=kwargs["tenant_id"],
        )
        return real_prepare(**kwargs)

    monkeypatch.setattr(
        main,
        "prepare_company_briefing_reference_publication",
        race_prepare,
    )
    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/company-briefing-references",
        headers=headers,
        json={"status": "unavailable", "references": []},
    )

    assert rejected.status_code == 409
    assert prepare_calls == 1
    assert analysis_path.read_bytes() == prior_artifact
    assert database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )["status"] == "Failed"


def test_company_briefing_reference_prepared_crash_reconciles_once(
    service_app: TestClient,
) -> None:
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses",
        headers=headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    prior_path = Path(str(flight["analysis_path"]))
    prior_bytes = prior_path.read_bytes()
    desired = {"status": "unavailable", "references": []}
    updated = json.loads(prior_bytes)
    updated["company_briefing_references"] = desired
    target_bytes = json.dumps(updated, indent=2).encode()
    target_path = prior_path.with_name(f"{prior_path.stem}.prepared-crash.json")
    target_path.write_bytes(target_bytes)
    payload_sha256 = hashlib.sha256(
        json.dumps(desired, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    operation = database.prepare_company_briefing_reference_publication(
        flight_id=int(flight["id"]),
        tenant_id="tenant-1",
        analysis_id=analysis_id,
        actor_id="pilot-7",
        payload_sha256=payload_sha256,
        prior_analysis_path=str(prior_path),
        target_analysis_path=str(target_path),
        prior_artifact_sha256=hashlib.sha256(prior_bytes).hexdigest(),
        target_artifact_sha256=hashlib.sha256(target_bytes).hexdigest(),
        audit_details={
            "reference_count": 0,
            "governed_reference_status": "unavailable",
            "governed_extract_ids": [],
        },
    )
    assert operation is not None
    assert database.get_flight_by_analysis_id(
        analysis_id,
        "tenant-1",
    )["status"] == "Processing"

    database.init_db()
    recovered = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert recovered is not None
    assert recovered["status"] == "Completed"
    assert recovered["analysis_path"] == str(target_path)
    assert json.loads(target_path.read_bytes())["company_briefing_references"] == desired
    committed = database.find_company_briefing_reference_publication(
        tenant_id="tenant-1",
        analysis_id=analysis_id,
        payload_sha256=payload_sha256,
        target_analysis_path=str(target_path),
        states=("committed",),
    )
    assert committed is not None
    with database.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE id=?",
            (committed["audit_event_id"],),
        ).fetchone()[0] == 1
    database.init_db()
    with database.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE id=?",
            (committed["audit_event_id"],),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("target_damage", ["missing", "corrupt"])
def test_company_briefing_reference_reconciler_rolls_back_bad_target(
    service_app: TestClient,
    target_damage: str,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    prior_path = Path(str(flight["analysis_path"]))
    prior_bytes = prior_path.read_bytes()
    target_path = prior_path.with_name(
        f"{prior_path.stem}.prepared-{target_damage}.json"
    )
    target_bytes = prior_bytes + b"\n"
    target_path.write_bytes(target_bytes)
    operation = database.prepare_company_briefing_reference_publication(
        flight_id=int(flight["id"]),
        tenant_id="tenant-1",
        analysis_id=analysis_id,
        actor_id="pilot-7",
        payload_sha256=hashlib.sha256(b"unavailable").hexdigest(),
        prior_analysis_path=str(prior_path),
        target_analysis_path=str(target_path),
        prior_artifact_sha256=hashlib.sha256(prior_bytes).hexdigest(),
        target_artifact_sha256=hashlib.sha256(target_bytes).hexdigest(),
        audit_details={"reference_count": 0},
    )
    assert operation is not None
    if target_damage == "missing":
        target_path.unlink()
    else:
        target_path.write_bytes(b"corrupt")

    database.init_db()
    restored = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert restored is not None
    assert restored["status"] == "Completed"
    assert restored["analysis_path"] == str(prior_path)
    assert prior_path.read_bytes() == prior_bytes
    with database.connect() as conn:
        operation_row = conn.execute(
            """
            SELECT state FROM company_briefing_reference_publications
            WHERE id=?
            """,
            (operation["id"],),
        ).fetchone()
        assert operation_row["state"] == "aborted"
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE id=?",
            (operation["audit_event_id"],),
        ).fetchone()[0] == 0


def test_stale_analysis_claim_token_cannot_release_replacement_claim(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    first = database.claim_analysis(
        int(flight["id"]),
        "tenant-1",
        expected_status="Completed",
    )
    assert first is not None
    assert database.update_status(
        int(flight["id"]),
        "Failed",
        tenant_id="tenant-1",
        expected_current_status="Processing",
        expected_claim_token=first["analysis_claim_token"],
    )
    second = database.claim_analysis(
        int(flight["id"]),
        "tenant-1",
        expected_status="Failed",
    )
    assert second is not None
    assert second["analysis_claim_token"] != first["analysis_claim_token"]

    assert not database.restore_analysis_state(
        int(flight["id"]),
        "Completed",
        flight["notes"],
        flight["last_error"],
        tenant_id="tenant-1",
        analysis_failure_category=flight["analysis_failure_category"],
        expected_current_status="Processing",
        expected_claim_token=first["analysis_claim_token"],
    )
    current = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert current is not None
    assert current["status"] == "Processing"
    assert current["analysis_claim_token"] == second["analysis_claim_token"]
    assert database.restore_analysis_state(
        int(flight["id"]),
        "Failed",
        second["notes"],
        second["last_error"],
        tenant_id="tenant-1",
        analysis_failure_category=second["analysis_failure_category"],
        expected_current_status="Processing",
        expected_claim_token=second["analysis_claim_token"],
    )


def test_surface_overlays_are_tenant_scoped_embedded_and_preserved(
    service_app: TestClient,
) -> None:
    owner_headers = _authorization("tenant-owner", "pilot-owner")
    other_headers = _authorization("tenant-other", "pilot-other")
    created = service_app.post(
        "/v1/analyses",
        headers=owner_headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = created.json()["flight"]
    overlays = [
        _surface_contract(flight["departure"], "departure"),
        _surface_contract(flight["destination"], "destination"),
    ]
    overlays[0]["reviewRequired"] = [{
        "notamNumber": "SX68/26",
        "entityType": "taxiway",
        "entityRef": "W9/W/R",
        "scope": "ambiguous",
        "plainEnglish": "The uploaded and reviewed publication times conflict.",
        "evidence": "Uploaded 1430Z; reviewed source 1730Z.",
        "sourceConflict": {
            "publicationId": "SUP 068/2026",
            "sourceUrl": "https://aim-sg.caas.gov.sg/example",
            "checkedAt": "2026-08-01T00:00:00.000Z",
            "conflictingFields": ["startsAt"],
            "uploaded": {
                "startsAt": "2026-05-14T14:30:00.000Z",
                "endsAt": "2026-10-01T21:30:00.000Z",
            },
            "reviewed": {
                "startsAt": "2026-05-14T17:30:00.000Z",
                "endsAt": "2026-10-01T21:30:00.000Z",
            },
        },
    }]
    overlays[0]["counts"]["reviewRequired"] = 1
    airport_surface_index = [
        {
            "icao": flight["departure"],
            "name": "Departure test airport",
            "roles": ["departure"],
            "roleLabel": "Departure",
            "stationStatus": "held",
            "sourceLabel": "Uploaded OFP station package",
            "window": {
                "startsAt": "2026-07-11T09:42:00Z",
                "endsAt": "2026-07-11T11:42:00Z",
                "referenceAt": "2026-07-11T10:42:00Z",
                "referenceBasis": "departure",
            },
            "notamCount": 1,
            "notes": {
                "status": "unavailable",
                "message": "AIRPORT NOTES UNAVAILABLE — REVIEW REQUIRED",
                "releaseStatus": None,
                "airportVersion": None,
                "cycle": None,
                "schemaVersion": None,
                "objects": [],
                "lines": [],
                "omittedLineCount": 0,
            },
        },
        {
            "icao": flight["destination"],
            "name": "Destination test airport",
            "roles": ["destination"],
            "roleLabel": "Destination",
            "stationStatus": "held",
            "sourceLabel": "Uploaded OFP station package",
            "window": {
                "startsAt": "2026-07-11T19:00:00Z",
                "endsAt": "2026-07-11T21:00:00Z",
                "referenceAt": "2026-07-11T20:00:00Z",
                "referenceBasis": "destination",
            },
            "notamCount": 2,
            "notes": {
                "status": "released",
                "message": "RELEASED AIRPORT NOTES — EXACT PACKAGE VALUES",
                "releaseStatus": "released",
                "airportVersion": "TEST-2607-1",
                "cycle": "2607",
                "schemaVersion": "1",
                "objects": [
                    {"name": "ops.json", "sha256": "a" * 64},
                ],
                "lines": [
                    {
                        "sourceObject": "ops.json",
                        "path": "surface.caution",
                        "value": "Exact released test note.",
                    },
                ],
                "omittedLineCount": 0,
            },
        },
    ]

    cross_tenant = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=other_headers,
        json={"overlays": overlays},
    )
    assert cross_tenant.status_code == 404

    invalid = _surface_contract("WADD", "departure")
    rejected = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={"overlays": [invalid]},
    )
    assert rejected.status_code == 422

    published = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={
            "overlays": overlays,
            "airport_surface_index": airport_surface_index,
        },
    )
    assert published.status_code == 200
    published_overlays = published.json()["surface_overlays"]
    assert [item["role"] for item in published_overlays] == [
        "departure",
        "destination",
    ]
    assert all(
        item["report_map"]["mode"] == "schematic-fallback"
        for item in published_overlays
    )
    assert published.json()["airport_surface_index"] == airport_surface_index

    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert len(briefing["flight"]["surface_overlays"]) == 2
    assert briefing["flight"]["airport_surface_index"] == airport_surface_index
    assert (
        briefing["briefing"]["airport_surface_index"]
        == airport_surface_index
    )
    source_conflict = briefing["flight"]["surface_overlays"][0][
        "reviewRequired"
    ][0]["sourceConflict"]
    assert source_conflict["publicationId"] == "SUP 068/2026"
    assert source_conflict["conflictingFields"] == ["startsAt"]

    level1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=owner_headers,
    )
    document = fitz.open(stream=level1.content, filetype="pdf")
    try:
        text = "\n".join(page.get_text() for page in document)
        assert document.page_count == 3
    finally:
        document.close()
    assert "Surface overlay: 1 exact closure mark." in " ".join(text.split())
    assert "Closed: TAXIWAY S2" in text
    assert "CAAS SUP 068/2026" in text

    level2 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-2",
        headers=owner_headers,
    )
    level2_document = fitz.open(stream=level2.content, filetype="pdf")
    try:
        level2_text = "\n".join(page.get_text() for page in level2_document)
        assert level2_document.page_count == 7
    finally:
        level2_document.close()
    assert "active closures" in level2_text
    assert "CAAS SUP 068/2026" in level2_text
    assert "1430Z" in level2_text
    assert "1730Z" in level2_text
    assert "review required" in level2_text

    timing = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=owner_headers,
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    assert timing.status_code == 200
    overlays[0]["window"]["basis"] = "actual_takeoff"
    overlays[1]["window"]["basis"] = (
        "calculated_destination_from_atot_and_cfp_actm"
    )
    republished = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={"overlays": overlays},
    )
    assert republished.status_code == 200
    assert [
        item["window"]["basis"]
        for item in republished.json()["surface_overlays"]
    ] == [
        "actual_takeoff",
        "calculated_destination_from_atot_and_cfp_actm",
    ]
    # This request intentionally models an older cached app bundle that knows
    # only the overlay field. Omission must preserve the governed airport index.
    assert republished.json()["airport_surface_index"] == airport_surface_index
    refreshed = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert len(refreshed["flight"]["surface_overlays"]) == 2

    accidental_clear = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={},
    )
    cross_tenant_clear = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=other_headers,
        json={"overlays": []},
    )
    assert accidental_clear.status_code == 422
    assert cross_tenant_clear.status_code == 404

    cleared = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={"overlays": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["surface_overlays"] == []
    assert cleared.json()["airport_surface_index"] == airport_surface_index

    cleared_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert cleared_briefing["flight"]["surface_overlays"] == []
    assert (
        cleared_briefing["briefing"]["airport_surface_index"]
        == airport_surface_index
    )

    explicit_index_clear = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=owner_headers,
        json={"overlays": [], "airport_surface_index": []},
    )
    assert explicit_index_clear.status_code == 200
    assert explicit_index_clear.json()["airport_surface_index"] == []
    explicitly_cleared_briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert explicitly_cleared_briefing["flight"]["airport_surface_index"] == []
    assert explicitly_cleared_briefing["briefing"]["airport_surface_index"] == []

    cleared_level1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=owner_headers,
    )
    cleared_document = fitz.open(stream=cleared_level1.content, filetype="pdf")
    try:
        cleared_text = "\n".join(page.get_text() for page in cleared_document)
        assert cleared_document.page_count == 3
    finally:
        cleared_document.close()
    assert "Closed: TAXIWAY S2" not in cleared_text
    assert "exact closure mark" not in cleared_text

    cleared_level2 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-2",
        headers=owner_headers,
    )
    cleared_level2_document = fitz.open(
        stream=cleared_level2.content,
        filetype="pdf",
    )
    try:
        cleared_level2_text = "\n".join(
            page.get_text()
            for page in cleared_level2_document
        )
        assert cleared_level2_document.page_count == 7
    finally:
        cleared_level2_document.close()
    assert "active closures" not in cleared_level2_text


def test_processing_claim_blocks_weather_surface_and_map_report_writers(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    artifact_paths = {
        field: Path(str(flight[field]))
        for field in ("analysis_path", "level1_report", "level2_report")
    }
    artifact_bytes = {field: path.read_bytes() for field, path in artifact_paths.items()}
    publish_calls = 0
    original_publish = main._publish_surface_overlay_reports

    def counted_publish(*args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(main, "_publish_surface_overlay_reports", counted_publish)
    claimed = database.claim_analysis(int(flight["id"]), "tenant-1")
    assert claimed is not None
    try:
        weather = service_app.post(
            f"/v1/analyses/{analysis_id}/weather-window",
            headers=_authorization(),
            json={"before_minutes": 120, "after_minutes": 90},
        )
        surface = service_app.post(
            f"/v1/analyses/{analysis_id}/surface-overlays",
            headers=_authorization(),
            json={
                "overlays": [
                    _surface_contract(created.json()["flight"]["departure"], "departure"),
                    _surface_contract(
                        created.json()["flight"]["destination"],
                        "destination",
                    ),
                ]
            },
        )
        rendered = service_app.post(
            f"/v1/analyses/{analysis_id}/reports/render",
            headers=_authorization(),
        )
    finally:
        database.restore_analysis_state(
            int(flight["id"]),
            str(claimed["status"]),
            claimed["notes"],
            claimed["last_error"],
            tenant_id="tenant-1",
        )

    assert weather.status_code == 409
    assert surface.status_code == 409
    assert rendered.status_code == 409
    assert publish_calls == 0
    for field, path in artifact_paths.items():
        assert path.read_bytes() == artifact_bytes[field]


def test_surface_overlay_publication_rolls_back_all_artifacts_on_rename_failure(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    flight = database.get_flight_by_analysis_id(
        created.json()["analysis_id"],
        "tenant-1",
    )
    assert flight is not None
    analysis = main.load_analysis(flight["analysis_path"])
    assert analysis is not None
    destinations = {
        "analysis": Path(str(flight["analysis_path"])),
        "level1": Path(str(flight["level1_report"])),
        "level2": Path(str(flight["level2_report"])),
    }
    prior_bytes = {
        name: path.read_bytes()
        for name, path in destinations.items()
    }

    def render_replacement(
        _flight, _findings, _warnings, level, destination, **_kwargs
    ):
        destination.write_bytes(f"replacement-level-{level}".encode())

    monkeypatch.setattr(main, "render_pdf", render_replacement)
    original_replace = Path.replace
    injected = False

    def fail_analysis_publication(self: Path, target):
        nonlocal injected
        if Path(target) == destinations["analysis"] and not injected:
            injected = True
            raise OSError("Synthetic surface analysis publication failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_analysis_publication)

    with pytest.raises(
        OSError,
        match="Synthetic surface analysis publication failure",
    ):
        main._publish_surface_overlay_reports(flight, analysis, [])

    assert injected is True
    for name, path in destinations.items():
        assert path.read_bytes() == prior_bytes[name]
    assert list(main.RESULT_DIR.glob("*.surface.tmp")) == []
    assert list(main.REPORT_DIR.glob("*.surface.tmp")) == []
    assert list(main.RESULT_DIR.glob("*.publication-backup-*")) == []
    assert list(main.REPORT_DIR.glob("*.publication-backup-*")) == []


def test_report_worker_endpoint_preserves_labelled_schematic_fallback(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    ).json()
    analysis_id = created["analysis_id"]

    rendered = service_app.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=_authorization(),
    )

    assert rendered.status_code == 200
    map_render = rendered.json()["map_render"]
    assert map_render["mode"] == "schematic-fallback"
    assert map_render["reports_refreshed"] is False
    assert "Schematic route display" in map_render["label"]
    assert Path(map_render["artifact_path"]).is_file()
    assert rendered.json()["report_refresh"] == {
        "state": "current",
        "reports_current": True,
        "warning": None,
    }


def test_schematic_report_worker_does_not_promote_stale_reports(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    ).json()
    analysis_id = created["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    database.set_report_refresh_state(
        int(flight["id"]),
        "failed",
        error_type="SyntheticStaleReports",
        tenant_id="tenant-1",
    )

    rendered = service_app.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=_authorization(),
    )

    assert rendered.status_code == 200
    assert rendered.json()["map_render"]["reports_refreshed"] is False
    assert rendered.json()["report_refresh"]["state"] == "failed"
    assert service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=_authorization(),
    ).status_code == 409


def test_report_retry_does_not_embed_the_resolved_failure_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    retry_warning = "Stored reports are stale; retry report generation."
    analysis = {
        "flight": {},
        "findings": [],
        "view": {
            "warnings": ["Operational warning", retry_warning],
            "report_refresh": {"state": "failed", "warning": retry_warning},
        },
    }
    rendered_warnings: list[list[str]] = []

    def capture_render(_flight, _findings, warnings, level, destination, **_kwargs):
        rendered_warnings.append(list(warnings))
        destination.write_bytes(f"level-{level}".encode())

    monkeypatch.setattr(report_worker, "render_pdf", capture_render)
    level1 = tmp_path / "level-1.pdf"
    level2 = tmp_path / "level-2.pdf"
    level1.write_bytes(b"old-level-1")
    level2.write_bytes(b"old-level-2")

    refreshed = report_worker._regenerate_reports(
        analysis=analysis,
        level1_path=level1,
        level2_path=level2,
        map_result=MapRenderResult(
            provider="test",
            mode="primary",
            content=b"png",
            media_type="image/png",
            label="Test map",
        ),
        map_path=tmp_path / "map.png",
    )

    assert refreshed is True
    assert rendered_warnings == [["Operational warning"], ["Operational warning"]]
    assert level1.read_bytes() == b"level-1"
    assert level2.read_bytes() == b"level-2"


def test_report_retry_publishes_neither_pdf_when_level_two_render_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    def fail_second_render(_flight, _findings, _warnings, level, destination, **_kwargs):
        destination.write_bytes(f"new-level-{level}".encode())
        if level == 2:
            raise ValueError("Synthetic level 2 report failure")

    monkeypatch.setattr(report_worker, "render_pdf", fail_second_render)
    level1 = tmp_path / "level-1.pdf"
    level2 = tmp_path / "level-2.pdf"
    level1.write_bytes(b"old-level-1")
    level2.write_bytes(b"old-level-2")

    with pytest.raises(ValueError, match="Synthetic level 2 report failure"):
        report_worker._regenerate_reports(
            analysis={"flight": {}, "findings": [], "view": {}},
            level1_path=level1,
            level2_path=level2,
            map_result=MapRenderResult(
                provider="test",
                mode="primary",
                content=b"png",
                media_type="image/png",
                label="Test map",
            ),
            map_path=tmp_path / "map.png",
        )

    assert level1.read_bytes() == b"old-level-1"
    assert level2.read_bytes() == b"old-level-2"
    assert list(tmp_path.glob("*.map.tmp")) == []


def test_report_publication_rolls_back_the_complete_artifact_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    def render_new_reports(
        _flight, _findings, _warnings, level, destination, **_kwargs
    ):
        destination.write_bytes(f"new-level-{level}".encode())

    monkeypatch.setattr(report_worker, "render_pdf", render_new_reports)
    level1 = tmp_path / "level-1.pdf"
    level2 = tmp_path / "level-2.pdf"
    map_destination = tmp_path / "route-map.png"
    map_staged = tmp_path / ".route-map.stage.png"
    analysis_destination = tmp_path / "analysis.json"
    level1.write_bytes(b"old-level-1")
    level2.write_bytes(b"old-level-2")
    map_destination.write_bytes(b"old-map")
    map_staged.write_bytes(b"new-map")
    analysis_destination.write_bytes(b'{"version":"old"}')

    original_replace = Path.replace
    injected = False

    def fail_analysis_publication(self: Path, target):
        nonlocal injected
        if Path(target) == analysis_destination and not injected:
            injected = True
            raise OSError("Synthetic analysis JSON publication failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_analysis_publication)

    with pytest.raises(
        OSError,
        match="Synthetic analysis JSON publication failure",
    ):
        report_worker._regenerate_reports(
            analysis={"flight": {}, "findings": [], "view": {}},
            level1_path=level1,
            level2_path=level2,
            map_result=MapRenderResult(
                provider="test",
                mode="primary",
                content=b"png",
                media_type="image/png",
                label="Test map",
            ),
            map_path=map_staged,
            additional_staged_artifacts=[(map_staged, map_destination)],
            additional_json_artifacts=[
                ({"version": "new"}, analysis_destination)
            ],
        )

    assert level1.read_bytes() == b"old-level-1"
    assert level2.read_bytes() == b"old-level-2"
    assert map_destination.read_bytes() == b"old-map"
    assert analysis_destination.read_bytes() == b'{"version":"old"}'
    assert not map_staged.exists()
    assert list(tmp_path.glob("*.publication-stage-*")) == []
    assert list(tmp_path.glob("*.publication-backup-*")) == []


def test_report_publication_stages_analysis_before_replacing_any_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    def render_new_reports(
        _flight, _findings, _warnings, level, destination, **_kwargs
    ):
        destination.write_bytes(f"new-level-{level}".encode())

    monkeypatch.setattr(report_worker, "render_pdf", render_new_reports)
    level1 = tmp_path / "level-1.pdf"
    level2 = tmp_path / "level-2.pdf"
    map_destination = tmp_path / "route-map.png"
    map_staged = tmp_path / ".route-map.stage.png"
    analysis_destination = tmp_path / "analysis.json"
    level1.write_bytes(b"old-level-1")
    level2.write_bytes(b"old-level-2")
    map_destination.write_bytes(b"old-map")
    map_staged.write_bytes(b"new-map")
    analysis_destination.write_bytes(b'{"version":"old"}')

    original_write_text = Path.write_text

    def fail_analysis_staging(self: Path, data: str, *args, **kwargs):
        if self.name.startswith(
            f".{analysis_destination.name}.publication-stage-"
        ):
            raise OSError("Synthetic analysis JSON staging failure")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_analysis_staging)

    with pytest.raises(OSError, match="Synthetic analysis JSON staging failure"):
        report_worker._regenerate_reports(
            analysis={"flight": {}, "findings": [], "view": {}},
            level1_path=level1,
            level2_path=level2,
            map_result=MapRenderResult(
                provider="test",
                mode="primary",
                content=b"png",
                media_type="image/png",
                label="Test map",
            ),
            map_path=map_staged,
            additional_staged_artifacts=[(map_staged, map_destination)],
            additional_json_artifacts=[
                ({"version": "new"}, analysis_destination)
            ],
        )

    assert level1.read_bytes() == b"old-level-1"
    assert level2.read_bytes() == b"old-level-2"
    assert map_destination.read_bytes() == b"old-map"
    assert analysis_destination.read_bytes() == b'{"version":"old"}'
    assert not map_staged.exists()
    assert list(tmp_path.glob("*.map.tmp")) == []
    assert list(tmp_path.glob("*.publication-stage-*")) == []
    assert list(tmp_path.glob("*.publication-backup-*")) == []


def test_report_worker_embeds_primary_png_and_refreshes_reports(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    ).json()
    analysis_id = created["analysis_id"]

    # Generate a valid PNG so ReportLab/Pillow exercise the real embedding path.
    png_buffer = BytesIO()
    Image.new("RGB", (8, 8), "navy").save(png_buffer, format="PNG")
    png = png_buffer.getvalue()

    class FakeRenderer:
        name = "test-primary"

        async def render_snapshot(self, contract, *, width, height):
            return MapRenderResult(
                provider=self.name,
                mode="primary",
                content=png,
                media_type="image/png",
                label="Test realistic map",
                metadata={"route_hash": contract.route_hash},
            )

    monkeypatch.setattr(
        report_worker,
        "_renderers",
        lambda settings, **_identity: [FakeRenderer()],
    )
    rendered = service_app.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=_authorization(),
    )

    assert rendered.status_code == 200
    metadata = rendered.json()["map_render"]
    assert metadata["mode"] == "primary"
    assert metadata["reports_refreshed"] is True
    assert Path(metadata["artifact_path"]).read_bytes() == png

    level1 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=_authorization(),
    )
    level2 = service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-2",
        headers=_authorization(),
    )
    assert level1.content.startswith(b"%PDF")
    assert level2.content.startswith(b"%PDF")


def test_report_worker_cli_claims_and_finalizes_stale_report_retry(
    service_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.odss_map_v06.renderers import MapRenderResult

    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    database.set_report_refresh_state(
        int(flight["id"]),
        "failed",
        error_type="SyntheticStaleReports",
        tenant_id="tenant-1",
    )
    analysis_path = Path(str(flight["analysis_path"]))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis.setdefault("view", {}).setdefault("warnings", []).append(
        main.REPORT_REFRESH_WARNING
    )
    analysis["view"]["report_refresh"] = {
        "state": "failed",
        "reports_current": False,
        "warning": main.REPORT_REFRESH_WARNING,
    }
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    png_buffer = BytesIO()
    Image.new("RGB", (8, 8), "navy").save(png_buffer, format="PNG")
    png = png_buffer.getvalue()

    class FakeRenderer:
        name = "test-cli-primary"

        async def render_snapshot(self, contract, *, width, height):
            return MapRenderResult(
                provider=self.name,
                mode="primary",
                content=png,
                media_type="image/png",
                label="Test CLI map",
                metadata={"route_hash": contract.route_hash},
            )

    monkeypatch.setattr(
        report_worker,
        "_renderers",
        lambda settings, **_identity: [FakeRenderer()],
    )
    monkeypatch.setattr(
        report_worker,
        "_parse_args",
        lambda: SimpleNamespace(
            analysis_id=analysis_id,
            tenant_id="tenant-1",
            user_id="pilot-7",
            width=1600,
            height=900,
        ),
    )

    assert report_worker.main() == 0

    refreshed = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert refreshed is not None
    assert refreshed["status"] == "Completed"
    assert refreshed["report_refresh_state"] == "current"
    assert refreshed["report_refresh_error_type"] is None
    refreshed_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert refreshed_analysis["view"]["report_refresh"] == {
        "state": "current",
        "reports_current": True,
        "warning": None,
    }
    assert main.REPORT_REFRESH_WARNING not in refreshed_analysis["view"]["warnings"]
    assert service_app.get(
        f"/v1/analyses/{analysis_id}/reports/level-1",
        headers=_authorization(),
    ).status_code == 200


def test_service_analysis_is_hidden_from_another_tenant_on_every_surface(
    service_app: TestClient,
) -> None:
    owner_headers = _authorization("tenant-owner", "pilot-owner")
    other_headers = _authorization("tenant-other", "pilot-other")
    created = service_app.post(
        "/v1/analyses",
        headers=owner_headers,
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    owner_row = database.get_flight_by_analysis_id(analysis_id, "tenant-owner")
    assert owner_row is not None
    original_timing = owner_row["actual_takeoff_utc"]

    read_paths = [
        f"/v1/analyses/{analysis_id}",
        f"/v1/analyses/{analysis_id}/briefing",
        f"/v1/analyses/{analysis_id}/map-contract",
        f"/v1/analyses/{analysis_id}/route.geojson",
        f"/v1/analyses/{analysis_id}/markers.geojson",
        f"/v1/analyses/{analysis_id}/hazards.geojson",
        f"/v1/analyses/{analysis_id}/map-config",
        f"/v1/analyses/{analysis_id}/map-fallback",
        f"/v1/analyses/{analysis_id}/reports/level-1",
        f"/v1/analyses/{analysis_id}/reports/level-2",
        f"/v1/analyses/{analysis_id}/level-3",
        f"/v1/analyses/{analysis_id}/reports/level-3",
        f"/render/maps/{analysis_id}",
    ]
    for path in read_paths:
        response = service_app.get(path, headers=other_headers)
        assert response.status_code == 404, path

    timing = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=other_headers,
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    render = service_app.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=other_headers,
    )
    surface = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=other_headers,
        json={
            "overlays": [
                _surface_contract(
                    created.json()["flight"]["departure"],
                    "departure",
                )
            ],
        },
    )
    assert timing.status_code == 404
    assert render.status_code == 404
    assert surface.status_code == 404
    with pytest.raises(LookupError):
        database.save_timing_reference(
            int(owner_row["id"]),
            "2026-07-11T10:42:00+00:00",
            "takeoff",
            "2026-07-11T10:42:00+00:00",
            tenant_id="tenant-other",
        )

    unchanged = database.get_flight_by_analysis_id(analysis_id, "tenant-owner")
    assert unchanged is not None
    assert unchanged["actual_takeoff_utc"] == original_timing
    assert database.get_flight_by_analysis_id(analysis_id, "tenant-other") is None


def test_governed_profile_chart_route_serves_only_held_validated_report_page(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    assert "profile_charts" in created.json()["links"]

    flight = database.get_flight_by_analysis_id(analysis_id, "tenant-1")
    assert flight is not None
    analysis_path = Path(str(flight["analysis_path"]))
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    artifact = {
        "chart_number": "8-7",
        "source_document": "Controlled depressurisation profiles",
        "source_revision": "2026-07-01",
        "source_page": 19,
        "source_link": "controlled-library/profile/8-7",
        "route_airway_match_verified": True,
        "aircraft_effectivity_verified": True,
        "chart_image_validated": True,
        "level1_analysis_chart_embedded": True,
        "level1_report_page": 3,
        "level2_full_source_chart_embedded": True,
        "level2_report_page": 1,
    }
    payload.setdefault("flight", {})["depressurisation_profile_charts"] = [artifact]
    analysis_path.write_text(json.dumps(payload), encoding="utf-8")

    chart = service_app.get(
        f"/v1/analyses/{analysis_id}/profile-charts/8-7",
        headers=_authorization(),
    )
    assert chart.status_code == 200
    assert chart.headers["content-type"] == "image/png"
    assert chart.headers["cache-control"] == "no-store"
    assert chart.content.startswith(b"\x89PNG\r\n\x1a\n")

    claimed = database.claim_analysis(int(flight["id"]), "tenant-1")
    assert claimed is not None
    try:
        assert service_app.get(
            f"/v1/analyses/{analysis_id}/profile-charts/8-7",
            headers=_authorization(),
        ).status_code == 409
        assert service_app.get(
            f"/v1/analyses/{analysis_id}/reports/level-2",
            headers=_authorization(),
        ).status_code == 409
    finally:
        database.restore_analysis_state(
            int(flight["id"]),
            str(claimed["status"]),
            claimed["notes"],
            claimed["last_error"],
            tenant_id="tenant-1",
            analysis_failure_category=claimed["analysis_failure_category"],
        )

    database.set_report_refresh_state(
        int(flight["id"]),
        "failed",
        error_type="SyntheticStaleReports",
        tenant_id="tenant-1",
    )
    assert service_app.get(
        f"/v1/analyses/{analysis_id}/profile-charts/8-7",
        headers=_authorization(),
    ).status_code == 409
    database.set_report_refresh_state(
        int(flight["id"]),
        "current",
        tenant_id="tenant-1",
    )

    unknown = service_app.get(
        f"/v1/analyses/{analysis_id}/profile-charts/10-4",
        headers=_authorization(),
    )
    assert unknown.status_code == 404
    other_tenant = service_app.get(
        f"/v1/analyses/{analysis_id}/profile-charts/8-7",
        headers=_authorization(tenant_id="tenant-2"),
    )
    assert other_tenant.status_code == 404

    payload["flight"]["depressurisation_profile_charts"][0][
        "aircraft_effectivity_verified"
    ] = False
    analysis_path.write_text(json.dumps(payload), encoding="utf-8")
    unverified = service_app.get(
        f"/v1/analyses/{analysis_id}/profile-charts/8-7",
        headers=_authorization(),
    )
    assert unverified.status_code == 404
