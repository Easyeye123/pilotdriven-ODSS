from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import run_odss_analysis

EXPECTED = {
    "SQ303": {
        "source_sha256": "887d96b5a01ab42e841ca9a61ff4547f6e16facbf24695fb62d63b282c2a4177",
        "departure": "EBBR",
        "destination": "WSSS",
        "route_hash": "73af662d43350cd49c945af48febdf2da14d38099429ee3d87d2488353943f60",
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_takeoff_weight_kg": 245529,
            "planned_landing_weight_kg": 175802,
        },
    },
    "SQ304": {
        "source_sha256": "ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef",
        "departure": "WSSS",
        "destination": "EBBR",
        "route_hash": "90a055e3ec2fca7b83e7f10603d333b0104dae4f0175180dca85918049ff9f87",
        "masses": {
            "planned_zfw_kg": 175500,
            "planned_takeoff_weight_kg": 262222,
            "planned_landing_weight_kg": 184797,
        },
    },
}


def _run(name: str, source: Path, root: Path, flight_id: int) -> dict:
    expected = EXPECTED[name]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != expected["source_sha256"]:
        raise ValueError(
            f"{name} golden CFP checksum mismatch: expected {expected['source_sha256']}, got {source_hash}"
        )
    result = run_odss_analysis(
        source,
        root / "results",
        root / "reports",
        flight_id,
    )
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"]
    findings = payload["findings"]
    contract = payload["map_contract"]

    assert payload["schema_version"] == "0.6.0"
    assert flight["flight_number"] == name
    assert flight["departure"] == expected["departure"]
    assert flight["destination"] == expected["destination"]
    assert flight["masses"] == expected["masses"]
    assert len(flight["route_waypoints"]) >= 100
    assert contract["route_hash"] == expected["route_hash"]
    assert len(contract["route_geojson"]["features"]) == 1
    assert len(contract["markers_geojson"]["features"]) == len(flight["route_waypoints"])
    assert Path(result["level1_report"]).read_bytes().startswith(b"%PDF")
    assert Path(result["level2_report"]).read_bytes().startswith(b"%PDF")

    if name == "SQ303":
        assert flight.get("bobcat") is None
        assert len([item for item in findings if item["engine"] == "communications"]) == 5
        assert max(
            item["data"].get("maximum_msa_hundreds_ft", 0)
            for item in findings
            if item["engine"] == "terrain"
        ) == 166
        assert flight["edto"]["airports"][0]["airport"] == "VTBD"
    else:
        assert flight["bobcat"] == {
            "waypoint": "BIROS",
            "flight_level": 360,
            "cto_utc": "2026-07-12T21:58:00+00:00",
            "ctot_utc": "2026-07-12T16:25:00+00:00",
        }
        depressurisation = [item for item in findings if item["engine"] == "depressurisation"]
        assert [item["title"] for item in depressurisation] == [
            "High terrain detected but no profile matched"
        ]
        assert [item["airport"] for item in flight["edto"]["airports"]] == ["WIMM", "VCBI"]
        assert any(item["engine"] == "bobcat" for item in findings)

    return {
        "flight_number": name,
        "departure": flight["departure"],
        "destination": flight["destination"],
        "route_points": len(flight["route_waypoints"]),
        "route_hash": contract["route_hash"],
        "finding_count": len(findings),
        "level1_report": result["level1_report"],
        "level2_report": result["level2_report"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ODSS v0.6 SQ303/SQ304 golden cases.")
    parser.add_argument("--sq303", required=True, type=Path)
    parser.add_argument("--sq304", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    for path in (args.sq303, args.sq304):
        if not path.is_file():
            parser.error(f"Golden CFP not found: {path}")

    if args.output:
        root = args.output
        root.mkdir(parents=True, exist_ok=True)
        results = [
            _run("SQ303", args.sq303, root / "sq303", 303),
            _run("SQ304", args.sq304, root / "sq304", 304),
        ]
    else:
        with tempfile.TemporaryDirectory(prefix="odss-v06-golden-") as temporary:
            root = Path(temporary)
            results = [
                _run("SQ303", args.sq303, root / "sq303", 303),
                _run("SQ304", args.sq304, root / "sq304", 304),
            ]

    print(json.dumps({"status": "passed", "cases": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
