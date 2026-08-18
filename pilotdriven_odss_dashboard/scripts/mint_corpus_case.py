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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--filename")
    parser.add_argument("--departure-iata")
    parser.add_argument("--destination-iata")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = manifest["cases"]

    if args.filename:
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
        })
        print(f"appended {args.case_id}: {cases[-1]['route_point_count']} waypoints")
    else:
        for index, case in enumerate(cases):
            source = args.corpus_dir / case["filename"]
            payload = analyse(source, flight_id=980000 + index)
            flight = payload["flight"]
            contract = payload.get("map_contract") or {}
            count = len(flight.get("route_waypoints") or [])
            route_hash = contract.get("route_hash")
            changed = (
                count != case["route_point_count"] or route_hash != case["route_hash"]
            )
            case["route_point_count"] = count
            case["route_hash"] = route_hash
            print(f"{'refreshed' if changed else 'unchanged'} {case['case_id']}: {count} waypoints")

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest now holds {len(cases)} cases")


if __name__ == "__main__":
    main()
