from __future__ import annotations

import json
from pathlib import Path

import pytest

from odss_surface.osm import SurfaceGraph, load_snapshot
from odss_surface.resolver import resolve_surface_notam

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "fixtures" / "wsss_surface_snapshot.json"


@pytest.mark.skipif(not SNAPSHOT.is_file(), reason="WSSS OSM snapshot not fetched")
def test_real_wsss_snapshot_resolves_historical_r7_r5_case():
    graph = SurfaceGraph(load_snapshot(SNAPSHOT))
    required = {"R", "R4", "R5", "R7", "R8"}
    assert required <= set(graph.available_refs)
    case = json.loads((ROOT / "fixtures" / "wsss_regression_notams.json").read_text())[0]
    findings = resolve_surface_notam(
        graph,
        case["raw"],
        briefing_time_utc=case["briefing_time_utc"],
    )
    assert len(findings) == 2
    assert all(item.mapped for item in findings)
    assert all(item.x_coordinates for item in findings)
