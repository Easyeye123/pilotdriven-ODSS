"""Mint or refresh private-corpus manifest cases from their source PDFs.

Usage:
    .venv/bin/python scripts/mint_corpus_case.py --corpus-dir <dir> \
        [--case-id SQ223-SIN-PER-18AUG --filename SQ22318082026SIN.pdf \
         --departure-iata SIN --destination-iata PER]

Without --filename, every existing manifest case is re-analysed and its
route_point_count / route_hash refreshed in place (used after parser fixes;
a corpus flight's pinned numbers must always describe the current, complete
parse). With --filename, a new case is appended.

The gate's rule is "at least the pinned set": whenever a CFP exposes a
defect, mint it here and it is protected forever.

The manifest records the extraction token (app/odss/extraction_rules.py) its
identities were minted under. A refresh that moves any case's route or
extraction identity under the token it was minted under is refused: the parser
changed what it holds, so a pack saved before the change must reopen as an
older extraction, and that needs a new token in both repos (F9 of Codex's
independent QA of release 468, 10 Oct 2026). Appending a case to a manifest
minted under another token is refused until every case is refreshed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import run_odss_analysis
from app.odss.extraction_rules import EXTRACTION_RULES
from run_private_cfp_corpus import (
    EXTRACTION_CONTRACT_VERSION,
    build_extraction_snapshot,
)

MANIFEST = ROOT / "tests" / "private_cfp_corpus_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyse(source: Path, flight_id: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="mint-corpus-") as scratch:
        work = Path(scratch)
        result = run_odss_analysis(
            source, work / "analysis", work / "legacy-reports", flight_id
        )
        if result.get("status") != "Completed":
            raise SystemExit(f"{source.name}: analysis status {result.get('status')!r}")
        return json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))


def extraction_expectations(flight: dict) -> dict:
    snapshot = build_extraction_snapshot(flight)
    if snapshot["structure_failures"]:
        raise SystemExit(
            "Cannot mint an incomplete extraction baseline: "
            + "; ".join(snapshot["structure_failures"])
        )
    return {
        "counts": snapshot["counts"],
        "identity_sha256": snapshot["identity_sha256"],
    }


def unchanged_token_refusal(recorded: str | None, current: str, moved_case_ids: list[str]) -> str | None:
    """Why a remint must not be written, or None when it may be."""
    if moved_case_ids and recorded == current:
        return (
            f"{len(moved_case_ids)} case(s) changed route or extraction identity under the extraction token they were "
            f"minted under ({current}): {', '.join(moved_case_ids)}. Bump EXTRACTION_RULES in app/odss/extraction_rules.py "
            "and CURRENT_EXTRACTION_RULES in the app together, then remint; nothing was written."
        )
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--filename")
    parser.add_argument("--departure-iata")
    parser.add_argument("--destination-iata")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["extraction_contract_version"] = EXTRACTION_CONTRACT_VERSION
    cases = manifest["cases"]

    if args.filename:
        if manifest.get("extraction_rules") != EXTRACTION_RULES:
            raise SystemExit(
                f"The manifest was minted under extraction {manifest.get('extraction_rules')!r}, not {EXTRACTION_RULES}; "
                "refresh every case first (run without --filename)."
            )
        if not (args.case_id and args.departure_iata and args.destination_iata):
            raise SystemExit("--filename needs --case-id, --departure-iata, --destination-iata")
        if any(case["case_id"] == args.case_id for case in cases):
            raise SystemExit(f"case_id {args.case_id} already exists")
        source = args.corpus_dir / args.filename
        payload = analyse(source, flight_id=990000 + len(cases))
        flight = payload["flight"]
        contract = payload.get("map_contract") or {}
        cases.append({
            "case_id": args.case_id,
            "filename": args.filename,
            "source_sha256": sha256_file(source),
            "source_page_count": fitz.open(source).page_count,
            "flight_number": flight.get("flight_number"),
            "departure": flight.get("departure"),
            "destination": flight.get("destination"),
            "departure_iata": args.departure_iata,
            "destination_iata": args.destination_iata,
            "route_point_count": len(flight.get("route_waypoints") or []),
            "route_hash": contract.get("route_hash"),
            "extraction_expectations": extraction_expectations(flight),
        })
        print(f"appended {args.case_id}: {cases[-1]['route_point_count']} waypoints")
    else:
        moved: list[str] = []
        for index, case in enumerate(cases):
            source = args.corpus_dir / case["filename"]
            payload = analyse(source, flight_id=980000 + index)
            flight = payload["flight"]
            contract = payload.get("map_contract") or {}
            count = len(flight.get("route_waypoints") or [])
            route_hash = contract.get("route_hash")
            expectations = extraction_expectations(flight)
            changed = (
                count != case["route_point_count"] or route_hash != case["route_hash"]
            )
            if changed or expectations != case.get("extraction_expectations"):
                moved.append(case["case_id"])
            case["route_point_count"] = count
            case["route_hash"] = route_hash
            case["extraction_expectations"] = expectations
            print(f"{'refreshed' if changed else 'unchanged'} {case['case_id']}: {count} waypoints")
        refusal = unchanged_token_refusal(manifest.get("extraction_rules"), EXTRACTION_RULES, moved)
        if refusal:
            raise SystemExit(refusal)

    manifest["extraction_rules"] = EXTRACTION_RULES
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"manifest now holds {len(cases)} cases")


if __name__ == "__main__":
    main()
