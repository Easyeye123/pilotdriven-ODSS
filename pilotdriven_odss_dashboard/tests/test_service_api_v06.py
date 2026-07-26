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
            "basis": "filed-std-sta",
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
        json={"overlays": overlays},
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

    briefing = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert len(briefing["flight"]["surface_overlays"]) == 2

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
    assert "Surface overlay: 1 exact closure mark." in text
    assert "Closed: TAXIWAY S2" in text

    timing = service_app.post(
        f"/v1/analyses/{analysis_id}/timing",
        headers=owner_headers,
        json={
            "reference_type": "takeoff",
            "reference_utc": "2026-07-11T10:42:00+00:00",
        },
    )
    assert timing.status_code == 200
    refreshed = service_app.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=owner_headers,
    ).json()
    assert len(refreshed["flight"]["surface_overlays"]) == 2


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
