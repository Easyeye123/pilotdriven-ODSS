from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import fitz
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_rev3_visual_regression.py"
PINNED_MANIFEST = Path(__file__).with_name("rev3_visual_reference_manifest.json")


def _create_pdf(path: Path, label: str) -> None:
    with fitz.open() as document:
        page = document.new_page(width=240, height=160)
        page.draw_rect(fitz.Rect(12, 12, 228, 148), color=(0.1, 0.2, 0.5), width=2)
        page.insert_text((24, 52), "REV3 SYNTHETIC VISUAL CONTRACT", fontsize=11)
        page.insert_text((24, 82), label, fontsize=16)
        document.save(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(reference: Path, output: Path) -> None:
    with fitz.open(reference) as document:
        pages = []
        for page_number, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(1.0, 1.0),
                colorspace=fitz.csRGB,
                alpha=False,
                annots=True,
            )
            pages.append(
                {
                    "page_number": page_number,
                    "width_points": float(page.rect.width),
                    "height_points": float(page.rect.height),
                    "width_pixels": pixmap.width,
                    "height_pixels": pixmap.height,
                    "reference_raster_sha256": hashlib.sha256(pixmap.samples).hexdigest(),
                }
            )
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "rev3-raster-pixel-equality",
                "case_id": "SYNTHETIC-REV3",
                "reference_asset": {
                    "filename": reference.name,
                    "sha256": _sha256(reference),
                },
                "renderer": {
                    "library": "PyMuPDF",
                    "binding_version": str(fitz.VersionBind),
                    "mupdf_version": str(fitz.mupdf_version),
                    "scale": 1.0,
                    "colorspace": "DeviceRGB",
                    "alpha": False,
                    "annotations": True,
                },
                "pages": pages,
                "thresholds": {
                    "max_changed_pixel_ratio": 0.0,
                    "max_mean_absolute_error": 0.0,
                    "max_channel_delta": 0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_gate(
    *,
    reference: Path,
    candidate: Path,
    manifest: Path,
    receipt: Path,
    diff_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--reference",
        str(reference),
        "--candidate",
        str(candidate),
        "--manifest",
        str(manifest),
        "--output",
        str(receipt),
    ]
    if diff_dir is not None:
        command.extend(["--diff-dir", str(diff_dir)])
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_identical_synthetic_pdf_passes_exact_pixel_gate(tmp_path: Path) -> None:
    reference = tmp_path / "synthetic-reference.pdf"
    candidate = tmp_path / "synthetic-candidate.pdf"
    manifest = tmp_path / "manifest.json"
    receipt_path = tmp_path / "receipt.json"
    _create_pdf(reference, "PIXELS MATCH")
    shutil.copyfile(reference, candidate)
    _write_manifest(reference, manifest)

    completed = _run_gate(
        reference=reference,
        candidate=candidate,
        manifest=manifest,
        receipt=receipt_path,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert receipt["status"] == "passed"
    assert receipt["summary"]["changed_pixels"] == 0
    assert receipt["summary"]["changed_pixel_ratio"] == 0.0
    assert receipt["summary"]["mean_absolute_error"] == 0.0
    assert receipt["summary"]["max_channel_delta"] == 0
    assert receipt["pages"][0]["pixel_difference"]["difference_bbox_pixels"] is None


def test_changed_synthetic_pdf_fails_with_metrics_and_diff_png(tmp_path: Path) -> None:
    reference = tmp_path / "synthetic-reference.pdf"
    candidate = tmp_path / "synthetic-candidate.pdf"
    manifest = tmp_path / "manifest.json"
    receipt_path = tmp_path / "receipt.json"
    diff_dir = tmp_path / "diffs"
    _create_pdf(reference, "REFERENCE")
    _create_pdf(candidate, "CHANGED")
    _write_manifest(reference, manifest)

    completed = _run_gate(
        reference=reference,
        candidate=candidate,
        manifest=manifest,
        receipt=receipt_path,
        diff_dir=diff_dir,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    page = receipt["pages"][0]
    difference = page["pixel_difference"]
    diff_path = diff_dir / difference["diff_png"]

    assert completed.returncode == 1
    assert receipt["status"] == "failed"
    assert receipt["summary"]["failed_page_count"] == 1
    assert difference["changed_pixels"] > 0
    assert difference["changed_pixel_ratio"] > 0
    assert difference["mean_absolute_error"] > 0
    assert difference["max_channel_delta"] > 0
    assert difference["difference_bbox_pixels"] is not None
    assert diff_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert any("Changed-pixel ratio" in item for item in page["violations"])


def test_wrong_private_reference_hash_fails_before_comparison(tmp_path: Path) -> None:
    reference = tmp_path / "synthetic-reference.pdf"
    candidate = tmp_path / "synthetic-candidate.pdf"
    manifest = tmp_path / "manifest.json"
    receipt_path = tmp_path / "receipt.json"
    _create_pdf(reference, "REFERENCE")
    shutil.copyfile(reference, candidate)
    _write_manifest(reference, manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["reference_asset"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    completed = _run_gate(
        reference=reference,
        candidate=candidate,
        manifest=manifest,
        receipt=receipt_path,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert completed.returncode == 1
    assert receipt["status"] == "failed"
    assert receipt["preflight_error_type"] == "VisualRegressionError"
    assert "Reference PDF checksum mismatch" in receipt["preflight_error"]
    assert "pages" not in receipt


def test_pinned_manifest_contains_only_the_private_asset_contract() -> None:
    payload = json.loads(PINNED_MANIFEST.read_text(encoding="utf-8"))

    # 41 page entries of geometry + checksums only; far below any size that could embed the PDF.
    assert PINNED_MANIFEST.stat().st_size < 16_000
    assert payload["reference_asset"] == {
        "filename": "SQ214_REV3_reference_v6.pdf",
        "sha256": "4397ed3f32c1c6a4cf5cea4f58978ff2309f391294b7d97dffbec34e4d7f5986",
    }
    assert len(payload["pages"]) == 41
    assert payload["provenance"]["combined_briefing_schema_version"] == "2026-08-23-flow-round-v6"
    assert "20-21 Aug 2026" in payload["provenance"]["approval_basis"]
    assert payload["thresholds"] == {
        "max_changed_pixel_ratio": 0.0,
        "max_mean_absolute_error": 0.0,
        "max_channel_delta": 0,
    }


def test_sq214_rev3_private_exact_visual_reference(tmp_path: Path) -> None:
    reference_value = os.environ.get("ODSS_REV3_VISUAL_REFERENCE_PDF")
    candidate_value = os.environ.get("ODSS_REV3_VISUAL_CANDIDATE_PDF")
    if not reference_value and not candidate_value:
        pytest.skip(
            "Set ODSS_REV3_VISUAL_REFERENCE_PDF and ODSS_REV3_VISUAL_CANDIDATE_PDF "
            "to run the proprietary REV3 raster gate"
        )
    assert reference_value and candidate_value, (
        "ODSS_REV3_VISUAL_REFERENCE_PDF and ODSS_REV3_VISUAL_CANDIDATE_PDF "
        "must be set together"
    )
    receipt_path = tmp_path / "private-rev3-receipt.json"
    completed = _run_gate(
        reference=Path(reference_value),
        candidate=Path(candidate_value),
        manifest=PINNED_MANIFEST,
        receipt=receipt_path,
        diff_dir=tmp_path / "private-rev3-diffs",
    )
    receipt_text = receipt_path.read_text(encoding="utf-8")

    assert completed.returncode == 0, completed.stdout + completed.stderr + receipt_text
    assert json.loads(receipt_text)["status"] == "passed"


MINT_SCRIPT = ROOT / "scripts" / "mint_rev3_visual_reference.py"


def _run_mint(*, reference: Path, manifest: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(MINT_SCRIPT),
        "--reference",
        str(reference),
        "--manifest",
        str(manifest),
        "--case-id",
        "SYNTHETIC-REV3",
        "--approval-basis",
        "synthetic test approval",
    ]
    command.extend(extra or [])
    return subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)


def test_mint_script_writes_a_manifest_the_gate_accepts_for_its_own_reference(tmp_path: Path) -> None:
    reference = tmp_path / "approved-reference.pdf"
    _create_pdf(reference, "APPROVED")
    manifest = tmp_path / "minted-manifest.json"

    minted = _run_mint(reference=reference, manifest=manifest)

    assert minted.returncode == 0, minted.stdout + minted.stderr
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["gate"] == "rev3-raster-pixel-equality"
    assert payload["case_id"] == "SYNTHETIC-REV3"
    assert payload["reference_asset"] == {
        "filename": "approved-reference.pdf",
        "sha256": _sha256(reference),
    }
    assert payload["renderer"]["binding_version"] == str(fitz.VersionBind)
    assert payload["renderer"]["mupdf_version"] == str(fitz.mupdf_version)
    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["page_number"] == 1
    assert len(payload["pages"][0]["reference_raster_sha256"]) == 64
    assert payload["thresholds"] == {
        "max_changed_pixel_ratio": 0.0,
        "max_mean_absolute_error": 0.0,
        "max_channel_delta": 0,
    }
    assert payload["provenance"]["approval_basis"] == "synthetic test approval"
    assert payload["provenance"]["minted_on"]
    # The manifest must not embed the private asset itself.
    assert manifest.stat().st_size < 4_000

    receipt = tmp_path / "self-receipt.json"
    completed = _run_gate(reference=reference, candidate=reference, manifest=manifest, receipt=receipt)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "passed"

    other = tmp_path / "other.pdf"
    _create_pdf(other, "DIFFERENT")
    other_receipt = tmp_path / "other-receipt.json"
    rejected = _run_gate(reference=reference, candidate=other, manifest=manifest, receipt=other_receipt)
    assert rejected.returncode == 1
    assert json.loads(other_receipt.read_text(encoding="utf-8"))["status"] == "failed"


def test_mint_script_refuses_a_missing_reference(tmp_path: Path) -> None:
    manifest = tmp_path / "never-written.json"

    minted = _run_mint(reference=tmp_path / "missing.pdf", manifest=manifest)

    assert minted.returncode == 1
    assert not manifest.exists()
    assert "PDF not found" in minted.stdout + minted.stderr
