"""Governed weather-chart extraction from the uploaded briefing package.

LIDO/OFP packages append their weather charts — SIGWX prognostic charts and
wind/temperature charts — as full-page raster images at the back of the PDF.
The text pipeline never sees them, which is why the briefing reported "SIGWX
chart unavailable" while the chart sat inside the pilot's own upload.

This module finds that appendix in ANY package (no fixed page numbers): a
candidate page is one whose extractable text is near-empty while a substantial
image fills it. Every candidate is held; classification is attempted within a
bounded work budget by the same governed Bedrock Claude profile the platform
already uses for surface extraction, which reads the chart's own printed
identity — kind, issuer, WMO heading, validity — off the raster. Classification
is additive and fail-closed:

- A page the model cannot classify (or Bedrock being disabled or unreachable)
  is still HELD, as ``unclassified``; AI failure never drops evidence.
- If a package exceeds the bounded classification capacity, every page remains
  held and the manifest explicitly requires manual review; it never presents a
  silently partial classification as complete.
- Identity fields the model could not read stay null and the entry is marked
  unverified; nothing is inferred from filenames or page positions.
- The held artifact is the page of the uploaded package itself, addressed by
  page number and pinned by the image bytes' sha256 — nothing external is
  fetched and nothing is redrawn.
"""

from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from datetime import datetime, timezone
from hashlib import sha256
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader


CHART_KINDS = ("sigwx_high_level", "sigwx_mid_level", "wind_temperature", "other")
_MAX_TEXT_CHARS = 200
_MIN_IMAGE_BYTES = 30 * 1024
_MIN_IMAGE_DIMENSION = 600
_MIN_IMAGE_PIXELS = 500_000
_MIN_RENDERED_PAGE_COVERAGE = 0.48
_MIN_RENDERED_PAGE_SPAN = 0.55
_MAX_CLASSIFIED_CHARTS = 40
_TOOL_NAME = "record_chart_classification"
_OCR_ENGINE = "tesseract"
_OCR_ROUTE = re.compile(
    r"\((?P<context>[A-Z]{3,5})\)\s*"
    r"(?P<flight>[A-Z]{2,3}\s*\d{2,4})\s*:\s*"
    r"(?P<departure>[A-Z]{3})\s*(?:-|=)+>\s*(?P<destination>[A-Z]{3})\b",
    re.IGNORECASE,
)
_OCR_LEVELS = re.compile(
    r"\bFL\s*(?P<lower>\d{2,3})\s*-\s*(?:FL\s*)?(?P<upper>\d{2,3})\b",
    re.IGNORECASE,
)
_OCR_VALID = re.compile(
    r"\bVALID\s*(?P<hour>\d{2})\s*UTC\s*"
    r"(?P<day>\d{1,2})\s*(?P<month>[A-Z]{3})\s*(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

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


def _ocr_enabled() -> bool:
    flag = os.environ.get("ODSS_WEATHER_CHART_OCR", "auto").strip().lower()
    if flag in {"disabled", "off", "none", "false"}:
        return False
    return shutil.which(_OCR_ENGINE) is not None


def _ocr_timeout_seconds() -> float:
    raw = os.environ.get("ODSS_WEATHER_CHART_OCR_TIMEOUT_SECONDS", "20").strip()
    try:
        return min(60.0, max(2.0, float(raw)))
    except ValueError:
        return 20.0


def _ocr_budget_seconds() -> float:
    raw = os.environ.get("ODSS_WEATHER_CHART_OCR_BUDGET_SECONDS", "45").strip()
    try:
        return min(180.0, max(2.0, float(raw)))
    except ValueError:
        return 45.0


def _ocr_workers() -> int:
    raw = os.environ.get("ODSS_WEATHER_CHART_OCR_WORKERS", "4").strip()
    try:
        return min(8, max(1, int(raw)))
    except ValueError:
        return 4


def _limited_ocr_distance(observed: str, expected: str) -> int:
    """Return edit distance for short printed labels without sample aliases."""
    previous = list(range(len(expected) + 1))
    for row, observed_char in enumerate(observed, start=1):
        current = [row]
        for column, expected_char in enumerate(expected, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (observed_char != expected_char),
            ))
        previous = current
    return previous[-1]


def _has_fixed_time_chart_title(text: str) -> bool:
    """Match ordered title words with a small, generic OCR-error budget."""
    expected = ("FIXED", "TIME", "PROGNOSTIC", "CHART")
    glyphs = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})
    for line in str(text or "").upper().splitlines():
        words = [
            token.translate(glyphs)
            for token in re.findall(r"[A-Z0-9]+", line)
        ]
        for start in range(0, max(0, len(words) - len(expected) + 1)):
            candidate = words[start:start + len(expected)]
            if all(
                _limited_ocr_distance(observed, target)
                <= (2 if len(target) >= 5 else 1)
                for observed, target in zip(candidate, expected)
            ):
                return True
    return False


def parse_chart_ocr_identity(text: str) -> dict[str, Any] | None:
    """Parse a route-specific fixed-time chart identity from printed OCR.

    All four independent printed patterns are mandatory: chart title, route,
    flight-level band and UTC validity.  No filename, page number or appendix
    position participates in classification.
    """
    normalized = str(text or "").replace("→", "->").replace("⇒", "=>")
    route = _OCR_ROUTE.search(normalized)
    levels = _OCR_LEVELS.search(normalized)
    validity = _OCR_VALID.search(normalized)
    if not all((route, levels, validity)) or not _has_fixed_time_chart_title(normalized):
        return None
    if _limited_ocr_distance(route.group("context").upper(), "ENRT") > 1:
        return None
    lower = int(levels.group("lower"))
    upper = int(levels.group("upper"))
    month = _MONTHS.get(validity.group("month").upper())
    if month is None or not (100 <= lower < upper <= 700):
        return None
    try:
        valid_time = datetime(
            int(validity.group("year")),
            month,
            int(validity.group("day")),
            int(validity.group("hour")),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return {
        "status": "printed",
        "source": "tesseract_ocr",
        "flight_number": re.sub(r"\s+", "", route.group("flight").upper()),
        "departure_iata": route.group("departure").upper(),
        "destination_iata": route.group("destination").upper(),
        "valid_time_utc": valid_time.isoformat(),
        "flight_levels": f"FL{lower}-FL{upper}",
        "chart_kind": (
            "sigwx_high_level" if lower >= 250 else "sigwx_mid_level"
        ),
        "title": "FIXED TIME PROGNOSTIC CHART",
        "evidence": "printed-title-route-levels-validity",
    }


def _ocr_chart_image(
    image: bytes,
    deadline: float | None = None,
) -> dict[str, Any]:
    if not _ocr_enabled():
        return {"ocr_status": "unavailable"}
    timeout = _ocr_timeout_seconds()
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"ocr_status": "budget-exhausted"}
        timeout = min(timeout, max(0.1, remaining))
    try:
        completed = subprocess.run(
            [_OCR_ENGINE, "stdin", "stdout", "-l", "eng", "--psm", "11"],
            input=image,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ocr_status": f"error:{type(exc).__name__}"}
    if completed.returncode != 0:
        return {"ocr_status": f"error:exit_{completed.returncode}"}
    text = completed.stdout.decode("utf-8", errors="replace")
    identity = parse_chart_ocr_identity(text)
    result: dict[str, Any] = {
        "ocr_status": "parsed" if identity else "unclassified",
        "ocr_text_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }
    if identity:
        result["route_context"] = identity
    return result


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


def _page_box(page: Any) -> tuple[float, float, float, float] | None:
    """Return a finite, positive crop/media box in page user-space units."""
    box = getattr(page, "cropbox", None) or getattr(page, "mediabox", None)
    if box is None:
        return None
    try:
        values = tuple(float(value) for value in (
            box.left,
            box.bottom,
            box.right,
            box.top,
        ))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    left, bottom, right, top = values
    if not all(math.isfinite(value) for value in values):
        return None
    if right <= left or top <= bottom:
        return None
    return left, bottom, right, top


def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )) / 2.0


def _clip_polygon_to_page(
    points: list[tuple[float, float]],
    page_box: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """Clip a transformed unit-image rectangle to the visible page box."""
    left, bottom, right, top = page_box

    def clip(
        polygon: list[tuple[float, float]],
        inside: Any,
        intersect: Any,
    ) -> list[tuple[float, float]]:
        if not polygon:
            return []
        output: list[tuple[float, float]] = []
        previous = polygon[-1]
        previous_inside = inside(previous)
        for current in polygon:
            current_inside = inside(current)
            if current_inside != previous_inside:
                output.append(intersect(previous, current))
            if current_inside:
                output.append(current)
            previous = current
            previous_inside = current_inside
        return output

    def vertical_intersection(
        first: tuple[float, float],
        second: tuple[float, float],
        x_value: float,
    ) -> tuple[float, float]:
        x1, y1 = first
        x2, y2 = second
        if x2 == x1:
            return x_value, y1
        ratio = (x_value - x1) / (x2 - x1)
        return x_value, y1 + ratio * (y2 - y1)

    def horizontal_intersection(
        first: tuple[float, float],
        second: tuple[float, float],
        y_value: float,
    ) -> tuple[float, float]:
        x1, y1 = first
        x2, y2 = second
        if y2 == y1:
            return x1, y_value
        ratio = (y_value - y1) / (y2 - y1)
        return x1 + ratio * (x2 - x1), y_value

    clipped = points
    clipped = clip(
        clipped,
        lambda point: point[0] >= left,
        lambda first, second: vertical_intersection(first, second, left),
    )
    clipped = clip(
        clipped,
        lambda point: point[0] <= right,
        lambda first, second: vertical_intersection(first, second, right),
    )
    clipped = clip(
        clipped,
        lambda point: point[1] >= bottom,
        lambda first, second: horizontal_intersection(first, second, bottom),
    )
    return clip(
        clipped,
        lambda point: point[1] <= top,
        lambda first, second: horizontal_intersection(first, second, top),
    )


def _rendered_image_geometry(
    matrix: Any,
    page_box: tuple[float, float, float, float] | None,
) -> dict[str, float] | None:
    """Measure the visible footprint of a PDF image's transformed unit box."""
    if page_box is None:
        return None
    try:
        a, b, c, d, e, f = (float(value) for value in matrix[:6])
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (a, b, c, d, e, f)):
        return None
    points = [
        (e, f),
        (a + e, b + f),
        (a + c + e, b + d + f),
        (c + e, d + f),
    ]
    clipped = _clip_polygon_to_page(points, page_box)
    visible_area = _polygon_area(clipped)
    if visible_area <= 0:
        return None
    left, bottom, right, top = page_box
    page_width = right - left
    page_height = top - bottom
    visible_width = max(x for x, _ in clipped) - min(x for x, _ in clipped)
    visible_height = max(y for _, y in clipped) - min(y for _, y in clipped)
    return {
        "coverage": min(1.0, visible_area / (page_width * page_height)),
        "width_span": min(1.0, max(0.0, visible_width) / page_width),
        "height_span": min(1.0, max(0.0, visible_height) / page_height),
    }


def _image_key(image: Any) -> str | None:
    name = str(getattr(image, "name", "") or "")
    if not name:
        return None
    stem = name.rsplit(".", 1)[0]
    return stem if stem.startswith("/") else f"/{stem}"


def _image_dimensions(image: Any) -> tuple[int, int] | None:
    try:
        raster = image.image
        width, height = (int(value) for value in raster.size)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _page_image_details(
    page: Any,
    placements: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    try:
        images = list(page.images)
    except Exception:
        return details
    for image in images:
        try:
            data = image.data
        except Exception:
            continue
        if not data:
            continue
        dimensions = _image_dimensions(image)
        width, height = dimensions or (None, None)
        details.append({
            "data": data,
            "width": width,
            "height": height,
            "pixels": width * height if width and height else 0,
            "geometry": (placements or {}).get(_image_key(image) or ""),
        })
    return details


def _substantial_raster_candidate(details: dict[str, Any]) -> bool:
    """Accept a page-dominating raster, including highly compressed charts."""
    geometry = details.get("geometry")
    dimension_evidence = bool(
        int(details.get("width") or 0) >= _MIN_IMAGE_DIMENSION
        and int(details.get("height") or 0) >= _MIN_IMAGE_DIMENSION
        and int(details.get("pixels") or 0) >= _MIN_IMAGE_PIXELS
    )
    if geometry is None:
        # Compatibility for PageObject-like readers without pypdf's visitor
        # geometry. Intrinsic dimensions preserve sparse, highly compressed
        # charts; the previous byte threshold remains the final fallback.
        return bool(
            dimension_evidence or len(details["data"]) >= _MIN_IMAGE_BYTES
        )
    return bool(
        dimension_evidence
        and geometry["coverage"] >= _MIN_RENDERED_PAGE_COVERAGE
        and geometry["width_span"] >= _MIN_RENDERED_PAGE_SPAN
        and geometry["height_span"] >= _MIN_RENDERED_PAGE_SPAN
    )


def _page_text_and_image_placements(
    page: Any,
) -> tuple[str, dict[str, dict[str, float]]]:
    """Extract page text and the largest visible placement per image."""
    page_box = _page_box(page)
    placements: dict[str, dict[str, float]] = {}

    def record_placement(
        operator: Any,
        operands: Any,
        matrix: Any,
        _tm: Any,
    ) -> None:
        if operator != b"Do" or not operands:
            return
        geometry = _rendered_image_geometry(matrix, page_box)
        if geometry is None:
            return
        key = str(operands[0])
        previous = placements.get(key)
        if previous is None or geometry["coverage"] > previous["coverage"]:
            placements[key] = geometry

    try:
        text = (page.extract_text(visitor_operand_before=record_placement) or "").strip()
    except TypeError:
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
    except Exception:
        text = ""
    return text, placements


def _select_chart_image_details(
    page: Any,
    placements: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any] | None:
    """Select one substantial chart raster by rendered coverage first.

    Detection, re-extraction, OCR and AI classification must all consume the
    same embedded image.  Intrinsic pixels and encoded bytes are deterministic
    tie-breakers only; they must not let a large logo or inset panel replace a
    page-dominating chart when placement geometry is available.
    """
    if placements is None:
        _, placements = _page_text_and_image_placements(page)
    candidates = [
        details
        for details in _page_image_details(page, placements)
        if _substantial_raster_candidate(details)
    ]
    return max(
        candidates,
        key=lambda item: (
            (item.get("geometry") or {}).get("coverage", 0.0),
            item["pixels"],
            len(item["data"]),
        ),
        default=None,
    )


def largest_page_image(page: Any) -> bytes | None:
    """The largest-coverage embedded image on a page, or None."""
    details = _select_chart_image_details(page)
    return details["data"] if details else None


def detect_chart_appendix(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Find raster chart pages in the package, wherever they sit."""
    candidates: list[dict[str, Any]] = []
    reader = PdfReader(str(pdf_path))
    for number, page in enumerate(reader.pages, start=1):
        text, placements = _page_text_and_image_placements(page)
        if len(text) > _MAX_TEXT_CHARS:
            continue
        details = _select_chart_image_details(page, placements)
        if details is None:
            continue
        data = details["data"]
        geometry = details.get("geometry")
        dimension_evidence = bool(
            int(details.get("width") or 0) >= _MIN_IMAGE_DIMENSION
            and int(details.get("height") or 0) >= _MIN_IMAGE_DIMENSION
            and int(details.get("pixels") or 0) >= _MIN_IMAGE_PIXELS
        )
        media = _media_type(data)
        candidates.append({
            "page_number": number,
            "image_sha256": sha256(data).hexdigest(),
            "image_bytes": len(data),
            "image_width": details.get("width"),
            "image_height": details.get("height"),
            "rendered_page_coverage": (
                round(geometry["coverage"], 6) if geometry else None
            ),
            "detection_basis": (
                "page-dominating-raster"
                if geometry
                else "intrinsic-raster-dimensions"
                if dimension_evidence
                else "legacy-byte-fallback"
            ),
            "media_type": media,
        })
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


def _apply_ai_classification(
    entry: dict[str, Any],
    classification: dict[str, Any],
) -> None:
    """Keep Bedrock additive when deterministic printed evidence exists."""
    if entry.get("route_context"):
        entry["ai_classification"] = dict(classification)
        if classification.get("classification_status") == "classified":
            for key in ("issuer", "wmo_heading", "confidence"):
                if classification.get(key) and not entry.get(key):
                    entry[key] = classification[key]
        return
    entry.update(classification)


def _apply_ocr_classification(
    entry: dict[str, Any],
    result: dict[str, Any],
) -> None:
    entry.update(result)
    route_context = entry.get("route_context") or {}
    if route_context:
        entry.update({
            "kind": route_context["chart_kind"],
            "classification_status": "ocr-classified",
            "valid_time_utc": route_context["valid_time_utc"],
            "flight_levels": route_context["flight_levels"],
            "title": route_context["title"],
            "confidence": "deterministic-printed-pattern",
        })


def build_weather_chart_manifest(pdf_path: str | Path) -> dict[str, Any]:
    """Detect, OCR-classify and pin the package's weather charts.

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
            "image_width": candidate.get("image_width"),
            "image_height": candidate.get("image_height"),
            "rendered_page_coverage": candidate.get("rendered_page_coverage"),
            "detection_basis": candidate.get("detection_basis"),
            "kind": "unclassified",
            "classification_status": "unclassified",
            "verified": False,
            "source": "uploaded_package",
        })

    classification_charts = charts[:_MAX_CLASSIFIED_CHARTS]
    deferred_charts = charts[_MAX_CLASSIFIED_CHARTS:]
    for entry in deferred_charts:
        entry["ocr_status"] = "not-run:classification-cap"
        entry["classification_skip_reason"] = "classification-cap-exceeded"

    ocr_available = _ocr_enabled()
    ocr_budget = _ocr_budget_seconds()
    ocr_workers = _ocr_workers()
    if classification_charts and ocr_available:
        try:
            reader = PdfReader(str(pdf_path))
            deadline = time.monotonic() + ocr_budget
            futures = {}
            applied_futures = set()
            with ThreadPoolExecutor(max_workers=ocr_workers) as pool:
                for entry in classification_charts:
                    image = largest_page_image(
                        reader.pages[entry["page_number"] - 1]
                    )
                    if image is None:
                        entry["ocr_status"] = "error:image_unreadable"
                        continue
                    futures[pool.submit(
                        _ocr_chart_image,
                        image,
                        deadline,
                    )] = entry
                try:
                    for future in as_completed(
                        futures,
                        timeout=max(0.1, deadline - time.monotonic() + 0.25),
                    ):
                        entry = futures[future]
                        try:
                            _apply_ocr_classification(entry, future.result())
                            applied_futures.add(future)
                        except Exception as exc:
                            entry["ocr_status"] = f"error:{type(exc).__name__}"
                            applied_futures.add(future)
                except FuturesTimeoutError:
                    pass
                for future, entry in futures.items():
                    if future in applied_futures:
                        continue
                    if future.done():
                        try:
                            _apply_ocr_classification(entry, future.result())
                        except Exception as exc:
                            entry["ocr_status"] = f"error:{type(exc).__name__}"
                    else:
                        future.cancel()
                        entry["ocr_status"] = "budget-exhausted"
        except Exception as exc:
            for entry in classification_charts:
                if not entry.get("ocr_status"):
                    entry["ocr_status"] = f"error:{type(exc).__name__}"
    else:
        for entry in classification_charts:
            entry["ocr_status"] = "unavailable"

    if classification_charts and _classification_enabled():
        model_id = _model_id()
        budget = _ai_budget_seconds()
        deadline = time.monotonic() + budget
        try:
            client = _bedrock_client()
            reader = PdfReader(str(pdf_path))
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {}
                for entry in classification_charts:
                    image = largest_page_image(reader.pages[entry["page_number"] - 1])
                    if image is None:
                        _apply_ai_classification(
                            entry,
                            {"classification_status": "error:image_unreadable"},
                        )
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
                        _apply_ai_classification(entry, future.result())
                    except Exception as exc:  # fail-closed per page
                        failure = f"error:{type(exc).__name__}:{str(exc)[:120]}"
                        _apply_ai_classification(
                            entry,
                            {"classification_status": failure},
                        )
        except Exception as exc:
            for entry in classification_charts:
                _apply_ai_classification(
                    entry,
                    {
                        "classification_status": (
                            f"error:{type(exc).__name__}:{str(exc)[:120]}"
                        )
                    },
                )

    for entry in charts:
        route_context = entry.get("route_context") or {}
        if (
            entry["classification_status"] != "classified"
            and entry["classification_status"] != "ocr-classified"
        ):
            entry["kind"] = "unclassified"
        entry["verified"] = bool(
            (
                entry["classification_status"] == "classified"
                and entry.get("kind")
                in ("sigwx_high_level", "sigwx_mid_level", "wind_temperature")
                and entry.get("valid_time_utc")
            )
            or (
                entry["classification_status"] == "ocr-classified"
                and route_context.get("status") == "printed"
                and route_context.get("chart_kind")
                in ("sigwx_high_level", "sigwx_mid_level")
                and route_context.get("valid_time_utc")
            )
        )
        entry["label"] = _label(entry)

    classification_incomplete = bool(deferred_charts)
    return {
        "status": (
            "manual-review-required"
            if classification_incomplete
            else "held"
            if charts
            else "none_detected"
        ),
        "reason": (
            f"{len(charts)} held chart pages exceed the bounded "
            f"{_MAX_CLASSIFIED_CHARTS}-page classification capacity; "
            "all pages remain held and manual review is required."
            if classification_incomplete
            else None
        ),
        "generated_at_utc": generated_at,
        "coverage": {
            "held_chart_count": len(charts),
            "classification_capacity": _MAX_CLASSIFIED_CHARTS,
            "classification_work_count": len(classification_charts),
            "unprocessed_chart_count": len(deferred_charts),
            "classification_incomplete": classification_incomplete,
        },
        "ocr": {
            "enabled": ocr_available,
            "engine": _OCR_ENGINE if ocr_available else None,
            "budget_seconds": ocr_budget,
            "workers": ocr_workers,
        },
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
    "parse_chart_ocr_identity",
]
