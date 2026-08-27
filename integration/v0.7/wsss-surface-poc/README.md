# ODSS v0.7 WSSS surface-NOTAM proof of concept

This package resolves selected WSSS runway/taxiway/taxilane NOTAM wording against a bounded, versioned OpenStreetMap surface graph and returns MapLibre-ready GeoJSON.

The official NOTAM is authoritative. OSM supplies candidate geometry only. This display is for briefing orientation and is not for navigation.

## Implemented

- whole taxiway/taxilane closure;
- closure between two taxiway intersections;
- `including junction` markers;
- `behind aircraft stand` and stand-range projection;
- aircraft-code restriction applicability;
- B/C validity and bounded D-schedule evaluation;
- high/medium/low/unmapped confidence;
- repeated red X markers along long closed segments;
- text-only fallback and original-NOTAM retention;
- MapLibre browser demo;
- historical WSSS regression cases A0783/25 and A0392/25.

## Architecture boundary

ODSS owns parsing, time applicability, graph resolution, aircraft applicability, confidence and GeoJSON. PilotDriven owns authentication, tenant context, storage and the responsive UI. No deterministic aviation calculation belongs in React.

## Local use

```bash
cd integration/v0.7/wsss-surface-poc
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/fetch_wsss_osm.py
pytest -q
python -m odss_surface
```

Open:

```text
http://127.0.0.1:8077/demo
```

## API example

```bash
curl -sS http://127.0.0.1:8077/v1/airports/WSSS/surface-resolve \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "notam_text": "A0783/25 NOTAMN\nA) WSSS B) 2503041800 C) 2503041900\nE) FLW TWY CLSD:\n1. TXL R7 BTN TWY R AND TXL R4, INCLUDING JUNCTION OF TXL R7/TXL R5\n2. TXL R5 BTN TXL R7 AND TWY R8",
  "briefing_time_utc": "2025-03-04T18:30:00Z",
  "aircraft_code": "F",
  "include_surface_geometry": true
}
JSON
```

## Snapshot policy

The GitHub workflow performs a bounded Overpass extraction, normalises it to a stable snapshot, runs the real-snapshot regression and commits:

```text
fixtures/wsss_surface_snapshot.json
fixtures/wsss_surface_coverage.json
fixtures/wsss_surface_sample_contract.json
```

Production must replace per-request public Overpass access with a scheduled controlled ingestion process. The public OSM tile service is not used for automated report generation; the existing Amazon Location/MapLibre/Playwright renderer remains the production basemap architecture.

## Promotion beyond proof of concept

Before WSSS is labelled operationally chart-checked, compare OSM reference and connectivity coverage with the current CAAS aerodrome and ground-movement charts, document material differences, and expand regression coverage for current NOTAM phrasing.
