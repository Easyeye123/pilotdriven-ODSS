# PilotDriven ODSS Personal Dashboard

A local FastAPI application for uploading supported Lido CFP PDFs, running deterministic ODSS analysis and generating Level 1 and Level 2 reports.

## Current working baseline — v0.5

The dashboard currently supports:

- CFP section and Page 1 parsing;
- route-log waypoints and coordinates;
- Page 1 MEL/CDL/CDDL extraction;
- fuel, mass and take-off performance;
- NOTAM and weather filtering;
- BOBCAT;
- EDTO;
- MSA greater than `100*`;
- VWS greater than 4;
- route-aware depressurisation profiles;
- early FIR/ATC calls;
- actual takeoff time and waypoint-ATA re-anchoring;
- personal notes with report-placement controls;
- canonical analysis JSON;
- three-page Level 1 report;
- expanded Level 2 report;
- offline schematic route map.

The schematic map is a functional fallback and is not the final realistic PilotDriven map.

## ODSS v0.6 integration handoff

The complete Phase 1–7 reference implementation is under:

```text
../integration/v0.6/
```

It contains:

- versioned map contract;
- route and marker GeoJSON;
- stable route hash;
- marker roles and label priorities;
- Amazon Location Hybrid / MapLibre adapter;
- Playwright PDF map capture;
- Amazon Location static fallback;
- schematic offline fallback;
- FastAPI map endpoints;
- print-map HTML/JavaScript/CSS;
- React/Next.js PilotDriven component;
- tests and runbooks.

Read:

```text
../docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md
../docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md
../docs/architecture/ADR-006-realistic-map-rendering.md
```

## Run the v0.5 dashboard locally

```bash
cd pilotdriven_odss_dashboard

python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

For source development:

```bash
python -m uvicorn app.main:app \
  --reload \
  --reload-exclude ".venv/*" \
  --host 127.0.0.1 \
  --port 8000
```

Do not let WatchFiles monitor the in-project virtual environment.

## Enable v0.6 map dependencies

```bash
python -m pip install \
  -r ../integration/v0.6/reference/requirements-map.txt

python -m playwright install chromium
```

Copy `.env.example` to `.env` and configure the Amazon Location key.

## Operational clock

1. Run the CFP analysis.
2. Enter actual takeoff time, or select a waypoint and enter actual ATA.
3. The engine preserves CFP ACTM and derives calculated UTC.
4. Reports and canonical JSON are regenerated.

## Personal notes

Notes may be assigned to:

- separate personal-notes section;
- departure airport;
- destination airport;
- enroute ATC/communications.

Each note can be included in Level 1, Level 2 or both. Notes are labelled as pilot-entered and not ODSS-validated.

## Test

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m compileall -q app
pytest -q
```

The v0.6 reference tests run separately:

```bash
cd ../integration/v0.6/reference
PYTHONPATH=. pytest -q
```

## Data directories

```text
data/odss.db        local SQLite records
data/uploads/       source CFP PDFs
data/results/       canonical ODSS JSON
data/reports/       generated reports
```

These files are local and must not be committed.

## Integration boundary

The future PilotDriven frontend should consume ODSS contracts and APIs. It may own presentation, mapping controls, identity, storage and tenancy, but it must not independently recalculate deterministic operational conclusions.

## Limitations

- The parser currently supports the validated Lido layouts only.
- The bundled reference items are not a substitute for operator-approved MEL/CDL, AIP/Jeppesen or depressurisation material.
- The map is for briefing orientation only and not for navigation.
- The system is decision support and does not replace dispatch authority or commander judgement.
