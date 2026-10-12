"""OCR recovery keeps printed evidence and the original total work budget."""
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

from app.odss import weather_charts as wc


PRINTED = (
    "FIXED TIME PROGNOSTIC CHART\n(ENRT) AB123: SIN -> HAN\n"
    "FL 250-600\nVALID 10 UTC 11 Jul 2026\n"
)
MISSING_ARROW = PRINTED.replace("->", "")


def chart_image(size=(710, 900)):
    buffer = BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(wc, "_ocr_enabled", lambda: True)
    monkeypatch.setenv("ODSS_WEATHER_CHART_OCR_TIMEOUT_SECONDS", "20")
    clock = [100.0]
    monkeypatch.setattr(wc.time, "monotonic", lambda: clock[0])
    calls, replies = [], []

    def run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        clock[0] += 3.0
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(returncode=0, stdout=reply.encode(), stderr=b"")

    monkeypatch.setattr(wc.subprocess, "run", run)
    return calls, replies, clock


def test_recovery_reads_whole_scaled_image_with_same_strict_parser(native):
    calls, replies, _ = native
    replies.extend([MISSING_ARROW, PRINTED])
    original = chart_image()
    result = wc._ocr_chart_image(original)
    assert result["route_context"] == wc.parse_chart_ocr_identity(PRINTED)
    assert len(calls) == 2
    assert calls[0]["input"] == original
    with Image.open(BytesIO(calls[1]["input"])) as image:
        assert image.size == (1420, 1800)
    assert result["ocr_text_sha256"] == sha256(PRINTED.encode()).hexdigest()
    assert result["ocr_attempts"][0]["image_sha256"] == sha256(original).hexdigest()
    assert result["ocr_attempts"][1]["image_sha256"] == sha256(calls[1]["input"]).hexdigest()


def test_retry_uses_remaining_per_image_timeout(native):
    calls, replies, _ = native
    replies.extend([MISSING_ARROW, PRINTED])
    wc._ocr_chart_image(chart_image())
    assert [call["timeout"] for call in calls] == [20.0, 17.0]


def test_retry_uses_remaining_global_deadline(native):
    calls, replies, _ = native
    replies.extend([MISSING_ARROW, PRINTED])
    wc._ocr_chart_image(chart_image(), deadline=107.0)
    assert [call["timeout"] for call in calls] == [7.0, 4.0]


@pytest.mark.parametrize("invalid", [MISSING_ARROW, PRINTED.replace("->", "<-"), PRINTED.replace("VALID 10 UTC 11 Jul 2026", "")])
def test_retry_never_inserts_direction_or_combines_partial_transcripts(native, invalid):
    calls, replies, _ = native
    replies.extend([MISSING_ARROW, invalid])
    result = wc._ocr_chart_image(chart_image())
    assert result["ocr_status"] == "unclassified"
    assert "route_context" not in result
    assert len(calls) == 2


def test_already_parsed_image_is_not_reprocessed(native):
    calls, replies, _ = native
    replies.append(PRINTED)
    assert wc._ocr_chart_image(chart_image())["route_context"] == wc.parse_chart_ocr_identity(PRINTED)
    assert len(calls) == 1


def test_unrelated_chart_is_not_reprocessed(native):
    calls, replies, _ = native
    replies.append("WIND AND TEMPERATURE\nSIN -> HAN\nVALID 10 UTC 11 Jul 2026")
    assert wc._ocr_chart_image(chart_image())["ocr_status"] == "unclassified"
    assert len(calls) == 1


def test_retry_does_not_start_after_global_budget(native):
    calls, replies, _ = native
    replies.append(MISSING_ARROW)
    result = wc._ocr_chart_image(chart_image(), deadline=102.0)
    assert len(calls) == 1
    assert result["ocr_status"] == "budget-exhausted"
    assert "route_context" not in result


def test_retry_timeout_remains_explicit_and_never_classifies(native):
    calls, replies, _ = native
    replies.extend([MISSING_ARROW, wc.subprocess.TimeoutExpired("tesseract", 17)])
    result = wc._ocr_chart_image(chart_image())
    assert result["ocr_status"] == "error:TimeoutExpired"
    assert "route_context" not in result
    assert len(result["ocr_attempts"]) == 2


def test_pixel_limit_refuses_upscale_without_losing_original_result(native):
    calls, replies, _ = native
    replies.append(MISSING_ARROW)
    result = wc._ocr_chart_image(chart_image((2001, 2000)))
    assert result["ocr_status"] == "unclassified"
    assert result["ocr_retry_status"] == "not-run:pixel-limit"
    assert len(calls) == 1


def test_source_decode_failure_is_explicit(native):
    calls, replies, _ = native
    replies.append(MISSING_ARROW)
    result = wc._ocr_chart_image(b"bad image")
    assert result["ocr_status"] == "unclassified"
    assert result["ocr_retry_status"].startswith("error:")
    assert len(calls) == 1
