from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import fitz

from scripts.run_private_cfp_corpus import (
    REQUIRED_CASE_IDS,
    check_required_publication_markers,
    load_manifest,
    scan_physical_pdf,
)


MANIFEST = Path(__file__).with_name("private_cfp_corpus_manifest.json")
ROOT = Path(__file__).resolve().parents[1]


def test_private_release_manifest_holds_at_least_the_pinned_set():
    """The corpus only grows: every required case is pinned, new failures are
    minted in via scripts/mint_corpus_case.py, and nothing pins an exact size
    (an exact-size assert would need editing to admit a newly failing CFP)."""
    payload = load_manifest(MANIFEST)
    cases = payload["cases"]

    case_ids = {case["case_id"] for case in cases}
    # This is the exact boss-reviewed HelpYou/briefing flow.  Keep the literal
    # assertion as well as the generic subset check so a future edit cannot
    # remove the case from both the manifest and REQUIRED_CASE_IDS unnoticed.
    assert "SQ910-SIN-MNL-21AUG" in REQUIRED_CASE_IDS
    assert "SQ910-SIN-MNL-21AUG" in case_ids
    # SQ481 is the current literal boss-feedback OFP. Keep it pinned as a
    # release requirement, not merely present as an optional manifest row.
    assert "SQ481-JNB-SIN-25AUG" in REQUIRED_CASE_IDS
    assert "SQ481-JNB-SIN-25AUG" in case_ids
    assert REQUIRED_CASE_IDS <= case_ids
    assert len(case_ids) == len(cases), "case ids must be unique"
    assert len({case["filename"] for case in cases}) == len(cases)
    assert len({case["source_sha256"] for case in cases}) == len(cases)
    assert len({case["route_hash"] for case in cases}) == len(cases)
    # Plausibility floor only: a real LIDO briefing package is never a
    # few-page summary. The old >=52 bound was an artifact of the first
    # batch being exclusively long-haul (PER-SIN is a legitimate 51 pages).
    assert all(case["source_page_count"] >= 20 for case in cases)
    assert all(len(case["source_sha256"]) == 64 for case in cases)
    assert all(int(case["route_point_count"]) > 0 for case in cases)


def test_manifest_is_plain_json_and_contains_no_private_pdf_bytes():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["extraction_contract_version"] == 2
    assert MANIFEST.stat().st_size < 64_000


def test_odss_runtime_image_is_reachable_only_through_the_full_pytest_stage():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "RUN python -m pytest -q" in dockerfile
    assert "COPY --from=test /tmp/odss-tests-passed" in dockerfile


def test_private_corpus_checks_lossless_and_operational_publications():
    """The corpus proves both complete facts and the eight-page download."""
    runner = (ROOT / "scripts" / "run_private_cfp_corpus.py").read_text(
        encoding="utf-8"
    )
    production = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "include_audit_appendix=True" in runner
    assert "include_audit_appendix=False" in runner
    assert "_Operational_Flight_Briefing.pdf" in runner
    assert "include_audit_appendix=True" not in production


def test_required_markers_are_checked_on_the_surface_that_owns_them():
    case = {
        "departure_iata": "SIN",
        "departure": "WSSS",
        "destination_iata": "PER",
        "destination": "YPPH",
    }
    common = "FLIGHT BRIEFING SIN / WSSS PER / YPPH"
    phases = "RELEASE BEFORE PUSH ROUTE ARRIVAL WEATHER"

    assert check_required_publication_markers(
        case,
        audit_text=common,
        operational_text=f"{common} {phases}",
    ) == []
    assert check_required_publication_markers(
        case,
        audit_text=common,
        operational_text=common,
    ) == [
        "operational: RELEASE",
        "operational: BEFORE PUSH",
        "operational: ROUTE",
        "operational: ARRIVAL",
        "operational: WEATHER",
    ]
    assert check_required_publication_markers(
        case,
        audit_text="FLIGHT BRIEFING SIN / WSSS",
        operational_text=f"{common} {phases}",
    ) == ["audit: PER / YPPH"]

    # The former category/status-only strip must not certify a production PDF.
    assert "operational: BEFORE PUSH" in check_required_publication_markers(
        case,
        audit_text=common,
        operational_text=(
            f"{common} PERFORMANCE STATUS AIRPORTS WEATHER ROUTE OPEN REVIEW"
        ),
    )


def test_physical_scanner_accepts_a_readable_non_overlapping_page(tmp_path):
    output = tmp_path / "readable.pdf"
    with fitz.open() as document:
        page = document.new_page(width=841.89, height=595.28)
        page.insert_text(
            (50, 80),
            "FLIGHT BRIEFING synthetic physical release gate page with enough readable text.",
            fontsize=12,
        )
        page.insert_text(
            (50, 110),
            "The second line is separated and proves that the raster contains visible contrast.",
            fontsize=12,
        )
        document.save(output)

    result = scan_physical_pdf(output)

    assert result["valid"] is True
    assert result["page_count"] == 1
    assert result["pages"][0]["visible_overlap_count"] == 0
    assert result["pages"][0]["outside_text_box_count"] == 0
    assert result["pages"][0]["raster_has_contrast"] is True


def test_physical_scanner_rejects_visible_overlapping_text(tmp_path):
    output = tmp_path / "overlap.pdf"
    with fitz.open() as document:
        page = document.new_page(width=841.89, height=595.28)
        text = "FLIGHT BRIEFING overlapping synthetic text must stop the release immediately."
        page.insert_text((50, 80), text, fontsize=12)
        page.insert_text((50, 80), text, fontsize=12)
        document.save(output)

    result = scan_physical_pdf(output)

    assert result["valid"] is False
    assert result["pages"][0]["visible_overlap_count"] > 0
    assert any("overlap" in item["message"] for item in result["violations"])


def test_one_missing_private_cfp_makes_the_corpus_command_fail(tmp_path):
    corpus_dir = tmp_path / "empty-corpus"
    output_dir = tmp_path / "receipt"
    corpus_dir.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_private_cfp_corpus.py"),
            "--corpus-dir",
            str(corpus_dir),
            "--output",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(
        (output_dir / "private-cfp-corpus-receipt.json").read_text(encoding="utf-8")
    )

    assert completed.returncode != 0
    assert receipt["status"] == "failed"
    assert receipt["failed_case_count"] == receipt["expected_case_count"] > 0
    assert "Required private CFP is missing" in receipt["preflight_error"]
