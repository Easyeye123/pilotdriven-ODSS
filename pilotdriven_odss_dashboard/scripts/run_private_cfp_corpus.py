from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urlsplit

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing
from app.odss.report_quality import validate_combined_briefing_pdf


DEFAULT_MANIFEST = ROOT / "tests" / "private_cfp_corpus_manifest.json"
EXPECTED_CORPUS_SIZE = 11
DEFERRED_TYPES = {"MEL", "CDL", "CDDL"}
DEFERRED_REFERENCE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if payload.get("schema_version") != 1 or not isinstance(cases, list):
        raise ValueError("Private CFP corpus manifest must use schema version 1.")
    if len(cases) != EXPECTED_CORPUS_SIZE:
        raise ValueError(
            f"Private CFP corpus must contain exactly {EXPECTED_CORPUS_SIZE} cases; "
            f"manifest contains {len(cases)}."
        )
    filenames: set[str] = set()
    hashes: set[str] = set()
    case_ids: set[str] = set()
    required = {
        "case_id",
        "filename",
        "source_sha256",
        "source_page_count",
        "flight_number",
        "departure",
        "destination",
        "departure_iata",
        "destination_iata",
        "route_point_count",
        "route_hash",
    }
    for case in cases:
        if not isinstance(case, dict) or required - set(case):
            missing = sorted(required - set(case if isinstance(case, dict) else {}))
            raise ValueError(f"Private CFP corpus case is incomplete: {missing}.")
        filename = Path(str(case["filename"]))
        if filename.is_absolute() or filename.name != str(filename) or ".." in filename.parts:
            raise ValueError(f"Private CFP corpus filename must be relative: {filename}.")
        source_hash = str(case["source_sha256"])
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError(f"Private CFP corpus hash is malformed for {case['case_id']}.")
        if (
            str(filename) in filenames
            or source_hash in hashes
            or str(case["case_id"]) in case_ids
        ):
            raise ValueError("Private CFP corpus filenames, hashes and case IDs must be unique.")
        filenames.add(str(filename))
        hashes.add(source_hash)
        case_ids.add(str(case["case_id"]))
    return payload


def preflight_source(case: dict[str, Any], corpus_dir: Path) -> dict[str, Any]:
    source = corpus_dir / str(case["filename"])
    if not source.is_file():
        raise FileNotFoundError(f"Required private CFP is missing: {case['filename']}.")
    source_hash = sha256_file(source)
    if source_hash != case["source_sha256"]:
        raise ValueError(
            f"{case['case_id']} source hash mismatch: expected "
            f"{case['source_sha256']}, got {source_hash}."
        )
    with fitz.open(source) as document:
        source_page_count = len(document)
    if source_page_count != int(case["source_page_count"]):
        raise ValueError(
            f"{case['case_id']} source page mismatch: expected "
            f"{case['source_page_count']}, got {source_page_count}."
        )
    return {
        "source": source,
        "source_sha256": source_hash,
        "source_page_count": source_page_count,
    }


def _ink_rect(word: tuple[Any, ...]) -> fitz.Rect:
    rect = fitz.Rect(word[:4])
    inset = rect.height * 0.22
    return fitz.Rect(rect.x0, rect.y0 + inset, rect.x1, rect.y1 - inset)


def scan_physical_pdf(path: Path) -> dict[str, Any]:
    """Render and geometrically inspect every physical output page."""
    violations: list[dict[str, Any]] = []
    page_receipts: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            words = page.get_text("words")
            text = page.get_text().strip()
            outside = []
            for word in words:
                rect = fitz.Rect(word[:4])
                if (
                    rect.x0 < -0.5
                    or rect.y0 < -0.5
                    or rect.x1 > page.rect.width + 0.5
                    or rect.y1 > page.rect.height + 0.5
                ):
                    outside.append(str(word[4]))

            ink = [_ink_rect(word) for word in words]
            overlaps = []
            for index, left in enumerate(ink):
                for right in ink[index + 1 :]:
                    intersection = left & right
                    if (
                        not intersection.is_empty
                        and intersection.width > 1.0
                        and intersection.height > 1.5
                    ):
                        overlaps.append({
                            "left": [round(value, 2) for value in left],
                            "right": [round(value, 2) for value in right],
                        })
                        if len(overlaps) >= 10:
                            break
                if len(overlaps) >= 10:
                    break

            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(0.4, 0.4),
                colorspace=fitz.csGRAY,
                alpha=False,
            )
            samples = pixmap.samples
            raster_has_contrast = bool(samples) and min(samples) != max(samples)
            page_violations = []
            if len(text) < 50:
                page_violations.append("page has less than 50 characters of readable text")
            if outside:
                page_violations.append(f"{len(outside)} text boxes extend outside the page")
            if overlaps:
                page_violations.append(f"{len(overlaps)} visible text overlaps were detected")
            if not raster_has_contrast:
                page_violations.append("physical raster has no visible contrast")
            for message in page_violations:
                violations.append({"page": page_number, "message": message})
            page_receipts.append({
                "page": page_number,
                "text_characters": len(text),
                "word_count": len(words),
                "outside_text_box_count": len(outside),
                "visible_overlap_count": len(overlaps),
                "raster_width": pixmap.width,
                "raster_height": pixmap.height,
                "raster_has_contrast": raster_has_contrast,
                "violations": page_violations,
            })
    return {
        "valid": not violations,
        "page_count": len(page_receipts),
        "pages": page_receipts,
        "violations": violations,
    }


def deferred_items(flight: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for item in flight.get("deferred_items") or []:
        item_type = str(item.get("item_type") or "").strip().upper()
        reference = str(item.get("reference") or "").strip().upper()
        key = (item_type, reference)
        if (
            item_type not in DEFERRED_TYPES
            or not DEFERRED_REFERENCE.fullmatch(reference)
            or not any(character.isdigit() for character in reference)
            or key in seen
        ):
            continue
        seen.add(key)
        rows.append({
            "type": item_type,
            "reference": reference,
            "has_cfp_remark": bool(str(item.get("company_remark") or "").strip()),
        })
    return rows


def governed_link_parameters(uri: str) -> dict[str, list[str]] | None:
    parts = urlsplit(uri)
    fragment_path, separator, fragment_query = parts.fragment.partition("?")
    if "governed-deferred-reference" not in fragment_path or not separator:
        return None
    return parse_qs(fragment_query)


def inspect_deferred_contract(
    output: Path,
    flight: dict[str, Any],
) -> dict[str, Any]:
    expected = deferred_items(flight)
    all_text = []
    link_parameters = []
    with fitz.open(output) as document:
        for page in document:
            all_text.append(page.get_text())
            for link in page.get_links():
                if link.get("uri"):
                    parameters = governed_link_parameters(str(link["uri"]))
                    if parameters is not None:
                        link_parameters.append(parameters)
    folded_text = "\n".join(all_text).upper()
    missing_links = []
    missing_labels = []
    for item in expected:
        matching = [
            parameters
            for parameters in link_parameters
            if parameters.get("type") == [item["type"]]
            and parameters.get("reference") == [item["reference"]]
            and parameters.get("flightNumber") == [str(flight.get("flight_number") or "")]
        ]
        if len(matching) != 1:
            missing_links.append({**item, "matching_link_count": len(matching)})
        if item["has_cfp_remark"]:
            label = f"CFP REMARK - NOT THE APPROVED {item['type']} REMEDY"
            if label not in folded_text:
                missing_labels.append(label)
    return {
        "valid": not missing_links and not missing_labels,
        "expected_reference_count": len(expected),
        "governed_link_count": len(link_parameters),
        "missing_or_duplicate_links": missing_links,
        "missing_truth_labels": missing_labels,
    }


def run_case(
    case: dict[str, Any],
    preflight: dict[str, Any],
    output_root: Path,
    flight_id: int,
) -> dict[str, Any]:
    case_root = output_root / str(case["case_id"])
    result = run_odss_analysis(
        preflight["source"],
        case_root / "analysis",
        case_root / "legacy-reports",
        flight_id,
    )
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"]
    map_contract = payload.get("map_contract") or {}
    checks = {
        "flight_number": flight.get("flight_number") == case["flight_number"],
        "departure": flight.get("departure") == case["departure"],
        "destination": flight.get("destination") == case["destination"],
        "route_point_count": len(flight.get("route_waypoints") or []) == int(case["route_point_count"]),
        "route_hash": map_contract.get("route_hash") == case["route_hash"],
        "analysis_status": result.get("status") == "Completed",
        "analysis_report_refresh": result.get("report_refresh_state") == "current",
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise AssertionError(
            f"{case['case_id']} deterministic analysis mismatch: {', '.join(failed_checks)}."
        )

    combined = case_root / f"{case['case_id']}_Flight_Briefing.pdf"
    render_combined_briefing(
        flight,
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        combined,
        source_pdf_path=str(preflight["source"]),
        weather_charts=payload.get("weather_charts") or {},
    )
    quality = validate_combined_briefing_pdf(combined)
    if not quality["valid"]:
        raise AssertionError(
            f"{case['case_id']} report quality failed: "
            + "; ".join(item.message for item in quality["violations"])
        )
    physical = scan_physical_pdf(combined)
    if not physical["valid"]:
        raise AssertionError(
            f"{case['case_id']} physical PDF failed: {physical['violations'][:3]}."
        )
    with fitz.open(combined) as document:
        output_text = "\n".join(page.get_text() for page in document).upper()
    required_text = (
        "FLIGHT BRIEFING",
        "CFP PAGE 1 - FLIGHT PLAN",
        f"{case['departure_iata']} / {case['departure']}",
        f"{case['destination_iata']} / {case['destination']}",
    )
    missing_text = [marker for marker in required_text if marker.upper() not in output_text]
    if missing_text:
        raise AssertionError(
            f"{case['case_id']} output is missing required text: {missing_text}."
        )
    deferred = inspect_deferred_contract(combined, flight)
    if not deferred["valid"]:
        raise AssertionError(
            f"{case['case_id']} governed deferred-item contract failed: {deferred}."
        )
    return {
        "case_id": case["case_id"],
        "status": "passed",
        "source_filename": case["filename"],
        "source_sha256": preflight["source_sha256"],
        "source_page_count": preflight["source_page_count"],
        "flight_number": flight["flight_number"],
        "departure": flight["departure"],
        "destination": flight["destination"],
        "route_point_count": len(flight.get("route_waypoints") or []),
        "route_hash": map_contract["route_hash"],
        "combined_pdf": str(combined.relative_to(output_root)),
        "combined_sha256": sha256_file(combined),
        "combined_page_count": quality["page_count"],
        "physical_pdf": {
            "page_count": physical["page_count"],
            "outside_text_box_count": sum(
                page["outside_text_box_count"] for page in physical["pages"]
            ),
            "visible_overlap_count": sum(
                page["visible_overlap_count"] for page in physical["pages"]
            ),
            "blank_or_flat_page_count": sum(
                not page["raster_has_contrast"] or page["text_characters"] < 50
                for page in physical["pages"]
            ),
        },
        "deferred_contract": deferred,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the mandatory 11-CFP private physical-PDF release corpus."
    )
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    receipt_path = output_root / "private-cfp-corpus-receipt.json"
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "gate": "private-11-cfp-physical-pdf",
        "status": "failed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": None,
        "expected_case_count": EXPECTED_CORPUS_SIZE,
        "passed_case_count": 0,
        "failed_case_count": 0,
        "cases": [],
    }
    try:
        manifest = load_manifest(args.manifest)
        receipt["manifest_sha256"] = sha256_file(args.manifest)
        preflights = []
        for case in manifest["cases"]:
            preflights.append(preflight_source(case, args.corpus_dir.resolve()))

        for index, (case, preflight) in enumerate(zip(manifest["cases"], preflights), start=1):
            print(f"[{index}/{EXPECTED_CORPUS_SIZE}] {case['case_id']} - analysing and rendering")
            try:
                case_receipt = run_case(case, preflight, output_root, 9000 + index)
            except Exception as exc:
                case_receipt = {
                    "case_id": case["case_id"],
                    "status": "failed",
                    "source_filename": case["filename"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            receipt["cases"].append(case_receipt)
        receipt["passed_case_count"] = sum(
            case["status"] == "passed" for case in receipt["cases"]
        )
        receipt["failed_case_count"] = len(receipt["cases"]) - receipt["passed_case_count"]
        receipt["status"] = "passed" if receipt["failed_case_count"] == 0 else "failed"
    except Exception as exc:
        receipt["preflight_error_type"] = type(exc).__name__
        receipt["preflight_error"] = str(exc)
        receipt["failed_case_count"] = EXPECTED_CORPUS_SIZE
    write_receipt(receipt_path, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "passed": receipt["passed_case_count"],
        "failed": receipt["failed_case_count"],
        "receipt": str(receipt_path),
    }, indent=2))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
