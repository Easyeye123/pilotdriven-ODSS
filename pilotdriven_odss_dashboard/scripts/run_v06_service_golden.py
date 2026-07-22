from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.database as database
import app.main as main_app
import app.odss_map_v06.report_worker as report_worker

EXPECTED = {
    "SQ303": {
        "source_sha256": "887d96b5a01ab42e841ca9a61ff4547f6e16facbf24695fb62d63b282c2a4177",
        "direction": "EBBR->WSSS",
        "route_hash": "73af662d43350cd49c945af48febdf2da14d38099429ee3d87d2488353943f60",
        "markers": 143,
    },
    "SQ304": {
        "source_sha256": "ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef",
        "direction": "WSSS->EBBR",
        "route_hash": "90a055e3ec2fca7b83e7f10603d333b0104dae4f0175180dca85918049ff9f87",
        "markers": 146,
    },
}


def _configure(output: Path, token: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    database.DB_PATH = output / "odss.db"
    main_app.UPLOAD_DIR = output / "uploads"
    main_app.REPORT_DIR = output / "reports"
    main_app.RESULT_DIR = output / "results"
    report_worker.MAP_DIR = output / "maps"
    os.environ["ODSS_SERVICE_TOKEN"] = token
    os.environ.pop("AWS_LOCATION_API_KEY", None)


def _case(client: TestClient, name: str, path: Path, token: str) -> dict:
    expected = EXPECTED[name]
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if source_hash != expected["source_sha256"]:
        raise ValueError(
            f"{name} golden CFP checksum mismatch: expected {expected['source_sha256']}, got {source_hash}"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-PilotDriven-Tenant-Id": "golden-tenant",
        "X-PilotDriven-User-Id": "golden-runner",
        "X-PilotDriven-Workspace-Id": "golden-regression",
        "X-PilotDriven-Flight-Id": name,
    }
    with path.open("rb") as source:
        response = client.post(
            "/v1/analyses",
            headers=headers,
            files={"file": (path.name, source, "application/pdf")},
        )
    response.raise_for_status()
    analysis = response.json()
    analysis_id = analysis["analysis_id"]
    contract_response = client.get(
        f"/v1/analyses/{analysis_id}/map-contract",
        headers=headers,
    )
    contract_response.raise_for_status()
    contract = contract_response.json()
    fallback_response = client.get(
        f"/v1/analyses/{analysis_id}/map-fallback",
        headers=headers,
    )
    fallback_response.raise_for_status()
    render_response = client.post(
        f"/v1/analyses/{analysis_id}/reports/render",
        headers=headers,
    )
    render_response.raise_for_status()
    briefing_response = client.get(
        f"/v1/analyses/{analysis_id}/briefing",
        headers=headers,
    )
    briefing_response.raise_for_status()
    briefing = briefing_response.json()

    direction = f"{analysis['flight']['departure']}->{analysis['flight']['destination']}"
    assert direction == expected["direction"]
    assert contract["route_hash"] == expected["route_hash"]
    assert len(contract["markers_geojson"]["features"]) == expected["markers"]
    assert fallback_response.headers["x-odss-map-mode"] == "schematic-fallback"
    assert render_response.json()["map_render"]["mode"] == "schematic-fallback"

    return {
        "analysis_id": analysis_id,
        "status": analysis["status"],
        "direction": direction,
        "route_hash": contract["route_hash"],
        "markers": len(contract["markers_geojson"]["features"]),
        "fallback_mode": fallback_response.headers["x-odss-map-mode"],
        "report_render_mode": render_response.json()["map_render"]["mode"],
        "warnings": briefing.get("warnings") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real SQ303/SQ304 CFPs through the versioned ODSS service API."
    )
    parser.add_argument("--sq303", required=True, type=Path)
    parser.add_argument("--sq304", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    for source in (args.sq303, args.sq304):
        if not source.is_file():
            parser.error(f"Golden CFP not found: {source}")

    token = "odss-v06-golden-service-token"
    _configure(args.output, token)
    with TestClient(main_app.app, follow_redirects=False) as client:
        summary = {
            "SQ303": _case(client, "SQ303", args.sq303, token),
            "SQ304": _case(client, "SQ304", args.sq304, token),
        }

    destination = args.output / "service_golden_summary.json"
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
