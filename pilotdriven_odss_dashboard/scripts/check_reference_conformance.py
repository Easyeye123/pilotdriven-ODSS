"""Release gate: the Download PDF still matches David's reference format.

He asked the question himself on 9 Sep 2026 at 21:22:52 - "So you have to check
and make sure the memory losses and standard established does not degenerate.
How do you ensure that???"

This gate is that answer. For each flight it

1. runs the real analysis on a real private-corpus OFP,
2. renders the briefing through ``render_combined_briefing`` with
   ``include_audit_appendix=False`` - the exact call the Download PDF button
   makes in ``app/main.py`` - so it can never certify an artefact pilots do not
   receive, and
3. reads the physical PDF back and compares it with the structure minted from
   his own reference briefings in ``tests/boss_reference_format_manifest.json``.

Any drift - a page dropped, a section renamed, the ribbon gone, a page-1 tile
or the release strip missing, the decision grid or the flight-phase timeline
lost - fails the release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.odss.reference_conformance import (  # noqa: E402
    MANIFEST_GATE,
    DEFAULT_MANIFEST,
    ReferenceConformanceError,
    check_reference_conformance,
    extract_reference_structure,
    load_manifest,
    sha256_file,
)

# The flights this round is actually about: the three he sent reference
# briefings for, the flight he said had "degenerated to somewhat much simpler
# and less user friendly", and the pack he drove on video the same evening.
DEFAULT_CASES = (
    "SQ910-SIN-MNL-21AUG",
    "SQ481-JNB-SIN-25AUG",
    "SQ38-SIN-LAX-29AUG",
    "SQ605-ICN-SIN-08SEP",
    "SQ882-SIN-HKG-09SEP",
)
CORPUS_MANIFEST = ROOT / "tests" / "private_cfp_corpus_manifest.json"


def verify_against_reference_files(manifest: dict, reference_dir: Path) -> list[dict]:
    """Prove the pinned structure still belongs to David's own documents."""
    checked = []
    for entry in manifest["minted_from"]:
        path = Path(reference_dir) / entry["filename"]
        if not path.is_file():
            raise ReferenceConformanceError(
                f"Reference briefing {entry['filename']} is not in {reference_dir}"
            )
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise ReferenceConformanceError(
                f"{entry['filename']} is not the file the structure was minted from"
            )
        if entry.get("role") == "primary":
            rederived = extract_reference_structure(path)
            pinned = dict(manifest["reference_structure"])
            variants = pinned["overview"].pop("tile_provenance_tag_variants", None)
            if rederived != pinned:
                raise ReferenceConformanceError(
                    f"The pinned structure no longer matches {entry['filename']}; "
                    "re-mint it rather than editing the manifest"
                )
            if variants is not None:
                pinned["overview"]["tile_provenance_tag_variants"] = variants
        checked.append({"filename": entry["filename"], "sha256": digest})
    return checked


def corpus_source(corpus_dir: Path, case_id: str) -> Path:
    cases = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))["cases"]
    case = next((item for item in cases if item["case_id"] == case_id), None)
    if case is None:
        raise ReferenceConformanceError(f"{case_id} is not in the private CFP corpus manifest")
    source = Path(corpus_dir) / case["filename"]
    if not source.is_file():
        raise ReferenceConformanceError(f"Corpus source for {case_id} is missing: {source}")
    return source


def render_production_download(source: Path, work_dir: Path, case_id: str) -> Path:
    """Render exactly what the Download PDF button renders."""
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    case_root = Path(work_dir) / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    result = run_odss_analysis(source, case_root / "analysis", case_root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    candidate = case_root / f"{case_id}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"],
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        candidate,
        source_pdf_path=str(source),
        weather_charts=payload.get("weather_charts") or {},
        # app/main.py never passes include_audit_appendix; neither does this
        # gate. A gate that certifies the audit composition certifies an
        # artefact no pilot downloads.
    )
    return candidate


def run(corpus_dir: Path, cases: list[str], manifest_path: Path, work_dir: Path,
        reference_dir: Path | None) -> dict:
    manifest = load_manifest(manifest_path)
    structure = manifest["reference_structure"]
    extensions = manifest.get("contract_extensions") or {}
    reference_files: list[dict] = []
    if reference_dir is not None:
        reference_files = verify_against_reference_files(manifest, reference_dir)

    results = []
    for case_id in cases:
        source = corpus_source(corpus_dir, case_id)
        candidate = render_production_download(source, work_dir, case_id)
        outcome = check_reference_conformance(
            candidate, structure=structure, contract_extensions=extensions
        )
        results.append(
            {
                "case_id": case_id,
                "source": source.name,
                "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "valid": outcome["valid"],
                "violations": outcome["violations"],
            }
        )

    failed = [item for item in results if not item["valid"]]
    return {
        "schema_version": 1,
        "gate": MANIFEST_GATE,
        "status": "failed" if failed else "passed",
        "publication_path": "render_combined_briefing(include_audit_appendix=False)",
        "manifest_sha256": sha256_file(manifest_path),
        "reference_files": reference_files,
        "reference_structure_verified_against_files": bool(reference_files),
        "cases": results,
        "failed_cases": [item["case_id"] for item in failed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--reference-dir", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", dest="cases", default=None)
    args = parser.parse_args()

    temporary = None
    work_dir = args.work_dir
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="reference-conformance-")
        work_dir = Path(temporary.name)
    try:
        receipt = run(
            args.corpus_dir,
            list(args.cases or DEFAULT_CASES),
            args.manifest,
            Path(work_dir),
            args.reference_dir,
        )
    except (OSError, ReferenceConformanceError, KeyError, TypeError, ValueError) as exc:
        receipt = {
            "schema_version": 1,
            "gate": MANIFEST_GATE,
            "status": "failed",
            "error": str(exc),
        }
    finally:
        if temporary is not None:
            temporary.cleanup()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if receipt["status"] == "passed":
        print(f"Reference-format conformance passed for {len(receipt['cases'])} flight(s)")
        return 0
    print(json.dumps(receipt, indent=2), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
