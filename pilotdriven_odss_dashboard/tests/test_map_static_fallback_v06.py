from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss_map_v06.aws_location import (
    AwsLocationStaticRenderer,
    _bounding_box,
    _simplify_route_geometry,
    _static_overlay,
)
from app.odss_map_v06.contract import MapBounds, MapContract
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.renderers import MapRenderError, MapRenderResult, RendererChain
from app.odss_map_v06.snapshot import (
    PlaywrightMapSnapshotRenderer,
    _chromium_launch_args,
    _request_headers_for_url,
)


def _contract(point_count: int = 160) -> MapContract:
    coordinates = [
        [1.0 + index * 0.45, -12.0 + index * 0.18]
        for index in range(point_count)
    ]
    markers = [
        {
            "type": "Feature",
            "id": f"wp-{index:04d}",
            "geometry": {"type": "Point", "coordinates": coordinate},
            "properties": {
                "name": f"P{index:03d}",
                "role": "departure" if index == 0 else "destination" if index == point_count - 1 else "route",
                "priority": 100 if index in {0, point_count - 1} else 0,
            },
        }
        for index, coordinate in enumerate(coordinates)
    ]
    return MapContract(
        route_hash="a" * 64,
        route_geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "planned-route",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {},
                }
            ],
        },
        markers_geojson={"type": "FeatureCollection", "features": markers},
        bounds=MapBounds(west=0, south=-15, east=75, north=20),
        priority_labels=["P000", f"P{point_count - 1:03d}"],
    )


def test_static_overlay_is_simplified_under_aws_budget() -> None:
    contract = _contract()
    overlay = _static_overlay(
        contract,
        marker_limit=12,
        route_point_limit=80,
    )
    encoded = json.dumps(overlay, separators=(",", ":"), ensure_ascii=True)
    route = overlay["features"][0]["geometry"]["coordinates"]

    assert len(encoded) <= 4200
    assert len(route) == 80
    assert route[0] == contract.route_geojson["features"][0]["geometry"]["coordinates"][0]
    assert route[-1] == contract.route_geojson["features"][0]["geometry"]["coordinates"][-1]
    assert _bounding_box(contract) == "0.000000,-15.000000,75.000000,20.000000"


def test_multiline_simplification_preserves_each_segment_endpoints() -> None:
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[float(index), 0.0] for index in range(20)],
            [[100.0 + float(index), 1.0] for index in range(20)],
        ],
    }
    simplified = _simplify_route_geometry(geometry, max_points=12)

    assert simplified["type"] == "MultiLineString"
    assert simplified["coordinates"][0][0] == [0.0, 0.0]
    assert simplified["coordinates"][0][-1] == [19.0, 0.0]
    assert simplified["coordinates"][1][0] == [100.0, 1.0]
    assert simplified["coordinates"][1][-1] == [119.0, 1.0]


def test_static_map_uses_separate_server_key_with_single_key_compatibility() -> None:
    split = MapSettings(
        aws_location_api_key="browser-referrer-key",
        aws_location_server_api_key="server-static-key",
    )
    legacy = MapSettings(aws_location_api_key="legacy-map-key")

    assert split.style_descriptor_url.endswith("?key=browser-referrer-key")
    assert split.static_map_api_key == "server-static-key"
    assert legacy.style_descriptor_url.endswith("?key=legacy-map-key")
    assert legacy.static_map_api_key == "legacy-map-key"


def test_static_renderer_sends_only_server_key(
    monkeypatch,
) -> None:
    requested: list[str] = []

    class FakeResponse:
        status_code = 200
        content = b"jpeg-data"
        headers = {"content-type": "image/jpeg"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr(
        "app.odss_map_v06.aws_location.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    renderer = AwsLocationStaticRenderer(
        MapSettings(
            aws_location_api_key="browser-referrer-key",
            aws_location_server_api_key="server-static-key",
        )
    )

    result = asyncio.run(renderer.render_snapshot(_contract(4), width=800, height=450))

    assert result.mode == "static-fallback"
    assert len(requested) == 1
    assert "server-static-key" in requested[0]
    assert "browser-referrer-key" not in requested[0]
    assert "width=700" in requested[0]
    assert "height=450" in requested[0]
    assert "pois=" not in requested[0]
    assert "crop-labels=" not in requested[0]
    assert "lang=" not in requested[0]


def test_print_capture_sends_service_bearer_only_to_internal_origin() -> None:
    settings = MapSettings(
        print_base_url="https://odss.internal.example",
        service_token="internal-service-token",
    )

    internal = _request_headers_for_url(
        "https://odss.internal.example/static/map.js",
        {"accept": "*/*"},
        settings,
    )
    external = _request_headers_for_url(
        "https://maps.geo.ap-southeast-2.amazonaws.com/v2/tiles/1/1/1",
        {"accept": "*/*", "authorization": "Bearer stale"},
        settings,
    )

    assert internal["authorization"] == "Bearer internal-service-token"
    assert "authorization" not in external


def test_print_capture_enables_software_webgl_for_gpu_less_workers() -> None:
    launch_args = _chromium_launch_args()

    assert "--use-gl=angle" in launch_args
    assert "--use-angle=swiftshader-webgl" in launch_args
    assert "--enable-unsafe-swiftshader" in launch_args
    assert "--disable-gpu" not in launch_args


def test_print_capture_checks_loaded_map_state_when_idle_callback_is_delayed() -> None:
    source = inspect.getsource(PlaywrightMapSnapshotRenderer.render_snapshot)

    assert "window.__ODSS_MAP_INSTANCE__" in source
    assert "map.isStyleLoaded()" in source
    assert "map.areTilesLoaded()" in source
    assert "Rendered map route hash does not match the contract" in source


def test_renderer_chain_redacts_keys_from_persisted_warnings() -> None:
    class FailedRenderer:
        name = "failed-primary"

        async def render_snapshot(self, contract, *, width, height):
            raise MapRenderError(
                "Failed https://maps.example/tile?key=browser-secret-value&x=1"
            )

    class SuccessfulRenderer:
        name = "safe-fallback"

        async def render_snapshot(self, contract, *, width, height):
            return MapRenderResult(
                provider=self.name,
                mode="static-fallback",
                content=b"image",
                media_type="image/jpeg",
                label="Safe fallback",
            )

    result = asyncio.run(
        RendererChain(FailedRenderer(), SuccessfulRenderer()).render_snapshot(
            _contract(4),
            width=800,
            height=450,
        )
    )

    assert "browser-secret-value" not in str(result.warnings)
    assert "key=[redacted]" in str(result.warnings)


@pytest.mark.parametrize("region", ["ap-southeast-1", "ap-southeast-5"])
@pytest.mark.parametrize(
    ("style", "fallback"),
    [("Hybrid", "schematic"), ("Satellite", "schematic"), ("Standard", "static")],
)
def test_hybrid_and_static_fallback_reject_grabmaps_regions(
    region: str,
    style: str,
    fallback: str,
) -> None:
    settings = MapSettings(aws_region=region, style=style, fallback=fallback)

    with pytest.raises(ValueError, match="Hybrid/Satellite maps are unavailable"):
        settings.validate()
