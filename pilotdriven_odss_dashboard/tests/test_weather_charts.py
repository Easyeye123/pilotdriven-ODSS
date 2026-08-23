"""Weather-chart appendix: detection, AI classification, and fail-closed holds."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import app.odss.weather_charts as weather_charts
import pytest
from app.odss.weather_charts import (
    build_weather_chart_manifest,
    detect_chart_appendix,
    parse_chart_ocr_identity,
)


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _FakeImage:
    def __init__(self, data: bytes):
        self.data = data


class _FakePage:
    def __init__(self, text: str, images: list[bytes]):
        self._text = text
        self.images = [_FakeImage(item) for item in images]

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, path):
        self.pages = _FAKE_PAGES


_CHART_IMAGE = PNG_MAGIC + b"\x00" * (40 * 1024)
_LOGO_IMAGE = PNG_MAGIC + b"\x00" * (2 * 1024)
_FAKE_PAGES = [
    _FakePage("OPERATIONAL FLIGHT PLAN\n" + "ROUTE TEXT " * 200, []),          # text page
    _FakePage("Page 2 of 4", [_LOGO_IMAGE]),                                    # small logo only
    _FakePage("Page 3 of 4", [_CHART_IMAGE]),                                   # chart page
    _FakePage("", [_CHART_IMAGE + b"\x11"]),                                    # chart page, no text
]


def _patch_reader(monkeypatch):
    monkeypatch.setattr(weather_charts, "PdfReader", _FakeReader)
    monkeypatch.setattr(
        weather_charts,
        "_ocr_chart_image",
        lambda _image, _deadline=None: {"ocr_status": "unavailable:test"},
    )


def test_detection_finds_raster_pages_without_fixed_numbers(monkeypatch):
    _patch_reader(monkeypatch)
    found = detect_chart_appendix("ignored.pdf")
    assert [item["page_number"] for item in found] == [3, 4]
    assert all(item["media_type"] == "image/png" for item in found)
    assert found[0]["image_sha256"] != found[1]["image_sha256"]


def test_detection_keeps_large_compressed_chart_below_byte_threshold(monkeypatch):
    class _Raster:
        size = (900, 710)

    class _CompressedFullPageImage:
        data = PNG_MAGIC + b"\x00" * (23 * 1024)
        image = _Raster()

    class _CompressedChartPage:
        images = [_CompressedFullPageImage()]

        @staticmethod
        def extract_text() -> str:
            return "Page 49 of 59"

    class _CompressedReader:
        def __init__(self, path):
            self.pages = [_CompressedChartPage()]

    monkeypatch.setattr(weather_charts, "PdfReader", _CompressedReader)

    found = detect_chart_appendix("ignored.pdf")

    assert len(found) == 1
    assert found[0]["page_number"] == 1
    assert found[0]["image_bytes"] < weather_charts._MIN_IMAGE_BYTES
    assert (found[0]["image_width"], found[0]["image_height"]) == (900, 710)
    assert found[0]["detection_basis"] == "intrinsic-raster-dimensions"


class _GeometryImage:
    def __init__(
        self,
        data: bytes,
        *,
        name: str,
        width: int,
        height: int,
    ) -> None:
        self.data = data
        self.name = name
        self.image = SimpleNamespace(size=(width, height))


class _GeometryBox:
    left = 0
    bottom = 0
    right = 595
    top = 842


class _GeometryPage:
    cropbox = _GeometryBox()

    def __init__(
        self,
        text: str,
        image: _GeometryImage,
        matrix: list[float],
    ) -> None:
        self._text = text
        self.images = [image]
        self._matrix = matrix

    def extract_text(self, *, visitor_operand_before=None) -> str:
        if visitor_operand_before:
            visitor_operand_before(
                b"Do",
                [f"/{self.images[0].name.rsplit('.', 1)[0]}"],
                self._matrix,
                [1, 0, 0, 1, 0, 0],
            )
        return self._text


def test_detection_uses_rendered_coverage_not_compressed_bytes_or_pixels(
    monkeypatch,
) -> None:
    compressed_chart = PNG_MAGIC + b"\x00" * (12 * 1024)
    ordinary_illustration = PNG_MAGIC + b"\x11" * (80 * 1024)
    pages = [
        _GeometryPage(
            "Page 1 of 3",
            _GeometryImage(
                compressed_chart,
                name="Im1.png",
                width=900,
                height=710,
            ),
            [515, 0, 0, 652, 40, 95],
        ),
        _GeometryPage(
            "Illustrated information page",
            _GeometryImage(
                ordinary_illustration,
                name="Im2.png",
                width=1600,
                height=1200,
            ),
            [180, 0, 0, 120, 50, 500],
        ),
        _GeometryPage(
            "NORMAL TEXT " * 40,
            _GeometryImage(
                ordinary_illustration,
                name="Im3.png",
                width=1600,
                height=1200,
            ),
            [515, 0, 0, 652, 40, 95],
        ),
    ]

    class _GeometryReader:
        def __init__(self, path):
            self.pages = pages

    monkeypatch.setattr(weather_charts, "PdfReader", _GeometryReader)

    found = detect_chart_appendix("ignored.pdf")

    assert [item["page_number"] for item in found] == [1]
    assert found[0]["image_bytes"] < weather_charts._MIN_IMAGE_BYTES
    assert found[0]["detection_basis"] == "page-dominating-raster"
    assert found[0]["rendered_page_coverage"] > 0.60


def test_multi_image_page_uses_same_coverage_ranked_raster_everywhere(
    monkeypatch,
) -> None:
    chart_image = PNG_MAGIC + b"\x22" * (12 * 1024)
    oversized_panel = PNG_MAGIC + b"\x33" * (80 * 1024)

    class _MultiImagePage:
        cropbox = _GeometryBox()
        images = [
            _GeometryImage(
                oversized_panel,
                name="ImPanel.png",
                width=1800,
                height=1200,
            ),
            _GeometryImage(
                chart_image,
                name="ImChart.png",
                width=900,
                height=710,
            ),
        ]

        @classmethod
        def extract_text(cls, *, visitor_operand_before=None) -> str:
            if visitor_operand_before:
                visitor_operand_before(
                    b"Do",
                    ["/ImPanel"],
                    [180, 0, 0, 120, 50, 500],
                    [1, 0, 0, 1, 0, 0],
                )
                visitor_operand_before(
                    b"Do",
                    ["/ImChart"],
                    [515, 0, 0, 652, 40, 95],
                    [1, 0, 0, 1, 0, 0],
                )
            return "Page 1 of 1"

    class _MultiImageReader:
        def __init__(self, path):
            self.pages = [_MultiImagePage()]

    ocr_images: list[bytes] = []
    ai_images: list[bytes] = []

    def record_ocr(image: bytes, _deadline=None) -> dict[str, str]:
        ocr_images.append(image)
        return {"ocr_status": "unclassified"}

    def record_ai(_client, _model_id, image: bytes, _media) -> dict[str, str]:
        ai_images.append(image)
        return {"classification_status": "error:test"}

    monkeypatch.setattr(weather_charts, "PdfReader", _MultiImageReader)
    monkeypatch.setattr(weather_charts, "_ocr_enabled", lambda: True)
    monkeypatch.setattr(weather_charts, "_ocr_chart_image", record_ocr)
    monkeypatch.setattr(weather_charts, "_classification_enabled", lambda: True)
    monkeypatch.setattr(weather_charts, "_model_id", lambda: "test-model")
    monkeypatch.setattr(weather_charts, "_bedrock_client", object)
    monkeypatch.setattr(weather_charts, "_classify_one", record_ai)

    detected = detect_chart_appendix("ignored.pdf")
    extracted = weather_charts.extract_chart_image("ignored.pdf", 1)
    manifest = build_weather_chart_manifest("ignored.pdf")

    expected_sha = sha256(chart_image).hexdigest()
    assert detected[0]["image_sha256"] == expected_sha
    assert manifest["charts"][0]["image_sha256"] == expected_sha
    assert extracted == chart_image
    assert ocr_images == [chart_image]
    assert ai_images == [chart_image]


def test_sq910_offline_detection_holds_all_raster_chart_pages(monkeypatch) -> None:
    private_cfp = (
        Path(__file__).resolve().parents[2]
        / "private_cfp_corpus"
        / "SQ91021082026SIN.pdf"
    )
    if not private_cfp.is_file():
        pytest.skip("private SQ910 release-gate CFP is not available")
    monkeypatch.setenv("ODSS_WEATHER_CHART_OCR", "disabled")
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "disabled")

    detected = detect_chart_appendix(private_cfp)
    manifest = build_weather_chart_manifest(private_cfp)

    expected_pages = list(range(46, 58))
    assert [item["page_number"] for item in detected] == expected_pages
    assert [item["page_number"] for item in manifest["charts"]] == expected_pages
    assert manifest["status"] == "held"
    assert manifest["ocr"]["enabled"] is False
    assert manifest["classifier"]["enabled"] is False
    vertical_profile = next(
        item for item in detected if item["page_number"] == 49
    )
    assert vertical_profile["image_bytes"] == 23_778
    assert vertical_profile["detection_basis"] == "page-dominating-raster"


def test_manifest_holds_pages_even_with_ai_disabled(monkeypatch):
    _patch_reader(monkeypatch)
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "disabled")
    manifest = build_weather_chart_manifest("ignored.pdf")
    assert manifest["status"] == "held"
    assert manifest["classifier"]["enabled"] is False
    kinds = [chart["kind"] for chart in manifest["charts"]]
    assert kinds == ["unclassified", "unclassified"]
    assert all(chart["verified"] is False for chart in manifest["charts"])
    assert all(chart["label"].startswith("Briefing chart p") for chart in manifest["charts"])


def test_manifest_preserves_every_chart_and_fails_closed_above_classification_capacity(
    monkeypatch,
):
    pages = [
        _FakePage("", [_CHART_IMAGE + index.to_bytes(2, "big")])
        for index in range(41)
    ]

    class _ManyChartReader:
        def __init__(self, path):
            self.pages = pages

    monkeypatch.setattr(weather_charts, "PdfReader", _ManyChartReader)
    monkeypatch.setenv("ODSS_WEATHER_CHART_OCR", "disabled")
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "disabled")

    manifest = build_weather_chart_manifest("ignored.pdf")

    assert manifest["status"] == "manual-review-required"
    assert [chart["page_number"] for chart in manifest["charts"]] == list(
        range(1, 42)
    )
    assert manifest["coverage"] == {
        "held_chart_count": 41,
        "classification_capacity": 40,
        "classification_work_count": 40,
        "unprocessed_chart_count": 1,
        "classification_incomplete": True,
    }
    assert manifest["charts"][-1]["classification_skip_reason"] == (
        "classification-cap-exceeded"
    )
    assert "all pages remain held" in manifest["reason"]


def test_printed_ocr_identity_requires_title_route_levels_and_validity() -> None:
    identity = parse_chart_ocr_identity(
        "FIXED TIME PROGNOSTIC CHART\n"
        "(ENRT) SQ214: PER -> SIN\n"
        "FL 250-600\n"
        "VALID 12 UTC 19 Aug 2026\n"
    )

    assert identity == {
        "status": "printed",
        "source": "tesseract_ocr",
        "flight_number": "SQ214",
        "departure_iata": "PER",
        "destination_iata": "SIN",
        "valid_time_utc": "2026-08-19T12:00:00+00:00",
        "flight_levels": "FL250-FL600",
        "chart_kind": "sigwx_high_level",
        "title": "FIXED TIME PROGNOSTIC CHART",
        "evidence": "printed-title-route-levels-validity",
    }
    assert parse_chart_ocr_identity(
        "(ENRT) SQ214: PER -> SIN\nFL 250-600\nVALID 12 UTC 19 Aug 2026"
    ) is None


def test_ocr_classification_is_primary_and_bedrock_remains_optional(monkeypatch):
    _patch_reader(monkeypatch)
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "disabled")
    route_context = parse_chart_ocr_identity(
        "FIKED T1ME PROGNOSTIK CHART\n"
        "(ENXT) SQ214: PER => SIN\n"
        "FL 250-600\n"
        "VALID 12 UTC 19 Aug 2026\n"
    )
    monkeypatch.setattr(
        weather_charts,
        "_ocr_chart_image",
        lambda _image, _deadline=None: {
            "ocr_status": "parsed",
            "ocr_text_sha256": "printed-hash",
            "route_context": route_context,
        },
    )

    manifest = build_weather_chart_manifest("ignored.pdf")

    assert all(chart["classification_status"] == "ocr-classified" for chart in manifest["charts"])
    assert all(chart["kind"] == "sigwx_high_level" for chart in manifest["charts"])
    assert all(chart["verified"] is True for chart in manifest["charts"])
    assert manifest["charts"][0]["route_context"]["valid_time_utc"] == (
        "2026-08-19T12:00:00+00:00"
    )


def test_ocr_identity_rejects_unrelated_title_and_route_context() -> None:
    assert parse_chart_ocr_identity(
        "BROKEN RANDOM WEATHER PICTURE\n"
        "(AREA) SQ352: SIN -> CPH\n"
        "FL 250-600\n"
        "VALID 06 UTC 20 Aug 2026\n"
    ) is None


def test_ocr_deadline_exhaustion_fails_closed_without_starting_process(monkeypatch):
    monkeypatch.setattr(weather_charts, "_ocr_enabled", lambda: True)
    monkeypatch.setattr(weather_charts.time, "monotonic", lambda: 100.0)

    def unexpected_process(*args, **kwargs):
        raise AssertionError("expired OCR work must not start a subprocess")

    monkeypatch.setattr(weather_charts.subprocess, "run", unexpected_process)

    assert weather_charts._ocr_chart_image(
        _CHART_IMAGE,
        deadline=99.0,
    ) == {"ocr_status": "budget-exhausted"}


class _FakeBedrock:
    def __init__(self, payloads):
        self._payloads = payloads
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        payload = self._payloads[min(self.calls - 1, len(self._payloads) - 1)]
        return {"output": {"message": {"content": [
            {"toolUse": {"name": "record_chart_classification", "input": payload}}
        ]}}}


def test_ai_classification_reads_identity_and_marks_verification(monkeypatch):
    _patch_reader(monkeypatch)
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "auto")
    monkeypatch.setenv("ODSS_WEATHER_CHART_MODEL", "test-model")
    fake = _FakeBedrock([
        {
            "kind": "sigwx_high_level",
            "issuer": "WAFC WASHINGTON",
            "wmo_heading": "PGEE05 KKCI",
            "valid_time_utc": "2026-07-25T06:00Z",
            "flight_levels": "FL250-FL600",
            "title": "FIXED TIME PROGNOSTIC CHART",
            "confidence": "high",
        },
        {"kind": "wind_temperature", "valid_time_utc": None, "confidence": "medium"},
    ])
    monkeypatch.setattr(weather_charts, "_bedrock_client", lambda: fake)
    manifest = build_weather_chart_manifest("ignored.pdf")
    sigwx = next(c for c in manifest["charts"] if c["kind"] == "sigwx_high_level")
    wind = next(c for c in manifest["charts"] if c["kind"] == "wind_temperature")
    assert sigwx["verified"] is True
    assert sigwx["issuer"] == "WAFC WASHINGTON"
    assert sigwx["label"] == "SIGWX · FL250-FL600 · valid 2026-07-25T06:00Z"
    # A readable kind without a readable validity is held but never "verified".
    assert wind["verified"] is False
    assert fake.calls == 2


def test_ai_failure_degrades_to_unclassified_and_never_drops_pages(monkeypatch):
    _patch_reader(monkeypatch)
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "auto")
    monkeypatch.setenv("ODSS_WEATHER_CHART_MODEL", "test-model")

    class _Boom:
        def converse(self, **kwargs):
            raise RuntimeError("bedrock unreachable")

    monkeypatch.setattr(weather_charts, "_bedrock_client", lambda: _Boom())
    manifest = build_weather_chart_manifest("ignored.pdf")
    assert manifest["status"] == "held"
    assert len(manifest["charts"]) == 2
    assert all(chart["kind"] == "unclassified" for chart in manifest["charts"])
    assert all(
        chart["classification_status"].startswith("error:") for chart in manifest["charts"]
    )


def test_invalid_kind_from_model_is_rejected_not_trusted(monkeypatch):
    _patch_reader(monkeypatch)
    monkeypatch.setenv("ODSS_WEATHER_CHART_AI", "auto")
    monkeypatch.setenv("ODSS_WEATHER_CHART_MODEL", "test-model")
    fake = _FakeBedrock([{"kind": "totally_new_kind", "confidence": "high"}])
    monkeypatch.setattr(weather_charts, "_bedrock_client", lambda: fake)
    manifest = build_weather_chart_manifest("ignored.pdf")
    assert all(chart["kind"] == "unclassified" for chart in manifest["charts"])
    assert any(
        chart["classification_status"] == "error:invalid_kind" for chart in manifest["charts"]
    )
