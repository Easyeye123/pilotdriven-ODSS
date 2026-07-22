# PilotDriven ODSS Personal Dashboard

A local FastAPI dashboard for uploading Lido CFP PDFs, running the deterministic PilotDriven ODSS engine and generating Level 1 and Level 2 reports.

## What now works

- Upload and archive Lido CFP PDFs.
- Parse the CFP section, Page 1, route log, route coordinates, BOBCAT allocation, performance, fuel, EDTO and deferred items.
- Check official NOAA Aviation Weather Center international SIGMET data for positive volcanic-ash route/time/flight-level intersections, retain source provenance, and fail closed to manual review when complete flight coverage cannot be proven.
- Plot an offline contextual route map using the actual waypoint coordinates contained in the Lido CFP over a bundled Natural Earth 1:110m land layer.
- Display a dark visual briefing dashboard with:
  - flight and schedule controls;
  - PZFW, PLDW and PTOW in integer kg;
  - departure and destination airport panels;
  - the mapped CFP route and selected FIR/critical waypoint labels;
  - an enroute exceptions summary;
  - early ATC/FIR communication timing;
  - EDTO summary; and
  - pertinent enroute weather.
- Generate a three-page landscape **Level 1 pertinent brief** with a mapped summary cover, colour-coded operational detail and route/contingency review, plus a fourth volcanic-ash page only for an affected or unresolved assessment.
- Start the **Level 2 expanded report** with the same visual briefing cover, followed by the complete deterministic analysis and warnings.
- Store a canonical `view.briefing` object in the analysis JSON so the current dashboard, PDF renderer and future PilotDriven frontend share the same facts.
- Detect continuous MSA greater than `100*` events and VWS greater than 4 events.
- Match the bundled route-aware depressurisation profiles and early FIR-contact rules when applicable.
- Extract weather and airport NOTAM records without silently truncating the airport list.
- Evaluate NOTAM B/C validity and supported Item D daily, weekday, date-list, month-range and overnight schedules against airport-specific operational windows.
- Keep unsupported Item D schedules visible for manual review instead of guessing applicability.
- Keep critical destination and alternate NOTAMs in Level 1 while retaining the complete active/review set in Level 2.
- Save the canonical analysis result as JSON and display organised findings in the flight workspace.
- Enter an **actual takeoff time (ATOT)** or an **actual waypoint ATA** and calculate:
  - pertinent event UTCs;
  - early ATC/FIR call UTCs;
  - FIR crossing UTCs;
  - all route-waypoint calculated ATA/UTC values;
  - date rollover and delay against scheduled departure.
- Re-anchor the route in flight by entering a known waypoint ATA; the engine derives ATOT as `waypoint ATA - waypoint ACTM`.
- Retain ACTM as the source elapsed-time value. Absolute UTC is always calculated as `derived ATOT + CFP ACTM`.
- Add, edit and delete **personal pilot notes** for each flight.
- Place each personal note in one of four report locations:
  - a separate personal-notes section;
  - the departure-airport section;
  - the destination-airport section;
  - the enroute ATC/communications section.
- Select whether each note appears in Level 1, Level 2, or both reports.
- Regenerate analysis JSON and both PDF reports automatically when an included personal note or timing reference changes.
- Reject unreadable, password-protected, empty, oversized and incomplete CFP uploads with controlled errors.
- Keep the last completed JSON/PDF artifacts available while a rerun is in progress or if replacement generation fails.
- Reject duplicate analysis requests and recover interrupted runs after an application restart.
- Preserve existing SQLite records through an automatic schema migration.

## Visual route map semantics

The default route display is generated offline from the coordinates printed in the Lido CFP route log over a bundled Natural Earth 1:110m land layer. It provides recognisable coastline context without pretending to be an aeronautical chart. It is intended for briefing orientation only and is **not for navigation**.

The map renderer is deliberately separated from the canonical route/briefing model. When this ODSS module is incorporated into the wider PilotDriven project, the renderer can be replaced by MapLibre, Mapbox or an approved aeronautical map service without rewriting the deterministic aviation engines.

## Run locally

```bash
cd pilotdriven_odss_dashboard
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

For source-code development with automatic reload, exclude the in-project virtual environment so WatchFiles does not repeatedly restart while packages are installed:

```bash
python -m uvicorn app.main:app --reload --reload-exclude ".venv/*"
```

Uploads are limited to 25 MB and 180 PDF pages. The current parser accepts the supported Lido CFP layout only; a readable PDF that lacks its required route, fuel or mass fields fails analysis instead of producing zero-filled operational results.

Python 3.12 is the supported local and container runtime. After pulling this upgrade, recreate or upgrade the virtual environment because the framework, upload parser and PDF libraries include reliability and security updates.

## Personal notes workflow

1. Open the flight workspace.
2. In **Personal notes**, select the report placement.
3. Enter the note text, up to 2,000 characters.
4. Select Level 1, Level 2, or both.
5. Select **Add personal note**.
6. Use **Edit note** or **Delete note** for later changes.

Notes may be entered before or after CFP analysis. When reports already exist, any note change automatically reruns the analysis and replaces Level 1, Level 2 and canonical JSON artifacts. Notes are stored separately from the system processing-status text.

Every PDF note panel is labelled as pilot-entered personal content. The ODSS engine does not treat personal notes as extracted or validated operational findings.

## Operational clock workflow

1. Upload the Lido CFP and run the ODSS analysis.
2. Open the flight workspace.
3. In **Actual-time operational clock**, select either:
   - **Actual takeoff time (ATOT)**; or
   - **Actual waypoint ATA**.
4. Enter the UTC date and UTC time.
5. For waypoint ATA mode, select the route waypoint.
6. Select **Save time and recalculate UTC table**.

The timing entry is required only for absolute UTC calculations. The preflight analysis can still run in ACTM-only mode before takeoff. Saving or changing the timing reference automatically regenerates the analysis JSON and both PDF reports.

The dashboard labels all route values as **calculated waypoint ATA/UTC**. They are not presented as pilot-recorded actual crossing times unless the waypoint itself was used as the entered ATA reference.

## Upgrade an existing local clone

Stop the running server with `Ctrl+C`, then:

```bash
git pull origin main
cd pilotdriven_odss_dashboard
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Your existing SQLite flight records are retained. Open each existing flight and select **Run analysis again** to parse route coordinates, rebuild the canonical visual briefing model and generate the new visual PDFs.

## Test locally

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m compileall -q app
pytest -q
```

The regression suite covers upload validation, failed reruns, last-known-good artifacts, NOTAM applicability and priority, route-coordinate parsing, conditional three/four-page Level 1 generation, volcanic-ash time/level/geometry and antimeridian checks, visual output, actual takeoff anchoring, waypoint-ATA re-anchoring, personal-note CRUD and report placement.

GitHub Actions also generates Level 1 and Level 2 visual sample PDFs as build artifacts for visual inspection.

## Data storage

```text
data/odss.db        SQLite flight records, timing references and personal notes
data/uploads/       uploaded CFP PDFs
data/results/       structured ODSS JSON results
data/reports/       generated Level 1 / Level 2 PDFs
```

Set `ODSS_DATA_DIR` to move all four paths to a writable deployment volume. Render's free web-service filesystem is ephemeral, so a free boss-demo instance loses uploaded flights when it is restarted or redeployed. Attach a persistent disk and point `ODSS_DATA_DIR` at its mount path before relying on saved flight history.

## Limited boss QA deployment

An internet-facing instance must set both `ODSS_USERNAME` and `ODSS_PASSWORD`. The dashboard then requires HTTP Basic authentication on every page and file download while leaving `/healthz` public for hosting health checks. Startup fails if only one credential is configured.

This protects a single-user demonstration but does not turn the personal dashboard into a production multi-user aviation system. Keep the deployment limited to authorised synthetic or approved QA CFPs until tenant isolation, encrypted object storage, background processing and formal reference governance are implemented.

## PilotDriven integration boundary

The PilotDriven frontend consumes ODSS through the authenticated `/v1` service boundary. It may replace visual components and the map renderer, but it must not duplicate or change deterministic operational calculations in client-side code.

The detailed v0.5 implementation contract is in `../docs/visual-route-briefing-v0.5.md`.

## ODSS v0.6 PilotDriven handoff

The complete Phase 1–7 reference implementation is under:

```text
../integration/v0.6/
```

It contains:

- versioned map contract;
- route and marker GeoJSON;
- stable route hash;
- marker roles and label priorities;
- verified volcanic-ash hazard GeoJSON;
- Amazon Location Hybrid / MapLibre adapter;
- Playwright PDF map capture;
- Amazon Location static fallback;
- schematic offline fallback;
- FastAPI map endpoints;
- print-map HTML/JavaScript/CSS;
- React/Next.js PilotDriven component;
- contract tests and runbooks.

Read:

```text
../HANDOFF_MANIFEST.md
../docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md
../docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md
../docs/architecture/ADR-006-realistic-map-rendering.md
```

Install the optional map dependencies:

```bash
python -m pip install -r ../integration/v0.6/reference/requirements-map.txt
python -m playwright install chromium
```

Copy `.env.example` to `.env` and configure the Amazon Location key. The realistic map remains disabled until that key and the MapLibre/Playwright integration are configured. The schematic map remains the explicitly labelled final fallback.

Run the v0.6 reference tests:

```bash
cd ../integration/v0.6/reference
PYTHONPATH=. pytest -q
```

## Reference-library limitation

The bundled MEL, communication and depressurisation entries are regression/reference abstractions derived from the current ODSS development cases. They are not a substitute for a current operator-approved MEL, CDDL, Jeppesen/AIP material or depressurisation manual. The application deliberately flags missing reference matches rather than inventing terms.

Every bundled reference match is labelled `manual-review` in the analysis output and dashboard. It must remain a candidate finding until an authorised current reference library is supplied and governed.

## NOTAM operating windows

The engine evaluates destination and alternate NOTAMs against a configurable product window of ETA plus or minus two hours by default. Departure uses plus or minus one hour by default. These are briefing-policy windows, not an aviation-standard claim. Override them with `ODSS_NOTAM_ARRIVAL_WINDOW_MINUTES` and `ODSS_NOTAM_DEPARTURE_WINDOW_MINUTES` when an approved product policy changes.

## Deployment caution

This build is intended for personal local validation. Add authentication, tenant isolation, encrypted object storage, background job processing and formal reference management before any internet deployment.

## Authoritative v0.6 service API

The integrated service boundary is versioned under `/v1`. PilotDriven calls it
with `Authorization: Bearer <ODSS_SERVICE_TOKEN>` and supplies tenant/user
context only from its trusted backend-for-frontend layer.

```text
POST /v1/analyses
GET  /v1/analyses/{id}
GET  /v1/analyses/{id}/briefing
GET  /v1/analyses/{id}/map-contract
GET  /v1/analyses/{id}/route.geojson
GET  /v1/analyses/{id}/markers.geojson
GET  /v1/analyses/{id}/hazards.geojson
GET  /v1/analyses/{id}/map-config
GET  /v1/analyses/{id}/map-fallback
POST /v1/analyses/{id}/timing
POST /v1/analyses/{id}/reports/render
GET  /v1/analyses/{id}/reports/level-1
GET  /v1/analyses/{id}/reports/level-2
```

ODSS remains authoritative for CFP parsing and all deterministic aviation
calculations. The browser renders the returned briefing and GeoJSON; it does
not recompute NOTAM or volcanic-ash applicability, MEL/CDL/CDDL, performance, BOBCAT, EDTO,
ACTM/UTC, communications, terrain, VWS or depressurisation findings.

## Playwright report worker

After an analysis has completed, capture the canonical MapLibre route map and
refresh the Level 1 and Level 2 reports with:

```bash
python -m app.odss_map_v06.report_worker <analysis-id>
```

The worker uses this explicit hierarchy:

```text
Amazon Location Hybrid + Playwright
  -> Amazon Location static Satellite map
  -> labelled schematic fallback
```

A map downgrade is recorded in the analysis JSON under `view.map_render` and
is never presented silently. The dashboard, captured map and PDFs share the
same stored map contract and route hash.

## SQ303 / SQ304 golden regression cases

The proprietary CFP fixtures are not stored in the repository. Run the full
operational and route-hash regressions by supplying authorised local copies:

```bash
python scripts/run_v06_golden_regressions.py \
  --sq303 "/secure/path/SQ303.pdf" \
  --sq304 "/secure/path/SQ304.pdf" \
  --output /tmp/odss-v06-golden
```

The regression verifies the exact authorised fixture checksums, direction,
mass values, route ordering/hash, report creation, SQ303 high-terrain/EDTO/
communication results and SQ304 BOBCAT/EDTO values. The current SQ304 fixture
has no governed depressurisation profile match, so the expected result is an
explicit manual chart-index review rather than an invented profile. CI may opt in with
`ODSS_GOLDEN_SQ303_CFP` and `ODSS_GOLDEN_SQ304_CFP`; otherwise that test is
explicitly skipped.
