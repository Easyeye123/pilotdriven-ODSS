# PilotDriven Flight Briefing

> **Naming:** Flight Briefing is the permanent product-facing name. The repository and selected internal identifiers retain the legacy ODSS token for compatibility.

PilotDriven aviation decision-support development repository.

The working personal dashboard is in [`pilotdriven_odss_dashboard/`](pilotdriven_odss_dashboard/README.md).

Current dashboard release: **v0.6.1** — authenticated service integration, deterministic Lido CFP analysis, a three-page landscape Level 1 brief with an additional volcanic-ash review page only when affected or unresolved, expanded Level 2 output, ATOT recalculation and canonical map/report contracts.

## Quick start

```bash
git clone https://github.com/Easyeye123/pilotdriven-ODSS.git
cd pilotdriven-ODSS/pilotdriven_odss_dashboard
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`, upload a Lido CFP PDF, create the flight workspace, and select **Run Flight Briefing analysis**.

## Flight Briefing v0.6 PilotDriven handoff

Flight Briefing v0.6 is the integration handoff for the final realistic-map standard and future combination with `pilotdriven.com`.

The v0.5 schematic baseline is preserved at:

```text
archive/odss-v0.5-schematic-baseline
```

### Repository layout

```text
pilotdriven_odss_dashboard/
  Working personal Flight Briefing application

integration/v0.6/
  Reference map contracts, render adapters, print capture,
  fallbacks, Next.js component and tests

docs/
  Architecture decisions, Phase 1–7 plan, AWS/Playwright
  runbooks, API contracts and integration guide

HANDOFF_MANIFEST.md
  File-level handoff inventory
```

## Helpyou framework

The first source-governed Helpyou product and integration baseline is documented at:

1. [`docs/helpyou/README.md`](docs/helpyou/README.md)
2. [`docs/helpyou/HELPYOU_SYSTEM_REQUIREMENTS_V1.md`](docs/helpyou/HELPYOU_SYSTEM_REQUIREMENTS_V1.md)
3. [`docs/helpyou/HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md`](docs/helpyou/HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md)
4. [`docs/helpyou/HELPYOU_DATA_CONTRACTS_V1.md`](docs/helpyou/HELPYOU_DATA_CONTRACTS_V1.md)
5. [`integration/helpyou/README.md`](integration/helpyou/README.md)

Helpyou routes Lido CFPs to Flight Briefing, keeps pilot memory outside the Flight Briefing evidence boundary, uses Axiomatic Design to structure teaching replies, and activates Endsley, Rasmussen and developmental CBTA review only when pilot reasoning is available.

### v0.6 architecture

```text
Lido CFP
  -> Flight Briefing parser and deterministic engines
  -> canonical analysis JSON
  -> map contract / route GeoJSON / marker and verified-hazard GeoJSON
  -> Amazon Location Hybrid + MapLibre
  -> Playwright PDF capture
  -> static fallback
  -> schematic offline fallback
```

The PilotDriven frontend may replace presentation and map controls. It must not independently recalculate NOTAM applicability, volcanic-ash applicability, ACTM/UTC, BOBCAT, EDTO, MSA/VWS, MEL/CDL or depressurisation findings.

### Start with Python 3.12

For normal local use:

```bash
cd pilotdriven_odss_dashboard
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For development reload, exclude `.venv`:

```bash
python -m uvicorn app.main:app \
  --reload \
  --reload-exclude ".venv/*" \
  --host 127.0.0.1 \
  --port 8000
```

### Read first for PilotDriven combination

1. [`HANDOFF_MANIFEST.md`](HANDOFF_MANIFEST.md)
2. [`docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md`](docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md)
3. [`docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md`](docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md)
4. [`docs/helpyou/README.md`](docs/helpyou/README.md)
5. [`docs/architecture/ADR-006-realistic-map-rendering.md`](docs/architecture/ADR-006-realistic-map-rendering.md)
6. [`integration/v0.6/README.md`](integration/v0.6/README.md)

## Important

Flight Briefing is operational decision support only. Approved operator documents, current dispatch information, ATC instructions and commander judgement remain controlling.
