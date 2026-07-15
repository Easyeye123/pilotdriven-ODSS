# PilotDriven ODSS Personal Dashboard

A local FastAPI dashboard for uploading Lido CFP PDFs, running the deterministic PilotDriven ODSS engine and generating Level 1 and Level 2 reports.

## What now works

- Upload and archive Lido CFP PDFs.
- Parse the CFP section, Page 1, route log, BOBCAT allocation, performance, fuel, EDTO and deferred items.
- Detect continuous MSA greater than `100*` events and VWS greater than 4 events.
- Match the bundled route-aware depressurisation profiles and early FIR-contact rules when applicable.
- Extract selected weather and operationally pertinent airport NOTAM records.
- Generate and download Level 1 and Level 2 PDF reports automatically.
- Save the canonical analysis result as JSON and display organised findings in the flight workspace.
- Preserve existing SQLite records through an automatic schema migration.

## Run locally

```bash
cd pilotdriven_odss_dashboard
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

After pulling this upgrade, reinstall the requirements because PyMuPDF and ReportLab are now required.

## Upgrade from v0.1

```bash
git pull
cd pilotdriven_odss_dashboard
.venv\Scripts\activate          # Windows
pip install --upgrade -r requirements.txt
uvicorn app.main:app --reload
```

Your existing SQLite flight records are retained. Open the flight workspace and select **Run ODSS analysis**. Successful processing changes the status to **Completed** and creates Level 1, Level 2 and analysis JSON download buttons.

## Data storage

```text
data/odss.db        SQLite flight records
data/uploads/       uploaded CFP PDFs
data/results/       structured ODSS JSON results
data/reports/       generated Level 1 / Level 2 PDFs
```

## Reference-library limitation

The bundled MEL, communication and depressurisation entries are regression/reference abstractions derived from the current ODSS development case. They are not a substitute for a current operator-approved MEL, CDDL, Jeppesen/AIP material or depressurisation manual. The application deliberately flags missing reference matches rather than inventing terms.

## Deployment caution

This build is intended for personal local validation. Add authentication, tenant isolation, encrypted object storage, background job processing and formal reference management before any internet deployment.
