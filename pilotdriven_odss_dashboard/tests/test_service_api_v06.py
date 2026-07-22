from __future__ import annotations

import sys
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database
import app.main as main
import app.odss_map_v06.report_worker as report_worker


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
    monkeypatch.setenv("ODSS_SERVICE_TOKEN", "service-test-token")
    monkeypatch.delenv("AWS_LOCATION_API_KEY", raising=False)
    with TestClient(main.app, follow_redirects=False) as client:
        yield client


def _authorization() -> dict[str, str]:
    return {"Authorization": "Bearer service-test-token"}


def test_service_api_requires_bearer_token(service_app: TestClient) -> None:
    anonymous = service_app.get("/v1/health")
    authorized = service_app.get("/v1/health", headers=_authorization())

    assert anonymous.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["version"] == "0.6.1"
    assert authorized.json()["map_contract"] == "1.1"



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

    assert anonymous.status_code == 401
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
    assert len(database.list_flights()) == 1


def test_service_timing_accepts_atot_and_rejects_unknown_reference(
    service_app: TestClient,
) -> None:
    created = service_app.post(
        "/v1/analyses",
        headers=_authorization(),
        files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    ).json()
    analysis_id = created["analysis_id"]

    updated = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=_authorization(),
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
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
    assert briefing["timing"]["actual_takeoff_utc"] == "2026-07-11T10:42:00+00:00"


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

    monkeypatch.setattr(report_worker, "_renderers", lambda settings: [FakeRenderer()])
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
