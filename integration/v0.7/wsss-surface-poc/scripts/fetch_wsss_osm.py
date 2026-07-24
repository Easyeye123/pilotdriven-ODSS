#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odss_surface.osm import SurfaceGraph, load_snapshot, normalise_overpass_payload  # noqa: E402

BBOX = (1.315, 103.965, 1.385, 104.020)  # south, west, north, east
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
QUERY = f'''[out:json][timeout:90];
(
  way["aeroway"~"^(taxiway|taxilane|runway|apron)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["aeroway"~"^(holding_position|parking_position)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out body geom;'''
REQUIRED_REFS = {"P7", "P8", "Q", "R", "R4", "R5", "R7", "R8"}


def fetch() -> dict:
    encoded = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    errors: list[str] = []
    for endpoint in ENDPOINTS:
        for attempt in range(1, 4):
            request = urllib.request.Request(
                endpoint,
                data=encoded,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                    "User-Agent": "PilotDriven-ODSS-WSSS-Surface-POC/0.7 (+https://github.com/Easyeye123/pilotdriven-ODSS)",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                    return json.load(response)
            except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
                errors.append(f"{endpoint} attempt {attempt}: {type(exc).__name__}: {exc}")
                time.sleep(min(15, attempt * 3))
    raise RuntimeError("All Overpass requests failed:\n" + "\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "fixtures" / "wsss_surface_snapshot.json",
    )
    parser.add_argument(
        "--coverage-output",
        type=Path,
        default=ROOT / "fixtures" / "wsss_surface_coverage.json",
    )
    parser.add_argument("--raw-output", type=Path, default=None)
    parser.add_argument("--allow-missing-required-refs", action="store_true")
    args = parser.parse_args()

    payload = fetch()
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    normalized = normalise_overpass_payload(payload, airport="WSSS", bbox=BBOX)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")

    graph = SurfaceGraph(load_snapshot(args.output))
    available = set(graph.available_refs)
    missing = sorted(REQUIRED_REFS - available)
    coverage = {
        "airport": "WSSS",
        "source_timestamp": graph.snapshot.source_timestamp,
        "bbox": {
            "south": BBOX[0],
            "west": BBOX[1],
            "north": BBOX[2],
            "east": BBOX[3],
        },
        "required_refs": sorted(REQUIRED_REFS),
        "missing_required_refs": missing,
        **graph.coverage,
    }
    args.coverage_output.parent.mkdir(parents=True, exist_ok=True)
    args.coverage_output.write_text(json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(coverage, indent=2))
    if missing and not args.allow_missing_required_refs:
        print(
            "Required WSSS references missing from OSM snapshot: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
