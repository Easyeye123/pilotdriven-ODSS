# PilotDriven ODSS Personal Dashboard

A working local prototype for uploading Lido CFP PDFs and creating a dedicated flight workspace for each upload.

## Current functionality

- Upload a CFP PDF.
- Create a persistent flight record in SQLite.
- List recent flights on the dashboard.
- Open an individual flight workspace.
- Download the original CFP.
- Trigger a placeholder analysis job.
- Attach and download Level 1 and Level 2 PDF reports.
- Preserve the repository boundary for later PilotDriven/AWS integration.

The current **Run analysis pipeline** action validates the upload and queues the known ODSS modules. It does not yet parse the full Lido document. The deterministic parser and engines from the ODSS core are the next integration step.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Data storage

```text
data/odss.db        SQLite flight records
data/uploads/       uploaded CFP PDFs
data/reports/       attached Level 1 / Level 2 PDFs
```

## Next implementation stage

1. Connect the Lido CFP parser.
2. Persist canonical ODSS result JSON.
3. Add Overview, MEL/CDDL, NOTAM, Weather, Terrain/VWS, Depressurisation and Communications tabs.
4. Generate Level 1 and Level 2 reports automatically.
5. Add revision comparison between successive CFP uploads.
6. Replace local storage adapters with S3/Aurora adapters when merging into PilotDriven.
7. Add authentication before any internet deployment.

## Important

This prototype is not hardened for public internet deployment and does not provide operational approval. It is for personal development and validation of the ODSS workflow.
