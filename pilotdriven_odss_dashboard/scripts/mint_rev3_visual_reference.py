#!/usr/bin/env python3
"""Mint the SQ214 REV3 exact-pixel visual reference manifest from an approved private PDF.

Use this only for a deliberate, reviewed supersession of the approved reference.
The PDF itself stays private; only page geometry, raster checksums, the renderer
contract and the approval provenance are written to the manifest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_rev3_visual_regression import (  # noqa: E402
    DEFAULT_MANIFEST,
    VisualRegressionError,
    _geometry,
    _raster,
    _render_document,
    _runtime_renderer_contract,
    compare_pdf_rasters,
    load_manifest,
    sha256_file,
)

EXACT_THRESHOLDS = {
    "max_changed_pixel_ratio": 0.0,
    "max_mean_absolute_error": 0.0,
    "max_channel_delta": 0,
}


def build_manifest(
    *,
    reference: Path,
    case_id: str,
    approval_basis: str,
    combined_briefing_schema_version: str | None,
) -> dict[str, Any]:
    pages = _render_document(reference)
    page_entries = []
    for page in pages:
        geometry = _geometry(page)
        raster = _raster(page)
        page_entries.append(
            {
                "page_number": page.page_number,
                "width_points": geometry["width_points"],
                "height_points": geometry["height_points"],
                "width_pixels": raster["width_pixels"],
                "height_pixels": raster["height_pixels"],
                "reference_raster_sha256": raster["sha256"],
            }
        )
    provenance: dict[str, Any] = {
        "minted_on": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "approval_basis": approval_basis,
    }
    if combined_briefing_schema_version:
        provenance["combined_briefing_schema_version"] = combined_briefing_schema_version
    return {
        "schema_version": 1,
        "gate": "rev3-raster-pixel-equality",
        "case_id": case_id,
        "reference_asset": {
            "filename": reference.name,
            "sha256": sha256_file(reference),
        },
        "renderer": _runtime_renderer_contract(),
        "pages": page_entries,
        "thresholds": dict(EXACT_THRESHOLDS),
        "provenance": provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mint the REV3 exact-pixel reference manifest from an approved private PDF."
    )
    parser.add_argument("--reference", required=True, type=Path, help="approved private reference PDF")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="manifest path to write")
    parser.add_argument("--case-id", default="SQ214-PER-SIN-19AUG-REV3")
    parser.add_argument(
        "--approval-basis",
        required=True,
        help="who approved this reference and on what basis (recorded in the manifest)",
    )
    parser.add_argument(
        "--combined-briefing-schema-version",
        default=None,
        help="COMBINED_BRIEFING_SCHEMA_VERSION the reference was rendered under",
    )
    args = parser.parse_args()

    try:
        payload = build_manifest(
            reference=args.reference,
            case_id=args.case_id,
            approval_basis=args.approval_basis,
            combined_briefing_schema_version=args.combined_briefing_schema_version,
        )
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        load_manifest(args.manifest)
        receipt = compare_pdf_rasters(
            reference_path=args.reference,
            candidate_path=args.reference,
            manifest_path=args.manifest,
        )
        if receipt["status"] != "passed":
            raise VisualRegressionError(
                "Minted manifest does not accept its own reference: "
                + "; ".join(receipt.get("failure_reasons", []))
            )
    except VisualRegressionError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1

    print(
        json.dumps(
            {
                "status": "minted",
                "manifest": str(args.manifest),
                "reference": payload["reference_asset"],
                "page_count": len(payload["pages"]),
                "renderer": payload["renderer"],
                "provenance": payload["provenance"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
