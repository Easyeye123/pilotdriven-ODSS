# PilotDriven ODSS

PilotDriven Operational Decision Support System development repository.

The working personal dashboard is in [`pilotdriven_odss_dashboard/`](pilotdriven_odss_dashboard/README.md).

Current dashboard release: **v0.5.0** — functional Lido CFP parsing, deterministic ODSS analysis, structured JSON output, visual route briefing, and automatic Level 1 / Level 2 PDF generation.

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

Open `http://127.0.0.1:8000`, upload a Lido CFP PDF, create the flight workspace, and select **Run ODSS analysis**.
