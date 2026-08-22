from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "rev3_visual_reference_manifest.json"


class VisualRegressionError(ValueError):
    """The private reference or raster contract cannot be trusted."""


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    width_points: float
    height_points: float
    width_pixels: int
    height_pixels: int
    samples: bytes
    raster_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualRegressionError(f"Cannot read visual reference manifest {path.name}: {exc}") from exc

    if payload.get("schema_version") != 1:
        raise VisualRegressionError("Visual reference manifest schema_version must be 1")
    if payload.get("gate") != "rev3-raster-pixel-equality":
        raise VisualRegressionError("Visual reference manifest has an unexpected gate identifier")

    reference = payload.get("reference_asset")
    if not isinstance(reference, dict):
        raise VisualRegressionError("Visual reference manifest is missing reference_asset")
    if not isinstance(reference.get("filename"), str) or not reference["filename"]:
        raise VisualRegressionError("Visual reference filename must be a non-empty string")
    reference_hash = reference.get("sha256")
    if not isinstance(reference_hash, str) or len(reference_hash) != 64:
        raise VisualRegressionError("Visual reference sha256 must be a 64-character digest")

    renderer = payload.get("renderer")
    if not isinstance(renderer, dict):
        raise VisualRegressionError("Visual reference manifest is missing renderer")
    required_renderer = {
        "library",
        "binding_version",
        "mupdf_version",
        "scale",
        "colorspace",
        "alpha",
        "annotations",
    }
    if set(renderer) != required_renderer:
        raise VisualRegressionError(
            "Visual reference renderer keys must be exactly "
            + ", ".join(sorted(required_renderer))
        )
    if renderer["library"] != "PyMuPDF":
        raise VisualRegressionError("Visual reference renderer library must be PyMuPDF")
    if renderer["scale"] != 1.0:
        raise VisualRegressionError("Visual reference renderer scale must be exactly 1.0")
    if renderer["colorspace"] != "DeviceRGB" or renderer["alpha"] is not False:
        raise VisualRegressionError("Visual reference renderer must use DeviceRGB without alpha")
    if renderer["annotations"] is not True:
        raise VisualRegressionError("Visual reference renderer must include PDF annotations")

    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise VisualRegressionError("Visual reference manifest must contain at least one page")
    for page_number, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_number") != page_number:
            raise VisualRegressionError("Visual reference pages must be sequential and one-based")
        for field in ("width_points", "height_points"):
            if not isinstance(page.get(field), (int, float)) or page[field] <= 0:
                raise VisualRegressionError(f"Page {page_number} has invalid {field}")
        for field in ("width_pixels", "height_pixels"):
            if not isinstance(page.get(field), int) or page[field] <= 0:
                raise VisualRegressionError(f"Page {page_number} has invalid {field}")
        raster_hash = page.get("reference_raster_sha256")
        if not isinstance(raster_hash, str) or len(raster_hash) != 64:
            raise VisualRegressionError(
                f"Page {page_number} reference_raster_sha256 must be a 64-character digest"
            )

    thresholds = payload.get("thresholds")
    exact_thresholds = {
        "max_changed_pixel_ratio": 0.0,
        "max_mean_absolute_error": 0.0,
        "max_channel_delta": 0,
    }
    if thresholds != exact_thresholds:
        raise VisualRegressionError(
            "REV3 is an exact pixel-equality gate; all raster thresholds must remain zero"
        )
    return payload


def _runtime_renderer_contract() -> dict[str, Any]:
    return {
        "library": "PyMuPDF",
        "binding_version": str(fitz.VersionBind),
        "mupdf_version": str(fitz.mupdf_version),
        "scale": 1.0,
        "colorspace": "DeviceRGB",
        "alpha": False,
        "annotations": True,
    }


def _render_page(page: fitz.Page, page_number: int) -> RenderedPage:
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(1.0, 1.0),
        colorspace=fitz.csRGB,
        alpha=False,
        annots=True,
    )
    samples = bytes(pixmap.samples)
    return RenderedPage(
        page_number=page_number,
        width_points=float(page.rect.width),
        height_points=float(page.rect.height),
        width_pixels=pixmap.width,
        height_pixels=pixmap.height,
        samples=samples,
        raster_sha256=hashlib.sha256(samples).hexdigest(),
    )


def _render_document(path: Path) -> list[RenderedPage]:
    if not path.is_file():
        raise VisualRegressionError(f"PDF not found: {path.name}")
    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise VisualRegressionError(f"PDF requires a password: {path.name}")
            return [
                _render_page(page, page_number)
                for page_number, page in enumerate(document, start=1)
            ]
    except VisualRegressionError:
        raise
    except Exception as exc:
        raise VisualRegressionError(f"Cannot render PDF {path.name}: {exc}") from exc


def _geometry(page: RenderedPage) -> dict[str, float]:
    return {
        "width_points": round(page.width_points, 6),
        "height_points": round(page.height_points, 6),
    }


def _raster(page: RenderedPage) -> dict[str, Any]:
    return {
        "width_pixels": page.width_pixels,
        "height_pixels": page.height_pixels,
        "sha256": page.raster_sha256,
    }


def _page_contract_violations(
    page: RenderedPage,
    expected: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    violations: list[str] = []
    geometry_tolerance = 0.000001
    for field in ("width_points", "height_points"):
        if abs(getattr(page, field) - float(expected[field])) > geometry_tolerance:
            violations.append(
                f"{label} {field} {getattr(page, field):.6f} != expected {expected[field]:.6f}"
            )
    for field in ("width_pixels", "height_pixels"):
        if getattr(page, field) != int(expected[field]):
            violations.append(
                f"{label} {field} {getattr(page, field)} != expected {expected[field]}"
            )
    return violations


def _pixel_difference(
    reference: RenderedPage,
    candidate: RenderedPage,
    *,
    diff_path: Path | None,
) -> dict[str, Any]:
    if (
        reference.width_pixels != candidate.width_pixels
        or reference.height_pixels != candidate.height_pixels
        or len(reference.samples) != len(candidate.samples)
    ):
        raise VisualRegressionError("Cannot compare raster samples with different dimensions")

    total_pixels = reference.width_pixels * reference.height_pixels
    if reference.raster_sha256 == candidate.raster_sha256:
        return {
            "total_pixels": total_pixels,
            "changed_pixels": 0,
            "changed_pixel_ratio": 0.0,
            "mean_absolute_error": 0.0,
            "max_channel_delta": 0,
            "difference_bbox_pixels": None,
            "total_absolute_error": 0,
            "diff_png": None,
        }

    reference_samples = reference.samples
    candidate_samples = candidate.samples
    diff_samples = bytearray(len(reference_samples)) if diff_path is not None else None
    changed_pixels = 0
    total_absolute_error = 0
    max_channel_delta = 0
    min_x = reference.width_pixels
    min_y = reference.height_pixels
    max_x = -1
    max_y = -1

    for offset in range(0, len(reference_samples), 3):
        red_delta = abs(reference_samples[offset] - candidate_samples[offset])
        green_delta = abs(reference_samples[offset + 1] - candidate_samples[offset + 1])
        blue_delta = abs(reference_samples[offset + 2] - candidate_samples[offset + 2])
        total_absolute_error += red_delta + green_delta + blue_delta
        pixel_max = max(red_delta, green_delta, blue_delta)
        if pixel_max > max_channel_delta:
            max_channel_delta = pixel_max
        if diff_samples is not None:
            diff_samples[offset] = red_delta
            diff_samples[offset + 1] = green_delta
            diff_samples[offset + 2] = blue_delta
        if pixel_max:
            changed_pixels += 1
            pixel_index = offset // 3
            y, x = divmod(pixel_index, reference.width_pixels)
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    if diff_path is not None and diff_samples is not None:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_pixmap = fitz.Pixmap(
            fitz.csRGB,
            reference.width_pixels,
            reference.height_pixels,
            bytes(diff_samples),
            False,
        )
        diff_pixmap.set_dpi(72, 72)
        diff_pixmap.save(diff_path)

    difference_bbox = None
    if changed_pixels:
        difference_bbox = {
            "x0": min_x,
            "y0": min_y,
            "x1": max_x + 1,
            "y1": max_y + 1,
        }
    return {
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "changed_pixel_ratio": round(changed_pixels / total_pixels, 12),
        "mean_absolute_error": round(
            total_absolute_error / (total_pixels * 3),
            6,
        ),
        "max_channel_delta": max_channel_delta,
        "difference_bbox_pixels": difference_bbox,
        "total_absolute_error": total_absolute_error,
        "diff_png": diff_path.name if diff_path is not None else None,
    }


def _validate_reference(
    reference_pages: list[RenderedPage],
    manifest: dict[str, Any],
) -> None:
    expected_pages = manifest["pages"]
    if len(reference_pages) != len(expected_pages):
        raise VisualRegressionError(
            f"Reference page count {len(reference_pages)} != expected {len(expected_pages)}"
        )
    for reference_page, expected_page in zip(reference_pages, expected_pages):
        violations = _page_contract_violations(
            reference_page,
            expected_page,
            label=f"Reference page {reference_page.page_number}",
        )
        if violations:
            raise VisualRegressionError("; ".join(violations))
        if reference_page.raster_sha256 != expected_page["reference_raster_sha256"]:
            raise VisualRegressionError(
                f"Reference page {reference_page.page_number} raster checksum mismatch: "
                f"expected {expected_page['reference_raster_sha256']}, "
                f"got {reference_page.raster_sha256}"
            )


def compare_pdf_rasters(
    *,
    reference_path: Path,
    candidate_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    diff_dir: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    runtime_renderer = _runtime_renderer_contract()
    if runtime_renderer != manifest["renderer"]:
        raise VisualRegressionError(
            "Renderer contract mismatch: expected "
            f"{json.dumps(manifest['renderer'], sort_keys=True)}, got "
            f"{json.dumps(runtime_renderer, sort_keys=True)}"
        )
    if reference_path.name != manifest["reference_asset"]["filename"]:
        raise VisualRegressionError(
            f"Reference filename {reference_path.name!r} != expected "
            f"{manifest['reference_asset']['filename']!r}"
        )
    actual_reference_hash = sha256_file(reference_path)
    if actual_reference_hash != manifest["reference_asset"]["sha256"]:
        raise VisualRegressionError(
            "Reference PDF checksum mismatch: expected "
            f"{manifest['reference_asset']['sha256']}, got {actual_reference_hash}"
        )

    reference_pages = _render_document(reference_path)
    _validate_reference(reference_pages, manifest)
    candidate_hash = sha256_file(candidate_path)
    candidate_pages = _render_document(candidate_path)
    expected_pages = manifest["pages"]
    thresholds = manifest["thresholds"]

    page_receipts: list[dict[str, Any]] = []
    total_pixels = 0
    total_changed_pixels = 0
    total_absolute_error = 0
    max_channel_delta = 0
    compared_page_count = 0
    max_page_count = max(len(reference_pages), len(candidate_pages))

    for index in range(max_page_count):
        page_number = index + 1
        if index >= len(reference_pages):
            candidate_page = candidate_pages[index]
            page_receipts.append(
                {
                    "page_number": page_number,
                    "status": "failed",
                    "reference_geometry_points": None,
                    "candidate_geometry_points": _geometry(candidate_page),
                    "reference_raster": None,
                    "candidate_raster": _raster(candidate_page),
                    "pixel_difference": None,
                    "violations": ["Candidate has an unexpected extra page"],
                }
            )
            continue
        reference_page = reference_pages[index]
        if index >= len(candidate_pages):
            page_receipts.append(
                {
                    "page_number": page_number,
                    "status": "failed",
                    "reference_geometry_points": _geometry(reference_page),
                    "candidate_geometry_points": None,
                    "reference_raster": _raster(reference_page),
                    "candidate_raster": None,
                    "pixel_difference": None,
                    "violations": ["Candidate is missing this reference page"],
                }
            )
            continue

        candidate_page = candidate_pages[index]
        expected_page = expected_pages[index]
        violations = _page_contract_violations(
            candidate_page,
            expected_page,
            label=f"Candidate page {page_number}",
        )
        pixel_difference = None
        if (
            reference_page.width_pixels == candidate_page.width_pixels
            and reference_page.height_pixels == candidate_page.height_pixels
            and len(reference_page.samples) == len(candidate_page.samples)
        ):
            diff_path = None
            if diff_dir is not None and reference_page.raster_sha256 != candidate_page.raster_sha256:
                diff_path = diff_dir / f"page-{page_number:02d}-absolute-difference.png"
            pixel_difference = _pixel_difference(
                reference_page,
                candidate_page,
                diff_path=diff_path,
            )
            compared_page_count += 1
            total_pixels += pixel_difference["total_pixels"]
            total_changed_pixels += pixel_difference["changed_pixels"]
            total_absolute_error += pixel_difference.pop("total_absolute_error")
            max_channel_delta = max(
                max_channel_delta,
                pixel_difference["max_channel_delta"],
            )
            if pixel_difference["changed_pixel_ratio"] > thresholds["max_changed_pixel_ratio"]:
                violations.append(
                    "Changed-pixel ratio "
                    f"{pixel_difference['changed_pixel_ratio']:.12f} exceeds "
                    f"{thresholds['max_changed_pixel_ratio']:.12f}"
                )
            if pixel_difference["mean_absolute_error"] > thresholds["max_mean_absolute_error"]:
                violations.append(
                    "Mean absolute error "
                    f"{pixel_difference['mean_absolute_error']:.6f} exceeds "
                    f"{thresholds['max_mean_absolute_error']:.6f}"
                )
            if pixel_difference["max_channel_delta"] > thresholds["max_channel_delta"]:
                violations.append(
                    "Maximum channel delta "
                    f"{pixel_difference['max_channel_delta']} exceeds "
                    f"{thresholds['max_channel_delta']}"
                )
        else:
            violations.append("Candidate raster dimensions differ from the reference raster")

        page_receipts.append(
            {
                "page_number": page_number,
                "status": "failed" if violations else "passed",
                "reference_geometry_points": _geometry(reference_page),
                "candidate_geometry_points": _geometry(candidate_page),
                "reference_raster": _raster(reference_page),
                "candidate_raster": _raster(candidate_page),
                "pixel_difference": pixel_difference,
                "violations": violations,
            }
        )

    page_count_matches = len(candidate_pages) == len(reference_pages)
    failed_page_count = sum(page["status"] == "failed" for page in page_receipts)
    status = "passed" if page_count_matches and failed_page_count == 0 else "failed"
    failure_reasons: list[str] = []
    if not page_count_matches:
        failure_reasons.append(
            f"Candidate page count {len(candidate_pages)} != expected {len(reference_pages)}"
        )
    if failed_page_count:
        failure_reasons.append(f"{failed_page_count} page(s) failed the exact raster contract")

    return {
        "schema_version": 1,
        "gate": manifest["gate"],
        "case_id": manifest["case_id"],
        "status": status,
        "manifest": {
            "filename": manifest_path.name,
            "sha256": sha256_file(manifest_path),
        },
        "reference": {
            "filename": reference_path.name,
            "pdf_sha256": actual_reference_hash,
            "page_count": len(reference_pages),
        },
        "candidate": {
            "filename": candidate_path.name,
            "pdf_sha256": candidate_hash,
            "page_count": len(candidate_pages),
        },
        "renderer": runtime_renderer,
        "thresholds": thresholds,
        "summary": {
            "expected_page_count": len(reference_pages),
            "candidate_page_count": len(candidate_pages),
            "compared_page_count": compared_page_count,
            "failed_page_count": failed_page_count,
            "total_pixels_compared": total_pixels,
            "changed_pixels": total_changed_pixels,
            "changed_pixel_ratio": round(total_changed_pixels / total_pixels, 12)
            if total_pixels
            else None,
            "mean_absolute_error": round(total_absolute_error / (total_pixels * 3), 6)
            if total_pixels
            else None,
            "max_channel_delta": max_channel_delta,
        },
        "failure_reasons": failure_reasons,
        "pages": page_receipts,
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def _failed_preflight_receipt(
    *,
    manifest_path: Path,
    reference_path: Path,
    candidate_path: Path,
    error: Exception,
) -> dict[str, Any]:
    manifest_hash = sha256_file(manifest_path) if manifest_path.is_file() else None
    return {
        "schema_version": 1,
        "gate": "rev3-raster-pixel-equality",
        "status": "failed",
        "manifest": {
            "filename": manifest_path.name,
            "sha256": manifest_hash,
        },
        "reference": {"filename": reference_path.name},
        "candidate": {"filename": candidate_path.name},
        "preflight_error_type": type(error).__name__,
        "preflight_error": str(error),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a private SQ214 REV3 reference and candidate as exact RGB rasters."
    )
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", required=True, type=Path, help="JSON receipt path")
    parser.add_argument(
        "--diff-dir",
        type=Path,
        help="Optional directory for absolute-difference PNGs; keep it outside Git",
    )
    args = parser.parse_args()

    try:
        receipt = compare_pdf_rasters(
            reference_path=args.reference,
            candidate_path=args.candidate,
            manifest_path=args.manifest,
            diff_dir=args.diff_dir,
        )
    except Exception as exc:
        receipt = _failed_preflight_receipt(
            manifest_path=args.manifest,
            reference_path=args.reference,
            candidate_path=args.candidate,
            error=exc,
        )
    _write_receipt(args.output, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(args.output),
                "failure_reasons": receipt.get("failure_reasons", []),
                "preflight_error": receipt.get("preflight_error"),
            },
            indent=2,
        )
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
