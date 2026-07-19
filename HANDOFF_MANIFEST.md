# PilotDriven ODSS v0.6 handoff manifest

## Repository baseline

- Working dashboard baseline: ODSS v0.5
- Archived branch: `archive/odss-v0.5-schematic-baseline`
- v0.6 handoff branch: `feature/v0.6-pilotdriven-handoff`

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

## Included process documentation

```text
docs/architecture/ADR-006-realistic-map-rendering.md
docs/handoff/PHASES_1_TO_7_IMPLEMENTATION.md
docs/handoff/PILOTDRIVEN_COMBINATION_GUIDE.md
docs/api/MAP_CONTRACT_V1.md
docs/runbooks/AWS_LOCATION_SETUP.md
docs/runbooks/PLAYWRIGHT_MAP_CAPTURE.md
docs/testing/V0_6_ACCEPTANCE_MATRIX.md
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
