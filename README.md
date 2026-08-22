# PilotDriven Flight Briefing

This repository retains the historical name `pilotdriven-ODSS` for continuity. The current PilotDriven product-module name is **Flight Briefing**.

Flight Briefing is the deterministic Lido CFP analysis engine for PilotDriven. It computes flight-specific findings and never substitutes model knowledge for missing operational data. Helpyou retrieves governed authoritative content. PilotDriven presents the briefing and the pilot decides.

> **Flight Briefing computes and never guesses. Helpyou retrieves and never invents. PilotDriven presents — and the pilot always decides.**

The working personal dashboard is in [`pilotdriven_odss_dashboard/`](pilotdriven_odss_dashboard/README.md).

## Current publication baseline

New pilot-facing output follows:

- [`FLIGHT_BRIEFING_PUBLICATION_PROTOCOL_V1_3.md`](docs/protocols/FLIGHT_BRIEFING_PUBLICATION_PROTOCOL_V1_3.md)
- [`flight-briefing-publication-profile-v1.3.json`](docs/protocols/flight-briefing-publication-profile-v1.3.json)
- [`BRIEFING_PUBLICATION_MEMORY_2026-08-08.md`](docs/knowledge/BRIEFING_PUBLICATION_MEMORY_2026-08-08.md)

The primary artifact is one combined PDF named:

```text
<FLIGHT>_<DDMMMYYYY>_Flight_Briefing.pdf
```

The current-facing report does not expose `Level 1`, `Level 2`, `Pertinent Brief` or `Evidence Level` labels. The full CFP is not appended or attached unless expressly requested. Page 1 places operational information on the left and the route map on the right; Departure, Destination and preferred Alternate cards use equal geometry; decision gates link to evidence; detailed text and numerics use the larger v1.3 typography baseline; and MEL/CDL, EDTO and depressurisation references use selected authoritative source crops.

The fail-closed Python publication contract is implemented in:

```text
pilotdriven_odss_dashboard/app/odss/flight_briefing_publication.py
```

## Quick start

```bash
git clone https://github.com/Easyeye123/pilotdriven-ODSS.git
cd pilotdriven-ODSS/pilotdriven_odss_dashboard
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, upload a supported Lido CFP PDF and run the deterministic analysis.

## Architecture

```text
Lido CFP
  -> Flight Briefing parser and deterministic engines
  -> canonical analysis JSON
  -> route/time/level, NOTAM, hazard, fuel, performance, EDTO,
     BOBCAT, communications, terrain, VWS and depressurisation findings
  -> combined-report plan and publication manifest
  -> PilotDriven presentation
  -> pilot decision

Controlled manuals / AIP / NOTAM / official weather
  -> Helpyou source governance and retrieval
  -> exact source crops, links and policy evidence
```

React, browser code and LLMs must not independently recalculate deterministic aviation findings.

## Mandatory hazard assessment

Every CFP review includes exact source-governed screening of available:

- SIGMET;
- tropical cyclone products;
- volcanic ash products;
- frontal weather; and
- clear-air turbulence products.

A product is promoted only when the authoritative, temporal, spatial, vertical and operational-consequence gates pass. Missing coverage remains a declared gap and is never interpreted as NIL.

## High Terrain Exposure and depressurisation

The trigger is MSA strictly greater than `100*`; exactly `100*` is a boundary. A matched profile requires route/airway/direction and aircraft-effectivity verification, flight-specific analysis and the embedded cropped authoritative chart. Unmatched exposure remains unresolved.

## Helpyou framework

The merged Helpyou baseline is documented at:

1. [`docs/helpyou/README.md`](docs/helpyou/README.md)
2. [`docs/helpyou/HELPYOU_SYSTEM_REQUIREMENTS_V1.md`](docs/helpyou/HELPYOU_SYSTEM_REQUIREMENTS_V1.md)
3. [`docs/helpyou/HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md`](docs/helpyou/HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md)
4. [`docs/helpyou/HELPYOU_DATA_CONTRACTS_V1.md`](docs/helpyou/HELPYOU_DATA_CONTRACTS_V1.md)
5. [`integration/helpyou/README.md`](integration/helpyou/README.md)

Helpyou may organise, cite and teach Flight Briefing outputs, but it must not recalculate them. Pilot memory and pilot experience remain outside the deterministic operational-evidence boundary.

## PilotDriven integration handoff

Read in order:

1. [`HANDOFF_MANIFEST.md`](HANDOFF_MANIFEST.md)
2. [`docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md`](docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md)
3. [`docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md`](docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md)
4. [`docs/helpyou/README.md`](docs/helpyou/README.md)
5. [`docs/architecture/ADR-006-realistic-map-rendering.md`](docs/architecture/ADR-006-realistic-map-rendering.md)
6. [`integration/v0.6/README.md`](integration/v0.6/README.md)

The v0.5 schematic baseline remains preserved at `archive/odss-v0.5-schematic-baseline`.

## Test

```bash
cd pilotdriven_odss_dashboard
python -m pip install -r requirements-dev.txt
python -m compileall -q app
pytest -q
```

The v1.3 regressions fail publication for prohibited labels, full-CFP attachment, reversed Page 1 scan path, unequal airport cards, undersized typography, X-shaped logo use, broken decision links, missing source crops, duplicate primary facts, incomplete hazard objects, NIL inference, text overlap, clipping and incomplete depressurisation-chart embedding.

## Authority boundary

Flight Briefing is operational decision support. Approved operator documents, current dispatch information, current aeronautical and meteorological products, ATC instructions and commander judgement remain controlling.
