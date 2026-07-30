# PilotDriven ODSS v0.6 handoff manifest

## Repository baseline

- Working dashboard baseline: ODSS v0.5
- Archived branch: `archive/odss-v0.5-schematic-baseline`
- v0.6 handoff branch: `feature/v0.6-pilotdriven-handoff`
- Helpyou framework branch: `feature/helpyou-framework-v1`

## Included source

### Existing ODSS application

```text
pilotdriven_odss_dashboard/
```

Contains the working Lido parser, deterministic engines, timing, notes, dashboard and Level 1/Level 2 generation.

### v0.6 realistic-map reference

```text
integration/v0.6/reference/
```

Contains:

- map contract;
- GeoJSON builder;
- priority-label logic;
- renderer abstraction;
- Amazon Location MapLibre adapter;
- Amazon Location static fallback;
- Playwright snapshot adapter;
- schematic fallback;
- FastAPI router;
- print-map template;
- MapLibre JavaScript/CSS;
- tests;
- optional dependencies.

### PilotDriven Next.js reference

```text
integration/v0.6/pilotdriven-nextjs/
```

Contains:

- typed ODSS map contract;
- MapLibre React component;
- dependency manifest;
- frontend integration notes.

### Helpyou policy reference

```text
integration/helpyou/
```

Contains:

- deterministic request segregation;
- cognitive activation gates;
- authoritative evidence validation;
- ODSS/pilot-memory boundary enforcement;
- compact citation rendering;
- minimum-sufficient response planning;
- regression tests.

## Included process documentation

```text
docs/architecture/ADR-006-realistic-map-rendering.md
docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md
docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md
docs/api/MAP_CONTRACT_V1.md
docs/runbooks/AWS_LOCATION_SETUP.md
docs/runbooks/PLAYWRIGHT_MAP_CAPTURE.md
docs/testing/V0_6_ACCEPTANCE_MATRIX.md
docs/helpyou/README.md
docs/helpyou/HELPYOU_SYSTEM_REQUIREMENTS_V1.md
docs/helpyou/HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md
docs/helpyou/HELPYOU_DATA_CONTRACTS_V1.md
```

## Not included

- Amazon Location API key;
- source Lido CFP packages;
- generated operational reports;
- user SQLite database;
- proprietary MEL/CDL/Jeppesen/depressurisation manuals;
- production PilotDriven authentication or billing;
- operator approval/certification.

## Handoff rule

The PilotDriven project should consume ODSS contracts and APIs. It should not reimplement deterministic aviation logic in React or client-side map code.

Helpyou may organise, cite and teach ODSS outputs, but it must not recalculate them. Pilot memory and pilot experience remain outside the ODSS operational evidence boundary.
