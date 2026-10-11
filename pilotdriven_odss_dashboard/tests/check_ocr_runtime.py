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
from app.odss.weather_charts import _ocr_chart_image, parse_chart_ocr_identity


PRINTED = "FIXED TIME PROGNOSTIC CHART\n(ENRT) SQ214: PER -> SIN\nFL 250-600\nVALID 10 UTC 11 Jul 2026\n"


def page_image(text: str, dpi: int = 180) -> tuple[bytes, bytes]:
    with pymupdf.open() as document:
        page = document.new_page(width=800, height=500)
        page.insert_text((40, 65), text, fontsize=24, fontname="helv")
        return document.tobytes(), page.get_pixmap(dpi=dpi).tobytes("png")


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
        actual = _ocr_chart_image(image)
        if actual.get("ocr_status") != "parsed" or actual.get("route_context") != expected:
            raise RuntimeError(f"Real OCR changed printed identity: {name}: {actual}")
        results.append({"case": name, "imageSha256": hashlib.sha256(image).hexdigest(), **actual})
    for name, image, status in (
        ("missing-validity", page_image(PRINTED.rsplit("VALID", 1)[0])[1], "unclassified"),
        ("blank-image", page_image("")[1], "unclassified"),
        ("malformed-image", b"not an image", "error:exit_1"),
    ):
        actual = _ocr_chart_image(image)
        if actual.get("ocr_status") != status or "route_context" in actual:
            raise RuntimeError(f"OCR did not fail safely: {name}: {actual}")
        results.append({"case": name, **actual})
    expired = _ocr_chart_image(png, deadline=time.monotonic() - 1)
    if expired != {"ocr_status": "budget-exhausted"}:
        raise RuntimeError(f"OCR deadline was not enforced: {expired}")
    results.append({"case": "expired-budget", **expired})
    print(json.dumps({"status": "PASS", "scope": "synthetic real-process OCR controls; not private CFP acceptance",
                      "component": identity, "textPdfSha256": hashlib.sha256(text_pdf).hexdigest(),
                      "scannedPdfSha256": hashlib.sha256(scan_bytes).hexdigest(), "cases": results}, indent=2))


if __name__ == "__main__":
    main()
