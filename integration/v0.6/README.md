# PilotDriven ODSS v0.6.1 integration handoff

This directory contains the reference source and documentation required to implement Phases 1–7 of the realistic-map upgrade and combine ODSS with the wider `pilotdriven.com` project.

## Contents

```text
reference/
  odss_map_v06/          Python map contract and render adapters
  templates/             print-map HTML
  static/                MapLibre JavaScript/CSS
  tests/                 contract regression tests
  requirements-map.txt   optional map/screenshot dependencies
pilotdriven-nextjs/
  components/            React/Next.js map component
  lib/                   TypeScript contract types
```

## Status

- ODSS v0.5 remains the current functional baseline.
- The v0.6 code is an integration-ready reference slice.
- A live realistic map requires an Amazon Location API key.
- The Playwright browser must be installed for primary PDF capture.
- Static and schematic fallbacks are mandatory.
- Map contract 1.1 adds source-derived volcanic-ash hazard GeoJSON. Empty or
  unresolved assessments never invent a polygon.

## FastAPI integration

1. Add `integration/v0.6/reference` to the Python package path or publish it as an internal package.
2. Install `requirements-map.txt`.
3. Copy/link the print template and static assets.
4. Create a loader that retrieves the canonical analysis by ID.
5. Mount the router from `odss_map_v06.api`.
6. Expose map contract/config endpoints.
7. Add the renderer chain to the report worker.

Example:

```python
from odss_map_v06.api import create_map_router
from odss_map_v06.config import MapSettings

settings = MapSettings.from_env()
app.include_router(
    create_map_router(
        load_analysis=analysis_store.get,
        templates=templates,
        settings=settings,
    )
)
```

## PilotDriven integration

Use the Next.js reference component as a starting point. PilotDriven should consume the ODSS API; it must not copy the deterministic aviation rules into the browser.

## Validation

```bash
cd integration/v0.6/reference
python -m pip install -e .
pytest
```

Then run the existing dashboard suite and the SQ303/SQ304 golden cases.
