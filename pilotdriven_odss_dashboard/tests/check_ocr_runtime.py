"""Run real OCR in the final image, with synthetic inputs and AI disabled.

This post-build probe is intentionally separate from unit tests that mock the
OCR process. It verifies the installed component before exercising the same
subprocess and identity parser used for weather charts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pymupdf


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ODSS_WEATHER_CHART_AI"] = "off"
os.environ["ODSS_WEATHER_CHART_OCR"] = "on"
from app.odss import weather_charts
from app.odss.weather_charts import _ocr_chart_image, parse_chart_ocr_identity


PRINTED = "FIXED TIME PROGNOSTIC CHART\n(ENRT) SQ214: PER -> SIN\nFL 250-600\nVALID 10 UTC 11 Jul 2026\n"


def page_image(text: str, dpi: int = 180) -> tuple[bytes, bytes]:
    with pymupdf.open() as document:
        page = document.new_page(width=800, height=500)
        page.insert_text((40, 65), text, fontsize=24, fontname="helv")
        return document.tobytes(), page.get_pixmap(dpi=dpi).tobytes("png")


def recorded_ocr(image: bytes) -> dict:
    """Capture actual native outputs without substituting recognition results."""
    native_run = weather_charts.subprocess.run
    calls = []

    def capture(command, **kwargs):
        started = time.monotonic()
        completed = native_run(command, **kwargs)
        calls.append({"command": command, "imageSha256": hashlib.sha256(kwargs["input"]).hexdigest(),
                      "timeoutSeconds": kwargs["timeout"], "elapsedSeconds": time.monotonic() - started,
                      "exitCode": completed.returncode, "stdout": completed.stdout.decode("utf-8", errors="replace"),
                      "stderr": completed.stderr.decode("utf-8", errors="replace")})
        return completed

    weather_charts.subprocess.run = capture
    try:
        result = _ocr_chart_image(image)
    finally:
        weather_charts.subprocess.run = native_run
    return {**result, "native_calls": calls}


def main() -> None:
    path = Path("/usr/share/pilotdriven-tesseract/verify_component.py")
    spec = importlib.util.spec_from_file_location("installed_ocr_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = module.verify()
    expected = parse_chart_ocr_identity(PRINTED)
    if expected is None:
        raise RuntimeError("Synthetic printed control is invalid")
    text_pdf, png = page_image(PRINTED)
    # A second PDF contains only an image, so extraction cannot accidentally
    # pass by reading the original PDF text layer.
    with pymupdf.open() as scanned:
        page = scanned.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png)
        scan_bytes = scanned.tobytes()
    with pymupdf.open(stream=scan_bytes, filetype="pdf") as scanned:
        if scanned[0].get_text().strip():
            raise RuntimeError("Scanned control unexpectedly has a text layer")
        scan_png = scanned[0].get_pixmap(dpi=150).tobytes("png")
    results = []
    for name, image in (("printed-png", png), ("scanned-pdf", scan_png)):
        actual = recorded_ocr(image)
        if actual.get("ocr_status") != "parsed" or actual.get("route_context") != expected:
            raise RuntimeError(f"Real OCR changed printed identity: {name}: {actual}")
        results.append({"case": name, "imageSha256": hashlib.sha256(image).hexdigest(), **actual})
    for name, image, status in (
        ("missing-validity", page_image(PRINTED.rsplit("VALID", 1)[0])[1], "unclassified"),
        ("blank-image", page_image("")[1], "unclassified"),
        ("malformed-image", b"not an image", "error:exit_1"),
    ):
        actual = recorded_ocr(image)
        if actual.get("ocr_status") != status or "route_context" in actual:
            raise RuntimeError(f"OCR did not fail safely: {name}: {actual}")
        results.append({"case": name, **actual})
    # Synthetic identity text is rasterised into an image-only PDF, then read
    # back at varied resolutions. Route direction is always printed evidence.
    varied = [
        ("sin-lhr-72dpi", PRINTED.replace("SQ214: PER -> SIN", "SQ481: SIN -> LHR"), 72, True),
        ("hkg-sin-96dpi", PRINTED.replace("SQ214: PER -> SIN", "ABC123: HKG -> SIN"), 96, True),
        ("sin-mel-144dpi", PRINTED.replace("SQ214: PER -> SIN", "AB321: SIN => MEL"), 144, True),
        ("mel-syd-200dpi", PRINTED.replace("SQ214: PER -> SIN", "QF702: MEL -> SYD"), 200, True),
        ("han-sin-300dpi", PRINTED.replace("SQ214: PER -> SIN", "XY908: HAN -> SIN"), 300, True),
        ("no-arrow-72dpi", PRINTED.replace("->", ""), 72, False),
        ("no-arrow-144dpi", PRINTED.replace("->", ""), 144, False),
        ("reverse-arrow-96dpi", PRINTED.replace("->", "<-"), 96, False),
        ("reverse-arrow-180dpi", PRINTED.replace("->", "<-"), 180, False),
    ]
    for name, printed, dpi, accepted in varied:
        _, raster = page_image(printed, dpi)
        with pymupdf.open() as document:
            page = document.new_page(width=800, height=500)
            page.insert_image(page.rect, stream=raster)
            scanned_bytes = document.tobytes()
        with pymupdf.open(stream=scanned_bytes, filetype="pdf") as document:
            if document[0].get_text().strip():
                raise RuntimeError("Varied scanned control has a text layer")
            image = document[0].get_pixmap(dpi=dpi).tobytes("png")
        actual = recorded_ocr(image)
        expected_identity = parse_chart_ocr_identity(printed) if accepted else None
        row = {"case": name, "dpi": dpi, "scannedPdfSha256": hashlib.sha256(scanned_bytes).hexdigest(),
               "imageSha256": hashlib.sha256(image).hexdigest(), "expectedIdentity": expected_identity, **actual}
        print("OCR_RUNTIME_CASE " + json.dumps(row), flush=True)
        if actual.get("ocr_status") != ("parsed" if accepted else "unclassified") or actual.get("route_context") != expected_identity:
            raise RuntimeError(f"Varied scanned identity failed: {name}")
        results.append(row)
    expired = _ocr_chart_image(png, deadline=time.monotonic() - 1)
    if expired != {"ocr_status": "budget-exhausted"}:
        raise RuntimeError(f"OCR deadline was not enforced: {expired}")
    results.append({"case": "expired-budget", **expired})
    print(json.dumps({"status": "PASS", "scope": "synthetic real-process OCR controls; not private CFP acceptance",
                      "component": identity, "textPdfSha256": hashlib.sha256(text_pdf).hexdigest(),
                      "scannedPdfSha256": hashlib.sha256(scan_bytes).hexdigest(), "cases": results}, indent=2))


if __name__ == "__main__":
    main()
