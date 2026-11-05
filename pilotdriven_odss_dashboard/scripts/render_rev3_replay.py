"""Re-render the immutable historical visual input with today's renderer.

Only this layout test replays a private capture. The parser and live-source
corpus still run independently; their output is never replaced by this PDF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.odss.combined_brief import render_combined_briefing

DEFAULT_MANIFEST = ROOT / "tests" / "rev3_replay_input_manifest.json"


def checked_asset(path: Path, expected: dict) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.name != expected["filename"] or digest != expected["sha256"]:
        raise ValueError(f"Historical input identity mismatch: {path.name}")
    return digest


def render_replay(analysis: Path, source: Path, candidate: Path,
                  manifest_path: Path = DEFAULT_MANIFEST) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("gate") != "rev3-historical-input-replay":
        raise ValueError("Unexpected historical replay manifest")
    analysis_sha = checked_asset(analysis, manifest["analysis"])
    source_sha = checked_asset(source, manifest["source"])
    payload = json.loads(analysis.read_text())
    # Rebuild the view inside the current renderer. The stored view supplies
    # only its original warnings, exactly as in the source-corpus renderer.
    candidate.parent.mkdir(parents=True, exist_ok=True)
    render_combined_briefing(
        payload["flight"], payload["findings"],
        payload.get("view", {}).get("warnings") or [], candidate,
        source_pdf_path=str(source),
        weather_charts=payload.get("weather_charts") or {},
        include_audit_appendix=True,
    )
    return {
        "schema_version": 1,
        "gate": manifest["gate"],
        "status": "passed",
        "scope": "historical renderer only; live-source corpus is checked separately",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "analysis_sha256": analysis_sha,
        "source_sha256": source_sha,
        "candidate": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = render_replay(args.analysis, args.source, args.candidate)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt = {"status": "failed", "gate": "rev3-historical-input-replay", "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
