# PilotDriven ODSS Personal Dashboard

A local FastAPI dashboard for uploading Lido CFP PDFs, running the deterministic PilotDriven ODSS engine and generating Level 1 and Level 2 reports.

## What now works

- Upload and archive Lido CFP PDFs.
- Parse the CFP section, Page 1, route log, route coordinates, BOBCAT allocation, performance, fuel, EDTO and deferred items.
- Plot an offline schematic route map from the actual waypoint coordinates contained in the Lido CFP.
- Display a dark visual briefing dashboard with:
  - flight and schedule controls;
  - PZFW, PLDW and PTOW in integer kg;
  - departure and destination airport panels;
  - the mapped CFP route and selected FIR/critical waypoint labels;
  - an enroute exceptions summary;
  - early ATC/FIR communication timing;
  - EDTO summary; and
  - pertinent enroute weather.
- Generate a fixed three-page **Level 1 pertinent brief**:
  1. visual route briefing;
  2. operational detail; and
  3. route and contingency detail.
- Include clickable Page 1 PDF links to the Page 2 airport/operational sections and Page 3 communications/EDTO/route sections.
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
- Clear stale generated artifacts before a rerun and publish replacement JSON/PDF artifacts only after generation succeeds.
- Reject duplicate analysis requests and recover interrupted runs after an application restart.
- Preserve existing SQLite records through an automatic schema migration.

## Visual route map semantics

The current route display is an offline schematic generated from the coordinates printed in the Lido CFP route log. It is intended for briefing orientation only and is **not for navigation**.

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

The regression suite covers upload validation, failed reruns, missing artifacts, NOTAM applicability and priority, route-coordinate parsing, three-page Level 1 generation, internal PDF links, visual cover output, actual takeoff anchoring, waypoint-ATA re-anchoring, personal-note CRUD and report placement.

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

The future PilotDriven frontend should consume the canonical `view.briefing` and `flight.route_waypoints` objects. It may replace the visual components and map renderer, but it should not duplicate or change deterministic operational calculations in client-side code.

The detailed implementation contract is in `../docs/visual-route-briefing-v0.5.md`.

## Reference-library limitation

The bundled MEL, communication and depressurisation entries are regression/reference abstractions derived from the current ODSS development cases. They are not a substitute for a current operator-approved MEL, CDDL, Jeppesen/AIP material or depressurisation manual. The application deliberately flags missing reference matches rather than inventing terms.

## Deployment caution

This build is intended for personal local validation. Add authentication, tenant isolation, encrypted object storage, background job processing and formal reference management before any internet deployment.
