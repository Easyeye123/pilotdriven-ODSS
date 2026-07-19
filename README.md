# PilotDriven ODSS

PilotDriven Operational Decision Support System development repository.

## Current state

- **ODSS v0.5** is the working local FastAPI dashboard.
- It parses supported Lido CFP packages, runs deterministic operational analysis, creates canonical JSON, and generates Level 1 and Level 2 reports.
- **ODSS v0.6** is the integration handoff for the final realistic-map standard and future combination with `pilotdriven.com`.

The v0.5 schematic baseline is preserved at:

```text
archive/odss-v0.5-schematic-baseline
```

## Repository layout

```text
pilotdriven_odss_dashboard/
  Working personal ODSS application

integration/v0.6/
  Reference map contracts, render adapters, print capture,
  fallbacks, Next.js component and tests

docs/
  Architecture decisions, Phase 1–7 plan, AWS/Playwright
  runbooks, API contracts and integration guide

HANDOFF_MANIFEST.md
  File-level handoff inventory
```

## v0.6 architecture

```text
Lido CFP
  -> ODSS parser and deterministic engines
  -> canonical analysis JSON
  -> map contract / route GeoJSON / marker GeoJSON
  -> Amazon Location Hybrid + MapLibre
  -> Playwright PDF capture
  -> static fallback
  -> schematic offline fallback
```

The PilotDriven frontend may replace presentation and map controls. It must not independently recalculate NOTAM applicability, ACTM/UTC, BOBCAT, EDTO, MSA/VWS, MEL/CDL or depressurisation findings.

## Start the current dashboard

```bash
git clone https://github.com/Easyeye123/pilotdriven-ODSS.git
cd pilotdriven-ODSS/pilotdriven_odss_dashboard

python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Do not use unrestricted `--reload` with an in-project `.venv`. For development:

```bash
python -m uvicorn app.main:app \
  --reload \
  --reload-exclude ".venv/*" \
  --host 127.0.0.1 \
  --port 8000
```

Use Python 3.12. Run without reload for normal use, or exclude `.venv` from the development reloader.

## Read first for PilotDriven combination

1. [`HANDOFF_MANIFEST.md`](HANDOFF_MANIFEST.md)
2. [`docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md`](docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md)
3. [`docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md`](docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md)
4. [`docs/architecture/ADR-006-realistic-map-rendering.md`](docs/architecture/ADR-006-realistic-map-rendering.md)
5. [`integration/v0.6/README.md`](integration/v0.6/README.md)

## Important

ODSS is operational decision support only. Approved operator documents, current dispatch information, ATC instructions and commander judgement remain controlling.
