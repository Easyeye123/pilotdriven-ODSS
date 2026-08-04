# Helpyou Flight Discussion Test Bed v0.1

This is a separate, browser-based prototype for a pilot to:

- discuss a CFP-grounded flight scenario;
- explain a decision in their own words;
- receive one material facilitator question at a time;
- view a concise source-grounded teaching response;
- inspect selective Endsley, Rasmussen and developmental CBTA observations;
- teach Helpyou through pilot experience, corrections, techniques and source references;
- review and delete the resulting private pilot-memory record;
- export the complete session as JSON for adversarial review.

## Product boundaries

- **Flight Briefing** owns the Lido CFP, weather, NOTAM, timing and deterministic flight baseline.
- The test bed consumes the immutable SQ23 golden fixture; it does not parse or recalculate the CFP.
- The SQ23 case is fixed as stable OEI. Fire, smoke, severe damage or another failure requires a separate controlled case.
- Pilot wording and Helpyou interpretation are stored separately.
- Pilot knowledge remains `pilot_reported`; it never becomes Flight Briefing evidence without independent source verification.
- The prototype is a discussion and teaching aid, not a formal operator LOFT or competency assessment.

## Run

From the repository root:

```bash
python -m pip install -r pilotdriven_odss_dashboard/requirements.txt
PYTHONPATH=integration/helpyou python -m testbed
```

Open:

```text
http://127.0.0.1:8010
```

Optional environment variables:

```text
HELPYOU_TESTBED_HOST
HELPYOU_TESTBED_PORT
HELPYOU_TESTBED_DB
```

## Test

```bash
PYTHONPATH=integration/helpyou pytest -q integration/helpyou/testbed/tests
```

The SQLite database is created under `integration/helpyou/testbed/data/` by default and is excluded from source control except for `.gitkeep`.
