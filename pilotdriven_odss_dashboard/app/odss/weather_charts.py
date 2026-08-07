"""Governed weather-chart extraction from the uploaded briefing package.

LIDO/OFP packages append their weather charts — SIGWX prognostic charts and
wind/temperature charts — as full-page raster images at the back of the PDF.
The text pipeline never sees them, which is why the briefing reported "SIGWX
chart unavailable" while the chart sat inside the pilot's own upload.

This module finds that appendix in ANY package (no fixed page numbers): a
candidate page is one whose extractable text is near-empty while a substantial
image fills it. Each candidate is then classified by the same governed Bedrock
Claude profile the platform already uses for surface extraction, which reads
the chart's own printed identity — kind, issuer, WMO heading, validity — off
the raster. Classification is additive and fail-closed:

- A page the model cannot classify (or Bedrock being disabled or unreachable)
  is still HELD, as ``unclassified``; AI failure never drops evidence.
- Identity fields the model could not read stay null and the entry is marked
  unverified; nothing is inferred from filenames or page positions.
- The held artifact is the page of the uploaded package itself, addressed by
  page number and pinned by the image bytes' sha256 — nothing external is
  fetched and nothing is redrawn.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import os
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader


CHART_KINDS = ("sigwx_high_level", "sigwx_mid_level", "wind_temperature", "other")
_MAX_TEXT_CHARS = 200
_MIN_IMAGE_BYTES = 30 * 1024
_MAX_HELD_CHARTS = 40
_TOOL_NAME = "record_chart_classification"

_PROMPT = (
    "This image is one full page from an airline flight-briefing package. "
    "Classify the aviation weather chart and transcribe ONLY what is printed "
    "on the chart itself. If a field is not printed or not readable, return "
    "null for it — never guess. kinds: sigwx_high_level (significant weather "
    "prognostic chart, typically FL250-FL630), sigwx_mid_level, "
    "wind_temperature (wind/temp aloft chart), other."
)

_TOOL_SPEC = {
    "toolSpec": {
        "name": _TOOL_NAME,
        "description": "Record the classification of one briefing chart page.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(CHART_KINDS)},
                "issuer": {"type": ["string", "null"]},
                "wmo_heading": {"type": ["string", "null"]},
                "valid_time_utc": {"type": ["string", "null"]},
                "flight_levels": {"type": ["string", "null"]},
                "title": {"type": ["string", "null"]},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
            "required": ["kind", "confidence"],
        }},
    }
}


def _media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "application/octet-stream"


def _bedrock_format(media: str) -> str | None:
    return {"image/png": "png", "image/jpeg": "jpeg"}.get(media)


def _model_id() -> str:
    return os.environ.get("ODSS_WEATHER_CHART_MODEL", "").strip()


def _classification_enabled() -> bool:
    flag = os.environ.get("ODSS_WEATHER_CHART_AI", "auto").strip().lower()
    if flag in {"disabled", "off", "none", "false"}:
        return False
    return bool(_model_id())


def _ai_budget_seconds() -> float:
    raw = os.environ.get("ODSS_WEATHER_CHART_AI_BUDGET_SECONDS", "45").strip()
    try:
        return min(180.0, max(5.0, float(raw)))
    except ValueError:
        return 45.0


def _bedrock_client():
    import boto3

    region = os.environ.get("ODSS_WEATHER_CHART_BEDROCK_REGION", "").strip()
    return boto3.client("bedrock-runtime", region_name=region) if region else boto3.client("bedrock-runtime")


def largest_page_image(page: Any) -> bytes | None:
    """The biggest embedded image on a page, or None."""
    best: bytes | None = None
    try:
        images = list(page.images)
    except Exception:
        return None
    for image in images:
        try:
            data = image.data
        except Exception:
            continue
        if data and (best is None or len(data) > len(best)):
            best = data
    return best


def detect_chart_appendix(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Find raster chart pages in the package, wherever they sit."""
    candidates: list[dict[str, Any]] = []
    reader = PdfReader(str(pdf_path))
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if len(text) > _MAX_TEXT_CHARS:
            continue
        data = largest_page_image(page)
        if not data or len(data) < _MIN_IMAGE_BYTES:
            continue
        media = _media_type(data)
        candidates.append({
            "page_number": number,
            "image_sha256": sha256(data).hexdigest(),
            "image_bytes": len(data),
            "media_type": media,
        })
        if len(candidates) >= _MAX_HELD_CHARTS:
            break
    return candidates


def extract_chart_image(pdf_path: str | Path, page_number: int) -> bytes | None:
    """Re-extract one held chart image from the stored package."""
    reader = PdfReader(str(pdf_path))
    if not 1 <= page_number <= len(reader.pages):
        return None
    return largest_page_image(reader.pages[page_number - 1])


def _classify_one(client: Any, model_id: str, image: bytes, media: str) -> dict[str, Any]:
    image_format = _bedrock_format(media)
    if image_format is None:
        return {"classification_status": "error:unsupported_image_format"}
    response = client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": image_format, "source": {"bytes": image}}},
                {"text": _PROMPT},
            ],
        }],
        toolConfig={"tools": [_TOOL_SPEC], "toolChoice": {"tool": {"name": _TOOL_NAME}}},
        inferenceConfig={"maxTokens": 400, "temperature": 0},
    )
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == _TOOL_NAME:
            payload = tool_use.get("input") or {}
            kind = payload.get("kind")
            if kind not in CHART_KINDS:
                return {"classification_status": "error:invalid_kind"}
            return {
                "classification_status": "classified",
                "kind": kind,
                "issuer": payload.get("issuer"),
                "wmo_heading": payload.get("wmo_heading"),
                "valid_time_utc": payload.get("valid_time_utc"),
                "flight_levels": payload.get("flight_levels"),
                "title": payload.get("title"),
                "confidence": payload.get("confidence"),
            }
    return {"classification_status": "error:no_tool_result"}


def _label(entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if kind in ("sigwx_high_level", "sigwx_mid_level"):
        parts = ["SIGWX"]
        if entry.get("flight_levels"):
            parts.append(str(entry["flight_levels"]))
        if entry.get("valid_time_utc"):
            parts.append(f"valid {entry['valid_time_utc']}")
        return " · ".join(parts)
    if kind == "wind_temperature":
        parts = ["Wind/Temp"]
        if entry.get("valid_time_utc"):
            parts.append(f"valid {entry['valid_time_utc']}")
        return " · ".join(parts)
    return f"Briefing chart p{entry['page_number']}"


def build_weather_chart_manifest(pdf_path: str | Path) -> dict[str, Any]:
    """Detect, classify and pin the package's weather charts.

    Always returns a manifest; classification problems degrade individual
    entries to ``unclassified`` rather than losing the held page.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        candidates = detect_chart_appendix(pdf_path)
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "generated_at_utc": generated_at,
            "charts": [],
        }
    charts: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        charts.append({
            "chart_number": index,
            "page_number": candidate["page_number"],
            "media_type": candidate["media_type"],
            "image_sha256": candidate["image_sha256"],
            "image_bytes": candidate["image_bytes"],
            "kind": "unclassified",
            "classification_status": "unclassified",
            "verified": False,
            "source": "uploaded_package",
        })

    if charts and _classification_enabled():
        model_id = _model_id()
        budget = _ai_budget_seconds()
        deadline = time.monotonic() + budget
        try:
            client = _bedrock_client()
            reader = PdfReader(str(pdf_path))
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {}
                for entry in charts:
                    image = largest_page_image(reader.pages[entry["page_number"] - 1])
                    if image is None:
                        entry["classification_status"] = "error:image_unreadable"
                        continue
                    futures[pool.submit(
                        _classify_one, client, model_id, image, entry["media_type"]
                    )] = entry
                for future in as_completed(futures, timeout=budget):
                    entry = futures[future]
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        entry.update(future.result())
                    except Exception as exc:  # fail-closed per page
                        entry["classification_status"] = (
                            f"error:{type(exc).__name__}:{str(exc)[:120]}"
                        )
        except Exception as exc:
            for entry in charts:
                if entry["classification_status"] == "unclassified":
                    entry["classification_status"] = (
                        f"error:{type(exc).__name__}:{str(exc)[:120]}"
                    )

    for entry in charts:
        if entry["classification_status"] != "classified":
            entry["kind"] = "unclassified"
        entry["verified"] = bool(
            entry["classification_status"] == "classified"
            and entry.get("kind") in ("sigwx_high_level", "sigwx_mid_level", "wind_temperature")
            and entry.get("valid_time_utc")
        )
        entry["label"] = _label(entry)

    return {
        "status": "held" if charts else "none_detected",
        "generated_at_utc": generated_at,
        "classifier": {
            "enabled": _classification_enabled(),
            "model_id": _model_id() or None,
        },
        "charts": charts,
    }


__all__ = [
    "CHART_KINDS",
    "build_weather_chart_manifest",
    "detect_chart_appendix",
    "extract_chart_image",
    "largest_page_image",
]
