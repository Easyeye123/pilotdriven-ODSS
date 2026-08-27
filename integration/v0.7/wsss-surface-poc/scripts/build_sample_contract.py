#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odss_surface.contract import build_surface_contract  # noqa: E402
from odss_surface.osm import SurfaceGraph, load_snapshot  # noqa: E402
from odss_surface.resolver import resolve_surface_notam  # noqa: E402


def main() -> int:
    snapshot = ROOT / "fixtures" / "wsss_surface_snapshot.json"
    cases = json.loads((ROOT / "fixtures" / "wsss_regression_notams.json").read_text(encoding="utf-8"))
    graph = SurfaceGraph(load_snapshot(snapshot))
    case = cases[0]
    findings = resolve_surface_notam(
        graph,
        case["raw"],
        briefing_time_utc=case["briefing_time_utc"],
        selected_aircraft_code="F",
    )
    contract = build_surface_contract(
        graph,
        findings,
        briefing_time_utc=case["briefing_time_utc"],
        include_surface_geometry=True,
    )
    output = ROOT / "fixtures" / "wsss_surface_sample_contract.json"
    output.write_text(json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {output} with {len(contract['notam_overlays_geojson']['features'])} overlay features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
